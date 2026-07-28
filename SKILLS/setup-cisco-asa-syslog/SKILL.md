---
name: setup-cisco-asa-syslog
version: 1.0.0
description: >-
  Set up Cisco ASA (Cisco Secure Firewall ASA) event import into Fluency / Ingext via syslog. The
  agent performs the whole Fluency side itself: it resolves the site's syslog endpoint via the
  syslog MCP calls — syslog_get_config to read the existing transport, syslog_register_config to
  create it if the site has none (once per site, ever), syslog_update_config to enable the listener
  the ASA will use — and installs the "Cisco ASA Syslog" connector (CiscoASAFWLog). The ASA side is
  a real device runbook: logging enable / logging host / logging trap / logging permit-hostdown in
  the CLI, or Configuration → Device Management → Logging in ASDM, ending in write memory. The ASA
  supports UDP, TCP and secure (SSL/TLS) syslog; TLS is preferred, and the platform CA certificate
  is imported into a trustpoint with crypto ca trustpoint / crypto ca authenticate. CRITICAL:
  with TCP or TLS syslog the ASA by default BLOCKS ALL NEW CONNECTIONS through the firewall when
  the syslog server is unreachable (%ASA-3-201008) — logging permit-hostdown must be considered
  before recommending TCP/TLS. SELF-CONTAINED: it ends by creating the connector itself — when
  routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers: "connect
  our Cisco ASA to Ingext", "forward ASA firewall logs to Fluency", "ASA syslog into the datalake",
  "set up the Cisco ASA connector", "ingest ASA VPN and firewall events". Do NOT use for other
  syslog vendors (Cisco Meraki is setup-cisco-meraki-syslog; Peplink is setup-peplink-syslog;
  FortiGate is setup-fortigate-syslog; Palo Alto is setup-paloalto-syslog; SonicWall is
  setup-sonicwall-syslog; Check Point is setup-checkpoint-syslog; Sophos is
  setup-sophos-firewall-syslog or setup-sophos-utm-syslog), and not for
  Firepower / FTD managed by FMC, whose logging is configured in the
  management centre rather than on the ASA itself.
---

# Set up Cisco ASA syslog import

Import a **Cisco ASA / Cisco Secure Firewall ASA**'s system log — connection build/teardown, ACL
hits and denies, VPN events, admin activity, failover — into Fluency / Ingext via **syslog**.
Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`CiscoASAFWLog`** ("Cisco ASA Syslog"), which parses
  the ASA stream.
