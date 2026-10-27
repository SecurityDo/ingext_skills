---
name: compliance-assessment
version: 1.1.0
description: >-
  Produce a customer-facing compliance evidence report for ONE Ingext/Fluency tenant and ONE
  calendar month, built from read-only queries through the tenant's MCP connector (KQL over
  Office365, Entra sign-in and audit, Windows audit, CloudTrail and any network or endpoint
  tables the tenant has; behavior summaries; Office 365 and Qualys resource dumps; connector and
  report inventory). Maps the evidence onto 13 NIST SP
  800-53 Rev. 5 control groups as supported, partial, not observed or needs manual review, and
  renders a self-contained HTML plus a mail-ready PDF. Never claims
  certification or compliance. USE THIS SKILL for "compliance assessment", "NIST 800-53
  posture", "audit-ready evidence report", "control coverage report" for a tenant. DO NOT use it
  for a single incident (incident-investigation) or for a user (office-user-investigation).
---

# Compliance Assessment (evidence report, per tenant per month)

Turn a tenant's own telemetry into an honest, executive-ready compliance evidence report. It
states what the evidence **supports**, what is only **partial**, and what was **not observed**.
It is read-only: it never changes the tenant.

This skill works directly on the tenant's MCP connector (for example the **Develop** connector). The
report is the reduced, evidence-led view: 13 control groups from the tenant's own telemetry, not a
full control package, and the report says so.

## Data integrity (non-negotiable)

Every figure in the report is parsed by `scripts/build_report.py` from the raw tool results you
saved. Never type a number into the HTML. A missing file renders as "not collected" and a status
of not observed; an empty but true report is the correct outcome. Do not put individual users,
case ids or comments in the report, and never copy credentials you see in connector listings.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if it is ambiguous. |
| Period | One `YYYY-MM`. Default to the last full calendar month. Confirm tenant and period before querying. |

Epoch milliseconds for the window: start = first day 00:00 UTC, end = first day of the next
month 00:00 UTC.

## Step 1 — Check which tables exist

Before collecting anything, call `list_data_tables` for the tenant and keep the result. Collect
from a table only if it is listed. Never probe for a table by running its query. Event tables
(Office365, AzureSigninLogs, AzureAuditLogs, WindowsAudit, CloudTrail and the extra sources below) are
queried with `kql_search`.
Resource tables (office365User and the rest) are inventory snapshots and are downloaded as
dumps, not queried.

| Evidence file | Table that must be listed |
|---|---|
| `o365_workloads.json` | `Office365` (event) |
| `signin.json` | `AzureSigninLogs` (event) |
| `audit_categories.json` | `AzureAuditLogs` (event) |
| `windows.json` | `WindowsAudit` (event) |
| `ct_events.json`, `ct_console.json`, `ct_iam.json`, `ct_root.json`, `ct_errors.json` | `CloudTrail` (event) |
| `src_<Table>.json` | any listed stream table whose name matches a class in `references/queries.md` (network, endpoint, cloud or identity) |
| `users.jsonl.gz` | `office365User` (resource) |
| `devices.jsonl.gz` | `office365Device` (resource) |
| `ca_policies.jsonl.gz` | `office365ConditionalAccessPolicy` (resource) |
| `qualys.jsonl.gz` | `qualysHost` (resource) |

A table that is not listed is skipped: no file is saved, the report shows it as not collected,
and the control it feeds is not observed. Say in the hand-off which tables were absent.
`behavior_summary_search`, `list_connectors` and `list_reports` do not depend on this list.

## Step 2 — Collect (save each raw result)

Make a working folder and save each tool's raw JSON result under the file name shown. See
`references/queries.md` for the exact KQL. Run the independent queries in parallel; a query that
fails at the proxy is retried once, then left out (it renders as not collected).

| File | Tool |
|---|---|
| `o365_workloads.json`, `signin.json`, `audit_categories.json`, `windows.json` | `kql_search` with `rangeFrom` and `rangeTo` set to the month |
| `ct_*.json`, `src_<Table>.json` | `kql_search`, same window; one narrow query per file (see the note on large tables in `references/queries.md`) |
| `behavior.json` | `behavior_summary_search`, same window, `limit: 0`, facets `status`, `classification`, `scoreLevel` |
| `users.jsonl.gz`, `devices.jsonl.gz`, `ca_policies.jsonl.gz`, `qualys.jsonl.gz` | `list_resource_dumps`, then `get_resource_dump_url` per resource (see below). Current snapshot, no time window |
| `connectors.json` | `list_connectors`, reduced to `{"entries": [{"application": ..., "state": ...}]}` before saving (see below) |
| `reports.json` | `list_reports` |

