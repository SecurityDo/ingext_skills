---
name: azure-log-analytics-search
version: 1.0.0
description: >
  Search a customer's own Azure Log Analytics / Microsoft Sentinel workspace live, with KQL,
  through the azure_logs_* tools. Use this skill whenever the user asks to query, search,
  count, aggregate, or investigate data that lives in Azure — e.g. "search their Sentinel
  workspace for failed sign-ins", "what tables are in the customer's Log Analytics
  workspace", "run this KQL against Azure", "check SigninLogs in Azure for user X",
  "query the ASIM network session parser", or any follow-up refining a prior Azure answer.
  Trigger on any phrasing that points at Azure, Log Analytics, Sentinel, a workspace, or an
  ASIM parser. This is NOT the Ingext datalake: nothing here has been ingested, every call
  reaches the customer's Azure tenant, and the table set is Azure's, not ours. For datalake
  event search use ingext-kql instead; for platform metrics use ingext-promql.
---

# Azure Log Analytics Search

You answer questions about data in a customer's **own Azure Log Analytics or Microsoft
Sentinel workspace** by writing KQL and running it there live.

## This is not the datalake

Nothing in this workspace has been ingested into Ingext. Every call leaves our
infrastructure, authenticates to Azure as the customer's app registration, and counts
against their workspace's query quota and concurrency. Two consequences:

- **The table set is Azure's.** `SigninLogs`, `SecurityEvent`, `Heartbeat`, `AADUserRiskEvents`
  and several hundred more — not `AzureSigninLogs`, not `Office365`, not `behavior`. Never
  reach for a datalake table name here, and never answer an Azure question from the
  datalake's schema knowledge base.
- **Discovery is live, not cached.** This skill carries no embedded schema. Every workspace
  differs, so you find out what exists by asking it.

If the question is about data Ingext ingested, this is the wrong skill — use **ingext-kql**.

## Scope

Answer one kind of question: how to search, count, aggregate, or investigate data in the
tenant's Azure Log Analytics workspace. Anything else is out of scope.

**In scope:**
- "how many failed sign-ins in their Sentinel workspace yesterday"
- "what does SigninLogs look like in Azure"
- "run `SecurityEvent | where EventID == 4625 | summarize count() by Account` against Azure"
- follow-ups that refine a prior Azure query

**Out of scope:** the Ingext datalake, platform metrics, general chat, non-KQL coding help.
If the request is out of scope, say so in one sentence and name the right skill. Do not call
any azure_logs_* tool for an out-of-scope request — each one costs the customer a query.

---

## Tools

Four tools, all read-only, all reaching the customer's workspace.

| Tool | When to use |
|---|---|
| `azure_logs_list_tables` | You don't yet know what the workspace holds. **Call this first.** Pass `filter` (case-insensitive substring) on anything but a tiny workspace — a Sentinel workspace has hundreds of entries and an unfiltered listing floods your context. `total` reports the count *before* the filter. |
| `azure_logs_get_schema` | You have candidate names and need their columns. `tables` is a **list** — ask for every one you are about to query in a single call. |
| `azure_logs_validate` | You have a candidate query. **Always call this before `azure_logs_search`.** Returns `ok: true`, or `ok: false` plus Azure's own parser message. |
| `azure_logs_search` | Run the query and get rows back. |

All four take an optional `integrationName`. Omit it when the account has exactly one
`AzureLogAnalytics` integration — the usual case. If there are several, the error names them,
so you can retry without guessing. If the account has none, say so plainly: the workspace has
not been connected yet, and no query will work until it is.

> **Finding the right connector:** these tools arrive prefixed with the connector ID
> (e.g. `mcp__<uuid>__azure_logs_search`). Use whichever Ingext/Fluency connector is
> connected; if several are and the user hasn't named a tenant, ask which one.

---

## Workflow

### 1. Find the queryable name
Call `azure_logs_list_tables` with a `filter` that matches the subject — `signin`, `security`,
`heartbeat`, `asim`. Each entry carries:

- `name` — **the KQL identifier, to use verbatim.** Azure KQL is case-sensitive.
- `kind` — `table` for stored data, `function` for a saved function or parser.
- `timespanColumn` — the column Azure applies a time range to, usually `TimeGenerated`.

**Do not ignore the functions.** On a Sentinel workspace the ASIM parsers are functions, and
they normalize several vendors onto one column set — usually a better query target than the
raw table behind them. **Which parsers exist varies by workspace**, and the gaps are wider
than you would expect: take them from the listing (`filter: "asim"`) rather than from a
remembered name, and never query a parser you have not seen there.

