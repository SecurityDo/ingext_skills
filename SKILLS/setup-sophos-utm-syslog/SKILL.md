---
name: setup-sophos-utm-syslog
version: 1.0.0
description: >-
  Set up Sophos UTM 9 (the legacy Astaro-lineage UTM / SG appliance) event import into Fluency /
  Ingext via syslog. The agent performs the whole Fluency side itself: it resolves the site's
  syslog endpoint via the syslog MCP calls — syslog_get_config to read the existing transport,
  syslog_register_config to create it if the site has none (once per site, ever),
  syslog_update_config to enable the UDP listener UTM requires — and installs the "Sophos UTM
  Syslog" connector (SophosUTMSyslog). The UTM side is WebAdmin-only: Logging & Reporting → Log
  Settings → Remote Syslog Server, add a syslog server (network definition + service definition),
  then tick the subsystems under Remote Syslog Log Selection. UTM 9 offers no TLS syslog option, so
  the stream is unencrypted. IMPORTANT: Sophos UTM reached END OF LIFE on 30 June 2026 — the skill
  states this up front and points to Sophos Firewall as the vendor's path forward, while still
  getting today's logs flowing. SELF-CONTAINED: it ends by creating the connector itself — when
  routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers: "connect
  our Sophos UTM to Ingext", "forward SG appliance logs to Fluency", "Sophos UTM 9 syslog into the
  datalake", "set up the Sophos UTM connector", "ingest Astaro/UTM firewall logs". Do NOT use for
  Sophos Firewall (the current XG / XGS line running SFOS, "System services → Log settings") —
  that is setup-sophos-firewall-syslog with a different connector (SophosFWLog). Do NOT use for
  Sophos Central / Sophos EDR / Intercept X, which arrives over the Sophos Central API — that is
  setup-sophos-central-connector (SophosEDR).
---

# Set up Sophos UTM 9 syslog import

Import a **Sophos UTM 9** appliance's logs — packet filter, web filtering, IPS, authentication,
system events — into Fluency / Ingext via **syslog**. This is the legacy Astaro-lineage UTM,
managed in **WebAdmin**, running on SG hardware, third-party hardware, a VM, or AWS.

> ## ⚠ Sophos UTM is past end of life
>
> **Sophos UTM reached end of life on 30 June 2026** — all versions, on every platform (SG
> hardware, software/third-party hardware, virtual, AWS). As of today that date has **passed**.
> After it:
>
> - **No further updates to the UTM operating system or software**, and **no patches or fixes for
>   vulnerabilities discovered** from here on.
> - Protection content stops flowing: **anti-virus signature and engine updates** (both Sophos and
>   Avira), **IPS signature and engine updates**, **anti-spam (SASI) updates**, and **URL
>   classification lookups (SXL)**.
> - **Sophos support cannot be offered beyond 31 December 2026**, whatever a license says.
>
> **Say this to the customer before configuring anything.** Then help them anyway: an appliance
> that no longer receives security fixes is a *stronger* reason to get its logs into a SIEM, not a
> weaker one. The vendor's path forward is **Sophos Firewall (SFOS, XGS series)** — when they
> migrate, the syslog work is redone there with **`setup-sophos-firewall-syslog`** and a different
> connector (`SophosFWLog`); the site's syslog endpoint carries over unchanged.
>
> Citations for every date above are in `assets/references.md`.

Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`SophosUTMSyslog`** ("Sophos UTM Syslog"), which parses
  the UTM stream. The template takes no parameters.
- **UTM side (customer's WebAdmin):** enable remote syslog under **Logging & Reporting → Log
  Settings → Remote Syslog Server**, add the server (a network definition + a service definition),
  and tick the subsystems under **Remote Syslog Log Selection**. UTM 9's dialog offers **name,
  server, port only — there is no TLS or encryption option** (see `assets/references.md`).

> **Not Sophos Firewall, not Sophos Central.** Three unrelated Sophos log sources with similar
> names. Sophos UTM 9 (this skill — WebAdmin, "Logging & Reporting → Log Settings") ≠ **Sophos
> Firewall / SFOS** (web admin console, "System services → Log settings",
> `setup-sophos-firewall-syslog`) ≠ **Sophos Central / EDR** (cloud API, no syslog,
> `setup-sophos-central-connector`). If the admin describes a "Log settings" page with a per-server
> category matrix and a Format dropdown, they are on Sophos Firewall — switch skills.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. A **UDP** listener must be enabled for UTM (`syslog_update_config` if missing) |
| Ingext | Connector | Template **`SophosUTMSyslog`** ("Sophos UTM Syslog"), instance e.g. `sophosutmsyslog`, no parameters |
| Sophos UTM | Network definition | A **DNS host** (hostname) or **Host** (IP) definition for the syslog endpoint |
| Sophos UTM | Service definition | A **UDP** service definition for the endpoint port (or the built-in Syslog service if the port is 514) |
| Sophos UTM | Remote syslog server + log selection | **Logging & Reporting → Log Settings → Remote Syslog Server**: enabled, server, port, and the ticked subsystems |

Nothing here is billable on either side.

---

## Prerequisites

- Admin access to the UTM's **WebAdmin** interface (the operator or their network admin — the
  agent cannot click it).
