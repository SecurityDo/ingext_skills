---
name: setup-sonicwall-syslog
version: 1.0.0
description: >-
  Set up SonicWall firewall (SonicOS) event import into Fluency / Ingext via syslog. The agent
  performs the whole Fluency side itself: it resolves the site's syslog endpoint via the syslog
  MCP calls — syslog_get_config to read the existing transport, syslog_register_config to create
  it if the site has none (once per site, ever), syslog_update_config to enable the listener this
  firewall can actually speak — and installs the "SonicWall NGFW Syslog" connector
  (SonicWallFWLog). The firewall side is web-UI work the customer's admin does: add a syslog
  server under Device > Log > Syslog, choose the syslog format, and pick which log categories are
  forwarded under Device > Log > Settings. Transport depends on firmware — SonicOS 8 can send
  UDP, TCP or TLS (prefer TLS); SonicOS 7.x and 6.5 are UDP only. SELF-CONTAINED: it ends by
  creating the connector itself — when routed from customer-onboarding, do NOT chain into
  add-connector afterward. Triggers: "connect our SonicWall to Ingext", "forward SonicWall
  firewall logs to Fluency", "SonicOS syslog into the datalake", "set up the SonicWall connector",
  "get our TZ/NSa firewall logs in". Do NOT use for other syslog vendors (Check Point is
  setup-checkpoint-syslog; Peplink is setup-peplink-syslog; FortiGate, Palo Alto, Meraki, Cisco
  ASA use setup-cisco-asa-syslog, Sophos uses setup-sophos-firewall-syslog or
  setup-sophos-utm-syslog), and not for
  SonicWall Analytics/GMS reporting or SonicWall Cloud Edge — this imports the firewall's own
  event log over syslog, nothing more.
---

# Set up SonicWall (SonicOS) syslog import

Import a **SonicWall** firewall's event log — connection, threat, VPN, admin and system events —
into Fluency / Ingext via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`SonicWallFWLog`** ("SonicWall NGFW Syslog"), which
  parses the SonicWall stream. The template takes no parameters.
