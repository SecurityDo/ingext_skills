---
name: fortigate-traffic-activity-report
version: 1.0.0
description: >-
  Produce a FortiGate Traffic Activity report for ONE Ingext/Fluency tenant and a period (a calendar month by
  default) as HTML, PDF and CSV, built ONLY from the archive of the scheduled report
  Fortigate_Traffic_Activity_Report. It never runs kql_search, run_report or any other live search: it lists the
  archive, downloads the archived daily results, merges them and lays out firewall traffic volume (events, blocks,
  bytes sent and received), applications and categories, services, destination countries, firewall
  policies, reporting devices, the largest internal senders and a generative-AI summary, with the archive
  coverage, gap days and scans the tenant could not run. It also writes the GenAI evidence (per application,
  source, destination and policy) that the separate GenAI Egress report reads. USE THIS SKILL for "FortiGate
  traffic report", "firewall bandwidth and top talkers last month", "what applications and countries does the
  firewall see", "GenAI traffic through the firewall". DO NOT use it to search firewall logs, for VPN logins,
  administrator changes or IPS events (fortigate-security-activity-report), to investigate an incident, or for a
  tenant that has no archive (set up the scheduled report first).
---

# FortiGate Traffic Activity Report

Answers: how much traffic crosses the firewall and how much of it is blocked, which applications and categories
carry it, where it goes, which policies and which firewalls handle it, who sends the most, and how much of it is
generative-AI traffic. It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `behavior_*`,
`lake_search` or anything else that queries the tenant's data. Every figure comes from `download_report_archive`.
If the archive is missing days, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `Fortigate_Traffic_Activity_Report` (an FPL report that runs once a
day for exactly one UTC day, with the archive enabled). If `list_scheduled_report` shows no such report on the
tenant, stop and tell the user to deploy it first (its script is `references/Fortigate_Traffic_Activity_Report.js`;
see `references/archive_format.md`, section "Producing the archive"). It is the daily run that makes the
archive additive: every table adds across days, so a month or a quarter is a merge of dailies. The run is two scans
of the traffic table (see the format note), so it is much lighter than a scan per table.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example the tenant's own MCP connector). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (the last full month if none is named). At most 92 days per download; for a quarter, download month by month and pass every file to the script. |
| Report name | `Fortigate_Traffic_Activity_Report` unless the user's tenant uses another name. |
| Hosts | The report names internal hosts and IP addresses. Build with `--no-actors` when it will leave the tenant's owner. |

## Step 1 — Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and the
script hashes. Compare with the period and tell the user the number of missing days before building.

If days inside the period are missing and the user wants them, `backfill_report_archive(account, name, from, to)`
(one backfill at a time per account, up to 92 days, before today; a traffic day is the heaviest of the FortiGate
reports and takes minutes on a busy firewall, so state the wait), then check `list_report_archive`. A
backfill is the archive's own job, not a search made for this report. Early days can only be as deep as the
tenant's retention.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. A month is several MB, so the harness saves it to a file. Use
that file as is; do not print it and do not hand-copy numbers out of it. If a download is too large, download 10 to
15 days at a time and pass every file to the script.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant "Acme" --site <site> \
  --out WORKDIR/report.html --interactive WORKDIR/report_interactive.html --csv WORKDIR/traffic.csv --summary-json WORKDIR/traffic_summary.json [--no-actors]
