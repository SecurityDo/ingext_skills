# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}` (a range download also has a top-level `coverage`).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day), `completedOn`,
  `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` has eleven FplTable objects `{name, table: {rowCount, columns[], rows[]}}`. `rows[]` holds one
  object per row keyed by column name. An empty table has no columns and no rows. A zero count can be absent or null:
  treat it as 0.

| Object | One row per | Columns |
|---|---|---|
| `fg_trend` | day | Date, failedLogins, sessionExpiries, sslSessions, ipsecTunnelsUp, ipsecTunnelsDown, appCtrlBlocks, webFilterBlocks, ipsAnomalies, adminLogins, adminLoginsFailed, adminConfigChanges |
| `fg_totals` | run | failedLogins, sources, sslSessions, blocked, ipsAnomalies, adminChanges, adminLoginsFailed, ipsecUp, ipsecDown (not used by the builder; it recomputes from fg_trend) |
| `fg_failed_device` | device | Date, device, failures, sources, countries, usernames, firstSeen, lastSeen |
| `fg_failed_country` | country | Date, country, failures, sources, usernames |
| `fg_failed_source` | source address (top 100) | Date, remip, failures, usernames, country, device, firstSeen, lastSeen, pattern |
| `fg_failed_user` | user (top 100) | Date, user, failures, sources, countries, devices, firstSeen, lastSeen |
| `fg_vpn_user` | user (top 100) | Date, user, sessions, sources, countries, devices, firstSeen, lastSeen |
| `fg_anomaly` | attack x severity | Date, attack, severity, events, sources, firstSeen, lastSeen |
| `fg_admin` | admin (top 100) | Date, admin, loginsOk, loginsFailed, changes, lastSeen |
| `fg_blocked` | control x item (top 100) | Date, control, item, blocks, hosts |
| `sources` | scan | source, status (`ok` or `not available`), detail (error text) |

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. `fg_trend`: add each metric across days; the sum is the period total.
3. Per-entity tables: add the count columns by key across days. Distinct columns (sources, usernames, countries,
   devices, hosts) are exact for one day and one row only: report the peak day, never the sum.
4. firstSeen is the earliest and lastSeen the latest across days.
5. A day with no completed run is a gap, listed with its state, never counted as zero.
6. A day whose `sources` rows say "not available" contributes nothing to that scan (not a zero).
7. Different `scriptHash` values across days mean the query changed; say so before comparing days.
8. Windows are half-open (`from <= timestamp < to`), so back-to-back days never double count.
9. Top-100 tables are a lower bound for an entity outside a day's top 100.

Known script hash: `b965b344949125ef` (the version in `references/Fortigate_Security_Activity_Report.js`).

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `Fortigate_Security_Activity_Report` (type `fpl_report`; source in
`references/Fortigate_Security_Activity_Report.js`; arguments `from=-1d@d`, `to=@d`, `interval=1d`). Create it with
`processor_add` (group Fortigate) and `create_scheduled_report` (schedule daily, UTC, archive enabled), then
`backfill_report_archive` for earlier days. Every scan runs through a `Run()` wrapper that catches a missing
NetworkFortigateEvent table, so the same script deploys unchanged to tenants without FortiGate data. Schedule at the
same time as the tenant's other daily reports so the runs are spread out: a day is run a few hours after it ends.
Changing a schedule time never runs the report by itself; the next run is the next occurrence of the new time.
