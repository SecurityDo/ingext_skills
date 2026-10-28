---
name: microsoft365-entra-activity-report
version: 1.0.0
description: >-
  Produce a Microsoft 365 and Entra Activity report for ONE Ingext/Fluency tenant and a period (a calendar
  month by default) as HTML, PDF and CSV, built ONLY from the archive of the scheduled report
  Office365_Entra_Activity_Report. It never runs kql_search, run_report or any other live search: it lists the
  archive, downloads the archived daily results, merges them and lays out Office 365 audit events, Entra user
  sign-ins, directory-audit changes, service-principal and non-interactive sign-ins, with breakdowns, the archive
  coverage, gap days, and any table the tenant does not have. USE THIS SKILL for "Microsoft 365 activity report",
  "Entra sign-in report", "M365 dashboard report", "failed sign-ins and mailbox activity last month". DO NOT use
  it to search events, to investigate a user or incident, or for a tenant that has no archive (set up the
  scheduled report first).
---

# Microsoft 365 and Entra Activity Report

Answers: how much Microsoft 365 and Entra activity did this tenant record, how many sign-ins failed or used a
single factor or legacy authentication, how often did roles, policies, mailbox rules and permissions change, how
many application sign-ins failed on an expired secret, and which applications, countries and operations are
busiest? It is read-only and archive-only.

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`,
`behavior_*`, `lake_search` or anything else that queries the tenant's data. Every figure comes from
`download_report_archive`. If the archive is missing days, say so and offer `backfill_report_archive`;
never fill a gap by searching.

The archive is written by the scheduled report `Office365_Entra_Activity_Report` (an FPL report that runs once a
day for exactly one UTC day, with the archive enabled). If `list_scheduled_report` shows no such report on the
tenant, stop and tell the user to deploy it first (its script is `references/Office365_Entra_Activity_Report.js`; see
`references/archive_format.md`, section "Producing the archive").

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (the last full month if none is named). A custom range is fine, at most 92 days per download; for a quarter, download month by month and pass every file to the script. |
| Report name | `Office365_Entra_Activity_Report` unless the user's tenant uses another name. |

## Step 1 — Check coverage

`list_report_archive(account, name)` shows what is archived: first and last day, completed, aborted, and
`missingDays`. Compare it with the period. Tell the user the number of missing days before building.

If days inside the period are missing and the user wants them, `backfill_report_archive(account, name, from, to)`
(one backfill at a time per account, up to 92 days; large tenants take a few minutes a day, so state the wait),
then check back with `list_report_archive`. A backfill runs the report on the tenant, but it is the archive's own
job and not a search made for this report. Backfilled days can only be as deep as the tenant's data retention:
early days may legitimately read as zero.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. A month is several MB, so the harness saves it to a file.
Use that file as is. Do not print it and do not hand-copy numbers out of it. If the result arrives inline, write
it to a scratch file outside the repository.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant acme --site Develop \
  --out WORKDIR/report.html --csv WORKDIR/m365_entra.csv --summary-json WORKDIR/m365_entra_summary.json
```

Pass the whole requested period in `--from/--to`, including days that have not happened yet or are not
archived: the script then lists them as gaps instead of silently shrinking the period. The script sums the per-day
trend rows, sums every breakdown table by value, treats a missing value as 0, keeps the latest run when a day was
archived twice, and reports script-hash changes.

**Tables the tenant does not have.** The processor catches a missing table and records it in the archived
`sources` table as "not available". The script reads that per day and shows each of the five sources as
available, available with no events, partial, not available on this tenant, or not collected (an older script
version that did not include the source). A section for a source with no data says so; it is never drawn as zero.
Tell the user which sources are not available, because that is a finding about the tenant's data, not an error.

## Step 4 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp Microsoft 365 and Entra Activity Report"
```

It needs Playwright and a Chrome or Chromium binary (override with `--chrome` or `CHROME_PATH`). If `pdftoppm`
exists, look at every page (footer on every page, no clipped text, tables inside the page); otherwise check in
print media that each table has `scrollWidth <= clientWidth`. If you cannot look at the pages, say so.

## Reading the result

- Lead with the period, the days archived out of the days expected, which sources are present, and the totals.
- Name the security-relevant counts plainly: failed sign-ins and their error codes, single-factor successes,
  legacy authentication, Conditional Access failures, risky sign-ins, role and policy changes, mailbox hard
  deletes, inbox-rule and mailbox-permission changes, and service-principal secret errors. These are findings to
  hand to the customer, not verdicts: the report shows counts, never who or from where. Say what to look at
  next (the user or incident investigation skills), without searching here.
- Service-principal sign-ins are usually most of the Entra volume. Quote their share and the share that used a
  client secret before calling a number high. A steady count of expired-secret errors (codes 7000222, 7000215)
  usually means one integration needs a new secret; the archive does not say which person or app owner to contact.
- Office 365 also logs Azure Active Directory logins. Do not add Office 365 login counts to the Entra sign-in counts.
- **A gap is not zero.** Say which days are missing and whether a backfill is possible.
- Repeat the limits the report prints, especially that counts relate to 800-53 controls and are not a
  compliance determination.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Daily results are merged additively. Never average percentages and never sum distinct counts (the report has
  no distinct-user figures for that reason).
- Facet tables hold at most 100 values a day. For lists that cover every event the `(other)` row is the events
  minus the listed values, so shares add up; subset lists (failed, admin, sensitive) drop `(none)`.
- Counts only: no user names, addresses or object names appear in the archive or in this report. Do not add them.
- Never read the raw `AzureAudit` or `MSEntra` tables or add them to the parsed Entra tables; they duplicate them.
- Never write "compliant", "certified" or "attested". Rows are related to controls, not equivalent.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF
first. Do not post automatically.
