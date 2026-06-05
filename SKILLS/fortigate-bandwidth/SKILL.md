---
name: fortigate-bandwidth
description: >
  Correctly calculate FortiGate traffic bandwidth (bytes sent/received, top talkers, data
  volume) from NetworkFortigateTraffic / fortigatetraffic data in the Ingext datalake. ALWAYS
  apply these rules whenever a KQL query, FPL report, dashboard, or summary sums or ranks
  FortiGate sentbyte/rcvdbyte/sentpkt/rcvdpkt — e.g. "top talkers", "bandwidth by srcip",
  "data usage per host", "busiest IPs", "traffic volume". FortiGate byte fields are CUMULATIVE
  session counters, so a naive sum() massively over-counts; the per-interval deltas in _fields
  must be used instead. This knowledge should fire before writing or running any FortiGate
  traffic aggregation, including when reached indirectly through ingext-kql, fluency-report, or
  fpl-report-builder.
---

# FortiGate Bandwidth Calculation

How to correctly compute bytes / bandwidth from FortiGate traffic logs
(`NetworkFortigateTraffic` schema, or any `fortigatetraffic`-style index) in the
Ingext datalake. Apply these rules to any aggregation of FortiGate byte/packet
counters — KQL queries, FPL reports, dashboards, or written summaries.

## The core problem: cumulative counters

FortiGate's `sentbyte`, `rcvdbyte`, `sentpkt`, and `rcvdpkt` are **cumulative
running totals for the session**, not the bytes for that single log record. For
long-lived sessions FortiGate emits periodic log lines, and **each line repeats
the cumulative total to date**.

Therefore `summarize sum(sentbyte)` **double-counts** — it re-adds the running
total on every periodic record. A single multi-day session can inflate an hourly
total to petabytes.

### Telltale signs of a bad (cumulative) value

- A single source IP whose total dwarfs everything else by orders of magnitude
  (e.g. PB while everyone else is in MB/GB).
- `bytes / packets` works out to **megabytes per packet** — physically
  impossible (real packets max ~65 KB). Compute `sentbyte/sentpkt` as a sanity
  check; multi-MB/packet means the byte field is cumulative or corrupt.
- The same 5-tuple (`srcip:srcport -> dstip:dstport`) repeating across many
  records with a steadily growing `duration` and monotonically increasing
  `sentbyte`/`sentpkt`.

## logid 0000000020 = periodic session updates

Log ID `0000000020` is the FortiGate "traffic forward" **periodic session
update**. These are the high-volume records that repeat cumulative counters.
They dominate the index by record count and are the main source of inflation.

## The fix: use per-interval deltas from _fields

There are **no top-level delta columns**. The per-interval deltas live inside the
`_fields` dynamic JSON bag (it carries the `kusto_dynamic_json` hint). On records
that have them, `_fields` contains:

- `sentdelta` — bytes sent since the previous log line
- `rcvddelta` — bytes received since the previous log line
- `sentpktdelta`, `rcvdpktdelta`, `durationdelta` — packet / duration deltas

These deltas are the **correct per-record values to sum**.

### Important caveats

- **They are stored as strings** (e.g. `"2087"`) — wrap in `tolong()` before
  summing.
- Access via `_fields.sentdelta` / `_fields.rcvddelta`.
- **Not every record has them.** A session-close record may carry only the
  cumulative `sentbyte`/`rcvdbyte`, which in that case IS the true session total.

## The canonical pattern

Prefer the delta when present; fall back to the cumulative byte only when there
is no delta. Use `coalesce`:

```kql
NetworkFortigateTraffic
| where TimeGenerated > ago(1h)
| where logid != "0000000020"
| extend sent = coalesce(tolong(_fields.sentdelta), sentbyte),
         rcvd = coalesce(tolong(_fields.rcvddelta), rcvdbyte)
| summarize event_count = count(),
            total_sentbyte = sum(sent),
            total_rcvdbyte = sum(rcvd) by srcip
| extend total_bytes = total_sentbyte + total_rcvdbyte
| top 10 by total_bytes desc
```

Notes on the pattern:

- `coalesce(tolong(_fields.sentdelta), sentbyte)` — delta first, cumulative byte
  as fallback. This matters beyond the obvious periodic logs: many other logids
  also carry cumulative counters, and the coalesce silently corrects them.
- Filtering `logid != "0000000020"` drops the noisiest periodic-update records.
  If you instead WANT long-lived-session bandwidth included, do NOT drop
  `0000000020` — keep it and rely on its `sentdelta`/`rcvddelta` (those records
  reliably carry deltas). Choose one approach consistently.
- Swap `srcip` for `dstip`, `app`, `service`, `dstport`, etc. to re-pivot.
- For "most sent" vs "most received" rankings, order by `total_sentbyte` or
  `total_rcvdbyte` separately.

## Worked validation (why this matters)

Real example from a live tenant, top talkers over one hour:

- Naive `sum(sentbyte)` ranked `10.31.170.2` at ~15.62 PB — actually one 102-day
  VoIP (SIP/UDP 5060) session logged 28 times with a cumulative (and corrupt:
  multi-MB/packet) counter.
- Naive `sum(sentbyte)` also ranked `10.240.80.2` at ~21.86 GB — but 16 of its 56
  records carried cumulative counters. With deltas applied, its true traffic was
  ~1.34 MB, dropping it out of even the top 100.

## Checklist before reporting FortiGate bandwidth

1. Never `sum()` raw `sentbyte`/`rcvdbyte` across session logs.
2. Use `coalesce(tolong(_fields.sentdelta), sentbyte)` (and the rcvd analog).
3. Decide deliberately whether to include or exclude `logid 0000000020`.
4. Sanity-check the top result's bytes-per-packet ratio; flag multi-MB/packet.
5. State the time window; FortiGate volume is meaningless without it.
