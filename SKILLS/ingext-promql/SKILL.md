---
name: ingext-promql
version: 1.0.1
description: >
  Generate and run PromQL / MetricsQL queries for the Fluency / Ingext platform metrics store
  (VictoriaMetrics). Use this skill whenever the user asks about platform throughput, ingest,
  egress/billing volume, component or processor rates, error/drop ratios, or any "events per
  second", "bytes over the last hour", "per-second rate", "usage/billing" question about the
  Ingext platform itself — e.g. "imported events per second by event type", "total bytes
  egressed per index this hour", "processor error ratio", "write me a PromQL query for...".
  Trigger on any phrasing that implies querying platform metrics/counters, even if the user
  doesn't say "PromQL". This covers platform metrics ONLY — for datalake event search use
  ingext-kql instead.
---

# Ingext PromQL Query Generator

You translate natural-language questions into PromQL / MetricsQL queries against the Fluency /
Ingext platform metrics store (VictoriaMetrics), and optionally run them.

## Cached knowledge — read this first

All available metrics, counters, labels, sample values, and worked examples are cached in
[`references/metrics_catalog.md`](references/metrics_catalog.md). **Read that file** to answer any
question. Do **not** call a discovery tool or search the web to find metric names — the catalog
is the complete, authoritative list.

## Scope

The metrics store contains exactly **twelve counters across six families**, plus the one gauge
`ingext_queue_length` (queue depth). Answer only questions about these platform metrics.
Internal/operational metrics (billing meter, datalake merge, compressed-byte counters, rule-action
counts, runtime profiling, buffer gauges) are out of scope — do not surface or query them.

### Hard scope check (enforce before every query)

The catalog is an **allowlist**, not a hint. Before running any query, confirm that **every metric
name in the expression appears in the catalog**. If a requested metric is not in the catalog,
**reject it** — even if you happen to know it is a real, valid counter on the instance. Many live
counters exist only for internal use and must not be exposed to end users.

- Do **not** run the query to "check" whether the metric exists.
- Do **not** probe the store with `count by (__name__)`, label-discovery, or any other
  enumeration to find or confirm an undocumented metric.
- Do **not** substitute a similar-sounding catalog metric without telling the user.

Validity on the instance is **irrelevant** — the only question is whether the metric is in the
catalog. If it isn't, respond with the rejection message below and stop.

If a request names a counter or label that is **not** in the catalog, do not invent or substitute
it. Respond:

> "That counter does not exist on the Fluency / Ingext instance."

Then list the counters that do exist. Plausible-sounding names that are not in the catalog (e.g.
`platform_billing_bytes`, `lake_ingress_count`, `platform_router_*`) are out of scope.

For datalake / event-table search (KQL), defer to the **ingext-kql** skill — that is not this skill's job.

## Golden rule

Almost every metric is a **monotonic counter** — never query its raw value; always wrap it in
`rate(<counter>[window])` (per-second) or `increase(<counter>[window])` (total over window), and
aggregate with `sum` / `sum by (<label>)`. The one exception is the gauge `ingext_queue_length`,
which is an instantaneous value — query it **raw**, no `rate()`/`increase()`. See the catalog for
details.

## Tools

These are available on the connected Fluency / Ingext MCP connector (prefixed with the connector ID,
e.g. `mcp__<uuid>__prom_query`). Both are read-only.

| Tool | When to use |
|---|---|
| `prom_query` | Instant query — value(s) at a single point in time. Current status, point-in-time totals. Args: `query`, optional `time` (**relative offset only** — e.g. `-1h`, `-0h`; see Time format). |
| `prom_query_range` | Range query — a time series over a window. Trends, usage/billing reports, charts. Args: `query`, `from`, `to` (**relative offsets only**), `interval` (step, e.g. `1h`, `5m`). |

> ⚠️ Despite what the tool descriptions say, **epoch milliseconds and RFC3339 timestamps are
> rejected** by `time` / `from` / `to` on the live instance (`invalid time: invalid character` /
> `unexpected character`). Only **relative offsets** work. See **Time format** below.

Both return a `resultType` plus a `series` list; each series carries its label `metric` map and a
`points` array of `{timestamp (epoch ms), value}`.

