# Ingext Skills

A collection of skills for the Ingext / Fluency platform. A skill is a bundle of
instructions (and sometimes scripts and reference data) that Claude loads when it
recognises a matching request, letting it carry out a specific task — querying the
datalake, running a report, investigating a user, checking site health, and more.

- Skill sources live in [`SKILLS/`](./SKILLS) (each is a folder with a `SKILL.md`).
- Packaged, installable skills live in [`cowork/`](./cowork) as `*.skill` files.
- Change history is in [`release_notes/`](./release_notes).

Each skill's `SKILL.md` frontmatter carries a `version:`. All skills are currently
at **1.0.0**.

## Installation

### Step 1 — Connect Claude Code to GitHub

Before installing skills, connect Claude Code to GitHub so it can access this repository
directly.

1. Open Claude Code and go to **Settings → Connectors**.
2. Click **Add Connector** and search for **GitHub**.
3. Select the GitHub connector and click **Connect**.
4. Authenticate via **OAuth login** with your GitHub account.
5. Once connected, Claude Code can browse and pull files from any repository you have
   access to.

### Step 2 — Install skills from this repository

With the GitHub connector active, ask Claude to install the skills directly:

> "Install the skills from github.com/SecurityDo/ingext_skills"

Claude will browse the repository, download the `.skill` files, and add them to your
Claude Code plugins automatically.

Alternatively, install a specific skill by name:

> "Install the fluency-report skill from github.com/SecurityDo/ingext_skills"

## Skills at a glance

