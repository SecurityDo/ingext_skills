# Ingext / Fluency PromQL Metrics Catalog (cached)

This is the **complete, authoritative** list of end-user metrics on the Fluency / Ingext platform's
built-in **VictoriaMetrics** store. It is cached knowledge — do **not** call a discovery tool or
search the web to answer a metrics question. Everything queryable lives in this file.

Source: `ingext_schema/metrics/*.yaml`. Query language: **PromQL** or **MetricsQL**.

> Internal/operational metrics (datalake merge, compressed-byte counters, runtime profiling, queue
> and buffer gauges) are intentionally excluded — end users do not query them. If asked about one,
> treat it as out of scope (see the scope rule below).

## Golden rule — counters are monotonic

**Every metric below is a monotonic counter.** Never query the raw value. Always wrap a counter in
`rate()` or `increase()` over a time window:

- `rate(<counter>[5m])` → per-second average over the window (use for "per second", live rates).
- `increase(<counter>[1h])` → total delta over the window (use for totals, billing, volume).

Aggregate across series with `sum`, and break out by label with `sum by (<label>)`.

## Scope rule — reject anything not in this catalog

This catalog is an **allowlist**. There are exactly **six metric families** and **twelve
counters**. If a request names a counter or label that does not appear in this file, **reject it** —
**even if it is a real, valid counter on the instance.** Many live counters exist only for internal
use and must never be exposed to end users, so validity on the instance is irrelevant: the only
test is whether the metric is in this file. Respond:

> "That counter does not exist on the Fluency / Ingext instance."

Then optionally list the counters that do exist. Do **not**:
- run the query to "check" whether the metric exists;
- probe the store (`count by (__name__)`, label discovery, etc.) to find or confirm a metric;
- invent, guess, or substitute a similar-sounding metric;
- surface an internal metric even if you happen to know it exists.

---

## 1. platform_component — stream fabric component metrics

**Platform flow:** data moves through the fabric as **datasource (`src_*`) → router (`rt_*`) →
datasink (`sink_*`)**. Each router contains **at least one pipe** (`pipe_*`) that does the
processing and directs the data to a sink. So a single logical path is
`datasource → router (with one or more pipes) → datasink`. (Pipe-level processing detail is in
§2 `platform_processor`.)

| Counter | Description |
|---|---|
| `platform_component_total` | component event count |
| `platform_component_bytes` | component byte count |

| Label | Description | Sample values |
|---|---|---|
| `component` | stream fabric component type | `datasource`, `router`, `pipe`, `datasink`, `implicitConnection` |
| `action` | stream action — see note below | `input`, `output`, `pass`, `error`, `drop`, `ignore`, `compressed` |
| `id` | component ID | `src_*`, `sink_*`, `rt_*`, `pipe-*` |
| `application` | application name | `Office365`, `GSuite` |
| `appInstance` | application instance name | `Office365-default`, `GSuite-default` |

**Action semantics:**
- `input` — data **received** by a source or router.
- `pass` — data passed through (e.g. forwarded by a router/pipe).
- `output` — data emitted by a component (e.g. written out by a datasink).
- `compressed` — compressed (on-wire) byte count at a sink.
- `error` / `drop` / `ignore` — events that errored, were dropped, or were ignored.

> Because a router records both `input` and `pass` for the same stream, **summing across
> actions double-counts** a pass-through. To measure true volume through a router, pick a single
> action (e.g. `input`), don't sum all actions.

```promql
# Events per second by component type and action, last 5 minutes.
sum by (component, action) (rate(platform_component_total[5m]))
# Dropped/errored events per second by component ID.
sum by (id) (rate(platform_component_total{action=~"error|drop"}[5m]))
```

## 2. platform_processor — stream fabric processor metrics

| Counter | Description |
|---|---|
| `platform_processor_total` | processor event count |
| `platform_processor_bytes` | processor byte count |

| Label | Description | Sample values |
|---|---|---|
| `pipe` | pipe component ID | `pipe_*` |
| `processor` | processor name | `Office365_Adjustment` |
| `action` | processor (pipe) processing result — see note | `pass`, `error`, `abort`, `drop` |
| `application` | application name | `Office365`, `GSuite` |
| `appInstance` | application instance name | `Office365-default`, `GSuite-default` |

**Action semantics:**
- `pass` — processed and passed on.
- `abort` — the pipe aborted its processing and handed the event to the **next pipe within the
  same router**. This is **normal routing, NOT an error** — do not count it as a failure.
