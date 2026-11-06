---
name: googleworkspace-resource-report
version: 1.0.0
description: >-
  Produce a Google Workspace users, groups and activity report for ONE Ingext/Fluency tenant as HTML (print and interactive), PDF and CSVs, built ONLY from the archive of the scheduled report GoogleWorkspace_Resource_Report. It never runs kql_search, run_report or any live search and never downloads a resource dump. It scores every user (Needs action, Watch, Healthy), shows 2-Step Verification enrolment and the admin gap, stale and never-signed-in accounts, org units, groups, and the sign-ins, suspicious logins, admin changes and app authorizations. USE THIS SKILL for "Google Workspace resource report", "Google Workspace user health for tenant X", "who has no 2-Step Verification". DO NOT use it to investigate one user or event, set up the connector (add-connector), or for a tenant with no archive.
---

# Google Workspace Resource Report

Answers: how many Google Workspace users there are, which need action first, who has no 2-Step Verification (and which admins), which
accounts are stale or never signed in, how users spread over org units and domains, how many groups there are, and what the audit activity of the archived days
looked like (sign-ins, failures, suspicious sign-ins, admin changes, app authorizations). It is read-only and
archive-only. It writes a print-style HTML page, a self-contained interactive HTML file (tabs, search, sort, filters, CSV export, dark
mode), a PDF and CSVs.

**The rule that defines this skill: no live searches and no dumps.** Never call `kql_search`, `run_report`, `lake_search`,
`list_resource_dumps`, `get_resource_dump_url` or anything else that queries the tenant. Every figure comes from
`download_report_archive`. If days are missing, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `GoogleWorkspace_Resource_Report` (an FPL report, one UTC day per run (`-1d@d` to `@d`),
archive enabled, daily; source `fplProcessors/code/GoogleWorkspace_Resource_Report.js` in the Scripts repo). If `list_scheduled_report` shows
none on the tenant, stop and tell the user to deploy it first.

**Snapshot tables are never added; activity is.** Each archived run covers one day. Users, org units, domains, groups, the account
counts and the scores come from the latest completed day only (adding them would count the same users again). The audit activity is merged
across every archived day: counts add, one row per day is kept once (the latest run wins if a day was archived twice), event types sum,
admin changes and suspicious sign-ins are unioned, and accounts is the busiest single day. Missing days are gaps, never zeros, and the report
shows days archived out of days expected. A backfill re-runs the audit window for a past date, but the user and group tables are always
today's directory, so it fills activity gaps only.

`<skill-dir>` below means this skill's base directory.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example the tenant's own MCP connector). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | The last few days; the report reads the latest archived day in it. At most 92 days per download, and one or two days is enough. |
| Report name | `GoogleWorkspace_Resource_Report` unless the tenant uses another name. |
| Customer name | Optional; shown in the subtitle. |

Work in a fresh directory, e.g. `./googleworkspace_<account>_<yyyymmdd>/`.

## Steps

### 1. Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and script hashes. State the
days archived out of the days in the period and the date the report is as of. A missing last day means the latest figures are older than
the period end: say which date they are as of, and offer `backfill_report_archive` for the gap. If no day is archived, stop.

### 2. Download

`download_report_archive(account, name, from=<last day or two>, to=<last day>)` and save the result as `<work>/archive.json`. A day is
small (counts plus up to 200 users and short event lists); use the saved file as is and do not print it or copy numbers by hand. If
several files were downloaded, pass all of them; the script takes the latest completed day across them.

### 3. Health check

```bash
python3 <skill-dir>/scripts/googleworkspace_resource_report.py check --archive <work>/archive.json
```

It prints the as-of day, the days in the file, the user, needs-action, admin-without-2SV and event counts, then any archived query that
did not run. `PROBLEM` (exit code 1) is no completed day, the user table and the audit stream both unavailable on the latest day (no
Google Workspace import on the tenant) or a latest day older than 3 days. Stop and tell the user. A tenant with no events is not a problem.

### 4. Render

