# Example: group-by aggregation

## Question

> Over the last 24 hours, which source IPs in FortigateTraffic sent the most denied packets? Show the top 20.

## Shape of the query

1. Start from the table: `FortigateTraffic`.
2. Narrow the time range: `where TimeGenerated > ago(24h)`.
3. Narrow to the rows we care about: `where action == "deny"` (FortiGate traffic action).
4. Aggregate with `summarize` to get one row per source IP and count how many rows each has.
5. Return the top 20 by count.

## Query

```
FortigateTraffic
| where TimeGenerated > ago(24h)
| where action == "deny"
| summarize denies = count() by srcip
| top 20 by denies desc
```

## Variations

Add a second group-by dimension (destination country) and sum bytes rather than counting rows:

```
FortigateTraffic
| where TimeGenerated > ago(24h)
| where action == "deny"
| summarize bytes = sum(sentbyte), hits = count() by srcip, dstcountry
| top 25 by bytes desc
```

Bucket the timeline into 1-hour bins to show the trend:

```
FortigateTraffic
| where TimeGenerated > ago(24h)
| where action == "deny"
| summarize denies = count() by bin(TimeGenerated, 1h), srcip
| order by TimeGenerated asc
```

## Principles

- Put the most selective `where` clauses first — time range, then action/type, then string matches — so the engine can prune early.
- Aliasing with `summarize denies = count()` produces readable column names. Skip aliasing only for single-result queries.
- `top N by <col> desc` is both cleaner and faster than `order by ... | take N`.
