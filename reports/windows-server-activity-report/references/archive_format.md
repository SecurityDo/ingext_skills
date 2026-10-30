# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}` (a range download also has a top-level `coverage`).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day), `completedOn`,
  `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` has five objects. Tables are `{name, table: {rowCount, columns[], rows[]}}`; `rows[]` holds one
  object per row keyed by column name. An empty table has no columns and no rows. A zero count can be absent or null:
  treat it as 0.

| Object | One row per | Columns |
|---|---|---|
| `win_trend` | day | Date, events, bytes, hosts, logonsOk, logonsFailed, rdpLogons, networkLogons, explicitCreds, kerberosFailures, ntlmFailures, lockouts, privLogons, accountCreated, accountEnabled, accountDisabled, accountDeleted, passwordChanges, groupAdds, servicesInstalled, tasksCreated, auditPolicyChanges, logsCleared, processCreations, powershellScripts |
| `win_facets` | (see below) | one table per facet: `<facet>` value and `count_` |
| `win_failed_source` | source address (top 100) | Date, remip, failures, usernames, hosts, firstSeen, lastSeen, pattern |
| `win_ingest` | host x event ID (top 300) | Date, host, eventId, events, bytes, description, eventName |
| `sources` | scan | source, status (`ok` or `not available`), detail (error text) |

`win_facets` is not an FplTable: it is `value.orderedMap{keys, values}`. `keys[0]` is `PrimaryResult` (empty); every
other key is a facet and `values[i].sx.rows` holds `{<facet>: value, count_: n}`. The engine returns at most 100
values per facet. Facets: host, eventId, logonType, failedReason, failedUser, failedIp, logonUser, privAccount,
acctEvent, acctActor, acctTarget, groupName, groupActor, persistItem, tamperEvent, tamperHost, tamperActor. Subset
facets (all except host and eventId) label an event outside their subset `(none)`; the builder drops `(none)`.
Facet pairs are not kept: acctActor and acctTarget are separate lists. The `sources` table has one row per scan and
a row "event ID names (AD_EventID lookup)".

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. `win_trend`: add each metric across days; the sum is the period total. `hosts` is the peak day.
3. `win_facets`: add counts by value across days, drop `(none)`.
4. `win_failed_source`: add failures by address; usernames and hosts are the peak day; firstSeen the earliest, lastSeen the latest; the pattern is recomputed from the merged figures.
5. `win_ingest`: add events and bytes by (host, eventId); host and event ID totals come from these sums. The events missing from the top-300 pairs are the trend events minus the pair events.
6. A day with no completed run is a gap, listed with its state, never counted as zero.
7. A day whose `sources` rows say "not available" contributes nothing to that scan (not a zero).
8. Different `scriptHash` values across days mean the query changed; say so before comparing days.
9. Windows are half-open (`from <= timestamp < to`), so back-to-back days never double count.
10. Top-100 lists are a lower bound for a value outside a day's top 100.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `WindowsSrv_Activity_Report` (type `fpl_report`, group AD; source in the
Scripts repo `fplProcessors/code/WindowsSrv_Activity_Report.js` and in `references/WindowsSrv_Activity_Report.js`;
arguments `from=-1d@d`, `to=@d`, `interval=1d`). It reaches a tenant through the Scripts repo release. Schedule it daily, UTC,
archive enabled, then `backfill_report_archive` for earlier days. Every scan runs through a `Run()` wrapper that catches
a missing WindowsAudit table, so the same script deploys unchanged to tenants without Windows data. Schedule at the
same time as the tenant's other daily reports so the runs are spread out. A day takes about 4 to 5 minutes on a tenant
with 700,000 events a day; changing a schedule time never runs the report by itself.