**Resource dumps.** Call `list_resource_dumps` for the tenant to get each resource's customer
name and record count. If a resource is not listed, treat it as absent. Call
`get_resource_dump_url` with `resource`, `customer` and the default `jsonl` format, then download
the URL straight to disk with `curl -o WORKDIR/<file>` (the link expires in 15 minutes; never
read it into the conversation). `build_report.py` counts the records locally. Check the record
count in the file against the `count` that `list_resource_dumps` reported; a mismatch means a
truncated download.

**Connector credentials.** `list_connectors` returns credentials in clear text (API keys, HEC and
integration tokens). Never save the raw result to the work folder. Reduce it to the application
and state of each entry (for example with `python3 -c`, reading the harness-saved file) and save
only that, then delete any raw copy. The report needs nothing else from it.

**Extra sources.** A tenant's network, endpoint, cloud and identity tables decide how much of SC-7
(boundary protection), SI-3 (malicious code protection) and AU-2 (logging) can be observed. For every
listed stream table that matches a class in `references/queries.md`, save `src_<TableName>.json` from
`<TableName> | summarize events=count()`. A count only shows that telemetry exists; rules, denied traffic,
agent coverage and detections are not evaluated, and the report says so. A table that matches no class is
not queried.

**Account hygiene.** The `office365User` dump already carries registration and role data (`userRegistration`
with MFA registration and admin flag, `roles`, `userType`, `accountEnabled`) and the device dump carries
last sign-in and compliance flags. The script counts disabled accounts, guests, administrators and
administrators without MFA, enabled users with and without MFA registration, and devices with no sign-in
for 90 days, with no further query. MFA registration is not MFA enforcement, and the report says so.

Large results are saved to a file by the harness; copy that file to the name above rather than
retyping it. Do not substitute a different table for one that is absent.

## Step 3 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --tenant acme --tenant-name "Example Corp" \
  --site Develop --period 2026-09 --out WORKDIR/report.html
```

Add `--summary-json WORKDIR/compliance_summary.json` to also write the control statuses and the facts
behind them (event volumes, sign-in failures, directory users, Conditional Access policies, Qualys hosts,
audit categories) as JSON. The CISO_monthly_report skill reads that file for its compliance section and
for its O365 hygiene, environment changes and vulnerability rows.

## Step 4 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html \
  --output WORKDIR/report.pdf --title "Example Corp Compliance Evidence Report - September 2026"
```

The renderer needs Playwright and a Chrome or Chromium binary. It looks for Chrome in the usual
macOS, Linux and Windows paths (override with `--chrome` or `CHROME_PATH`) and for Playwright in
the current folder, the input's folder and the global npm root. It writes a Letter PDF with the
title in the footer on the left and "X of Y" on the right.

QA before delivering:

1. If `pdftoppm` exists, convert the pages to PNG and look at every page: footer on every page,
   no stranded heading, no clipped or overlapping text, tables inside the page.
2. In print media at the PDF content width, check with Playwright that each table has
   `scrollWidth <= clientWidth` and its right edge inside the document width. If a table
   overflows, tighten column widths or wrapping and rebuild.
3. If you cannot look at the pages (no `pdftoppm`), say that in the hand-off.

## Reading the result

- **Supported:** the evidence directly shows the control operating in the window.
- **Partial:** some evidence exists, but configuration, coverage or review cadence was not shown.
- **Not observed:** evidence was not collected, or the tenant has no data source for it. This is
  not a failed control.
- **Needs manual review:** policy and procedure controls (AC-1, IA-1, IR-1); only customer
  documents can evidence them.

Before handing the report over, read the gaps list with the user and note anything you could
have collected but did not (retention settings, MFA coverage, vulnerability findings).

## Accuracy discipline

- Never write "compliant", "certified" or "attested". Write what the evidence supports.
- Resource-table counts are a snapshot as of the dump (`createdOn` in `list_resource_dumps`; Qualys
  can be older than the others), not the report month; event counts are for the month. Say so.
- A field that reads implausibly (a device compliance flag of 0 across all devices) is likely
  unpopulated: leave it out and say why.
- The control mapping is the analyst's, not the platform's. Keep that sentence in the methodology.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically.
