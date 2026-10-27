# Evidence files

Each file is the result of one tool call on the tenant's MCP connector, saved as JSON. The script reads
only the fields below; other fields are ignored.

| File | Fields read |
|---|---|
| `cases.json`, `cases_prev.json` | one `behavior_summary_search` result, or an array of paged results: `total`, `documents[].source` with `key`, `keyType`, `dayIndex`, `riskScore`, `status`, `classification`, `behaviorRules`, `incidentDetectionTime`, `updatedOn`, `comments[]` (`createdOn`, `username`, `actions`) |
| `health.json` | written by the application-health skill: `mode`, `counts`, `applications[]` (`application`, `instance`, `state`, `status`, `labels`), `resourceFeeds[]` (`resource`, `customer`, `ageDays`, `empty`, `stale`) |
| `admins.json` | `{"checked": [upn], "admins": {upn: [role]}}` from `get_azure_user_record` |
| `compliance_summary.json` | written by compliance-assessment `build_report.py --summary-json`: `rows[]` (`control`, `title`, `status`) and `facts` (`events`, `workloads`, `audit_categories`, `users`, `devices`, `qualys_hosts`, `conditional_access`) |

Only `cases.json` is required. A month with no case at all stops the run.

Notes

- MTTD is structurally zero (a case is created at its first event), so the report says it is not meaningful.
- Response and close times start at `incidentDetectionTime`. A case without it is left out of those times, because the summary's `from` is only a two-minute bucket label of the first event.
- Comments on a case are written by the automated assistant (`AI-Assistant`) unless a person commented.
  The report separates assistant or analyst first response from analyst first response, and counts
  closed cases closed by the assistant, so a quiet analyst trail is visible instead of hidden.
- A resource feed is stale when its dump is older than a day or has no records.
- Rolling-trend categories come from keywords in `behaviorRules` (the `CATEGORIES` table at the top
  of `build_report.py`). A case counts once, in the first matching category; unmatched cases are
  shown as Other. Adjust the table for a tenant's rule names if too many fall into Other.