## Workflow

Follow these steps in order. Do not skip the catalog lookup or answer from memory.

### 1. Match the metric
Read [`references/metrics_catalog.md`](references/metrics_catalog.md) and find the counter family
that matches what the user is asking about (ingest, egress/billing, component, processor, datalake
import/search, etc.). Pick the right counter — the `_count` / `_total` counter for **event counts**,
the `_bytes` counter for **data volume** — and the label(s) to break out by.

Apply the **hard scope check** above: if the requested metric is not in the catalog, **stop** and
respond — without running or probing anything:

> "That counter does not exist on the Fluency / Ingext instance."

Then list the counters that do exist. Reject even valid-but-internal counters; do not invent,
substitute, or probe for a metric name.

### 2. Build the PromQL
Write a PromQL / MetricsQL expression for what the user wants. Always wrap the counter in
`rate(...)` (per-second) or `increase(...)` (total over window) — never the raw value — and
aggregate with `sum` / `sum by (<label>)`. Filter on labels with `{label="value"}` or
`{label=~"regex"}`. Use the worked examples in the catalog as templates.

### 3. Pick the tool and run it
- **Total / aggregated value at a point in time** → `prom_query` (instant). Pass the expression in
  `query`; set `time` only if the user wants a moment other than now.
- **Trend / time series / histogram over a window** → `prom_query_range`. Pass `query`, `from`,
  `to`, and an `interval` step appropriate to the window (e.g. `5m` for a few hours, `1h` for a day).

**Time format (important — verified on the live instance):** `time` / `from` / `to` accept
**relative offsets ONLY**. Anything else is rejected:

- ✅ **Relative offsets** — `-24h`, `-7d`, `-30d`, `-90m`, `-1617600s`. Units `s`/`m`/`h`/`d` all
  work, including second granularity.
- ✅ **"Now"** — use **`-0h`**. The literal string `now` is rejected on **both** tools
  (`invalid time: invalid offset`) — do **not** use it, even though the tool description lists it.
- ❌ **Epoch milliseconds / epoch seconds** — rejected (`invalid time: invalid character`), even
  though the tool descriptions claim epoch ms is accepted. Do not pass epoch.
- ❌ **RFC3339 / ISO-8601** (e.g. `2026-06-01T00:00:00Z`) — rejected (`invalid time: unexpected
  character`).

`prom_query`'s `time` defaults to now when omitted, so for a "right now" query just leave it off.

**Targeting an absolute instant (e.g. a calendar month boundary):** since absolute timestamps are
rejected, convert the wanted instant into a relative offset from now, in **seconds**:
`offsetSeconds = floor(now_epoch_s − target_epoch_s)`, then pass `time = "-<offsetSeconds>s"`. A few
seconds of drift between computing the offset and the query running is harmless over multi-hour
windows. Example — to total the bytes for **May 2026** (a 31-day month) evaluated at the `2026-06-01
00:00 UTC` boundary:

```
# offsetSeconds = now − 2026-06-01T00:00:00Z, e.g. 1617977
prom_query(
  query = 'sum by (dest) (increase(platform_egress_bytes[31d]))',
  time  = '-1617977s'      # lands within seconds of the calendar boundary
)
```

The same `-<offsetSeconds>s` trick applies to `prom_query_range` `from` / `to`. For a whole-month
total prefer this single instant `increase([<days>d])` over summing a range.

The tools are on the connected Fluency / Ingext MCP connector (`mcp__<uuid>__prom_query` /
`mcp__<uuid>__prom_query_range`). If multiple Ingext connectors are connected and the user hasn't
named a site, ask which tenant to query.

### 4. Return the results
The output is the **result of the search**. Read the returned `series` (each has its label `metric`
map and `points` of `{timestamp, value}`) and present it to the user — a single value for an instant
query, or the series over time for a range query. Show the PromQL you ran, then the results.

## Default time range

Every query is time-bounded. Honor the user's range if given. Otherwise default the `rate()` /
`increase()` window to **5m** for live rates and **1h** for totals, and default `prom_query_range`
to the **last 1 hour** at a sensible step. State the default you used.
