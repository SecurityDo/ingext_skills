# Application catalog

The routing map for `customer-onboarding`. **This is the only file to edit when a new deep-dive
skill lands** — add a row, and the router picks it up.

Two tiers:

- **Guided** — the application has a dedicated skill that handles prerequisites the generic
  connector installer cannot (cloud IAM plumbing, customer-owned app registration). Route there.
- **Standard** — no dedicated skill; `add-connector` discovers the template live via
  `list_connector_templates` and installs it. The rows below are a convenience for recognising the
  request, **not** an authoritative template list. The platform is the source of truth; never quote
  these template names back to the user as "what's available" — call `list_connector_templates`.

---

## Guided applications

### AWS CloudTrail

| Field | Value |
|---|---|
| **Aliases** | CloudTrail, AWS audit logs, AWS API logs |
| **Route** | `setup-aws-cloudtrail-connector` (self-contained — it ends in `create_connector` itself) |
| **Auth path** | AWS cross-account assume-role (`ingextAssumeRole`) + S3 → SQS notification |
| **Prerequisites** | An existing S3 bucket CloudTrail writes to; the bucket's region; ability to run CloudFormation in the customer's own AWS account. Optional: object prefix, external ID |
| **Hands back** | Nothing to carry — the skill installs the connector itself |
| **Datalake table** | `AWSCloudTrail` — confirm the live name with `list_data_tables` before querying |
| **First-event latency** | ~5 min (CloudTrail batches deliveries to S3), plus queue drain |

The same plumbing fits other S3-notification sources — AWS CloudWatch Logs (S3), Fluent Bit (S3),
GuardDuty in S3. That skill documents how to swap the connector in its final step.

### Microsoft 365 / Entra audit logs

| Field | Value |
|---|---|
| **Aliases** | Office 365, O365, Microsoft 365, Entra audit, Azure AD audit, AzureAudit |
| **Route** | `automatic-create-ingext-azureaudit-app` (preferred) → **then** `add-connector` |
| **Auth path** | **Customer-owned app** (app-only client credentials) — *not* the hosted OAuth consent flow |
| **Prerequisites** | An Entra **Global Administrator** (admin consent is required for the nine Application permissions) |
| **Hands back** | `tenantId`, `clientId`, `clientSecret` → carry into `add-connector` |
| **Datalake table** | `Office365`, `AzureAuditLogs` |
| **First-event latency** | Up to ~30–60 min for the first Office 365 Management API events after subscription starts |

> **Prefer the automatic variant.** `automatic-create-ingext-azureaudit-app` *performs* the app
> registration (az CLI, with a PowerShell 7 fallback) — the operator only completes the interactive
> sign-in — and it still covers the guide-a-third-party-admin case as its Mode B. Route to the
> older guide-only `create-ingext-audit-app` only if the automatic variant isn't installed. Both
> hand back the same three fields (note the automatic variant names the app `ingext-azureaudit`;
> the guide-only one names it `ingext-audit`).

> **Fork in the road — ask before routing.** Microsoft 365 has *two* onboarding paths and they are
> not interchangeable:
>
> - **Customer-owned app** → `automatic-create-ingext-azureaudit-app` → `add-connector`. The
>   customer registers and owns the app. Use when they want the app in their own tenant, or when
>   policy forbids third-party multi-tenant apps.
> - **Hosted OAuth consent** → `add-connector` **alone**. The Office365 / AzureAudit templates take
>   only `adminConsentEmail`; a consent email goes to that address and the admin authorises
>   Fluency's multi-tenant app. See `add-connector` Step 7.
>
> Never send a customer-owned-app tenant into the consent flow, or vice versa. If it's unclear
> which they want, ask.

### Microsoft Defender

| Field | Value |
|---|---|
| **Aliases** | Defender, MS Defender, Defender XDR, Graph Security incidents/alerts |
| **Route** | `automatic-create-ingext-defender-app` (preferred) → **then** `add-connector` |
| **Auth path** | **Customer-owned app** (app-only client credentials) |
| **Prerequisites** | An Entra **Global Administrator** (admin consent for `SecurityIncident.Read.All`, `SecurityAlert.Read.All`) |
| **Hands back** | `tenantId`, `clientId`, `clientSecret` → carry into `add-connector` |
| **Datalake table** | Confirm with `list_data_tables` — varies by platform version |
| **First-event latency** | Polling-based; allow ~15–30 min, and note incidents only appear if Defender has generated any |

> **Prefer the automatic variant.** `automatic-create-ingext-defender-app` *performs* the app
> registration (az CLI, with a PowerShell 7 fallback) — the operator only completes the interactive
> sign-in — and it still covers the guide-a-third-party-admin case as its Mode B. Route to the older
> guide-only `create-ingext-defender-app` only if the automatic variant isn't installed. Both hand
> back the same three fields.

