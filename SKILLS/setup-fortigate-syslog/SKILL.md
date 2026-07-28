---
name: setup-fortigate-syslog
version: 1.0.0
description: >-
  Set up FortiGate / FortiOS firewall log import into Fluency / Ingext via syslog. The agent
  performs the whole Fluency side itself: it resolves the site's syslog endpoint via the syslog
  MCP calls — syslog_get_config to read the existing transport, syslog_register_config to create
  it if the site has none (once per site, ever), syslog_update_config to enable the listener the
  FortiGate will speak — and installs the "FortiGate NGFW Syslog V2" connector (FortiGateFWLogV2).
  The FortiGate side is a real runbook: FortiOS supports UDP, plain TCP and TLS syslog, so this
  skill prefers TLS (`set mode reliable` + `set enc-algorithm`) with the platform CA certificate
  imported under System → Certificates, and covers the GUI path (Log & Report → Log Settings),
  the `config log syslogd setting` / `config log syslogd filter` CLI, which log categories get
  forwarded, and `diagnose log test`. SELF-CONTAINED: it ends by creating the connector itself —
  when routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers:
  "connect our FortiGate to Ingext", "forward Fortinet firewall logs to Fluency", "FortiGate
  syslog into the datalake", "set up the Fortinet connector", "send FortiOS logs to Fluency".
  Do NOT use for FortiAnalyzer or FortiManager (different products, different templates — check
  the live template list), not for FortiClient/FortiEDR endpoint telemetry, and not for analysing
  FortiGate bandwidth once data lands — that is the fortigate-bandwidth skill. Other syslog
  vendors have their own skills (setup-paloalto-syslog, setup-peplink-syslog); anything with no
  dedicated skill goes to add-connector.
---

# Set up FortiGate / FortiOS syslog import

Import a **FortiGate** firewall's logs — traffic, UTM/security events, system and admin events —
into Fluency / Ingext via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`FortiGateFWLogV2`** ("FortiGate NGFW Syslog V2"),
  which parses the FortiOS stream. The template takes no parameters.