- **ASA side (customer's firewall):** a genuine device runbook — CLI or ASDM — covering what to
  send, at what severity, over which transport, and how to persist it.

**Transport, verified:** the ASA supports **UDP** (default, port 514), **TCP** (default port
1470) and **secure syslog over SSL/TLS** (the `secure` keyword — TCP only; an error occurs if you
try it with UDP). **Prefer TLS.** But read the box below first — on the ASA, TCP-family transports
carry an outage mode that UDP does not. Citations live in `assets/references.md`.

> ### ⚠️ Read before choosing TCP or TLS on an ASA
>
> Cisco: *"If you specify TCP, when the ASA discovers syslog server failures, for security
> reasons, new connections through the ASA are blocked."* And for secure logging: *"A secure
> logging connection can only be established with an SSL/TLS-capable syslog server. If an SSL/TLS
> connection cannot be established, all new connections will be denied."*
>
> This is not a logging degradation — **the firewall stops passing new traffic**, and logs
> `%ASA-3-201008: Disallowing new connections.` Since 8.3(2) the same block also triggers when the
> **logging queue fills up**, not only when the server is down. It is deliberate (Common Criteria
> EAL4+), and Cisco's own guidance is: *"Unless required, we recommended allowing connections when
> syslog messages cannot be sent or received."*
>
> The escape hatch is **`logging permit-hostdown`** (default: off), which "makes the status of a
> TCP-based syslog server irrelevant to new user sessions". **Configure it before, or in the same
> change as, the TCP/TLS `logging host` line** — never after.
>
> **Put this decision to the customer explicitly**, before configuring anything: encrypted
> transport with `logging permit-hostdown` (traffic keeps flowing, syslog can silently gap), or
> UDP (no outage mode, no encryption), or encrypted transport *without* `permit-hostdown` if a
> compliance regime genuinely requires fail-closed logging. Do not pick for them.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. Enable the listener this ASA will use (`syslog_tls` preferred, else `syslog_udp` / `syslog_tcp`) with `syslog_update_config` if missing |
| Ingext | Connector | Template **`CiscoASAFWLog`** ("Cisco ASA Syslog"), instance e.g. `ciscoasafwlog`, parameters `datalake` (default `managed`) and `index` (default `CiscoASA`) |
| ASA | Logging configuration | `logging enable`, a `logging host` entry, `logging trap <severity>`, `logging timestamp`, and — for TCP/TLS — `logging permit-hostdown`, persisted with `write memory` |
| ASA | (TLS only) CA trustpoint | The platform CA certificate imported into a trustpoint via `crypto ca trustpoint` + `crypto ca authenticate` |

Nothing here is billable on either side. Volume is controlled by `logging trap` severity and,
optionally, a message list — see Step 3.4.

---

## Prerequisites

- **Privileged (enable/config) access to the ASA** — CLI over SSH/console, or ASDM. Per §3.3 of
  the rollout spec this is **guide-only by default**: the agent walks the admin through it. If the
  operator *explicitly* offers SSH access to the device, the agent may run the documented commands
  — but must not push for device credentials.
- A **maintenance-aware moment** if TCP or TLS is chosen. See the warning box: a misconfigured
  TCP/TLS syslog host can stop the firewall passing new connections.
- The ASA must be able to reach the syslog endpoint on the chosen port/protocol from the interface
  named in `logging host`. Valid ports are **1025–65535** for either protocol.
- **`logging host` takes an IP address** (`syslog_ip` is documented as "the IP address (IPv4 or
  IPv6) of the syslog server") — resolve the endpoint domain to an address, and confirm with
  Fluency that the address is stable before hard-coding it.
- **IPv6 cannot be used for secure logging** — if the endpoint is reached over IPv6, TLS is off the
  table.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the ASA (default):** you resolve/create the syslog
  transport, install the connector, then walk whoever holds ASA access through the CLI (or ASDM)
  runbook, and verify rows.
- **(b) Runbook only:** print the full procedure — a ready-to-paste command block with the resolved
  endpoint address and port filled in — for the firewall admin to apply in a change window. Offer
  to resume verification when they return.

Before either: settle the **transport decision** from the warning box, and ask whether this is a
**failover pair** (TCP syslog is not supported on a standby unit) or **multiple-context mode**
(four syslog servers per context, sixteen total).

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **Decide which listener this ASA needs**, per the transport decision above:
   - **TLS chosen** → **`syslog_tls`**. The ASA speaks SSL/TLS over TCP with the `secure` keyword.
   - **Plain TCP chosen** → **`syslog_tcp`**.
   - **UDP chosen** (or IPv6 endpoint, or the customer declines the TCP outage tradeoff) →
     **`syslog_udp`**.
3. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
4. **Configuration exists but lacks the listener you need** → **`syslog_update_config`** to enable
   it. Leave the existing listeners untouched; other devices depend on them.
5. **Capture the deliverables:** the endpoint **domain** (and its resolved **IP address**, since
   `logging host` needs one), the **port**, and the **protocol**. These go into the ASA in Step 3.

> **TLS certificate:** when using the `syslog_tls` listener, the ASA must trust the platform CA —
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt — imported into a trustpoint in
> Step 3.3. Without it the TLS session never establishes, and on an ASA that means the
> `permit-hostdown` question becomes an availability question. Do not skip it.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`CiscoASAFWLog`** template ("Cisco ASA
   Syslog", category `onpremise`) and use its **current** schema. In the 2026-07 snapshot it takes
   `datalake` (default `managed`) and `index` (default `CiscoASA`) — the live template is the
   truth.
2. **`list_connectors`** — if a `CiscoASAFWLog` instance already exists, the site is likely already
   ingesting ASA syslog; additional ASAs just point at the same endpoint (Step 3) and share it.
   Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `CiscoASAFWLog`
   - `instance`: `ciscoasafwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Cisco ASA Syslog`
   - `inputParameters`: **every** parameter the live template defines — `datalake` (`managed`) and
     `index` (`CiscoASA`) unless the operator wants otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Cisco ASA
Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Configure the ASA (guided)

All commands below are Cisco-documented; substitute the interface name, endpoint address and port
from Step 1. Everything runs from **global configuration mode** (`configure terminal`).

### 3.1 The UDP path (simplest, no outage mode)

```
configure terminal
logging enable
logging timestamp
logging host outside 203.0.113.10 udp/514
logging trap informational
logging device-id hostname
write memory
```

- `logging enable` turns on transmission of syslog messages to all configured output locations.
- `logging timestamp` adds the date and time to each message. For an unambiguous, year-bearing,
  UTC timestamp use **`logging timestamp rfc5424`** instead (`YYYY-MM-DDTHH:MM:SSZ`) — recommended
  where the parser and the SIEM should agree on time without guessing.
- `logging host <interface_name> <ip> udp/<port>` — `interface_name` is the interface through which
  the ASA reaches the syslog server; the protocol defaults to **UDP** if omitted, and the default
  UDP port is **514**.
- `logging trap <severity>` selects what is sent to syslog servers (Step 3.4).
- `logging device-id hostname` prefixes messages with the ASA's hostname — do this when more than
  one ASA feeds the same endpoint, so the datalake can tell them apart. Other forms:
  `context-name`, `ipaddress <interface_name>`, `string <text>`, `cluster-id`.
- `write memory` persists the running configuration. **Nothing above survives a reload without
  it.**

UDP is connectionless: the ASA gives no error if the address or port is wrong, and it never blocks
traffic when the collector is down.

### 3.2 The TCP path

```
configure terminal
logging enable
logging timestamp
logging permit-hostdown              ! do this FIRST — see the warning box
logging host outside 203.0.113.10 tcp/1470
logging trap informational
write memory
```

- Default TCP port is **1470**; use the port the Fluency listener actually offers.
- `logging permit-hostdown` makes the status of a TCP-based syslog server irrelevant to new user
  sessions. Default is **off**, i.e. the firewall fails closed.
- Cisco notes for TCP: the ASA opens **four connections** to the syslog server so messages are not
  lost; the connection takes about a minute to initiate after the collector restarts; and a
  downed collector takes roughly **six minutes** to flip from *Connected* to *Not connected* in
  `show logging`.
- **TCP syslog is not supported on a standby unit** in a failover pair.

### 3.3 The TLS path (preferred where the tradeoff is accepted)

**Order matters.** Import the CA and set `permit-hostdown` *before* the `secure` host line.

**a) Guard the outage mode**

```
configure terminal
logging permit-hostdown
```

**b) Import the platform CA certificate into a trustpoint**

