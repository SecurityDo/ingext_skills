---
name: soc2-compliance-analysis
version: 1.0.0
description: >-
  Express a tenant's NIST 800-53 compliance evidence in SOC 2 Trust Services Criteria terms as HTML plus CSV: each
  requirement with its related 800-53 control groups and their statuses, a caveat, the strongest
  mapped areas, the not-observed areas, and what telemetry cannot evidence. USE THIS SKILL for
  "SOC 2 view of our compliance evidence", "map the NIST findings to SOC 2", "SOC 2 readiness
  evidence", "crosswalk to SOC 2". It reads the compliance_summary.json that compliance-assessment
  writes and collects nothing itself. PREREQUISITE: install and run compliance-assessment first.
  Rows are related, never equivalent; it never claims SOC 2 compliance or certification. DO NOT use
  it for the 800-53 control table (nist-compliance-analysis) or a customer evidence report
  (compliance-assessment).
---

# SOC 2 Compliance Analysis

> **Prerequisite: install `compliance-assessment` and run it for the tenant and month with
> `--summary-json`.** This skill reads that file and collects nothing. The 800-53 control table itself is
> `nist-compliance-analysis`; this is its SOC 2 companion.

Renders the 800-53-rooted evidence in SOC 2 Trust Services Criteria language. It is read-only.

## Steps

1. Run **compliance-assessment** with `--summary-json WORKDIR/compliance_summary.json`.
2. Build:

```bash
python3 scripts/build_report.py --summary WORKDIR/compliance_summary.json --out WORKDIR/report.html \
  --csv WORKDIR/report.csv --tenant "Example Corp" --site Develop
```

## Reading it

One table: `Requirement | Title and caveat | Related 800-53 groups and status`. Summarize:

- **Strongest mapped areas:** requirements whose every related 800-53 group is supported.
- **Not observed:** requirements whose related groups are all not observed (evidence not collected).
- **Evidence still required:** everything partial, mixed or needing manual review.
- **Not evidenced by telemetry:** the parts of SOC 2 that logs and inventories cannot show. Read this list aloud.

## Rules

- Always say rows are **mapped or related** to 800-53-rooted evidence. Never say a SOC 2 requirement is
  equivalent to, or met by, a related 800-53 status. Only a licensed CPA firm can issue a SOC 2 report or an auditor's opinion (Type 1 or Type 2).
- Keep the 800-53 source group in every row; a row never raises a status.
- The mapping is the analyst's and indicative; check it against the current text of SOC 2 Trust Services Criteria before use.
- Not observed is not a failure. Never write "compliant", "certified" or "attested".
- The output names the tenant; keep it out of the repository.
