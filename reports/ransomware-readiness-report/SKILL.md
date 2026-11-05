---
name: ransomware-readiness-report
version: 1.3.0
description: >-
  Assess ONE Fluency / Ingext tenant's ability to prevent, withstand and recover from ransomware and render
  a board-level report (HTML and PDF): an overall rating, an eight-pillar scorecard, 6 to 10 ranked issues
  with owners, targets and MITRE techniques, a 90-day roadmap and the strengths to keep. Examines backup
  server exposure, EDR coverage and unprotected devices, ASR and LAPS hardening, exploitable
  vulnerabilities, detect-only EDR policy, admin MFA, domain-controller log clearing and remote-access tool
  sprawl, from SentinelOne, Defender, Entra ID and Windows audit tables. USE THIS SKILL for "ransomware
  readiness", "would we survive ransomware", "ransomware resilience or preparedness", "board ransomware
  briefing", "Board Rpt 2". Read-only through the tenant's MCP connector. DO NOT use it for one incident
  (incident-investigation) or a general endpoint hygiene page (defender-resource-report, falcon-resource-report,
  sentinelone-resource-report). The cyber-risk-in-dollars report reuses this skill's evidence.
---

# Ransomware Readiness (board report)

Produces a board-safe report: no individual user, host or IP names; plain-language "why the board should
care"; an owner and a target date on every recommendation. Read-only; nothing in the tenant is changed.

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark, `render_pdf.mjs`). This skill carries no copy:
`scripts/render_report.py` finds the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and stops
with a clear message if it is missing. The layout is fixed by the renderer and the chart and table components are the
ones in that skill's chart gallery.

## What is fixed and what the analyst writes

The renderer fixes the structure: title block, KPI strip (overall rating, critical issues, high issues, one secure-score
figure), executive summary with the board ask, the eight-pillar scorecard, the ranked findings, the 90-day roadmap,
strengths, methodology. The analyst supplies only the content in `findings.json` (the evidence and the words). The
**overall rating is computed** from the pillar statuses by `render_report.py`, never taken from the file; a mismatch is
reported.

## Steps

1. **Connector.** Confirm which tenant. If the user did not name one, call `list_accounts` and ask.
2. **Read `references/query_playbook.md`.** It holds the proven queries and the engine quirks (WindowsAudit uses
   `timestamp`; resource tables take no time filter; always pass both `rangeFrom` and `rangeTo`). Follow the `ingext-kql`
   skill for every query and run `validate_kql` before `kql_search`.
3. **Resource data: download and parse locally.** Never query resource tables with KQL. Call
   `list_resource_dumps` for the tenant, then `get_resource_dump_url` for each of: sentinelOneAgent,
   sentinelOneApplication, sentinelOneThreat, msDefenderMachine, msDefenderSecureConfig (parquet),
   msDefenderSecureScore, msDefenderVulnerability (parquet, over a million rows), office365User and
   office365ConditionalAccessPolicy. Download each file with `curl -o <dump_dir>/<resource>.jsonl.gz` (or
   `.parquet`) in a shell that can reach the tenant host (links expire in 15 minutes; fetch them in one go), then run
   `python3 scripts/resource_evidence.py <dump_dir> evidence.json`. It needs pandas and pyarrow for the parquet files and
   writes aggregate counts only: coverage and stale agents, detect-only modes, Defender devices with no EDR agent, backup
   products and versions, remote-access tools, end-of-life OS, ASR, LAPS and Credential Guard gaps, Critical and High
   vulnerabilities with exploit availability, threat classes, user counts and conditional-access MFA policies. A dump that
   is missing is listed under `gaps`: a visibility gap, never a guess. If the shell cannot reach the tenant host, tell the
   user the host must be allowed or the download run on their own computer.
