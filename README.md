# Ingext Skills

A collection of skills for the Ingext / Fluency platform. A skill is a bundle of
instructions (and sometimes scripts and reference data) that Claude loads when it
recognises a matching request, letting it carry out a specific task — querying the
datalake, running a report, investigating a user, checking site health, and more.

- Skill sources live in [`SKILLS/`](./SKILLS) (each is a folder with a `SKILL.md`).
- [`reports/`](./reports) holds report skills only: skills that produce a finished report
  document (HTML / PDF / CSV) from tenant data, such as security agent deployment status, O365
  activity and compliance assessment. Skills about *handling*
  reporting (running, rolling up, authoring or building dashboards for FPL reports) stay in
  `SKILLS/`. Same layout either way.
- Packaged, installable skills live in [`cowork/`](./cowork) as `*.skill` files.
- Change history is in [`release_notes/`](./release_notes).

Each skill is versioned independently in its `SKILL.md` frontmatter. The inventory below
lists all **54 skills** across `SKILLS/` and `reports/`, with the version, source and
matching downloadable package. Packages are ZIP archives with a `.skill` extension.

## Installation

### Claude Code — install a source folder

Clone this public repository; a GitHub connector or GitHub login is not required:

```bash
git clone https://github.com/SecurityDo/ingext_skills.git
cd ingext_skills
```

Copy the **whole skill folder**, including scripts, references and assets, into a
Claude Code skills directory. For example, to install `ingext-kql` for your user:

```bash
mkdir -p "$HOME/.claude/skills"
cp -R SKILLS/ingext-kql "$HOME/.claude/skills/"
```

For a project-scoped installation, copy it into `.claude/skills/` in that project
instead. Report skills install the same way; for example:

```bash
cp -R reports/ciso-monthly-report "$HOME/.claude/skills/"
```

Install prerequisites named in the skill as well. For `ciso-monthly-report`, those
are `health-status-report` and `compliance-assessment`. Start Claude Code and use
`/ingext-kql` or `/ciso-monthly-report`, or describe the task normally.

