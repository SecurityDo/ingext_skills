---
name: privileged-access-drift-report
version: 2.0.0
description: >-
  Measure how ONE Fluency / Ingext tenant's administrator, directory-role and application privileges changed over the archived days and
  render a CISO report (HTML and PDF): drift rating, dated timeline, findings, applications granted tier-0 to tier-2 Graph permissions,
  role inventory, strengths, coverage gaps and proposed detections. Built ONLY from the archives of Office365_Resource_Inventory_Report
  and Privileged_Access_Drift_Report (plus the Entra and Windows activity archives); never runs kql_search or run_report. USE THIS SKILL
  for "privileged access drift", "privilege creep", "who got admin rights", "PIM review", "standing privilege", "app permission review",
  "CISO Rpt 2". DO NOT use it for one user (office-user-investigation), a current-state review (office365-posture-review) or a tenant
  with no archive (schedule the reports first).
---

# Privileged Access Drift (CISO report)

Port of the original CISO Rpt 2 skill onto Ingext-native tools and the Fluency editorial style. Read-only. CISO audience: name applications and
shared-style accounts, never individual administrators. Counts, roles and application names only; the archives hold no user list.

**Prerequisite: the `fluency-report` skill** (brand kit in its `scripts/`; `render_report.py` finds it or uses `FLUENCY_BRAND_DIR`).
The scheduled reports must be deployed and archiving: `Office365_Resource_Inventory_Report`, `Privileged_Access_Drift_Report`, and for the extras
`Office365_Entra_Activity_Report` and `WindowsSrv_Activity_Report`. Nothing here is searched live.

## Steps

1. **Tenant and window.** Confirm the tenant (`list_accounts` if not named). The window is the last 60 days; the archive decides how much of it is covered.
2. **List the archives.** `list_report_archive` for each of the four reports. Note the days each holds. Missing days of `Privileged_Access_Drift_Report` can be requested with
   `backfill_report_archive` (offer it; never fill a gap with a search). `Office365_Resource_Inventory_Report` is a snapshot per day: it cannot be backfilled, so its
   history starts when it was deployed.
3. **Download the archived days** with `download_report_archive` (`from`/`to` for the window) and save each reply as a file:
   - `Office365_Resource_Inventory_Report`, `objects` `o365res_users,o365res_role_holders,sources` -> `inventory.json`
   - `Privileged_Access_Drift_Report`, all objects -> `pad.json`
   - `Office365_Entra_Activity_Report`, `objects` `audit_facets` -> `entra.json` (optional)
   - `WindowsSrv_Activity_Report`, `objects` `win_trend` only (never the facet objects, which hold account names) -> `windows_archive.json` (optional)
4. **Publisher map (optional).** The archive records the application id of each grant. For the verified publisher, `list_resource_dumps` then `get_resource_dump_url`
   (format `jsonl`) for `office365InstalledApp`, download with `curl -sS -o <file> "<url>"` (the link expires, carries its own credential and must not appear in a reply or a file),
   and run `python3 scripts/dump_evidence.py --apps office365InstalledApp.jsonl.gz -o apps.json`. Never read a dump into the conversation. Without it the table says "not checked".
5. **Merge:** `python3 scripts/drift_evidence.py --inventory inventory.json --pad pad.json [--entra entra.json] [--windows-archive windows_archive.json] [--apps apps.json] --asof YYYY-MM-DD -o drift_evidence.json`.
6. **Rate and draft:** `python3 scripts/rate_evidence.py --evidence drift_evidence.json --tenant "<Name>" --date YYYY-MM-DD --out draft_findings.json`.
   The rating and the tiers come only from `assets/rating_rules.json` (see `references/scoring.md`).
7. **Review** the draft: plain language, no individual names; add what the rules cannot know (a vendor's stated need for a permission, a break-glass
   account, an approved PAM tool). Keep every `coverage_gaps` entry; they state how many archived days back each figure.
8. **Render:** `python3 scripts/render_report.py draft_findings.json <out_dir>` writes `Privileged_Access_Drift_<Tenant>_<DDMonYY>.html` and `.pdf`.
9. **Reply briefly:** the drift rating, the top three findings, the archive coverage and the file names.

## How the archive days are combined

Event counts (role events, application grants, Conditional Access changes, sign-ins) are added over the days. Distinct-account counts per day (administrators that signed in,
administrators with a single-factor sign-in) use the **busiest day**, which is a lower bound for the whole period. Directory state (privileged accounts, holders per role, licences,
MFA registration) is the **latest inventory day**; the difference between inventory days gives the change in Global Administrators and in privileged accounts.

## What cannot be measured (state in the report)

- **Dormant administrators**: the archives hold how many administrators signed in on a day, not which ones, so an account with no sign-in for the window cannot be listed.
- **Delegated (user-consented) grants** are counted from the Entra activity archive but not listed by application; only application permissions are.
- **PIM-eligible (inactive) assignments** are not in the user snapshot; only active role holders are counted.
- **LAPS deployment** is not measured; the device local-administrator role holders are counted only.
- **History** is as long as the archives: a short `Privileged_Access_Drift_Report` archive is stated as a gap, and role-holder history starts at the first inventory day that carries it.
- A tenant whose directory audit scan was "not available" shows "Not observed", not zero drift. A tenant without `RoleManagement` events gets a finding that role changes are invisible.
- **On-premises changes** are the archived Windows report's `groupAdds` (4728, 4732, 4756) and `accountCreated` (4720) over the days it holds.
- Applications that assign roles and then remove them (removals at least 80% of additions) are treated as time-boxed tooling: still reported, not rated high.

## Rules

- Only report what the archives show. Never run a live search for this report. Never change tenant configuration. Never name individual administrators; applications and shared accounts may be named.
