---
name: cyber-risk-in-dollars-report
version: 1.0.0
description: >-
  Quantify ONE Fluency / Ingext tenant's cyber risk in dollars for the board and CFO and render a report (HTML and PDF):
  expected annual loss, 1-in-10 and 1-in-20 year loss, a loss exceedance curve, a quantified risk register (ransomware,
  business email compromise, cloud data breach) and the dollar value of each recommended action, by FAIR-style Monte Carlo
  simulation calibrated from the ransomware-readiness evidence and the archived sign-in report. USE THIS SKILL for "cyber
  risk in dollars", "cyber risk quantification", "CRQ", "FAIR analysis", "annualized loss expectancy", "loss exceedance
  curve", "security ROI", "cyber insurance limit", "how much could a breach cost us", "Board Rpt 1". Read-only through the
  tenant MCP connector. REQUIRES the ransomware-readiness-report and fluency-report skills. DO NOT use it for one incident
  (incident-investigation) or for the readiness rating itself (ransomware-readiness-report).
---

# Cyber Risk in Dollars (board report)

Turns security evidence into financial risk a board and CFO can act on. Board-safe: no individual user, host or IP
names. Read-only; nothing in the tenant is changed. Results are modelled ranges, not forecasts.

**Prerequisites.**
- **`ransomware-readiness-report`.** This report reuses its evidence and its list of fired rules; it duplicates none of that
  logic. Run its evidence steps for the same tenant first (see step 2).
- **`fluency-report`.** All styling lives in that skill's `scripts/`. `scripts/render_report.py` finds it next to this
  skill (or at `FLUENCY_BRAND_DIR`) and stops with a clear message if it is missing.

## What is fixed and what the analyst does

The numbers are rule-based. `assets/calibration_rules.json` (listed in `references/calibration_rules.md`) turns the
readiness evidence into a frequency range and a loss range for each scenario; `scripts/calibrate_scenarios.py` applies it
and `scripts/render_report.py` simulates and renders. The analyst does **not** type frequencies or dollar figures: to
change one, change the rules file and regenerate the document. The analyst checks the evidence bullets and assumptions,
adds what the customer supplied, and writes the reply. Text in the report that quotes a result (expected loss, bad-year
loss, the largest scenario) is filled in from the simulation, so it always matches the numbers.

## Steps

1. **Connector and tenant.** Confirm which tenant. If the user did not name one, call `list_accounts` and ask.
2. **Readiness evidence.** Follow the `ransomware-readiness-report` skill, steps 3 to 6, for this tenant: download the
   resource dumps and run `resource_evidence.py`, build the Windows and sign-in evidence from the archived reports
   (archive-only: never a live search), then run `rate_evidence.py`. Keep four files: `resource_evidence.json`,
   `windows_evidence.json` (if the Windows archive exists), `entra_evidence.json` (if the sign-in archive exists) and the
   rating draft `draft_findings.json` (its `_review.rules_fired` is what drives the treatments). A missing source is a
   gap that widens the range, not a reason to stop.
3. **Business inputs.** Ask once, in a single short question, for: annual revenue or daily downtime cost, cyber insurance
   limit and deductible, the largest 1-in-10-year loss the board will tolerate, and the annual cost of each recommended
   action. Write the answers to `business_inputs.json` (shape: `assets/business_inputs.sample.json`). If the user wants to
   proceed without them, skip the file: the report scales loss from a reference organization and says so under
   assumptions. Never invent control costs; the report shows "cost to be supplied".
4. **Benchmarks.** The loss anchors (IBM Cost of a Data Breach, FBI IC3) are listed in `assets/calibration_rules.json`
   under `benchmarks`. If they are more than a year old, check them with a web search and update that file and the
   `anchor` sentences before running.
5. **Calibrate.** Run
   `python3 scripts/calibrate_scenarios.py --resource resource_evidence.json [--windows windows_evidence.json]
   [--entra entra_evidence.json] --rating draft_findings.json --tenant "<Tenant>" [--business business_inputs.json]
   --out scenarios.json`. It prints each scenario's frequency range, typical cost per event, the evidence factors that
   applied and which actions were included.
6. **Review `scenarios.json`.** Read the evidence bullets (counts only; no users, hosts or IPs), each scenario's
   calibration paragraph and the assumptions. Wording may be sharpened and customer-supplied facts added to
   `assumptions`; do not edit the numbers. `_review` lists the factors applied, the data gaps and any defaults used.
7. **Render.** `python3 scripts/render_report.py scenarios.json <out_dir>` (add `--no-pdf` to skip the PDF). Output:
   `Cyber_Risk_in_Dollars_<Tenant>_<DDMonYY>.html` and `.pdf`. It prints the expected annual loss, the 1-in-10 and
   1-in-20 year loss and the largest scenario.
8. **Reply briefly:** expected annual loss, the 1-in-10 year loss, the largest scenario, the action that avoids the most
   loss, and the main data gaps.

## Limits to state in the report

- **Three scenarios.** Ransomware, business email compromise and credential-driven cloud breach. Accidental and insider
  exposure (including shadow AI) is not modelled: the Office 365 archive counts sharing and external-access events but
  reports zero DLP matches, which cannot separate "no DLP policy" from "no matches", and no generative-AI egress source
  exists. Third-party compromise is not modelled separately so as not to double count ransomware.
- **Business email compromise** is calibrated from sign-in data and the Office 365 archive's counts of inbox-rule and
  mailbox-permission changes. Forwarding targets, who made the changes and payment controls are not in any archive, so
  they widen the range. The weights for rule and permission volume are proposals; the sources do not define them.
- **Recovery is unproven.** No backup job, age, immutability or restore-test data is available (see the
  ransomware-readiness skill), which widens the ransomware range.
- **Losses are gross.** Insurance recoveries and deductibles are not netted off; a supplied limit is only compared with
  the simulated years.
- **Treatment effects are expert estimates**, and actions overlap, so the avoided loss per action does not add up to the
  total.

## Reference

`references/fair_method.md` explains the method and scenarios. `references/calibration_rules.md` lists every weight,
threshold and loss figure (generated by `scripts/make_calibration_doc.py` after each change to the rules file).
`assets/sample_scenarios_gramfg.json` is a worked example of the calibration output.
