---
name: fpl-report-dashboard
version: 1.0.0
description: >-
  Build, test, deploy and release an Ingext / Fluency dashboard report: an fpl_report
  processor whose script returns named tables and metric streams, plus a reportConfig of
  panels (text, counter, table, topn, metric line charts, sparkLine, pie) and a grid layout
  that the platform UI renders. Use when the user wants to create, add, build or fix a
  dashboard, a report with charts, a metrics dashboard, a panel or layout, or report
  arguments; when a report's charts show all zeros; or when a report must be deployed with
  its layout to a tenant and released through the Scripts repo. Covers Platform_Metric_Query
  and QueryRange data sources, chart range alignment, FPL pitfalls in report code, testing
  with processor test and run_report, deploying a test copy with its reportConfig, and the
  release. Not for writing KQL-only report source (fpl-report-builder) or turning an
  existing report's output into an HTML summary (fluency-report).
---

# FPL dashboard report

A dashboard is an **`fpl_report` processor**: a script whose `main()` returns an object of
named tables and metric streams, plus a meta entry whose `reportConfig` binds each panel to
one of those names and lays the panels out on a grid. The UI runs the script with the
report's `arguments` and renders the panels.

```
fplProcessors/code/<Name>.js     main({from, to, interval}) -> {hosts, cpu, ...}
fplProcessors/meta/<Name>.json   type fpl_report, arguments[], reportConfig{panels[], layout[]}
```

Worked example: `assets/WinHost_Health_Report.js` + `assets/WinHost_Health_Report.json`
(host status tables, two counters, seven metric line charts over `winhost_*` gauges).

## When to defer

- KQL-only report source compiled from queries → **fpl-report-builder**.
- Run an existing report and render an HTML summary → **fluency-report**.
- PromQL exploration before you write the report → **ingext-promql**.
- Metrics a parser or channel rule must first produce → **deploy-fpl-processor** /
  **parser-rule**; check the series exist (`prom_query`) before building panels on them.

## 1. Data sources inside the script

| Call | Returns | Feeds |
| --- | --- | --- |
| `Platform_Metric_Query(promql, t)` | table: one row per series, label columns + `_value`, `_timestamp` | table, counter, topn |
| `Platform_Metric_QueryRange(promql, from, to, interval)` | metric stream (one line per series) | `metric` (line), `sparkLine` |
| `Platform_Metric_QueryBuild({...})` | a PromQL string | either of the above |
| `Platform_Metric_Sort` / `Sort_Histogram` | topk table / its stream | topn / metric |
| `jsonTable(list)` | table from your own objects | table, counter |

Times use FPL syntax: `"@m"`, `"-6h@m"`, `"-24h@h"`, or absolute RFC3339 /
`20060102_150405` (UTC). `"now"` and `"@5m"` are **invalid**.

Status tables usually read several instant queries and merge them per key. Collect each into
a map, then build rows and `jsonTable(rows)` — simpler and safer than chained `Join`:

```js
function valueMap(query, to, labels) {
    let m = {}
    Platform_Metric_Query(query, to).Each((row) => {
        let parts = []
        for _, l = range labels { parts = append(parts, toString(row[l])) }
        m[parts.Join(" ")] = row._value
    })
    return m
}
```

Leave a missing value **undefined** (the cell renders empty); a `null` prints as `"null"`.

## 2. Metric charts must use an aligned range — or every chart reads zero

The platform lays out a stream's slots counting back from `to`. VictoriaMetrics rounds a
range query of 50+ points to multiples of the step. Unless both ends sit on that grid no
point lands in a slot: **all charts show 0** (flags 0), while short test windows (<50 points)
look fine. Snap the chart window in the script — `assets/WinHost_Health_Report.js`
`alignedRange()`:

```js
function alignedSeconds(t, step) {
    let box = {sec: 0}                       // a lambda cannot assign an outer variable
    Platform_Metric_Query(`time()`, t).Each((row) => { box.sec = row._value })
    return Math.floor(box.sec / step) * step
}
// new Time() needs an integer: parseInt(sprintf("%.0f", seconds * 1000))
```

Status tables keep the real `to`; only the `QueryRange` calls get the snapped window.

