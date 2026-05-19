# Dynamic JSON columns

Columns flagged with `"logical_hint": "kusto_dynamic_json"` in the schema hold a JSON document. The reader parses the string as JSON on read, so you can navigate into it with the dot operator (`.`) and bracket indexing (`[]`).

Examples from `SigninLogs.DeviceDetail` (a dynamic column):

```
SigninLogs
| where DeviceDetail.operatingSystem == "Windows"
| project UserPrincipalName, DeviceDetail.browser, DeviceDetail.trustType
```

Nested access and arrays:

```
SigninLogs
| where LocationDetails.countryOrRegion == "US"
| extend firstCondPolicy = ConditionalAccessPolicies[0].displayName
```

String keys with special characters need bracket indexing:

```
ContainerLogV2
| extend podUid = KubernetesMetadata["pod-uid"]
```

Coerce the resulting value to a concrete type before aggregating on it:

```
FortigateEvent
| extend bytes = tolong(_fields.sentbyte)
| summarize total = sum(bytes) by srcip
```

Built-in helpers that operate on dynamic:

- `parse_json(s)` — force-parse a string into dynamic.
- `bag_keys(d)` — array of top-level keys.
- `mv-expand <col>` — turn an array into rows.
- `array_length(d)` — length of a dynamic array.

If the underlying JSON field is missing, navigation yields `null` and comparison returns `false`, so `where DeviceDetail.browser == "Edge"` silently skips rows where `DeviceDetail` doesn't have `browser`.
