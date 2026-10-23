---
name: compliance-assessment
version: 1.0.0
description: >-
  Produce a customer-facing compliance evidence report for ONE Ingext/Fluency tenant and ONE
  calendar month, built from read-only queries through the tenant's MCP connector (KQL over
  Office365, Entra sign-in and audit, Windows audit; behavior summaries; Office 365 and Qualys
  resource dumps; connector and report inventory). Maps the evidence onto 13 NIST SP
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

This skill works directly on the tenant's MCP connector (for example the **Develop** connector).
It does not need the Fluency MSSP compliance engine. If a connector also serves
`assess_compliance_posture` or `export_compliance_assessment_package`, those produce the full
40-control package and companion views (CSF, 800-171, CMMC, ISO 27001, FICA); this skill is the
reduced, evidence-led view, and the report says so. Check the engine's output before trusting it:
if `assessment_type` is `static_registry_projection` or the evidence window is empty, it is a
skeleton, not an assessment.

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
(Office365, AzureSigninLogs, AzureAuditLogs, WindowsAudit) are queried with `kql_search`.
Resource tables (office365User and the rest) are inventory snapshots and are downloaded as
dumps, not queried.

| Evidence file | Table that must be listed |
|---|---|
| `o365_workloads.json` | `Office365` (event) |
| `signin.json` | `AzureSigninLogs` (event) |
| `audit_categories.json` | `AzureAuditLogs` (event) |
| `windows.json` | `WindowsAudit` (event) |
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
| `behavior.json` | `behavior_summary_search`, same window, `limit: 0`, facets `status`, `classification`, `scoreLevel` |
| `users.jsonl.gz`, `devices.jsonl.gz`, `ca_policies.jsonl.gz`, `qualys.jsonl.gz` | `list_resource_dumps`, then `get_resource_dump_url` per resource (see below). Current snapshot, no time window |
| `connectors.json`, `reports.json` | `list_connectors`, `list_reports` |

**Resource dumps.** Call `list_resource_dumps` for the tenant to get each resource's customer
name and record count. If a resource is not listed, treat it as absent. Call
`get_resource_dump_url` with `resource`, `customer` and the default `jsonl` format, then download
the URL straight to disk with `curl -o WORKDIR/<file>` (the link expires in 15 minutes; never
read it into the conversation). `build_report.py` counts the records locally. Check the record
count in the file against the `count` that `list_resource_dumps` reported; a mismatch means a
truncated download.

Large results are saved to a file by the harness; copy that file to the name above rather than
retyping it. Do not substitute a different table for one that is absent.

## Step 3 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --tenant acme --tenant-name "Example Corp" \
  --site Develop --period 2026-09 --out WORKDIR/report.html
```

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
