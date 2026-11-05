---
name: windows-server-activity-report
version: 1.0.1
description: >-
  Produce a Windows Server Activity report for ONE Ingext/Fluency tenant and a period (a calendar month by
  default) as HTML, PDF and CSV, built ONLY from the archive of the scheduled report WindowsSrv_Activity_Report.
  It never runs kql_search, run_report or any other live search: it lists the archive, downloads the archived daily
  results, merges them and lays out event ingestion by host and event ID, user logons and failures, failed-logon
  sources, privileged logons, account and group changes, services and scheduled tasks installed, audit-log clears and
  policy changes, with the archive coverage, gap days and scans the tenant could not run. USE THIS SKILL for "Windows
  server activity report", "domain controller activity last month", "failed Windows logons report", "Windows event
  ingestion report". DO NOT use it to search Windows events, to investigate an incident or a user, or for a tenant
  that has no archive (set up the scheduled report first).
---

# Windows Server Activity Report

Answers: how many Windows events came in from which hosts and event IDs, who logged on and how, how many logons
failed and from where, is anyone spraying or brute-forcing accounts, who used privileged logons, what accounts and
groups changed, which services and scheduled tasks were installed, and were audit logs cleared or the audit policy
changed? It covers everything the older WindowsSrv_Ingress_Search_Report returns (events, hosts, events by host and by
event ID with names) and adds the security tables. It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `behavior_*`,
`lake_search` or anything else that queries the tenant's data. Every figure comes from `download_report_archive`.
If the archive is missing days, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `WindowsSrv_Activity_Report` (an FPL report that runs once a day for
exactly one UTC day, with the archive enabled; it reads the `WindowsAudit` table). If `list_scheduled_report` shows no
such report on the tenant, stop and tell the user to deploy it first (source in the Scripts repo,
`fplProcessors/code/WindowsSrv_Activity_Report.js`, also `references/WindowsSrv_Activity_Report.js`; see
`references/archive_format.md`, section "Producing the archive").

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (the last full month if none is named). At most 92 days per download; for a quarter, download month by month and pass every file to the script. |
| Report name | `WindowsSrv_Activity_Report` unless the user's tenant uses another name. |
| Actors | The report names user accounts and source IPs. Build with `--no-actors` when it will leave the tenant's owner. |

## Step 1 — Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and the
script hashes. Compare with the period and tell the user the number of missing days before building.

If days inside the period are missing and the user wants them, `backfill_report_archive(account, name, from, to)`
(one backfill at a time per account, up to 92 days, before today; a day takes several minutes on a busy domain
controller, so state the wait), then check `list_report_archive`. A backfill is the archive's own job, not a search
made for this report. Early days can only be as deep as the tenant's retention.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. A month is several MB, so the harness saves it to a file. Use that
file as is; do not print it and do not hand-copy numbers out of it. If a download is too large, download 10 to 15
days at a time and pass every file to the script.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant "Acme" --site Develop \
  --out WORKDIR/report.html --csv WORKDIR/windows.csv --summary-json WORKDIR/windows_summary.json [--no-actors]
```

Pass the whole requested period in `--from/--to`, including days not yet archived: they are listed as gaps instead of
silently shrinking the period. The script sums the per-day trend rows, sums every facet and list by value, keeps the
latest run when a day was archived twice, and reports script-hash changes.

Add `--interactive WORKDIR/report_interactive.html` to also write one self-contained interactive page (tabs, search, sort, filter, CSV export of the filtered view, dark mode, hover trend charts) from the same merged data; `--no-actors` omits user names and IPs from it too.

**Scans the tenant could not run.** The processor catches a missing table or failed query and records it in the
archived `sources` table as "not available" with the error text. The report shows each scan as available, partial
or not available. If every scan is not available the tenant has no Windows events: the report says so and the zeros
are not findings of "no activity". Tell the user, because that is a finding about the tenant's data.

## Step 4 — Render and QA

```bash
node <fluency-report>/scripts/render_pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Acme Windows Server Activity Report"
```

It needs Playwright and a Chrome or Chromium binary (override with `--chrome` or `CHROME_PATH`). If `pdftoppm`
exists, look at every page (footer on each page, no clipped text, tables inside the page); otherwise check in print
media that each table has `scrollWidth <= clientWidth`. If you cannot look at the pages, say so.

## Reading the result

- Lead with the period, days archived out of days expected, and the totals: events, hosts, user logons, failed
  logons, privileged logons, account and group changes, services and tasks added, log clears.
- Failed logons: quote the reasons and the top sources. The pattern column is a rule of thumb (10 or more user names
  from one address in a day is a spray; 50 or more failures is brute force; the rest is a probe). Say that it is a
  lead for the customer, not a verdict, and point to incident or user investigation for the next step. An internal
  address with one account and many failures is usually a stale password on a service or a mapped drive.
- Audit-log clears (1102, 104) and audit-policy changes (4719) are the items to hand to the customer first: which host,
  which account, how many.
- Account created or deleted, group adds and new services or tasks need an owner's explanation, not a conclusion.
- Event names come from the AD_EventID lookup, which names security IDs only; IDs such as 7036, 800, 4103, 4104 or 600
  use the description carried on the event, and some have none. Say how many IDs have no name (the summary JSON holds it).
- **A gap is not zero.** Name the missing days and whether a backfill is possible.
- Repeat the limits the report prints, especially that counts relate to 800-53 controls and are not a compliance
  determination.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Counts add across days. Distinct counts (hosts, user names per source) are shown as the peak single day and must
  never be added or averaged. Never present a top-100 list or the top-300 host and event ID pairs as complete: the
  report prints how many events fall outside them.
- The user, source-IP and actor lists are personal data. Say so when delivering and share them only with the customer
  who owns the data, or build with `--no-actors`.
- Only the `WindowsAudit` table is read. Older nxlogAD events held in the default table are not part of this report;
  on a tenant that still has both, the counts matched on the one tenant checked (navasotavalley, 29 Oct 2026), apart
  from 48 events with no event ID that only `WindowsAudit` holds.
- Never write "compliant", "certified" or "attested". Rows are related to controls, not equivalent.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF first.
Do not post automatically.

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