To update, pull the repository and replace the installed folder with the current
source folder. Installing only `SKILL.md` omits supporting files the skill needs.
See [Claude Code's skills documentation](https://code.claude.com/docs/en/skills).

### Claude / Cowork — upload a packaged skill

1. Download the matching file from [`cowork/`](./cowork) using GitHub's **Download raw file** action.
2. The `.skill` file is already a ZIP archive. If the upload picker requires `.zip`,
   rename the downloaded file's extension to `.zip`; do not zip the archive again.
3. Open **Customize → Skills**, select **+ → Create skill → Upload a skill**,
   upload the archive and enable the skill. Enable code execution and file creation
   if your account requires it.
4. Upload and enable any prerequisite skills too, then start a new Cowork session
   or Claude chat and describe your task.

Cowork uses the skills enabled for your Claude account; it does not read local
`~/.claude/skills/` folders. To update an uploaded skill, upload the current package
through the Skills UI and check that the intended version is enabled.
See [Anthropic's upload instructions](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
and [Cowork skill loading](https://code.claude.com/docs/en/skills#use-skills-in-cowork-and-cloud-sessions).

### Connect the platform separately

Installing a skill supplies instructions and supporting files. Platform skills also
need a configured Ingext / Fluency MCP connection with the permissions and data
sources their instructions require. Installing a skill does not configure that connection.

### Renamed skill: CISO monthly report

`CISO_monthly_report` is now **`ciso-monthly-report`**. The source folder, frontmatter
name and package use the new name. Its `metadata.aliases` records the old name for
catalog consumers, and the instructions recognize requests using the legacy name.
This metadata does not register an old slash command in Claude Code: update automation
to `/ciso-monthly-report`, install the new folder/package, and remove the old installed
copy after migration. The former README anchor is retained below for existing links.

## Generated release catalog

Each published catalog release contains **`catalog.json` and one downloadable `.skill`
archive per source skill**. Packages are built directly from `SKILLS/` and `reports/`,
so the release does not depend on manually refreshed copies in `cowork/`.

After the first catalog workflow publishes on `master`, API consumers can fetch:

[Latest catalog JSON](https://github.com/SecurityDo/ingext_skills/releases/latest/download/catalog.json)
· [Published releases and direct downloads](https://github.com/SecurityDo/ingext_skills/releases)

The latest URL follows GitHub's latest release. To keep that URL dedicated to this
catalog, leave unrelated releases unmarked as latest. These endpoints become available
when the first catalog release is published; generating a local preview does not publish it.

### API contract

Read `catalog.json` as JSON; there is no need to scan GitHub folders or parse skill
frontmatter at request time. Its top-level fields are:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | Catalog format version, currently `1`; separate from individual skill versions |
| `repositoryUrl` | Source repository |
| `sourceRevision` | Full Git commit SHA used for every entry and package |
| `sourceCommittedAt` | Commit timestamp; deterministic rather than the build's wall-clock time |
| `releaseTag` | `catalog-` followed by the full source commit SHA |
| `skills` | All published skills, sorted by `id` |

Every skill entry includes `id`, `name`, `version`, `description`, `category` (`skill`
or `report`), `aliases`, `sourcePath`, `sourceUrl`, `fileCount` and `download`:

```json
{
  "filename": "ciso-monthly-report.skill",
  "url": "https://github.com/SecurityDo/ingext_skills/releases/download/catalog-FULL_COMMIT_SHA/ciso-monthly-report.skill",
  "format": "zip",
  "sha256": "SHA256_OF_THE_ARCHIVE",
  "sizeBytes": 28569
}
```

This is an illustrative `download` object; use the actual URL, checksum and size from
the catalog. `download.url` is the direct package download, with no GitHub file-preview
page in between. It names a specific release, so cached catalogs keep pointing at their
matching packages when a newer catalog appears. `sourceUrl` also names the exact commit.
Skill versions change independently; `sourceRevision` identifies the complete catalog snapshot.

An API can cache this document, list its entries, resolve legacy IDs through `aliases`,
and return each `download` object unchanged. Retain the last successfully loaded catalog
if a refresh fails. A package downloader can verify `sha256` and `sizeBytes` against the
actual bytes before offering or installing the archive. Catalog discovery does not
mean a skill is already installed or usable with a particular tenant's permissions.

### Build and publish

```bash
python3 -m pip install -r scripts/requirements-catalog.txt
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/build_catalog.py --output dist
```

The builder requires committed source skill changes, checks names, versions, descriptions
and alias collisions, and writes a new or empty output directory. Archives include the
complete source skill with normalized ZIP timestamps, ordering and permissions, preserving
executable scripts. `dist/` is ignored by Git. Use a fresh output directory for another build.
The generated JSON and packages are release assets, not files to commit to `master`.

[The catalog workflow](./.github/workflows/skill-catalog.yml) validates and builds previews
for pull requests. A successful build on `master` creates a draft GitHub release, uploads
all packages and `catalog.json`, checks the asset inventory, then publishes the release
as latest. Readers see the catalog only after its packages are uploaded. Retrying an
interrupted draft resumes the upload; an already published release is left unchanged.
Old queued builds do not replace the current catalog. The workflow can also be run
manually on `master`. It uses the repository's GitHub Actions token with release-write
permission; no separate API service or GitHub token needs to be distributed to downloaders.

## Editing skills

Skill frontmatter is validated before it can be committed. Two rules bite most often:
`description` must be at most **1024 characters** (the folded YAML value, not the raw
block) and it must contain **no XML-style tags** — write `a tenant`, not `<tenant>`.

Enable the hook once per clone:

```bash
git config core.hooksPath .githooks
```

Run it by hand, or in CI, against the working tree:

```bash
python3 scripts/validate_skills.py --worktree
```

With no flag it validates the **staged** content, which is what the pre-commit hook uses.

Note that `cowork/*.skill` packages embed their own copy of `SKILL.md`. Editing
`SKILLS/<name>/SKILL.md` (or `reports/<name>/SKILL.md`) requires rebuilding the package in the same change. The validator checks frontmatter
in both source and archives; it does not check that their full file contents match.

## Skills at a glance

| Skill | Version | Source | Package | What it does |
| --- | --- | --- | --- | --- |
| [customer-onboarding](#customer-onboarding) | 1.0.0 | [Source](./SKILLS/customer-onboarding) | [Download](./cowork/customer-onboarding.skill) | Front door for a new customer: menu of applications → route to the right setup skill → verify ingestion |
| [ingext-kql](#ingext-kql) | 1.1.5 | [Source](./SKILLS/ingext-kql) | [Download](./cowork/ingext-kql.skill) | Generate a validated KQL query over the datalake |
| [ingext-promql](#ingext-promql) | 1.0.4 | [Source](./SKILLS/ingext-promql) | [Download](./cowork/ingext-promql.skill) | Generate / run PromQL for platform metrics |
| [azure-log-analytics-search](#azure-log-analytics-search) | 1.0.0 | [Source](./SKILLS/azure-log-analytics-search) | [Download](./cowork/azure-log-analytics-search.skill) | Search the customer's own Azure Log Analytics / Sentinel workspace live with KQL |
| [fortigate-bandwidth](#fortigate-bandwidth) | 1.0.0 | [Source](./SKILLS/fortigate-bandwidth) | [Download](./cowork/fortigate-bandwidth.skill) | Correct FortiGate bandwidth aggregation rules |
| [fluency-report](#fluency-report) | 1.0.3 | [Source](./SKILLS/fluency-report) | [Download](./cowork/fluency-report.skill) | Run an existing FPL report → HTML summary |
| [compliance-assessment](#compliance-assessment) | 1.8.2 | [Source](./reports/compliance-assessment) | [Download](./cowork/compliance-assessment.skill) | Per-tenant, per-month NIST SP 800-53 evidence report from the tenant's own telemetry → HTML + PDF |
| [fluency-report-rollup](#fluency-report-rollup) | 1.0.1 | [Source](./SKILLS/fluency-report-rollup) | [Download](./cowork/fluency-report-rollup.skill) | Monthly / quarterly / trend report assembled from a scheduled report's archived daily runs |
| [fpl-report-builder](#fpl-report-builder) | 1.0.1 | [Source](./SKILLS/fpl-report-builder) | [Download](./cowork/fpl-report-builder.skill) | Author an FPL report definition from KQL |
| [fpl-report-dashboard](#fpl-report-dashboard) | 1.0.0 | [Source](./SKILLS/fpl-report-dashboard) | [Download](./cowork/fpl-report-dashboard.skill) | Build, test, deploy and release a dashboard report: panels, layout, metric charts |
| [ciso-monthly-report](#ciso-monthly-report) | 1.0.2 | [Source](./reports/ciso-monthly-report) | [Download](./cowork/ciso-monthly-report.skill) | Customer-facing CISO Monthly SOC report for one tenant: 8 chapters, 16 sections, computed figures, GAP and PARTIAL marked → HTML |
| [health-status-report](#health-status-report) | 1.2.2 | [Source](./reports/health-status-report) | [Download](./cowork/health-status-report.skill) | Installed applications health for a tenant, using the Fluency 9 Applications-page status logic → HTML + PDF + CSV |
| [mssp-coverage-map](#mssp-coverage-map) | 1.0.1 | [Source](./reports/mssp-coverage-map) | [Download](./cowork/mssp-coverage-map.skill) | Fleet map of licensed Microsoft 365 seats against EDR endpoints and users per tenant, with the gaps ranked → HTML + CSV |
| [mssp-ops-sitrep](#mssp-ops-sitrep) | 1.0.2 | [Source](./reports/mssp-ops-sitrep) | [Download](./cowork/mssp-ops-sitrep.skill) | Shift-handoff SitRep across a connector's accounts: queue, escalations, health, product posture, four team lanes → HTML |
| [office365-posture-review](#office365-posture-review) | 1.0.1 | [Source](./reports/office365-posture-review) | [Download](./cowork/office365-posture-review.skill) | Office 365 / Entra posture from resource dumps: users, app registrations and devices, ranked by severity → HTML + CSV |
| [nist-compliance-analysis](#nist-compliance-analysis) | 1.0.1 | [Source](./reports/nist-compliance-analysis) | [Download](./cowork/nist-compliance-analysis.skill) | NIST SP 800-53 control-by-control analysis from compliance-assessment results, with CSF 2.0 and 800-171 child views → HTML + CSV |
| [iso-cmmc-compliance-analysis](#iso-cmmc-compliance-analysis) | 1.2.1 | [Source](./reports/iso-cmmc-compliance-analysis) | [Download](./cowork/iso-cmmc-compliance-analysis.skill) | ISO/IEC 27001:2022 and CMMC 2.0 companion view of the 800-53 evidence, related not equivalent → HTML + CSV |
| [pci-dss-compliance-analysis](#pci-dss-compliance-analysis) | 1.3.1 | [Source](./reports/pci-dss-compliance-analysis) | [Download](./cowork/pci-dss-compliance-analysis.skill) | PCI DSS v4.0.1 companion view of the 800-53 evidence, related not equivalent → HTML + CSV |
| [hipaa-compliance-analysis](#hipaa-compliance-analysis) | 1.3.1 | [Source](./reports/hipaa-compliance-analysis) | [Download](./cowork/hipaa-compliance-analysis.skill) | HIPAA Security Rule companion view of the 800-53 evidence → HTML + CSV |
| [soc2-compliance-analysis](#soc2-compliance-analysis) | 1.3.1 | [Source](./reports/soc2-compliance-analysis) | [Download](./cowork/soc2-compliance-analysis.skill) | SOC 2 Trust Services Criteria companion view of the 800-53 evidence → HTML + CSV |
| [cis-compliance-analysis](#cis-compliance-analysis) | 1.3.1 | [Source](./reports/cis-compliance-analysis) | [Download](./cowork/cis-compliance-analysis.skill) | CIS Critical Security Controls v8.1 companion view of the 800-53 evidence → HTML + CSV |
| [fedramp-compliance-analysis](#fedramp-compliance-analysis) | 1.3.1 | [Source](./reports/fedramp-compliance-analysis) | [Download](./cowork/fedramp-compliance-analysis.skill) | FedRAMP Rev. 5 baseline view of the 800-53 evidence → HTML + CSV |
| [gdpr-compliance-analysis](#gdpr-compliance-analysis) | 1.3.1 | [Source](./reports/gdpr-compliance-analysis) | [Download](./cowork/gdpr-compliance-analysis.skill) | GDPR security-of-processing companion view of the 800-53 evidence → HTML + CSV |
| [endpoint-os-currency](#endpoint-os-currency) | 1.0.1 | [Source](./reports/endpoint-os-currency) | [Download](./cowork/endpoint-os-currency.skill) | Endpoint OS inventory, end-of-support and build-currency report from an EDR or Entra device dump → HTML + PDF + CSV |
| [security-agent-deployment-status-report](#security-agent-deployment-status-report) | 1.1.0 | [Source](./reports/security-agent-deployment-status-report) | [Download](./cowork/security-agent-deployment-status-report.skill) | Per-device EDR / agent coverage report (SentinelOne, Defender, Entra ID, Horizon3 network scans); runs with whatever inventories the tenant has → HTML + PDF + CSV |
| [azure-user-signin-investigation](#azure-user-signin-investigation) | 1.0.4 | [Source](./SKILLS/azure-user-signin-investigation) | [Download](./cowork/azure-user-signin-investigation.skill) | Investigate Azure AD sign-ins & directory changes |
| [proofpoint-investigation](#proofpoint-investigation) | 1.0.0 | [Source](./SKILLS/proofpoint-investigation) | [Download](./cowork/proofpoint-investigation.skill) | Investigate one Proofpoint email: sender, direction, delivery, threat, clicks and blast radius from the event rows |
| [office-user-investigation](#office-user-investigation) | 1.0.4 | [Source](./SKILLS/office-user-investigation) | [Download](./cowork/office-user-investigation.skill) | Investigate an M365 mailbox user (KQL + GeoIP) |
| [o365-activity-report](#o365-activity-report) | 1.0.2 | [Source](./reports/o365-activity-report) | [Download](./cowork/o365-activity-report.skill) | Account-wide O365/Exchange activity report (KQL: timechart + tables) |
| [incident-investigation](#incident-investigation) | 1.6.5 | [Source](./SKILLS/incident-investigation) | [Download](./cowork/incident-investigation.skill) | Triage an escalated behavior incident / AI-assist ticket to a verdict |
| [ingext-get-profile](#ingext-get-profile) | 1.0.1 | [Source](./SKILLS/ingext-get-profile) | [Download](./cowork/ingext-get-profile.skill) | Resolve a user, group or device to its profile: admin, roles, MFA, status; OS, last user, join state, EDR health |
| [ingext-log-analytics-evidence](#ingext-log-analytics-evidence) | 1.0.0 | [Source](./SKILLS/ingext-log-analytics-evidence) | [Download](./cowork/ingext-log-analytics-evidence.skill) | The incident checks that read a customer's own Log Analytics workspace (few accounts have one): sessions, Graph, containment, endpoint triggers, Azure changes |
| [ingext-health-monitor](#ingext-health-monitor) | 1.0.2 | [Source](./SKILLS/ingext-health-monitor) | [Download](./cowork/ingext-health-monitor.skill) | Check whether a site is healthy and ingesting |
| [add-connector](#add-connector) | 1.0.0 | [Source](./SKILLS/add-connector) | [Download](./cowork/add-connector.skill) | Install a new application connector |
| [deploy-fpl-processor](#deploy-fpl-processor) | 1.0.0 | [Source](./SKILLS/deploy-fpl-processor) | [Download](./cowork/deploy-fpl-processor.skill) | Deploy an FPL processor to a tenant and wire it into the running pipeline |
| [eventwatch-rule](#eventwatch-rule) | 1.1.1 | [Source](./SKILLS/eventwatch-rule) | [Download](./cowork/eventwatch-rule.skill) | Create, test, threshold and deploy an EventWatch behavior / aggregation rule |
| [parser-rule](#parser-rule) | 1.1.0 | [Source](./SKILLS/parser-rule) | [Download](./cowork/parser-rule.skill) | Create, test, deploy and release a parser rule: a registered rule matched in FPL, emitting into CorrelationService |
| [setup-aws-cloudtrail-connector](#setup-aws-cloudtrail-connector) | 1.0.0 | [Source](./SKILLS/setup-aws-cloudtrail-connector) | [Download](./cowork/setup-aws-cloudtrail-connector.skill) | Set up the AWS CloudTrail connector: S3 → SQS notification, cross-account role, real-time import |
| [setup-aws-guardduty-connector](#setup-aws-guardduty-connector) | 1.0.0 | [Source](./SKILLS/setup-aws-guardduty-connector) | [Download](./cowork/setup-aws-guardduty-connector.skill) | Set up the Amazon GuardDuty connector: assume-role, per-region detector check, API poll |
| [create-ingext-audit-app](#create-ingext-audit-app) | 1.0.0 | [Source](./SKILLS/create-ingext-audit-app) | [Download](./cowork/create-ingext-audit-app.skill) | Guide an Entra admin to register the `ingext-audit` app (Graph + O365 audit import) |
| [create-ingext-audit-app-azcli](#create-ingext-audit-app-azcli) | 1.0.0 | [Source](./SKILLS/create-ingext-audit-app-azcli) | [Download](./cowork/create-ingext-audit-app-azcli.skill) | az CLI variant of `create-ingext-audit-app`: cowork can run it directly when the operator is the tenant's Global Admin |
| [create-ingext-defender-app](#create-ingext-defender-app) | 1.0.0 | [Source](./SKILLS/create-ingext-defender-app) | [Download](./cowork/create-ingext-defender-app.skill) | Guide an Entra admin to register the `ingext-defender` app (Graph Security incidents + alerts) |
| [billing-csv](./SKILLS/billing-csv/SKILL.md) | 1.3.0 | [Source](./SKILLS/billing-csv) | [Download](./cowork/billing-csv.skill) | Per-client billing CSV from the daily usage ledger and billable-user inventory |
| [ingext-entity-tables](./SKILLS/ingext-entity-tables/SKILL.md) | 1.0.0 | [Source](./SKILLS/ingext-entity-tables) | [Download](./cowork/ingext-entity-tables.skill) | Discover and query entity lookup tables, watchlists and reference values |
| [aws-cloudtrail-activity-report](./reports/aws-cloudtrail-activity-report/SKILL.md) | 1.0.1 | [Source](./reports/aws-cloudtrail-activity-report) | [Download](./cowork/aws-cloudtrail-activity-report.skill) | AWS CloudTrail activity report from archived daily report results |
| [microsoft365-entra-activity-report](./reports/microsoft365-entra-activity-report/SKILL.md) | 2.0.1 | [Source](./reports/microsoft365-entra-activity-report) | [Download](./cowork/microsoft365-entra-activity-report.skill) | Microsoft 365 and Entra activity report from archived daily report results |
| [windows-server-activity-report](./reports/windows-server-activity-report/SKILL.md) | 1.0.2 | [Source](./reports/windows-server-activity-report) | [Download](./cowork/windows-server-activity-report.skill) | Windows Server activity report from archived daily report results |
| [fortigate-security-activity-report](./reports/fortigate-security-activity-report/SKILL.md) | 1.0.1 | [Source](./reports/fortigate-security-activity-report) | [Download](./cowork/fortigate-security-activity-report.skill) | FortiGate security activity report from archived daily report results |
| [microsoft365-resource-inventory-report](./reports/microsoft365-resource-inventory-report/SKILL.md) | 1.0.1 | [Source](./reports/microsoft365-resource-inventory-report) | [Download](./cowork/microsoft365-resource-inventory-report.skill) | Microsoft 365 / Entra directory inventory (users, MFA, devices, apps, groups, licenses) from archived daily snapshots, with an interactive HTML view |
| [sentinelone-resource-report](./reports/sentinelone-resource-report/SKILL.md) | 1.0.1 | [Source](./reports/sentinelone-resource-report) | [Download](./cowork/sentinelone-resource-report.skill) | SentinelOne agents, applications and threats in one report (endpoint status, agent versions, risky apps, open threats) from the archive of the scheduled report SentinelOne_Resource_Report, with an interactive HTML view |
| [falcon-resource-report](./reports/falcon-resource-report/SKILL.md) | 1.0.1 | [Source](./reports/falcon-resource-report) | [Download](./cowork/falcon-resource-report.skill) | CrowdStrike Falcon hosts and detections in one report (host health, sensor releases, policy coverage, open detections per host) from the archive of the scheduled report CrowdStrike_Resource_Report, with an interactive HTML view |
| [ransomware-readiness-report](./reports/ransomware-readiness-report/SKILL.md) | 1.0.0 | [Source](./reports/ransomware-readiness-report) | [Download](./cowork/ransomware-readiness-report.skill) | Board ransomware readiness report: overall rating, eight-pillar scorecard, ranked issues with owners and MITRE, 90-day roadmap → HTML + PDF |
| [cyber-risk-in-dollars-report](./reports/cyber-risk-in-dollars-report/SKILL.md) | 1.0.0 | [Source](./reports/cyber-risk-in-dollars-report) | [Download](./cowork/cyber-risk-in-dollars-report.skill) | Board cyber risk in dollars: expected annual loss, 1-in-10 and 1-in-20 year loss, loss exceedance curve, risk register and the dollar value of each action (FAIR Monte Carlo) → HTML + PDF |
| [defender-resource-report](./reports/defender-resource-report/SKILL.md) | 1.0.1 | [Source](./reports/defender-resource-report) | [Download](./cowork/defender-resource-report.skill) | Microsoft Defender for Endpoint devices in one report (enrolment, check-in, antivirus, vulnerabilities, secure configuration, recommendations, alerts, ranked devices) from the archive of the scheduled report Defender_Resource_Report, with an interactive HTML view |
| [guardduty-resource-report](./reports/guardduty-resource-report/SKILL.md) | 1.0.0 | [Source](./reports/guardduty-resource-report) | [Download](./cowork/guardduty-resource-report.skill) | AWS GuardDuty findings in one report (severity, finding types and categories, accounts and regions, resources, repeat-heavy findings, ranked findings, 30 days of daily counts) from the archive of the scheduled report GuardDuty_Resource_Report, with an interactive HTML view |
| [googleworkspace-resource-report](./reports/googleworkspace-resource-report/SKILL.md) | 1.0.0 | [Source](./reports/googleworkspace-resource-report) | [Download](./cowork/googleworkspace-resource-report.skill) | Google Workspace users and activity in one report (user health score, 2-Step Verification and admin gaps, stale and never-signed-in accounts, org units, groups, 30 days of sign-ins, suspicious logins and admin changes) from the archive of the scheduled report GoogleWorkspace_Resource_Report, with an interactive HTML view |

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
- "using the ingext_kql skill, how many assets do we have by category and provider"

### azure-log-analytics-search

Searches the customer's **own Azure Log Analytics / Microsoft Sentinel workspace** live
with KQL — nothing is ingested, every call reaches their Azure tenant. Discovers tables
and ASIM parsers with `azure_logs_list_tables`, resolves columns with
`azure_logs_get_schema`, parse-validates, then runs the query. Not the datalake: for
ingested event data use **ingext-kql**.

**Try:**
- "search the customer's Sentinel workspace for failed sign-ins in the last hour"
- "what tables are in their Azure Log Analytics workspace"
- "which ASIM parsers does the workspace have, and what columns does ASimAuthentication return"
- "run `SigninLogs | summarize count() by ResultType` against Azure for yesterday"

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

### fluency-report-rollup

Builds a week, month, quarter or trend version of a scheduled report from its archive:
the report runs once a day for exactly that day, and each day is kept for 12 months. The
skill checks coverage first and reports or backfills missing days. It merges the dailies
the way the report computes its numbers (sum by key, each time bucket once, top-N and
totals recomputed), using the bundled `scripts/rollup.py`. fluency-report then renders the
result. It also covers ranges the report refuses to run directly, such as a quarter.

**Try:**
- "give me the monthly System_Event_Ingress_Report for September"
- "build a Q3 ingress report from the daily archive"
- "show month-over-month ingress for the last three months"
- "which days are missing from the archive for this report? backfill them"

### compliance-assessment

Builds a customer-facing compliance evidence report for one tenant and one month, mapped onto
13 NIST SP 800-53 Rev. 5 control groups as supported, partial, not observed or needs manual
review. It checks `list_data_tables` first, queries event tables (Office 365, Entra, Windows,
CloudTrail and any network, endpoint or identity table the tenant has) with KQL, and takes inventory
and account-hygiene data (MFA registration, administrators, guests, device sign-in age) from resource
dumps. Every figure is rendered by a script from saved raw results. It never says compliant or
certified. Lives in [`reports/`](./reports).

**Try:**
- "run the compliance assessment for <tenant> for September on the Develop connector"

<a id="ciso_monthly_report"></a>

### ciso-monthly-report

Builds the monthly SOC story for one tenant as a single HTML report for a CISO: an executive summary
with a Green, Amber or Red rating, what happened, repeat patterns, what can and cannot be seen, a
risk register, response performance, a NIST SP 800-53 evidence add-on and a remediation plan. It
reads the tenant's behavior summaries (cases), the health-status-report result and the
compliance-assessment results through its MCP connector; `scripts/build_report.py` computes every
figure from the saved results and marks anything the connector cannot supply as GAP or PARTIAL. The
report separates the automated assistant's first response from an analyst's. The analyst writes only
the narrative. **Prerequisites: install the health-status-report and compliance-assessment skills first.** Lives in [`reports/`](./reports).

**Try:**
- "run the CISO monthly report for <tenant> for September"
- "build the M-SOC monthly report for <tenant>"

### health-status-report

Reports the health of every installed application on a tenant as HTML, PDF and a per-application CSV,
with the same status logic as the Fluency 9 Applications page (Running, Error, Attention, Disabled,
Other). It reads `list_connector_config` where the connector has it, else `list_connectors` (state only),
removes credentials, and saves the result as `health.json`, which `ciso-monthly-report` reuses. For
platform-wide health (logins, queues, egress) use ingext-health-monitor. Lives in [`reports/`](./reports).

**Try:**
- "run the installed applications health report for <tenant>"
- "which of <tenant>'s applications are in error or need attention?"

### mssp-coverage-map

Compares, for every tenant a provider can act on, the licensed Microsoft 365 seats with the endpoints and
users in its EDR dumps (CrowdStrike Falcon, SentinelOne, Microsoft Defender), flags the gap and sorts
tenants into EDR under-coverage, aligned, identity-blind, endpoint-blind and not assessable. It reads one
`list_resource_dumps` per account and downloads the `office365User` and EDR dumps of the accounts that have
them; a script computes every figure and writes an HTML map and a CSV. The gap is directional, not exact.
Lives in [`reports/`](./reports).

**Try:**
- "which of my customers have EDR coverage gaps?"
- "build the identity versus endpoint coverage map for all tenants"

### mssp-ops-sitrep

A shift-handoff page for the team running a portfolio of tenants. It reads each account's behavior summaries
(tickets scored 3,000 or more), plus the optional health-status-report and mssp-coverage-map results, and
shows the queue, unworked and escalated tickets, application health, product posture for Office365,
CrowdStrike Falcon and SentinelOne, and what the SOC Manager, Administrator, Operator and Investigator
lanes should do next. Everything is computed by a script; anything not collected says so. It keeps no
state. Lives in [`reports/`](./reports).

**Try:**
- "give me the operations sitrep for all accounts on <connector>"
- "what is escalated or unworked across my customers this week?"

### office365-posture-review

Reviews a tenant's Office 365 / Entra inventory for hygiene and misconfiguration: privileged users, weak MFA
factors, OAuth-connected users, stale token baselines; app registrations with HTTP redirects, implicit grant,
no verified publisher or no credentials; and rooted, non-compliant, unmanaged, stale or unattributed devices.
It downloads the `office365User`, `office365Application` and `office365Device` dumps and a script computes
every finding. It is resource posture, not activity. Lives in [`reports/`](./reports).

**Try:**
- "do an Office 365 posture review for <tenant>"
- "which of <tenant>'s app registrations use implicit grant or HTTP redirects?"

### nist-compliance-analysis

Reads the result of `compliance-assessment` and writes a NIST SP 800-53 Rev. 5 control-by-control analysis:
scope, counts by status, a table of control, status, evidence state and next evidence to collect, and an
optional CSF 2.0 / SP 800-171 Rev. 3 child view that keeps the 800-53 lineage. It collects nothing itself, uses
statuses exactly as returned, and never treats "not observed" as a failure. Prerequisite: `compliance-assessment`.
Lives in [`reports/`](./reports).

**Try:**
- "give me the NIST 800-53 control-by-control analysis for <tenant>"
- "which controls lack evidence, and what should we collect next?"

### iso-cmmc-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in ISO/IEC 27001:2022
Annex A and CMMC 2.0 Level 2 language: each control or practice with its related 800-53 groups and their
statuses, a caveat, the strongest mapped areas and the evidence still needed. Rows are related, never
equivalent, and nothing is a certification or assessment result. It collects nothing itself. Prerequisite:
`compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in ISO 27001 terms"
- "map the NIST findings to CMMC practices for <tenant>"

### pci-dss-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in PCI DSS v4.0.1 language (10.x logging, 8.x authentication, 11.3 scans, 1.x network controls, 12.10 incident response): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in PCI DSS v4.0.1 terms"

### hipaa-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in the HIPAA Security Rule language (164.312 technical safeguards and the 164.308 administrative standards): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in the HIPAA Security Rule terms"

### soc2-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in the SOC 2 Trust Services Criteria language (the Security (Common Criteria) category, CC5 to CC7): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in the SOC 2 Trust Services Criteria terms"

### cis-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in CIS Critical Security Controls v8.1 language (safeguards for inventory, accounts, MFA, vulnerabilities, logs, malware and incident response): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in CIS Critical Security Controls v8.1 terms"

### fedramp-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in the FedRAMP Rev. 5 baselines language (the 800-53 controls that appear in the Low, Moderate and High baselines): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in the FedRAMP Rev. 5 baselines terms"

### gdpr-compliance-analysis

Reads the result of `compliance-assessment` and expresses the 800-53-rooted evidence in GDPR language (Articles 5, 24, 30, 32, 33 and 34 security-of-processing evidence): each requirement with its related 800-53 groups and statuses, a caveat, the strongest mapped areas, and what telemetry cannot evidence. Rows are related, never equivalent, and nothing is a certification or compliance finding. It collects nothing itself. Prerequisite: `compliance-assessment`. Lives in [`reports/`](./reports).

**Try:**
- "show our compliance evidence in GDPR terms"

### endpoint-os-currency

Reports which operating systems a tenant's endpoints run, which Windows releases are past or near
the end of vendor support, and which hosts are on an older build than the rest of the fleet. It
reads one resource dump (CrowdStrike `falconAgent`, else `sentinelOneAgent`, else Entra
`office365Device`), computes everything locally and renders HTML, PDF and a per-host CSV. Support
dates come from a curated, dated table in the script. Lives in [`reports/`](./reports).

**Try:**
- "which of <tenant>'s endpoints are on an unsupported OS?"
- "run the endpoint OS currency report for <tenant>"

### fpl-report-builder

Authors an FPL report *source file* by compiling one or more KQL queries into a
single time-bounded report definition. For **writing** the definition — not running
it (use fluency-report) and not for single standalone queries (use ingext-kql).

**Try:**
- "create an FPL report from these queries"
- "turn these KQL queries into a report"

### fpl-report-dashboard

Builds a dashboard report end to end: the `fpl_report` script (metric queries, status
tables, metric streams), its `reportConfig` panels and 16-column layout, testing with
`processor test` and `run_report`, deploying a test copy with its layout, and the Scripts
repo release. Includes the chart-alignment fix for dashboards whose charts read zero, a
panel cookbook, a deploy helper and a worked example (Windows host health).

**Try:**
- "build a dashboard for these metrics"
- "add a host health report with CPU and disk charts"
- "the report's charts all show zero"
### security-agent-deployment-status-report

Builds a client-ready security agent deployment status report for an account: which active
devices have every required agent installed and reporting, which are missing one, and which have
an agent that went silent. It downloads the account's inventory resource dumps (by default
SentinelOne, Microsoft Defender for Endpoint, Entra ID as a reference, and the hosts Horizon3.ai
NodeZero pentests found on the network), matches devices across them by Entra device ID, then by
hostname, then (for network-scan hosts) by IP address, and processes everything locally with a
standard-library Python script — no FPL report, processor, or search queries. An inventory that is
missing, empty or broken is left out of the run and named in the report, so a broken integration is
never reported as missing agents and a tenant without every integration still gets a report.
Network devices found by the scan are counted as "no agent expected" and hosts with no detectable
OS as "unidentified", outside the percentages. Output is a Fluency-branded HTML page and PDF plus a
`devices.csv` of every device. The inventories are set in `sources.json`, so adding Intune,
CrowdStrike, another agent or another network scanner is a config change.

**Try:**
- "run the agent deployment status report for account X"
- "which devices are missing SentinelOne or Defender?"
- "give me an EDR coverage report for customer Y"
- "deployment gap report for the Fluency account, as a PDF"
- "which hosts did Horizon3 find that have no EDR agent?"

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

### proofpoint-investigation

Investigates one Proofpoint message from the tenant's own Proofpoint events: who sent it, who
received it, inbound or outbound (from the participants, not the cluster label), whether it was
delivered or blocked, what Proofpoint flagged, whether there is click evidence, and how many other
messages share the threat. `scripts/proofpoint_verdict.py` computes the verdict from the saved
`kql_search` rows and the answer separates confirmed facts, inferences and unknowns. For a general
behavior incident use incident-investigation.

**Try:**
- "who sent this Proofpoint email and was it delivered?" (with a GUID or recipient and day)
- "investigate this Proofpoint alert for <tenant>"

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

### o365-activity-report

Produces an **account-wide** (whole-tenant, not a single user) Microsoft 365 activity
report by querying the `Office365` datalake table directly with KQL and rendering the
*real* results deterministically as a KPI strip, a **timechart**, and ranked breakdown
**tables** in a self-contained HTML page (optional PDF). Three focuses: `all` (every
workload), `exchange` (mailbox activity), and `mailitemsaccessed` (who accessed which
mailboxes, external vs owner, from where). This is the KQL, account-wide counterpart of
`fluency-report` (FPL) and `office-user-investigation` (single user). Every figure is
rendered by the build script from the saved query output — a query that returns nothing
shows an explicit "no data" panel; numbers are never synthesized.

**Try:**
- "report on Office365 Exchange activity in the last 24 hours"
- "MailItemsAccessed activity report for the account"
- "account-wide O365 activity timechart by workload today"

### microsoft365-entra-activity-report

Produces a Microsoft 365 and Entra activity report for **one tenant and a period** (a calendar
month by default) as HTML, PDF and CSV, built **only from the archive** of the scheduled report
`Office365_Entra_Activity_Report`. It never runs a live search: it lists the archive, downloads the
archived daily results, merges them and lays out Office 365 audit events, Entra user sign-ins,
directory-audit changes and service-principal and non-interactive sign-ins, with breakdowns,
archive coverage, gap days and any table the tenant does not have. Counts add across days;
distinct counts and top-N lists are labelled as peaks and lower bounds.

**Try:**
- "Microsoft 365 activity report for last month"
- "Entra sign-in report for October"
- "failed sign-ins and mailbox activity last month"

### aws-cloudtrail-activity-report

Produces an AWS CloudTrail activity report for **one tenant and a period** as HTML, PDF and CSV,
built **only from the archive** of the scheduled report `CloudTrail_Activity_Report`. It merges the
archived daily results into events, errors, access denied, console logins and MFA, IAM changes,
root-identity events and CloudTrail changes, with breakdowns by service, region, identity type and
error code, plus archive coverage and gap days. A gap is shown as a gap, never as zero.

**Try:**
- "CloudTrail activity report for last month"
- "root and IAM activity report"
- "AWS audit activity summary"

### fortigate-security-activity-report

Produces a FortiGate security activity report for **one tenant and a period** as HTML, PDF and CSV,
built **only from the archive** of the scheduled report `Fortigate_Security_Activity_Report`. It lays
out failed SSL-VPN logins (by device, country, source address and user, with a spray / brute-force /
probe pattern), VPN sessions and IPsec tunnels, application-control and web-filter blocks, IPS and DoS
anomalies, and administrator logins and configuration changes, with archive coverage, gap days and
the scans the tenant could not run. User and IP tables can be left out with `--no-actors`.

**Try:**
- "FortiGate activity report for last month"
- "VPN failed logins last month"
- "FortiGate admin changes report"

### windows-server-activity-report

Produces a Windows server activity report for **one tenant and a period** as HTML, PDF and CSV,
built **only from the archive** of the scheduled report `WindowsSrv_Activity_Report` (it reads the
`WindowsAudit` table). It covers what the older ingress report returns (events and bytes by host and
by event ID, with names from the `AD_EventID` lookup) and adds user logons and failures, failed-logon
sources with a spray / brute-force / probe pattern, privileged logons, account and group changes,
services and scheduled tasks installed, and audit-log clears and policy changes, with archive
coverage and gap days. User and IP lists can be left out with `--no-actors`. An optional single-file
interactive page (tabs, search, sort, filters, CSV export, trend dropdown, daily counts tab) is built with `--interactive`.

**Try:**
- "Windows server activity report for last month"
- "failed Windows logons last month"
- "were any audit logs cleared on the domain controllers"

### microsoft365-resource-inventory-report

Produces a Microsoft 365 / Entra resource inventory report for **one tenant** as HTML, PDF and CSV,
built **only from the archive** of the scheduled report `Office365_Resource_Inventory_Report`. It
shows users, administrators and MFA registration (naming the enabled users with no MFA, administrators
first), devices, Conditional Access policies by state, app registrations with client-secret hygiene and
app-only permissions, enterprise applications, groups, and licensed users with users per license. The
directory tables are snapshots, so the report shows the latest archived day and a trend over the days
instead of adding them. `--interactive` also writes a single self-contained HTML file with tabs, search,
sort and filter on the user lists, CSV export and hover trend charts. User lists can be left out with
`--no-actors`.

**Try:**
- "Microsoft 365 resource report for Acme"
- "which enabled users have no MFA"
- "administrators without MFA and expired app secrets"

### sentinelone-resource-report

Produces a SentinelOne resource report for **one tenant** as HTML (print-style and interactive), PDF and
CSV, built **only from the archive of the scheduled report `SentinelOne_Resource_Report`** (an FPL report in
the Scripts repo, daily). It never runs a search and never reads a resource dump. It covers reporting state
(endpoints silent for more than 7 days), agent versions against the newest build in the fleet, protection
mode, application risk levels and the most widespread applications, threat history by classification and
week, open threats (not mitigated or not resolved), and a ranked list of endpoints that need action. Each
archived day is a snapshot: the report uses the latest day and shows a change table across the days. The
interactive HTML file has tabs, search, sort and filter on every table and CSV export of the filtered view,
and dark mode.

### falcon-resource-report

Produces a CrowdStrike Falcon resource report for **one tenant** as HTML (print-style and interactive), PDF and
CSV, built **only from the archive of the scheduled report `CrowdStrike_Resource_Report`** (an FPL report in
the Scripts repo, daily 04:35 UTC). It never runs a search and never reads a resource dump. It covers
check-in state, sensor releases against the newest three in the fleet, platforms and roles, prevention and
other policy coverage, detections of the last 30 days by severity, status and tactic, hosts with open High or
Critical detections, and a ranked list of hosts that need action. Healthy hosts are counted but not listed.
Identity, data-protection and cloud alert products are shown as fleet totals only. The interactive HTML file
has tabs, search, sort and filter on every table and CSV export.

### ransomware-readiness-report

Assesses **one tenant's** ability to prevent, withstand and recover from ransomware and renders a board-level
report (HTML and PDF) in the Fluency editorial style: an overall rating, an eight-pillar scorecard, six to ten
ranked issues (what we found, why the board should care, recommendation, owner, target, MITRE technique), a
90-day roadmap and the strengths to keep. Evidence comes from resource dumps downloaded and parsed locally
(SentinelOne or CrowdStrike agents, Defender, Entra users and conditional-access policies) and from the archived
Windows server and Entra sign-in reports; nothing is queried live and a missing source is a visibility gap, not a
guess. Colours and severities follow documented thresholds (`references/rating_thresholds.md`), and the renderer
computes the overall rating from the pillar statuses. Names no users, hosts or IPs. Read-only. The
cyber-risk-in-dollars report reuses this evidence.

### cyber-risk-in-dollars-report

Quantifies **one tenant's** cyber risk in dollars for the board and CFO: expected annual loss, 1-in-10 and 1-in-20
year loss, a loss exceedance curve, a quantified risk register (ransomware, business email compromise, cloud data
breach) and the dollar value of each recommended action, by FAIR-style Monte Carlo simulation, rendered as HTML and
PDF in the Fluency editorial style. It requires the ransomware-readiness-report evidence and a short intake (revenue
or downtime cost, insurance limit, risk appetite, control costs; all optional). Frequencies and losses come from
documented rules (`references/calibration_rules.md`), never typed in by hand; anything the telemetry cannot measure
widens the range and is stated. Read-only; names no users, hosts or IPs.

### defender-resource-report

Produces a Microsoft Defender for Endpoint resource report for **one tenant** as HTML (print-style and
interactive), PDF and CSV, built **only from the archive of the scheduled report `Defender_Resource_Report`**
(an FPL report in the Scripts repo, daily). It never runs a search and never reads a resource dump. It covers
enrolment (onboarded against can-be-onboarded, insufficient information and unsupported), check-in recency,
operating systems, antivirus health, exposure and risk, vulnerabilities by severity and exploitability, the
top exploitable CVEs and software, secure configuration compliance and the most common failing settings,
security recommendations, alerts and incidents (informational alerts shown but not scored), and a ranked list
of devices that need action with the reasons. The interactive HTML file has tabs, search, sort and filter on
every table and CSV export.

### guardduty-resource-report

Produces an AWS GuardDuty findings report for **one tenant** as HTML (print-style and interactive), PDF and
CSV, built **only from the archive of the scheduled report `GuardDuty_Resource_Report`** (an FPL report in the
Scripts repo, daily). It never runs a search and never reads a resource dump. GuardDuty re-sends a finding each
time it sees more of the same activity, so findings are counted once by id at their latest update. It covers
severity (high, medium, low), findings updated in the last 24 hours and 7 days, new findings, finding types
and categories, accounts and regions, the resources affected, repeat-heavy findings, GuardDuty's current list,
a ranked list of findings that need action with the reasons, and 30 days of daily counts. The interactive HTML
file has tabs, a trend dropdown, search, sort and filter on every table and CSV export.

### googleworkspace-resource-report

Produces a Google Workspace users, groups and activity report for **one tenant** as HTML (print-style and
interactive), PDF and CSV, built **only from the archive of the scheduled report
`GoogleWorkspace_Resource_Report`** (an FPL report in the Scripts repo, daily). It never runs a search and never
reads a resource dump. Every user gets a documented score (Needs action, Watch, Healthy; suspended and archived
accounts are Disabled). It covers 2-Step Verification enrolment and enforcement, admins without it, stale and
never-signed-in accounts, recovery info, accounts outside the main domain, org units, groups, and the sign-ins,
failed and suspicious logins, admin changes and app authorizations of every archived day (each run is one day;
users and scores are the latest snapshot, activity is added across days, missing days are shown as gaps). The interactive HTML file has tabs,
a trend dropdown, search, sort and filter on every table and CSV export.

### incident-investigation

Takes an escalated Fluency behavior incident — a risk score, an alert, an AI-assist ticket
marked actionable — and works it to a verdict. Pulls the behavior summary and the AI-assist
result out of the eventwatch API, then runs the four checks that actually decide the answer:
the **fleet base rate** for the rule that fired (a rule firing for 33 users in a week is a
rollout, not an attack), every source IP **resolved against the rest of the tenant**, the
device that **approved** the change read out of `StrongAuthenticationPhoneAppDetail`, and the
negatives — inbox rules, forwarding, OAuth grants, removed MFA factors — that a benign
verdict rests on. Carries the error-code, user-agent, duplicate-row and GeoIP traps that
manufacture findings that are not there. Ends in a written closure with the detection tuning
that stops the next eleven copies of the same ticket.

Has a dedicated workflow per incident type: Office365 / Entra ID, Teams helpdesk
impersonation, Okta, SentinelOne and Google Workspace (the Google one separates a first
interactive login from a genuinely new address, and reads the approving device from the
mobile sync report); anything else runs a generic workflow. The helpdesk workflow covers
mail bombing, outside "IT" contacts on Teams and the intrusion that follows. There the
attacker works through the employee's own computer during a call, so clean sign-ins clear
nothing and the verdict rests on whether the employee engaged and what ran on the device.

Depends on **ingext-get-profile** for step 1 (what the subject and every target IS), and,
on the few accounts with an AzureLogAnalytics integration, on
**ingext-log-analytics-evidence** for the checks that read the customer's workspace.
For the whole mailbox rather than one incident, use **office-user-investigation**; to write
the suppression the base-rate check calls for, use **eventwatch-rule**.

**Try:**
- "investigate this incident on <tenant>"
- "the AI assist says actionable — check it"
- "get the behavior summary for <user> and tell me if it's real"
- "why did <user> score 3600?"
- "should we escalate this alert?"

### ingext-get-profile

Resolves one entity — a user, a group or a device — on one tenant account and returns
what it **is**. Reads the account's resource tables from `list_data_tables` to decide whether the
entity is a Google Workspace user (`gsuiteUser`), a Microsoft 365 user (`office365User`),
both or neither, queries every directory present (matching aliases, UPNs, guest mail
addresses and object ids), and for Microsoft users also reads the live Graph record. Returns
a normalized profile — status, admin flags and full role list, MFA / 2-Step Verification
state, aliases, recovery contacts, group type — plus the tables it checked and any gaps.
For a device it checks Defender, Entra/Intune, SentinelOne, CrowdStrike and Qualys (whichever
the account has) and returns OS, last user, IPs, join and compliance state, and each EDR
agent's health, plus Defender risk and exposure. It accepts a behavior-summary id such as
`asset_<host>_<date>` directly. A sub-skill of **incident-investigation**; also usable on its
own.

**Try:**
- "get the profile for <user> on <tenant>"
- "is <user> a Google or Office 365 user?"
- "is this account an admin?"
- "look up the group <object id>"
- "what is asset_<host>_<date>?"
- "profile the host <hostname>"

---

## Platform operations

### ingext-log-analytics-evidence

The workspace half of **incident-investigation**, for the few accounts that connect the
customer's own Azure Log Analytics workspace. There the workspace, not the datalake, is the
evidence: non-interactive sign-ins, where a stolen session was captured and everywhere it
was replayed, the Microsoft Graph requests its tokens made, whether the password was really
changed (including an on-prem reset that never synced) and whether anyone used it after
containment; for a Defender for Endpoint alert, the exact process or PowerShell line it fired
on, who logged on to the host, and who created, deleted or rebuilt the host in Azure. Nine
bundled `la_*` queries, run with the `azure_logs_*` tools. incident-investigation step 0
decides whether it applies; for free-form workspace queries use **azure-log-analytics-search**.

**Try:**
- "trace this session id in the customer's Log Analytics"
- "what did the stolen token ask Graph for?"
- "was <user>'s password really changed, and did anyone use it afterwards?"
- "what did this Defender custom detection actually fire on?"
- "who rebuilt <host> in Azure?"

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

### deploy-fpl-processor

Moves an FPL processor from a repo onto a tenant and wires it into the tenant's running
pipeline, through the provider proxy (`INGEXT_SITE_URL`/`INGEXT_TOKEN` from
`/etc/fluency_grid_config.json`, then `--gridaccount <tenant>`). The order is the point:
prove the script on its fixtures, rehearse the mechanics on a scratch tenant, then
**validate the mapping against the target tenant's own records** before anything is wired —
that step is what catches the vendor shapes no sample contains. Wiring is done by
`assets/ingext-pipe.mjs`, built on the `ingext-api` TypeScript client: it creates the redis
sink and the pipe with the `priority` and ownership tags an app-installed pipe carries, is
idempotent, reads back what was stored, and unwires in one call. It also covers publishing a
plugin binary and the `platform_source_reload` that makes it live, and releasing an object to
the repo registries with `sync_cli` so it reaches tenants beyond the one it was deployed to.
For installing a vendor connector rather than deploying a script, use **add-connector**.

**Try:**
- "deploy Varonis_Behavior to the acme tenant"
- "push this parser to the customer site and wire it into the pipeline"
- "add a behavior pipe for the Falcon app on fabrikam"
- "roll out the new processor, but test it somewhere safe first"

### eventwatch-rule

Creates, tests and deploys an EventWatch rule — the behavior and aggregation rules that turn
parsed events into behavior signals. The order is the point: read the tenant's **real** event
shapes with `datalake search` before writing a selector (`ingext kql` returns no rows for the
`default` index), then choose the threshold by replaying real history rather than guessing.
`assets/replay-threshold.py` computes the per-key maximum in a sliding window and the alert
count at each candidate threshold — which is how you find that `gt 5` against a probe that
peaked at exactly 5 fires never, and that 89% of your matches are a noise class that should
be excluded first. Its `--overlap` mode catches the other classic defect: a selector matching
several stages of one logical action, raising two behavior events per login.

Covers the id rule that cannot be undone — **`id > 0` is global and becomes read-only in the
tenant** (`update` and `delete` both refused, only `toggle` works), so iterate with `id: 0`
and ship with the allocated id — plus `sync_cli release <repo> rule` (which
`release ... fplProcessor` does **not** do), and the sticky disabled flag and flip-not-set
toggle that decide whether a synced rule actually runs. `assets/check-rule-state.py` asserts
the content that landed and is pollable while waiting on a sync.
For deploying the parser that produces the events, use **deploy-fpl-processor**.

**Try:**
- "create an eventwatch rule to track SSL-VPN logins by user"
- "add an aggregation rule for multiple failed logins in a few hours"
- "why is this rule never firing?"
- "promote the local test rule to the global one on <tenant>"

### parser-rule

Creates, tests, deploys and releases a parser rule: a registered EventWatch rule with
`parser` set, whose matching runs in an FPL channel rule instead of the eventwatch engine. The
channel rule writes the same hit and aggregation lines eventwatch would into the
`CorrelationService` sink, and fsm_service, mantis and the behavior summary service treat them
exactly like an eventwatch rule's — so a parser release no longer restarts the rule's warm-up.

Covers when to choose a parser rule over a static rule or a dynamic behavior signal, the
never-matching selector the rule file must carry in both forms, the line formats (strings in a
hit line's `valueMap`, `__undefined` for a missing field, seconds in `ts`), local validation
with `fplJobValidate -signals` over sample events, `rule_test` (which runs the stored
processor for a parser rule), and wiring a **site-local** caller pipe at priority 1500 that
returns `"abort"`, so a test never edits a released processor that the next sync would
overwrite. Then tagging the stored event's `@behaviors` from the channel rule as eventwatch
does for a static rule (hit rules with timeline or risks, never aggregations, an array of
strings set before the event is sunk), reading fsm_service's `parserSignalFile` keep/drop
counts, comparing side by side with the static rule, warm-up, and `sync_cli release` of the
rule and the channel rule.
`assets/` holds the kql pilot's working rules and channel rules.
For the rule's behaviorRule, correlations and thresholds, use **eventwatch-rule**.

**Try:**
- "create a parser rule for Office365 logins, matched in FPL"
- "move this static rule's matching into the parser and compare the two"
- "why are my parser rule's signals dropped?"
- "release the parser rule and its channel rule"

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

### setup-aws-guardduty-connector

End-to-end setup of the **Amazon GuardDuty** connector, using an STS **assume-role** rather than an
access key. GuardDuty is an **API poll**, not an S3 delivery — there is no bucket, no SQS queue and
no prefix, which is the main thing to unlearn if you arrive from **setup-aws-cloudtrail-connector**.
It drives the six-step runbook — `get_account_podrole` for the tenant pod role ARN → the customer
runs the `IngextSaasPodRole` and `GuardDutyRole` CloudFormation templates (bundled in `assets/`),
overriding `GuardDutyRole`'s `IAMRole` default → confirm a GuardDuty **detector actually exists** in
every region to be polled → `add_assumed_role` plus `test_assumed_role` → `create_connector` with
Regions and AWS Role. The step with no analogue elsewhere is the detector check: a region with
GuardDuty switched off returns no findings and the poll still succeeds, so the failure is a silent
empty index. Verification uses `create-sample-findings` rather than waiting for real ones, because a
healthy GuardDuty in a quiet account produces none for days.

**Try:**
- "set up the GuardDuty connector for us-east-1, without an access key"
- "import GuardDuty findings into Ingext"
- "the GuardDuty index is empty and nothing is erroring"
- "what will GuardDuty cost before I enable the other regions?"

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

---