Download https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt and have the base-64
(PEM) text ready to paste.

> **What this file is** (inspected 2026-07-28): a PEM bundle of **five public roots** — Amazon
> Root CA 1–4 and Starfield Services Root CA G2, the Amazon Trust Services roots behind
> AWS-issued certificates. Unlike a browser or a general-purpose OS, the **ASA has no ambient
> public-CA store for this** — a trustpoint must be created explicitly, so the import below is
> genuinely required rather than optional. The bundle contains five roots; import the one that
> anchors the endpoint's chain (paste them one trustpoint at a time if unsure — an unused
> trustpoint is harmless). It is server-trust only; the ASA presents no client certificate here.

```
configure terminal
crypto ca trustpoint FLUENCY-SYSLOG-CA
 enrollment terminal
 revocation-check none
 exit
crypto ca authenticate FLUENCY-SYSLOG-CA
```

The ASA responds `Enter the base 64 encoded CA certificate. End with a blank line or the word
"quit" on a line by itself`. Paste the PEM block, type `quit`, then confirm the fingerprint
prompt (`Do you accept this certificate? [yes/no]:`) with `yes`. A successful import reports
`Trustpoint CA certificate accepted.` / `% Certificate successfully imported`.

`enrollment terminal` is what makes this a manual, paste-in trustpoint — no enrolment of the ASA's
own identity is needed, because ASA secure syslog is **one-way TLS**: the ASA validates the
server, and does not present a client certificate.

**c) (Recommended) pin the server identity — RFC 6125**

```
crypto ca reference-identity FLUENCY-SYSLOG
 dns-id syslog.example.fluency.tld
 exit
```

Cisco's own example for this feature is a syslog server. Use the endpoint's **domain** here (not
its IP) — the check compares your configured reference identity against the identity presented in
the server's certificate, so it works even though `logging host` connects by address. If the
presented identity cannot be matched, the connection is not established and an error is logged.

**d) Point logging at the endpoint over TLS**

```
logging enable
logging timestamp rfc5424
logging host outside 203.0.113.10 tcp/6514 secure reference-identity FLUENCY-SYSLOG
logging trap informational
logging device-id hostname
write memory
```

