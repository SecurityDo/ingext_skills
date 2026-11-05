---
name: iso-cmmc-compliance-analysis
version: 1.2.0
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

After the tables comes a **Framework-specific checks** table with 10 ISO 27001 Annex A checks and 10 CMMC practices (`--framework` limits it to one), each showing No gap seen, Review, Gap seen or Not evaluable. It covers MFA, logging, incidents, threat findings and, when the summary carries Defender evidence (compliance-assessment 1.4.0 or later with the `mde_*` dumps), vulnerabilities, antivirus, secure configuration and device inventory. Without Defender evidence those rows read Not evaluable. No gap seen is an observation about the evidence, never a statement that a control is met.

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

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own
copy: the build scripts here that style a report find the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and
import `fluency_brand` from it, and stop with a clear message if it is not installed. Install `fluency-report` alongside this skill. In the steps below, `<fluency-report>` means
that skill's folder.

- The HTML report is one self-contained file (mark, fonts and CSS inlined). The PDF is rendered from that same HTML with the same
  CSS, so the two match: `node <fluency-report>/scripts/render_pdf.mjs --input report.html --output report.pdf`.
  US Letter, same editorial styling as the HTML (brandline, closing footer line; no paged footer). It needs Playwright
  (`npm install playwright`) and a Chromium or Chrome binary; it finds a Chrome install automatically.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore
  the brand CSS (grid, fonts, page rules), so the PDF would not match the HTML.
- Do not hand-write report styling. The look is the Fluency editorial style (white paper, IBM Plex, black rules, one blue / red / amber, no cards or gradients). A new page is `fluency_brand.page(...)`; markup from an older script goes
  through `fluency_brand.apply_brand(html)`. Design and component reference: the `fluency-report` skill (`references/widget_recipes.md`).
