---
name: falcon-resource-report
version: 1.0.0
description: >-
  Produce a CrowdStrike Falcon resource report for ONE Ingext/Fluency tenant as HTML (print and interactive), PDF and CSVs, built ONLY from the archive of the scheduled report CrowdStrike_Resource_Report. It never runs kql_search, run_report or any live search and never downloads a resource dump. It lays out host check-in health, sensor versions, protection gaps, policy coverage and 30 days of endpoint detections, ranking which hosts need action. USE THIS SKILL for "CrowdStrike resource report", "Falcon host inventory", "Falcon sensor health for tenant X", "which Falcon hosts have protection gaps or open detections". DO NOT use it to search events, triage alerts, for a single host (ingext-get-profile), agent coverage against other products (security-agent-deployment-status-report), OS support dates (endpoint-os-currency), or a tenant with no archive.
---

# CrowdStrike Falcon Resource Report

Answers: how many hosts does Falcon manage, how many have stopped checking in, how many run an older sensor release, which hosts have
a protection gap (reduced functionality mode, sensor not provisioned, no prevention policy, contained, uninstall protection off), how
complete the policy coverage is, how many endpoint detections were raised in the last 30 days, how many are still open, and which
hosts need action first. It is read-only and archive-only. It writes a print-style HTML page, a self-contained interactive HTML file (tabs, search,
sort, filters, CSV export, dark mode), a PDF and CSVs.

**The rule that defines this skill: no live searches and no dumps.** Never call `kql_search`, `run_report`, `lake_search`,
`list_resource_dumps`, `get_resource_dump_url` or anything else that queries the tenant. Every figure comes from
`download_report_archive`. If days are missing, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `CrowdStrike_Resource_Report` (an FPL report, one UTC day per run, 30-day detection
window, archive enabled, daily 04:35 UTC; source `fplProcessors/code/CrowdStrike_Resource_Report.js` in the Scripts repo). If
`list_scheduled_report` shows none on the tenant, stop and tell the user to deploy it first.

**These are snapshots, not events.** The Falcon host table has no history. Each archived day is the state when that day's run took the
snapshot (the detections are the 30 days before it). Never add days; the report uses the latest completed day. A backfill cannot
reconstruct a past host state: it records today's hosts under the past date, so say that when offering it.

`<skill-dir>` below means this skill's base directory.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Conekt). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | The last few days; the report reads the latest archived day in it. At most 92 days per download, and one or two days is enough. |
| Report name | `CrowdStrike_Resource_Report` unless the tenant uses another name. |
| Customer name | Optional; shown in the subtitle. |

Work in a fresh directory, e.g. `./falcon_resources_<account>_<yyyymmdd>/`.

## Steps

### 1. Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and script hashes. State the
days archived out of the days in the period and the date the report is as of. A missing last day means the latest figures are older
than the period end: say which date they are as of, and offer `backfill_report_archive` for the gap. If no day is archived, stop.

### 2. Download

`download_report_archive(account, name, from=<last day or two>, to=<last day>)` and save the result as `<work>/archive.json`. A day is
about 0.25 MB (counts and up to 500 host names with scores, no user names); use the saved file as is and do not print it or copy
numbers by hand. If several files were downloaded, pass all of them; the script takes the latest completed day across them.

### 3. Health check

```bash
python3 <skill-dir>/scripts/falcon_resource_report.py check --archive <work>/archive.json
```

It prints the as-of day, the days in the file and the host count, then any archived query that did not run. `PROBLEM` (exit code 1)
is no completed day, a day with no hosts (the tenant has no Falcon import) or a latest day older than 3 days. Stop and tell the user.

### 4. Render

```bash
python3 <skill-dir>/scripts/falcon_resource_report.py render --archive <work>/archive.json --work <work> \
  --account <account> --customer "<Customer>"
```

This prints the totals and writes to `<work>`:

- `falcon_resource_report.html`, the print-style page for the PDF, with `assets/logo2.png` copied next to it;
- `falcon_resource_report_interactive.html`, the file to open in a browser;
- `facts.json`: every number on the page, the as-of day, the coverage notes and the narrative;
- `hosts.csv`: the hosts the archive lists (those that score above 0, highest first, at most 500) with score, state and reasons;
- `alerts.csv`: the top 25 hosts with open detections;
- `policies.csv`: for each policy type, hosts assigned, not assigned and not applied.

`--max-listed N` caps the "Hosts needing attention" table in the print-style report (default 40). The CSV and the interactive file
carry every host the archive lists.

**What the archive does not carry, so the report does not show:** an operating-system breakdown, domains, sites, criticality, tags,
last logged-in user, duplicate host names, per-policy ids, and any host that scores 0 (healthy hosts are counted, not listed). The
fleet totals cover every host. If the host table is cut at 500 the Data notes say so.

### 5. Write the narrative

The default narrative is generic. Read `facts.json`, filter `hosts.csv` for specifics, then write `<work>/narrative.json`:

```json
{
  "summary": ["<p>HTML for paragraph 1 (may use <strong>)</p>", "<p>paragraph 2</p>"],
  "nextSteps": [
    {"when": "This week", "tone": "urgent", "text": "Restore full functionality on the 3 hosts in reduced functionality mode."},
    {"when": "Within 14 days", "tone": "normal", "text": "..."},
    {"when": "Quarterly", "tone": "routine", "text": "..."}
  ]
}
```

Run step 4 again; it picks up `narrative.json`. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in the CSV. Compute it; don't estimate. State the as-of date.
- **Summary.** Two paragraphs: the fleet and its check-in and sensor health, then the protection gaps, policy picture and detections.
  Each is at most about 90 words.
- **Next steps.** At most 6, ordered by urgency. `when` is one of: This week, Within 14 days, Within 30 days, Quarterly. `tone` is
  `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client: use no internal terms (archive, FPL, connector); hedge causes the data cannot show (a
  silent host may be powered off, retired or renamed); containment is often deliberate, so say a host "is contained", not compromised.

### 6. PDF and review

Open the interactive file in a browser (or Playwright) once. Every tab should render with no console error, and the Hosts search,
filters and sort should change the row count. Print `falcon_resource_report.html` (not the interactive file) to PDF on A4 with 12 mm
margins, background graphics on and no scaling:

```bash
chromium --headless --no-pdf-header-footer --print-to-pdf=<work>/falcon_resource_report.pdf \
  file://<work>/falcon_resource_report.html
```

The report runs about five to six pages. If you can rasterise the pages, check that no labels are clipped and the KPI strip and
summary sit together on page 1.

### 7. Deliver

Give the interactive HTML, print-style HTML, PDF and the three CSV paths, plus two or three sentences: the as-of date, how many hosts
are silent, how many have a protection gap, how many need action and how many detections are open. Keep internal findings out of the PDF
and put them in your reply (for example an archived day that is several days old, or an archived query that did not run).

## What the report does not cover

- Alert triage and investigation: the report counts and ranks detections per host; use the Falcon console or the alert tools to work
  them. Identity (IdP), data-protection and cloud alerts are shown as fleet totals only and do not affect host scores.
- Windows end-of-support dates: use `endpoint-os-currency`.
- Comparing Falcon with Defender or SentinelOne: use `security-agent-deployment-status-report`.

`references/methodology.md` covers the scoring and the archive tables.