- `secure` specifies SSL/TLS **for TCP only** — using it with `udp/` returns an error.
- The `reference-identity` clause is optional; drop it if you have not configured one.
- **IPv6 is not supported for secure logging.**
- Cisco's guidelines add: the server certificate received from a syslog server must contain
  **`ServAuth`** in its Extended Key Usage field (checked on non-self-signed certificates). If the
  platform's syslog certificate is rejected, check this before anything else.

### 3.4 Choose what actually gets sent

Two controls, and they compose:

**Severity threshold — `logging trap`.** Sending severity *N* sends *N and everything more
severe*. Cisco's levels:

| Level | Name | Meaning |
|---|---|---|
| 0 | `emergencies` | You cannot use the system. *(The ASA never generates level 0.)* |
| 1 | `alerts` | Immediate action needed |
| 2 | `critical` | Critical conditions |
| 3 | `errors` | Error conditions |
| 4 | `warnings` | Warning conditions |
| 5 | `notifications` | Normal but significant conditions |
| 6 | `informational` | Informational messages |
| 7 | `debugging` | Debugging messages |

`logging trap informational` (6) is the usual SIEM setting — it includes connection
build/teardown and ACL hits, which is what makes ASA logs useful, without the firehose of level 7.
`logging trap debugging` will generate enormous volume and Cisco warns debugging output "can
render the system unusable"; use it only for short, deliberate troubleshooting. Two documented
counterweights worth passing on: Cisco's syslog-server guidelines say **if you configure two or
more logging servers, limit the logging severity level to warnings for all of them**, and
**assign only one list or class to each syslog server**.

**Message lists — `logging list`.** For surgical control, build a named list and send *that*
instead of a bare severity:

```
logging list ingext-list level informational
logging list ingext-list level warnings class vpn
logging list ingext-list message 106100-106103
logging trap ingext-list
```

A message is logged if it satisfies **any** criterion in the list (and only once if it satisfies
several). Do **not** name a list after a severity level (`err`, `warning`, …) — Cisco prohibits it.

**Per-message tuning.**

```
no logging message 106015              ! stop generating a specific message entirely
logging message 106100 level 5         ! change one message's severity
show logging message 106100            ! what is this message's current level / is it enabled?
```

Re-enable with `logging message <id>`; reset all disabled messages with
`clear configure logging disabled`, and all modified levels with `clear configure logging level`.

**ACL hit logging.** Add `log` to an ACE to generate **106100** for every matching permit or deny
flow. Denies already generate **106023** by default without the keyword. If ACL logging is the
point of the integration, confirm the relevant ACEs carry `log`.

**Queue.** `logging queue <n>` (default **512**, range 0–8192 depending on platform; 0 means
maximum). Relevant on TCP/TLS because a **full queue also blocks new connections** — raise it if
`show logging queue` shows drops.

**Facility.** `logging facility <number>` — default **20**, which is what most UNIX collectors
expect. Only change it if Fluency asks you to.

### 3.5 ASDM equivalents

For an admin who works in **ASDM** rather than the CLI:

| Task | ASDM location |
|---|---|
| Turn logging on | **Configuration → Device Management → Logging → Logging Setup** → check **Enable logging** |
| Add / edit the syslog server | **Configuration → Device Management → Logging → Syslog Servers** → **Add** (interface, IP, TCP/UDP, port) |
| Enable TLS on that server | Edit the server → click the **TCP** radio button → check **Enable secure syslog with SSL/TLS** → optionally name a **Reference Identity** object |
| The outage escape hatch | Same **Syslog Servers** pane → **Allow user traffic to pass when TCP syslog server is down** (this *is* `logging permit-hostdown`) |
| Set the severity sent to syslog servers | **Configuration → Device Management → Logging → Logging Filters** → select the **Syslog Servers** destination → **Edit** |
| Build a message list | **Configuration → Device Management → Logging → Event Lists** → **Add** |
| Facility, per-message severity, disable a message | **Configuration → Device Management → Logging → Syslog Setup** |
| Watch the device's own log | **Monitoring → Logging → Real-Time Log Viewer** (and **Log Buffer Viewer**) |

ASDM writes to the running configuration — the change still needs saving to flash (the CLI
equivalent is `write memory`).

### 3.6 Interface and reachability gotchas

