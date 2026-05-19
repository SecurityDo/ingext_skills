# KQL syntax cheat sheet

KQL (Kusto Query Language) reads top-to-bottom, piped through `|`.

## Shape of a query

```
<TableName>
| where <condition>
| extend <newCol> = <expr>
| summarize <agg>... by <col>...
| project <col>, <col>, ...
| order by <col> [asc|desc]
| top <N> by <col> [asc|desc]
```

Start with a table name. Each `|` takes the previous stage's rows as input.

## Filtering — `where`

```
| where status == 200
| where UserPrincipalName contains "@contoso.com"
| where srcip in ("10.0.0.1", "10.0.0.2")
| where TimeGenerated > ago(6h)
| where TimeGenerated between (datetime(2026-01-01) .. datetime(2026-01-02))
```

String comparisons: `==`, `!=`, `contains`, `has`, `startswith`, `endswith`, `matches regex`. All case-sensitive unless you append `_cs` / `_cs` or lowercase both sides with `tolower()`.

## Aggregating — `summarize`

```
| summarize count() by srcip
| summarize total=sum(bytes), requests=count() by srcip
| summarize count() by bin(TimeGenerated, 5m)
```

Common aggregators: `count()`, `sum(col)`, `avg(col)`, `min(col)`, `max(col)`, `dcount(col)`, `make_set(col)`, `make_list(col)`, `percentile(col, 95)`.

`bin(col, <duration>)` buckets values — use for time-series charts.

## Projecting / extending

```
| project srcip, dstip, TimeGenerated
| extend hour = bin(TimeGenerated, 1h)
| project-rename src = srcip, dst = dstip
```

## Sorting & limiting

```
| top 10 by count_ desc
| order by TimeGenerated desc
| take 100
```

`top N by col` is equivalent to `order by col | take N` but more efficient.

## Time helpers

- `ago(<duration>)` → a point in time N ago. Durations: `1s`, `5m`, `2h`, `1d`, `7d`.
- `now()` → current time.
- `datetime("2026-01-01T00:00:00Z")` → explicit point.
- `between(a .. b)` → inclusive range.
- `bin(TimeGenerated, 5m)` → floor to 5-minute bucket.

## String / type helpers

- `tolower(s)`, `toupper(s)`, `strlen(s)`, `substring(s, start, len)`.
- `split(s, "/")` → array.
- `parse_json(s)` → dynamic.
- `toint(s)`, `tolong(s)`, `todouble(s)`, `tostring(x)`.
