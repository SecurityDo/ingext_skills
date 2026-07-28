---
name: setup-cisco-meraki-syslog
version: 1.0.0
description: >-
  Set up Cisco Meraki router / firewall (MX, and optionally MS / MR) event import into Fluency /
  Ingext via syslog. The agent performs the whole Fluency side itself: it resolves the site's
  syslog endpoint via the syslog MCP calls — syslog_get_config to read the existing transport,
  syslog_register_config to create it if the site has none (once per site, ever),
  syslog_update_config to enable the listener the Meraki network will use — and installs the
  "Cisco Meraki Syslog" connector (CiscoMerakiFWLog). The Meraki side is Dashboard-only (no device
  CLI): an admin adds a syslog server under Network-wide → Configure → General and picks the roles
  that decide what is forwarded. MX appliances on MX26.1+ can do TCP and encrypted (TLS) syslog —
  prefer TLS there and upload the platform CA bundle under Organization → Certificates; older MX,
  and all MS / MR, are UDP. Syslog is configured PER NETWORK, so a customer with many Meraki
  networks repeats it per network (or uses a configuration template / the Dashboard API).
  SELF-CONTAINED: it ends by creating the connector itself — when routed from customer-onboarding,
  do NOT chain into add-connector afterward. Triggers: "connect our Meraki firewall to Ingext",
  "forward Meraki MX logs to Fluency", "Meraki syslog into the datalake", "set up the Cisco Meraki
  connector", "get our Meraki dashboard logs into Fluency". Do NOT use for other syslog vendors
  (Cisco ASA is setup-cisco-asa-syslog; Peplink is setup-peplink-syslog; FortiGate is
  setup-fortigate-syslog; Palo Alto is setup-paloalto-syslog; SonicWall is setup-sonicwall-syslog;
  Check Point is setup-checkpoint-syslog; Sophos is setup-sophos-firewall-syslog or
  setup-sophos-utm-syslog), and
  not for Meraki API/webhook-based integrations — this is the syslog path only.
---

# Set up Cisco Meraki syslog import

Import a **Cisco Meraki** network's events — MX appliance event log, firewall flows, URL requests
and IDS/security alerts, plus optionally MS switch and MR wireless events — into Fluency / Ingext
via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`CiscoMerakiFWLog`** ("Cisco Meraki Syslog"), which
  parses the Meraki stream.