- `logging host <interface_name> …` — the interface named is the one used to reach the collector.
  In 9.18.3.60 and later this configuration takes precedence over a route lookup, so name the right
  one.
- If you configure syslog on an interface with **management-only access enabled**, dataplane
  messages **302015, 302014, 106023 and 304001** are dropped and never reach the collector — the
  most commonly noticed symptom being "we get admin events but no traffic logs". Use an interface
  with management-only access disabled.
- Cisco's guidelines: the syslog server should be reachable through the ASA; configure the device
  to deny ICMP unreachable messages on the interface through which the server is reachable, and
  suppress **313001, 313004 and 313005** to avoid a feedback loop.
- Limits: up to **16 syslog servers**; in multiple-context mode, **four per context**.

**Deliverables from this section:** none to collect — once `write memory` completes, events flow
on their own.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing connectors
  from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (the template's
  `index` default is `CiscoASA` — confirm the live name with `list_data_tables`), the endpoint
  domain/port/protocol, the `logging trap` severity actually configured, and **whether
  `logging permit-hostdown` was set** — that last one is an availability fact the customer's ops
  team needs recorded. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of minutes
  of `write memory`, *when the ASA logs something*. At `logging trap informational` on a firewall
  carrying real traffic, that is continuous; on a lab ASA it may be sparse. Compare against the
  device's own view (`show logging` buffer, or ASDM's Real-Time Log Viewer) before judging. Mark ⏳
  until either rows land or the device-side log shows events that never arrived — only the latter
  is ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "CiscoASAFWLog",
  "instance": "ciscoasafwlog",
  "table": "<confirm live with list_data_tables; template index default 'CiscoASA'>",
  "syslogEndpoint": "<domain>",
  "syslogEndpointIp": "<resolved ip used in logging host>",
  "syslogPort": "<port>",
  "protocol": "<tls|tcp|udp>",
  "loggingTrap": "informational",
  "permitHostdown": true
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **On the ASA, `show logging`** — this is the device's own ground truth. Expect:
   - `Syslog logging: enabled`
   - `Trap logging: level informational, facility 20, <N> messages logged` — the counter is the
     proof the ASA is *sending*
   - `Logging to <interface> <ip>` — the configured collector
   - `Permit-hostdown logging: enabled` if you set it
   For a TCP/TLS host, `show logging` also reports the connection state (remember: a downed
   collector takes about six minutes to show as *Not connected*). A healthy TLS host shows the
   four TCP connections the ASA opens.
3. **Generate a documented test event.** Any command other than a `show` command generates
   **`%ASA-5-111008: User 'user' executed the 'string' command.`** — severity 5, so it is sent at
   `logging trap notifications` (5), `informational` (6) or `debugging` (7). Re-entering a harmless
   configuration command (e.g. `logging timestamp`) is therefore a deterministic, no-impact test
   event. At `logging trap debugging` you additionally get `%ASA-7-111009: User 'user' executed
   cmd: string` for `show` commands too.
