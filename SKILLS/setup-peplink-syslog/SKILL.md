---
name: setup-peplink-syslog
version: 1.0.0
description: >-
  Set up Peplink / Pepwave router and firewall event import into Fluency / Ingext via syslog.
  The agent performs the whole Fluency side itself: it resolves the site's syslog endpoint via
  the syslog MCP calls — syslog_get_config to read the existing transport, syslog_register_config
  to create it if the site has none (once per site, ever), syslog_update_config to enable the UDP
  listener Peplink requires — and installs the "Peplink Router/Firewall Syslog" connector
  (PeplinkFWLog). The router side is portal-only and small: the operator enables Remote Syslog
  under System → Event Log with the endpoint host and port (Peplink sends syslog over UDP; there
  is no TLS/TCP option on the device). SELF-CONTAINED: it ends by creating the connector itself —
  when routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers:
  "connect our Peplink router to Ingext", "forward Pepwave MAX logs to Fluency", "Peplink syslog
  into the datalake", "set up the Peplink connector". Do NOT use for other syslog vendors
  (FortiGate, Palo Alto, Meraki, SonicWall, Cisco ASA, Check Point, Sophos — no dedicated skills
  yet; route those to add-connector), and not for Peplink devices' own health monitoring — this
  imports the router's event log, nothing more.
---

# Set up Peplink / Pepwave syslog import

Import a **Peplink / Pepwave** router or firewall's event log — WAN state changes, system and
admin events — into Fluency / Ingext via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain,
  port, protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then
  shared by every syslog integration that follows.
- **Fluency connector (yours):** install **`PeplinkFWLog`** ("Peplink Router/Firewall Syslog"),
  which parses the Peplink stream. The template takes no parameters.
- **Router side (customer's admin UI):** enable **Remote Syslog** under **System → Event Log**,
  pointed at the endpoint host + port. Peplink delivers syslog over **UDP** — the device offers
  no TCP or TLS option (see `assets/references.md`).

Vendor-side steps are backed by Peplink's manuals and community answers; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. A **UDP** listener must be enabled for Peplink (`syslog_update_config` if missing) |
| Ingext | Connector | Template **`PeplinkFWLog`** ("Peplink Router/Firewall Syslog"), instance e.g. `peplinkfwlog`, no parameters |
| Peplink | Remote Syslog setting | **System → Event Log → Remote Syslog**: enabled, server = endpoint domain, port = the UDP port. Available across Balance / MediaFast / MAX models |

Nothing here is billable on either side.

---

## Prerequisites

- Admin access to the Peplink device's **web admin UI** (the operator or their network admin —
  the agent cannot click it).
- The device must be able to reach the syslog endpoint over **UDP** on the configured port —
  check outbound firewall rules on the path.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads
  the endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the router (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever has the Peplink admin UI through
  the one Remote Syslog screen, and verify rows.
- **(b) Runbook only:** print the full procedure — including the endpoint host/port once you've
  resolved it — for the network admin to apply later. Offer to resume verification when they
  return.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Configuration exists but no UDP listener** (e.g. only `syslog_tls` is enabled) →
   **`syslog_update_config`** to enable **`syslog_udp`** — Peplink can only send UDP.
   Leave the existing listeners (TLS/TCP) untouched; other devices may be using them.
4. **Capture the deliverables:** the endpoint **domain**, the **UDP port**, and the protocol.
   These go into the router in Step 3.

> **TLS note (other devices, not Peplink):** when a syslog source *does* support TLS, prefer the
> `syslog_tls` listener and give its admin the platform CA certificate:
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
> Peplink's remote syslog has no TLS option, so for this skill the UDP listener is the path.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`PeplinkFWLog`** template ("Peplink
   Router/Firewall Syslog") and use its current schema; in the 2026-07 snapshot it has **no
   parameters**, but the live template is the truth.
2. **`list_connectors`** — if a PeplinkFWLog instance already exists, the site is likely already
   ingesting Peplink syslog; additional routers just point at the same endpoint (Step 3) and
   share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `PeplinkFWLog`
   - `instance`: `peplinkfwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Peplink Router/Firewall Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Peplink
Router/Firewall Syslog** — and read the syslog endpoint host/port from the platform's
Connectors page.

---

## Step 3 — Point the router at it (guided)

In the Peplink / Pepwave **web admin UI** (applies across Balance / MediaFast / MAX):

1. Go to **System → Event Log**.
2. **Remote Syslog:** check/enable it.
3. **Remote Syslog Host** (server address): the endpoint **domain** from Step 1 (hostname or IP
   are both accepted by the device).
4. **Port:** the **UDP port** from Step 1. The device's default is 514 — change it if the
   endpoint uses a different port.
5. **Save / Apply Changes.**

Delivery is **UDP** — connectionless, so the router gives no error if the host or port is wrong;
verification (below) is the only confirmation. The event log carries device events (WAN
up/down, system and admin events), so volume is modest on a healthy, quiet router.

**Deliverables from this section:** none to collect — once Apply is clicked, events flow on
their own.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), and the endpoint
  domain/port/protocol so the summary shows where the device points. None of these are
  credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes of **Apply**, *when the router logs something*. A quiet router legitimately produces
  little; compare against the device's own **System → Event Log** page before judging. Mark ⏳
  until either rows land or the device-side log shows events that never arrived — only the
  latter is ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "PeplinkFWLog",
  "instance": "peplinkfwlog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "udp"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. Open the device's **System → Event Log** page — it shows what the router has actually
   logged. That is the ground truth to compare against.
3. Count rows in the Peplink table over the last hour via the **`ingext-kql`** skill (confirm
   the live table name with `list_data_tables` first). Rows should trail the device's own event
   log by seconds-to-minutes.
4. If the device log is quiet, generate a benign event rather than waiting — e.g. sign out and
   back in to the admin UI, or make a trivial no-impact settings change — then re-check.

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows, but the device's Event Log shows events | UDP drops silently. Re-check host (typo, wrong domain), port (matches the endpoint's UDP port, not the 514 default if different), and that the path allows outbound UDP to the endpoint. |
| Site syslog config exists but only TLS/TCP listeners | `syslog_update_config` to enable the UDP listener — do **not** re-register the site config. Leave existing listeners untouched. |
| No site syslog config at all | `syslog_register_config` — once per site. If unsure whether one exists, `syslog_get_config` first, always. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Multiple Peplink devices | Point each at the same endpoint host/port; they share the one connector (senders are distinguished in the data). Don't create per-device instances unless the data shows otherwise. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |
| Events arrive garbled / unparsed | Confirm the connector installed is `PeplinkFWLog` (not a generic syslog path) so the Peplink parser handles the stream. |
| Customer asks for encrypted transport | The device has no TLS syslog option (see references). Options are accepting UDP for this source or carrying it over a private path (e.g. an existing site-to-site tunnel) — a network-design decision for the customer, not this skill. |

---

## Security notes

- **UDP syslog is unencrypted and unauthenticated in transit.** Router event logs are
  low-sensitivity compared to credentials, but the customer should know the stream crosses the
  network in cleartext and an on-path party could read or spoof it. If that is unacceptable,
  see the failure-modes row above — the device itself cannot do TLS.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door —
  no need to publish them beyond the people configuring devices.
- The TLS CA certificate link in Step 1 is for *other*, TLS-capable syslog sources at the same
  site; nothing Peplink-side consumes it.

---

## Layout

```
setup-peplink-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Peplink manual + community citations; platform syslog-transport notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
