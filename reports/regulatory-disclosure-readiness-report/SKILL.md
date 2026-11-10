---
name: regulatory-disclosure-readiness-report
version: 1.0.0
description: >-
  Test whether ONE Fluency / Ingext tenant could detect, assess and report a significant cyber incident inside the SEC Form 8-K
  Item 1.05, NIS2 Art. 23, DORA Art. 19 and customer or privacy-notice deadlines, and render a board report (HTML and PDF): overall
  readiness (Ready, Partially ready, Not ready), a clock test, eight disclosure capabilities, the open-case register, findings, a control
  map and proposed detections. Measured from the behavior-case register (triage time, escalations awaiting a human decision,
  reportability, open backlog), the log sources present and log clearing. USE THIS SKILL for "regulatory disclosure readiness",
  "SEC 8-K cyber disclosure", "NIS2 or DORA reporting readiness", "could we report in time", "breach notification readiness",
  "Board Rpt 3". Read-only via the tenant MCP connector. Not legal advice. DO NOT use it for one incident (incident-investigation).
---

# Regulatory Disclosure Readiness (board report)

Port of the original Board Rpt 3 skill onto Ingext-native tools and the Fluency editorial style. Read-only. Board audience: counts and
durations only, never individuals, hosts or addresses. The regulatory content is a planning summary, **not legal advice**; say so.

**Prerequisite: the `fluency-report` skill** (brand kit in its `scripts/`; `render_report.py` finds it or uses `FLUENCY_BRAND_DIR`).

## Steps

1. **Tenant and applicability.** Confirm the tenant (`list_accounts` if not named). Ask once for applicability facts: SEC registrant (or
   public parent), EU establishment or services and sector, whether it is an EU financial entity (DORA), customer or insurer notice
   clauses (hours). Write the answers to `applicability.json` (`assets/sample_evidence/applicability.sample.json`). Without answers
   proceed: SEC and NIS2 show "Confirm", DORA "Not applicable", customer notice is assumed.
2. **Case register (90 days, risk 3,000+).** Use epoch milliseconds for `rangeFrom`/`rangeTo` (now minus 90 days to now).
   - Register counts: `behavior_summary_search` with `searchStr` `riskScore:[3000 TO *]`, `limit` 1, `facets` `status`, `classification`,
     `scoreLevel`, `keyType`. Save the reply (the `total` and facet counts are exact) as `facets.json`.
   - Open cases: same range, `searchStr` `riskScore:[3000 TO *] AND status:new`, `limit` 20, `offset` 0, 20, 40 ... up to 100 cases,
     `facets` `scoreLevel`, `keyType` on the first page. Large replies are saved to a file by the tool; keep every file.
   - Closed sample: `riskScore:[3000 TO *] AND status:closed`, `sortField` `to`, `limit` 20 (one or two pages).
   Small replies come back inline instead of in a file; write them to a file yourself before step 5.
3. **Scope and log clearing (no event search).** `list_data_tables` (save as `tables.json`). If the tenant has Windows event logs, call
   `list_report_archive` for `WindowsSrv_Activity_Report`, then `download_report_archive` for the last 30 days with `objects` `win_trend`
   and `sources` (never the facet tables, which hold user names); save as `windows_archive.json`. Its `logsCleared` column counts Event 1102
   and 104. No archived days leaves evidence integrity as "Confirm". Retention is not probed: every tenant keeps 12 months of logs.
4. **Evidence:**
   `python3 scripts/case_evidence.py --facets facets.json --open open*.json --closed closed*.json --asof YYYY-MM-DD -o case_evidence.json`
   `python3 scripts/platform_evidence.py --tables tables.json [--windows-archive windows_archive.json] --asof YYYY-MM-DD -o platform_evidence.json`
5. **Rate and draft:** `python3 scripts/rate_evidence.py --cases case_evidence.json --platform platform_evidence.json --tenant "<Name>" --date YYYY-MM-DD [--applicability applicability.json] --out draft_findings.json`.
   Ratings come only from `assets/rating_rules.json` (see `references/scoring.md`).
6. **Review** the draft: plain language, no individual names; add what the rules cannot know (counsel's notes, what the tenant already
   documents elsewhere). Keep every `coverage_gaps` entry.
7. **Render:** `python3 scripts/render_report.py draft_findings.json <out_dir>` writes `Regulatory_Disclosure_Readiness_<Tenant>_<DDMonYY>.html` and `.pdf`.
8. **Reply briefly:** the readiness rating, the decisive gap, the applicability questions for counsel, and the file names.

## What cannot be measured (state in the report)

- **Reportability decisions** are not a field on Ingext cases, so the report shows "Not evidenced" unless a marker is found in case
  classifications or actions, or counsel states determinations are recorded elsewhere (`reportability_register`).
- **Triage and escalation** come from AI-analyst comments on the case. A tenant without them shows "Not evidenced" and the human-action clock uses case age.
- **Retention** is stated, not measured: 12 months is a platform guarantee, so timeline reconstruction is always Ready.
- **Scope** is which log sources exist (identity, collaboration, endpoint, network, cloud), not what an incident touched.
- Board, legal and customer-notice workflow, vendor incident intake and applicability are documents: "Confirm".
- If fewer open cases were read than exist, counts of old, escalated and personal-data cases are lower bounds (the report says so).

## Rules

- Only report what the data shows. Never change tenant configuration. Never name individuals.
- No event table is searched. Cases come from `behavior_summary_search`; scope from `list_data_tables`; log clearing from the archived Windows report.