- The appliance must be able to reach the syslog endpoint outbound over **UDP** on the configured
  port — check upstream firewall/ISP rules on the path.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.
- The customer has been told about the end-of-life status above. Do not skip that conversation
  because the ticket only asked for syslog.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the UTM (default):** you resolve/create the syslog
  transport, install the connector, then walk whoever has WebAdmin through the Remote Syslog
  Server tab and the log selection, and verify rows.
- **(b) Runbook only:** print the full procedure — including the endpoint host/port once you've
  resolved it — for the network admin to apply later. Offer to resume verification when they
  return.

Either way, lead with the EoL note and the `setup-sophos-firewall-syslog` follow-on, so the
customer plans the migration rather than discovering it later.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Configuration exists but no UDP listener** (e.g. only `syslog_tls` is enabled, because a
   Sophos Firewall or another TLS-capable device was onboarded first) → **`syslog_update_config`**
   to enable **`syslog_udp`**. Leave the existing listeners untouched — other devices depend on
   them.
4. **Capture the deliverables:** the endpoint **domain**, the **UDP port**, and the protocol.
   These go into the UTM in Step 3.

> **No TLS on this device.** UTM 9's Add Syslog Server dialog exposes **Name, Server, Port** and
> nothing else — Sophos documents no encryption option for remote syslog, so the platform CA
> certificate (https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt) has nothing to
> consume it here. Encrypted transport for this appliance means carrying the syslog over a private
> path (an existing site-to-site tunnel, a local relay that re-forwards over TLS) — a network
> design decision for the customer, not something the UTM can do itself. Sophos Firewall *can*
> (`setup-sophos-firewall-syslog`), which is one more argument for the migration.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`SophosUTMSyslog`** template ("Sophos UTM
   Syslog") and use its current schema; in the 2026-07 snapshot it has **no parameters**, but the
   live template is the truth. Do not confuse it with `SophosFWLog` (Sophos Firewall) or
   `SophosEDR` (Sophos Central).
2. **`list_connectors`** — if a SophosUTMSyslog instance already exists, the site is likely
   already ingesting UTM syslog; additional appliances just point at the same endpoint (Step 3)
   and share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `SophosUTMSyslog`
   - `instance`: `sophosutmsyslog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Sophos UTM Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Sophos UTM
Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the UTM at it (guided)

Everything below happens in **WebAdmin**. UTM splits the job across three pages: the object
definitions (where the endpoint lives), the Remote Syslog Server tab (that it forwards), and the
log selection (what it forwards). All three are required.

### 3.1 — Define the endpoint as objects

UTM's syslog dialog does not take a raw address and port — it takes a **network definition** and a
**service definition**. Create them first (or from the `+` icons inside the dialog, which open the
same forms):

**Network definition** — *Definitions & Users → Network Definitions → New Network Definition*:

- **Name:** e.g. `Fluency-Ingext-Syslog`
- **Type:**
  - **DNS host** when the endpoint is a hostname — "a DNS hostname, dynamically resolved by the
    system to produce an IP address", re-resolved periodically per the record's TTL. This is the
    right choice for a platform endpoint whose address can change.
  - **Host** if the customer insists on pinning a single IP address.
- **Hostname / IPv4 address:** the endpoint from Step 1.

> **Caution (Sophos's own):** never use one of the UTM's **own interfaces** as the remote syslog
> host — that creates a logging loop.

**Service definition** — *Definitions & Users → Service Definitions → New Service Definition*:

- **Name:** e.g. `Fluency-Syslog-UDP`
- **Type of definition:** **UDP**
- **Destination port:** the endpoint port from Step 1
- **Source port:** a range is fine, e.g. `1:65535`

If the endpoint uses the standard port 514, the appliance's built-in **Syslog** service definition
can be used instead of creating one.

> **Transport:** UDP is the path this skill drives, and the only one that is well attested for UTM
> 9 remote syslog. UTM service definitions can also be TCP, and the dialog will accept a TCP
> service, but Sophos documents no TCP behaviour for remote syslog and community reports of it
> working are inconclusive — **don't experiment on a customer's production appliance**; use UDP.

### 3.2 — Enable remote syslog and add the server

*Logging & Reporting → Log Settings → **Remote Syslog Server** tab*:

1. Click the **toggle switch** to enable remote syslog. It turns **amber**, and the **Remote
   Syslog Settings** area becomes editable.
2. In the **Syslog Servers** box click the **Plus** icon — the **Add Syslog Server** dialog opens.
3. Fill in:
   - **Name:** a descriptive name, e.g. `Fluency Ingext`
   - **Server:** the network definition from §3.1 (or create it here with `+`)
   - **Port:** the service definition from §3.1 (or create it here with `+`)
4. **Save**, then **Apply** in the Remote Syslog Settings area. The switch turns **green**.

**Remote Syslog Buffer** (same page): the number of log lines held in the buffer, **default
1000**. Leave it unless the appliance is bursty and lines are being lost; raise it and **Apply**.

### 3.3 — Select which logs get forwarded (the part everyone forgets)

Scroll to **Remote Syslog Log Selection** — editable only once remote syslog is enabled. Tick the
checkbox of every subsystem whose log should be delivered; **Select All** ticks everything at
once. Then **Apply**.

**Nothing is forwarded until something is ticked.** A green toggle with an empty selection is the
most common "we configured it and no data arrived" outcome on this appliance.

> **UNVERIFIED — the exact checkbox labels.** Sophos's UTM 9 administration guide documents the
> mechanism ("select the checkboxes of the logs that should be delivered", plus **Select All**) but
> does **not** publish the list of subsystem labels, and no other authoritative enumeration was
> found. Read them off the screen; they mirror the UTM's own log subsystems, the same ones listed
> under *Logging & Reporting → View Log Files*. Third-party integration guides mention items such
> as **Packet Filter / firewall**, **Web Filtering**, **Intrusion Prevention System**, and
> authentication logs — treat those as secondary hints, not a complete or exact list.

Guidance for choosing (operational judgement, not a Sophos recommendation):

- **Start with Select All** if volume is not a concern — it is one click, it cannot miss a
  subsystem, and several third-party integrations recommend exactly that.
- **If volume matters**, tick the security-relevant subsystems first — packet filter/firewall,
  intrusion prevention, web filtering, authentication, and system/configuration events — and leave
  chatty proxy debug logs off. Tune after a day of real data rather than guessing up front.
- **Check what else is listening.** Per third-party reporting (secondary), UTM's log selection is
  **global, not per-server**: if the customer already forwards to another collector, every
  configured syslog server receives the same selection. Widening the selection for Fluency widens
  it for them too — say so before ticking Select All.

### 3.4 — Confirm on the device itself

*Logging & Reporting → View Log Files → **Today's Log Files***:

- **Live Log** opens a pop-up that streams the file in real time, with **Autoscroll** and a filter
  box — the fastest way to see whether the subsystem you ticked is producing anything at all.
- **View** shows the file in its current state. (Files larger than 512 MB can't be viewed.)
- Do **not** use **Clear** on a customer's appliance — it deletes the log file's contents.

**Deliverables from this section:** none to collect — once **Apply** is clicked, events flow on
their own.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), the endpoint
  domain/port/protocol, **and the end-of-life note** — the onboarding summary is exactly where a
  customer's decision-maker will see it. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes of **Apply**, *when a ticked subsystem logs something*. A UTM at a small site with a
  narrow selection can be genuinely quiet; compare against **Today's Log Files → Live Log** before
  judging. Mark ⏳ until either rows land or the device's own log shows entries that never arrived
  — only the latter is ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "SophosUTMSyslog",
  "instance": "sophosutmsyslog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "udp",
  "device": "Sophos UTM 9",
  "vendorLifecycle": "Sophos UTM end of life 30 June 2026; no support after 31 December 2026; migrate to Sophos Firewall (setup-sophos-firewall-syslog)",
  "logSelection": ["<subsystems ticked under Remote Syslog Log Selection>"]
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. Open **Logging & Reporting → View Log Files → Today's Log Files** and start a **Live Log** on a
   subsystem you ticked. That is the ground truth for what the appliance actually recorded.
3. Count rows in the Sophos UTM table over the last hour via the **`ingext-kql`** skill (confirm
   the live table name with `list_data_tables` first — the template has no index parameter). Rows
   should trail the Live Log by seconds-to-minutes.
4. **Need a deterministic test event?** Sign out of WebAdmin and back in, or browse to a site
   through the appliance if web filtering is ticked — then look for the same event in both the
   Live Log and the datalake. Make sure the corresponding subsystem is ticked first; an
   authentication/admin event is useless as a probe if that log isn't selected.
5. If the Live Log is busy and the datalake is empty past a few minutes, go to Failure modes —
   with UDP there will be no error anywhere on the appliance to find.

---

## Failure modes

| Situation | Response |
|---|---|
| Zero rows, but the UTM's own log files show entries | UDP drops silently. Re-check the network definition (right hostname/IP), the service definition (**UDP**, destination port matching the endpoint — not the 514 convention if the endpoint differs), and that the path permits outbound UDP from the appliance to the endpoint. |
| Remote syslog enabled but nothing ticked | The **Remote Syslog Log Selection** area forwards **nothing** until checkboxes are set. Tick the subsystems (or Select All) and **Apply**. |
| Toggle amber, not green | Settings were never applied. Click **Apply** in Remote Syslog Settings — amber means editable/pending, green means live. |
| Site syslog config exists but only TLS/TCP listeners | `syslog_update_config` to enable the **UDP** listener — do **not** re-register the site config. Leave existing listeners untouched. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. If unsure whether one exists, `syslog_get_config` first, always. |
| Customer demands encrypted transport | UTM 9 has **no TLS syslog option** (Name/Server/Port only). Options: carry it over a private path (existing tunnel or a local relay that re-forwards over TLS), or migrate to Sophos Firewall, which supports Secure log transmission — `setup-sophos-firewall-syslog`. Do not pretend the appliance can do TLS. |
| Someone selected a TCP service definition | Sophos documents no TCP behaviour for UTM remote syslog and reports are inconclusive. Switch to a **UDP** service definition; if the customer needs TCP specifically, that's a reason to migrate, not to experiment. |
| Logging loop / appliance flooding itself | The syslog host must not be one of the UTM's **own interfaces** — Sophos calls this out explicitly. Repoint the network definition at the platform endpoint. |
| Another SIEM suddenly gets more data | The log selection is global across configured syslog servers (secondary reporting): widening it for Fluency widens it for every destination. Coordinate with whoever owns the other collector. |
| Log lines missing during traffic bursts | **Remote Syslog Buffer** defaults to 1000 lines. Raise it and **Apply**. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Events arrive garbled / unparsed | Confirm the installed connector is **`SophosUTMSyslog`** — `SophosFWLog` parses the *Sophos Firewall* format and will not fit UTM's output. UTM has no format selector to change. |
| The admin's UI doesn't match this runbook | They are probably on **Sophos Firewall** (SFOS): "System services → Log settings", a Format dropdown, a per-server category matrix. Switch to `setup-sophos-firewall-syslog`. If they're in a cloud console with API credentials, it's **Sophos Central** → `setup-sophos-central-connector`. |
| Customer asks whether to bother, given EoL | Answer honestly: the appliance stops receiving security fixes and signature updates, so central logging *and* a migration plan both matter. Get the logs flowing today; note `setup-sophos-firewall-syslog` for after the migration. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **UDP syslog is unencrypted and unauthenticated in transit**, and UTM 9 offers no alternative.
  Firewall/proxy logs carry internal addressing, usernames, and visited URLs — the customer should
  make that tradeoff knowingly rather than discover it in an audit.
- **The appliance itself is unpatched from 30 June 2026 onward.** Central logging does not fix
  that; it only means an incident is visible. Keep the migration recommendation attached to the
  onboarding record.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — no
  need to publish them beyond the people configuring devices.
- The platform CA certificate is for *other*, TLS-capable syslog sources at the same site (Sophos
  Firewall among them); nothing on UTM 9 consumes it.
- Prefer a scoped log selection over **Select All** when the appliance proxies user web traffic —
  full proxy logs are both high-volume and privacy-sensitive.

---

## Layout

```
setup-sophos-utm-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Sophos UTM 9 admin-guide + end-of-life citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