- **Firewall side (customer's admin UI):** add a syslog server under **Device → Log → Syslog**,
  choose the **Syslog Format**, and confirm which log categories are flagged for syslog under
  **Device → Log → Settings**.

**Transport is firmware-dependent and this decides Step 1.** SonicOS 8 added a **Protocol**
selector — **UDP, TCP or TLS** (TLS 1.2/1.3, RFC 5425, default port 6514). SonicOS 7.0/7.1 and
6.5 have **no protocol selector**: syslog leaves the firewall over **UDP/514** only. Establish the
version before choosing a listener.

Vendor-side steps are backed by SonicWall's technical documentation and knowledge base; citations
live in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. The listener the firmware can speak must be enabled (`syslog_update_config` if missing): `syslog_tls` for SonicOS 8, `syslog_udp` for SonicOS 7.x/6.5 |
| Ingext | Connector | Template **`SonicWallFWLog`** ("SonicWall NGFW Syslog"), instance e.g. `sonicwallfwlog`, no parameters |
| SonicWall | Address object | The syslog endpoint as an **FQDN** (or Host) address object — the syslog server field is an address-object picker |
| SonicWall | Syslog server entry | **Device → Log → Syslog → Syslog Servers → Add**: event profile, address object, port, protocol (SonicOS 8), server type, syslog format, facility, syslog ID |
| SonicWall | CA certificate (TLS only) | The platform CA bundle imported under **Device → Settings → Certificates**, if the firewall does not already trust the endpoint's issuer |
| SonicWall | Log category selection | **Device → Log → Settings**: the **Syslog** checkbox per category/group/event, plus the **Logging Level** |

Nothing here is billable on either side.

---

## Prerequisites

- **Admin access to the SonicWall web management UI** (the operator or their firewall admin — the
  agent cannot click it). A full administrator is needed for **Device → Settings → Certificates**
  if TLS is in play.
- **The SonicOS version.** It decides the transport. Read it from the firewall's
  **Monitor → System Status / dashboard** or the login banner, or ask the admin. Treat "SonicWall"
  with no version as unanswered — do not assume TLS.
- The firewall must be able to reach the syslog endpoint from its egress interface on the
  configured port and protocol — check outbound rules on the path (and on any upstream device).
- If the endpoint is a hostname, the firewall needs working DNS (**Network → DNS**) to resolve an
  FQDN address object.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the firewall (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever has the SonicWall admin UI through
  the address object, the syslog server entry, the format choice and the category selection, and
  verify rows.
- **(b) Runbook only:** print the full procedure — including the endpoint host/port/protocol once
  you've resolved it — for the firewall admin to apply later. Offer to resume verification when
  they return.

The firewall's own CLI is **not** a documented path for this procedure in the SonicWall docs we
verified (see `assets/references.md`), so do not offer to drive it over SSH.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

**First, pin the transport to the firmware:**

| SonicOS version | Available syslog transports | Listener to drive |
|---|---|---|
| **8.x** | UDP, TCP, **TLS** (1.2/1.3, RFC 5425; port auto-fills 6514) | **`syslog_tls`** — prefer it |
| **7.0 / 7.1** | UDP only (no protocol selector in the Add Syslog Server dialog) | `syslog_udp` |
| **6.5** | UDP only | `syslog_udp` |
| **7.2 / 7.3** | **UNVERIFIED** — the 7.3 Device Log guide was not reachable at build time. Have the admin open **Device → Log → Syslog → Syslog Servers → Add** and look for a **Protocol** field: present → treat as 8.x, absent → treat as 7.0/7.1 | per what the dialog shows |

Then:

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Configuration exists but not the listener this firewall needs** (e.g. only `syslog_udp` is
   enabled and this is a SonicOS 8 box you want on TLS) → **`syslog_update_config`** to enable the
   additional listener. Leave the existing listeners untouched; other devices depend on them.
4. **Capture the deliverables:** the endpoint **domain**, the **port** for the chosen listener,
   and the **protocol**. These go into the firewall in Step 3.

> **TLS (SonicOS 8 only):** prefer the `syslog_tls` listener. The firewall validates the
> endpoint's server certificate during the handshake and fails closed if it cannot. Give the admin
> the platform CA certificate for the trust step in Step 3:
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
>
> **No TLS on SonicOS 7.x/6.5.** Say so plainly rather than implying the customer can encrypt it:
> the firewall has no protocol selector, so the stream leaves in cleartext UDP. The options are
> accepting that for this source, carrying it over a private path (an existing site-to-site
> tunnel), or upgrading to SonicOS 8 — a customer decision, not this skill's.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`SonicWallFWLog`** template ("SonicWall NGFW
   Syslog", category `onpremise`) and use its current schema; in the 2026-07 snapshot it has **no
   parameters**, but the live template is the truth.
2. **`list_connectors`** — if a SonicWallFWLog instance already exists, the site is likely already
   ingesting SonicWall syslog; additional firewalls just point at the same endpoint (Step 3) and
   share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `SonicWallFWLog`
   - `instance`: `sonicwallfwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `SonicWall NGFW Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **SonicWall
NGFW Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the firewall at it (guided)

Everything below is the **SonicOS 7.x/8 web UI**. The SonicOS 6.5 equivalents are called out at
the end. Menu paths are quoted from SonicWall's documentation — see `assets/references.md`.

### 3.1 — Create the address object for the endpoint

The syslog server field is an **address-object picker**, not a free-text box.

1. **Object → Match Objects → Addresses → Address Objects → Add.**
2. **Name:** something obvious, e.g. `Fluency-Syslog`.
3. **Type:** **FQDN** if the endpoint is a hostname (resolved with the DNS servers configured
   under **Network → DNS**), or **Host** if you were given an IP.
4. Save.

> The Add Syslog Server dialog also offers to create a new address object inline in SonicOS 8; the
> standalone object is easier to reuse for the firewall rule you may need on the egress path.

### 3.2 — (TLS only, SonicOS 8) make the firewall trust the endpoint

The firewall automatically trusts issuers in its built-in CA list; anything else must be imported
or the connection fails certificate validation.

1. Try the syslog server first (§3.3). If the connection shows a certificate/validation failure,
   import the CA.
2. **Device → Settings → Certificates → Import.**
3. Choose **"Import a CA certificate from a PKCS#7 (\*.p7b) or DER (.der or .cer) encoded file"**,
   click **Add File**, select the file, **Open**, then **Import**. The entry appears in the
   Certificates table.
4. **The platform CA file needs converting first.** `ca.crt` at
   https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt is a **PEM bundle of five root
   certificates** (Amazon Root CA 1–4 and Starfield Services Root CA G2 — the endpoint's
   certificate chains to Amazon Trust Services). SonicOS imports PKCS#7 or DER, not PEM, so
   convert the bundle on any machine with OpenSSL:

   ```bash
   curl -fsSL https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt -o fluency-ca.pem
   openssl crl2pkcs7 -nocrl -certfile fluency-ca.pem -outform DER -out fluency-ca.p7b
   ```

   Import `fluency-ca.p7b`. (A single root can instead be converted with
   `openssl x509 -in fluency-ca.pem -outform DER -out fluency-ca.cer`, but that takes only the
   first certificate in the bundle.)
5. **Do not** reach for **Ignore TLS Certificate Error** as the fix. It disables validation, which
   is most of what TLS was buying. Use it only to prove a diagnosis, then undo it.

### 3.3 — Add the syslog server

**Device → Log → Syslog → Syslog Servers tab → Add.** The dialog fields, in order:

| Field | What to set | Notes |
|---|---|---|
| **Event Profile** | `0` unless you are deliberately splitting traffic across servers | 0–23 (24 groups); **max 7 syslog servers per group**. A category is mapped to a profile in §3.5 |
| **Name or IP Address** | the address object from §3.1 | dropdown of address objects |
| **Protocol** *(SonicOS 8 only)* | **TLS** (preferred) / TCP / UDP | UDP is the default; the port auto-fills **514** for UDP/TCP and **6514** for TLS |
| **Port** | **the port from Step 1** | override the auto-filled default if the platform's port differs — this is the single most common mistake |
| **Ignore TLS Certificate Error** *(SonicOS 8, TLS)* | leave **off** | see §3.2 |
| **Server Type** | **Syslog Server** | the other option, **Analyzer**, is for SonicWall's own Analyzer/GMS |
| **Syslog Format** | **Default** — see the format note below | options: Default, WebTrends, Enhanced Syslog, ArcSight |
| **Syslog Facility** | leave the factory default (**Local Use 0**) unless the customer standardizes on another | full facility list available |
| **Syslog ID** | leave **`firewall`**, or set a per-firewall string if several SonicWalls feed the same site | 0–32 alphanumeric/underscore characters; emitted as `id=<value>` on every message |
| **Event Rate Limiting** / **Data Rate Limiting** | leave disabled unless the customer needs a cap | defaults when enabled: 1000 events/s, 10,000,000 bytes/s |
| **Local Interface** / **Outbound Interface** | leave unset unless the customer routes management traffic over a specific interface | |

Click **Add**, then **Accept/Save** the page.

> **Syslog Format — read this before choosing.**
> **Fluency does not publish which format the `SonicWallFWLog` parser expects, and we could not
> verify it (UNVERIFIED).** Start with **Default**, the SonicOS factory setting, because it is what
> an unconfigured firewall emits and therefore the most likely parser target. Do **not** pick
> ArcSight or WebTrends for this connector — those reshape the message for other products.
> SonicWall's own KB tells customers to pick **Enhanced**, but that KB is about feeding SonicWall
> Analytics/GMS, not Fluency, so it is not evidence about this parser.
> **Diagnostic:** if rows arrive in the datalake but fields are unparsed or collapse into a raw
> message blob, switch the format to **Enhanced Syslog**, wait for fresh events, and re-check. If
> neither renders correctly, ask Fluency support which format `SonicWallFWLog` expects rather than
> guessing a third.

### 3.4 — Global syslog settings (same page, Syslog Settings)

- **Enhanced Syslog / ArcSight field selection** — if (and only if) you selected one of those
  formats, the Configure icon opens a field picker. All options are selected by default; **Host**
  and **Event ID** are fixed. Leave everything enabled — trimming fields here is what silently
  removes columns from the datalake later.
- **Display Syslog Timestamp in UTC** — recommended when the firewall's local time zone is not
  UTC, so datalake timestamps line up without guessing an offset.
- **Enable NDPP Enforcement for Syslog Server** — leave off unless the customer is under an NDPP
  compliance regime; it is the one setting on the page that is not per-server.
- Under SonicWall GMS management the format is forced to **Default** and the ID to **firewall**,
  and both fields grey out — expected, not a fault.

### 3.5 — Choose what gets forwarded

**Device → Log → Settings.** This page, not the syslog page, decides which events leave the box.

1. **Logging Level** (top of the page) — the priority floor. Options run Emergency (highest) down
   to Debug; the default is **Inform**. Events below the level are not logged at all, so they can
   never reach syslog. Leave it at Inform unless the customer asks for more or less.
2. **Alert Level** — separate control for alerting; unrelated to syslog delivery.
3. The table lists **Category → Group → individual Event**, with columns **Priority, GUI, Alert,
   Syslog, IPFIX, Email**. The **Syslog** checkbox is what marks an event for forwarding. It can
   be toggled at category, group or single-event level, and the Priority can be overridden at the
   same three levels.
4. To send everything a normal firewall generates, leave the factory selection alone and only add
   categories the customer explicitly wants. If they want the noisy ones off (typically high-volume
   connection logging), clear the **Syslog** checkbox for that category rather than raising the
   Logging Level, which would also stop local logging.
5. **Event Profile mapping (only if you used a profile other than 0):** edit the category and set
   **Use This Syslog Server Profile** to the profile number you gave the server in §3.3. Events
   whose profile does not match the server's profile do not go to that server.

### 3.6 — Save

**Accept / Save** on each page you touched. SonicOS applies syslog changes without a reboot.

### SonicOS 6.5 differences

- Syslog server: **Manage | Log Settings | SYSLOG** → **Syslog** tab → **Add** — same field set
  (name/IP, format, facility, ID); **no protocol selector, UDP only**.
- Packet capture for verification: **Investigate | Packet monitor → Configure** (instead of
  Monitor | Packet Monitor → General).

**Deliverables from this section:** none to collect — once the page is accepted, events flow on
their own. Note the **Syslog Format** and **Syslog ID** actually chosen; both matter when
diagnosing unparsed rows.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing connectors
  from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), the endpoint
  domain/port/protocol, and the **SonicOS version + syslog format chosen** so a later parsing
  question is answerable without re-interviewing the admin. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of minutes
  of the firewall accepting the change, *provided the firewall is logging something*. A firewall
  behind a quiet link at 2am legitimately produces little; compare against the device's own
  **Monitor → Logs → System Logs** before judging. Mark ⏳ until either rows land or the device's
  own log shows events that never arrived — only the latter is ❌.
- **Rows-but-garbled is not success.** If the count is non-zero but fields are unparsed, report it
  as ⏳ with the format diagnostic from §3.3, not ✅.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "SonicWallFWLog",
  "instance": "sonicwallfwlog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "<tls|tcp|udp>",
  "sonicOsVersion": "<e.g. 8.0 / 7.1 / 6.5>",
  "syslogFormat": "Default",
  "syslogId": "firewall"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **The firewall's own log is the ground truth.** Open **Monitor → Logs → System Logs** — it shows
   what the firewall has actually recorded. Anything the datalake is missing must be visible here
   first; if this page is empty too, the problem is logging configuration (§3.5), not delivery.
3. **Prove the firewall is emitting packets** (SonicWall's documented check — the closest thing to
   a test-syslog button; see the failure modes for why there isn't one):
   - **Monitor → Packet Monitor → General.**
   - *Monitor Filter:* Ether Type(s) `IP`, IP Type(s) `UDP` (use `TCP` if you configured TCP/TLS),
     Destination Port(s) = the port from Step 1, enable **Bidirectional Address and Port Matching**.
   - *Display Filter:* enable all checkboxes.
   - *Advanced Monitor Filter:* enable **Monitor Firewall Generated Packets** and **Monitor
     Intermediate Packets** — without the first one, firewall-originated syslog is invisible.
   - **OK → Start Capture.** Packets to the endpoint address mean the firewall is doing its job and
     the problem, if any, is on the path or the listener.
   - SonicOS 6.5: **Investigate | Packet monitor → Configure**.
4. Count rows in the SonicWall table over the last hour via the **`ingext-kql`** skill (confirm the
   live table name with `list_data_tables` first). Rows should trail the firewall's own log by
   seconds-to-minutes.
5. **Inspect a row, don't just count it.** Confirm fields are parsed into columns rather than
   sitting in a raw blob — that is what catches a wrong Syslog Format while the count looks fine.

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows, firewall's System Logs shows events, protocol is UDP | UDP drops silently — the firewall reports nothing. Run the Packet Monitor capture (Verification §3). Packets present → the path or listener is the problem (egress rule, wrong port, listener not enabled). No packets → re-check the syslog server entry is **enabled** and the category's **Syslog** checkbox in Device → Log → Settings. |
| Zero rows on SonicOS 8 with TCP/TLS | TCP and TLS surface connection state on the Syslog Servers page — read it. A failed TLS handshake is almost always trust (§3.2) or the wrong port (6514 auto-fills; the platform's TLS port may differ). |
| Wrong port | The dialog auto-fills 514 (UDP/TCP) or 6514 (TLS). If the platform's listener uses another port and nobody overrode the default, nothing arrives and nothing errors on UDP. Re-read Step 1's port. |
| Listener/protocol mismatch | Site has `syslog_tls` only but the firewall is SonicOS 7.x (UDP-only): `syslog_update_config` to add `syslog_udp` — do **not** re-register the site config, and leave the TLS listener alone for the devices using it. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. If unsure whether one exists, `syslog_get_config` first, always. |
| Site config exists → tempted to re-register | Don't. `syslog_update_config` adds a listener; re-registering is not a repair mechanism and risks the listeners other devices depend on. |
| TLS certificate/trust failure | The endpoint's chain is Amazon Trust Services. If the firewall's built-in CA list doesn't cover it, import the converted bundle per §3.2. "Ignore TLS Certificate Error" is a diagnosis aid, not a fix. |
| Rows arrive but fields are unparsed | Wrong **Syslog Format**. Fluency's expected format for `SonicWallFWLog` is **UNVERIFIED**; try Default first, then Enhanced Syslog, and confirm with Fluency support before trying anything else. Do not use ArcSight or WebTrends for this connector. |
| Fields missing from otherwise-parsed rows | Someone trimmed the Enhanced Syslog / ArcSight field picker (§3.4). Re-enable all fields. |
| Events visible in GUI but never forwarded | The category/group/event's **Syslog** checkbox is clear, or its priority is below the **Logging Level** (default Inform), or its **Use This Syslog Server Profile** doesn't match the server's Event Profile (§3.5). |
| Egress blocked | Firewall-originated traffic still has to leave: confirm outbound to the endpoint on the configured port/protocol is permitted here and upstream. This is the most common "everything looks right" cause. |
| Address object won't resolve | An FQDN address object depends on the DNS servers under **Network → DNS**. Substitute a Host object with the resolved IP as a test — if that works, fix DNS rather than leaving the IP hard-coded. |
| Timestamps off by hours | Enable **Display Syslog Timestamp in UTC** (§3.4), or fix the firewall's time zone/NTP. |
| Several SonicWalls, one connector | Point each at the same endpoint host/port; they share the one connector. Give each a distinct **Syslog ID** so senders are distinguishable. Don't create per-firewall instances unless the data shows otherwise. |
| "Where is the send-test-syslog button?" | There isn't one in the documentation we verified (**UNVERIFIED**: no test-syslog mechanism is documented for SonicOS). Use the Packet Monitor capture plus a benign, self-generated event — an admin logout/login or any change that writes to the firewall's own log — and compare against Monitor → Logs → System Logs. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — reconnect, or read the endpoint from the platform UI's Connectors page instead. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **UDP and TCP syslog are unencrypted in transit.** On SonicOS 7.x/6.5 that is the only option the
  firewall offers. Firewall logs are not credentials, but they map internal addressing, users, VPN
  peers and blocked-threat detail — an on-path party could read or spoof them. Tell the customer
  plainly, and if it is unacceptable the answer is SonicOS 8 with TLS or a private path, not a
  workaround.
- **Prefer TLS on SonicOS 8**, and do not paper over a handshake failure with **Ignore TLS
  Certificate Error** — that setting silently downgrades the connection to encryption without
  authentication.
- The platform CA bundle is public trust material, not a secret; the syslog endpoint host/port are
  not credentials either, but they name an open ingestion door — no need to publish them beyond the
  people configuring devices.
- Nothing in this procedure requires a firewall credential to be shared with the agent, and none
  should be. If the admin offers CLI/API access, decline — the documented path is the web UI.
- Raising the Logging Level to Debug to "see more" ships far more data than the customer expects,
  including material they may consider sensitive. Change it deliberately, not as a diagnostic
  reflex.

---

## Layout

```
setup-sonicwall-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← SonicWall technical-documentation + KB citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
