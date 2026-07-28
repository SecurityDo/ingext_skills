---
name: setup-checkpoint-syslog
version: 1.0.0
description: >-
  Set up Check Point firewall log import into Fluency / Ingext via syslog, using Check Point's
  Log Exporter. The agent performs the whole Fluency side itself: it resolves the site's syslog
  endpoint via the syslog MCP calls — syslog_get_config to read the existing transport,
  syslog_register_config to create it if the site has none (once per site, ever),
  syslog_update_config to enable the listener Log Exporter will use — and installs the "Check Point
  Firewall Syslog" connector (CheckPointFWLog). The Check Point side is NOT the gateway's own
  syslog: logs are exported from the Management Server / Log Server that holds them, with the
  cp_log_export CLI in expert mode or the SmartConsole Log Exporter/SIEM object. Log Exporter
  speaks syslog over TCP or UDP, and TLS only with mutual authentication — prefer TCP unless the
  mutual-TLS prerequisites are confirmed. SELF-CONTAINED: it ends by creating the connector itself
  — when routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers:
  "connect Check Point to Ingext", "forward Check Point firewall logs to Fluency", "set up Log
  Exporter to the datalake", "Check Point syslog connector", "get our Quantum gateway logs in". Do
  NOT use for other syslog vendors (SonicWall is setup-sonicwall-syslog; Peplink is
  setup-peplink-syslog; FortiGate is setup-fortigate-syslog; Palo Alto is setup-paloalto-syslog;
  Meraki is setup-cisco-meraki-syslog; Cisco ASA is setup-cisco-asa-syslog; Sophos is
  setup-sophos-firewall-syslog or setup-sophos-utm-syslog), and not for Check Point
  Harmony/Infinity cloud log export or
  the CEF/LEEF SIEM formats — this connector consumes the syslog-format export.
---

# Set up Check Point syslog import (Log Exporter)

Import a **Check Point** deployment's firewall logs — connection, threat-prevention, VPN and
administrator-audit events — into Fluency / Ingext via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`CheckPointFWLog`** ("Check Point Firewall Syslog"),
  which parses the Check Point stream. The template takes no parameters.
