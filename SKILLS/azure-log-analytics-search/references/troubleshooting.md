# When an azure_logs_* call fails

Everything here reaches the customer's Azure tenant, so most failures are about
*their* configuration, not ours. Read the message — these errors are rewritten to
name the actual fix, and several of Azure's own remedies are misleading.

## Authentication and access

**`403 InsufficientAccessError`** — the app registration authenticated fine and
is not allowed to read this workspace. It needs a **role assignment on the
workspace itself**: the workspace → *Access control (IAM)* → *Add role
assignment* → **Reader**, or the narrower **Log Analytics Reader**.

Microsoft's troubleshooting page suggests switching to the ARM endpoint at this
point. That is a red herring — client credentials are supported on the endpoint
we use, and switching would force subscription and resource group into the
config for nothing. A fresh role assignment can take up to an hour to propagate,
so "I just granted it" and a 403 are compatible.

**`401` / other `403`** — the credentials themselves. `tenantId`, `clientId`,
`clientSecret`.

**`AADSTS7000215: Invalid client secret provided. Ensure the secret being sent
in the request is the client secret value, not the client secret ID`** — take
this one literally. Azure shows two things on the secret blade, and the one you
want is the **Value** column, which is a ~40-character string containing `~`
and is displayed only once, at creation. The **Secret ID** is a GUID. If the
integration's `clientSecret` is a GUID, it is the wrong field, and a GUID
sitting in `workspaceId` with a `~`-containing string in `clientSecret` means
the two were pasted the wrong way round.

## Addressing the workspace

**`404`** — `workspaceId` must be the **workspace GUID** (Log Analytics
workspace → Overview → *Workspace ID*), not its ARM resource id. The query
endpoint addresses workspaces by GUID and needs no subscription or resource
group.

**No integration configured** — the account has no `AzureLogAnalytics`
integration at all. Nothing can be queried until one is created with
`tenantId` / `clientId` / `workspaceId` and its `clientSecret`. Say that
plainly rather than retrying.

**Several integrations configured** — the error lists them by name. Re-run with
`integrationName` set to the one the user means; ask if it is ambiguous.

## Query failures

**`SyntaxError` / `SYN0002`** — a parse failure, reported in band by
`azure_logs_validate` as `ok: false`. The message names the offending token and
its line/column position. Fix and revalidate.

**`SemanticError`** — the query parsed but does not bind: an unknown table,
an unknown column, or a saved function that references a table this workspace
does not have. Re-check the name against `azure_logs_list_tables` and the
columns against `azure_logs_get_schema` before editing anything else.

**`PartialError` on a successful call** — the response carries `partial: true`
alongside real rows. The rows are genuine but the result is incomplete, usually
because part of the scan failed or timed out. Never present a partial result as
a complete answer; say which it is.

**`504`, "Azure timed out running the query"** — narrow the time range or push
the work into a `summarize` so less comes back.

**`429`, throttled** — the workspace's concurrency or rate limit. The message
carries Azure's `Retry-After` when it sent one. Back off; do not retry in a
loop. Remember that `azure_logs_validate` and a function schema probe each take
a slot too, so a burst of those can be what caused it.

## Empty results that are not empty

**`timespan` starting `1970-`** — `rangeFrom`/`rangeTo` were sent in seconds.
They are **epoch milliseconds**.

**Zero rows with a `note`** — the note names the intersection that was applied.
Azure ANDs your range with the query's own time predicate and the narrower wins,
so a query carrying `ago(7d)` run with a 24-hour default returns nothing. Drop
the range and re-run.

**`204` / a workspace with no data** — the workspace exists and is readable but
holds nothing at all. Distinguish this from a filter that matched nothing.

## Refused before we call Azure

**"control commands (queries starting with '.') are not allowed"** — this
endpoint runs read-only KQL. Azure's query endpoint would reject them anyway.

**"the externaldata operator is not allowed"** — it would make Azure fetch a URL
supplied in the query.

There is deliberately no rule against semicolons or multi-statement queries:
`let cutoff = ago(1d); SigninLogs | where TimeGenerated > cutoff` is idiomatic
and ubiquitous in Sentinel content, and there is no injection vector to justify
banning it — the query travels as a JSON string field and is concatenated into
nothing.

## Everything fails the same way

**`mcpserver: access denied: unknown user` on every tool** — not an Azure
problem and not specific to these tools. An API token could not call any MCP
tool before ingext_remote **9.12.12**; `initialize` and `tools/list` worked,
which makes it look per-tool. Against an older api, use a user's session token
or the OAuth flow.

**Every function reports zero columns, with no `columnsError`** — also
pre-9.12.12. Function schemas were read from the metadata document, which does
not describe them. Report the limitation rather than concluding the parsers are
empty.
