# Ingext Skills

A collection of Claude Code skills for Fluency / Ingext users. Skills extend Claude with
specialised capabilities that activate automatically when you describe what you want.

---

## What is a Skill?

A `.skill` file is a self-contained plugin for Claude Code. Once installed, Claude
recognises trigger phrases and automatically invokes the skill's instructions and bundled
assets — no manual commands needed.

---

## Repository Layout

```
ingext_skills/
├── SKILLS/                          # Raw skill source files (browsable)
│   ├── fluency-report/              # SKILL.md + assets/, references/
│   ├── fortigate-bandwidth/         # SKILL.md
│   ├── fpl-report-builder/          # SKILL.md + references/
│   ├── html-to-pdf/                 # SKILL.md + scripts/
│   ├── ingext-kql/                  # SKILL.md + references/
│   ├── azure-user-signin-investigation/  # SKILL.md + assets/, evals/, scripts/ (FPL sign-in/dir-change reports)
│   └── office-user-investigation/   # SKILL.md + assets/, evals/, scripts/ (KQL Office365 table + GeoIP map)
└── cowork/                          # Pre-packaged .skill bundles (installable)
    ├── fluency-report.skill
    ├── fortigate-bandwidth.skill
    ├── fpl-report-builder.skill
    ├── html-to-pdf.skill
    ├── ingext-kql.skill
    ├── azure-user-signin-investigation.skill
    └── office-user-investigation.skill
```

- **`SKILLS/`** — the unpacked source of each skill, one folder per skill. Use this to
  read, review, or modify a skill's contents.
- **`cowork/`** — the same skills built as `.skill` packages (zip archives) ready to drop
  into Claude Code via Cowork.

---

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

### Updating skills

To get the latest version of any skill, ask Claude:

> "Update my Ingext skills from github.com/SecurityDo/ingext_skills"

Claude will pull the latest `.skill` files from the repository and replace the installed
versions.

### Manual install

If you prefer to install manually without the GitHub connector:

1. Download the desired `.skill` file from the [`cowork/`](cowork/) folder in this repo.
2. Open Claude Code and go to **Cowork → Customize**.
3. Drag and drop the file onto the plugins panel, or click **Add Plugin** and select it.

---

## Available Skills

### `fluency-report.skill`

Run any report from your Fluency / Ingext FPL catalog and get a branded, single-page HTML
summary — KPI cards, charts, tables, and a written interpretation of the data.

**Trigger phrases**

- "Run a Fluency report"
- "Run the Ingext `<ReportName>` report"
- "Give me a Fluency summary on `<topic>`"
- "Pull the Fluency `<ReportName>` report and summarize it"

> Fluency and Ingext are interchangeable — both trigger the skill.

**What you get**

- A browser-ready HTML file with Fluency branding
- KPI cards, bar/line/donut charts, and severity-coded tables tailored to the report's
  data shape
- A short written interpretation highlighting the highest-signal findings
- A suggested next-steps section

**Notes**

- Claude always lists your available reports first and matches your request against the
  real catalog. It will never invent or substitute a report that doesn't exist.
- If you ask for a report by name and it isn't in your catalog, Claude will tell you and
  list what's available.
- To also get a PDF, ask Claude to "convert it to PDF" after the HTML is generated — it
  will automatically chain into the `html-to-pdf` skill.

---

### `azure-user-signin-investigation.skill`

Investigate a user's **Azure AD / Entra ID sign-in and directory-change** activity by running
three Fluency FPL reports in parallel and combining the results into a single-page HTML
investigation report — sign-in timeline, executive summary, per-report data tables, and
security recommendations. Reads the `AzureSigninLogs` / `AzureAuditLogs` datalake tables.

> **Which user-investigation skill?** Use **`azure-user-signin-investigation`** for Azure AD
> sign-in history (IPs/apps/success-failure/location) and directory changes (role/group/
> password changes the user made or that targeted them), when the three FPL reports are
> deployed. Use **`office-user-investigation`** for mailbox / Office 365 activity (Exchange
> ops, hidden inbox rules / BEC, OAuth consents, geolocated source-IP map) by querying the
> `Office365` datalake table directly with KQL — including when the FPL reports aren't deployed.

**Trigger phrases**

- "Investigate Azure AD / Entra user `<email>`"
- "Pull `<email>`'s sign-in history on Fluency"
- "What directory changes did `<user>` make or receive?"
- "Run the Azure sign-in investigation for `<email>`"

**What you get**

- A browser-ready HTML investigation report with Fluency branding
- Chronological activity timeline merging sign-ins and directory changes
- Executive summary highlighting suspicious patterns (failed logins, unusual locations,
  privilege changes, etc.)