- `drop` — the event was dropped.
- `error` — a processing error occurred. **Only `error` indicates a failure.**

```promql
# Processed events per second by processor, last 5 minutes.
sum by (processor) (rate(platform_processor_total[5m]))
# Per-processor error ratio, last 5 minutes.
sum by (processor) (rate(platform_processor_total{action="error"}[5m]))
  / sum by (processor) (rate(platform_processor_total[5m]))
```

## 3. platform_egress — egress metrics

| Counter | Description |
|---|---|
| `platform_egress_count` | egress event count |
| `platform_egress_bytes` | egress byte count |

| Label | Description | Sample values |
|---|---|---|
| `id` | component ID | `sink_*` |
| `eventType` | event types | `Fortigate`, `Office365` |
| `name` | component name | `EventWatch`, `DatalakeOffice365` |
| `dest` | event destination | `eventwatch`, `datalake` |
| `datalake` | datalake name | `managed` |
| `index` | datalake index name — **bare index only**, not the full `$datalake-$index` form used by the `lake_*` metrics | `Office365`, `default`, `NetworkFortigateTraffic`, `NetworkFortigateEvent` |
| `application` | application name | `Office365`, `GSuite` |
| `appInstance` | application instance name | `Office365-default`, `GSuite-default` |

```promql
# Egress events per second by destination, last 5 minutes.
sum by (dest) (rate(platform_egress_count[5m]))
# Total bytes egressed per datalake index over the last hour.
sum by (index) (increase(platform_egress_bytes[1h]))
```

## 4. lake_ingress — datalake ingest metrics

Datalake input/ingest. (This is the live name for the schema's `lake_import_*`.)

| Counter | Description |
|---|---|
| `lake_ingress_count` | datalake ingest event count |
| `lake_ingress_bytes` | datalake ingest byte count |

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `fabrikam` |
| `index` | datalake index **full name** `$datalake-$index` | `managed-AzureAuditLogs`, `managed-Office365` |

```promql
# Ingested events per second by index, last 5 minutes.
sum by (index) (rate(lake_ingress_count[5m]))
# Total bytes ingested per index over the last hour.
sum by (index) (increase(lake_ingress_bytes[1h]))
```

## 5. lake_search — datalake on-demand search metrics

| Counter | Description |
|---|---|
| `lake_search_count` | search event count |
| `lake_search_bytes` | search byte count |

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `fabrikam` |
| `index` | datalake index **full name** `$datalake-$index` | `managed-default`, `managed-Office365` |
| `provider` | service provider name | — |

```promql
# Searched events per second by provider, last 5 minutes.
sum by (provider) (rate(lake_search_count[5m]))
# Total bytes searched per index over the last hour.
sum by (index) (increase(lake_search_bytes[1h]))
```

## 6. lake_realtime_search — datalake realtime search metrics

| Counter | Description |
|---|---|
| `lake_realtime_search_count` | realtime search event count |
| `lake_realtime_search_bytes` | realtime search byte count |

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `fabrikam` |
| `index` | datalake index **full name** `$datalake-$index` | `managed-Office365` |
| `provider` | service provider name | — |

```promql
# Realtime-searched events per second by provider, last 5 minutes.
sum by (provider) (rate(lake_realtime_search_count[5m]))
```

---

## Tenant note

The schema also defines `fluency_import_*` and `lake_import_*`, which were **not observed** on the
live tenant. `lake_import_*` is the schema's older name for what production emits as
**`lake_ingress_*`** (§4) — same shape (`account`, full `index`). Treat the `lake_ingress_*` names
as authoritative for querying.

---

## Quick reference — all counters

| Family | Count counter | Byte counter | Key labels |
|---|---|---|---|
| Component | `platform_component_total` | `platform_component_bytes` | `component`, `action`, `id`, `application`, `appInstance` |
| Processor | `platform_processor_total` | `platform_processor_bytes` | `pipe`, `processor`, `action`, `application`, `appInstance` |
| Egress | `platform_egress_count` | `platform_egress_bytes` | `id`, `eventType`, `name`, `dest`, `datalake`, `index` (bare), `application`, `appInstance` |
| Lake ingress | `lake_ingress_count` | `lake_ingress_bytes` | `account`, `index` (full) |
| Lake search | `lake_search_count` | `lake_search_bytes` | `account`, `index` (full), `provider` |
| Lake realtime search | `lake_realtime_search_count` | `lake_realtime_search_bytes` | `account`, `index` (full), `provider` |
