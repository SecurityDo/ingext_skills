# 2026-11-02 — microsoft365-resource-inventory-report 1.0.0 (new)

| Skill | Version | Status |
| --- | --- | --- |
| microsoft365-resource-inventory-report | 1.0.0 | released |

**An archive-only Microsoft 365 / Entra directory inventory**, built the same way as the other archive-only
activity reports. It reads only the archive of the scheduled report `Office365_Resource_Inventory_Report`
(FPL processor id 720182 in the Scripts repo) and never searches live.

- Users, administrators (isAdmin flag or any directory role), MFA registration, and the **named list of enabled
  users with no MFA**, administrators first; devices; Conditional Access policies by state; app registrations,
  client-secret hygiene and app-only permissions; enterprise applications; groups; licensed users with users per
  license.
- The directory tables are snapshots. The report uses the latest archived day in the period and shows a trend
  over the archived days; days are never added, and a backfill records today's directory, not a past state.
- `--interactive` writes one self-contained HTML file (tabs, search, sort and filter on the user lists, CSV export,
  hover trend charts, dark mode). Print-style HTML, PDF and CSV as in the other report skills.
- The lists name people, so the report and archive are personal data; `--no-actors` leaves the lists out.
- Dry run on a 2,752-user tenant: all ten scans ran in about 13 seconds; the no-MFA list matches the count (1,337).
