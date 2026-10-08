---
name: ingext-entity-tables
version: 1.0.0
description: >
  Discover and search Ingext entityinfo (lookup) tables — the ENTITY_* tables holding event-ID
  descriptions, status/reason codes, watchlists, whitelists/blacklists, critical assets/users/subnets,
  license SKU names, and AgentID translations. Use when the user asks "what entity tables / lookup tables /
  watchlists exist", "what fields does the X entity table have", "what does event ID 4672 mean",
  "show the critical users list", "look up SKU X", or "what's in the country whitelist". Always calls
  list_entity_tables first, then searches the table directly with KQL. Does NOT join entity tables to event
  tables (ingext-kql owns the JOIN enrichment patterns) and does NOT cover stream or resource tables (use ingext-kql).
---

# Ingext Entity Tables — Search

Entity tables are small lookup tables Fluency ships and syncs into each tenant (or the tenant imports
itself). They are **not** in `list_data_tables` and **not** in the ingext-kql schema KB. The only source of
truth for their names and columns is the `list_entity_tables` MCP tool, **per tenant**. This skill covers
finding them and searching them on their own — no joins. To enrich event-table results with an entity
table (JOIN, including CIDR/subnet matching), hand off to `ingext-kql`, which uses this skill's discovery step.

## Workflow

1. **Pick the tenant.** `list_accounts` if the user did not name one. Use the connector the user names
   (tools are prefixed per connector, e.g. `mcp__Develop__*`).
2. **List the entity tables.** Call `list_entity_tables(account)`. Each entry has:
   - `name` — entityinfo name
   - `kqlName` — identifier to write in KQL **verbatim** (usually `ENTITY_<name>`; bracket-quoted such as
     `['ENTITY_Microsoft License List']` when the name has spaces; empty = cannot be queried until renamed)
   - `fields` — column names in CSV order. **Every column is a string** — use `toint()` / `todouble()` for
     arithmetic. Names may contain spaces (`['Event ID']`) or start with `##` (translation tables).
   - `lookupType` — `string_match`, `prefix`, `CIDR`, or `translation`
   - `description`
   If the user only asked what exists or what fields a table has, answer from this list and stop.
3. **Choose the table** by name/description. Never guess a table name or column — use `kqlName` and `fields` exactly.
4. **Draft the KQL** against that single table (patterns below). No time filter, no dedup: entity tables are
   snapshots.
5. **Validate** with `validate_kql`, then run with `kql_search` and report the real rows. If it returns
   nothing, say the table is empty rather than concluding there is no match.
6. **Return** the query plus a 1–2 sentence explanation and the table used. For a pure query answer follow
   ingext-kql's JSON contract (`kql`, `explanation`, `tables`).

## Search patterns (verified on tenant `titan`)

Preview a table:
```
ENTITY_AD_EventID | take 10
```
Filter on a column (spaced column names use brackets; `contains` is case-insensitive substring):
```
ENTITY_AD_EventID | where Description contains "logon" | project ['Event ID'], Description | take 20
```
Exact lookup of one key:
```
ENTITY_AD_EventID | where ['Event ID'] == "4672"
```
Count / list rows:
```
ENTITY_AD_LogonType | summarize Total=count()
```
Table whose name has spaces:
```
['ENTITY_Microsoft License List'] | where ['Product name'] contains "E5" | project ['Product name'], SKUID | take 3
```
Single-column watchlist:
```
ENTITY_Exchange_Uncommon_Operations | take 10
```

## Gotchas

- **Values are strings.** Compare event IDs as `"4672"`, not `4672`; cast before numeric math.
- **Spaced names need brackets:** `['Event ID']`, `['ENTITY_Microsoft License List']`. An empty `kqlName` means the table cannot be written in KQL.
- **Empty tables.** A table imported with no rows is listed but returns no rows or fails. On `titan`,
  `ENTITY_Group_Critical_Subnets` and the `ENTITY_AD` translation table returned 0 rows. Say so.
- **lookupType hints how to read values:** `prefix` rows are prefixes (match with `startswith` when reading
  them), `CIDR` rows are subnets, `translation` tables map an AgentID to `##username`, `##asset`, `##ip`.
- **Catalog is per tenant** (titan ≈ 45 tables). Never reuse another tenant's list.
- **Subqueries in `in (...)` don't parse** — keep queries single-table here.

## Try

"What entity tables does titan have?", "Show the fields of AD_LogonType", "What does event ID 4672
mean?", "List the O365 administrator list", "Find Microsoft 365 E5 license SKUs".