```

`--out` is the print-style HTML that the PDF is rendered from; `--interactive` is a separate self-contained file to open
in a browser (tabs, search, sort, filters, CSV export of the filtered table, a trend explorer with hatched gap days, dark
mode). Give the user the interactive HTML and the PDF; the print HTML is only the PDF's source.

Pass the whole requested period in `--from/--to`, including days not yet archived: they are listed as gaps instead of
silently shrinking the period. The script sums the per-day trend rows, sums every table by key, keeps the latest
run when a day was archived twice, and reports script-hash changes. `--no-actors` drops the internal sender and the
GenAI source and destination tables.

**Scans the tenant could not run.** The processor catches a missing table or failed query and records it in the
archived `sources` table as "not available" with the error text. If every scan is not available the tenant has no
FortiGate traffic logs: the report says so and the zeros are not findings of "no activity". Tell the user.

## Step 4 — Render and QA

```bash
node <fluency-report>/scripts/render_pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Acme FortiGate Traffic Activity Report"
```

It needs Playwright and a Chrome or Chromium binary (override with `--chrome` or `CHROME_PATH`). If `pdftoppm`
exists, look at every page (footer on each page, no clipped text, tables inside the page); otherwise check in print
media that each table has `scrollWidth <= clientWidth`. If you cannot look at the pages, say so.

## Reading the result

- Lead with the period, days archived out of days expected, and the totals: events, share blocked, bytes sent and
  received, GenAI events and bytes.
- Volumes are per-record deltas of the session byte counters, not the raw cumulative counters. If a figure looks
  too large or too small against another source, that is the first thing to check; never add the raw `sentbyte`
  columns back in.
- "Events" are log records, not sessions. A long session writes several records, so do not quote events as a
  session count.
- **Application names are the coverage of the GenAI view.** The report prints the share of events that carry an
  application name. A policy without Application Control writes none, so on a tenant with a low share the GenAI
  figures are a lower bound and "no GenAI traffic" is not a finding. Say so before reading anything into the GenAI
  section.
- Destinations are application, address and country, never a domain: traffic logs carry no host name or URL.
- A service or application the firewall could not name appears as (unnamed tcp port) or (unnamed udp port): the
  processor collapses those (tens of thousands on a busy firewall) to stay inside the engine's 8124-row result limit.
- **A truncated day.** If a day's dimensions result reached the 8000-row guard the report prints a warning: its
  smallest rows were dropped, so read the tables for that day as lower bounds and say so.
- Blocked events are firewall action deny. Policy 0 denies are the implicit deny; a very large count there is
  usually background noise (discovery protocols, scans), not an attack. Say that it is a lead, not a verdict.
- The largest senders are hosts by bytes sent. A backup server or a file server is usually at the top; a user
  workstation near the top is the item to hand to the customer.
- **A gap is not zero.** Name the missing days and whether a backfill is possible.
- Repeat the limits the report prints.

## The GenAI evidence

The summary JSON (`--summary-json`) has a `genai` key (events, blocked events, bytes sent and received, and the
per-application totals) and the full `genai_app`, `genai_source`, `genai_destination` and `genai_policy` tables
(every row the archive holds). The separate GenAI Egress report reads this evidence instead of scanning traffic again; this
skill only summarises it in section 8. Do not draw conclusions about data leaving the company from the byte counts
alone: bytes sent to a GenAI service say how much was sent, not what it was.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Counts and volumes add across days. Distinct hosts and addresses are not reported because they cannot be added
  across days. Never present a top-N list as complete: a range total for a row outside a day's top N is a lower
  bound.
- The sender, GenAI source and GenAI destination tables are personal data. Say so when delivering and share them
  only with the customer who owns the data, or build with `--no-actors`.
- Only forward-traffic logs are scanned. This report has no VPN, administrator, web-filter or IPS counts; those are
  in the fortigate-security-activity-report skill.
- Never write "compliant", "certified" or "attested". These are counts of firewall log records.

## Delivering to the customer

Deliver the interactive HTML, the PDF and the CSV. Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF first.
Do not post automatically.

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own
copy: the build script here finds the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and
imports `fluency_brand` from it, and stops with a clear message if it is not installed. Install `fluency-report` alongside this skill. In the steps above, `<fluency-report>` means
that skill's folder.

- The HTML report is one self-contained file (mark, fonts and CSS inlined). The PDF is rendered from that same HTML with the same
  CSS, so the two match. US Letter, same editorial styling as the HTML. It needs Playwright
  (`npm install playwright`) and a Chromium or Chrome binary; it finds a Chrome install automatically.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore
  the brand CSS (grid, fonts, page rules), so the PDF would not match the HTML.
- Do not hand-write report styling. A new page is `fluency_brand.page(...)`; markup from an older script goes
  through `fluency_brand.apply_brand(html)`. Design and component reference: the `fluency-report` skill (`references/widget_recipes.md`).
