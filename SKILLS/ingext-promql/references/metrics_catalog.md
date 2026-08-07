# Ingext / Fluency PromQL Metrics Catalog (cached)

This is the **complete, authoritative** list of end-user metrics on the Fluency / Ingext platform's
built-in **VictoriaMetrics** store. It is cached knowledge — do **not** call a discovery tool or
search the web to answer a metrics question. Everything queryable lives in this file.

Source: `ingext_schema/metrics/*.yaml`. Query language: **PromQL** or **MetricsQL**.

> Most internal/operational metrics (datalake merge, component-level compressed-byte counters,
> runtime profiling, buffer gauges) are intentionally excluded — end users do not query them. The
> `lake_search_*` compressed-byte and cost counters (§5) are the exception and **are** exposed. If
> asked about an excluded metric, treat
> it as out of scope (see the scope rule below). The one exception is the `ingext_queue_length`
> gauge (§7), which is exposed for queue-depth monitoring.

## Golden rule — counters vs the queue gauge

Almost everything below is a **monotonic counter** — never query its raw value; always wrap it in
`rate()` or `increase()` over a time window:

- `rate(<counter>[5m])` → per-second average over the window (use for "per second", live rates).
- `increase(<counter>[1h])` → total delta over the window (use for totals, billing, volume).

The **one exception** is the gauge `ingext_queue_length` (§7): it is an instantaneous value, so
query it **raw** — do **not** apply `rate()`/`increase()`.

Aggregate across series with `sum`, and break out by label with `sum by (<label>)`.

## Scope rule — reject anything not in this catalog

This catalog is an **allowlist**. There are exactly **six counter families** (seventeen counters) plus
**one gauge** (`ingext_queue_length`). If a request names a counter, gauge, or label that does not
appear in this file, **reject it** —
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
# Total bytes received by all datasources over the last hour (ingress volume).
sum (increase(platform_component_bytes{component="datasource", action="input"}[1h]))
# Ingress bytes per source application over the last hour (top sources).
sum by (application) (increase(platform_component_bytes{component="datasource", action="input"}[1h]))
# Per-datasource ingest rate trend (for spike / outage anomaly detection).
sum by (application) (rate(platform_component_bytes{component="datasource", action="input"}[1h]))
# Top talker datasources by ingress volume over the last hour.
topk(5, sum by (id, application) (increase(platform_component_bytes{component="datasource", action="input"}[1h])))
# Router processing errors by router over the last hour (0 = healthy).
sum by (id, application) (increase(platform_component_total{component="router", action="error"}[1h]))
# Events dropped at routers and sinks by component over the last hour.
sum by (component, id, application) (increase(platform_component_total{component=~"router|datasink", action="drop"}[1h]))
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
# Pipe processing errors by pipe and processor over the last hour (locate the failing pipe).
sum by (pipe, processor) (increase(platform_processor_total{action="error"}[1h]))
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
# Total bytes egressed by destination over the last hour (e.g. eventwatch vs datalake).
sum by (dest) (increase(platform_egress_bytes[1h]))
# Total bytes egressed by event type over the last hour.
sum by (eventType) (increase(platform_egress_bytes[1h]))
```

## 4. lake_ingress — datalake ingest metrics

Datalake input/ingest. (This is the live name for the schema's `lake_import_*`.)

| Counter | Description |
|---|---|
| `lake_ingress_count` | datalake ingest event count |
| `lake_ingress_bytes` | datalake ingest byte count |

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `titan` |
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
| `lake_search_bytes` | search byte count (uncompressed) |
| `lake_search_compressed` | search byte count (on-disk / compressed) |
| `lake_search_pod_seconds` | billable search-pod occupancy, in pod-seconds |
| `lake_search_core_seconds` | `pod_seconds` × the pod CPU request (1.5 cores) |
| `lake_search_cost_millicents` | search cost, in **thousandths of a cent** |

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `titan` |
| `index` | datalake index **full name** `$datalake-$index` | `managed-default`, `managed-Office365` |
| `provider` | service provider name | — |

`count` / `bytes` / `compressed` measure **data volume** — they are incremented at plan time from
the size of the slots scheduled to be scanned. The other three measure **cost**, and are recorded
once per completed search from the wall-clock each search pod was occupied.

Cost accounting (SaaS on-demand search only — `AccountSearchManagerV2`):

- Time is billed per pod, with a **60-second floor**: a pod that runs for 2 s still bills 60. A
  search fanned out to *N* pods bills at least `60 × N` pod-seconds. Failed and retried pod
  attempts count too, since the pod was occupied either way.
- Rate is **$0.126 per pod-hour**, i.e. exactly **3.5 millicents per pod-second** — so
  `cost_millicents == 3.5 × pod_seconds` and `core_seconds == 1.5 × pod_seconds` always hold.
  Divide `cost_millicents` by 1000 for cents, by 100000 for dollars. Millicents rather than cents
  because a minimum-size search costs ~0.21 ¢, which whole cents would round away.
- Realtime search emits **no** pod/core/cost series (see §6) — it runs in-process on no search pod.

```promql
# Searched events per second by provider, last 5 minutes.
sum by (provider) (rate(lake_search_count[5m]))
# Total bytes searched per index over the last hour.
sum by (index) (increase(lake_search_bytes[1h]))
# Search spend in dollars per account over the last day.
sum by (account) (increase(lake_search_cost_millicents[1d])) / 100000
# Search CPU burn (cores) per account, last hour.
sum by (account) (rate(lake_search_core_seconds[1h]))
# Top 10 most expensive accounts this week.
topk(10, sum by (account) (increase(lake_search_cost_millicents[7d])))
# Pod-seconds bought per GB actually scanned — high means many small fan-out searches
# paying the 60 s floor.
sum by (account) (increase(lake_search_pod_seconds[1d]))
  / (sum by (account) (increase(lake_search_bytes[1d])) / 1e9)
