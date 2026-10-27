# health.json

Written by `scripts/evaluate_health.py`.

| Field | Meaning |
|---|---|
| `mode` | `full` or `state_only` |
| `capturedAtMs` | when the connector data was captured, epoch ms |
| `counts` | applications per status: `running`, `error`, `attention`, `disabled`, `other` |
| `totals` | `inputBytes`, `outputBytes` over all applications, 24 h (null in state-only mode) |
| `limits` | plain-language limits of this run; repeat them wherever the result is used |
| `resourceFeeds` | null if `--dumps` was not given, else one entry per dump: `resource`, `customer`, `createdOnMs`, `ageDays`, `count`, `empty`, `stale` |
| `applications[]` | one per installed application instance, worst status first |

Each application:

| Field | Meaning |
|---|---|
| `application`, `instance`, `displayName`, `instanceName` | identity |
| `state` | the connector state (`Running`, `Aborted`, `WaitingForConsent`, ...) |
| `status` | `error`, `attention`, `disabled`, `other` or `running` |
| `labels` | the reasons shown on the page, for example `Missing component`, `Inactive` |
| `signals` | which of Error, Missing component, Disabled source, Inactive were raised |
| `inputBytes`, `outputBytes`, `errorBytes` | 24 h totals (null when not applicable or in state-only mode) |
| `errorRows` | components with error bytes: `component`, `name`, `bytes` |
| `errorMessages` | `component`, `message` quoted from errors or the latest alert |
| `lastActiveMs` | newest component activity, epoch ms (null if none or state-only) |
| `resourceOnly` | true when all sources are resource sources, so there is no traffic view |
| `resourceSources` | `name` and `newestDumpMs` of each resource source |
