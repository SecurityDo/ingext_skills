# Azure KQL — what differs from the Ingext datalake

The language is the same family, but the workspace, the dialect surface and the
result envelope are not ours. These are the differences that actually change a
query.

## Table naming

Azure's names, used verbatim and **case-sensitively**. A partial map of what a
datalake question translates to:

| If you were thinking of… | In Azure it is |
|---|---|
| `AzureSigninLogs` | `SigninLogs` (plus `AADNonInteractiveUserSignInLogs`, `AADServicePrincipalSignInLogs`, `ADFSSignInLogs`, `AADManagedIdentitySignInLogs`) |
| Windows event logs | `SecurityEvent`, `Event` |
| agent liveness | `Heartbeat` |
| Azure AD audit | `AuditLogs` |
| risk detections | `AADUserRiskEvents`, `AADRiskyUsers`, `AADServicePrincipalRiskEvents` |

Never assume a table is present. A workspace only holds the tables its data
connectors populate — `azure_logs_list_tables` is the authority, and `total`
tells you how many entries exist before your `filter` narrowed them.

## Tables vs functions

`kind` splits the listing in two, and the difference is not cosmetic.

- **`table`** — stored data. Columns come from the workspace metadata document
  for free, with Microsoft's own descriptions.
- **`function`** — a saved function or parser. Its result shape is *not* in the
  metadata document, so `azure_logs_get_schema` executes it over a dead window to
  learn the columns (`columnSource: "probe"`, names and types only).

On a Sentinel workspace the ASIM parsers are functions. They normalize several
vendors' schemas onto one column set, so a query written against a parser keeps
working when the customer swaps vendors. Prefer them when one covers the
question.

**Which ones exist is per-workspace.** The documented family is large —
`ASimAuthentication`, `ASimNetworkSession`, `ASimDnsActivity`, `ASimFileEvent`,
`ASimProcessEvent`, `ASimAuditEvent` and the parameterized `_Im_*` forms — but a
given workspace typically carries only the few its connectors installed, often
in vendor-specific (`ASimAuditEvent<Vendor>`) or locally authored variants, and
may have none of the headline names at all. Treat every parser name as unknown
until it appears in a listing: `filter: "asim"` (and `filter: "_im_"`), then
query what is actually there.

The `_Im_*` forms are the parameterized versions. Called bare they behave like
the matching `ASim*` view; they also accept filtering parameters, which push the
filter down and scan less. If a bare call works, use it — this is not the place
to get clever with parameters you have not verified against the workspace.

Note that a function may exist and still fail to bind — it can reference a table
the workspace does not have. That surfaces as `columnsError` on the schema, and
as a `SemanticError` from `azure_logs_validate`. Pick another entry rather than
fighting it.

## Query shapes that work well here

```kusto
SigninLogs
| where ResultType != 0
| summarize failures = count() by UserPrincipalName, ResultType
| top 20 by failures desc
```

```kusto
// Let statements and semicolons are fine and idiomatic.
let cutoff = ago(7d);
SigninLogs
| where TimeGenerated > cutoff
| summarize by UserPrincipalName
```

```kusto
// Time bucketing for a trend.
SecurityEvent
| where EventID == 4625
| summarize attempts = count() by bin(TimeGenerated, 1h), Account
```

Remember the range rule: the second example constrains time itself, so send it
with **no** `rangeFrom`/`rangeTo`.

## Sign-in result codes

`ResultType` is a string. `0` is success; everything else is a failure code, and
the common ones are worth recognizing rather than looking up every time:

| Code | Meaning |
|---|---|
| `0` | success |
| `50053` | account locked out / smart lockout |
| `50055`, `50057` | expired password, disabled account |
| `50072`, `50074` | MFA enrolment required, MFA required and not satisfied |
| `50126` | invalid username or password |
| `50158` | external security challenge not satisfied (conditional access) |
| `53003` | blocked by conditional access policy |

A burst of `50126` is password spraying; a burst of `50074`/`50158` against a
*correct* password is closer to MFA fatigue. Say which one the data shows.

## The result envelope

`azure_logs_search` returns `data` in the capitalized Kusto REST v1 shape — the
same shape our own `kql_search` emits, so one reader serves both:

```json
{"Tables":[{"TableName":"PrimaryResult",
            "Columns":[{"ColumnName":"ResultType","DataType":"string"},
                       {"ColumnName":"events","DataType":"long"}],
            "Rows":[["0",1200],["50126",17]],
            "Truncated":false}]}
```

Azure's own wire format is the lowercase `tables`/`name`/`columns`/`rows` form;
it is converted on the way through, so you will not see it. Column types are
Kusto scalars: `string`, `long`, `real`, `bool`, `datetime`, `dynamic`, `guid`,
`timespan`, `decimal`, `int`.

Alongside `data`, the response carries `took` (milliseconds), `total` (rows
returned), `timespan` (the window actually applied), and optionally `truncated`,
`partial`/`error`, and `note`.

## Dynamic columns

A `dynamic` column holds a JSON bag and its interior is never described by the
schema. Navigate with `.` or `["key"]`, and cast before aggregating:

```kusto
SigninLogs
| extend city = tostring(LocationDetails.city)
| summarize count() by city
```

To see inside one, project a few rows first rather than guessing at keys.
