# Queries for compliance-assessment

All run against one tenant account through the connector's `kql_search` (or the named tool).
Set `rangeFrom` / `rangeTo` to the month in epoch milliseconds for the event queries.

| File | Query |
|---|---|
| `o365_workloads.json` | `Office365 \| summarize events=count() by Workload` |
| `signin.json` | `AzureSigninLogs \| summarize events=count(), failed=countif(ResultType != "0"), users=dcount(UserPrincipalName)` |
| `audit_categories.json` | `AzureAuditLogs \| summarize events=count() by Category` |
| `windows.json` | `WindowsAudit \| summarize events=count()` |

Resource tables are not queried. Each is a resource dump (`list_resource_dumps`, then
`get_resource_dump_url`, jsonl format) saved as:

| File | Resource | Customer (from `list_resource_dumps`) | Counted by the script |
|---|---|---|---|
| `users.jsonl.gz` | `office365User` | Office365ResourceWatch-<TENANT> | records; `accountEnabled == true` |
| `devices.jsonl.gz` | `office365Device` | Office365ResourceWatch-<TENANT> | records; `isManaged == true` |
| `ca_policies.jsonl.gz` | `office365ConditionalAccessPolicy` | Office365ResourceWatch-<TENANT> | records by `state` |
| `qualys.jsonl.gz` | `qualysHost` | Qualys-<TENANT> | records |

`behavior.json`: `behavior_summary_search` with `limit: 0` and `facets: ["status", "classification",
"scoreLevel"]`. The facets count incident-flagged summaries, so `status` totals are the incident
count, which is smaller than `total` (all behavior summaries).

Notes:
- Office365 is large (millions of rows a month). If the query is closed by the proxy, retry once;
  if it still fails, narrow to one week and say the figure is partial.
- `list_data_tables` runs first (SKILL.md Step 1). If a table is absent (no `WindowsAudit`, no
  `qualysHost`), do not run its query: the control it feeds is not observed on that tenant.
- Control mapping used by the script: AU-2/AU-12 (event volumes), SI-4 (behavior summaries),
  AU-6 and IR-4/IR-5 (incident dispositions), AC-2 (users, directory audit), AC-7 (failed
  sign-ins), IA-2/IA-5 (Conditional Access), CM-8 (devices, Qualys hosts), RA-5 (Qualys).
  AU-4/AU-11, SC-7 and SI-3 are always not observed until a source is added; AC-1, IA-1 and IR-1
  are always manual review.
