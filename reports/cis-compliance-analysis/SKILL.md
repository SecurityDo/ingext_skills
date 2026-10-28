---
name: cis-compliance-analysis
version: 1.3.0
description: >-
  Express a tenant's NIST 800-53 compliance evidence in CIS Critical Security Controls v8.1 terms as HTML plus CSV: each
  requirement with its related 800-53 control groups and their statuses, a caveat, the strongest
  mapped areas, the not-observed areas, and what telemetry cannot evidence. USE THIS SKILL for
  "CIS Controls view of our compliance evidence", "map the NIST findings to CIS Controls", "CIS Controls readiness
  evidence", "crosswalk to CIS Controls". It reads the compliance_summary.json that compliance-assessment
  writes and collects nothing itself. PREREQUISITE: install and run compliance-assessment first.
  Also runs framework-specific checks (MFA, logging, incidents, threat findings, history depth) and shows an evidence-coverage figure with its change since the prior month. Rows are related, never equivalent; it never claims CIS Controls compliance or certification. DO NOT use
  it for the 800-53 control table (nist-compliance-analysis) or a customer evidence report
  (compliance-assessment).
---

# CIS Controls Compliance Analysis

> **Prerequisite: install `compliance-assessment` and run it for the tenant and month with
> `--summary-json`.** This skill reads that file and collects nothing. The 800-53 control table itself is
> `nist-compliance-analysis`; this is its CIS Controls companion.

Renders the 800-53-rooted evidence in CIS Critical Security Controls v8.1 language. It is read-only.

## Steps

1. Run **compliance-assessment** with `--summary-json WORKDIR/compliance_summary.json`.
2. Build:

```bash
python3 scripts/build_report.py --summary WORKDIR/compliance_summary.json --out WORKDIR/report.html \
  --csv WORKDIR/report.csv --tenant "Example Corp" --site Develop
```

## Reading it

The page opens with an **evidence-coverage** card for this framework (supported = 1, partial = 0.5 over the mapped groups telemetry can evidence). When the summary carries a prior month, the card shows the change. A **Framework-specific checks** table follows the crosswalk: each row reads one of the framework's own requirements against the facts in the summary and returns No gap seen, Review, Gap seen or Not evaluable. The thresholds are the analyst's; No gap seen is an observation about one month of evidence, never a statement that a requirement is met.

When the summary carries Defender evidence (compliance-assessment 1.4.0 or later with the `mde_*` dumps), the checks table also covers known-exploit and aged critical vulnerabilities, antivirus currency, secure configuration and device inventory. Without it those rows read Not evaluable.


One table: `Requirement | Title and caveat | Related 800-53 groups and status`. Summarize:

- **Strongest mapped areas:** requirements whose every related 800-53 group is supported.
- **Not observed:** requirements whose related groups are all not observed (evidence not collected).
- **Evidence still required:** everything partial, mixed or needing manual review.
- **Not evidenced by telemetry:** the parts of CIS Controls that logs and inventories cannot show. Read this list aloud.

## Rules

- Always say rows are **mapped or related** to 800-53-rooted evidence. Never say a CIS Controls requirement is
  equivalent to, or met by, a related 800-53 status. Only a qualified assessor can issue a CIS Controls assessment result.
- Keep the 800-53 source group in every row; a row never raises a status.
- The mapping is the analyst's and indicative; check it against the current text of CIS Critical Security Controls v8.1 before use.
- Not observed is not a failure. Never write "compliant", "certified" or "attested".
- The output names the tenant; keep it out of the repository.
