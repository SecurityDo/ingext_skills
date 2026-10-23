# Merge rules: from dailies to a period

Every table a report returns needs one rule. Read the report's FPL script (`processor_get`) and
work out what each returned table *is*, then pick the mode below. The modes are the ones
`scripts/rollup.py` understands; the spec is `{"tables": {"tableName": {...}, ...}}`, and
tables are built in the order listed, so a `top` or `aggregate` must come after the table it
reads from.

## sum: counters per key

```json
"statsByEventType": {"mode": "sum", "key": "eventtype", "columns": ["totalSize", "eventCount"]}
```

The table has one row per key with additive numbers: counts, bytes, events, cost, alerts.
In FPL it comes from `Aggregate` with `groupBy` and `sum`/`count` columns, or a metric
`increase` / `sum` grouped by a label. Keys present on some days only are fine. Other columns
(labels such as `ProductName`) are carried from the newest day. `key` may be a list for a
multi-column key.

**Not additive** and must not use `sum`: `avg`, `percent`, `ratio`, `rate` (per second), `max`,
`min`, `dcount` / `count distinct`, `median`, `p95`, anything computed as `a / b`.

## timebucket: time series

```json
"totalStatsTimeTable": {"mode": "timebucket", "time": "Date", "format": "%Y/%m/%d %H:%M",
                        "step": "1h", "label": "end", "rollup": "1d",
                        "columns": ["totalSize", "eventCount"]}
```

Rows keyed by a timestamp: `TimeTable(...)`, `Platform_Metric_QueryRange(..., step)`, KQL
`bin(timestamp, 1h)`. Two traps, both seen on real data:

1. **The label is the bucket's end, not its start**, for metric range queries with `increase`:
   the row labelled `10/23 00:00` with a 1 h step holds 10/22 23:00–24:00. With a 1 d step, the
   row labelled `10/23` holds all of 10/22. Use `"label": "end"` for those, `"start"` for KQL
   `bin()` and similar.
2. **Each daily run also returns the bucket that straddles its start**, so a daily run of hourly
   data has 25 rows, not 24. Summing every row of every day counts one bucket per day twice:
   about +4% on hourly data. `timebucket` keeps a bucket only in the run whose day it starts in.

`step` is the bucket width in the dailies (a daily run usually gets hourly buckets). `rollup`
is what the period report shows: omit it to keep the original buckets, `"1d"` for one row per
day, `"1mo"` for one per month (a quarter's trend). Columns are summed within a rolled-up
bucket, so a rate or gauge column must not be in `columns`.

To tell which label a report uses, look at one daily: if its first row is the day's start and
it has one row more than the day has buckets, the labels are bucket ends.

## top: re-rank

```json
"topSizeByEventType": {"mode": "top", "from": "statsByEventType", "by": "totalSize", "n": 10}
```

The script's `Sort(n, "col")` / `top n by` on another table. Rebuild from the merged keyed
table. Merging the daily top-10s is wrong: a key ranked 11th every day can be first for the
month. `"ascending": true` for a bottom-N (`Sort(n, "+col")`).

## aggregate: totals over a merged table

```json
"totalStats": {"mode": "aggregate", "from": "statsByEventType",
               "columns": {"totalIngressSize": ["sum", "totalSize"], "totalEventTypes": ["count"]}}
```

A one-row table computed from another table (`Aggregate` with no `groupBy`). Recompute it from
the merged table:

| op | meaning |
| --- | --- |
| `["sum", "col"]` | sum of a column |
| `["count"]` | number of rows, i.e. distinct keys over the whole period |
| `["distinct", "col"]` | distinct values of a column |
| `["max", "col"]`, `["min", "col"]` | extremes |

`count` on a merged keyed table is the right distinct count for the period: six event types
on each of 30 days is six for the month, not 180.

## max / min / last

```json
"peakDay":   {"mode": "max",  "key": "host", "columns": ["peakEps"]},
"inventory": {"mode": "last", "key": "deviceId"}
```

`max` / `min` per key for peaks and lows. `last` keeps the newest day's row per key, for
snapshots and current-state tables (asset lists, configuration, open incidents).

## concat / drop

`concat` appends every day's rows unchanged (event lists, alerts with their own timestamps).
Watch the 4 MB download bound. `drop` leaves a table out; say on the page why it is missing.

## What cannot be merged

- **Ratios and percentages**: recompute from summed parts. If the dailies only carry the
  ratio, the period ratio can't be rebuilt; show it per day.
- **Distinct counts without a per-key table** (for example only `dcount(user)` per day):
  the period's distinct count is not recoverable. Say so, or change the report to also return
  the per-key table.
- **Medians and percentiles**: not mergeable from per-day values.
- **Averages**: only from a summed total and a summed count, never by averaging daily averages.

Whenever a table falls in this list, tell the user and suggest the report change that would
make it mergeable (return the numerator and denominator, or the per-key rows).

## Worked check: System_Event_Ingress_Report on titan (2026-10-23)

The report sums `platform_egress_bytes` / `platform_egress_count` (metric `increase`) by
destination, event type and product, plus an hourly (daily for ranges over 48 h) time table.
It refuses ranges over 60 days. The spec is in `example_spec_System_Event_Ingress_Report.json`.

30 dailies (2026-09-23 .. 2026-10-22, UTC) assembled against one direct run over the same
30 days:

| Table | Assembled vs direct |
| --- | --- |
| statsByDestination, statsByEventType, statsByProductName | same keys; worst key 0.015%, all within 0.02% |
| totalStats | total 14,811,590,885 vs 14,811,615,349 (−0.0002%); 6 event types both |
| totalStatsTimeTable, 30 days | worst day 0.0006%, after dropping 30 boundary buckets and reading labels as bucket ends |
| topSizeByEventType, topSizeByProductName | identical order |

Before the two time-series fixes the per-day series was off by +4% every day (the duplicated
boundary bucket) and shifted by a day (labels read as starts). The keyed totals were right
from the start. The remaining small differences come from metric extrapolation at window
edges. They are expected, and they shrink as the period grows.
