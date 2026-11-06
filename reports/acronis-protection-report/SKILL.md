---
name: acronis-protection-report
version: 1.0.0
description: >-
  Produce an Acronis Cyber Protect data review for ONE Ingext/Fluency tenant and a period (a calendar month
  by default) as HTML and PDF, built ONLY from the archive of the scheduled report Acronis_Protection_Report.
  It never runs kql_search, run_report or any other live search: it lists the archive, downloads the archived
  daily results, merges them and lays out open EDR cases, agents with stale protection definitions or no
  Active Protection, agent hygiene (stale and duplicate records, installer versions, failed updates), backup
  results and alert quality, with the archive coverage and any gap days. USE THIS SKILL for "Acronis report",
  "Acronis data review", "Acronis Cyber Protect monthly", "EDR cases in Acronis", "Acronis agent hygiene".
  DO NOT use it to search Acronis events, to investigate one device or incident, or for a tenant that has no
  archive (deploy and schedule the report first).
---

# Acronis Protection Report

Answers: which Acronis EDR cases are still open, which online agents are not updating or have no Active
Protection, how many agent records are stale or duplicated, how many agents are behind the current installer,
how many backups failed, and how much of the alert volume is re-sends and web-filter noise. It is read-only and
archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `lake_search`,
`behavior_*` or anything else that queries the tenant's data. Every figure comes from `download_report_archive`.
If the archive is missing days, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `Acronis_Protection_Report` (an FPL report that runs once a day for
exactly one UTC day, with the archive enabled). If `list_scheduled_report` shows no such report on the tenant, stop and
tell the user to deploy it first: its script is `references/Acronis_Protection_Report.js` and the steps are in
`references/archive_format.md`, section "Producing the archive". A tenant without the AcronisCP connector archives empty
tables, so the build stops with "nothing to report".

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names. Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Customer name | The name on the report cover. Ask if it is not obvious from the tenant. |
| Period | A calendar month by default (the last full month if none is named). A custom range is fine, at most 92 days per download; a quarter is downloaded month by month and every file is passed to the script. |
| Report name | `Acronis_Protection_Report` unless the tenant uses another name. |

## Step 1 - Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted and `missingDays`.
Compare with the period and tell the user the number of missing days before building. If the `scriptHashes` list has more
than one value, the report script changed inside the period; say so, because days may not be comparable.

If days are missing and the user wants them, `backfill_report_archive(account, name, from, to)` (one backfill at a time
per account, at most 92 days, about 6 to 10 seconds a day), then check again with `list_report_archive`. Backfilled event
tables are correct for their day, but the inventory tables of a backfilled day show the inventory as it is when the backfill
runs (see "Snapshot tables" below).

## Step 2 - Download

`download_report_archive(account, name, from, to)`. A month is about 2 MB, so the harness saves it to a file: use that file
as is. Do not print it and do not hand-copy numbers out of it. If the result arrives inline, write it to a scratch file
outside the repository.

## Step 3 - Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant acme --client "Acme Ltd" \
  --out WORKDIR/report.html --summary-json WORKDIR/acronis_summary.json
```

This writes the fixed report, `report.html`, with the Fluency brand. It is the source of the PDF (Step 4) and of the written
summary.

The **interactive HTML is the explorer**, the same format as the Microsoft 365 / Entra activity explorer. Build it from the same
archive files:

```bash
python3 scripts/build_explorer.py --archive ARCHIVE1.json [ARCHIVE2.json ...] --tenant acme --client "Acme Ltd" \
  --out WORKDIR/explorer.html [--standalone]