4. Count rows in the ASA table over the last hour via the **`ingext-kql`** skill (confirm the live
   table name with `list_data_tables` first — the template's `index` default is `CiscoASA`). Rows
   should trail `show logging`'s counter by seconds-to-minutes; search for the 111008 test event
   specifically.
5. `show logging queue` — if it shows discards, the ASA is generating faster than it can ship.
   Raise `logging queue`, lower `logging trap`, or both. On TCP/TLS this matters doubly: a full
   queue blocks new connections.
6. `show running-config logging` — confirm the configuration actually persisted, and re-run
   `write memory` if it did not.
7. TLS only: `show crypto ca certificate` — confirm the platform CA is present in the
   `FLUENCY-SYSLOG-CA` trustpoint.

---

## Failure modes

| Situation | Response |
|---|---|
| **Firewall stopped passing new traffic after the change; `%ASA-3-201008: Disallowing new connections`** | This is the TCP/TLS fail-closed behaviour. Immediate mitigations, in order: `logging permit-hostdown`; or `no logging host <if> <ip>` to remove the collector; or switch that host line to `udp/`. Then fix reachability and re-apply. Never leave a TCP/TLS syslog host configured on a production ASA without deciding this question deliberately. |
| Traffic blocked even though the collector is up | Since 8.3(2) a **full logging queue** triggers the same block (messages 414005–414008). Check `show logging queue`, raise `logging queue`, and/or lower `logging trap`. |
| Zero rows, but `show logging` shows messages logged (UDP) | UDP drops silently. Re-check the address (it must be an **IP** — `logging host` does not take an FQDN), the port (matches the endpoint's UDP listener, not 514 by habit), the interface named in `logging host`, and the egress path. |
| TLS never establishes | Work through: is the platform CA imported (`show crypto ca certificate`)? Was `secure` used with `tcp/` (it errors on `udp/`)? Is the endpoint reached over IPv6 (unsupported for secure logging)? Does the server certificate carry **`ServAuth`** in Extended Key Usage? If a `reference-identity` is configured, does its `dns-id` match what the certificate actually presents? |
| Admin/system events arrive but no traffic logs | Two usual causes: `logging trap` is too severe (traffic messages are level 6) — set `informational`; or syslog is bound to an interface with **management-only access enabled**, which drops 302015, 302014, 106023 and 304001. |
| Expected ACL hits missing | ACEs need the `log` keyword to generate **106100**; without it only denies log (**106023**). Also check the message is not disabled (`show logging message <id>`, `no logging message` reverses). |
| Volume far higher than expected | Lower `logging trap`, or move to a `logging list` that selects only the classes and message ranges wanted, then `logging trap <list-name>`. Do not leave `logging trap debugging` in place. |
| Failover pair: standby unit sends nothing over TCP | Documented — **sending syslogs over TCP is not supported on a standby device**. Use UDP if both units must ship, or accept active-only TCP shipping. |
| Multi-context ASA | **Four syslog servers per context** (sixteen total). Configure per context; consider `logging device-id context-name` so contexts are distinguishable in the datalake. |
| Several ASAs, indistinguishable in the datalake | `logging device-id hostname` (or `string <text>` / `ipaddress <interface>`) on each. |
| Site syslog config exists but lacks the listener this ASA needs | `syslog_update_config` to enable the missing listener — do **not** re-register the site config. Leave existing listeners untouched. |
| No site syslog config at all | `syslog_register_config` — once per site. If unsure whether one exists, `syslog_get_config` first, always. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Configuration lost after a reload | `write memory` was never run. Re-apply and persist. |
| Wrong table / table name unknown | The template's `index` default is `CiscoASA`, but `list_data_tables` is the authority. |
| Events arrive garbled / unparsed | Confirm the connector installed is `CiscoASAFWLog` (not a generic syslog path). Also check whether `format emblem` is set on the host line — EMBLEM is a Cisco-specific format (UDP only) and is **not** what this parser expects unless Fluency says otherwise. |
| Endpoint IP changed | `logging host` is pinned to an address. Re-point it (`no logging host …` then the new line) and `write memory`. Ask Fluency whether a stable address can be guaranteed for this site. |

---

## Security notes

- **UDP and plain TCP syslog are unencrypted and unauthenticated in transit.** ASA firewall logs
  are not low-sensitivity: they carry internal addressing, NAT mappings, VPN usernames and admin
  activity. The ASA *can* do TLS, so prefer it — and be explicit when the customer declines, rather
  than letting cleartext happen by default.
- **The `permit-hostdown` decision is a security decision, not just an availability one.** The
  fail-closed default exists for Common Criteria EAL4+ environments where unlogged traffic is
  unacceptable. Record which way the customer chose, and why, in the hand-back.
- ASA secure syslog is **one-way TLS**: the ASA validates the collector and presents no client
  certificate. There is no client credential to protect here — but that also means the collector
  cannot cryptographically identify *which* ASA is connecting; use `logging device-id` and network
  controls for attribution.
- The CA certificate imported into the trustpoint is a public certificate, not a secret. The
  trustpoint is device-wide, so it will be trusted for any TLS client connection the ASA validates
  against it — keep it scoped to a purpose-named trustpoint (`FLUENCY-SYSLOG-CA`) rather than
  adding the CA to a general-purpose one.
- `revocation-check none` on that trustpoint means no CRL/OCSP check. That is normal for a private
  syslog CA with no published revocation endpoint, but it is a real reduction in checking — say so
  rather than leaving it in a config block unexplained.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — no need
  to publish them beyond the people configuring devices.
- Enable/config access to the ASA is the sensitive thing in this procedure. The agent guides by
  default and must not ask for device credentials; if the operator offers SSH access, use it only
  for the documented commands above.

---

## Layout

```
setup-cisco-asa-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Cisco ASA documentation citations; platform syslog-transport notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
