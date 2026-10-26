---
name: fluency-report-rollup
version: 1.0.1
description: >-
  Build a weekly, monthly, quarterly or trend report for a Fluency / Ingext scheduled report
  from its archived daily runs instead of one long run. Each archived scheduled report runs
  once per day for exactly that day and the result is kept for 12 months, so a month or a
  quarter is assembled by merging dailies (sum counters by key, keep each time bucket once,
  recompute top-N and totals from the merged rows). Use when the user asks for a monthly,
  quarterly, month-over-month, week-over-week, last-90-days or year-to-date version of a
  scheduled report, a trend across months, or a report over a range longer than the report
  can run directly. Always starts with list_report_archive to check coverage, reports any
  missing days, and can backfill them with backfill_report_archive. Hands the merged result
  to fluency-report for the HTML page.
---

# Fluency / Ingext report rollup (month, quarter, trend)

A scheduled report with the **archive** turned on runs once a day for exactly the previous day
(in the archive's timezone, UTC by default) and keeps each day's result for **12 months**. A
longer report is then built from those dailies:

- it costs nothing to rebuild a month or a quarter, and no long query has to run;
- it works past limits the report itself enforces (many reports refuse ranges over 60 days,
  so a quarter can only be assembled);
- the same dailies give a trend: month over month, week over week, a per-day series.

The catch is that the dailies must be **merged the way the report computes its numbers**.
Summing the wrong column, or keeping a boundary time bucket twice, gives a confident wrong
number. This skill is mostly about getting the merge right.

## Tools

Tenant MCP (account name optional), or the grid MCP with an `account`:

| Tool | Use |
| --- | --- |
| `list_report_archive` | Which reports are archived; for one report, its days and a **coverage** summary |
| `download_report_archive` | One day, or a range of up to 92 days, as `days[]` of `{entry, result}` |
| `backfill_report_archive` | Run the report for past missing/aborted days (background, one at a time) |
| `processor_get` | The report's FPL script: read it to decide how each table merges |
| `run_report` | A direct run, to spot-check one assembled number on a short range |

If `list_report_archive` is not available, the tenant is on an older release; say so and stop.
If the report is not in the archived list, the archive is not enabled for it: tell the user an
Ingext admin has to enable it on the report's schedule. Dailies only exist from then on, unless
someone backfills them.

## Pipeline

```
1. list_report_archive                        which reports are archived
2. list_report_archive name, from, to         coverage of the requested range
   ├─ missing/aborted days → tell the user; offer backfill_report_archive
   └─ more than one scriptHash → warn: the script changed inside the range
3. processor_get name                         read the script → merge spec
4. download_report_archive name, from, to     ≤ 92 days per call, objects to trim
5. merge                                      scripts/rollup.py + the spec
6. spot-check one number with run_report on a short range (first time per report)
7. render with fluency-report (same objects[] shape), state coverage on the page
```

### 1–2. Pick the range and check coverage

Resolve the user's period to days in the report's archive timezone (`timezone` in the list
answer), both ends included: "September" → `2026-09-01` .. `2026-09-30`; "Q3" → `07-01` ..
`09-30`; "last 90 days" → the 90 days ending yesterday. Today is never in the archive; it is
written after the day ends.

Call `list_report_archive` with `name`, `from`, `to`. Read `coverage`:

- `completed == expected` → go on.
- `missingDays` / `abortedDays` → say which days, and either backfill them (step 2b) or build
  the report from what exists and **state the gap on the page** ("27 of 30 days; Sep 4–6
  missing"). Never scale a partial total up to a full month.
- `runningDays` → a run or backfill is in progress; wait and list again.
- more than one `scriptHashes` → the report script changed inside the range. Days before and
  after may not be comparable; say so, or backfill the old days with `force` to rerun them on
  the current script (only if the user agrees: it replaces those days).
- more than one `timezones` → the archive timezone changed inside the range (a tenant moved
  from UTC to its local zone, say). Days before the change keep their old day boundaries, so
  a few hours around the change are missing or counted twice. Say so on the page with the
  date of the change; the per-day series is off on that day only.

### 2b. Backfill

`backfill_report_archive` with `name` and `day`, or `from`/`to` (≤ 92 days, all before today).
Completed days are skipped unless `force`. It returns at once with `queued` and `skipped`; the
days run one after another in the background, about one report run each. Poll
`list_report_archive` (the `backfill` field shows `done`, `failed`, `current`) until it is gone,
then re-check coverage. Only one backfill runs at a time per account.

Backfilled days are only as good as the data still there: a day whose source data has aged
out of the datalake comes back empty, not missing. Flag days whose `total` is far below their
neighbours.

### 3. Decide the merge from the script

Get the script with `processor_get` and, for **every** table the report returns, decide how
dailies combine. [references/merge_rules.md](references/merge_rules.md) has the modes, the
traps, and how to recognise each in FPL. The short version:

| The table holds | Merge |
| --- | --- |
| counters per key (count, bytes, events) | **sum** by key |
| a time series (per hour / per day rows) | **timebucket**: keep each bucket once, roll up |
| a top-N of something | **top**: re-rank the merged keyed table, never merge the daily top-Ns |
| totals over another table | **aggregate**: recompute from the merged table |
| a count of distinct things | **distinct** over the merged keyed table, never a sum |
| a ratio, percentage, average | recompute from the summed numerator and denominator |
| a max / min / latest value | **max** / **min** / **last** |
| a snapshot (inventory, current state) | **last**: take the newest day |

If a table can't be merged correctly from what the dailies contain (a median, a distinct count
with no per-key table behind it, a percentile), say so: leave it out or show it per day. Don't
approximate it silently.

Write the decisions as a spec (see
[references/example_spec_System_Event_Ingress_Report.json](references/example_spec_System_Event_Ingress_Report.json)).

### 4. Download

`download_report_archive` with `name`, `from`, `to`. One call returns at most 92 days and 4 MB.

- Pass `objects` to keep only the tables the spec merges. Drop tables you recompute
  (top-N, totals): they only add bytes.
- **Don't pass `limit` for tables you sum.** `limit` keeps the first rows of each day, and a key
  outside them on some day would be summed short. Use `limit` only to peek at a shape.
- Too large → split the range (a month per call) and pass every file to the merge; days are
  de-duplicated by their start.
- Save each response to a file if you can run code, so the merge runs on the full data, not on
  what you can hold in context.

### 5. Merge

```
python3 scripts/rollup.py --spec spec.json --out rolled.json part1.json [part2.json ...]
```

It skips non-completed days, keeps each day once, applies the spec table by table, and writes
`objects[]` in the same shape a report run returns. It also records the days, script hashes and
coverage it used, plus notes such as how many boundary buckets it dropped. Without code
execution, apply the same rules by hand and show your working for the headline numbers.

### 6. Spot-check (first time for a report)

Run the report directly with `run_report` (`syncMode: true`) over a short range the archive
covers, e.g. the last 7 full days with RFC 3339 `from`/`to` at the day boundaries. Compare one
keyed total and the grand total. Small differences (well under 1%) come from metric
extrapolation at window edges and are expected. Differences of a whole bucket (about 1/24 for
hourly data) mean the time-series merge is double-counting a boundary bucket. Differences
whose size changes with the number of days mean the merge mode is wrong.

### 7. Render

Hand `rolled.json` to **fluency-report**: it reads the same `objects[]` shape. Put on the page:

- the period and the timezone of its day boundaries;
- coverage: days included out of days in the period, and any gaps by date;
- that it was assembled from daily runs, and whether the script changed inside the period.

For a trend, merge each period separately (each month, or each week) with the same spec, then
compare the per-period results. Comparing periods with different coverage is misleading
unless you say so.

## Rules

- Always list and check coverage first. Never present an assembled period as complete when
  coverage says it isn't.
- Never invent days, extrapolate missing days, or average daily percentages.
- Backfill only when the user wants it; a forced backfill replaces existing days.
- The archive's days are in the archive timezone. Say which on the page when it isn't UTC.
