---
name: setup-sophos-firewall-syslog
version: 1.0.0
description: >-
  Set up Sophos Firewall (the current XG / XGS line running Sophos Firewall OS, SFOS) event import
  into Fluency / Ingext via syslog. The agent performs the whole Fluency side itself: it resolves
  the site's syslog endpoint via the syslog MCP calls — syslog_get_config to read the existing
  transport, syslog_register_config to create it if the site has none (once per site, ever),
  syslog_update_config to enable the listener this firewall will speak — and installs the "Sophos
  Firewall Syslog" connector (SophosFWLog). The firewall side is web-admin-only: add a syslog
  server under System services → Log settings (SFOS supports TLS via "Secure log transmission", so
  prefer the TLS listener), then tick the log categories to forward in the Log settings matrix.
  SELF-CONTAINED: it ends by creating the connector itself — when routed from customer-onboarding,
  do NOT chain into add-connector afterward. Triggers: "connect our Sophos firewall to Ingext",
  "forward Sophos XGS logs to Fluency", "Sophos SFOS syslog into the datalake", "set up the Sophos
  Firewall connector", "ingest Sophos XG firewall logs". Do NOT use for Sophos UTM 9 (the legacy
  Astaro-lineage appliance, WebAdmin → Logging & Reporting) — that is setup-sophos-utm-syslog with
  a different connector (SophosUTMSyslog). Do NOT use for Sophos Central / Sophos EDR / Intercept X
  endpoint data, which arrives over the Sophos Central API — that is setup-sophos-central-connector
  (SophosEDR). This skill imports the firewall's own event stream, nothing else.
---

# Set up Sophos Firewall (SFOS) syslog import

Import a **Sophos Firewall**'s event log — firewall traffic, IPS, malware, web/app filtering,
admin and authentication events, threat-feed hits — into Fluency / Ingext via **syslog**. This is
the current XG / XGS line running **Sophos Firewall OS (SFOS)**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`SophosFWLog`** ("Sophos Firewall Syslog"), which
  parses the SFOS stream. The template takes no parameters.
- **Firewall side (customer's web admin console):** add a syslog server under **System services →
  Log settings**, then **tick the log categories** to forward to it. SFOS can encrypt the stream
  (**Secure log transmission** = TLS), so prefer the TLS listener where the platform offers one.

Vendor-side steps are backed by Sophos's SFOS 22.0 documentation and its published API reference;
citations live in `assets/references.md`.

> **Not Sophos UTM, not Sophos Central.** Sophos ships three unrelated log sources with similar
> names. Sophos Firewall (this skill, SFOS web admin console, "System services → Log settings")
> ≠ **Sophos UTM 9** (WebAdmin, "Logging & Reporting → Log Settings", `setup-sophos-utm-syslog`)
> ≠ **Sophos Central / EDR** (cloud API, no syslog, `setup-sophos-central-connector`). Confirm
> which one the customer runs before touching anything — the UI paths do not exist on the others.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. The listener this firewall will use must be enabled (`syslog_update_config` if missing) |
| Ingext | Connector | Template **`SophosFWLog`** ("Sophos Firewall Syslog"), instance e.g. `sophosfwlog`, no parameters |
| Sophos Firewall | Syslog server entry | **System services → Log settings → Add**: name, endpoint domain, port, Secure log transmission (TLS), facility, severity, format. Up to **five** syslog servers per firewall |
| Sophos Firewall | Log-category selection | The **Log settings** matrix — one column per syslog server; nothing is forwarded until categories are ticked |
| Sophos Firewall | CA certificate (TLS only) | The platform CA imported under **Certificates → Certificate authorities → Add** so the firewall trusts the endpoint |

Nothing here is billable on either side.

---

## Prerequisites

- Admin access to the firewall's **web admin console** (an administrator with rights over System
  services, Log settings and, for TLS, Certificates — the agent cannot click it).
- The firewall must be able to reach the syslog endpoint outbound on the chosen port and protocol —
  check upstream firewall/ISP rules on the path.