| Skill | What it does |
| --- | --- |
| [customer-onboarding](#customer-onboarding) | Front door for a new customer: menu of applications → route to the right setup skill → verify ingestion |
| [ingext-kql](#ingext-kql) | Generate a validated KQL query over the datalake |
| [ingext-promql](#ingext-promql) | Generate / run PromQL for platform metrics |
| [fortigate-bandwidth](#fortigate-bandwidth) | Correct FortiGate bandwidth aggregation rules |
| [fluency-report](#fluency-report) | Run an existing FPL report → HTML summary |
| [fpl-report-builder](#fpl-report-builder) | Author an FPL report definition from KQL |
| [azure-user-signin-investigation](#azure-user-signin-investigation) | Investigate Azure AD sign-ins & directory changes |
| [office-user-investigation](#office-user-investigation) | Investigate an M365 mailbox user (KQL + GeoIP) |
| [ingext-health-monitor](#ingext-health-monitor) | Check whether a site is healthy and ingesting |
| [add-connector](#add-connector) | Install a new application connector |
| [setup-aws-cloudtrail-connector](#setup-aws-cloudtrail-connector) | Set up the AWS CloudTrail connector: S3 → SQS notification, cross-account role, real-time import |
| [create-ingext-audit-app](#create-ingext-audit-app) | Guide an Entra admin to register the `ingext-audit` app (Graph + O365 audit import) |
| [create-ingext-audit-app-azcli](#create-ingext-audit-app-azcli) | az CLI variant of `create-ingext-audit-app`: cowork can run it directly when the operator is the tenant's Global Admin |
| [create-ingext-defender-app](#create-ingext-defender-app) | Guide an Entra admin to register the `ingext-defender` app (Graph Security incidents + alerts) |
| [automatic-create-ingext-azureaudit-app](#automatic-create-ingext-azureaudit-app) | Automatic variant: registers the `ingext-azureaudit` Entra app for the operator (az CLI, pwsh fallback) |
| [automatic-create-ingext-defender-app](#automatic-create-ingext-defender-app) | Automatic variant: registers the `ingext-defender` Entra app for the operator (az CLI, pwsh fallback) |
| [automatic-create-ingext-ms-eventhub](#automatic-create-ingext-ms-eventhub) | Provision Azure Event Hubs (namespace, hub, Listen policy) and install the connector — self-contained |
| [automatic-amazon-guardduty](#automatic-amazon-guardduty) | GuardDuty findings: creates the least-privilege IAM user + key (aws CLI script) and installs the connector |
| [setup-okta-connector](#setup-okta-connector) | Okta System Log import: guided API-token creation + connector install |
| [setup-duo-connector](#setup-duo-connector) | Cisco Duo Admin API: guided Admin API application + connector install |
| [setup-bitwarden-connector](#setup-bitwarden-connector) | Bitwarden organization event logs: guided org API key + connector install |
| [setup-box-connector](#setup-box-connector) | Box enterprise events: guided client-credentials platform app + connector install |
| [setup-sophos-central-connector](#setup-sophos-central-connector) | Sophos Central (EDR): guided API credential + connector install |
| [setup-sentinelone-connector](#setup-sentinelone-connector) | SentinelOne: guided service-user API token + connector install |
| [setup-trendmicro-visionone-connector](#setup-trendmicro-visionone-connector) | Trend Vision One: guided API key (regional base URL) + connector install |
| [setup-mimecast-connector](#setup-mimecast-connector) | Mimecast Cloud Gateway (API 2.0): guided app registration + connector install |
| [setup-proofpoint-tap-connector](#setup-proofpoint-tap-connector) | Proofpoint TAP: guided service credential + connector install |
| [setup-cortex-xdr-connector](#setup-cortex-xdr-connector) | Palo Alto Cortex XDR: guided API key (Advanced auth) + connector install |
| [setup-salesforce-event-monitoring-connector](#setup-salesforce-event-monitoring-connector) | Salesforce Event Monitoring (Shield): guided client-credentials app + connector install |
| [setup-bitdefender-securitytelemetry-connector](#setup-bitdefender-securitytelemetry-connector) | Bitdefender GravityZone Security Telemetry → platform-generated HEC intake |
| [setup-hec-passthrough](#setup-hec-passthrough) | Generic Splunk-HEC intake for products with no dedicated template |
| [html-to-pdf](#html-to-pdf) | Convert an HTML file to a PDF |

---

## Getting started

### customer-onboarding

The front door for a new customer bringing data into the platform. Checks what's already
connected, presents a menu of supported applications, and routes each choice to the skill that
actually sets it up — **setup-aws-cloudtrail-connector** for CloudTrail, **create-ingext-audit-app**
or **create-ingext-defender-app** (then **add-connector**) for the Entra customer-owned app paths,
**add-connector** for everything else. It carries the `tenantId` / `clientId` / `clientSecret` from
an app registration into the connector install, verifies events actually land in the datalake, then
loops back for the next source. It installs nothing itself — it's a router and a verifier.

Use it when the customer *doesn't* already know which application they want, or is onboarding
several sources at once. If they've named a single application, the dedicated skill triggers
directly.

**Try:**
- "we just signed up, help us get our logs into Fluency"
- "onboard a new customer"
- "what can we connect to Ingext?"
- "we have CloudTrail, Office 365, and a FortiGate to bring in"

---

## Datalake & metrics querying

### ingext-kql

Turns a natural-language question into a validated KQL query over the Ingext
datalake. Discovers tables with `list_data_tables`, resolves field definitions from
an embedded schema knowledge base (it never guesses an unknown schema), and always
parse-validates before returning. Use it for any datalake query, even trivial ones.

**Try:**
- "using the ingext_kql skill, count denied Fortigate traffic by srcip in the last 6 hours"
- "using the ingext_kql skill, top 10 users by failed sign-ins yesterday"
- "using the ingext_kql skill, tell me all the Office365 users and their licenses"
- "using the ingext_kql skill, write me a KQL query for failed Office365 logins by app"

### ingext-promql

Generates and runs PromQL / MetricsQL against the platform metrics store
(VictoriaMetrics) — throughput, ingest/egress volume, component and processor rates,
error/drop ratios. Platform metrics only; for event data use **ingext-kql**.

**Try:**
- "tell me the imported events per second by event type"
- "tell me the total bytes egressed per index this hour"
- "tell me the processor error ratio over the last day"

### fortigate-bandwidth

Knowledge skill that ensures FortiGate traffic bandwidth is aggregated correctly —
the byte fields are cumulative session counters, so per-interval deltas must be used
instead of a naive `sum()`. Fires automatically behind any FortiGate byte/packet
aggregation, including via ingext-kql, fluency-report, or fpl-report-builder.

---

## Reports

### fluency-report

Runs an existing FPL report and renders its result as a single-page, Fluency-branded
HTML summary (KPI cards, charts, tables, interpretation). It only runs reports that
actually exist — it never invents or substitutes one.

**Try:**
- "run a Fluency report"
- "run the Ingext IngestionRate report"
- "give me a Fluency report on top alerted users"
- "build a Fluency summary for the IngestionRate report"

### fpl-report-builder

Authors an FPL report *source file* by compiling one or more KQL queries into a
single time-bounded report definition. For **writing** the definition — not running
it (use fluency-report) and not for single standalone queries (use ingext-kql).

**Try:**
- "create an FPL report from these queries"
- "turn these KQL queries into a report"

---

## User investigations

### azure-user-signin-investigation

Investigates a user's Azure AD / Entra sign-in and directory-change activity by
running three saved FPL reports and combining them into one HTML report (sign-in
timeline, executive summary, per-report tables, recommendations). Use when the focus
is sign-ins and role/group/password changes.

**Try:**
- "investigate Azure AD user jane@corp.com"
- "pull X's sign-in history on Fluency"
- "what directory changes did X make or receive?"
- "run the Azure sign-in investigation for jane@corp.com"

### office-user-investigation

Investigates a Microsoft 365 mailbox user by querying the `Office365` datalake table
directly with KQL — Exchange operations, inbox rules (Business Email Compromise),
OAuth consents, mass deletes — geolocates every source IP offline, and produces a
self-contained HTML report with a GeoIP map plus an optional PDF.

**Try:**
- "investigate O365 mailbox user X"
- "look into mailbox activity for X"
- "check this account for BEC / suspicious inbox rules"
- "geoip map of a user's logins"

---

## Platform operations

### ingext-health-monitor

Checks the health of an Ingext site and produces a status report — whether data is
flowing, router/pipe errors and which pipe is failing, dropped and egressed volume,
ingestion spikes or outages, and queue backlog.

**Try:**
- "is the ingext site healthy?"
- "run a health check on the fluency instance"

### add-connector

Installs a new application connector: discovers available connector templates,
matches the request, gathers any required credentials/configuration interactively,
and deploys the connector instance.

**Try:**
- "add the CrowdStrike connector"
- "install the AWS SQS application"
- "connect Office 365 to Ingext"

### setup-aws-cloudtrail-connector

End-to-end setup of the **AWS CloudTrail** connector for **real-time** import from an existing
customer S3 bucket (with an optional object prefix). CloudTrail delivers events to S3; this skill
wires an S3 "new object" notification into a newly created **SQS** queue, grants Ingext cross-account
read access via an STS **assume-role**, registers that role, and installs the connector. It drives
the five-step runbook — `get_account_podrole` for the tenant pod role ARN → the customer runs the
`IngextSaasPodRole` and `IngextS3SqsNotification` CloudFormation templates (bundled in `assets/`) →
`add_assumed_role` to register the role → `create_connector` with Region, SQS URL, and AWS Role. The
same plumbing fits other S3-notification sources (CloudWatch Logs S3, Fluent Bit S3, GuardDuty in
S3) — swap the connector template in the final step. For a plain connector install with no AWS
plumbing, use **add-connector**.

**Try:**
- "set up the AWS CloudTrail connector, our logs are in S3 bucket acme-cloudtrail in us-east-1"
- "import CloudTrail from our S3 bucket into Ingext in real time"
- "connect CloudTrail via SQS to Fluency"
- "how do I register the IAM role and verify it before installing the CloudTrail connector?"

### create-ingext-audit-app

Guides an Azure AD / Entra admin through registering the **`ingext-audit`** application — a
customer-owned, app-only registration that Fluency / Ingext authenticates as to import Office 365
Management audit events, Azure AD audit events, and Azure AD resources (users, groups, devices,
apps). It adds the nine required **Application** permissions across Microsoft Graph and the Office
365 Management APIs, grants admin consent, creates a client secret, and hands back three fields —
`tenantId`, `clientId`, `clientSecret` — for the downstream "install application" stage. Offers a
ready-to-run PowerShell script (Microsoft.Graph SDK) or a manual portal walkthrough. This is the
customer-owned app path — for Fluency's hosted OAuth consent flow use **add-connector**.

**Try:**
- "create the ingext-audit app in our Entra tenant"
- "register the Azure app for Ingext audit import"
- "set up the Fluency Azure application, I'm a Global Admin"
- "walk me through the portal steps to make the ingext-audit app"

### create-ingext-audit-app-azcli

The **Azure CLI (`az` / Bash)** counterpart of **create-ingext-audit-app** — same `ingext-audit`
registration, same nine **Application** permissions across Microsoft Graph and the Office 365
Management APIs, same three-field output (`tenantId`, `clientId`, `clientSecret`). It adds a
**run-it-directly** capability via two modes: **Mode A** — when the cowork operator *is* the target
tenant's Global Admin, cowork runs the bundled `setup-ingext-audit.sh` on this machine (after the
operator's interactive `az login` and with per-command permission approval); **Mode B** — when
onboarding a third-party tenant cowork can't authenticate to, it hands the admin the script or a
portal walkthrough and collects the three fields. Prefer this over the PowerShell skill when the
admin uses az CLI / Linux / macOS, or when the operator wants cowork to run the setup.

**Try:**
- "I'm the Global Admin — run the Ingext Entra app setup for me"
- "register the ingext-audit app using the Azure CLI, not PowerShell"
- "onboard our tenant to Ingext with az CLI, I'm signed in already"

### create-ingext-defender-app

Guides an Azure AD / Entra admin through registering the **`ingext-defender`** application — a
customer-owned, app-only registration that Fluency / Ingext authenticates as to export **Microsoft
Defender** security incidents (`GET /security/incidents`) and alerts (`GET /security/alerts_v2`)
through the Microsoft Graph Security API. It adds the two required **Application** permissions on
Microsoft Graph (`SecurityIncident.Read.All`, `SecurityAlert.Read.All`), grants admin consent,
creates a client secret, and hands back three fields — `tenantId`, `clientId`, `clientSecret` — for
the downstream "install application" stage. Offers a ready-to-run PowerShell script (Microsoft.Graph
SDK) or a manual portal walkthrough. Sibling of **create-ingext-audit-app** (audit-log import); for
Fluency's hosted OAuth consent flow use **add-connector**.

**Try:**
- "create the ingext-defender app in our Entra tenant"
- "register the Entra app for Microsoft Defender event export"
- "set up the Azure app so Ingext can pull Defender incidents and alerts"
- "walk me through the portal steps to make the ingext-defender app"

### automatic-create-ingext-azureaudit-app

The **automatic** variant of `create-ingext-audit-app`: instead of only guiding an admin, cowork
**runs the setup itself** (Azure CLI script preferred, PowerShell 7 fallback) when the operator is
the target tenant's Global Admin (Mode A), with a guide-a-third-party-admin fallback (Mode B).
Registers the `ingext-azureaudit` app, grants the nine Application permissions with admin consent,
and hands back `tenantId` / `clientId` / `clientSecret` for the install stage.

**Try:**
- "create the ingext-azureaudit app for me — I'm the Global Admin"
- "run the audit-log app setup automatically"

### automatic-create-ingext-defender-app

The **automatic** variant of `create-ingext-defender-app`: cowork runs the app registration
(az CLI, pwsh fallback) for the operator — two Graph Security permissions, admin consent, client
secret — and hands back the three fields for the install stage. Mode A (operator is Global Admin)
and Mode B (guide a third-party admin).

**Try:**
- "create the ingext-defender app for me"
- "I'm the Global Admin, run the Defender export app setup"

### automatic-create-ingext-ms-eventhub

Integrates Ingext with **Azure Event Hubs**, self-contained: provisions the namespace, event hub,
and Listen-only SAS policy (az CLI or pwsh, run for the operator — the namespace is billable and
the scripts stop for confirmation), then creates the `AzureEventHubs` connector itself with the
resulting connection string. No `add-connector` follow-on.

**Try:**
- "connect Ingext to Azure Event Hubs"
- "set up an event hub for Fluency and hook up the connector"

---

## Connector setup (per-application)

Dedicated setup skills, one per application, that pair **cited vendor-side guidance** (create the
API credential, configure the export) with an **automatic Fluency-side install** — each ends in
`create_connector` itself, so `customer-onboarding` routes to them directly with no
`add-connector` follow-on. Where the vendor side is CLI-drivable, the skill runs it for the
operator (`automatic-*`); where it is portal-only, the skill guides the clicks and installs the
rest. All keep credentials out of summaries and verify ingestion honestly (row counts, real
first-event latency).

### automatic-amazon-guardduty

Imports **Amazon GuardDuty** findings. Mode A: the operator signs the aws CLI in and cowork runs
the bundled idempotent script — least-privilege IAM user (`ingext-guardduty`) with the AWS managed
`AmazonGuardDutyReadOnlyAccess` policy, plus an access key — then installs the `AmazonGuardDuty`
connector with the key pair and region list. Mode B guides a third-party admin. GuardDuty must
already be enabled (the skill never enables it — that starts billing); quiet accounts can use
GuardDuty **sample findings** as the smoke test.

**Try:**
- "import GuardDuty findings into Ingext"
- "create the ingext guardduty IAM user and hook up the connector"

### setup-okta-connector

**Okta System Log** import. Guides creating an API token (Security → API → Tokens) owned by a
least-privilege service account (Read-Only Administrator), flags the 30-day inactivity expiry and
the `-admin`-domain gotcha, then installs the `Okta` connector.

**Try:**
- "add Okta to Ingext"
- "import our Okta system log into Fluency"

### setup-duo-connector

**Cisco Duo** logs via the Admin API. Guides a Duo Owner through protecting the Admin API
application with the "Grant read log" permission, collects the integration key / secret key / API
hostname, then installs the `Duo` connector.

**Try:**
- "connect Cisco Duo to Ingext"
- "import Duo authentication logs"

### setup-bitwarden-connector

**Bitwarden organization event logs**. Guides an organization Owner (Teams/Enterprise) to the
org API key, handles the US/EU region choice, then installs the `Bitwarden` connector.
Self-hosted deployments are referred to support rather than improvised.

**Try:**
- "get Bitwarden event logs into Ingext"
- "connect our Bitwarden organization"

### setup-box-connector

**Box enterprise events** (`admin_logs`). Guides creating a Box platform app with the Client
Credentials Grant and the verified event-stream scope, the Admin-Console authorization, and the
Enterprise ID, then installs the `BoxCom` connector.

**Try:**
- "import Box admin logs into Fluency"
- "connect box.com enterprise events"

### setup-sophos-central-connector

**Sophos Central** (EDR / Intercept X). Guides a Sophos Central Super Admin through creating a
Service Principal Read-Only API credential, then installs the `SophosEDR` connector. Firewall/UTM
syslog are different connectors — route those to `add-connector`.

**Try:**
- "connect Sophos Central to Ingext"
- "import Sophos EDR events"

### setup-sentinelone-connector

**SentinelOne** activity and threats. Guides creating a least-privilege service user + API token
in the S1 console (with honest handling of the login-gated docs and token-expiry variance —
calendar the expiry the console shows), then installs the `SentinelOneAPI` connector.

**Try:**
- "add SentinelOne to Ingext"
- "import S1 threats into the datalake"

### setup-trendmicro-visionone-connector

**Trend Vision One**. Guides a Master Administrator through Administration → API Keys (start at
the read-only Auditor role, escalate only on 403s), picks the correct regional base URL from the
verified table, then installs the `TrendMicroVisionOne` connector.

**Try:**
- "connect Trend Vision One"
- "import Trend Micro Vision One events into Fluency"

### setup-mimecast-connector

**Mimecast Cloud Gateway** SIEM events via **API 2.0**. Guides registering an API 2.0 application
(Integrations → API and Platform Integrations) for the client ID/secret, then installs the
`MimecastCG` connector. Legacy API 1.0 credentials go through `add-connector` instead.

**Try:**
- "connect Mimecast to Ingext"
- "import Mimecast email security events"

### setup-proofpoint-tap-connector

**Proofpoint TAP**. Guides creating a service credential in the TAP Dashboard
(Settings → Connected Applications), then installs the `ProofpointTAP` connector. TAP events are
threat-driven — a quiet org legitimately shows little. Proofpoint Essentials is a different
product; route it to `add-connector`.

**Try:**
- "connect Proofpoint TAP"
- "import TAP threat events into Ingext"

### setup-cortex-xdr-connector

**Palo Alto Cortex XDR** incidents/alerts. Guides creating an API key
(Settings → Configurations → Integrations → API Keys) — the key's security level must match the
connector's `authMode` (default **Advanced**, the nonce+timestamp anti-replay scheme) — collects
the Key ID and the `https://api-{fqdn}` API URL, then installs the `CortexXDR` connector.
Firewall syslog is a different connector; route it to `add-connector`.

**Try:**
- "connect Cortex XDR to Ingext"
- "import Palo Alto Cortex incidents"

### setup-salesforce-event-monitoring-connector

**Salesforce Event Monitoring** (EventLogFile). Hard prerequisite stated up front: the Event
Monitoring add-on license (standalone or Salesforce Shield). Guides setting up an External
Client App / Connected App with the OAuth client-credentials flow (run-as user needs
"API Enabled" + "View Event Log Files"), collects the My Domain base URL + consumer key/secret,
then installs the `SalesforceEM` connector. Honest latency: hourly EventLogFiles lag ~3–6 hours —
zero rows right after install is expected.

**Try:**
- "import Salesforce event monitoring logs into Ingext"
- "connect our Salesforce Shield event logs"

### setup-bitdefender-securitytelemetry-connector

**Bitdefender GravityZone Security Telemetry**. Inverted flow: installs the `BitdefenderST`
connector first (the platform generates a Splunk-compatible HEC url + token), then guides the
GravityZone admin to point policy → Security Telemetry at those values. Requires an EDR-capable
license; zero rows are expected until the policy applies and endpoints stream. The Event Push
(EP) variant routes to `add-connector`.

**Try:**
- "stream GravityZone security telemetry to Ingext"
- "set up Bitdefender Security Telemetry"

### setup-hec-passthrough

Generic **Splunk-HEC-compatible intake** for any product with a Splunk/HEC output but no
dedicated template (checked against the live template list first). Installs `HecPassthrough`
under a source-derived datalake index, hands the generated HEC url + token to the operator, and
guides the source-side pointing plus a smoke-test curl.

**Try:**
- "our appliance only speaks Splunk HEC — get its logs into Ingext"
- "generic HEC endpoint for Fluency"

---

## Utilities

### html-to-pdf

Converts an HTML file to a high-fidelity PDF using headless Chromium (Playwright).
Commonly chained after a skill that produces an HTML report.

**Try:**
- "convert this HTML to PDF"
- "save this report as a PDF"
- "export this to PDF"
- "I need a PDF version of this dashboard"