- **Check Point side (customer's admin):** configure **Log Exporter** on the server that holds the
  logs.

> **The structural fact that trips people up: you do not configure syslog on the gateway.**
> Check Point gateways send their logs to a **Management Server** or **dedicated Log Server**, and
> **Log Exporter** — a daemon on that server — reads them, transforms them and forwards them over
> syslog. Check Point's own documentation scopes Log Exporter to the Management Server / Log Server
> (including Multi-Domain and SmartEvent servers) and recommends deploying it on **every server
> that holds logs you want exported**. Point the customer at the log server, not the firewall.

Vendor-side steps are backed by Check Point's Log Exporter Administration Guide, the Logging and
Monitoring Administration Guides and the `cp_log_export` CLI reference (sk122323 is the canonical
SK); citations live in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. The listener Log Exporter will use must be enabled (`syslog_update_config` if missing): **`syslog_tcp`** by default, `syslog_tls` only if the mutual-TLS prerequisites check out, `syslog_udp` as a last resort |
| Ingext | Connector | Template **`CheckPointFWLog`** ("Check Point Firewall Syslog"), instance e.g. `checkpointfwlog`, no parameters |
| Check Point | Log Exporter target | One target per log-holding server: `cp_log_export add name … target-server … target-port … protocol tcp format syslog`, or the equivalent **Log Exporter/SIEM** object in SmartConsole |
| Check Point | (TLS only) certificate material | A CA PEM plus a client P12 under `$EXPORTERDIR/targets/<Name>/certs/` — Log Exporter's TLS is **mutual authentication only** |

Nothing here is billable on either side.

---

## Prerequisites

- **Which server holds the logs.** A standard Management Server, a dedicated Log Server, a
  SmartEvent server, or a Multi-Domain Server with per-domain logs. If gateways are configured to
  **"Save logs locally, on this server"**, those logs are on the gateway and are *not* covered by
  the documented Log Exporter deployment (see the UNVERIFIED note in Step 3.1).
- **Expert-mode CLI access** (SSH / console, `expert` password) on that server — the documented
  primary path. *Or* a SmartConsole administrator who can create objects, **Publish**, and
  **Install database** for the GUI path.
- Confirmation that the gateways already send logs to that server — in SmartConsole the gateway
  object's **Logs** page offers **"Send gateway logs to server"**, a dedicated Log Server, or
  **"Save logs locally, on this server"**. Changing that requires Publish plus **Install Policy**.
- The server must be able to reach the syslog endpoint on the configured port/protocol — check
  outbound rules, including any Check Point policy governing the management server's own traffic.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides Check Point (default):** you resolve/create the syslog
  transport, install the connector, then hand the Check Point admin the exact `cp_log_export`
  command (or the SmartConsole click-path) with the real endpoint values filled in, and verify rows.
- **(b) Runbook only:** print the full procedure — including the resolved endpoint host/port/
  protocol and the ready-to-paste command — for the Check Point admin to apply later. Offer to
  resume verification when they return.

`cp_log_export` runs in **expert mode on a production management server**. Per the repo's
device-CLI boundary: guide it by default. If the operator explicitly offers a shell on that server
you may run the documented commands, but never ask for those credentials.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

**Pick the listener before you touch the platform.** Log Exporter's transport options are
**syslog over TCP or UDP**, plus TLS *with mutual authentication only*:

| Choice | When | Listener |
|---|---|---|
| **TCP** — the default recommendation | Always workable; connection-oriented, so a dead target is visible rather than silent, and Log Exporter remembers its last exported position and resumes after a disconnect | **`syslog_tcp`** |
| **TLS** | Only after the mutual-TLS prerequisites are confirmed (Step 3.4) — Check Point requires a **client certificate**, not just trust in the server | `syslog_tls` |
| **UDP** | Last resort, e.g. a site whose only listener is UDP and cannot be changed | `syslog_udp` |

Then:

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Configuration exists but not the listener you chose** (e.g. only `syslog_udp` is enabled and
   you want TCP) → **`syslog_update_config`** to enable the additional listener. Leave the existing
   listeners untouched; other devices depend on them.
4. **Capture the deliverables:** the endpoint **domain**, the **port** for the chosen listener, and
   the **protocol**. These go into the `cp_log_export` command in Step 3.

> **TLS note.** The platform CA certificate is
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt — a PEM bundle, which is exactly
> the format Log Exporter's `ca-cert` argument wants. But Log Exporter also insists on presenting a
> **client** certificate, and Check Point documents the CA as the one that signed *both* the client
> and the server certificates. Whether the Fluency TLS listener requests a client certificate — and
> whether it would accept one the customer generates — is **UNVERIFIED** (Step 3.4). Do not promise
> TLS before that is answered; start on TCP, move to TLS once Fluency confirms.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`CheckPointFWLog`** template ("Check Point
   Firewall Syslog", category `onpremise`) and use its current schema; in the 2026-07 snapshot it
   has **no parameters**, but the live template is the truth.
2. **`list_connectors`** — if a CheckPointFWLog instance already exists, the site is likely already
   ingesting Check Point syslog; an additional log server just gets its own Log Exporter target
   pointed at the same endpoint (Step 3) and shares the connector. Only add a second instance
   deliberately.
3. **`create_connector`** with:
   - `application`: `CheckPointFWLog`
   - `instance`: `checkpointfwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Check Point Firewall Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Check Point
Firewall Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Configure Log Exporter (guided)

### 3.1 — Confirm where the logs live

Log Exporter is a daemon on the **Management Server / Log Server**; it reads the log files
(`$FWDIR/log/`, e.g. `fw.log`), transforms each record and sends it to the target. Deploy a target
on **every** server holding logs you want exported — one Management Server plus two dedicated Log
Servers means three targets, all aimed at the same endpoint.

- **Multi-Domain (MDS):** each Domain has its own Log Exporter daemon and its own `$EXPORTERDIR`,
  switched with `mdsenv`. The `add` command takes `domain-server {mds | all}` to place the target in
  the MDS context or across all domains.
- **UNVERIFIED — gateway-local logs:** the current Check Point guides scope Log Exporter to
  Management/Log Servers. If a gateway is set to *"Save logs locally, on this server"*, treat
  exporting straight from that gateway as unverified: either point the gateway at the management/log
  server (gateway object → **Logs** → send to server; requires **Publish** + **Install Policy**), or
  get the supported gateway-side procedure from Check Point support. Do not improvise one.

### 3.2 — Path A (primary): the `cp_log_export` CLI

Connect to the server's command line and enter **expert mode**, then add the target. Substitute the
endpoint domain and port resolved in Step 1:

```bash
# Expert mode on the Management Server / Log Server that holds the logs
expert

# Create the export target (TCP, syslog format — see the format note below)
cp_log_export add name fluency-ingext \
  target-server <endpoint-domain> \
  target-port <port-from-step-1> \
  protocol tcp \
  format syslog \
  --apply-now
```

- **`name`** must start with a letter, be at least two characters, and use only Latin letters,
  digits, `-`, `_` and `.`. It becomes the directory name under `$EXPORTERDIR/targets/`, so keep it
  boring: `fluency-ingext`.
- **`--apply-now`** applies the change immediately. If you leave it off, the target is written but
  not started — apply it with `cp_log_export restart name fluency-ingext`.
- **Multi-Domain** adds `domain-server mds` (MDS context) or `domain-server all` (every domain)
  right after `name`.
- **UDP instead of TCP:** the same command with `protocol udp`. Accept it only per Step 1's table.

Check the result:

```bash
cp_log_export show                       # every configured target and its settings
cp_log_export status                     # running state
cp_log_export restart name fluency-ingext   # after any change made without --apply-now
```

Other subcommands you may need: `set name <Name> <args>` (change a setting), `stop` / `start`,
`delete name <Name>`, and `reexport` (see Verification).

> **Format — read this before choosing.**
> Leave the format at **`syslog`** (the tool's default). It is the plain syslog stream this
> connector is named for, and Check Point's own guidance for syslog receivers is to treat it as
> standard syslog-protocol framing. `cef`, `leef`, `json`, `splunk`, `logrhythm`, `rsa` and
> `generic` all reshape the message for other products and would land as differently-shaped rows.
> **Fluency does not publish which format the `CheckPointFWLog` parser expects, and we could not
> verify it (UNVERIFIED).** If rows arrive but fields are unparsed, do not shop through formats —
> ask Fluency support which one the parser expects, then change it deliberately:
> ```bash
> cp_log_export set name fluency-ingext format <format>
> cp_log_export restart name fluency-ingext
> ```
> **`read-mode`** is a separate knob: `semi-unified` (default) exports step-by-step unified records;
> `raw` exports records without unification and produces many more rows. Leave it at the default
> unless the customer has a reason.

### 3.3 — Path B (alternative): SmartConsole

Current versions can configure Log Exporter from the GUI — useful when the customer will not hand
out expert-mode access. TLS is **not** exposed here; that stays a CLI job (§3.4).

1. **Objects → More object types → Server → Log Exporter/SIEM** → new object.
2. **General** page: set **Export Configuration** to **Enabled**; fill in **Target Server** (the
   endpoint domain or IP), **Target Port** (from Step 1), and **Protocol** — **UDP is the default,
   so change it to TCP**.
3. **Data Manipulation** page: leave **Format** at **Syslog** (the default). Optionally set the
   aggregation mode for connection logs (*Semi unified* / *First and Last* / *Last only*) and
   **Aggregate log updates before export** — the latter makes every exported update carry the full
   record instead of only changed fields, at the cost of volume.
4. Open the **Management Server / Dedicated Log Server / SmartEvent Server** object → left tree →
   **Logs → Export** → **[+]** → select the Log Exporter object you just created. Repeat for every
   log-holding server.
5. **Publish** the session, then **Install database**: menu → **Install database** → select all
   objects → **Install**. The configuration does not take effect until this runs.
6. Re-run **Install database** after upgrading the servers.

### 3.4 — TLS (only when the prerequisite is confirmed)

Log Exporter's encrypted export is **mutual-authentication TLS 1.2 only**. It needs, on the
Management/Log Server:

- **`ca.pem`** — the CA certificate in PEM format. Check Point documents this as the CA that signed
  **both** the client and the target-server certificates.
- **`cp_client.p12`** — a client certificate in P12 format, plus the challenge phrase used when it
  was created.

Both files go in `$EXPORTERDIR/targets/<Name>/certs/` and must be readable
(`chmod -v +r <file>`). Then:

```bash
cp_log_export add name fluency-ingext-tls \
  target-server <endpoint-domain> \
  target-port <tls-port-from-step-1> \
  protocol tcp \
  format syslog \
  encrypted true \
  ca-cert $EXPORTERDIR/targets/fluency-ingext-tls/certs/ca.pem \
  client-cert $EXPORTERDIR/targets/fluency-ingext-tls/certs/cp_client.p12 \
  client-secret <challenge-phrase> \
  --apply-now
```

Check Point documents generating the client material with OpenSSL (key → CSR → certificate signed
by the CA → P12 export); the challenge phrase set during the P12 export is what `client-secret`
expects.

> **UNVERIFIED — do not promise this works before checking.** The platform CA bundle
> (https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt) is a **PEM bundle of five public
> roots — Amazon Root CA 1–4 and Starfield Services Root CA G2** — i.e. the syslog endpoint presents
> a publicly-trusted certificate. That file works fine as `ca-cert` for validating the endpoint. The
> open question is the client side: **does the Fluency TLS listener request a client certificate,
> and will it accept one the customer generates from their own CA?** Nothing in Fluency's published
> material answers that, and Check Point cannot be configured for one-way TLS. **Confirm with
> Fluency support (or whoever owns the site's syslog listener) before attempting TLS. Until then,
> use TCP** — and say plainly that the stream is unencrypted, per the security notes.

### 3.5 — Decide what gets exported

- Log Exporter can export **Security logs, Audit logs, or both** — audit logs being administrator
  actions on the management server, which many customers specifically want in the SIEM.
- Content can be filtered by field value, and gateway connection logs can be filtered out entirely,
  via the exporter's XML configuration under `$EXPORTERDIR/targets/<Name>/`. Configure filtering
  only if the customer asks: it is the usual cause of "the log is in SmartConsole but never reached
  the SIEM".
- **After editing any configuration file by hand, restart the instance** —
  `cp_log_export restart name <Name>` — the daemon does not pick up file edits on its own.

**Deliverables from this section:** the target **name** used, the **format**, the **protocol**, and
which servers got a target. Record them — they are what a later parsing or gap question needs.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing connectors
  from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the live
  name with `list_data_tables` — the template defines no index), the endpoint
  domain/port/protocol, and the Log Exporter **target name + format + which servers** carry a
  target. The `client-secret` challenge phrase, if TLS was used, is a credential — never echo it.
- **Latency expectation:** near-real-time once the target is applied — Log Exporter streams as logs
  land on the server, and after a disconnect it resumes from its last exported position rather than
  losing the gap. Expect rows within a couple of minutes; mark ⏳ until either rows land or
  SmartConsole's Logs view demonstrably shows events that never arrived — only the latter is ❌.
- **Rows-but-garbled is not success.** If the count is non-zero but fields are unparsed, report ⏳
  with the format question from §3.2, not ✅.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (the TLS challenge phrase is a
credential and is deliberately absent):

```json
{
  "connector": "CheckPointFWLog",
  "instance": "checkpointfwlog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "<tcp|tls|udp>",
  "logExporterTarget": "fluency-ingext",
  "logExporterFormat": "syslog",
  "exportingServers": ["<management or log server hostnames>"]
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **On the Check Point server:**
   ```bash
   cp_log_export show      # target present with the expected server/port/protocol/format
   cp_log_export status    # instance running
   ```
3. **SmartConsole → Logs & Monitor → Logs is the ground truth.** It shows what the log server
   actually holds. Anything missing from the datalake must be visible here first; if this view is
   empty for the period, the gap is gateway→log-server logging, not the export.
4. Count rows in the Check Point table over the last hour via the **`ingext-kql`** skill (confirm the
   live table name with `list_data_tables` first). Rows should trail the Logs view by
   seconds-to-minutes.
5. **Inspect a row, don't just count it.** Confirm fields are parsed into columns rather than sitting
   in a raw blob — that is what catches a format mismatch while the count looks fine.
6. **Need traffic on demand?** Two documented options, in order of preference:
   - Generate an **audit** log: perform and **Publish** a trivial administrator action in
     SmartConsole (audit logs are administrator actions and are exportable by Log Exporter).
   - Replay existing logs with **`cp_log_export reexport name <Name> --apply-now`**, which resets the
     exporter's position and re-exports from it. Use this deliberately — it duplicates rows in the
     datalake — and prefer it only when the connector's parsing is what's in question.

---

## Failure modes

| Situation | Response |
|---|---|
| Nothing arrives; the admin configured syslog **on the gateway** | The most common Check Point mistake. Gateway syslog is not this integration: Log Exporter runs on the Management Server / Log Server that holds the logs. Redo Step 3 there. |
| Nothing arrives; SmartConsole's Logs view is also empty | The gap is upstream of the export. Check the gateway object's **Logs** page — if it is set to *"Save logs locally, on this server"*, the logs never reach the exporting server. Changing it needs **Publish** + **Install Policy**. |
| Target configured but nothing sends | `--apply-now` was omitted, or a config file was edited by hand. Run `cp_log_export restart name <Name>` and re-check `cp_log_export status`. |
| SmartConsole path used, still nothing | **Install database** was skipped (menu → Install database → select all → Install), or the Log Exporter object was never attached under the server object's **Logs → Export**. |
| Multi-Domain: only some domains export | Each Domain has its own daemon and `$EXPORTERDIR`. Add the target with `domain-server all` (or per domain with `mdsenv`), not once at the top. |
| Silent drops on UDP | UDP reports nothing on failure — a wrong port or a blocked path looks identical to success. Prefer **TCP**, which surfaces connection failures and lets Log Exporter resume from its last position. |
| Listener/protocol mismatch | Site has `syslog_tls` only but Log Exporter is going to send TCP: `syslog_update_config` to add `syslog_tcp` — do **not** re-register the site config, and leave the TLS listener alone for the devices using it. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. If unsure whether one exists, `syslog_get_config` first, always. |
| Site config exists → tempted to re-register | Don't. `syslog_update_config` adds a listener; re-registering is not a repair mechanism and risks the listeners other devices depend on. |
| TLS handshake fails / `encrypted true` won't connect | Log Exporter does **mutual authentication only**. Confirm `ca-cert` (PEM) and `client-cert` (P12) exist under `$EXPORTERDIR/targets/<Name>/certs/`, are readable (`chmod +r`), and that `client-secret` matches the P12's challenge phrase. If the listener's client-certificate behaviour is still unconfirmed (§3.4 UNVERIFIED), fall back to TCP rather than guessing. |
| Rows arrive but fields are unparsed | Format mismatch. Fluency's expected format for `CheckPointFWLog` is **UNVERIFIED**; `syslog` is the default and the right starting point. Ask Fluency support before switching, then `cp_log_export set name <Name> format <fmt>` + `restart`. Do not cycle through cef/leef/json hoping one sticks. |
| Far more rows than expected | `read-mode raw` exports without unification, and *Aggregate log updates before export* re-sends full records. Return to `semi-unified` / leave aggregation off unless the customer asked. |
| Specific log types missing | Log Exporter exports Security logs, Audit logs, or both, and supports field-based filtering in its XML configuration. Check whether a filter is excluding them, then restart the instance. |
| Egress blocked | The management server's own outbound traffic still has to reach the endpoint on the configured port — including through any Check Point policy governing the management server. Verify from that host, not from a workstation. |
| Several log servers, one connector | Give each server its own Log Exporter target aimed at the same endpoint; they share the one connector. Don't create per-server connector instances unless the data shows otherwise. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — reconnect, or read the endpoint from the platform UI's Connectors page instead. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **TCP and UDP syslog are unencrypted in transit.** Check Point firewall logs describe internal
  topology, users, VPN peers, blocked threats and administrator actions — treat the stream as
  sensitive even though it is not a credential. If the customer cannot accept cleartext, the answers
  are resolving the mutual-TLS question in §3.4 or carrying the traffic over a private path, not a
  workaround this skill invents.
- **`client-secret` is a credential.** The P12 challenge phrase must never appear in a summary, a
  ticket, or the JSON hand-off — refer to it as "the challenge phrase from the client certificate".
  The P12 file itself is key material: keep it on the server, readable by the exporter only.
- **`cp_log_export` runs as expert (root-equivalent) on a production management server.** Guide it
  by default; run it only if the operator explicitly offers the shell, and never ask for those
  credentials. `add`, `set` and `restart` affect a live logging pipeline — show the command before
  running it.
- **`reexport` duplicates data.** It is a legitimate diagnostic, not a routine check.
- Exporting **audit logs** ships administrator activity off the management server. That is usually
  desirable for a SIEM, but say so out loud rather than letting the customer discover it.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — no need
  to publish them beyond the people configuring exporters.

---

## Layout

```
setup-checkpoint-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Check Point Log Exporter / cp_log_export citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
