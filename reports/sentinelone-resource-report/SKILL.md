---
name: sentinelone-resource-report
version: 1.0.0
description: >-
  Produce a SentinelOne resource report for ONE Ingext/Fluency tenant as HTML (print and interactive), PDF and CSVs, built ONLY from the archive of the scheduled report SentinelOne_Resource_Report. It never runs kql_search, run_report or any live search and never downloads a resource dump. It lays out agents (reporting status, versions, protection mode), applications (risk levels, most widespread) and threats (history, open threats, trend), ranking which endpoints need action. USE THIS SKILL for "SentinelOne resource report", "SentinelOne inventory", "which SentinelOne endpoints are not reporting or need attention". DO NOT use it to search events, for agent coverage against other products (security-agent-deployment-status-report), OS support dates (endpoint-os-currency), a single host (ingext-get-profile), or a tenant with no archive.
---

# SentinelOne Resource Report

Answers: how many SentinelOne endpoints are reporting, which are silent or on an older agent, which are not in
protect mode, which applications carry risk and how widespread they are, how many threats were detected and which are
still open, and which endpoints need action first. It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `lake_search`, the
resource dump tools or anything else that queries the tenant. Every figure comes from `download_report_archive`. If days
are missing, say so and offer `backfill_report_archive`; never fill a gap by searching or by downloading a dump.

The archive is written by the scheduled report `SentinelOne_Resource_Report` (an FPL report, one UTC day per run,
archive enabled; source `Scripts/fplProcessors/code/SentinelOne_Resource_Report.js`). If `list_scheduled_report`
shows none on the tenant, stop and tell the user to deploy it first. Its tables:

| Table | What it holds |
|---|---|
| `s1res_summary` | One row: endpoints, active, inactive, not reporting over 7 days, not in protect mode, patch required, behind newest, needs action / watch / healthy, installs, distinct apps, risky installs and endpoints, threats, open threats, `asOf` |
| `s1res_endpoints` | One row per endpoint: name, type, OS, group, agent version, reporting state, days silent, protection mode, patch status, risky apps, score, status, reasons |
| `s1res_agent_versions` | Endpoints per agent version, newest flagged |
| `s1res_apps_risk`, `s1res_apps_top` | Installs and endpoints per risk level; the 25 applications on the most endpoints |
| `s1res_threats_class`, `s1res_threats_daily`, `s1res_threats_open` | Threats by class and status; threats per day; each open threat |

**These are snapshots, not events.** The SentinelOne tables have no history. Each archived day is the state when that
day's run took the snapshot. Never add days; the report uses the latest archived day and shows a change table of the
other days. A backfill cannot reconstruct a past state: it records today's console state under the past date, so say
that when offering it.

A run has three parts:

- **Download.** `download_report_archive` returns the archived days as a file.
- **Process locally.** `scripts/s1_resource_report.py` reads the file and writes `facts.json`, three CSVs, a
  Fluency-branded print-style HTML page and a self-contained interactive HTML file. It uses only the Python
  standard library.
- **Narrative.** You write the summary and next steps from `facts.json`.

`<skill-dir>` below means this skill's base directory.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Conekt). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | The last few days (for "current state") or a month; the report shows the latest day in the period. At most 92 days per download. |
| Report name | `SentinelOne_Resource_Report` unless the tenant uses another name. |
| Customer name | Optional. Shown in the subtitle. |

Work in a fresh directory, e.g. `./sentinelone_resources_<account>_<yyyymmdd>/`.

## Steps

### 1. Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and script
hashes. State the days archived out of the days in the period. The report reads the latest day, so a missing last day
means the report is older than the period end: say which date it is as of. Offer `backfill_report_archive` for gaps
and say what a backfill records (above); never fill a gap by searching.

If the report is not listed, the tenant has no SentinelOne archive: stop and tell the user to deploy and schedule it.

### 2. Download

`download_report_archive(account, name, from, to)`. A day is small (tens of KB), so a month downloads in one call. Save
the result to a file in the work directory and use it as is; do not print it or copy numbers by hand. It holds endpoint
names, so keep it in the work directory.

### 3. Health check

```bash
python3 <skill-dir>/scripts/s1_resource_report.py check --archive <work>/archive.json
```

It prints the days archived, the latest day, one line per table with its row count, any query that was not available in
the archived run, and the headline totals.

- `PROBLEM` (exit code 1) is no completed day, a missing summary or endpoint table, or a latest day more than 2 days
  old. Stop and tell the user. Do not render a report from empty or stale data.