- **FortiGate side (customer's firewall):** a syslog server definition plus the filter that
  decides *which* logs go out. FortiOS speaks **UDP, plain TCP and TLS** — so unlike a UDP-only
  appliance, this one gets **TLS by default** (see Step 3).

Every device-side claim below is cited in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. The listener the FortiGate will use (`syslog_tls` preferred, else `syslog_tcp` / `syslog_udp`) is enabled with `syslog_update_config` if missing |
| Ingext | Connector | Template **`FortiGateFWLogV2`** ("FortiGate NGFW Syslog V2"), instance e.g. `fortigatefwlogv2`, no parameters |
| FortiGate | Syslog server entry | `config log syslogd setting` (or `syslogd2`–`syslogd4`), or GUI **Log & Report → Log Settings** |
| FortiGate | Syslog filter | `config log syslogd filter` — severity floor and per-category toggles |
| FortiGate | CA certificate (TLS only) | The platform CA imported at **System → Certificates → Import → CA Certificate** so the firewall trusts the endpoint |

Nothing here is billable on either side.

---

## Prerequisites

- Admin access to the FortiGate — the **web admin UI**, and ideally **SSH/console CLI**: the GUI
  exposes the syslog server address, but the transport mode, TLS settings and the log filter are
  CLI territory.
- The firewall must be able to reach the syslog endpoint **outbound** on the chosen port and
  protocol — check the egress path and any upstream firewall.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.
- **Optional:** per the repo's SSH policy, if the operator *offers* device access the agent may
  run the documented commands below. Never ask for firewall credentials — guide by default.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the firewall (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever holds the FortiGate through Step 3 —
  transport choice, CA import if TLS, the syslog block, the filter, and the on-device check.
- **(b) Runbook only:** print the full procedure — with the real endpoint host/port/protocol
  filled in once you've resolved it — for the firewall admin to apply later. Offer to resume
  verification when they return.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the descriptions below are intent, not exact parameter names.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that is what update is for.
3. **Configuration exists but lacks the listener this FortiGate will use** →
   **`syslog_update_config`** to enable it. Leave the existing listeners untouched; other devices
   at the site depend on them.
4. **Which listener?** FortiOS supports all three, so pick in this order:
   - **`syslog_tls` — the default choice.** Firewall logs carry internal IPs, usernames, URLs and
     policy names; they should not cross a network in cleartext. FortiOS does TLS with
     `set mode reliable` + `set enc-algorithm`.
   - `syslog_tcp` — if the customer rules out TLS (e.g. no appetite for certificate work) but
     wants connection-oriented delivery.
   - `syslog_udp` — last resort, or when the path is already private. **Say the tradeoff out
     loud:** UDP is unencrypted, unauthenticated and drops silently.
5. **Capture the deliverables:** endpoint **domain**, **port**, **protocol**. These go into the
   FortiGate in Step 3.

> **TLS certificate:** when you take the `syslog_tls` path, the firewall must trust the platform's
> certificate. Give the admin the platform CA certificate —
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt — and follow the import
> procedure in Step 3b. The CA certificate is public; it is not a credential.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`FortiGateFWLogV2`** template ("FortiGate
   NGFW Syslog V2") and use its current schema; in the 2026-07 snapshot it has **no parameters**,
   but the live template is the truth. Some older platforms still list a V1 **`FortiGateFWLog`** —
   **prefer V2** unless the operator has a specific reason for V1.
2. **`list_connectors`** — if a FortiGateFWLogV2 instance already exists, the site is likely
   already ingesting FortiGate syslog; additional firewalls just point at the same endpoint
   (Step 3) and share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `FortiGateFWLogV2`
   - `instance`: `fortigatefwlogv2` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `FortiGate NGFW Syslog V2`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **FortiGate
NGFW Syslog V2** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the FortiGate at it (guided)

This is the part that actually decides whether data flows. Work through it in order.

### 3a. Pick the FortiOS transport mode

`config log syslogd setting` has a `mode` that maps onto the wire protocol:

| FortiOS `set mode` | On the wire | Use it when |
|---|---|---|
| `udp` (FortiOS default) | UDP syslog | Only if TLS/TCP are ruled out — unencrypted, silent drops |
| `reliable` | TCP, framed per **RFC 6587** (octet counting) | Cleartext but connection-oriented |
| `reliable` + `set enc-algorithm high` | **TLS over TCP** | **Preferred** — encrypted, connection-oriented |
| `legacy-reliable` | TCP per **RFC 3195** (BEEP RAW profile) | Legacy receivers only — not the path here |

`enc-algorithm` is documented as "Enable/disable reliable syslogging with **TLS encryption**" and
takes `high-medium | high | low | disable`. **`high` is the right choice** unless the receiving
side rejects the handshake.

> **Framing caveat, worth knowing before you choose TCP/TLS:** FortiOS v6.0+ frames TCP syslog with
> RFC 6587 **octet counting** (each message prefixed by its byte length). Receivers that expect
> newline-delimited (non-transparent) framing can glue many events into one giant record. If
> TLS/TCP events land merged or truncated in the datalake, that is the cause — see Failure modes.

### 3b. TLS only — import the platform CA certificate first

Do this **before** enabling syslog, so the first connection attempt succeeds. When the FortiGate
is the syslog *client*, adding the CA that signed the server's certificate is what makes the
firewall trust it; a **client** certificate is only needed if the receiving server demands client
authentication — leave `set certificate` unset unless Fluency says otherwise.

> **What this file is** (inspected 2026-07-28): a PEM bundle of **five public roots** — Amazon
> Root CA 1–4 and Starfield Services Root CA G2, the Amazon Trust Services roots behind
> AWS-issued certificates. So the endpoint certificate is **publicly trusted**, and a FortiGate
> whose built-in CA list already includes those roots may validate it with no import at all —
> check **System → Certificates** before assuming the import is required. Importing is still a
> reasonable deliberate choice: it **pins** trust to these roots rather than the whole public-CA
> set. It is server-trust only, never a client certificate.

1. Download the platform CA: https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
2. In the FortiGate GUI: **System → Certificates → Import → CA Certificate → Type: File**, upload
   `ca.crt`, **OK**.
3. If **Certificates** is not in the System menu (hidden on some builds), enable it under
   **System → Feature Visibility** first, then repeat.
4. Confirm the imported CA appears in the certificate list (FortiOS names imported CAs
   `CA_Cert_1`, `CA_Cert_2`, … ). The CLI object lives under `config vpn certificate ca` — use the
   GUI import to load the PEM; **UNVERIFIED:** the exact CLI import syntax for a PEM blob is not
   documented in the sources checked, so do not hand-craft it.

### 3c. Configure the syslog server

**GUI (address only):** **Log & Report → Log Settings** → toggle **Send Logs to Syslog** to
*Enabled* → enter the endpoint address → **Apply**. This gets you a UDP/514 default; the mode,
port, TLS and filter settings below are CLI.

**CLI — TLS (preferred):**

```
config log syslogd setting
    set status enable
    set server "<endpoint-domain>"
    set port <tls-port-from-step-1>
    set mode reliable
    set enc-algorithm high
    set ssl-min-proto-version TLSv1-2
    set facility local7
    set format default
end
```

**CLI — plain TCP:**

```
config log syslogd setting
    set status enable
    set server "<endpoint-domain>"
    set port <tcp-port-from-step-1>
    set mode reliable
    set enc-algorithm disable
    set facility local7
    set format default
end
```

**CLI — UDP (fallback):**

```
config log syslogd setting
    set status enable
    set server "<endpoint-domain>"
    set port <udp-port-from-step-1>
    set mode udp
    set facility local7
    set format default
end
```

Notes on those values:

- **`server`** accepts an IP address or an FQDN — use the endpoint domain from Step 1.
- **`port`** — FortiOS defaults to 514. Set it explicitly to the endpoint's port; do not assume 514.
- **`facility`** — FortiOS defaults to `local7`; any RFC facility is accepted. Leave it alone
  unless the customer has a site convention.
- **`ssl-min-proto-version`** — the CLI reference lists `default | SSLv3 | TLSv1 | TLSv1-1 |
  TLSv1-2`; newer builds add TLS 1.3. `TLSv1-2` is a safe floor; `default` is fine if the enum on
  this build does not offer it.
- **`format`** — FortiOS offers `default | csv | cef | rfc5424 | json`. **UNVERIFIED:** which of
  these the Fluency `FortiGateFWLogV2` parser expects is not publicly documented. Leave it at
  **`default`** (FortiOS native `key=value`), which is what the template is named for, and raise
  it with Fluency support only if events land unparsed.
- **`source-ip`** — set it if the firewall must egress from a specific interface/IP (common when
  the endpoint is reached over an IPsec tunnel); pair with `set interface-select-method specify`
  and `set interface <name>` where the build supports it.

**Already using slot 1?** A FortiGate can send to **up to four** syslog servers. If
`config log syslogd setting` is already pointed at another collector, **do not overwrite it** —
use the next free slot instead, with identical syntax:

```
config log syslogd2 setting
    ...same settings...
end
```

`syslogd2`, `syslogd3` and `syslogd4` each have their own matching `filter` block.

### 3d. Choose which logs are forwarded

Three independent gates decide what actually leaves the box. All three must be open.

**1. The syslog filter** — the severity floor and per-category switches for *this* syslog
destination:

```
config log syslogd filter
    set severity information
    set forward-traffic enable
    set local-traffic disable
    set multicast-traffic disable
    set sniffer-traffic disable
    set anomaly enable
    set voip disable
end
```

- `severity` is the **lowest** level to log: `emergency | alert | critical | error | warning |
  notification | information | debug`. `information` is the usual production floor; `debug` is
  for troubleshooting only.
- `set filter "<expression>"` plus `set filter-type include|exclude` narrows further by field —
  useful for dropping a noisy source, expensive to get wrong. Leave both unset unless the
  customer asks.
- Use `get` inside the block to see the full list of toggles on this build.

**2. Traffic logging is per firewall policy.** A FortiGate emits traffic logs only for policies
that ask for them:

- GUI: **Policy & Objects → Firewall Policy** → edit a rule → **Log Allowed Traffic** →
  **Security Events (UTM)** or **All Sessions**.
- CLI: `set logtraffic {all | utm | disable}` inside `config firewall policy` / `edit <id>`.

`utm` logs only sessions that matched a security profile; `all` logs every session and is far
heavier. **Recommend `utm`/Security Events as the default** and let the customer opt into `all`
for the policies they actually need full flow records on. If nothing but system events shows up
in the datalake, this is nearly always why.

**3. Event logging** — system, VPN, user, router, HA, SD-WAN and friends are governed by
`config log eventfilter`, where **all categories are enabled by default**. Check it with `get`
before assuming; only a previous admin's tuning turns these off.

### 3e. Save

FortiOS writes each block when you type **`end`**; the GUI writes on **Apply**. There is no
separate commit step.

### 3f. Confirm on the device before you leave it

```
show full-configuration log syslogd setting
execute ping <endpoint-domain>
execute telnet <endpoint-domain> <port>
```

`execute telnet` proves a TCP/TLS port is reachable (it proves nothing for UDP). Then generate
traffic on purpose:

```
diagnose log test
```

`diagnose log test` writes a spread of synthetic entries — virus, URL block, IPS, anomaly,
application-control, and more — to local storage **and to every configured syslog server**. Its
optional arguments differ between FortiOS versions, so run it bare unless the version's own help
says otherwise. Finally, read the device's own view: **Log & Report → System Events** and
**Forward Traffic**.

**Deliverables from this section:** none to collect — once the block is saved, logs flow.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index; the repo's
  `fortigate-bandwidth` skill refers to a `NetworkFortigateTraffic` / `fortigatetraffic`-style
  table, treat that as a hint, not truth), and the endpoint domain/port/protocol. None of these
  are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes of saving the block, *when the firewall logs something*. A FortiGate under load is
  never quiet, so an empty table after five minutes is a real signal here, unlike a small
  appliance. Mark ⏳ only briefly; if the device's own Log & Report pages show events and the
  datalake shows none, that is ❌ and the Failure modes table applies.
- **Downstream caveat worth passing on:** FortiGate byte fields (`sentbyte` / `rcvdbyte`) are
  **cumulative session counters**, so any later `sum()` over them over-counts badly. Point
  analysts at the **`fortigate-bandwidth`** skill before they build bandwidth reports. A plain
  **row count** — what verification uses — is unaffected and safe.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "FortiGateFWLogV2",
  "instance": "fortigatefwlogv2",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "tls",
  "fortiosMode": "reliable + enc-algorithm high",
  "caCertificateImported": true
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **The FortiGate's own log views are the ground truth.** Open **Log & Report → System Events**
   and **Log & Report → Forward Traffic**. Whatever is there is what the device believes it
   logged; anything in the datalake must be a subset of it.
3. Generate a known event with **`diagnose log test`** (vendor-documented — it targets configured
   syslog servers), then count rows in the FortiGate table over the last few minutes via the
   **`ingext-kql`** skill. Confirm the live table name with **`list_data_tables`** first.
4. Rows should trail the device's own log by seconds-to-minutes. A **plain row count** is the
   correct smoke test — do not sum byte fields (see `fortigate-bandwidth`).
5. If nothing landed, work the device-side checks from Step 3f (`show full-configuration log
   syslogd setting`, `execute ping`, `execute telnet <endpoint> <port>`) before blaming the
   platform.

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows on **UDP**, but Log & Report shows events | UDP drops silently — the firewall never learns. Re-check `server` (typo/wrong domain), `port` (the endpoint's port, not the 514 default), and that outbound UDP to the endpoint is permitted. Prefer moving this source to TLS. |
| Site syslog config exists, but not the listener the FortiGate needs | `syslog_update_config` to enable `syslog_tls` (or `_tcp`/`_udp`). **Do not re-register** the site config, and leave the other listeners alone — other devices use them. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. When unsure, `syslog_get_config` first, always. |
| TLS handshake fails; FortiGate reports **Unknown CA** | The platform CA is not imported (or an intermediate is missing). Re-do Step 3b — **System → Certificates → Import → CA Certificate → File** — and confirm the CA is listed. Import intermediates too if the chain has them. |
| TLS fails but the CA is present | Check `ssl-min-proto-version` against what the endpoint accepts, and `enc-algorithm` (try `high`). A `set certificate` value left over from another integration will offer a client cert that the endpoint may reject — clear it unless client auth is required. |
| Events arrive **merged into one huge record** on TCP/TLS | FortiOS uses RFC 6587 octet-counting framing; a receiver expecting newline framing concatenates messages. Raise it with Fluency support with a sample; the interim workaround is `set mode udp`, which trades encryption for correct message boundaries. |
| Only system events land, no traffic | Traffic logging is per policy. Set **Log Allowed Traffic** (`set logtraffic utm` or `all`) on the policies that matter — Step 3d, gate 2. |
| Nothing at all lands, `diagnose log test` included | Check `set status enable`, then reachability: `execute ping <endpoint>`, `execute telnet <endpoint> <port>`. Then the egress path — an upstream firewall or ISP blocking the port is common. |
| The syslog slot was already taken by another collector | Do not overwrite it. Use `config log syslogd2 setting` (or 3/4) — up to four servers are supported, each with its own filter block. |
| Events arrive but look unparsed / wrong shape | Confirm `set format default` (not `csv`/`cef`/`json`) and that the installed connector is `FortiGateFWLogV2`, not a generic syslog path or the V1 template. |
| Only the V1 `FortiGateFWLog` template appears in the live list | Older platform. Confirm with the operator, and install V1 only if V2 genuinely is not offered — the V2 parser is the current one. |
| Bandwidth numbers look absurd after onboarding | Not an ingestion fault: FortiGate byte fields are cumulative session counters. Route the analyst to the **`fortigate-bandwidth`** skill. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **Prefer TLS for this device.** FortiGate logs are not low-sensitivity: they carry internal
  addressing, usernames, visited URLs, VPN activity and policy names. UDP and plain TCP syslog
  cross the network in cleartext and can be read or spoofed by anyone on the path. If the customer
  chooses UDP anyway, record that it was a deliberate decision and note the exposure.
- The platform **CA certificate is public** — it is a trust anchor, not a secret. Nothing in this
  runbook produces a credential; there is no token to leak into a ticket or summary.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — share
  them only with the people configuring devices.
- Keep `set severity` at a sane floor. `debug` on a busy firewall floods both the link and the
  datalake, and buries the events anyone actually wants.
- If a `set certificate` client certificate is ever required, it carries a private key that lives
  on the firewall — that key never leaves the device and must never be exported into a ticket.

---

## Layout

```
setup-fortigate-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Fortinet documentation + community citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
