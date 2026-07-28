---
name: setup-paloalto-syslog
version: 1.0.0
description: >-
  Set up Palo Alto Networks PAN-OS firewall log import into Fluency / Ingext via syslog. The agent
  performs the whole Fluency side itself: it resolves the site's syslog endpoint via the syslog
  MCP calls — syslog_get_config to read the existing transport, syslog_register_config to create
  it if the site has none (once per site, ever), syslog_update_config to enable the listener the
  firewall will speak — and installs the "PaloAlto Firewall Syslog" connector (PaloAlto_FWLog).
  The PAN-OS side is a real runbook and it is a TWO-PART job that trips people up: a Syslog server
  profile under Device → Server Profiles → Syslog (transport UDP/TCP/SSL, port, BSD or IETF
  format, facility), and then ATTACHING it — Objects → Log Forwarding match lists applied to
  security policy rules for traffic/threat/URL logs, plus Device → Log Settings, a different
  screen, for System/Config/User-ID/HIP/GlobalProtect logs — followed by Commit. PAN-OS supports
  SSL (TLSv1.2), so this skill prefers it and covers the certificate work. SELF-CONTAINED: it ends
  by creating the connector itself — when routed from customer-onboarding, do NOT chain into
  add-connector afterward. Triggers: "connect our Palo Alto firewall to Ingext", "forward PAN-OS
  logs to Fluency", "Palo Alto syslog into the datalake", "set up the PaloAlto connector", "send
  our PA-3220 logs to Fluency". Do NOT use for Cortex XDR — a different Palo Alto product with its
  own skill, setup-cortex-xdr-connector — nor for Prisma Access/SASE or Cortex Data Lake. Other
  syslog vendors have their own skills (setup-fortigate-syslog, setup-peplink-syslog); anything
  with no dedicated skill goes to add-connector.
---

# Set up Palo Alto Networks (PAN-OS) syslog import

Import a **Palo Alto Networks** firewall's logs — traffic, threat, URL filtering, system and
config events — into Fluency / Ingext via **syslog**. Three pieces, two of them yours:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — managed through the `syslog_*` MCP calls. Created **once per site**, then shared by
  every syslog integration that follows.
- **Fluency connector (yours):** install **`PaloAlto_FWLog`** ("PaloAlto Firewall Syslog"), which
  parses the PAN-OS stream. The template takes no parameters.