### 2. Get the columns (mandatory)
Call `azure_logs_get_schema` with every name you plan to query. Never infer a column name.
Names match case-insensitively and the workspace's real spelling comes back, so a near-miss
still resolves; a name the workspace does not have lands in `notFound` rather than failing
the call.

Read `columnSource` on each schema — it tells you how much to trust what you got:

| `columnSource` | Meaning |
|---|---|
| `metadata` | A table, read from the workspace metadata document. Free, and the columns carry Microsoft's own descriptions. |
| `probe` | A function. Its result shape is absent from the metadata document, so it was executed for — names and types only, no descriptions. |
| absent, with `columnsError` | The shape could not be resolved. **This is not "returns nothing"** — read the error. |
| absent, no `columnsError`, empty `columns` | The entry genuinely produces no columns. |

Probing is capped at twelve functions per call; anything past the cap says so in
`columnsError`, and you can ask for it in a second call. A `dynamic` column's interior is
never described — project a few rows to see inside one.

*(Function schemas require ingext_remote 9.12.12 or later. Against an older api every
function comes back with zero columns and no error — if you see that across the board, say
so rather than concluding the parsers are empty.)*

### 3. Draft the KQL
Use the name exactly as step 1 returned it, and only columns from step 2. See
[`references/azure_kql_notes.md`](references/azure_kql_notes.md) for the dialect notes that
differ from our datalake's KQL.

### 4. Validate
Call `azure_logs_validate`. A rejected query is an answer to iterate on, not a failure:
`verdict` stays `OK` and `ok` is `false`, with Azure's parser message in `error`. Fix and
call again.

Note that validation **executes** — against a one-second window in 1970, so it scans nothing,
but it does take a workspace concurrency slot. Don't loop on it carelessly.

### 5. Search
Call `azure_logs_search`. Read the **time range rule** below before you set a range; it is the
one thing on this surface that behaves opposite to our own `kql_search`.

### 6. Answer
Report the findings in prose or a small table, then state:

- the final KQL you ran,
- the `timespan` the response echoed — **the window actually applied**, not the one you asked
  for,
- `truncated: true` if it was set, and what the row cap was.

If `partial: true` came back, say so: the rows are real but incomplete, and presenting them as
a complete answer is the failure mode that matters here.

---

## The time range rule

**Azure ANDs your range with any time predicate inside the query, and the narrower wins.**
This is the opposite of `kql_search` over our datalake, where the query's own predicates take
precedence.

So:

- **If the query constrains time itself** (`| where TimeGenerated > ago(7d)`), **omit
  `rangeFrom`/`rangeTo`.** Sending both gives you the intersection, and a 24-hour default
  silently truncating a 7-day query reads as "no events".
- **If the query does not constrain time**, set `rangeFrom`/`rangeTo`, or accept the default
  of the **last 24 hours**. The default exists because sending no range at all makes Azure
  scan full retention — slow, expensive, and the fastest way to get a shared workspace
  throttled.
- **`rangeFrom` and `rangeTo` are epoch milliseconds.** Seconds will be accepted and land you
  in January 1970 with an empty result. The response echoes `timespan` as an ISO interval —
  **always check it**, and if it starts `1970-`, that is what happened.
- A zero-row result carries a `note` naming the intersection that was applied. Read it before
  reporting "no events".

## Row limits

`limit` defaults to 500 and caps at 5000 — a larger value is silently clamped, not rejected,
so asking for 10000 and getting 5000 back is not a bug. When the cap bites, the response sets
`truncated: true` both on the envelope and on the table. A truncated result is not a complete
answer — say so, or re-run with a `summarize` so the aggregate is exact rather than a sample of
the rows.

## What you may not run

Two shapes are refused locally, with a message saying why:

- **control commands** — anything starting with `.`
- **`externaldata`** — it would make Azure fetch a URL supplied in the query

Everything else goes through, including `let` statements and semicolons, which are idiomatic
in Sentinel content. The real boundary is the customer's app registration, which is scoped by
a role assignment to one workspace and has no write path at all.

## When something fails

See [`references/troubleshooting.md`](references/troubleshooting.md). The one worth knowing by
heart: a **403 `InsufficientAccessError`** means the app registration has no role assignment on
the workspace. Microsoft's own troubleshooting page suggests switching to the ARM endpoint at
that point — that is a red herring, and the error text we return names the real fix.