```

## 6. lake_realtime_search — datalake realtime search metrics

| Counter | Description |
|---|---|
| `lake_realtime_search_count` | realtime search event count |
| `lake_realtime_search_bytes` | realtime search byte count (uncompressed) |
| `lake_realtime_search_compressed` | realtime search byte count (on-disk / compressed) |

There is **no** `lake_realtime_search_pod_seconds` / `_core_seconds` / `_cost_millicents`: realtime
search runs in-process and occupies no search pod, so it has no pod time to bill. The API still
reports a per-search cost equal to one minimum pod unit (210 millicents), but that figure is not
pushed as a metric.

| Label | Description | Sample values |
|---|---|---|
| `account` | account name | `titan` |
| `index` | datalake index **full name** `$datalake-$index` | `managed-Office365` |
| `provider` | service provider name | — |

```promql
# Realtime-searched events per second by provider, last 5 minutes.
sum by (provider) (rate(lake_realtime_search_count[5m]))
```

---

## 7. ingext_queue_length — management queue length (gauge)

A **gauge** (instantaneous value): the length of the internal management queues — the number of
pending items currently in the queue. Query the **raw** value — do **not** apply `rate()` /
`increase()`. Aggregate with `sum` / `max` / `topk`, or use `*_over_time` functions
(`max_over_time`, `avg_over_time`, …) for trends.

| Gauge | Description |
|---|---|
| `ingext_queue_length` | internal management queue length (pending items currently in the queue) |

| Label | Description | Sample values |
|---|---|---|
| `provider` | service provider name | — |
| `account` | account name | `titan` |
| `service` | service name | `behavior`, `ml`, `datalake`, `eventwatch` |

```promql
# Current queue length by service.
sum by (service) (ingext_queue_length)
# Peak queue length per service over the last hour.
max by (service) (max_over_time(ingext_queue_length[1h]))
# Top 10 most-backlogged queues right now.
topk(10, ingext_queue_length)
```

---

## Tenant note

The schema also defines `fluency_import_*` and `lake_import_*`, which were **not observed** on the
live tenant. `lake_import_*` is the schema's older name for what production emits as
**`lake_ingress_*`** (§4) — same shape (`account`, full `index`). Treat the `lake_ingress_*` names
as authoritative for querying.

---

## Quick reference

**Gauge (read raw — no rate/increase):** `ingext_queue_length` — labels `provider`, `account`, `service`.

**Counters (rate/increase):**

| Family | Count counter | Byte counter | Key labels |
|---|---|---|---|
| Component | `platform_component_total` | `platform_component_bytes` | `component`, `action`, `id`, `application`, `appInstance` |
| Processor | `platform_processor_total` | `platform_processor_bytes` | `pipe`, `processor`, `action`, `application`, `appInstance` |
| Egress | `platform_egress_count` | `platform_egress_bytes` | `id`, `eventType`, `name`, `dest`, `datalake`, `index` (bare), `application`, `appInstance` |
| Lake ingress | `lake_ingress_count` | `lake_ingress_bytes` | `account`, `index` (full) |
| Lake search | `lake_search_count` | `lake_search_bytes` | `account`, `index` (full), `provider` |
| Lake realtime search | `lake_realtime_search_count` | `lake_realtime_search_bytes` | `account`, `index` (full), `provider` |

**Search cost counters** (SaaS on-demand search only, same labels as `lake_search_*`):
`lake_search_pod_seconds`, `lake_search_core_seconds` (= 1.5 × pod-seconds),
`lake_search_cost_millicents` (= 3.5 × pod-seconds; ÷1000 for cents, ÷100000 for dollars).
