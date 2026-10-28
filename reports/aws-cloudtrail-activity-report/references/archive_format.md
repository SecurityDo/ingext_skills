# Archive format and how it is merged

## What one archived day holds

`download_report_archive` returns `days[]` of `{entry, result}`. A range download also has a top-level
`coverage` (firstDay, lastDay, expected, completed, aborted, running, missing, scriptHashes, timezones).

- `entry`: `state` (completed, aborted, ...), `rangeFrom`, `rangeTo` (a UTC day, `T00:00:00Z` to the next),
  `completedOn`, `env.scriptHash`, `resultPath`. Only completed days carry a `result`.
- `result.objects[]` has two objects:
  - `trend`: `table.rows[]`, one row per interval (the schedule uses `1d`, so one row a day) with `Date`,
    `events`, `consoleLogins`, `failedLogins`, `iamChanges`, `rootEvents`, `errors`, `accessDenied`,
    `loginsNoMfa`, `trailChanges`. A zero count can arrive as null or absent: treat it as 0.
  - `facets`: `value.orderedMap{keys, values}`. `keys[0]` is `PrimaryResult` (empty); every other key is a
    facet and `values[i].sx.rows` holds `{<facet>: value, count_: n}`.

| Facet | Meaning | Covers |
|---|---|---|
| `source`, `region`, `identityType` | events by AWS service, region, identity type | every event; `(not recorded)` when empty |
| `errSource`, `errRegion`, `errCode` | errors by service, region, error code | errors; `(none)` = events without an error |
| `iamEvent` | IAM write events by event name | `(none)` = everything else |
| `rootEvent` | root-identity events by event name | `(none)` = everything else |
| `loginIdentity` | console logins by identity type | `(none)` = everything else |

The engine returns at most 100 values per facet, so a column with more distinct values (eventSource had 128 in a
day) loses its rarest ones. For `source`, `region` and `identityType` the report shows the lost tail as
`(other)` = trend events minus the facet total.

## Merge rules

1. One completed run per UTC day; if a day was archived twice, keep the latest `completedOn`.
2. Trend: add each metric across days. The sum is the period total.
3. Facets: add counts by value across days. Drop `(none)` when showing a subset facet.
4. A day with no completed run is a gap, listed with its state, never counted as zero.
5. Different `scriptHash` values across days mean the query changed; say so before comparing days.
6. Half-open daily windows (`timestamp >= from and timestamp < to`) mean back-to-back days never double count.

## Producing the archive (once per tenant)

The scheduled report is the FPL processor `CloudTrail_Activity_Report` (type `fpl_report`; arguments
`from=-1d@d`, `to=@d`, `interval=1d`), scheduled daily at 04:00 UTC with the archive enabled in UTC, so a day
is run a few hours after it ends and late-arriving events are included. It runs two scans per day: the trend
(`summarize ... by bin(timestamp, interval)`) and one `facet by` query that returns all breakdowns. Create it
with `processor_add` and `create_scheduled_report`, then `backfill_report_archive` for earlier days. The
queries are in `fpl-report-dashboard`'s CloudTrail example and in the repository's CloudTrail dashboard notes.
