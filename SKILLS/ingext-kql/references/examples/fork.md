# Example: several breakdowns in one pass (`fork`)

Available on every tenant since lake 2.10.25 (fleet charts v2.10.104, 2026-11-22).

## Question

> For the last 7 days of Office 365 activity, show events per workload, the five busiest
> operations with how many users ran each, and how many Exchange events there were.

Three answers over the same rows. Run as three queries, the datalake reads the week three times.
`fork` reads it once and feeds every subquery from the same rows, in parallel. Over 90 days of
Office 365, four summarizes took 4.8 s as one fork against 18.2 s as four queries.

## Query

```
Office365
| where timestamp > ago(7d)
| fork
    ByWorkload = (summarize events = count() by Workload)
    TopOps     = (summarize events = count(), users = dcount(UserId) by Operation | top 5 by events desc)
    Exchange   = (where Workload == "Exchange" | count)
```

The response carries one table per subquery, named `ByWorkload`, `TopOps` and `Exchange`,
instead of a single `PrimaryResult`. Each table holds exactly what that subquery returns when run
on its own.

## Walking through it

1. Everything before `fork` runs once: the time filter, any `where`, `extend` or `project`.
   Put the filters every subquery shares here.
2. Each `( ... )` is a subquery over those rows. It can filter further, `extend`, `summarize`,
   `top`, `take`, `distinct`, `count` or `project`.
3. Name a subquery with `Name = ( ... )`, or end it with `| as Name`. An unnamed subquery is
   called `Fork_1`, `Fork_2`, and so on by its position.

## Variants

A fork after a `summarize` runs its subqueries on the merged groups:

```
Office365
| where timestamp > ago(7d)
| summarize events = count() by Workload, Operation
| fork
    PerWorkload = (summarize operations = count(), events = sum(events) by Workload | top 3 by events desc)
    Busy        = (where events > 1000 | count)
```

Naming with `as`, and a default name:

```
Office365
| where timestamp > ago(7d)
| fork (summarize users = dcount(UserId) | as Users) (take 5 | project timestamp, Operation, UserId)
```

returns `Users` and `Fork_2`.

## Rules

- `fork` is the **last operator** of the query. Nothing can follow it, and it cannot sit inside a
  `let`, `join`, `union`, `mv-apply`, `facet` or another `fork`.
- A subquery reads only the fork's input: it cannot contain `join`, `union`, `facet` or another
  `fork`. Join or union before the `fork` if every subquery needs it.
- Subquery names must be unique. `as` is the subquery's last operator.
- Every subquery has its own row cap and its own `truncated` flag.
- `kql_summary` refuses `fork`; it exports one summarize. Use `kql_search`, or run one
  `kql_summary` per subquery.
- All subqueries share the table and the time window. Breakdowns over different tables or
  different windows are separate queries.

## `fork` or `facet`?

`facet by a, b` counts rows per value of each column. `fork` runs any subqueries you write. Use
`facet` for plain value counts, `fork` when the breakdowns need their own aggregates, filters or
`top`.

## Same answers without `fork`

If a tenant rejects `fork` (a lake older than 2.10.25), or the subqueries need different tables
or time windows, run each subquery as its own query with the shared prefix:

```
Office365 | where timestamp > ago(7d) | summarize events = count() by Workload
Office365 | where timestamp > ago(7d) | summarize events = count(), users = dcount(UserId) by Operation | top 5 by events desc
Office365 | where timestamp > ago(7d) | where Workload == "Exchange" | count
```
