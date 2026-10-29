---
name: ciso-monthly-report
version: 1.0.1
metadata:
  aliases: "CISO_monthly_report"
description: >-
  Generate the customer-facing CISO Monthly SOC (M-SOC) report for ONE Fluency / Ingext tenant and
  one calendar month as a single HTML document: an 8-chapter story (executive summary with a
  Green/Amber/Red rating, what happened, patterns, coverage, risk, defences with a NIST 800-53
  add-on, next steps, improvements) and 16 sections. USE THIS SKILL for "M-SOC report", "monthly SOC
  report", "CISO report", "board security report", "monthly security summary", or an executive
  report covering a month for a customer. Reads the tenant's behavior summaries (cases) through its
  MCP connector, plus health-status-report and compliance-assessment results; computes every figure
  locally and marks what the tools cannot supply as GAP or PARTIAL. Read-only. PREREQUISITES: install
  the health-status-report and compliance-assessment skills first. DO NOT use it for one incident
  (incident-investigation) or invoices (billing-csv).
---

# M-SOC Monthly Report

Formerly `CISO_monthly_report`. Requests using that legacy name refer to this skill.

> **Prerequisites: install the `health-status-report` and `compliance-assessment` skills before using this
> one.** The coverage and health section reads the `health.json` that `health-status-report` writes, and
> the compliance section reads the `compliance_summary.json` that `compliance-assessment` writes. Without
> them those sections show a GAP instead of a result.

A CISO-grade monthly report that tells the customer's SOC story, readable by someone who was not
in the SOC that month. It is read-only: use only tools that change nothing, and never post or send the
result without the operator's approval of the HTML.

The analyst writes the **narrative**. `scripts/build_report.py` computes every number, table, chart
and score from the saved raw tool results, applies the layout and enforces the chapter contract.

## Scope and window

1. One tenant (account). Call `list_accounts` and match the user's name; stop if it is ambiguous.
2. One calendar month, default the last full month. Use epoch milliseconds for `rangeFrom` (first
   instant of the month, UTC) and `rangeTo` (first instant of the next month). Pull the prior month the
   same way for the month-over-month columns.
3. Confirm tenant and month with the user before pulling.

## Step 1 — Collect

Save each result under the name shown, in a work folder outside the repository (the results name
real users, hosts and applications). A result the harness saves to a file can be copied as it is.

| File | Tool and arguments |
|---|---|
| `cases.json` | `behavior_summary_search(account, rangeFrom, rangeTo, searchStr="riskScore:[3000 TO *]", limit=100, sortField="to")`. A case is a behavior summary at or above the canonical review score of 3000. If `total` exceeds 100 page with `offset` and merge the results into one JSON array |
| `cases_prev.json` | optional: the same for the prior month; without it the deltas show as GAP |
| `events.json`, `events_prev.json` | optional: `prom_query(account, query="sum by (index) (increase(lake_ingress_count[<days>d]))", time="<first instant of the next month, RFC3339>")`, where `<days>` is the number of days in the month. The prior month uses the same call at the first instant of the report month; the metrics store may not reach back that far, and an empty result shows as a GAP |
| `health.json` | optional: run the **health-status-report** skill for the tenant as far as its evaluation step (Step 2; skip the HTML and PDF). It uses the full mode where the connector has `list_connector_config`, else its state-only fallback, plus `list_resource_dumps`, and owns the collection, the credential removal and the Fluency 9 status logic |
| `admins.json` | optional: only needed for a repeat user that is not in the user dump (the dump in `compliance_summary.json` already lists every directory account and its roles). Use `get_azure_user_record(account, username)` and record `{"checked": [upn, …], "admins": {upn: [role names]}}` |
| `compliance_summary.json` | optional: run the **compliance-assessment** skill for the same tenant and month with `--summary-json`. Besides the control statuses it carries the facts that skill already collected (event volumes, sign-in failures, directory users, MFA registration, administrators, devices, Conditional Access policies, CloudTrail counts, Qualys hosts, audit categories), which fill the O365 hygiene, environment changes and vulnerability rows and tell which repeat actors are administrators, so this report does not repeat those queries |

**The events-to-escalation funnel (section 2).** A ticket is a behavior summary scored 3,000 or more;
smaller ones are not counted anywhere in the report. The report shows, from the case file: tickets flagged,
tickets the AI assistant ran on (it left a comment), tickets closed, **escalated** tickets (still `new` after
the AI ran, so they need an analyst), and tickets the AI has not run on yet. The events at the top come from
`events.json`, the datalake ingest counter by index, with the `behavior` index left out because it holds the
engine's own output, not ingested events. The other indexes are summed as the metric returns them. An event
written to more than one index appears in each, and the counter differs from a KQL count, so describe it as
events written to the datalake, not as unique events.
`behavior_event_search` is not
used: tickets already group the events.

**What the behavior summary gives.** Each case carries `status`, `classification`, `behaviorRules`,
`riskScore`, `incidentDetectionTime`, `updatedOn` and its `comments` (`createdOn`, `username`, `actions`). The script
computes everything from those:

- **Case shape:** the combination of rules that fired, shown with an 8-character id. There is no
  connector fingerprint tool, so this is computed locally and does not match any fingerprint hash
  shown elsewhere.