```bash
python3 <skill-dir>/scripts/googleworkspace_resource_report.py render --archive <work>/archive.json --work <work> \
  --account <account> --customer "<Customer>"
```

This prints the totals and writes to `<work>`:

- `googleworkspace_resource_report.html`, the print-style page for the PDF, with `assets/logo2.png` copied next to it;
- `googleworkspace_resource_report_interactive.html`, the file to open in a browser;
- `facts.json`: every number on the page, the as-of day, the coverage notes and the narrative;
- `users.csv`: the users the archive lists (at most 200, needing attention first) with score, status and reasons;
- `groups.csv`: the top 100 groups by direct members;
- `daily.csv`: one row per archived day.

`--max-listed N` caps the "Users needing attention" table in the print-style report (default 20). The CSVs and the interactive file
carry every user the archive lists.

**What the archive does not carry, so the report does not show:** group member lists, mail or Drive content, and audit events beyond the
admin change and suspicious sign-in lists. Counts cover every user; the user table is cut at 200 and the Data notes say so.

### 5. Narrative (optional)

The report's structure is fixed by the script: the same KPI strip, summary, panels, tables and recommended next steps every run.
The summary and next-steps text are generated from the numbers by the script, so a plain `render` already produces a complete,
repeatable report. **Do not add, remove or reorder sections, charts or tables, and do not hand-edit the HTML.**

Only when the user asks for tailored wording, read `facts.json` and write `<work>/narrative.json` with just two keys, `summary`
(2-3 short HTML paragraphs) and `nextSteps` (at most 6 items with `when`, `tone`, `text`), then run step 4 again. Every number
must come from `facts.json` or a count of CSV rows; state the as-of date; write for the client (no internal terms such as archive,
FPL or connector); hedge causes the data cannot show. Without `narrative.json` the built-in text is used.

### 6. PDF and review

Open the interactive file in a browser (or Playwright) once. Every tab should render with no console error, the Trend explorer dropdown
should redraw the chart, and the Users search, filters and sort should change the row count. Print
`googleworkspace_resource_report.html` (not the interactive file) to PDF with the brand renderer (US Letter):

```bash
node <fluency-report>/scripts/render_pdf.mjs --input <work>/googleworkspace_resource_report.html --output <work>/googleworkspace_resource_report.pdf
```

If you can rasterise the pages, check that no labels are clipped and the KPI strip and summary sit together on page 1.

### 7. Deliver

Give the interactive HTML, print-style HTML, PDF and the three CSV paths, plus two or three sentences: the as-of date, how many users,
how many need action, how many admins lack 2-Step Verification and whether any sign-in was flagged. Keep internal findings out of the PDF
and put them in your reply (for example an archived day that is several days old, or an archived query that did not run).

## What the report does not cover

- Investigating one user or event: use `ingext-kql` for the underlying events.
- Connecting Google Workspace to the tenant: use `add-connector`.
- Mail or Drive content and per-group membership.

`references/methodology.md` covers the scoring and the archive tables.

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own
copy: the build scripts here that style a report find the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and
import `fluency_brand` from it, and stop with a clear message if it is not installed. Install `fluency-report` alongside this skill. In the steps below, `<fluency-report>` means
that skill's folder.

- The HTML report is one self-contained file (mark, fonts and CSS inlined). The PDF is rendered from that same HTML with the same
  CSS, so the two match: `node <fluency-report>/scripts/render_pdf.mjs --input report.html --output report.pdf`.
  US Letter, same editorial styling as the HTML (brandline, closing footer line; no paged footer). It needs Playwright
  (`npm install playwright`) and a Chromium or Chrome binary; it finds a Chrome install automatically.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore
  the brand CSS (grid, fonts, page rules), so the PDF would not match the HTML.
- Do not hand-write report styling. The look is the Fluency editorial style (white paper, IBM Plex, black rules, one blue / red / amber, no cards or gradients). A new page is `fluency_brand.page(...)`; markup from an older script goes
  through `fluency_brand.apply_brand(html)`. Design and component reference: the `fluency-report` skill (`references/widget_recipes.md`).