- Three per-report data tables: sign-in history, directory changes initiated by the user,
  and directory changes targeting the user
- Suggested next steps for the analyst

**Required reports in your FPL catalog**

- `GetDirectoryChangesInitiatedByUser`
- `GetDirectoryChangesTargetingUser`
- `GetUserSigninHistory`

If any of the three are missing, Claude will stop and tell you which ones are absent
rather than producing a partial report. (For tenants without these reports, use
`office-user-investigation` instead.)

---

### `office-user-investigation.skill`

Investigate a Microsoft 365 mailbox / Office 365 user by querying the **`Office365` datalake
table directly with KQL** (Office 365 Management Activity API data: Exchange, SharePoint,
AzureActiveDirectory, DLP). Geolocates every source IP offline (GeoLite2) and produces a
self-contained HTML report with a **GeoIP map**, KPI strip, executive summary, high-risk
findings, inbox-rule detail, per-country tables, sign-in timeline and recommendations — plus
an optional PDF. Works even when the Azure FPL reports / `AzureSigninLogs` tables aren't
deployed, as long as an `Office365` index exists.

**Trigger phrases**

- "Investigate O365 / mailbox user `<email>`"
- "Look into mailbox activity for `<email>`"
- "Check this account for BEC / inbox rules"
- "Run an Office user investigation"
- "Give me a GeoIP map of `<user>`'s logins"

**What you get**

- A self-contained HTML report (no internet needed to view) + optional PDF
- An inline-SVG **GeoIP map** of every source IP, colour-coded (primary user / other home /
  foreign / inbox-rule-creating) and sized by event volume
- KPI strip (sign-ins, failed logins, malicious inbox rules, suspicious IPs, OAuth consents)
- Data-driven verdict, high-risk findings, malicious inbox-rule detail, per-country and
  top-IP tables, daily sign-in timeline, and prioritised recommendations

**Requirements**

- An `Office365` datalake index on the tenant (Claude checks via `list_indexes`)
- Offline geolocation via the bundled GeoLite2 DB — always treat country/city as approximate
  and confirm with live threat intel before formal attribution

**Notes**

- Claude will ask for the username and time window (Last 24 hours, 7 days, 30 days, or
  custom) if you don't supply them up front.
- To get a PDF, ask Claude to "convert it to PDF" after the HTML is generated — it will
  chain into the `html-to-pdf` skill.

---

### `html-to-pdf.skill`

Convert any HTML file to a pixel-perfect PDF using headless Chromium (via Playwright).
Produces output identical to Chrome's "Print to PDF" — CSS grid, SVG charts, conic
gradients, and embedded images all render correctly.

**Trigger phrases**

- "Convert this HTML to PDF"
- "Save this as a PDF"
- "Export to PDF"
- "Make a PDF from this HTML file"
- "I need a PDF version"
- "Print this to PDF"

Claude will also offer to convert automatically after generating an HTML report.

**What you get**

- A `.pdf` file saved next to the source `.html` file by default
- Full fidelity rendering — everything Chrome can render, the PDF will contain
- Configurable page size, orientation, margins, and scale

**Supported options** *(you can ask Claude to apply any of these)*

| Option | Default | Description |
|---|---|---|
| Page size | A4 | A4, A3, Letter, Legal |
| Orientation | Portrait | Ask for landscape |
| Scale | 1× | E.g. "scale to 85%" to fit wide content |
| Margins | 15mm top/bottom, 10mm sides | Customisable |
| Single page | Off | "Fit everything on one page" |

**Notes**

- The first conversion in a session downloads a ~107 MB Chromium binary. Subsequent
  conversions in the same session reuse the cached binary and are much faster.
- If the HTML references Google Fonts, ask Claude to "wait longer for fonts to load" if
  text appears in a fallback font.

---

### `ingext-kql.skill`

Translate a natural-language question into a validated KQL query for the Ingext datalake.
Looks up the real indexes and schemas in your tenant before writing a single line of KQL,
so column names, field types, and table identifiers are always accurate.

**Trigger phrases**

- "Write me a KQL query for `<question>`"
- "Count denied Fortigate traffic by srcip in the last 6 hours"
- "Top 10 users by failed sign-ins yesterday"
- "Show behavior events with high scores today"
- Any natural-language description of what you want to search, count, or aggregate in the datalake

**What you get**

- A validated KQL query (passed through the parser before it reaches you)
- A 2-3 sentence explanation of what the query does and any assumptions made
- The list of index names the query references

**Workflow Claude follows**