- **Meraki side (customer's Dashboard):** Meraki is cloud-managed — there is no device CLI. An
  admin adds a syslog server under **Network-wide → Configure → General** and selects the
  **roles** that decide what gets sent. **This is per network.**

**Transport, verified:** Meraki supports **UDP**, and — on **MX Security Appliances running
MX26.1 firmware or higher** — **TCP** and **encrypted (TLS) syslog** (RFC 5425). Encrypted syslog
is **MX-only today**; Meraki's documentation says MS switches and MR access points will support it
"in a future release", and Z-series Teleworker Gateways do not support it at all. **Prefer TLS
when the MX qualifies.** Citations live in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. Enable the listener this Meraki network will use (`syslog_tls` preferred on MX26.1+, else `syslog_udp`) with `syslog_update_config` if missing |
| Ingext | Connector | Template **`CiscoMerakiFWLog`** ("Cisco Meraki Syslog"), instance e.g. `ciscomerakifwlog`, parameters `datalake` (default `managed`) and `index` (default `Meraki`) |
| Meraki | Syslog server entry | **Network-wide → Configure → General → Syslog servers**: server address + port + protocol + roles. **One entry per network** |
| Meraki | (TLS only) CA bundle | The platform CA certificate uploaded under **Organization → Certificates** and selected on the encrypted syslog server entry |

Nothing here is billable on either side. Meraki's own documentation warns that syslog — **flows
especially** — produces a large volume; role selection is the volume control (Step 3).

---

## Prerequisites

- Dashboard access with rights to edit **Network-wide → Configure → General** for each network
  that will forward, and — for TLS — rights on **Organization → Certificates** (an
  organization-level page). The agent cannot click the Dashboard.
- The Meraki devices must be able to reach the syslog endpoint on the chosen port/protocol. Meraki
  documents three paths (LAN / WAN / AutoVPN) with different source interfaces — see Step 3.
- **For TLS or TCP:** an **MX** running **MX26.1 or higher**. Check the running version at
  **Organization → Monitor → Firmware upgrades** (the *Schedule upgrades* tab has a *Current
  firmware version* column), or per network at **Network-wide → Configure → General** under
  *Firmware upgrades*.
- **For an FQDN server address:** also **MX26.1+** — below that, the server address must be an IP.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the Dashboard (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever holds Dashboard access through the
  syslog server entry (and the CA upload if TLS), and verify rows.
- **(b) Runbook only:** print the full procedure — including the resolved endpoint host/port,
  protocol, and the CA certificate URL if TLS — for the network admin to apply later. Offer to
  resume verification when they return.

Either way, establish **how many Meraki networks** are in scope before starting — the Dashboard
work repeats per network, and that changes the size of the job (Step 3, "Many networks").

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **Decide which listener this Meraki network needs**, before touching anything:
   - **MX on MX26.1+** → **`syslog_tls`**. This is the preferred path: Meraki's encrypted syslog
     is TLS over TCP per RFC 5425.
   - **MX below MX26.1, or MS switches / MR access points** → **`syslog_udp`**. TCP and TLS are
     documented as MX26.1+ features, and encrypted syslog is documented as MX-only today.
   - Mixed estate → you may need **both**: an MX entry on TLS and a separate entry for
     switch/wireless roles on UDP (Meraki requires separate server entries anyway — see Step 3).
3. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
4. **Configuration exists but lacks the listener you need** → **`syslog_update_config`** to enable
   it. Leave the existing listeners untouched; other devices depend on them.
5. **Capture the deliverables:** the endpoint **domain**, the **port**, and the **protocol**.
   These go into the Dashboard in Step 3.

> **TLS certificate:** when using the `syslog_tls` listener, give the Dashboard admin the platform
> CA certificate — https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt — and walk them
> through Step 3's "Trust the platform CA" section. This is **required**, not optional: by default
> an MX validates the syslog server's certificate against the **Common CA Database (CCADB)**,
> which will not contain a private platform CA, so an unuploaded CA means the TLS session does not
> establish.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`CiscoMerakiFWLog`** template ("Cisco Meraki
   Syslog", category `onpremise`) and use its **current** schema. In the 2026-07 snapshot it takes
   `datalake` (default `managed`) and `index` (default `Meraki`) — the live template is the truth.
2. **`list_connectors`** — if a `CiscoMerakiFWLog` instance already exists, the site is likely
   already ingesting Meraki syslog; additional Meraki networks just point at the same endpoint
   (Step 3) and share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `CiscoMerakiFWLog`
   - `instance`: `ciscomerakifwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Cisco Meraki Syslog`
   - `inputParameters`: **every** parameter the live template defines — `datalake` (`managed`) and
     `index` (`Meraki`) unless the operator wants otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Cisco Meraki
Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the Meraki Dashboard at it (guided)

Meraki devices are cloud-managed; **everything below happens in the Dashboard**, not on a device
CLI. Do this **for each network** whose devices should forward.

### 3.1 Add the syslog server

1. Go to **Network-wide → Configure → General**. The syslog controls live in the **Reporting**
   section. *(In single-device-type networks — Appliance-only, Switch-only or Wireless-only — the
   section is labelled **Logging** instead of **Reporting**.)*
2. Select **Add a syslog server**.
3. **Server address:** the endpoint **domain** from Step 1. An **FQDN requires MX26.1+**; on older
   firmware enter the endpoint's **IP address** instead.
4. **Port:** the port from Step 1. Meraki's own example configuration uses UDP 514 — use the
   platform's actual port, not 514, unless they match.
5. **Protocol:** leave **UDP** for MS / MR / pre-26.1 MX. Choose **TCP** if you are going to
   enable TLS (next section) — TLS is only offered over TCP.
6. **Roles:** select what this server should receive — see 3.2. This is the single most important
   choice on the page.
7. Select **Update syslog servers** to save.

You can define **multiple syslog servers per network**, and you will need more than one entry if
you are mixing an encrypted MX feed with switch/wireless roles.

### 3.2 Roles — what actually gets forwarded

Roles are Meraki's message categories, and they are product-specific. Verified from Meraki's
documentation:

| Role | Sent by | What it carries |
|---|---|---|
| **Event log** (`Appliance event log` / `Switch event log` / `Wireless event log`) | MX, MS, MR | A copy of the messages shown under **Network-wide → Monitor → Event log** |
| **Flows** (`Appliance Flows` / `Wireless Flows`) | MX, MR | Inbound/outbound flows with source, destination, ports and the matched firewall rule. **Highest volume by far** |
| **URLs** (`Appliance URLs` / `Wireless URLs`) | MX, MR | One entry per HTTP GET request. High volume |
| **IDS Security Alerts** / *Appliance Security Events* | **MX only** | IDS/IPS signature alerts |
| **Air Marshal events** | **MR only** | Detected/contained wireless traffic |

Product coverage, verbatim from Meraki: the MX sends four main roles — Event Log, IDS Security
Alerts, URLs, Flows; MR access points send the same roles **except** IDS Security Alerts and add
Air Marshal events; **MS switches currently support only Event Log messages**.

Naming note: with **MX26.1**, the `URLs` role split into **Appliance URLs** / **Wireless URLs**
and `Flows` split into **Appliance Flows** / **Wireless Flows**, selectable per product.
Pre-existing configurations that had `URLs` or `Flows` now show both halves selected. (The
Dashboard API still accepts the older strings — `Appliance event log`, `Switch event log`,
`Wireless event log`, `Air Marshal events`, `Flows`, `URLs`, `IDS alerts`, `Security events`.)

**For this connector** — `CiscoMerakiFWLog` is "Cisco Meraki Router / Firewall Events" — start
with the **appliance** roles: **Appliance event log** plus **IDS Security Alerts / Security
events**. Add **Appliance Flows** only if the customer actually wants per-flow firewall records
and has budgeted for the volume; add **Appliance URLs** only if they want per-request URL
telemetry. Switch and wireless roles are optional extras and land in the same stream.

**Flow-log volume control:** if **Appliance Flows** is enabled, logging is still per firewall
rule — turn it on or off for individual rules at **Security & SD-WAN → Configure → Firewall**,
in the **Syslog** column. Use this rather than dropping the whole role when only some rules matter.

### 3.3 Encrypted (TLS) syslog — MX26.1+ only

Do this when Step 1 resolved to the `syslog_tls` listener.

1. On the syslog server entry, set the **protocol to TCP** — TLS encryption is only supported
   over TCP.
2. Check the **Encrypted (TLS) syslog** checkbox (it only becomes available once TCP is selected).
3. **Roles on an encrypted entry:** because encrypted syslog is MX-only today, configure **only**
   **Appliance Event log**, **Appliance Flows** and/or **Appliance URLs** on that entry. If the
   customer also wants Switch or Wireless roles, **add a separate syslog server entry** for those.
4. Select **Update syslog servers**.

**Trust: try it without uploading anything first.** By default the MX validates the syslog
server's certificate against the **Common CA Database (CCADB)**. The platform CA file
(https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt) is a bundle of **five public
roots** — Amazon Root CA 1–4 and Starfield Services Root CA G2, the Amazon Trust Services roots
behind AWS-issued certificates — so the endpoint certificate is **publicly trusted** and CCADB
should already validate it. Don't do certificate work you don't need:

1. Configure the encrypted entry and check whether events arrive.
2. **Only if the handshake fails**, upload the bundle as a CA bundle on **Organization →
   Certificates**, then use **Select a certificate** on the syslog server entry to choose it.
   (Reasons it might: the device's CCADB snapshot lags, or the customer's policy is to pin.)

Uploading it is also a legitimate deliberate choice — it **pins** trust to the Amazon roots
instead of the whole public-CA set, which is narrower. Do that on purpose, not as a workaround.

> **Not a client certificate.** The bundle authenticates the *server* to the MX, one way. It
> cannot satisfy a listener that demands a client certificate.

### 3.4 Make sure the traffic can actually get there

Meraki documents three delivery paths, each sourcing from a different interface:

- **Server reachable over the LAN** — the MX sources from the VLAN interface where the server
  lives (or the transit VLAN interface if it is only reachable by static route).
- **Server reachable over the WAN** — the MX sources from the **public (WAN) interface**. This is
  the normal case for a cloud ingestion endpoint; confirm outbound egress is permitted.
- **Server reachable over AutoVPN** — the MX sources from the interface of the **highest VLAN
  participating in AutoVPN**, and the traffic is subject to the **site-to-site outbound firewall
  rules**, so an allow rule may be needed: **Security & SD-WAN → Configure → Site-to-site VPN →
  Organization-wide settings → Add a rule**.

Two further documented notes worth passing on: if syslog crosses a VPN, the source IP appears as
`6.X.X.X` when no VLANs are in VPN mode / the MX is in passthrough or Routed-NAT-single-LAN mode;
and if **full-tunnel VPN** is configured, use **VPN Full-Tunnel Exclusion** together with
encrypted syslog to reach a syslog server on the internet.

### 3.5 Many networks

**Syslog is configured per network** — the Dashboard page is under *Network-wide*, and the
Dashboard API models it as `PUT /networks/{networkId}/syslogServers`. A customer with 40 Meraki
networks needs the entry in all 40. Two documented ways to avoid 40 manual edits:

- **Configuration templates** — syslog server entries can be carried in a template and inherited
  by bound networks. *Documented caveat:* encrypted syslog deployed in a configuration template
  **before 6 March 2026** did not work (the network sent no syslog at all); the fix is to delete
  and re-add the encrypted syslog server entry in the template.
- **The Dashboard API** — `PUT /networks/{networkId}/syslogServers`, with a body of
  `servers: [{ host, port, roles }]`, scripted across the organization's networks.

Both are Dashboard-side work; the agent guides them but does not perform them.

**Deliverables from this section:** none to collect — once **Update syslog servers** is clicked,
events flow on their own.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (the template's
  `index` default is `Meraki` — confirm the live name with `list_data_tables`), the endpoint
  domain/port/protocol, and **how many Meraki networks were actually configured versus how many
  exist**. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes of **Update syslog servers**, *when the network logs something*. With only the Event log
  role selected on a quiet network that can legitimately be very little; compare against the
  Dashboard's own **Network-wide → Monitor → Event log** before judging. Mark ⏳ until either rows
  land or the Dashboard's event log shows events that never arrived — only the latter is ❌.
- If some networks are configured and others are not, say so explicitly — a partially onboarded
  Meraki estate reads as "done" in a checklist and silently loses the rest.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "CiscoMerakiFWLog",
  "instance": "ciscomerakifwlog",
  "table": "<confirm live with list_data_tables; template index default 'Meraki'>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "<tls|udp>",
  "merakiRoles": ["Appliance event log", "Security events"],
  "networksConfigured": "<n of m>"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. Open **Network-wide → Monitor → Event log** in the Dashboard — the **Event log** role sends a
   copy of exactly these messages, so this page is the **ground truth** to compare against.
3. Count rows in the Meraki table over the last hour via the **`ingext-kql`** skill (confirm the
   live table name with `list_data_tables` first — the template's `index` default is `Meraki`).
   Rows should trail the Dashboard's event log by seconds-to-minutes.
4. **There is no documented "send a test syslog message" button in the Meraki Dashboard** — the
   syslog documentation describes no test facility. Generate a real, benign event instead and
   watch it appear in both places: e.g. sign out and back in to the Dashboard, or bounce an unused
   switch port / disconnect and reconnect a test client so the event log records it. If
   **Appliance Flows** is enabled, ordinary internet traffic through the MX is itself continuous
   proof.
5. **TLS specifically:** if rows never appear on an encrypted entry, the CA bundle is the first
   suspect — re-check that the uploaded bundle on **Organization → Certificates** is selected on
   *this* server entry, not merely uploaded.

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows, but the Dashboard event log shows events (UDP) | UDP drops silently. Re-check the server address (typo, or an FQDN on pre-MX26.1 firmware, which is unsupported), the port (matches the endpoint's UDP port, not 514 by habit), and that the egress path permits outbound UDP — see Step 3.4 for which interface the MX sources from. |
| Zero rows on an encrypted (TLS) entry | The MX validates the server certificate against **CCADB** unless a CA bundle is uploaded **and selected**. Upload the platform CA under **Organization → Certificates** and select it via **Select a certificate** on that entry. Also confirm the MX is on **MX26.1+** — encrypted syslog is unavailable below it. |
| TLS/TCP option missing, or greyed out | TCP syslog (with or without TLS) requires **MX26.1+**, and encrypted syslog is **MX-only** — MS/MR are documented as "future release", and Z-series Teleworker Gateways do not support it. Use the `syslog_udp` listener for those. |
| Network stopped sending syslog entirely after a firmware change | Documented: an MX configured for encrypted syslog and then **downgraded below MX26.1 sends no syslog at all** and must be reconfigured for unencrypted syslog. |
| Encrypted syslog configured in a configuration template, nothing arrives | Documented issue for templates built **before 6 March 2026** — delete and re-add the encrypted syslog server entry in the template. |
| Site syslog config exists but lacks the listener this network needs | `syslog_update_config` to enable the missing listener — do **not** re-register the site config. Leave existing listeners untouched. |
| No site syslog config at all | `syslog_register_config` — once per site. If unsure whether one exists, `syslog_get_config` first, always. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Only one network's data is arriving | Syslog is **per network**. Repeat Step 3 for every network, or push it via a configuration template / the Dashboard API (Step 3.5). |
| Traffic volume far higher than expected | **Flows** and **URLs** are the culprits (Meraki warns flows especially consume large amounts of storage). Drop those roles, or leave the role on and disable logging per firewall rule at **Security & SD-WAN → Configure → Firewall**, **Syslog** column. |
| Syslog crosses AutoVPN and nothing arrives | Site-to-site outbound firewall rules apply — add an allow rule under **Security & SD-WAN → Configure → Site-to-site VPN → Organization-wide settings**. Note that a syslog-enabled block rule will log every dropped syslog packet, compounding the problem. |
| Wrong table / table name unknown | The template's `index` default is `Meraki`, but `list_data_tables` is the authority. |
| Events arrive garbled / unparsed | Confirm the connector installed is `CiscoMerakiFWLog` (not a generic syslog path) so the Meraki parser handles the stream. Note Meraki replaces any character in a device hostname that is not a letter, number or underscore with an underscore — that is expected, not corruption. |
| Multiple Meraki networks / devices | Point them all at the same endpoint host/port; they share the one connector (senders are distinguished in the data). Don't create per-network connector instances unless the data shows otherwise. |

---

## Security notes

- **UDP and plain TCP syslog are unencrypted and unauthenticated in transit.** For an MX on
  MX26.1+ there is a real alternative — use it. Meraki's encrypted syslog is TLS over TCP per RFC
  5425, and this skill prefers it wherever the firmware allows.
- Where TLS is genuinely unavailable — MS switches, MR access points, MX below 26.1, Z-series —
  say so plainly rather than implying the stream is protected. Flow and URL roles in particular
  carry internal IP addresses and browsing destinations in cleartext; the customer should decide
  knowingly, and can carry the stream over a private path (e.g. an existing AutoVPN tunnel)
  instead.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — no
  need to publish them beyond the people configuring devices.
- The CA certificate uploaded to **Organization → Certificates** is a public certificate, not a
  secret. It is organization-scoped, so uploading it affects every network in that organization
  that selects it — mention that before uploading into a shared MSP organization.
- Dashboard admin rights are the sensitive thing here: the same page that adds a syslog server can
  change reporting for the whole network. Prefer an admin with network-level rights over an
  organization owner for the day-to-day work.

---

## Layout

```
setup-cisco-meraki-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Meraki documentation citations; platform syslog-transport notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
