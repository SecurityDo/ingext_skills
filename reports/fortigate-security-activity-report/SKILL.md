---
name: fortigate-security-activity-report
version: 1.0.0
description: >-
  Produce a FortiGate Security Activity report for ONE Ingext/Fluency tenant and a period (a calendar month by
  default) as HTML, PDF and CSV, built ONLY from the archive of the scheduled report
  Fortigate_Security_Activity_Report. It never runs kql_search, run_report or any other live search: it lists the
  archive, downloads the archived daily results, merges them and lays out failed SSL-VPN logins (by device,
  country, source address and user), SSL-VPN sessions, IPsec tunnels, application-control and web-filter blocks,
  IPS/DoS anomalies and administrator logins and configuration changes, with the archive coverage, gap days and
  scans the tenant could not run. USE THIS SKILL for "FortiGate activity report", "VPN failed logins last month",
  "firewall security summary", "FortiGate admin changes report". DO NOT use it to search firewall events, for
  bandwidth or top talkers (fortigate-bandwidth), to investigate an incident, or for a tenant that has no archive
  (set up the scheduled report first).
---

# FortiGate Security Activity Report

Answers: how many SSL-VPN logins failed and from where, is anyone spraying or brute-forcing the VPN, how many
tunnels were established, what did application control and the web filter block, were there IPS or DoS anomalies,
and who logged in to or changed the firewall's configuration? It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `behavior_*`,
`lake_search` or anything else that queries the tenant's data. Every figure comes from `download_report_archive`.
If the archive is missing days, say so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `Fortigate_Security_Activity_Report` (an FPL report that runs once a
day for exactly one UTC day, with the archive enabled). If `list_scheduled_report` shows no such report on the
tenant, stop and tell the user to deploy it first (its script is `references/Fortigate_Security_Activity_Report.js`;
see `references/archive_format.md`, section "Producing the archive").

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Conekt). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (the last full month if none is named). At most 92 days per download; for a quarter, download month by month and pass every file to the script. |
| Report name | `Fortigate_Security_Activity_Report` unless the user's tenant uses another name. |
| Actors | The report names users and source IPs. Build with `--no-actors` when it will leave the tenant's owner. |

## Step 1 — Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays` and the
script hashes. Compare with the period and tell the user the number of missing days before building.

If days inside the period are missing and the user wants them, `backfill_report_archive(account, name, from, to)`
(one backfill at a time per account, up to 92 days, before today; a day takes seconds on a small firewall and
minutes on a large one, so state the wait), then check `list_report_archive`. A backfill is the archive's own job,
not a search made for this report. Early days can only be as deep as the tenant's retention.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. A month is several MB (a busy firewall can reach 4 MB), so the
harness saves it to a file. Use that file as is; do not print it and do not hand-copy numbers out of it. If a
download is too large, download 10 to 15 days at a time and pass every file to the script.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant "Acme" --site Conekt \
  --out WORKDIR/report.html --csv WORKDIR/fortigate.csv --summary-json WORKDIR/fortigate_summary.json [--no-actors]
```

Pass the whole requested period in `--from/--to`, including days not yet archived: they are listed as gaps instead of
silently shrinking the period. The script sums the per-day trend rows, sums every per-entity table by key, keeps
the latest run when a day was archived twice, and reports script-hash changes.

**Scans the tenant could not run.** The processor catches a missing table or failed query and records it in the
archived `sources` table as "not available" with the error text. The report shows each scan as available, partial
or not available. If every scan is not available the tenant has no FortiGate events: the report says so and the
zeros are not findings of "no activity". Tell the user, because that is a finding about the tenant's data.

## Step 4 — Render and QA

```bash
node <fluency-report>/scripts/render_pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Acme FortiGate Security Activity Report"
```

It needs Playwright and a Chrome or Chromium binary (override with `--chrome` or `CHROME_PATH`). If `pdftoppm`
exists, look at every page (footer on each page, no clipped text, tables inside the page); otherwise check in print
media that each table has `scrollWidth <= clientWidth`. If you cannot look at the pages, say so.

## Reading the result

- Lead with the period, days archived out of days expected, and the totals: failed VPN logins, SSL sessions,
  blocks, anomalies, admin changes.
- Failed logins: quote the countries and the top sources. The pattern column is a rule of thumb (10 or more user
  names from one address in a day is a spray; 50 or more failures is brute force; the rest is a probe). Say that it
  is a lead for the customer, not a verdict, and point to incident or user investigation for the next step.
- Most failed logins arrive with no user name (FortiOS leaves it empty). Say so before reading anything into the
  user list.
- Web-filter blocks are usually the largest count by far and mostly reflect browsing policy, not attacks. Put them
  beside the app-control blocks, not beside the anomalies.
- Admin changes and failed admin logins are the items to hand to the customer: who, how many, and when last.
- **A gap is not zero.** Name the missing days and whether a backfill is possible.
- Repeat the limits the report prints, especially that counts relate to 800-53 controls and are not a compliance
  determination.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Counts add across days. Distinct counts (sources, user names, countries, devices, hosts) are shown as the peak
  single day and must never be added or averaged. Never present a top-100 list as complete.
- The user, source-IP and administrator tables are personal data. Say so when delivering and share them only with
  the customer who owns the data, or build with `--no-actors`.
- Only event and UTM logs are scanned. This report has no bandwidth, top talkers or policy hits; for those use the
  fortigate-bandwidth skill's rules in a separate report.
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
