---
name: aws-cloudtrail-activity-report
version: 1.0.0
description: >-
  Produce an AWS CloudTrail Activity report for ONE Ingext/Fluency tenant and a period (a calendar
  month by default) as HTML, PDF and CSV, built ONLY from the archive of the scheduled report
  CloudTrail_Activity_Report. It never runs kql_search, run_report or any other live search: it lists the
  archive, downloads the archived daily results, merges them and lays out events, errors, access denied,
  console logins and MFA, IAM changes, root-identity events, CloudTrail changes, and breakdowns by
  service, region, identity type and error code, with the archive coverage and any gap days. USE THIS
  SKILL for "CloudTrail activity report", "AWS activity for last month", "AWS audit activity summary",
  "root and IAM activity report". DO NOT use it to search CloudTrail events, to investigate an incident or
  user, or for a tenant that has no archive (set up the scheduled report first).
---

# AWS CloudTrail Activity Report

Answers: how much AWS activity did this tenant record, how many errors and refused calls, who signs in
without MFA, how often did IAM, the root identity or CloudTrail itself change, and which services and
regions are busiest? It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`,
`behavior_*`, `lake_search` or anything else that queries the tenant's data. Every figure comes from
`download_report_archive`. If the archive is missing days, say so and offer `backfill_report_archive`;
never fill a gap by searching.

The archive is written by the scheduled report `CloudTrail_Activity_Report` (an FPL report that runs once a
day for exactly one UTC day, with the archive enabled). If `list_scheduled_report` shows no such report on the
tenant, stop and tell the user to deploy it first (its script is `references/CloudTrail_Activity_Report.js`; see
`references/archive_format.md`, section "Producing the archive").

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (the last full month if none is named). A custom range is fine, at most 92 days per download; for a quarter, download month by month and pass every file to the script. |
| Report name | `CloudTrail_Activity_Report` unless the user's tenant uses another name. |

## Step 1 — Check coverage

`list_report_archive(account, name)` shows what is archived: first and last day, completed, aborted, and
`missingDays`. Compare it with the period. Tell the user the number of missing days before building.

If days inside the period are missing and the user wants them, `backfill_report_archive(account, name, from, to)`
(one backfill at a time per account, up to 92 days, about 1.5 minutes a day, so state the wait), then check back
with `list_report_archive`. A backfill runs the report on the tenant, but it is the archive's own job and not a
search made for this report. Backfilled days can only be as deep as the tenant's data retention: early days may
legitimately read as zero.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. A month is about 2 MB, so the harness saves it to a file.
Use that file as is. Do not print it and do not hand-copy numbers out of it. If the result arrives inline, write
it to a scratch file outside the repository.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant acme --site Develop \
  --out WORKDIR/report.html --csv WORKDIR/cloudtrail.csv --summary-json WORKDIR/cloudtrail_summary.json
```

Pass the whole requested period in `--from/--to`, including days that have not happened yet or are not
archived: the script then lists them as gaps instead of silently shrinking the period. The script sums the per-day
trend rows, sums every breakdown table by value, treats a missing value as 0, keeps the latest run when a day was
archived twice, and reports script-hash changes.

## Step 4 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp AWS CloudTrail Activity Report"
```

It needs Playwright and a Chrome or Chromium binary (override with `--chrome` or `CHROME_PATH`). If `pdftoppm`
exists, look at every page (footer on every page, no clipped text, tables inside the page); otherwise check in
print media that each table has `scrollWidth <= clientWidth`. If you cannot look at the pages, say so.

## Reading the result

- Lead with the period, the days archived out of the days expected, and the totals.
- Name the security-relevant counts plainly: root-identity events, CloudTrail changes, failed logins and
  logins without MFA. A non-zero root count is a finding to hand to the customer, not a verdict: the report
  shows event names, never who or from where. Say what to look at next (the incident or user investigation
  skills), without searching here.
- Errors are normal in volume. Quote the share of events and the top error code before calling a number high.
- **A gap is not zero.** Say which days are missing and whether a backfill is possible.
- Repeat the limits the report prints, especially that counts relate to 800-53 controls and are not a
  compliance determination.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Daily results are merged additively. Never average percentages and never sum distinct counts.
- Facet tables hold at most 100 values a day. The `(other)` row is the day's events minus the listed
  values, so shares still add up.
- Counts only: no user names, addresses, ARNs or CVE ids appear in the archive or in this report. Do not add
  them.
- Never write "compliant", "certified" or "attested". Rows are related to controls, not equivalent.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF
first. Do not post automatically.