Legends: a range result's keys look like `["HOST01"]`. `stream.ReplaceKey({'["X"]': "X"})`
shows the bare value; build the map from **every** key that can appear in the range (e.g.
`last_over_time(...[24h])`), or an expired series loses its name. For two labels, make one
label first: `max by (series) (label_join(m, "series", " ", "host", "drive"))`.

## 3. Panels and layout

`reportConfig.panels[]`: `{key, dataTable, title, panelType, panelConfig}` plus the empty
`table/histogram/topn/chart/pie/geoMap/counter` objects every existing report carries.
`dataTable` names a key of the object `main()` returns. `layout[]`: `{id: <panel key>, x, y,
width, height}` on a **16-column** grid. Panel JSON for each type, and a layout sketch, are in
`references/panels.md`. Every panel key must appear in `layout` exactly once.

`arguments[]`: `{name, defaultValue, optional: true, type: "string"}` for each parameter of
`main()`; keep the script defaults and the meta defaults identical. On add and update the
platform recomputes `arguments` from the parameters `main()` declares, so the script's
defaults are what actually ship — change them there, not only in the meta.

## 4. FPL pitfalls that bite report code

- `Math.round` / `Math.floor` (capital M). There is no `math.Round`.
- `parseInt` takes a string; for a float use `parseInt(sprintf("%.0f", x))`.
  `toString(5.0)` is `"5.000000"` — format with `sprintf("%.0f/%d", a, b)`.
- Lambdas cannot assign outer variables; write through a map.
- Only `function` declarations at top level; return constants from a function.
- Avoid regex label matchers (`=~`) in queries until verified on the tenant: through the MCP
  query path they return nothing.
- Every builtin the script calls must exist in **both** the tenant's api validator (saving
  fails `unknown function`) and its platform runtime. A new builtin ships in the platform
  family and the api pair (e.g. `Platform_Metric_Gauge`: platform 9.0.7 + api 9.12.34).

## 5. Workflow

1. **Draft in the Scripts repo** under `pending/fplProcessors/{code,meta}/` with an id from
   `scripts_repo.py next-id fplProcessor` (reports are fplProcessor entries, 720xxx), and a
   row in `pending/README.md` (see scripts-repo-workflow).
2. **Test the logic** with `processor test` on the tenant (it runs on platform-0 with the
   real API set). `main` takes `{obj}` there, so test a wrapper that renames your entry point
   and `printf`s each returned table. Metric writes in a test are real — use fake labels.
3. **Deploy a test copy** `<Name>_test` (id 0) **with its reportConfig and arguments**.
   `ingext processor add` cannot carry them. Use the MCP `processor_add` tool (needs
   `confirm: true`) where available; otherwise `assets/deploy_report.py`, which posts the
   entry to `platform_processor_dao`. Update with the same tool (`update`).
4. **Run it** with MCP `run_report` (sync) at its **defaults** and at a window of 50+ points
   (6h at 5m). Check each table's rows and that each stream has `flags` 1 where data exists.
   Then open it in the UI — the run proves the data, not the rendering.
5. **Release**: promote out of `pending/`, commit explicit paths, `scripts_repo.py check`,
   `preview fplProcessor` (only your entries, or ask), `sync_cli release ... fplProcessor`,
   commit `release`, push `branch/saas`. Confirm the dump entry kept `reportConfig` and
   `arguments`.
6. **After the sync**, compare the tenant's copy with the repo (`processor_get` / `list_reports`)
   and delete `<Name>_test`. A forced sync (restarting the tenant's `gitsync-0`) only helps after
   the cluster mirror logs `advanced to <sha>`, about 5 minutes after the push.

## Checklist

- [ ] Every `dataTable` is a key `main()` returns; every panel key is in `layout` once.
- [ ] Script defaults == meta `arguments` defaults.
- [ ] Charts tested at 50+ points with the aligned range; legends show bare names.
- [ ] Missing values left undefined, not null.
- [ ] Builtins available on the target tenant's api and platform versions.
- [ ] Release preview shows only this report (and anything the user approved).
- [ ] Test copy deleted after the released version is confirmed on the tenant.