### Azure Event Hubs

| Field | Value |
|---|---|
| **Aliases** | Event Hub, EventHub, MS Event Hub, Azure Monitor / Entra / Defender log streaming via event hub |
| **Route** | `automatic-create-ingext-ms-eventhub` (self-contained — it ends in `create_connector` itself, so **no** `add-connector` follow-on) |
| **Auth path** | SAS connection string (Listen-only, hub-level policy) — the portal's "Connection string–primary key" |
| **Prerequisites** | **Contributor** (or Owner) on the target Azure subscription (Mode A: the skill provisions namespace + hub + policy; note the namespace is **billable**), or a third-party admin who runs it (Mode B). If the customer **already has** a hub and its connection string, the skill skips straight to its Ingext-side connector step |
| **Hands back** | Nothing to carry — the skill installs the connector itself and reports the connector `instance` id, `consumerGroup`, and hub/namespace names. The `connectionString` is a credential — don't echo it |
| **Datalake table** | `AzureEventHubs` (template default index) — confirm the live name with `list_data_tables` |
| **First-event latency** | **None until a producer streams into the hub.** The skill creates an empty hub; events start only after the customer points a producer (Azure Monitor diagnostic settings, Entra ID diagnostic settings, Defender Streaming API, …) at it — then typically ~5–15 min. Mark ⏳ with the producer follow-up noted, not ❌ |

> **Guided vs. standard fork:** route here when the Azure side still needs provisioning (no hub
> yet, or no Listen-only connection string). If the customer already holds a working "Connection
> string–primary key" and just wants the connector, plain `add-connector` also works — but this
> skill's connector step does the same install and validates the string's `EntityPath`, so
> preferring it is never wrong.

### Syslog sources (guided, compact)

Each row has a dedicated skill. **All are self-contained** — the skill resolves the site's syslog
transport itself (`syslog_get_config`; `syslog_register_config` **once per site, ever** if none
exists; `syslog_update_config` to add the listener a device needs, leaving existing listeners
alone), installs the connector, then guides the device-side configuration from cited vendor
documentation. **No `add-connector` follow-on.** None of these templates define an index, so
**confirm every table with `list_data_tables`**.

Transport is per-device and was verified per skill — it decides which listener to enable. TLS
devices are handed the platform CA bundle at
`https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt`; see the note below on what that
file actually is.

**Two transport facts that apply to every row** (confirmed by the Fluency team 2026-07-28):

- **There is a dedicated `tls_rfc6587` listener** — with its own `tls_rfc6587_port` — for senders
  that use **RFC 6587 octet-counted framing**. `syslog_get_config` reports both fields, and
  `syslog_register_config` / `syslog_update_config` can create the listener. **FortiGate needs
  this one**, because plain `syslog_tls` expects newline framing and would concatenate FortiOS
  messages into unusable records. Check any other octet-counting sender the same way.
