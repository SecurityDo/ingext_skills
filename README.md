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
| [create-ingext-defender-app](#create-ingext-defender-app) | Guide an Entra admin to register the `ingext-defender` app (Graph Security incidents + alerts) |
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
