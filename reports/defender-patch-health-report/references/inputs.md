# Inputs

The report reads four resource dumps and two small files. Only the two small files are written from tool output.

## Resource dumps (no queries)

| Resource | Used for |
|---|---|
| `msDefenderMachine` | Devices, enrolment status, health, last seen, duplicates |
| `msDefenderVulnerability` | CVE × device findings: severity, exploitability, first seen, recommended update, software |
| `msDefenderSecureConfig` | Configuration checks per device (applicable, compliant, impact) |
| `msDefenderAvHealth` | Antivirus mode, signature/engine/platform currency, scan times, full OS build |

Each is downloaded with `get_resource_dump_url(account, resource, customer, format="jsonl")` and saved as
`<work>/dumps/<resource>/<customer>.jsonl.gz`. A record is `{"@<resource>": {...fields...}, "@dayIndex": ..., ...}`; the script reads the inner
object. Field casing differs and is deliberate: `msDefenderVulnerability` is PascalCase (`CveId`, `VulnerabilitySeverityLevel`,
`ExploitabilityLevel`, `FirstSeenTimestamp`, `DeviceId`), the others are camelCase.

`msDefenderRecommendation` and `msDefenderSecureScore` are not used.

## `scope.json`

Written by hand from two tool results, small:

```json
{"endpointIntegrations": ["<name of each integration whose integration type is MSDefenderEndpoint>"],
 "dumpCounts": {"msDefenderMachine": 0, "msDefenderVulnerability": 0, "msDefenderSecureConfig": 0, "msDefenderAvHealth": 0}}
```

- `endpointIntegrations`: from `list_integrations(account)`, the `name` of every entry with `"integration": "MSDefenderEndpoint"`.
- `dumpCounts`: from `list_resource_dumps(account)`, the `count` of each dump. `check` fails if a downloaded file has a different row count.

An endpoint integration whose name is not the customer of any downloaded dump is reported as delivering no data.

## `a_alerts.json`

Alerts are an event stream (table `MSDefender`, event type `MSDefenderAlert`), not a resource table, so they are read with one `kql_search`
on the account. Two properties of the stream shape the query:

- The stream timestamp is when Defender last emitted the alert, not when it was created, and an alert is re-emitted whenever its state changes,
  so the same id appears many times. The query keeps the latest state of each alert and measures age from `createdDateTime`.
- Only alerts emitted inside the window are seen. Use a 180-day window so alerts that are still open but older than 30 days are included;
  an alert untouched for longer than the window, or older than the stream's retention, cannot appear.

Get the window as epoch milliseconds (end of the as-of day, 180 days back) and pass it as `rangeFrom` / `rangeTo`:

```bash
python3 <skill-dir>/scripts/defender_patch_health.py window --asof <yyyy-mm-dd>
```

```
MSDefenderAlert
| extend LastUpdate = todatetime(lastUpdateDateTime), Created = todatetime(createdDateTime)
| summarize arg_max(LastUpdate, *) by id
| extend ageDays = datetime_diff('day', datetime({ASOF}), Created)
| extend bucket = iff(ageDays <= 30, "0-30", "31+")
| extend t = iff(severity == "high" or serviceSource == "microsoftDefenderForEndpoint", tostring(title), "")
| summarize alerts=count(), oldestDays=max(ageDays) by serviceSource, severity, status, bucket, t
```

`{ASOF}` is the as-of date as `yyyy-mm-dd`. Save the whole response as `<work>/a_alerts.json` (about 30 rows; columns `serviceSource, severity,
status, bucket, t, alerts, oldestDays`). If `truncated` is true, stop and tell the user. The report counts alerts created in the last 30 days
from the `0-30` rows, counts every open alert (`new`, `inProgress`) at any age, and lists the open ones older than 30 days separately.
