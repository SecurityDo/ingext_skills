---
name: nist-compliance-analysis
version: 1.0.0
description: >-
  Turn a tenant's compliance-assessment result into a NIST SP 800-53 Rev. 5 control-by-control
  analysis as HTML plus CSV: scope and framework, counts by status, a table of Control, Title,
  Status, Evidence state and Next evidence, the evidence worth collecting next, and an optional CSF
  2.0 and SP 800-171 Rev. 3 child view that keeps the 800-53 lineage. USE THIS SKILL for "NIST
  compliance analysis", "800-53 control-by-control review", "which NIST controls lack evidence",
  "what evidence should we collect next", or a CSF or 800-171 rendering of the same evidence. It
  reads the compliance_summary.json that compliance-assessment writes and collects nothing itself.
  PREREQUISITE: install and run compliance-assessment first. Never claims certification or
  compliance. DO NOT use it for a customer-facing evidence report (compliance-assessment) or a
  single incident (incident-investigation).
---

# NIST Compliance Analysis

> **Prerequisite: install `compliance-assessment` and run it for the tenant and month with
> `--summary-json`.** This skill reads that file. Without it there is nothing to analyse.

A control-by-control reading of what the evidence supports, with the 800-53 control as the root. It is
read-only and collects nothing: statuses and evidence text are used exactly as compliance-assessment
returned them.

## Steps

1. Run **compliance-assessment** for the tenant and period with
   `--summary-json WORKDIR/compliance_summary.json` (it collects the evidence and owns the status logic).
2. Build:

```bash
python3 scripts/build_report.py --summary WORKDIR/compliance_summary.json --out WORKDIR/nist.html \
  --csv WORKDIR/controls.csv --tenant "Example Corp" --site Develop [--view csf|800-171|both]
```

## Reading it

Lead with: tenant scope, the framework (800-53 Rev. 5, 13 control groups), that the evidence is live for the
period, the counts by status, and the highest-value evidence to collect next. Then the table:

```text
Control | Title | Status | Evidence state | What the evidence showed | Next evidence
```

- **Supported:** the evidence directly shows the control operating in the window.
- **Partial:** some evidence exists; configuration, coverage or review cadence was not shown.
- **Not observed:** the evidence was not collected, or there is no data source for it. **Never present it as
  a failure.**
- **Needs manual review:** policy and procedure controls; only customer documents can evidence them.

The CSF 2.0 and SP 800-171 Rev. 3 views are an indicative **category-level** crosswalk (the analyst's, not
NIST's official mapping); say so and keep the 800-53 control visible as the lineage.

## Rules

- Never write "compliant", "certified" or "attested". Do not convert not observed into a failure.
- Use statuses exactly as returned; do not upgrade one because the evidence looks good.
- Snapshot counts are as of the dump time and event counts are for the period; say so.
- The output names the tenant; keep it out of the repository.
