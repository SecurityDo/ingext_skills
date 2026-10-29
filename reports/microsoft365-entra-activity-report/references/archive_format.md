# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}`. A range download also has a top-level
`coverage` (firstDay, lastDay, expected, completed, aborted, running, missing, scriptHashes, timezones).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day, `T00:00:00Z` to the next),
  `completedOn`, `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` has eleven objects: for each source `<s>_trend` and `<s>_facets`, plus `sources`.

| Source key | Table | Trend metrics (one row per day) |
|---|---|---|
| `o365` | Office365 | events, failedOps, adminOps, loginsOk, loginsFailed, mailItemsAccessed, mailSent, hardDeletes, inboxRuleChanges, mailboxPermissionChanges, sharingEvents, externalAccess, adminConfigChanges, securityAlerts, dlpEvents, copilotEvents |
| `signin` | AzureSigninLogs | events, failed, interactive, mfaRequired, singleFactorOk, caFailures, risky, guests, legacyAuth |
| `audit` | AzureAuditLogs | events, failed, userChanges, groupChanges, roleChanges, appChanges, policyChanges, adds, updates, deletes, passwordEvents |
| `sp` | AADServicePrincipalSignInLogs | events, failed, secretErrors, secretAuth, assertionAuth |
| `ni` | AADNonInteractiveUserSignInLogs | events, failed, guests |

- `<s>_trend`: `table.rows[]` with `Date` and the metrics. A zero count can arrive as null or absent: treat it as 0.
  An empty table (no rows, no columns) means no events or no table; the `sources` table says which.
- `<s>_facets`: `value.orderedMap{keys, values}`. `keys[0]` is `PrimaryResult` (empty); every other key is a
  facet and `values[i].sx.rows` holds `{<facet>: value, count_: n}`. "Full" facets cover every event
  (`(not recorded)` when empty); "subset" facets (`adminOp`, `sensitiveOp`, `failedOp`, `failedCode`,
  `failedActivity`) label the complement `(none)`. The facet lists are in `scripts/build_report.py` (SOURCES).
- `sources`: `table.rows[]` of `{source, status, detail}`, two rows per table (trend and facets). `status` is `ok`
  or `not available`; `detail` carries the error text ("table not found: <Name>"). An existing but empty table is
  `ok` with no rows.

The engine returns at most 100 values per facet. For full facets the report shows the lost tail as `(other)`
= trend events minus the facet total.

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. Trend: add each metric across days. The sum is the period total.
3. Facets: add counts by value across days. Drop `(none)` when showing a subset facet.
4. A day with no completed run is a gap, listed with its state, never counted as zero.
5. A day whose `sources` row for a table is "not available" contributes nothing to that source (not a zero);
   a day whose result lacks the source's objects was produced by an older script (not collected).
6. Different `scriptHash` values across days mean the query changed; say so before comparing days.
7. Half-open daily windows (`timestamp >= from and timestamp < to`) mean back-to-back days never double count.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `Office365_Entra_Activity_Report` (type `fpl_report`; source in
`references/Office365_Entra_Activity_Report.js`; arguments `from=-1d@d`, `to=@d`, `interval=1d`), scheduled daily
at 04:00 UTC with the archive enabled in UTC, so a day is run a few hours after it ends and late-arriving events
are included. Create it with `processor_add` and `create_scheduled_report` (schedule daily, hour 4, minute 0, UTC,
archive enabled), then `backfill_report_archive` for earlier days. Every scan runs through a `Run()` wrapper that
catches a table the tenant lacks, so the same script deploys unchanged to tenants with different Entra tables.
A large tenant can take minutes a day, longer than a synchronous `run_report` waits: launch with syncMode false.

## Actor facets (script version 3)

`o365_facets`: user, failedUser, failedIp, adminActor. `signin_facets`: user, failedUser, failedIp. `audit_facets`:
actor, failedActor. `sp_facets`: failedIp. `ni_facets`: failedUser, failedIp. user and actor cover every event, the rest
label events outside the subset "(none)". The engine keeps 100 values a facet a day. They hold personal data.
