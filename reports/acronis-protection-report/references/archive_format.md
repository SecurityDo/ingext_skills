# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}`. A range download also has a top-level `coverage`
(firstDay, lastDay, expected, completed, aborted, running, missing, scriptHashes, timezones).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day, `T00:00:00Z` to the next), `createdOn`,
  `completedOn`, `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` is a list of `{name, table}`; `table.rows[]` holds the rows. Zero counts can arrive as null or absent:
  treat them as 0.

| Table | Kind | Key | Merge |
|---|---|---|---|
| `acr_trend` | counter | Date | sum events, alertEvents, activityEvents, incidentEvents |
| `acr_alerts` | keyed | alertId | sum events and resolved; firstSeen min, lastSeen max; category, alertType, severity, device, planName from the latest day |
| `acr_incidents` | keyed | shortId + host | sum events; lastUpdate max; state, mitigation, severity from the latest day; transferredTo if any |
| `acr_edr_triggers` | keyed | incident + device | lastSeen max; detection min; mitigation and trigger from the latest day |
| `acr_activities` | counter | activityType | sum runs, ok, notOk |
| `acr_update_failures` | keyed | agentId + unit + activityType | sum failed; lastFailure max; errorCode from the latest day |
| `acr_backup` | counter | device + plan | sum runs, ok, failed, gbProcessed; lastRun max; union of error codes (5) |
| `acr_agent_summary`, `acr_defs_age`, `acr_versions`, `acr_units`, `acr_stale_agents`, `acr_duplicates`, `acr_no_active_protection`, `acr_tenants` | snapshot | - | read ONE day (the latest scheduled one); every row carries `asOf` |
| `sources` | status | source | every row must be `ok`, or the day is not used |

Caps per day: `acr_alerts` 3000 rows, `acr_edr_triggers` 500, `acr_update_failures` 1000, `acr_backup` 1000, `acr_stale_agents` 300,
`acr_activities` 100. A day over a cap is clipped; none has been near one on the first tenant.

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. Counters: add across days. Keyed tables: merge by key. Snapshot tables: one day, never added.
3. A day with no completed run is a gap, listed with its state, never counted as zero.
4. Different `scriptHash` values across days mean the query changed; say so before comparing days.
5. Half-open daily windows (`timestamp >= from and timestamp < to`) mean back-to-back days never double count events. Acronis
   re-sends alerts and activities, so alert and activity runs seen on two days are counted once per key (alerts, incidents,
   failures) or once per day (activities, which therefore overstate slightly at each day boundary).
6. A snapshot is the inventory when that day was run. A scheduled run (04:00 UTC, so within 8 hours of the day's end) is a true
   end-of-day snapshot; a backfilled day reads today's inventory.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `Acronis_Protection_Report` (type `fpl_report`; arguments `from=-1d@d`, `to=@d`,
`interval=1d`), scheduled daily at 04:00 UTC with the archive enabled in UTC, so a day is run a few hours after it ends and
late-arriving events are included. Its script is `Acronis_Protection_Report.js` in this folder.

1. `processor_add(account, name="Acronis_Protection_Report", type="fpl_report", scriptText=<the script>, arguments=[from, to,
   interval], confirm=true)`. This is tenant-local: no registry id and no git sync. To release it to other tenants instead, give
   it an id from the registries and release with `sync_cli` (see `deploy-fpl-processor`).
2. `create_scheduled_report(account, processorName="Acronis_Protection_Report", schedule={interval:"daily", hour:4, minute:0,
   timezone:"UTC"}, scheduleEnabled=true, archive={enabled:true, timezone:"UTC", argFrom:"from", argTo:"to"})`.
3. `backfill_report_archive(account, name, from, to)` for earlier days (event tables only are historical; see snapshot tables in
   SKILL.md).

The tenant needs the AcronisCP connector (`Acronis` index plus the `acronisAgent` and `acronisTenant` resource tables). Without it
the report returns empty tables and every source reads "not available".