```

It is one self-contained page with tabs (Events and alerts, EDR cases, Updates, Backup, Agents), date presets and pickers, KPI
cards with the change against the preceding period, a daily chart (hover a day, drag to select a range), facet panels and
sortable tables recomputed in the browser for the selected range, a filter box, and a day-by-day table. Days with no archived
result show as gaps, never zero. The Agents tab is the single inventory snapshot and does not follow the date range. The output
is a fragment (title, style, markup, script) for publishing with the Artifact tool, like the Entra explorer; add `--standalone`
to get a full HTML document that opens directly in a browser. It holds host names and Acronis unit names (no e-mail addresses),
so treat it as personal data. Publish it with the Artifact tool when the user wants a link to reopen or share; the PDF stays the
fixed, mail-ready copy.

## Step 4 - Render and QA

```bash
node <fluency-report>/scripts/render_pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Acme Ltd Acronis data review"
```

It needs Playwright and a Chrome or Chromium binary. If `pdftoppm` exists, look at every page (no clipped text, tables inside
the page); otherwise say you could not look at the pages.

## Merge rules (what the script does)

- One completed run per UTC day; if a day was archived twice, the latest `completedOn` wins.
- **Counters are summed:** `acr_trend`, `acr_activities` (runs, ok, notOk), `acr_backup` (runs, ok, failed, GB).
- **Keyed tables are merged by the vendor's own id** and take state from the latest day: `acr_alerts` by alert id,
  `acr_incidents` by incident short id and host, `acr_edr_triggers` by incident and device, `acr_update_failures` by agent,
  unit and activity type. So an alert seen on three days is ONE alert; distinct alerts, devices and agents are counted over
  the merged table and never summed across days.
- **Snapshot tables are read from one day, never added:** `acr_agent_summary`, `acr_defs_age`, `acr_versions`, `acr_units`,
  `acr_stale_agents`, `acr_duplicates`, `acr_no_active_protection`, `acr_tenants`.
- A day with no completed run is a gap, listed with its state, never zero.

### Snapshot tables

The inventory has no history, so an archived day's snapshot is the inventory at the moment that day was run. The script uses
the latest day written by the schedule (created within 8 hours of the day's end; the schedule runs at 04:00 UTC). If every
day in the period was backfilled, it uses the latest day and says in the Method section that the snapshot is the inventory as
of the backfill, not as of that day. Tell the user the same in your answer. For true history of agent hygiene, the schedule
must have been running through the period.

## Reading the result

- Lead with the period, the days archived out of the days expected, and the totals.
- Open EDR cases first: they are cases still `NOT_MITIGATED` at their latest state. Say that the feed has file names only (no
  hash, signer or parent process), so a "likely false positive" reading is a hypothesis; send the user to the Acronis console to
  confirm. Cases merged into another incident appear only in the trigger rows.
- Then online agents that are not updating or have no Active Protection; then stale and duplicate records, installer lag and
  failed definition updates; then backup, then alert quality.
- Quote alert counts as distinct alert ids, and say how many events they came from (re-sends).
- **A gap is not zero.** Say which days are missing and whether a backfill is possible.
- Repeat the limits the report prints: no Defender or Entra coverage cross-check, and no server backup visible in the feed.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` (report) or in the browser from the embedded archive rows (explorer). Never type a number into the HTML.
- Never sum distinct counts across days and never average percentages.
- Host names and Acronis unit names (an administrator's name and e-mail) are in the archive; the report strips the e-mail from
  unit names. Do not add users, full file paths or e-mail addresses.
- Run totals for activities are slightly overstated at each day boundary (an activity re-sent the next day counts on both days).
  The report says so.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF first. Do not post
automatically.

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own copy:
`build_report.py` finds the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and imports `fluency_brand`
from it, and stops with a clear message if it is not installed. In the steps above, `<fluency-report>` means that skill's folder.

- The HTML report is one self-contained file. The PDF is rendered from that same HTML with the same CSS, US Letter. The explorer is a separate page with its own layout and does not use the brand kit.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore the brand CSS.
- Do not hand-write report styling. A new page is `fluency_brand.page(...)`; design and component reference: the
  `fluency-report` skill (`references/widget_recipes.md`).