- **Firewall side (customer's PAN-OS admin):** a syslog **server profile**, then **attaching** it
  in *two different places* depending on log type, then a **Commit**. PAN-OS speaks **UDP, TCP and
  SSL (TLSv1.2)** — so this one gets **SSL by default** (see Step 3).

> **The thing that goes wrong:** people create the server profile, commit, and nothing arrives.
> A server profile on its own sends **nothing**. It has to be referenced — by a Log Forwarding
> profile attached to security rules (traffic/threat/URL), and separately under Device → Log
> Settings (system/config/User-ID/HIP). Step 3 makes both explicit.

Every device-side claim below is cited in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. The listener the firewall will use (`syslog_tls` preferred, else `syslog_tcp` / `syslog_udp`) is enabled with `syslog_update_config` if missing |
| Ingext | Connector | Template **`PaloAlto_FWLog`** ("PaloAlto Firewall Syslog"), instance e.g. `paloalto-fwlog`, no parameters |
| PAN-OS | Syslog server profile | **Device → Server Profiles → Syslog** — name, server address, Transport, Port, Format, Facility |
| PAN-OS | Log Forwarding profile | **Objects → Log Forwarding** with match lists, attached to security rules under **Policies → Security → *rule* → Actions** |
| PAN-OS | Log Settings entries | **Device → Log Settings** — System, Configuration, User-ID, HIP Match, GlobalProtect, Correlation |
| PAN-OS | Certificates (SSL only) | Platform CA imported as a trusted root under **Device → Certificate Management → Certificates**; a client certificate marked **Certificate for Secure Syslog** *only if* the receiver requires client auth |

Nothing here is billable on either side.

---

## Prerequisites

- A PAN-OS administrator with rights to edit server profiles, log forwarding, security policy and
  to **Commit** — the last one matters: nothing takes effect without it.
- The firewall's **management interface** (or whichever interface carries log forwarding) must
  reach the syslog endpoint outbound on the chosen port and protocol.
- **Panorama-managed?** Establish this up front — the same objects exist but are edited centrally
  and pushed, not edited on the firewall. See the Panorama note in Step 3.
- The **Fluency Ingext MCP** connected for the target Ingext instance, including the `syslog_*`
  tools (re-authenticate the MCP if they are not listed). Without the MCP, the operator reads the
  endpoint from the platform UI and installs the connector there instead.

---

## The offer — who does what

Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Agent does the Fluency side + guides the firewall (default):** you resolve/create the
  syslog transport, install the connector, then walk whoever holds the PAN-OS admin UI through
  Step 3 — server profile, certificates if SSL, both attachment points, Commit, and verification.
- **(b) Runbook only:** print the full procedure — with the real endpoint host/port/protocol
  filled in once you've resolved it — for the firewall admin to apply later. Offer to resume
  verification when they return.

The PAN-OS side is web-console work; the agent guides it rather than clicking it.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the descriptions below are intent, not exact parameter names.

1. **`syslog_get_config`** — read the site's existing syslog configuration. Always first.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that is what update is for.
3. **Configuration exists but lacks the listener this firewall will use** →
   **`syslog_update_config`** to enable it. Leave the existing listeners untouched; other devices
   at the site depend on them.
4. **Which listener?** PAN-OS supports all three, so pick in this order:
   - **`syslog_tls` — the default choice.** Firewall logs carry internal IPs, usernames, visited
     URLs, threat names and policy names. PAN-OS calls this transport **SSL** and supports
     **TLSv1.2 only**.
   - `syslog_tcp` — connection-oriented but cleartext; a reasonable middle ground if the customer
     rules out certificate work.
   - `syslog_udp` — last resort, or when the path is already private. **Say the tradeoff out
     loud:** UDP is unencrypted, unauthenticated and drops silently.
5. **Capture the deliverables:** endpoint **domain**, **port**, **protocol**. These go into the
   server profile in Step 3.

> **TLS certificate:** on the SSL path the firewall must trust the platform's certificate. Give
> the admin the platform CA certificate —
> https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt — and follow Step 3b. The CA
> certificate is public; it is not a credential.
>
> **SSL is clear to use here. (Answered 2026-07-28.)** PAN-OS documents that, *when the syslog
> server uses client authentication*, "the syslog server and the sending firewall must have
> certificates that the same trusted certificate authority (CA) signed" — a constraint a customer
> could not satisfy against a hosted endpoint. That case does not arise: the Fluency syslog TLS
> listener **does not request or accept client certificates** (confirmed by the Fluency team), so
> the handshake is plain one-way TLS with the firewall verifying the server. **Skip the client
> certificate entirely** — Step 3b.2 exists only for other receivers.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`PaloAlto_FWLog`** template ("PaloAlto
   Firewall Syslog") and use its current schema; in the 2026-07 snapshot it has **no parameters**,
   but the live template is the truth.
2. **`list_connectors`** — if a PaloAlto_FWLog instance already exists, the site is likely already
   ingesting PAN-OS syslog; additional firewalls just point at the same endpoint (Step 3) and
   share it. Only add a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `PaloAlto_FWLog`
   - `instance`: `paloalto-fwlog` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `PaloAlto Firewall Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **PaloAlto
Firewall Syslog** — and read the syslog endpoint host/port from the platform's Connectors page.

---

## Step 3 — Point the firewall at it (guided)

Four sub-steps, and skipping 3d is the classic failure.

### 3a. Create the syslog server profile

**Device → Server Profiles → Syslog → Add.**

- **Name** — a profile name (≤31 characters, case-sensitive, unique). Something like
  `fluency-ingext`.
- **Location** — on a multi-vsys firewall, choose the vsys or **Shared**. It cannot be changed
  after saving, so decide now.
- **Servers** tab → **Add**, then per server:

| Field | Value |
|---|---|
| **Name** | Server entry name, e.g. `fluency` |
| **Syslog Server** | The endpoint **domain** (IP or FQDN both accepted) from Step 1 |
| **Transport** | **SSL** (preferred — TLSv1.2 only), else TCP, else UDP |
| **Port** | The port from Step 1. PAN-OS defaults: **UDP 514**, **SSL 6514**; for TCP there is no default — set it explicitly |
| **Format** | **BSD** (the default) or **IETF**. Traditionally BSD goes with UDP and IETF with TCP/SSL |
| **Facility** | Defaults to **LOG_USER**; any standard syslog facility is accepted |

- Click **OK**.

> **Format choice.** **UNVERIFIED:** no public Fluency documentation states whether the
> `PaloAlto_FWLog` parser expects BSD (RFC 3164) or IETF (RFC 5424) framing. Start with the PAN-OS
> default **BSD**; if events land unparsed or with a mangled header, try **IETF** before assuming
> the connector is broken, and raise it with Fluency support. Do not touch the **Custom Log
> Format** tab — a custom format will almost certainly defeat the parser.

### 3b. SSL only — the certificate work

Do this **before** the Commit, so the first connection succeeds.

> **What this file is** (inspected 2026-07-28): a PEM bundle of **five public roots** — Amazon
> Root CA 1–4 and Starfield Services Root CA G2, the Amazon Trust Services roots behind
> AWS-issued certificates. The endpoint certificate is therefore **publicly trusted**, so a
> firewall whose default trusted-root store already carries those roots may need no import —
> check **Device → Certificate Management → Certificates → Default Trusted Certificate
> Authorities** first. Importing is still defensible as a **pin** to these roots specifically.
> It is server-trust only and cannot satisfy a listener that demands a client certificate.

1. **Trust the endpoint.** Download the platform CA
   (https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt) and import it at **Device →
   Certificate Management → Certificates** → **Import**, in **Base64 Encoded Certificate (PEM)**
   format, and select **Trusted Root CA** so the firewall treats it as an additional trusted
   authority beyond the pre-installed list.
2. **Client certificate — only if the receiver demands client authentication.** PAN-OS's own
   procedure is: **Device → Certificate Management → Certificates → Device Certificates →
   Generate**, with the **Common Name** set to the IP address the firewall uses to reach the
   syslog server; then open the certificate, tick **Certificate for Secure Syslog**, **OK**. The
   private key must live on the firewall (it cannot sit on an HSM), and the subject and issuer
   must differ. Skip this entirely if the endpoint does not ask for a client certificate.
3. **Revocation checking is not optional.** PAN-OS validates the TLS connection with **OCSP or
   CRL** where the certificates in the chain carry those extensions, and per the documentation you
   **cannot bypass an OCSP/CRL failure** — the chain must be valid and checkable. If the handshake
   dies with a revocation error, that is where to look.

### 3c. Attach it for traffic / threat / URL logs — Log Forwarding profile

These log types are produced by **policy matches**, so they are forwarded by a **Log Forwarding
profile** attached to security rules.

1. **Objects → Log Forwarding → Add**, enter a **Name**. Naming it **`default`** makes it apply
   automatically to newly created rules and zones — convenient, and worth mentioning.
2. Add one or more **match list** entries. Each carries:
   - **Name**
   - **Log Type** — choose from **Traffic, Threat, WildFire Submission, URL Filtering, Data
     Filtering, Tunnel, Authentication**. Add one entry per log type the customer wants.
   - **Filter** — optional; the Filter Builder narrows by log attributes. Leave it at *All Logs*
     unless there is a reason.
   - **Forward Method** — tick the **Syslog** server profile created in 3a.
3. **OK**.
4. **Attach it to policy: Policies → Security →** edit each rule that should log **→ Actions** tab
   → set the **Log Forwarding** profile. For traffic logs also enable **Log at Session End**
   (and/or **Log at Session Start** if the customer wants both).
   - A rule with no Log Forwarding profile sends nothing, no matter how good the server profile
     is. If the customer has hundreds of rules, name the profile `default` (step 1) and still
     sweep the existing rules — `default` only auto-applies to *new* ones.

### 3d. Attach it for system / config / User-ID / HIP logs — a *different* screen

**Device → Log Settings.** These log types are **not** policy-driven and are configured here, not
in Objects → Log Forwarding:

- **System** and **Correlation** — click **each Severity level**, select the syslog server
  profile, **OK**.
- **Configuration**, **User-ID**, **HIP Match**, **GlobalProtect** — edit each section, add a
  match list, select the syslog server profile.

This is the step people miss. Config logs are how you later answer "who changed that rule", and
they only arrive if this screen is filled in.

### 3e. Commit

Click **Commit**. Nothing above is live until the commit finishes — no server profile, no
forwarding, no certificates. Watch the commit complete rather than assuming.

> **Panorama-managed deployments.** If the firewalls are managed by Panorama, the same objects are
> authored centrally and pushed: the syslog server profile and **Device → Log Settings** live in a
> **Template**, and the **Log Forwarding** profile lives in a **Device Group**, then **Commit and
> Push**. Panorama can also forward the logs *it* collects to syslog itself, via **Panorama →
> Server Profiles → Syslog**, with syslog forwarding enabled on an interface under **Panorama →
> Setup → Interfaces** (local Log Collector) or **Panorama → Managed Collectors** (Dedicated Log
> Collector) — note it can be enabled on only one interface. Decide *which* device sends to
> Fluency — firewalls directly, or Panorama on their behalf — before configuring, and confirm the
> push mechanics against the Panorama admin guide for the customer's version.

**Deliverables from this section:** none to collect — once the commit lands, logs flow.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), and the endpoint
  domain/port/protocol. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — rows should appear within a couple of
  minutes **of the Commit**, when the firewall logs something. Until the commit completes, zero
  rows is expected and correct. A production firewall is rarely quiet, so a persistently empty
  table while **Monitor → Logs** shows traffic is a real failure, not a wait. Mark ⏳ during the
  commit window, ❌ once the device's own logs demonstrably show events that never arrived.
- **Partial-arrival is the common half-success:** traffic logs landing but no system/config logs
  (or vice versa) means only one of the two attachment points was configured — Step 3c vs 3d. Call
  that out rather than marking the source done.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "PaloAlto_FWLog",
  "instance": "paloalto-fwlog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "tls",
  "panosTransport": "SSL",
  "serverProfile": "<profile name>",
  "logForwardingProfileAttached": true,
  "logSettingsConfigured": true,
  "committed": true
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **The firewall's own log views are the ground truth.** **Monitor → Logs → Traffic / Threat /
   System / Configuration** show what the device actually recorded. Anything in the datalake must
   be a subset of that.
3. **There is no "send test message" button.** PAN-OS's documented syslog procedure ends at "check
   your syslog server" — it publishes no test-log feature for syslog server profiles. So generate
   a real event instead: the firewall **automatically generates Configuration and System logs**,
   so a benign config change plus a **Commit**, or an admin logout/login, produces fresh entries
   under **Monitor → Logs → Configuration** and **System** within seconds. Watch those, then look
   for the matching rows.
4. Count rows in the PAN-OS table over the last few minutes via the **`ingext-kql`** skill —
   confirm the live table name with **`list_data_tables`** first. A plain row count is the smoke
   test; no analysis needed.
5. Still nothing? Work the PAN-OS CLI checks below before blaming the platform:

```
ping host <endpoint-domain>
traceroute host <endpoint-domain>
show netstat numeric-host yes numeric-port yes all yes | match <port>
debug log-receiver statistics
```

   Version-specific extras: on **pre-11.1** use `debug syslog-ng status` and `debug syslog-ng
   stats`; on **11.1 and later** use `show system software status | match logrcvr`,
   `show syslog-ssl-conn-validation` and `show system state filter sw.logrcvr.syslog*`. On
   **12.2.x** (backported to 12.1.5) `debug log-receiver syslog-connections` shows per-connection
   status. A management-plane capture is available with `tcpdump filter "port <port>" snaplen 0`,
   exported via `scp export mgmt-pcap from mgmt.pcap to <user>@<host>:<path>`.

---

## Failure modes

| Situation | Response |
|---|---|
| Server profile created and committed, but **nothing arrives at all** | The profile alone forwards nothing. Confirm both attachment points: a Log Forwarding profile with the right match lists **attached to security rules** (Step 3c) *and* **Device → Log Settings** (Step 3d). |
| **Traffic/threat logs arrive, system/config logs do not** | Step 3d was skipped — Device → Log Settings is a separate screen from Objects → Log Forwarding. |
| **System/config logs arrive, traffic logs do not** | The Log Forwarding profile is not attached to the security rules, or the rules do not log. Policies → Security → *rule* → Actions → set Log Forwarding, and enable **Log at Session End**. |
| Everything looks configured but nothing changed | **The Commit never ran or failed.** Re-commit and watch it complete. |
| Zero rows on **UDP**, but Monitor → Logs shows events | UDP drops silently. Re-check the server address, the port (the endpoint's port, not the 514 default), and outbound UDP on the path. Prefer moving this source to SSL. |
| Site syslog config exists, but not the listener PAN-OS needs | `syslog_update_config` to enable `syslog_tls` (or `_tcp`/`_udp`). **Do not re-register** the site config; leave the other listeners alone — other devices use them. |
| No site syslog config at all | `syslog_register_config` — once per site, ever. When unsure, `syslog_get_config` first, always. |
| **SSL handshake fails** | Confirm the platform CA was imported and marked **Trusted Root CA** (Step 3b.1), and that the chain is complete. Remember PAN-OS supports **TLSv1.2 only** for this transport. |
| SSL fails with a revocation error | PAN-OS validates via OCSP/CRL where the chain carries those extensions and **cannot bypass a failure**. The chain must be valid and checkable — take it to Fluency support with the exact error. |
| Handshake fails and client authentication is suspected | It shouldn't be the cause — the Fluency listener neither requests nor accepts client certificates (confirmed 2026-07-28), so PAN-OS's same-CA constraint never applies. Look instead at the trusted-root import and at whether the server profile's address matches the certificate name. Do not generate a "Certificate for Secure Syslog"; it cannot help. |
| Events arrive but look unparsed / header mangled | Try switching **Format** between **BSD** and **IETF** in the server profile (Step 3a), and make sure nothing was entered on the **Custom Log Format** tab. Confirm the installed connector is `PaloAlto_FWLog`. |
| Firewall is Panorama-managed and local edits keep reverting | Expected — the config is pushed. Author the change in the Template (server profile, Log Settings) and Device Group (Log Forwarding), then Commit and Push. |
| Someone asks about Cortex XDR alongside this | Different product, different connector. Route to **`setup-cortex-xdr-connector`**; do not try to cover it here. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication, or an older server may not expose them — re-connect, or read the endpoint from the platform UI's Connectors page instead. |
| Wrong table / table name unknown | The template has no index parameter — `list_data_tables` is the authority. |

---

## Security notes

- **Prefer SSL for this device.** PAN-OS firewall logs carry internal addressing, usernames,
  visited URLs, threat detections, VPN/GlobalProtect activity and policy names. UDP and plain TCP
  syslog cross the network in cleartext and can be read or spoofed on the path. If the customer
  chooses UDP anyway, record it as a deliberate decision and note the exposure.
- The platform **CA certificate is public** — a trust anchor, not a secret. Nothing in this runbook
  produces a credential to leak into a ticket or a summary.
- If a **client certificate** is generated for secure syslog, its private key lives on the firewall
  and must stay there — never export it into a ticket, chat, or shared drive.
- The syslog endpoint host/port are not credentials, but they name an open ingestion door — share
  them only with the people configuring devices.
- Be deliberate about **Log at Session Start**: it roughly doubles traffic-log volume and, on a
  busy firewall, both the link and the datalake feel it. Session End alone is the normal default.
- **URL Filtering logs contain full browsing history for identified users.** Worth a word with the
  customer about who can query the datalake before turning that log type on.

---

## Layout

```
setup-paloalto-syslog/
├── SKILL.md
├── assets/
│   └── references.md    ← Palo Alto Networks documentation citations; platform syslog notes
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