- **Repeat actors:** an identifier with two or more cases. Admin status comes from `admins.json`; an
  account not looked up shows as "admin status not checked".
- **Time to first response:** from the case's `incidentDetectionTime` to its first comment. A case
  without that field is left out of the times (there is no fallback: the summary's own `from` is only a
  two-minute bucket label of the first event), and the report says how many cases carry it. A prior
  month with fewer than three usable cases is not compared. **Comments are written by the automated
  assistant (`AI-Assistant`) unless a person commented**, so the report separates the first response
  of the assistant or an analyst from the first analyst response, and counts the closed cases that the
  assistant closed. A report with no analyst comment on any case says exactly that.
- **Time to close:** from `incidentDetectionTime` to the later of `updatedOn` and the last comment,
  closed cases only.
- **ATT&CK:** no approved mapping source exists through the connector, so the appendix says so and no
  technique table is shown.

## Step 2 — Write the narrative

Write `narrative.json` (field list in `references/narrative.md`). Rules:

- Refer to computed values with placeholders: `{{cases}}`, `{{unacked}}`, `{{mttr_p50}}`,
  `{{mttr_p50_prev}}`, `{{human_n}}`, `{{closed_by_ai}}` and the rest listed in the reference. The script prints a
  warning for every other number in the prose, so every typed figure gets checked against the
  evidence. Fix the narrative or the evidence; do not ignore the warning.
- Chapter 1 has no raw metrics, alert counts, fingerprints or jargon. Conclusion first, two
  leadership decisions at most, one caveat if the data cannot support a conclusion.
- Chapters 2 to 7 each need **all four**: analysis (at least 150 words naming real users, hosts,
  sources, rules; bold the key figures), 1 to 3 callouts phrased as findings, one graphic, one table.
  The script supplies the graphic and the data tables; you supply the analysis and callouts.
- Findings must be about this tenant's evidence. Never invent escalations, improvements,
  containment actions or contacts. Prior-month claims need the prior-month pull.
- Tone: business language in chapter 1, IT/SOC evidence-first in chapters 2 to 7, closure language in 8.
  Prefer "what this means" over "what the chart says". No alarmism; be direct about blind spots.

**RAG rubric.** Red: any computed or analyst-scored risk is Critical, or visibility gaps materially
prevent detection of a plausible breach path. Amber: any High risk, weak classification discipline,
stale critical log sources, or repeated unresolved exposure. Green: no High or Critical risks and
coverage is materially healthy. Trend: improving, stable or declining against the prior month.

**Risk register.** Score = likelihood (1 to 5) × impact (1 to 5); bands 1–5 Low, 6–10 Medium, 11–17
High, 18–25 Critical. Seven categories: Identity & Access, Endpoint, Perimeter & Exposure, Insider &
Privilege, Patch & Vulnerability, Visibility & Detection, Data & Continuity. The register is analyst
scored from the evidence (the backend has no telemetry-risk computation), so the section carries a
PARTIAL flag. Every risk needs a case, source or count from the evidence behind it.

**Remediation.** 5 to 10 actions with owner, calendar due date (never "next week"), priority, linked
risk and evidence. Client actions are only what the customer must do: confirm activity, patch,
investigate an account, provide a log source, approve monitoring, supply contacts.

**Operational exposure rows.** O365 hygiene, environment changes and vulnerability highlights take their
default text from `compliance_summary.json` `facts`: directory users, MFA registration and administrators,
Conditional Access policies, device sign-in age, audit events by category, CloudTrail counts and the
Qualys host count. They are counts from resource snapshots and event
totals, not findings: say so, and add an `exposure` entry to the narrative only where you have checked
something more (for example an admin lookup). Without the file the three rows show a GAP.

**The compliance section** comes from the compliance-assessment skill's 13 control groups, which map
this tenant's own telemetry onto NIST SP 800-53 Rev. 5. Without `compliance_summary.json` the section
shows a GAP; do not write one from memory.

**Not available through the connector, so shown as GAP, never filled in:** the SOC escalation log, the SOC
change log, control effectiveness and ATT&CK mappings. Privileged
administrators belong in Admin Watch, never called offenders. `True Positive = 0` is ambiguous when
classification discipline is weak, or when the assistant closed every case; say so. Compliance wording: the evidence "supports" a control,
never "compliant"; this is an evidence aid, not an attestation.

## Step 3 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --narrative WORKDIR/narrative.json \
  --tenant acme --tenant-name "Example Corp" --month 2026-09 --out WORKDIR/report.html
```

Fix every `WARNING` before delivering: a short analysis, a missing callout, a placeholder that does
not exist, a number not backed by the evidence, a non-calendar due date.

## Step 4 — Check before delivering

- Chapter 1 has no raw metrics. All 8 chapters and 16 sections are present, empty sections are kept
  and marked.
- Every GAP and PARTIAL is visible and honest; the risk register exists even when PARTIAL.
- Look at the page. If you cannot, say so in the hand-off.
- The output is one self-contained HTML file with no external script, font link or image, so it can
  be posted as it stands. Fonts fall back to system fonts. There is no PDF step.

## Delivering

Posting or sending the report is a separate step that needs the operator's approval of the HTML.
Do not post automatically.
