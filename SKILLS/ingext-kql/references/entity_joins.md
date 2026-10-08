# Entity table JOIN samples

Worked samples for enriching event tables with `ENTITY_*` lookup tables. Read the **Entity tables
(enrichment with JOIN)** section of `SKILL.md` first for the rules. Discover the real table names and
columns for the tenant with `list_entity_tables` — the names below are the ones present on tenant
`titan` when these were written.

Status legend: **ran** = executed on `titan` and returned rows; **parses** = `validate_kql` ok, not executed
with data (the event table or entity table had no rows to test with).

## 1. Equality join — attach a description (inner join keeps only matches) — ran

Entity keys end in a period (`"Add group."`) but the audit field does not, so normalise the event side.
```
AzureAuditLogs
| where TimeGenerated > ago(30d)
| extend Operation = strcat(ActivityDisplayName, ".")
| join kind=inner ENTITY_O365_Azure_Administrative_Operations on Operation
| summarize Events = count() by Operation, Description
| order by Events desc
```

## 2. Left outer join — flag events against a list, keep everything — ran

`leftouter` keeps unmatched events; test an entity column with `isnotempty()` to see which matched.
```
AzureAuditLogs
| where TimeGenerated > ago(30d)
| extend Operation = strcat(ActivityDisplayName, ".")
| join kind=leftouter ENTITY_O365_Azure_Administrative_Operations on Operation
| extend IsAdminOp = iff(isnotempty(Description), "admin-operation", "other")
| summarize Events = count() by IsAdminOp
| order by Events desc
```

## 3. Anti-join — events NOT on the list — ran

`leftouter` plus `isempty()` on an entity column. Useful for whitelists ("not a known country / operation").
```
AzureAuditLogs
| where TimeGenerated > ago(30d)
| extend Operation = strcat(ActivityDisplayName, ".")
| join kind=leftouter ENTITY_O365_Azure_Administrative_Operations on Operation
| where isempty(Description)
| summarize Events = count() by ActivityDisplayName
| order by Events desc
| take 20
```

## 4. Resource table + lookup — license SKU GUID to product name — ran

`assignedLicenses` is an array, so `mv-expand` first. Drop empty SKUs before the join (unlicensed users
would otherwise show as blank). The license table holds **paid** licenses only, so free/trial SKUs stay
unmatched — show the GUID rather than hiding them.
```
office365User
| mv-expand lic = assignedLicenses
| extend SKUID = tostring(lic.skuId)
| where isnotempty(SKUID)
| join kind=leftouter ENTITY_Microsoft365_License_Table on SKUID
| extend License = iff(isnotempty(['Product name']), ['Product name'], strcat("(not in license table) ", SKUID))
| summarize Users = dcount(userPrincipalName) by License
| order by Users desc
```
Note the bracket-quoted column `['Product name']`. The same table also exists as
`['ENTITY_Microsoft License List']` (name with spaces) on some tenants — use whichever `list_entity_tables`
reports.

## 5. Prefix lookup — entity rows are prefixes, not full values — mechanics ran, CloudTrail form parses

`lookupType: prefix` (for example `ENTITY_AWS_Change_Actions`: `Create`, `Update`, `Remove`, ...) cannot be
joined on equality. Cross join on a constant key and keep rows where the event value starts with the prefix.
Aggregate the events down first so the cross join stays small.

Intended use — AWS API calls that are change actions (parses; `titan`'s CloudTrail returned no rows):
```
CloudTrail
| where TimeGenerated > ago(1d)
| summarize Events = count() by eventName
| extend k = 1
| join kind=inner (ENTITY_AWS_Change_Actions | extend k = 1) on k
| where eventName startswith Action
| summarize Events = sum(Events) by Action
| order by Events desc
```
Same join mechanics, executed on Azure AD audit activity names (returned `Update`, `Set`, `Add`, `Remove`):
```
AzureAuditLogs
| where TimeGenerated > ago(30d)
| summarize Events = count() by ActivityDisplayName
| extend k = 1
| join kind=inner (ENTITY_AWS_Change_Actions | extend k = 1) on k
| where ActivityDisplayName startswith Action
| summarize Events = sum(Events) by Action
| order by Events desc
```

## 6. CIDR lookup — classify IPs by subnet (longest-prefix match) — parses

`lookupType: CIDR`. Cross join on a constant key, keep IPs inside the range, then take the narrowest
(longest-prefix) subnet per IP with `arg_max(prefix, ...)`. Reduce events to distinct IPs *before* the cross
join. `ENTITY_Corporate_Subnets` and its columns `cidr`, `name`, `tags` are illustrative — take the real
`kqlName` and `fields` from `list_entity_tables`.
```
NetworkFortigateTraffic
| where TimeGenerated > ago(1d)
| where ipv4_is_private(srcip)
| summarize hits = count() by srcip
| extend k = 1
| join kind=inner (ENTITY_Corporate_Subnets | extend k = 1) on k
| where ipv4_is_in_range(srcip, cidr)
| extend prefix = ipv4_netmask_suffix(cidr)
| summarize arg_max(prefix, cidr, name, tags), hits = any(hits) by srcip
| summarize ips = count(), hits = sum(hits) by tags
| sort by hits desc
```
For FortiGate byte totals apply the fortigate-bandwidth rules instead of `count()`.

## Pitfalls seen while testing

- `where X in (ENTITY_T | project Col)` does not parse — use `join`.
- A join key that looks equal usually is not (trailing period, case, full country name vs code). Sample both
  sides with `take 10` first.
- A join that returns no rows against an empty entity table is not "no matches" — check the table has rows.
- On `titan`, `Office365` and `CloudTrail` returned counts but no rows through `kql_search`; samples that
  need them are marked parse-only.