- **Know the SFOS version.** Paths in this skill follow the current SFOS 22.0 help; they have been
  stable across 18.5 → 22.0, but read the on-screen labels if the customer is far behind.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the firewall (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever has the SFOS console through the
  syslog server entry, the category matrix and (if TLS) the certificate import, and verify rows.
- **(b) Runbook only:** print the full procedure — including the endpoint host/port/protocol once
  you've resolved it — for the firewall admin to apply later. Offer to resume verification when
  they return.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Choose the listener this firewall will speak, and prefer TLS.** SFOS supports encrypted
   syslog (the **Secure log transmission** option), so `syslog_tls` is the right target when the
   site has it or can have it. If the configuration lacks the listener you need, enable it with
   **`syslog_update_config`** (`syslog_tls`, else `syslog_udp`). Leave existing listeners
   untouched — other devices depend on them.
4. **Capture the deliverables:** the endpoint **domain**, the **port**, and the **protocol**.
   These go into the firewall in Step 3.

> **TLS decision — read this before promising encryption.** SFOS's *own* documented TLS-syslog
> procedure targets a customer-run `syslog-ng` server and is built around the firewall's **default
> CA**: the server is configured with `peer_verify(required-trusted)` and must hold the firewall's
> `Default.pem`. **That mutual arrangement does not apply here** — the Fluency syslog TLS listener
> neither requests nor accepts client certificates (confirmed by the Fluency team, 2026-07-28), so
> the handshake is one-way: the firewall verifies the server and presents nothing itself. Do not
> try to give Fluency the firewall's `Default.pem`; it has no use for it. What *is* documented and
> reliable, and is what actually decides success here: the firewall verifies the syslog server
> certificate's **Common Name** (and the SAN as well, in LINCE mode) against the address you
> configure, so always enter the endpoint **domain**, never an IP; and an external CA can be
> trusted via **Certificates → Certificate authorities → Add**. Platform CA certificate:
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
> If TLS cannot be made to work, fall back to the `syslog_udp` listener and tell the customer
> plainly that the stream is then unencrypted (see Security notes).

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`SophosFWLog`** template ("Sophos Firewall
   Syslog") and use its current schema; in the 2026-07 snapshot it has **no parameters**, but the
   live template is the truth.
2. **`list_connectors`** — if a SophosFWLog instance already exists, the site is likely already
   ingesting Sophos Firewall syslog; additional firewalls just point at the same endpoint (Step 3)
   and share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `SophosFWLog`
   - `instance`: `sophosfwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Sophos Firewall Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Sophos
Firewall Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the firewall at it (guided)

Everything below happens in the **SFOS web admin console**. Two halves matter equally: the
**syslog server entry** (where logs go) and the **Log settings matrix** (which logs go). Skipping
the second is the single most common reason a "configured" firewall sends nothing.

### 3.1 — Add the syslog server

**System services → Log settings → Add**, then fill in:

| Field | What to enter |
|---|---|
| **Name** | Something recognisable, e.g. `Fluency-Ingext` |
| **IP address/domain** | The endpoint **domain** from Step 1. Use the domain — with TLS the certificate's CN/SAN must match it |
| **Secure log transmission** | **On** when using the TLS listener (encrypts logs over TLS); off for the UDP listener |
| **Port** | The port from Step 1. Sophos's own TLS example uses **6514**; plain syslog conventionally uses **514** — use whatever the endpoint reports, not the convention |
| **Facility** | `DAEMON`, `KERNEL`, `USER`, or `LOCAL0`–`LOCAL7`. `DAEMON` is the usual choice; a distinct `LOCALn` per firewall is a documented way to tag which device a log came from |
| **Severity level** | The **minimum** severity forwarded — the firewall sends that level *and everything more severe*. `Information` is the normal SIEM choice; `Debug` includes absolutely everything; `Error` and above will silently starve the feed |
| **Format** | **`Standard syslog protocol`** (formerly "Central Reporting Format") or **`Device standard format (legacy)`**, a per-module custom layout. See the note below |

Click **Save**.

> **Format — pick deliberately.** Sophos offers exactly these two. Which one the Fluency
> `SophosFWLog` parser expects is **UNVERIFIED**; confirm with Fluency support, or settle it
> empirically (Step: Verification — if rows land but fields are unparsed, switch the format and
> re-check). Data point, labelled secondary: other SIEM integrations for this device (Elastic's
> Sophos integration, Fastvue/WebSpy's Sophos guides) specify **Device standard format**. Start
> there, and change only one thing at a time.

### 3.2 — TLS only: make the firewall trust the endpoint

Skip this if you settled on UDP.

> **What this file is** (inspected 2026-07-28): a PEM bundle of **five public roots** — Amazon
> Root CA 1–4 and Starfield Services Root CA G2, the Amazon Trust Services roots behind
> AWS-issued certificates. The endpoint certificate is therefore **publicly trusted**, so an SFOS
> appliance whose built-in authority list already carries those roots may validate without an
> import — check **Certificates → Certificate authorities** first. Importing remains a valid
> deliberate **pin** to these roots. It is server-trust only, not a client certificate — which is
> the separate open question flagged below.

1. Download the platform CA certificate:
   https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
2. In the console go to **Certificates → Certificate authorities → Add**, upload the CA
   certificate (or paste the certificate data). SFOS auto-detects the format and accepts X.509 in
   `.pem`, `.der`, and `.cer`. When the CA doesn't match a CSR generated on the firewall, SFOS
   asks for the CA's **purpose** — choose **Validation only** (this CA is only used to validate
   the syslog endpoint; "Signing and validation" would require a private key and is meant for
   re-signing/TLS-inspection CAs). Name it, **Save**.
3. Keep the **IP address/domain** field on the endpoint's **domain**: the firewall matches the
   server certificate's Common Name (and SAN, in LINCE mode) against it.
4. If the connection will not establish, do not spend the customer's afternoon on it — record the
   symptom, fall back to the UDP listener (`syslog_update_config`), and flag the mutual-TLS
   question from Step 1 for the Fluency team.

### 3.3 — Select which logs get forwarded (the part everyone forgets)

Back on **System services → Log settings**, scroll to the **Log settings** matrix. It has a column
per destination — **Local reporting**, **Central reporting**, and one per syslog server. Tick the
categories **in your new syslog server's column**. `Select all` is available; a per-category
selection is usually better for volume.

Sophos's published category list, with the sub-selections each one contains (category names as
shown in the UI; sub-selection names as published in the SFOS API reference — the console shows
friendlier labels, so read the screen and match by meaning):

| Category | What it carries | Sub-selections |
|---|---|---|
| **Firewall** | Traffic against the firewall configuration | Firewall/policy rules, Invalid traffic, Local ACLs, DoS attack, Dropped ICMP redirected packet, Dropped source-routed packet, Dropped fragmented traffic, MAC filtering, IP-MAC pair filtering, IP spoof prevention, SSL VPN tunnel, Protected application server, Heartbeat, ICMP error message, Bridge ACLs |
| **IPS** | Detected/dropped attacks | Anomaly, Signatures |
| **Antivirus** | Malware in HTTP, FTP, mail | HTTP, FTP, SMTP, POP3, IMAP, IM, HTTPS, SMTPS, POPS, IMAPS |
| **Anti-spam** | Spam and probable spam | SMTP, POP3, IMAP, SMTPS, POPS, IMAPS |
| **Content filtering** | Web and application filtering | Web filter, Application filter, Web content policy |
| **Events** | Configuration, authentication, system activity | Admin events, Authentication events, System events |
| **Web server protection** | WAF / protection policies | WAF events |
| **Active threat response** | MDR / NDR Essentials / X-Ops / third-party threat-feed hits | Destination match (all traffic), Remote source match (inbound), Local source match (outbound) |
| **Wireless** | Access point and SSID activity | Access points & SSID |
| **Heartbeat** | Endpoint health status | Endpoint status |
| **System health** | CPU, memory, live users, interfaces, disk | Usage |
| **Zero-day protection** | Zero-day protection events | Zero-day protection events |
| **SD-WAN** | SD-WAN profile, SLA, route usage | (not itemised in Sophos's API reference — read the console) |

**A sensible baseline for a SIEM feed:** Firewall, IPS, Antivirus, Content filtering, Events,
Active threat response, Heartbeat, Zero-day protection — plus Anti-spam, Web server protection and
Wireless where those features are actually licensed and used. **System health** is periodic
telemetry rather than security events; take it only if the customer wants it. That split is
operational judgement, not a Sophos recommendation — the customer's retention budget decides.

Two documented gotchas that silently produce empty categories:

- **Active threat response → Remote source match (inbound traffic) is off by default.** Turn it on
  if the customer wants inbound threat-feed hits.
- **Wireless → Access points & SSID is off by default under Local reporting** (wireless logs
  aren't shown in the Log viewer) — it can still be sent to a syslog server, but don't expect the
  device's own Log viewer to corroborate it.

Click **Apply**.

### 3.4 — Turn on logging in the rules themselves

Category selection routes logs; it does not create them. Per Sophos:

- **Firewall rules:** select **Log firewall traffic** in each rule whose sessions should be logged.
- **SSL/TLS inspection rules:** select **Log connections**.
- **Web policy events** appear only when the associated firewall rule has **Log firewall traffic**
  selected.

A firewall with the Firewall category ticked but no rule logging enabled forwards almost nothing.

### 3.5 — Confirm on the device itself

- **Log viewer** — click **Log viewer** in the upper-right corner of any page in the web admin
  console. It opens full-screen, updates automatically, and has module filters. This is the
  ground truth for "did the firewall actually record anything?"
- **Diagnostics → Packet capture** — shows packets passing an interface, which confirms syslog is
  actually leaving the box toward the endpoint. Use it when the Log viewer shows events but
  Fluency shows nothing.

**Deliverables from this section:** none to collect — once **Apply** is clicked, events flow on
their own.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), and the endpoint
  domain/port/protocol so the summary shows where the firewall points. None of these are
  credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes of **Apply**, *provided categories are ticked and rules log*. A firewall is rarely
  quiet, so unlike a small router, an hour of zero rows here is a real signal. Mark ⏳ only inside
  the first few minutes; after that, compare the device's own Log viewer against the datalake and
  work the Failure modes table.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "SophosFWLog",
  "instance": "sophosfwlog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "<tls|udp>",
  "device": "Sophos Firewall (SFOS)",
  "logFormat": "<Device standard format (legacy) | Standard syslog protocol>",
  "categoriesSelected": ["<as ticked in the Log settings matrix>"]
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. Open the firewall's **Log viewer** (upper-right of the web admin console) and filter to a
   module you enabled. That is the ground truth: it shows what the firewall itself recorded, in
   the same window you're querying Fluency for.
3. Count rows in the Sophos Firewall table over the last hour via the **`ingext-kql`** skill
   (confirm the live table name with `list_data_tables` first — the template has no index
   parameter). Rows should trail the Log viewer by seconds-to-minutes.
4. **Need a deterministic test event?** Sophos's **Events** category covers "configuration,
   authentication, and system activities" — so signing out of the web admin console and back in,
   or making a trivial no-impact configuration change, produces an Admin/Authentication event you
   can then look for in both the Log viewer and the datalake. Make sure **Events** is ticked in
   the syslog server's column first.
5. **Rows land but fields look wrong?** That is a format mismatch, not a delivery problem — switch
   **Format** between `Device standard format (legacy)` and `Standard syslog protocol` on the
   syslog server entry and re-check (see 3.1).

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows, Log viewer shows events, transport is UDP | UDP drops silently — no error is ever raised on the firewall. Re-check the domain (typo), the port (must match the endpoint's UDP port, not the 514 convention), and that the path permits outbound UDP from the firewall to the endpoint. Use **Diagnostics → Packet capture** to see whether the packets even leave. |
| Zero rows and no categories ticked | The syslog server entry alone forwards **nothing**. Go back to **System services → Log settings** and tick categories in that server's column (§3.3), then **Apply**. |
| Firewall category ticked, still almost no traffic logs | Rule-level logging is off. Select **Log firewall traffic** in the firewall rules (and **Log connections** in SSL/TLS inspection rules) that should be logged (§3.4). |
| Site syslog config exists but not the listener this firewall needs | `syslog_update_config` to enable it (`syslog_tls`, else `syslog_udp`) — do **not** re-register the site config. Leave existing listeners untouched. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. If unsure whether one exists, `syslog_get_config` first, always. |
| TLS won't establish / certificate errors | Three documented causes: (a) the **IP address/domain** field holds an IP or a name that doesn't match the server certificate's CN — SFOS matches the CN, and the SAN too in LINCE mode; (b) the platform CA was never imported under **Certificates → Certificate authorities → Add**; (c) **not** a client-certificate problem — the Fluency listener neither requests nor accepts one (confirmed 2026-07-28), so exporting the firewall's `Default.pem` will not help; recheck (a) and (b) instead, and fall back to UDP only once both are ruled out. |
| Egress blocked upstream | The firewall's own outbound path to the endpoint may be blocked by an ISP/upstream ACL even though the firewall is happy. Packet capture shows the send; absence of rows plus a clean capture means the drop is off-box. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Firewall already has five syslog servers | SFOS supports **up to five**. Retire an unused entry or ask the customer which destination to replace — there is no sixth slot. |
| Events arrive but are unparsed / half-empty | Format mismatch (§3.1) — switch between `Device standard format (legacy)` and `Standard syslog protocol`. Also confirm the installed connector is `SophosFWLog` and not a generic syslog path. |
| Duplicate events collapse / counts look low | **Log suppression** (Suppress logs on the Log settings page) collapses consecutive identical Firewall entries for local, Central and syslog destinations alike. Check it before hunting for a delivery bug. |
| Usernames / IPs show as ciphertext | **Data anonymization** is on — SFOS can encrypt identities in logs and reports. That's a customer policy decision; the SIEM sees what the firewall sends. |
| Customer actually runs UTM 9 or Sophos Central | Wrong skill: UTM 9 → `setup-sophos-utm-syslog` (`SophosUTMSyslog`); Sophos Central / EDR → `setup-sophos-central-connector` (`SophosEDR`, API not syslog). |
| Multiple Sophos firewalls | Point each at the same endpoint host/port; they share the one connector (senders are distinguished in the data). Consider a distinct `LOCALn` facility per firewall so the origin is obvious. Don't create per-device instances unless the data shows otherwise. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **Prefer TLS.** SFOS supports encrypted syslog; use the `syslog_tls` listener when it can be
  made to work. If you fall back to UDP, say so out loud: **UDP syslog is unencrypted and
  unauthenticated in transit**, and an on-path party could read or spoof it.
- **Firewall logs are not low-sensitivity.** They carry internal IP addressing, usernames,
  visited URLs, and email addresses — more privacy-relevant than a router's event log. That is an
  argument for TLS and for a deliberate category selection rather than `Select all`.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — don't
  publish them beyond the people configuring devices.
- The platform CA certificate is a **public** certificate; importing it is safe. The firewall's
  own **default CA** private key is not — never export or share it, only the `Default.pem`
  certificate if a syslog server needs to trust the firewall.
- Customers with a privacy mandate can turn on SFOS **data anonymization**, which encrypts
  identities in logs and reports. Raise it as an option; note it degrades SIEM correlation.

---

## Layout

```
setup-sophos-firewall-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Sophos SFOS documentation + API reference citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
