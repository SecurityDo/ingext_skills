# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}` (a range download also has a top-level `coverage`).

- `entry`: `state`, `rangeFrom`, `rangeTo` (a UTC day), `completedOn`, `env.scriptHash`. Only completed days carry a `result`.
- `result.objects[]` has eleven objects, each `{name, table: {rowCount, columns[], rows[]}}`; `rows[]` holds one object per row
  keyed by column name. An empty table has no columns and no rows. Booleans can come back as true/false or "true"/"false";
  `roles` is JSON text such as `["Global Administrator"]`.

| Object | One row per | Columns |
|---|---|---|
| `o365res_users` | tenant | users, enabled, disabled, guests, admins, registrationKnown, enabledMfaRegistered, enabledNoMfa, adminsNoMfa, asOf |
| `o365res_devices` | tenant | devices, managedKnown, managed, complianceKnown, nonCompliant, stale90d, asOf |
| `o365res_ca` | Conditional Access state | state, policies, asOf |
| `o365res_apps` | tenant | apps, secrets, certificates, appsNoCredentials, multiTenant, asOf |
| `o365res_app_secrets` | tenant | secrets, expired, expiring90d, longLived, asOf |
| `o365res_app_perms` | tenant | appsAppOnly, asOf |
| `o365res_enterprise` | tenant | total, enabled, disabled, microsoftOwned, registeredHere, thirdParty, assignmentRequired, withCredentials, asOf |
| `o365res_groups` | tenant | groups, securityEnabled, microsoft365, publicGroups, roleAssignable, dynamicGroups, emptyGroups, membersTotal, asOf |
| `o365res_noncompliant_users` | enabled user with no MFA | userPrincipalName, displayName, userType, finding, isAdmin, roles, asOf |
| `o365res_licensed_users` | user with a license | userPrincipalName, displayName, userType, accountEnabled, licenseCount, licenses, skuids, asOf |
| `sources` | scan | source, status (`ok` or `not available`), detail |

## Merge rules (these are snapshots, not events)

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. **Never add days together.** Each day is the directory state when the run took the snapshot. The report shows the latest
   archived day in the period (the state nearest the period end) and a per-day change table.
3. A day with no completed run is a gap, never zero. A backfill records the directory as it is when the backfill runs, so it
   cannot reconstruct a past state: a backfilled day shows today's directory.
4. A scan whose `sources` row says "not available" is not zero (for example no Conditional Access table on the tenant).
5. `o365res_noncompliant_users` has one row per user and no limit; its row count must equal `enabledNoMfa`. The report flags a mismatch.
6. When `registrationKnown` is 0 the MFA figures are unknown, not "no MFA".
7. Different `scriptHash` values across days mean the query changed; say so before comparing days.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `Office365_Resource_Inventory_Report` (type `fpl_report`; source in
`references/Office365_Resource_Inventory_Report.js`; arguments `from=-1d@d`, `to=@d`). It reaches a tenant through the Scripts
repo release. Schedule it daily, UTC, archive enabled. Every scan runs through a `Run()` wrapper that catches a missing table,
so the same script deploys to tenants without Microsoft 365 data. The run takes about 15 seconds on a tenant with 2,700 users.
The archive holds the user lists, so it is personal data.
