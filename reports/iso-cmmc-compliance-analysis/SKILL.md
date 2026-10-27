---
name: iso-cmmc-compliance-analysis
version: 1.0.0
description: >-
  Express a tenant's NIST 800-53 compliance evidence in ISO/IEC 27001:2022 Annex A and CMMC 2.0
  Level 2 language as HTML plus CSV: each ISO control or CMMC practice with its related 800-53
  control groups and their statuses, the caveat for each, the strongest mapped areas, the
  not-observed areas and the evidence still needed before audit or assessor use. USE THIS SKILL for
  "ISO 27001 view of our compliance evidence", "CMMC mapping", "crosswalk NIST findings to ISO or
  CMMC", "paragraph markings", "companion mapping". It reads the compliance_summary.json that
  compliance-assessment writes and collects nothing itself. PREREQUISITE: install and run
  compliance-assessment first. Rows are related, never equivalent; it never claims ISO
  certification, a CMMC result or compliance. DO NOT use it for the 800-53 control table
  (nist-compliance-analysis) or a customer evidence report (compliance-assessment).
---

# ISO/CMMC Compliance Analysis

> **Prerequisite: install `compliance-assessment` and run it for the tenant and month with
> `--summary-json`.** This skill reads that file and collects nothing. The 800-53 control table itself is
> `nist-compliance-analysis`; this is its ISO and CMMC companion.

Renders the 800-53-rooted evidence in ISO/IEC 27001:2022 and CMMC language. It is read-only.

## Steps

1. Run **compliance-assessment** with `--summary-json WORKDIR/compliance_summary.json`.
2. Build:

```bash
python3 scripts/build_report.py --summary WORKDIR/compliance_summary.json --out WORKDIR/companion.html \
  --csv WORKDIR/companion.csv --tenant "Example Corp" --site Develop [--framework iso|cmmc|both]
```

## Reading it

One table per framework: `Control | Title | Related 800-53 controls and status | Caveat`. Then summarize:

- **Strongest mapped areas:** companion controls whose every related 800-53 group is supported.
- **Not observed:** companion controls whose related groups are all not observed (evidence not collected).
- **Evidence still required before audit or assessor use:** everything partial, mixed or needing manual review.

## Rules

- Always say companion findings are **mapped or related** to 800-53-rooted evidence. Never say an ISO
  control, a CMMC practice, CSF or 800-171 is equivalent, and never say one is met because a related 800-53
  group is supported.
- Keep CMMC wording advisory. The rows follow Level 2 practices, aligned to SP 800-171 Rev. 2.
- Keep the 800-53 source group in every row; a companion row never raises a status.
- The mapping is the analyst's, indicative, and should be checked against ISO/IEC 27001:2022 Annex A and the
  CMMC assessment guide before audit use. ISO clauses 4 to 10 (the management system) are not covered.
- Not observed is not a failure. Never write "certified", "compliant" or "attested".
- The output names the tenant; keep it out of the repository.