3b. **Windows audit: archive only.** Call `list_report_archive` for `WindowsSrv_Activity_Report` and
   `download_report_archive` for the last 30 days (save the result to a file), then run
   `python3 scripts/windows_evidence.py <file> -o windows_evidence.json`. It sums the daily results into log clearing
   (1102/104), audit-policy changes, new services and scheduled tasks (7045/4697/4698), account and group changes, failed
   and NTLM logons and failed-logon source patterns, with suspect service names flagged. Never run `kql_search` or
   `run_report` for this pillar: if the report is not archived, the Windows pillar is "not measurable, visibility gap".
   (To test before a tenant has the archive, one `run_report` result for a single day has the same shape and is accepted.)
3c. **Sign-in events: archive only.** Call `list_report_archive` for `Office365_Entra_Activity_Report` (that exact name; no other
   name is accepted) and
   `download_report_archive` for the last 30 days with `objects` set to `signin_trend`, `signin_facets`, `audit_trend`
   and `sources`. Save the result to a file and run `python3 scripts/entra_evidence.py <file> -o entra_evidence.json`.
   It returns sign-in counts, the single-factor share, how many sign-ins had conditional access applied, legacy-auth
   clients, admin-portal sign-in volume and directory changes. Hidden risk levels or an unavailable table become gaps.
   If there is no archive the identity sign-in checks are "not measurable, visibility gap"; never query AzureSigninLogs.
4. **Run the eight pillars:** Backup and recovery; Endpoint coverage; Prevention and hardening; Vulnerability exposure;
   Detection and response; Identity and access; Logging and forensics; Threat activity. Fold remote-access tools and
   end-of-life systems into the most relevant pillar. 30-day WindowsAudit queries are slow: filter by EventID first.
5. **Backup product versions.** `resource_evidence.py` compares each backup product and version with
   `assets/backup_advisories.json` (the Veeam advisory list; edit that file when advisories or fixed versions change and
   the logic stays the same). Each row is VULNERABLE, fixed or newer, or "CVE status not verified". An unlisted product or
   version is never reported as safe.
6. **Select the top issues** (6 to 10), ranked Critical, High, Medium by how directly they enable encryption or block
   recovery. Backup compromise and unprotected devices outrank hygiene items. For each: finding (with numbers), why
   the board should care (one or two sentences, no jargon), recommendation, owner, target (7, 14, 30, 60 or 90 days),
   MITRE technique.
7. **Collect strengths:** controls that are compliant. A board needs balance.
8. **Write `findings.json`** in the shape of `assets/sample_findings_acme.json`. Fields: `tenant`, `assessment_date`
   (YYYY-MM-DD), `evidence_window`, `kpi_label`, `kpi_value`, `summary_headline`, `summary`, `board_ask`,
   `pillars` (eight of `{name, status red|amber|green, detail}`), `issues`, `roadmap`, `strengths`, `methodology`.
   Text is inserted as HTML: write `&amp;`, `&lt;`, `&gt;`.
9. **Render:** `python3 scripts/render_report.py findings.json <out_dir>` writes
   `Ransomware_Readiness_<Tenant>_<DDMonYY>.html` and the matching `.pdf` (same base name). `--date DDMonYY` overrides the
   stamp; `--no-pdf` skips the PDF.
10. **Reply briefly:** the overall rating, the top three issues and the file names.

## Scoring (computed by the renderer)

- Pillar **red / At risk**: any Critical issue in the pillar, or a control absent fleet-wide. **Amber / Needs work**:
  High or Medium issues, or partial coverage or no data. **Green / Healthy**: no material issues.
- Overall: a red pillar in Backup, Endpoint coverage or Prevention gives **Elevated Risk**; otherwise two or more red
  give **High Risk**; no red and no amber gives **Resilient**; everything else is **Moderate Risk**.

## Rules

- Board audience: aggregate counts only. Detail can be offered to the security team in chat.
- State caveats plainly: hostname matching, uncollected MFA data, server coverage gaps.
- Only report what the data shows. A pillar with no data is amber, "not measurable, visibility gap".
- Never change tenant configuration.
