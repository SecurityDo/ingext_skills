---
name: CISO_monthly_report
version: 1.0.0
description: >-
  Generate the customer-facing CISO Monthly SOC (M-SOC) report for ONE Fluency MSSP tenant and
  one calendar month as a single HTML document: an 8-chapter story (executive summary with a
  Green/Amber/Red rating, what happened, patterns, what we can and cannot see, what is at risk,
  how defences performed with a NIST 800-53 compliance add-on, what happens next, what improved)
  and 16 sections. USE THIS SKILL for "M-SOC report", "monthly SOC report", "CISO report",
  "board security report", "monthly security summary", "the SOC story for the month", or an
  executive report covering a month for a Fluency customer. Reads the tenant through the MSOC
  (fluency-mssp) connector, computes every figure locally from the saved tool results and
  marks anything the tools cannot supply as GAP or PARTIAL. Read-only. DO NOT use it for a
  single incident (incident-investigation), the NIST evidence report alone (compliance-assessment)
  or invoices (billing-csv).
---

# M-SOC Monthly Report

A CISO-grade monthly report that tells the customer's SOC story, readable by someone who was not
in the SOC that month. It is read-only: use only tools that change nothing, and never post or send the
result without the operator's approval of the HTML.

The analyst writes the **narrative**. `scripts/build_report.py` computes every number, table, chart
and score from the saved raw tool results, applies the layout and enforces the chapter contract.

## Scope and window

1. One tenant (`grid_account`), never an MSSP-wide pull. Resolve it with `list_tenants`; stop if the
   name is ambiguous.
2. One calendar month, default the last full month. Use epoch milliseconds for `range_from` (first
   instant of the month, UTC) and `range_to` (first instant of the next month). Pull the prior month
   with the same pattern for the month-over-month columns.
3. Confirm tenant and month with the user before pulling.

## Step 1 — Collect

Save each tool result under the name shown, in a work folder outside the repository (the
results name real users, hosts and applications). A result the harness saves to a file can be
copied as it is. A result that arrives inline (the compliance one is about 130,000 characters) can
be saved trimmed to the fields the script reads, which `references/evidence.md` lists; do not
alter a value. Keep `capped` and `reported_total` in the metrics files and `reported_total` in
`cases.json`: the script warns if a call covered fewer cases than the tenant has.

| File | Tool and arguments |
|---|---|
| `metrics.json`, `metrics_prev.json` | `summarize_case_metrics(grid_account, range_from, range_to)` for the month and the prior month |
| `fingerprints.json` | `summarize_case_fingerprints(grid_account, range_from, range_to, min_cases=1)` |
| `repeat.json`, `repeat_prev.json` | `categorize_repeat_actors(grid_account, range_from, range_to)` for the month and the prior month |
| `cases.json` | `list_cases(grid_account, range_from, range_to, status=["*"], limit=100, include_fingerprint=true)`; page with `offset` if `reported_total` exceeds 100 and merge the `cases` arrays |
| `cases_prev.json` | optional: the same for the prior month; without it the rolling-trend deltas show as GAP |
| `sources.json` | `evaluate_data_sources(grid_account)` |
| `compliance.json` | `assess_compliance_posture(grid_account, evidence_window={"from":…,"to":…})`; slow (about a minute). Skip if it fails: the section says no evidence was collected |

Before classifying cases fetch `get_instruction_group("behavior-summaries")` and
`get_instruction_group("health")` and follow them over this skill if they differ.
Use `case_count_in_window_live` for fingerprint percentages, never a historical count.

ATT&CK: the fingerprints result already carries each fingerprint's approved techniques. The appendix
lists them as supporting material, and shows no technique table when no case is mapped. Chapter 5
stays narrative, not a technique heat map.

## Step 2 — Write the narrative

Write `narrative.json` (field list in `references/narrative.md`). Rules:

- Refer to computed values with placeholders: `{{cases}}`, `{{unacked}}`, `{{mttr_p50}}`,
  `{{mttr_p50_prev}}`, `{{mttr_p90_h}}` and the rest listed in the reference. The script prints a
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

**The compliance counts.** `assess_compliance_posture` projects mapped evidence onto the controls, and
two different tenants tested returned the same counts (14 supported, 22 partial, 4 not observed,
the same four controls). Present the posture as what this month's collection supports, not as a
tenant-specific finding, and say so if a tenant's counts match another's.

**Not exposed to reporting tools, so shown as GAP, never filled in:** the SOC escalation log, the SOC
change log, control effectiveness and the processed-versus-escalated alert denominator. Privileged
administrators belong in Admin Watch, never called offenders. `True Positive = 0` is ambiguous when
classification discipline is weak; say so. Compliance wording: the evidence "supports" a control,
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
