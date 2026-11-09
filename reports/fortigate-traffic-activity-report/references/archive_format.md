# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}` (a range download also has a top-level `coverage`).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day), `completedOn`,
  `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` has three FplTable objects `{name, table: {rowCount, columns[], rows[]}}`. `rows[]` holds one
  object per row keyed by column name. An empty table has no columns and no rows. A zero count can be absent or null:
  treat it as 0.

| Object | One row per | Columns |
|---|---|---|
| `traffic_dims` | dimension value x outcome (a few hundred rows a day) | dim, val, outcome, events, bytesOut, bytesIn |
| `traffic_talkers` | internal host (top 100 by bytes sent) | source, host, events, blocked, bytesOut, bytesIn |
| `sources` | scan | source, status (`ok` or `not available`), detail (error text) |

`traffic_dims` holds every breakdown in one table so the processor needs one scan of the traffic table: a record is
counted once per dimension (the `dim` column), so each dimension sums to the same total and a dimension's size is added
to the others instead of multiplied by them. `val` holds the value; a dimension of several fields joins them with
" | " and the reader splits them again:

| dim | val | Covers |
|---|---|---|
| `device` | device \| interval start | every event; the sum over rows is the run total (the trend) |
| `genaiDevice` | device \| interval start | GenAI events only |
| `app` | application \| category | every event |
| `service` | service | every event |
| `country` | destination country | every event |
| `policy` | policy id | every event |
| `genaiApp` | application \| category | GenAI events |
| `genaiPolicy` | policy id \| application | GenAI events |
| `genaiSource` | source address \| host \| application | GenAI events |
| `genaiDestination` | destination address \| country \| application | GenAI events |

An application or service named `tcp/<port>` or `udp/<port>` (one the firewall could not name) is collapsed to
"(unnamed tcp port)" or "(unnamed udp port)", because there are tens of thousands of them on a busy firewall and the
engine returns at most 8124 rows. The scan ends with `top 8000` as a guard: a day whose `traffic_dims` has 8000 rows
was truncated and the builder says so.

Definitions: `events` is a log record, not a session. `bytesOut` is client to server and `bytesIn` server to client,
both per-record deltas (`_fields.sentdelta` / `_fields.rcvddelta`) with the cumulative `sentbyte` / `rcvdbyte` only as
a fallback for a record without a delta. `outcome` is `blocked` for firewall action deny and `allowed` for every other
action. A session is GenAI when Application Control gives it the category GenAI or its application name matches the
list in the processor.

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. The `device` and `genaiDevice` rows are the trend: add them across days (and across devices within a day); the sum
   is the period total. Blocked events are the rows with outcome `blocked`. The device view is the same rows summed by
   device.
3. Every other dimension: add the count and byte columns by key across days. There are no distinct counts in this
   report, because hosts and addresses cannot be added across days.
4. A day with no completed run is a gap, listed with its state, never counted as zero.
5. A day whose `sources` rows say "not available" contributes nothing to that scan (not a zero).
6. Different `scriptHash` values across days mean the query changed; say so before comparing days.
7. Windows are half-open (`from <= timestamp < to`), so back-to-back days never double count.
8. Top-N tables are a lower bound for a row outside a day's top N.
9. Application-name coverage is the share of `app` events whose application is not "(not recorded)". Below
   70% the GenAI view is flagged as a lower bound.

The script hash of the deployed processor is recorded by the platform on the first archived day; note it when the
first archive is read.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `Fortigate_Traffic_Activity_Report` (type `fpl_report`; source in
`references/Fortigate_Traffic_Activity_Report.js`; arguments `from=-1d@d`, `to=@d`, `interval=1d`). Create it with
`processor_add` (group Fortigate) and `create_scheduled_report` (schedule daily, UTC, archive enabled), then
`backfill_report_archive` for earlier days. Every scan runs through a `Run()` wrapper that catches a missing
NetworkFortigateTraffic table, so the same script deploys unchanged to tenants without FortiGate data. The processor
runs two scans of the traffic table (the grouped dimensions and the top senders), still the heaviest of the FortiGate
reports: schedule it away from the tenant's other daily reports, and run a first day by hand before backfilling a long range. Changing a schedule time never runs the
report by itself; the next run is the next occurrence of the new time.