1. Calls `list_indexes` to find the correct queryable table for your request
2. Calls `list_schemas` + `describe_schema` to get exact column names and types
3. Drafts KQL using the index name (not the schema name — these differ and the skill enforces the distinction)
4. Validates the query with `validate_kql` before returning anything
5. Returns `{ kql, explanation, tables }`

**Required connector tools**

`list_indexes`, `list_schemas`, `describe_schema`, `validate_kql` — available on the Ingext MCP connector.

**Notes**

- Every query is time-bounded. If you don't specify a time range the skill defaults to the last 24 hours and says so in the explanation.
- Bundled with KQL syntax reference, dynamic JSON column guide, and worked examples for group-by and facet queries — pulled on demand to keep context small.

---

### `fpl-report-builder.skill`

Author the source code for a Fluency / Ingext FPL report — a single file that compiles one
or more KQL queries into named sections behind a `main({from, to})` entry point. Hand it a
set of queries or just describe the sections you want, and it produces a ready-to-deploy
`.fpl` file with the time-range scaffold and the mandatory time filter wired into every
query.

**Trigger phrases**

- "Create an FQL/FPL report"
- "Turn these KQL queries into a report"
- "Build a report with an overview and a success-rate section"
- "Compile these queries into one report"
- "Scaffold an Office365 Exchange report"

> This skill *writes* a report definition. To run an existing report use `fluency-report`;
> to write a single standalone query use `ingext-kql`.

**What you get**

- A `.fpl` source file with the canonical `main` / `validateTimeRange` / `setEnv` scaffold
- One `GetXxx → kql(...)` section function per requested section, each labelled with a comment
- The mandatory `| where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))`
  filter enforced on every query, so one `from`/`to` pair drives the whole report
- A relative-time default window (yesterday by default; configurable per report cadence)

**Notes**

- Pure code authoring — the skill does not call MCP tools or query a live tenant, so it works
  without a connector. Confirm guessed column/table names against your schema before deploying.
- When you paste a query that hardcodes its own time filter (e.g. `ago(7d)` or a literal date
  range), the skill swaps in the standard window-driven filter and tells you it did.
- Bundled with a conventions reference (relative-time syntax, KQL building blocks, worked
  multi-section example) pulled on demand to keep context small.

---

### `fortigate-bandwidth.skill`

Reference knowledge for correctly calculating FortiGate traffic bandwidth from
`NetworkFortigateTraffic` data. FortiGate's `sentbyte`/`rcvdbyte` fields are
cumulative session counters, so naively summing them across periodic session logs
massively over-counts (a single long-lived session can inflate an hourly total to
petabytes). This skill teaches Claude to use the per-interval `sentdelta`/`rcvddelta`
values from the `_fields` JSON bag instead.

**Trigger phrases**

- "Top talkers by bandwidth / data volume"
- "Bandwidth by srcip / dstip"
- "Data usage per host on the FortiGate"
- "Busiest IPs", "traffic volume", any sum/ranking of FortiGate bytes

**What it changes**

- Replaces `sum(sentbyte)` with `sum(coalesce(tolong(_fields.sentdelta), sentbyte))`
  (and the received analog) — delta when present, cumulative byte as fallback
- Flags the `logid 0000000020` periodic-update records and how to include/exclude them
- Adds a bytes-per-packet sanity check to catch corrupt/cumulative values

> This is a knowledge skill — it carries no MCP tools of its own. It applies whenever
> FortiGate byte aggregation comes up, including indirectly via `ingext-kql`,
> `fluency-report`, or `fpl-report-builder`.

---

## Typical Workflow

```
You:    Run the Fluency IngestionRate report
Claude: [lists reports, matches IngestionRate, runs it, generates ingestionrate_report.html]

You:    Now convert it to PDF
Claude: [invokes html-to-pdf, produces ingestionrate_report.pdf]
```

---

## Requirements

- Claude Code with plugin support enabled
- Node.js available in the environment (for `html-to-pdf`)
- The Fluency Terps MCP connector added to Claude Code (for `fluency-report`) — see setup below

---

## MCP Connector Setup

The `fluency-report` skill requires the **Fluency Terps MCP connector** to query your
Ingext FPL catalog and run reports.

### Adding the connector

1. Open Claude Code and go to **Settings → Connectors** (or **MCP Servers**).
2. Add a new HTTP connector with your organisation's Ingext URL:
   ```
   https://<your-ingext-domain>/mcp
   ```
   For example: `https://terplab.yourdomain.ingext.io/mcp`
3. When prompted, authenticate via **OAuth login** using your Ingext credentials.
4. Save the connector. Claude Code will now have access to your FPL report catalog.

> Contact your Ingext administrator if you are unsure of your organisation's MCP URL.