- **TLS is one-way — no client certificates are accepted.** Devices verify the platform and
  present nothing. This *unblocks* Palo Alto and Sophos Firewall (their client-auth caveats never
  arise — don't generate a client certificate for either) and *rules out* TLS for Check Point,
  whose Log Exporter does mutual-auth TLS only.

| Device | Aliases | Route | Verified transports → listener | Device-side prerequisite |
|---|---|---|---|---|
| FortiGate | Fortinet, FortiOS, FGT | `setup-fortigate-syslog` | UDP / TCP / **TLS** → **`tls_rfc6587`** (FortiOS uses octet-counted framing — *not* plain `syslog_tls`) | Admin with **CLI** access (transport mode, TLS and log filters are CLI-only) |
| Palo Alto | PAN-OS, PA-series, Panorama | `setup-paloalto-syslog` | UDP / TCP / **SSL (TLS 1.2)** → `syslog_tls` | Admin who can edit server profiles, log forwarding **and Commit** |
| Cisco Meraki | Meraki MX/MS/MR, dashboard | `setup-cisco-meraki-syslog` | UDP / TCP / **TLS (MX 26.1+ only)** → `syslog_tls` on qualifying MX, else `syslog_udp` | Dashboard admin **per network**; Organization → Certificates for TLS |
| Cisco ASA | ASA, ASDM, Secure Firewall ASA | `setup-cisco-asa-syslog` | UDP / TCP / **TLS (`secure`)** → `syslog_tls` | Privileged CLI or ASDM, **plus a change window** if TCP/TLS (see the fail-closed warning) |
| SonicWall | SonicOS, TZ, NSa, NSsp | `setup-sonicwall-syslog` | **Version-gated:** SonicOS 8 = UDP/TCP/TLS; **7.x and 6.5 = UDP only** → `syslog_tls` on 8, else `syslog_udp` | Web-UI admin; pin the firmware version first — it decides the listener |
| Check Point | Quantum, Log Exporter, `cp_log_export` | `setup-checkpoint-syslog` | TCP / UDP / TLS-mutual-auth-only → **`syslog_tcp`** — TLS is unusable because the platform accepts no client certificate (R13, answered) | Expert-mode CLI on the **Management/Log Server** (not the gateway), or a SmartConsole admin |
| Sophos Firewall | Sophos XG/XGS, SFOS | `setup-sophos-firewall-syslog` | UDP / **TLS** (no plain TCP) → `syslog_tls` | SFOS admin over System services → Log settings (+ Certificates for TLS) |
| Sophos UTM 9 | Sophos SG, Astaro | `setup-sophos-utm-syslog` | **UDP only** → `syslog_udp` | UTM 9 WebAdmin admin. ⚠️ **UTM 9 reached end of life 30 Jun 2026** — see the row note |
| Peplink / Pepwave | Peplink Balance, Pepwave MAX | `setup-peplink-syslog` | **UDP only** → `syslog_udp` | Device web-admin access (System → Event Log) |
| Linux (RHEL family) | RHEL, Rocky, Alma, CentOS, rsyslog | `automatic-linux-rhel-syslog` | UDP / TCP / **TLS** → `syslog_tls` | **root/sudo** on the host (Mode A: the agent configures rsyslog itself), or a Linux admin (Mode B) |

**First-event latency for every syslog row:** near-real-time once the device forwards — seconds
to a couple of minutes. A quiet device legitimately produces little, so compare against the
device's own log view before judging; most skills document a way to generate a test event
(`logger` on Linux, a config change on PAN-OS, an admin command on ASA). Mark ⏳ only while a
device remains unconfigured; ❌ once a configured device's own log shows events that never landed.

> **⚠️ Sophos UTM 9 is end-of-life (30 June 2026).** No further OS, AV/IPS signature, or
> vulnerability updates, and Sophos support ends 31 December 2026. The skill still helps a
> customer today but says so up front and points at Sophos Firewall as the migration path.

> **What the platform CA file is** (inspected 2026-07-28): a PEM bundle of **five public roots** —
> Amazon Root CA 1–4 and Starfield Services Root CA G2. The syslog TLS endpoint therefore presents
> a **publicly trusted** certificate: many devices validate it with no import at all, and
> importing the bundle is best understood as **pinning** trust to those roots. It is server-trust
> only and **cannot** serve as a client certificate — which is why Check Point's mutual-TLS-only
> Log Exporter has no TLS path yet (plan §5, R13).

> **Open parser question affecting these rows (plan §5, R12):** which syslog *format* each Fluency
> parser expects is undocumented — FortiGate `default` vs others, PAN-OS **BSD vs IETF**, SonicWall
> **Default vs Enhanced**, Check Point `syslog` vs CEF/LEEF. Each skill recommends the vendor
> default and gives a diagnostic (rows landing but fields unparsed → try the alternate → ask
> Fluency). Worth settling centrally rather than per-customer.

---

### SaaS API & push integrations (guided, compact)

Each row below has a dedicated skill. **All are self-contained** — the skill guides the
vendor-side credential/config work (cited against vendor documentation), then ends in
`create_connector` itself, so there is **no `add-connector` follow-on**. Hands back: the
connector instance id + datalake table for Step 5 verification; credentials never appear in
summaries. Datalake tables marked *confirm live* have no index parameter on the template —
confirm with `list_data_tables` before querying (true for every row, but mandatory for those).

| Application | Aliases | Route | Vendor-side prerequisite | Datalake table | First-event latency |
|---|---|---|---|---|---|
| Okta | Okta | `setup-okta-connector` | Okta admin creates an API token (read-only service-account owner recommended; 30-day inactivity expiry) | `Okta` | ~15–30 min |
| Cisco Duo | Duo, Duo Security, Duo MFA | `setup-duo-connector` | Duo **Owner**-role admin protects the Admin API application ("Grant read log") | `Duo` | ~15–30 min |
| Bitwarden | Bitwarden event logs | `setup-bitwarden-connector` | Organization **Owner** (Teams/Enterprise plan) retrieves the org API key; self-hosted → contact support | *confirm live* | ~15–30 min |
| Box | box.com, Box enterprise events | `setup-box-connector` | Box Admin authorizes a Client-Credentials platform app; Enterprise ID needed | *confirm live* | ~15–30 min (Box's admin_logs can trail real time) |
| Sophos Central | Sophos EDR, Intercept X | `setup-sophos-central-connector` | Sophos Central **Super Admin** creates a Service Principal Read-Only API credential | *confirm live* | ~15–30 min |
| SentinelOne | S1, Singularity | `setup-sentinelone-connector` | Console admin creates a service user + API token (note token expiry; calendar it) | `SentinelOne` | ~15–30 min |
| Trend Vision One | Trend Micro, Vision One | `setup-trendmicro-visionone-connector` | Vision One **Master Administrator** creates an API key (start at Auditor role); regional base URL | *confirm live* | ~15–30 min |
| Cortex XDR | Cortex, PaloAlto Cortex XDR | `setup-cortex-xdr-connector` | Cortex XDR admin creates an API key (Settings → Configurations → Integrations → API Keys); key security level must match the connector's `authMode` (default **Advanced**) | `Cortex` | ~15–30 min |
| Salesforce Event Monitoring | Salesforce, EventLogFile, Shield logs | `setup-salesforce-event-monitoring-connector` | **Hard prerequisite: Event Monitoring add-on license** (standalone or Shield). Admin sets up an External Client App / Connected App with the client-credentials flow (run-as user needs "API Enabled" + "View Event Log Files") | *confirm live* | **Hours, not minutes** — hourly EventLogFiles lag ~3–6 h; license-less orgs see only a daily free subset. Zero rows right after install is expected — mark ⏳ |
| Mimecast | Mimecast CG, Cloud Gateway | `setup-mimecast-connector` | Mimecast admin registers an API 2.0 application (Integrations → API and Platform Integrations). Legacy 1.0 creds → `add-connector` | `Mimecast` | ~15–30 min |
| Proofpoint TAP | TAP, Targeted Attack Protection | `setup-proofpoint-tap-connector` | TAP Dashboard admin creates a service credential (Settings → Connected Applications) | *confirm live* | ~15–30 min; threat-driven — a quiet org shows little |
| Bitdefender Security Telemetry | GravityZone ST, BEST telemetry | `setup-bitdefender-securitytelemetry-connector` | GravityZone admin with policy rights + EDR-capable license; the connector's generated HEC url/token go into policy → Security Telemetry | *confirm live* | **None until the policy applies and endpoints stream** — mark ⏳, not ❌ |
| Amazon GuardDuty | GuardDuty | `automatic-amazon-guardduty` | GuardDuty **already enabled** (skill never enables it — billable); IAM-admin signs in for Mode A (agent runs the bundled aws CLI script) or a third-party admin runs it (Mode B). If findings already land in S3, prefer the CloudTrail skill's S3→SQS plumbing and swap the connector | *confirm live* | Findings-driven — honestly zero on quiet accounts; use GuardDuty sample findings as the smoke test |
| Anything with a Splunk-HEC output (no template of its own) | HEC, Splunk HEC, generic intake | `setup-hec-passthrough` | Source-product admin pastes the generated HEC url + token into its Splunk/HEC output | operator-chosen index | **None until the source pushes** — mark ⏳; rows within minutes of the first send |

---

## Standard applications (route: `add-connector`)

Aliases mirror `add-connector`'s own matching list, which is authoritative for template matching.

| Application | Aliases | Auth path | Prerequisites | Datalake table |
|---|---|---|---|---|
| Office 365 (consent path) | O365, Microsoft 365 | Hosted OAuth consent | Admin email; admin completes consent | `Office365` |
| Google Workspace | GSuite, G Suite | Hosted OAuth consent | Admin email; admin completes consent | `gsuiteUser`, `gsuiteGroup` |
| Bitdefender Event Push (EP) | GravityZone | API key | Ask which variant first: **Security Telemetry (ST) is guided** — `setup-bitdefender-securitytelemetry-connector`; only EP routes here | — |
| Proofpoint Essentials | — | API key | Ask which product first: **TAP is guided** — `setup-proofpoint-tap-connector`; only Essentials routes here | — |

**Anything not listed here is still supported.** `add-connector` calls `list_connector_templates`
and matches against the live catalogue. Route unknown vendors there rather than declaring them
unavailable — only `add-connector` can say that, from live data.

---

## FortiGate bandwidth caveat

If a customer onboards FortiGate and later asks about bandwidth, top talkers, or traffic volume,
the `fortigate-bandwidth` skill fires automatically — FortiGate byte fields are cumulative session
counters and a naive `sum()` over-counts badly. Nothing to do at onboarding time; noted here so the
router doesn't hand-roll a verification query that trips over it. For the Step 5 event-count check,
a plain row count is safe.

---

## Syslog sources still without a skill

Two members of the syslog family are **deliberately not built yet**, both blocked on
documentation (plan §5):

| Application | Template | Blocked on | Interim route |
|---|---|---|---|
| Windows Server via NXLog | `WindowsSrvNxLog` | **R6** — the reference `nxlog.conf` (route + format) Fluency's parser expects. A wrong format means events land but never parse | `add-connector` |
| ManageEngine | `ManageEngine` | **R9** — which ManageEngine product the parser targets (ADAudit Plus? EventLog Analyzer?). Without that there is no menu path to document | `add-connector` |

Do **not** improvise either procedure — that is exactly the silent-breakage the guided skills
exist to prevent.