- `warning` on an optional table means that panel is empty. Carry on and mention it.

### 4. Render

```bash
python3 <skill-dir>/scripts/s1_resource_report.py render --archive <work>/archive.json --work <work> \
  --account <account> --customer "<Customer>"
```

Pass every downloaded file to `--archive` if the period needed several. It prints the totals and writes to `<work>`:

- `sentinelone_resource_report.html`, the print-style page for the PDF, with `assets/logo2.png` copied next to it;
- `sentinelone_resource_report_interactive.html`, the file to open in a browser (see below);
- `facts.json`: every number on the page and the default narrative;
- `endpoints.csv`: every endpoint with its score, status and reasons;
- `applications_top.csv`: the 25 most widespread applications with publisher, risk and endpoints;
- `open_threats.csv`: every open threat.

`--max-listed N` caps the "Endpoints needing attention" table in the print-style report (default 40). The CSV and the
interactive file always have every endpoint.

**Interactive file.** One HTML file with no server and no internet needed. Tabs: Overview, Endpoints, Applications,
Threats and Coverage. Every table has search, sortable columns, filters, paging and an Export CSV button that
exports the filtered view. Tiles and bars on the Overview open the matching table already filtered. It follows the
browser's dark mode. Offer it for working through the endpoint list, and the PDF for a document to send.

**Personal data.** The files carry endpoint names and open-threat names, but no user names. Share them only with the
tenant's owner.

**What the archive does not carry.** The report has no scan-status or scan-age figures, no confidence breakdown of the
whole threat history (only the open threats show confidence), no publisher ranking, no machine-level application list
beyond the top 25, no per-endpoint threat history, no last logged-in user and no reboot-required flag. Do not state
those from memory; if the user needs them, say the scheduled report would have to be extended.

### 5. Write the narrative

The default narrative is generic. Read `facts.json`, filter the CSVs for specifics, then write
`<work>/narrative.json`:

```json
{
  "summary": ["<p>HTML for paragraph 1 (may use <strong>)</p>", "<p>paragraph 2</p>"],
  "nextSteps": [
    {"when": "This week", "tone": "urgent", "text": "Confirm the 4 unmitigated threats on FT-22-DISPATCH2 and REM-MART-1."},
    {"when": "Within 14 days", "tone": "normal", "text": "..."},
    {"when": "Quarterly", "tone": "routine", "text": "..."}
  ]
}
```

Run step 4 again; it picks up `narrative.json` automatically. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in the CSVs. Compute it; don't estimate.
- **Summary.** Two paragraphs: the fleet and its reporting health, then the threat and application picture. Each is at
  most about 90 words.
- **Next steps.** At most 6, ordered by urgency. `when` is one of: This week, Within 14 days, Within 30 days,
  Quarterly. `tone` is `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client:
  - Use no internal terms (dump, FPL, connector).
  - Hedge causes the data cannot show. A silent endpoint may be powered off, retired or renamed.
  - Say "open threat" only as defined on the page: not mitigated, or the incident is not resolved.

### 6. PDF and review

Open the interactive file in a browser (or Playwright) once. Every tab should render with no console error, and the
Endpoints search, filters and sort should change the row count.

Print `sentinelone_resource_report.html` (not the interactive file) to PDF on A4 with 12 mm margins, background graphics on and no scaling. With headless Chrome:

```bash
chromium --headless --no-pdf-header-footer --print-to-pdf=<work>/sentinelone_resource_report.pdf \
  file://<work>/sentinelone_resource_report.html
```

The report runs about five pages. If you can rasterise the pages, check that:
- no labels are clipped;
- the KPI strip and summary sit together on page 1.

### 7. Deliver

Give the interactive HTML, print-style HTML, PDF and the three CSV paths, plus two or three sentences: how many endpoints are not reporting, how
many threats are open, and the biggest application risk. State the day the report is as of and how many days were archived. Keep internal findings out of the PDF and put them in your
reply. Examples: a duplicate host name, silent endpoints whose last-active date the archive does not give, days missing from the archive.

## What the report does not cover

- Windows end-of-support dates: use `endpoint-os-currency`.
- Comparing SentinelOne with Defender or Entra: use `security-agent-deployment-status-report`.
- Live detections and alerts as they happen: use the SentinelOne alert investigation tools.

`references/methodology.md` covers the archive tables, the scoring and the data pitfalls.
