# FortiGate search (incident-investigation)

Use this whenever a workflow asks the firewall a question about one host: what page made a
lookup, what happened after a connection, whether a host moved data. The SentinelOne
network-STAR check ("find what made the connection, then what followed") and generic G3/G5
both land here. Everything runs on `ACCOUNT` only.

## The two tables answer different questions

| Table | Rows | Has | Does **not** have | Answers |
|---|---|---|---|---|
| `NetworkFortigateEvent` | `type=utm` (web filter, app control, IPS…) and `type=event` | `hostname`, `url`, `srcip`, `dstip`, `subtype`, `action` | byte counts | **which sites** the host reached: the trigger |
| `NetworkFortigateTraffic` | session logs | `srcip`, `srcport`, `dstip`, `dstport`, `sessionid`, `devname`, `sentbyte`, `rcvdbyte`, `duration`, `action`, `logid` | **`hostname` (no such column)** | **how much and how often**: the aftermath |

- **`hostname` exists only on `NetworkFortigateEvent`.** Projecting it on
  `NetworkFortigateTraffic` returns null on every row, because the column is not in that
  schema (step 4's "a column that does not exist returns null"). That null says nothing
  about web-filter visibility. Ask the Event table for names and the Traffic table for
  sessions, and join the two on `srcip` + `dstip` + time.
- **Both are KQL-only** (typed schemas): `lake_search` cannot read them. The time column is
  `TimeGenerated` on both; `timestamp` is empty.
- **A domain can be missing from the web filter while its sessions are in Traffic.** The web
  filter logs what its profile inspects, and a request that carries no inspected host is not
  logged by name. So "the domain is not in `NetworkFortigateEvent`" is not "the host never
  connected". Check Traffic on the resolved addresses before writing any negative.

## Three traps in Traffic that inflate every number

1. **Each flow can be logged by more than one FortiGate.** An internal firewall and a
   perimeter firewall (or an HA pair reporting separately) each log the same flow with their
   own `sessionid`, `devname` and near-identical bytes, milliseconds apart. Counting
   `sessionid`s or summing rows doubles everything. The flow key is the client side:
   **`srcip` + `srcport` + `dstip` + `dstport`**. Collect `make_set(devname)` to see how
   many devices logged it.

   **That key holds only when no firewall before the last one translates the source.**
   Firewalls in series each log their own hop: an internal firewall logs workstation VLAN
   → core with no NAT (`trandisp: noop`), and the perimeter firewall logs core → internet
   link with `snat` to the public address in `transip` / `transport`. Traffic that stays
   inside crosses only the internal firewall and is logged once, so `devices` varies
   per flow. Before trusting the client-side key, read one flow's rows in full
   (`devname`, `srcintf`/`dstintf`, their `*intfrole`, `trandisp`, `transip`,
   `transport`). If the first hop already changes `srcip` or `srcport`, the copies will
   not group. Then count on one device: for internet traffic, the one whose
   `dstintfrole` is `wan` and whose `transip` is the site's egress address. The
   perimeter row is also the one whose `transip` matches an agent's reported external
   IP.
2. **Byte columns are cumulative.** `sentbyte` / `rcvdbyte` are running totals per session,
   repeated on every periodic update (`logid 0000000020`) and on the close record. Never
   `sum()` them across rows (see the `fortigate-bandwidth` skill). Per flow, take
   **`max()`**: that is the session's total. For bandwidth across many sessions, use the
   `fortigate-bandwidth` delta rule instead.
3. **`action` is not one-row-per-session.** `accept` rows are periodic updates of a live
   session; `close`, `timeout`, `server-rst`, `client-rst` end it. Counting `accept` rows
   counts updates, not connections.

A session count or byte total that ignored any of these is wrong by a multiple.

## Size and pacing

These are among the largest tables on an account. A one-hour Traffic window has read
several GB, and a 30-day domain search has failed outright when the lake search pool ran
out of capacity. The reply's `total` / `totalBytes` is the scan size, whatever the `where`
clause keeps.

- Window: **the event ± 1 minute** for the trigger, **the event to + 60 minutes** for the
  aftermath. Never a day, never 30 days.
- One FortiGate query at a time (SKILL.md "Run scans of big tables one at a time").
- A failed scan is a gap. Retry it once on its own; do not widen it.

## F1 — The trigger: what was the host doing at that second?

Run `assets/queries/fw_trigger_hosts.kql` with `{SRCIP}` = the host's address at the time
(the SentinelOne activity's `agentipv4`, not the live record's) and `{T0}` = the raw event
time (the activity's `eventtime`, not the alert's `detectedAt` or a summary bucket).

Read the rows in time order:

- **A burst** in the seconds around `{T0}`: a site's own hosts plus its ad, analytics,
  consent and CDN hosts. The lookup came from a page the user opened. Name the site from
  the first-party hosts in the burst.
- **Ad-verification or bidding hosts only**, no first-party page load: an ad slot on a page
  that was already open refreshed. Same cause, later.
- **Nothing around `{T0}`** while F3 shows the host had traffic: the request did not come from
  a page. Look at extensions, push notifications and non-browser processes. That is a
  different case.
- **Nothing at all**, F3 included: no firewall visibility for the host at that time (off
  network, VPN split tunnel, home). It is a gap, not a negative.

**When the alert recurs** (the same domain on several days), anchor F1 on more than one
occurrence: the first, the ticket's own, and one in between. Every anchored occurrence
showing the same site is the finding. Say how many occurrences were checked out of how
many, and call the rest unverified.

## F2 — The aftermath: what followed the connection?

Run `assets/queries/fw_aftermath_sessions.kql` with `{SRCIP}`, `{T0}` and `{IPS}` = every
address in the lookup's `dnsresponse` (for a CNAME answer, the addresses after the CNAME).
One row per flow, already deduplicated across devices.

| Shape | Reading |
|---|---|
| A few flows within minutes of `{T0}`, kilobytes each, then nothing | A page load |
| Flows at a fixed interval to the end of the window | A beacon: escalate |
| One flow with `sent` far above `rcvd`, or megabytes up | Exfiltration shape: escalate |
| Long `dur` with steady small transfers | A held connection (push, websocket): find out what holds it |

**Shared CDN addresses are not indicators.** CDN-fronted domains share addresses with
unrelated sites. A flow to the address is a flow to the CDN, so attribute it to the
domain only near `{T0}`.

## F3 — The control: can this query see a large transfer from this host?

Run `assets/queries/fw_host_sessions_control.kql` with the same `{SRCIP}` and `{T0}`. It
counts every flow from the host in the aftermath window and lists the largest ones. Two
uses:

- **Visibility.** Flows exist, so the host was behind the firewall and F2's result is a
  measurement. Zero flows means F2's zero is a gap.
- **Scale.** The host's own largest flows (a backup job, a sync client) are the yardstick
  for "small". "No transfer over N KB" is only a negative next to a flow from the same host
  that is far larger.

## What goes in the closure

- The trigger site, the occurrences checked out of the total, and the table it came from.
- The aftermath as flows (not rows or session ids), bytes up and down from `max()`, first
  and last time, and how many devices logged each flow.
- F3's flow count and largest flow as the control.
- Each gap: a domain absent from the web filter by name, occurrences not anchored, no
  visibility.
