---
name: privileged-access-drift-report
version: 1.0.0
description: >-
  Measure how ONE Fluency / Ingext tenant's administrator, directory-role and application privileges changed over 60 days and render a
  CISO report (HTML and PDF): drift rating (High, Elevated, Moderate, Low), a dated timeline, findings, applications granted tier-0 to
  tier-2 Microsoft Graph permissions, the directory role inventory, strengths, coverage gaps and proposed detections. Measured from the
  Entra user snapshot (roles, licences, MFA registration), directory audit logs (PIM, roles assigned outside PIM, application grants,
  Conditional Access), administrator sign-ins and Windows audit events. USE THIS SKILL for "privileged access drift", "privilege creep",
  "who got admin rights", "PIM review", "standing privilege", "service principal or app permission review", "CISO Rpt 2". Read-only via the
  tenant MCP connector. DO NOT use it for one user (office-user-investigation) or a current-state posture review (office365-posture-review).
---

# Privileged Access Drift (CISO report)

Port of the original CISO Rpt 2 skill onto Ingext-native tools and the Fluency editorial style. Read-only. CISO audience: name applications and
shared-style accounts, never individual administrators. Counts, roles and application names only.

**Prerequisite: the `fluency-report` skill** (brand kit in its `scripts/`; `render_report.py` finds it or uses `FLUENCY_BRAND_DIR`).
Follow the `ingext-kql` skill for every query.

## Steps

1. **Tenant and window.** Confirm the tenant (`list_accounts` if not named) and use 60 days unless asked otherwise. `list_data_tables` (save as
   `tables.json`). Each missing table (AzureAuditLogs, AzureSigninLogs, office365User, office365InstalledApp, WindowsAudit) becomes a coverage gap.
2. **Snapshot data from resource dumps first (no query).** `list_resource_dumps` for the tenant, then `get_resource_dump_url` (format `jsonl`) for `office365User`
   and `office365InstalledApp` (use the resource names it lists). Download each link with `curl -sS -o <file> "<url>"` (the link expires in 15 minutes, carries its own
   credential and must not appear in a reply or a file). Never read a dump into the conversation. If the cloud proxy refuses the host, run the download and the script on the
   linked computer (`device_bash`); if neither can reach it, use the query fallback in `references/playbook.md` section 1. Then:
   `python3 scripts/dump_evidence.py --users office365User.jsonl.gz --apps office365InstalledApp.jsonl.gz --asof YYYY-MM-DD -o dump_out`
   writes `roles.json`, `accounts.json`, `apps.json` and the sign-in query files `signins_query_<n>.kql`. `dump_out/privileged_upns.txt` names individuals: keep it out of
   every deliverable and commit.
3. **Log queries** (`references/playbook.md` sections 2 to 6) with `rangeFrom`/`rangeTo` in epoch milliseconds (now minus 60 days to now). Run each
   `signins_query_<n>.kql` and save the replies as `signins_<n>.json`; run the audit queries and save `role_drift`, `role_activity`, `app_grants`, `app_events` and `ca_changes`. Small replies come back inline: write them to a file yourself. Skip a query whose table is absent.
   **On-premises changes come from the archive, not a search:** `list_report_archive` for `WindowsSrv_Activity_Report` (stop here if the tenant has no Windows logs), then
   `download_report_archive` for the last 30 days with `objects` `win_trend` only (never the facet objects, which hold account names); save as `windows_archive.json`. Report the days
   missing from the coverage and offer `backfill_report_archive` for them; never fill a gap with a search.
   Evidence: `python3 scripts/drift_evidence.py --roles dump_out/roles.json --accounts dump_out/accounts.json --signins signins_1.json [signins_2.json ...] [--role-drift ...] [--role-activity ...] [--app-grants ...] [--app-events ...] [--ca ...] [--windows-archive windows_archive.json] [--apps dump_out/apps.json] --tables tables.json --asof YYYY-MM-DD -o drift_evidence.json`
4. **Rate and draft:** `python3 scripts/rate_evidence.py --evidence drift_evidence.json --tenant "<Name>" --date YYYY-MM-DD --out draft_findings.json`.
   The rating and the tiers come only from `assets/rating_rules.json` (see `references/scoring.md`).
5. **Review** the draft: plain language, no individual names; add what the rules cannot know (a vendor's stated need for a permission, a break-glass
   account, an approved PAM tool). Keep every `coverage_gaps` entry.
6. **Render:** `python3 scripts/render_report.py draft_findings.json <out_dir>` writes `Privileged_Access_Drift_<Tenant>_<DDMonYY>.html` and `.pdf`.
7. **Reply briefly:** the drift rating, the top three findings and the file names.

## What cannot be measured (state in the report)

- **On-premises changes** are the archived Windows report's `groupAdds` (4728, 4732, 4756) and `accountCreated` (4720) over the days the archive holds; a short archive is stated as a coverage gap.
- **PIM-eligible (inactive) assignments** are not in the user snapshot; only active role holders are counted.
- **LAPS deployment** is not measured; the device local-administrator role holders are counted only.
- **Dormant** means no interactive sign-in in the window (non-interactive sign-ins are a separate table), so service accounts can appear dormant.
- **Publisher verification** needs the `office365InstalledApp` dump (or the `apps` query fallback); without it the application table says "not checked".
- A tenant without `RoleManagement` audit events shows "Not observed", not zero drift, and gets a finding that role changes are invisible.
- Applications that assign roles and then remove them (removals at least 80% of additions) are treated as time-boxed tooling: still reported, not rated high.

## Rules

- Only report what the data shows. Never change tenant configuration. Never name individual administrators; applications and shared accounts may be named.
