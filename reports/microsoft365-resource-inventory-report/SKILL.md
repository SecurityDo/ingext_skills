---
name: microsoft365-resource-inventory-report
version: 1.0.0
description: >-
  Produce a Microsoft 365 / Entra Resource Inventory report for ONE Ingext/Fluency tenant as HTML (print-style and interactive), PDF and CSV, built ONLY
  from the archive of the scheduled report Office365_Resource_Inventory_Report. It never runs kql_search, run_report or any
  other live search: it lists the archive, downloads the archived daily snapshots, takes the latest day in the period and
  lays out accounts, administrators and MFA registration (naming the enabled users with no MFA), devices, Conditional
  Access policies by state, app registrations with client-secret hygiene and app-only permissions, enterprise
  applications, groups, and licensed users with users per license. USE THIS SKILL for "Microsoft 365 resource report",
  "who has no MFA", "admins without MFA", "licensed users", "app registration secrets", "Entra directory inventory". DO NOT
  use it to search events, to investigate a user or incident, or for a tenant that has no archive (set up the scheduled
  report first).
---

# Microsoft 365 Resource Inventory Report

Answers: how many users, administrators, guests and devices does the directory hold, which enabled users have no MFA
registered (named, administrators first), how many Conditional Access policies are enforced, which app registrations have
expired or long-lived secrets or request app-only permissions, how many enterprise applications are third party, what do
the groups look like, and who holds which license. Panels match the Microsoft365_Status_Resource_Report (accounts, devices,
accounts without MFA, privileged accounts, licensed accounts, license count) and add the compliance facts. It is read-only
and archive-only. `--interactive` also writes a single self-contained interactive HTML file (tabs, search, sort and filter on the user lists, CSV export of the filtered view, hover trend charts, dark mode).

**The rule that defines this skill: no live searches.** Never call `kql_search`, `run_report`, `lake_search`, resource dump
tools or anything else that queries the tenant. Every figure comes from `download_report_archive`. If days are missing, say
so and offer `backfill_report_archive`; never fill a gap by searching.

The archive is written by the scheduled report `Office365_Resource_Inventory_Report` (an FPL report, one UTC day per run,
archive enabled). If `list_scheduled_report` shows none on the tenant, stop and tell the user to deploy it first (source
`references/Office365_Resource_Inventory_Report.js`; see `references/archive_format.md`, "Producing the archive").

**These are snapshots, not events.** The directory tables have no history. Each archived day is the state when that day's
run took the snapshot. Never add days; the report uses the latest archived day in the period and a change table of the days.
A backfill cannot reconstruct a past state: it records today's directory under the past date, so say that when offering it.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example the tenant's own MCP connector). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Never merge tenants. |
| Period | A calendar month by default (last full month if none is named); for "current state" use the last few days. At most 92 days per download. |
| Report name | `Office365_Resource_Inventory_Report` unless the tenant uses another name. |
| Actors | The report names users (without MFA, licensed). Build with `--no-actors` when it will leave the tenant's owner. |

## Step 1 — Check coverage

`list_report_archive(account, name, from, to)` shows first and last day, completed, aborted, `missingDays`, script hashes.
State the days archived out of the days in the period. Because the report reads the latest day, a missing last day means the
report is older than the period end: say which date it is as of.

## Step 2 — Download

`download_report_archive(account, name, from, to)`. The file holds the user lists (about 1 MB a day for 2,700 users), so for
a month download 10 to 15 days at a time or only the last days, and pass every file to the script. Use the saved file as is;
do not print it or copy numbers by hand.

## Step 3 — Build

```bash
python3 scripts/build_report.py --archive ARCHIVE1.json [ARCHIVE2.json ...] \
  --from 2026-10-01 --to 2026-10-31 --tenant "Acme" --site <site> \
  --out WORKDIR/report.html --interactive WORKDIR/report_interactive.html \
  --csv WORKDIR/users_no_mfa.csv --summary-json WORKDIR/summary.json [--top 50] [--no-actors]
```

`--csv` writes three files: the users without MFA (`users_no_mfa.csv`, every user), the licensed users
(`users_no_mfa_licensed.csv`) and the counts (`users_no_mfa_summary.csv`). `--no-actors` writes only the counts. The HTML
lists the first `--top` users (default 50); the CSV has all of them.

`--out` is the print-style report (for the PDF); `--interactive` is the file to open in a browser: Overview, Users without MFA, Licenses, Applications, Devices and policies, Groups, Trends and Coverage tabs. It needs no server or internet, embeds every user (so it is personal data; with `--no-actors` the lists are left out), and the trend tab appears with two or more archived days. Offer the interactive file for working through the users, and the PDF for a document to send.

**Scans the tenant could not run.** A missing table (for example no Conditional Access table) is recorded in `sources` as
"not available" and shown as such, never as zero. If `registrationKnown` is 0 the MFA figures are "unknown".

## Step 4 — Render and QA

Open the interactive file in a browser (or Playwright) once: every tab should render with no console error, and the user table search, filters and sort should change the row count.

```bash
node <fluency-report>/scripts/render_pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf --title "Acme Microsoft 365 Resource Inventory"
```

Needs Playwright and a Chrome or Chromium binary (`--chrome` or `CHROME_PATH`). If `pdftoppm` exists, look at every page
(footer on each page, no clipped text, tables inside the page); otherwise say you could not look.

## Reading the result

- Lead with the as-of date, days archived of days expected, users, administrators, enabled users without MFA and
  administrators without MFA. Administrators without MFA come first in any recommendation.
- Definitions: an administrator is any user with the isAdmin flag or any directory role; a non-compliant user is an enabled
  user with no MFA registered (guests included, shown by type). MFA registration is not MFA enforcement; say so.
- Conditional Access: enforced versus report-only versus disabled counts; zero enforced is a finding, a missing table is not.
- Secrets: expired and expiring within 90 days need an owner; long-lived (over 730 days) is a hygiene point. App-only
  counts show what is requested, not what was consented to.
- Device managed and compliance figures count only devices that report the field; "not reported" is not "unmanaged".
- The change table compares days; one archived day shows no change at all.

## Accuracy discipline

- Every figure is computed by `scripts/build_report.py` from the archive. Never type a number into the HTML.
- Never sum counts across days. A gap is not an unchanged directory.
- The list size must equal the enabled-no-MFA count; the report flags a mismatch.
- The lists and the archive are personal data: deliver only to the tenant's owner, or build with `--no-actors`.
- Never write "compliant", "certified" or "attested"; the facts are related to controls, not equivalent.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF first.

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
