# Example: facet search (multi-dimensional breakdown)

## Question

> In the last hour of SigninLogs, for each combination of country + client app, show how many sign-ins succeeded vs failed and the number of unique users involved.

A "facet" breaks one population into buckets across several independent dimensions so you can compare them side by side.

## Query

```
SigninLogs
| where TimeGenerated > ago(1h)
| extend country = tostring(LocationDetails.countryOrRegion)
| summarize
      total    = count(),
      success  = countif(ResultType == "0"),
      failed   = countif(ResultType != "0"),
      users    = dcount(UserPrincipalName)
  by country, ClientAppUsed
| order by total desc
```

## Walking through it

1. Time filter first, as always.
2. `extend country = tostring(LocationDetails.countryOrRegion)` pulls a field out of the `LocationDetails` dynamic JSON column. The `tostring()` cast keeps KQL happy when the value gets compared.
3. `summarize` with multiple aggregators produces a facet row per `(country, ClientAppUsed)`:
   - `count()` — total events in that cell.
   - `countif(<predicate>)` — conditional count; useful for "how many succeeded" versus "how many failed" without running two queries.
   - `dcount(col)` — distinct count, for user cardinality.
4. `order by total desc` sorts facets with the heaviest populations first — usually what a human wants to skim.

## Variants

Slice by risk level and result:

```
SigninLogs
| where TimeGenerated > ago(24h)
| summarize events = count() by RiskLevelDuringSignIn, ResultType
```

Add a time bucket to the facet for a trend:

```
SigninLogs
| where TimeGenerated > ago(24h)
| summarize events = count() by bin(TimeGenerated, 1h), RiskLevelDuringSignIn
| order by TimeGenerated asc
```

## Principles

- `countif(<predicate>)` is the cleanest way to report success / failure / severity splits in one pass.
- When you facet over a dynamic-JSON subfield, always `extend` + `tostring()` / `tolong()` first; using the dynamic value directly in `summarize ... by` works but produces ugly column names.
- Keep the facet dimensions to 2-3 at most. More than that usually means the user wants a different query, not a wider one.
