# Panel cookbook

Every panel below is copied from a report that renders in the UI today (source in brackets).
Wrap each in the common envelope:

```json
{
  "key": "<unique id, also used in layout>",
  "dataTable": "<key returned by main()>",
  "title": "<panel title>",
  "panelType": "<type>",
  "table": {"columns": []}, "histogram": {}, "topn": {}, "chart": {}, "pie": {},
  "geoMap": {"ipColumn": "", "valueColumn": ""}, "counter": {"field": ""},
  "panelConfig": { ... }
}
```

The `table` … `counter` objects stay empty; the panel reads `panelConfig`.

## text — heading or explanation (no dataTable)

```json
"panelType": "text",
"panelConfig": {"text": "<p><strong class=\"ql-size-large\">Windows Host Health</strong></p><p>What the page shows.</p>"}
```
[WinHost_Health_Report, Datalake_Metrics_Report]. Omit `dataTable`/`title` (they store as null).

## counter — one number

```json
"panelType": "counter",
"panelConfig": {"field": "_value", "format": "default"}
```
`format`: `default`, `comma`, `Readable Numbers`, `Data` (bytes), `comma_data`. The table's
first row is used; for a PromQL count that can be empty, add `or vector(0)`.
[WinHost_Health_Report, System_DataIngress]

## table

```json
"panelType": "table",
"panelConfig": {"columns": [
  {"field": "host", "header": "Host", "dateTimeFormat": "default", "alignment": ""},
  {"field": "cpuPct", "header": "CPU %", "dateTimeFormat": "default", "alignment": ""}
]}
```
Only listed columns show, in this order. [WinHost_Health_Report, Datalake_Metrics_Report]

## metric — line chart of a metric stream

```json
"panelType": "metric",
"panelConfig": {"chart": "line", "dateFormats": "HH:mm"}
```
`dataTable` must be a `Platform_Metric_QueryRange` / `Sort_Histogram` result — with an
**aligned range** (SKILL.md section 2). [WinHost_Health_Report, Platform_Component_Summary_inline]

## sparkLine — total with a small trend line

```json
"panelType": "sparkLine",
"panelConfig": {"angle": "bidirectional", "metrics": "complex", "ascend": "#00a300",
                "descend": "#d60000", "showline": true, "unit": "bytes"}
```
Fed by a single-series `QueryRange`. [Platform_Component_Summary_inline]

## topn — ranked bars from a table

```json
"panelType": "topn",
"panelConfig": {
  "categories": {"focus": {"name": "total", "isVariable": true, "label": "total", "field": "total"}, "format": "default"},
  "value": {"column": {"name": "city", "isVariable": true, "label": "city", "field": "city", "align": "left"}, "format": "default"},
  "options": {"legend": false}
}
```
`focus` is the numeric column, `value.column` the label column. [AzureAD_Login_Statistics]

## pie

Same `panelConfig` shape as topn. [AzureAD_Login_Statistics]

## histogram — line/bar over a table with a time column

```json
"panelType": "histogram",
"panelConfig": {"categories": {"focus": [{"name": "eventCount"}]}, "value": {"column": {"name": "Date"}},
                "options": {"type": "line"}, "allColumns": false}
```
[AdminSummaryReport]

## stackChart

```json
"panelType": "stackChart",
"panelConfig": {"categories": {"focus": {"name": "count"}, "type": {"name": "level"}}, "value": {"column": {"name": "dayIndex"}}}
```
[Behavior_Alerts_Summary_Report]

## Layout

`layout[]` entries `{"id": "<panel key>", "x": 0, "y": 0, "width": 8, "height": 3}` on a
**16-column** grid; `y` grows downward in rows. A typical page:

```
y0  h3   text (w8)            | counter (w4)  | counter (w4)
y3  h5   status table (w16)
y8  h6   table (w10)                          | table (w6)
y14 h6   metric (w8)                          | metric (w8)
y20 h6   metric (w8)                          | metric (w8)
```
