---
name: ingext-health-monitor
version: 1.0.0
description: Check the health of an Ingext / Fluency site and produce a clear status report. Trigger whenever the user asks about site health, whether data is flowing, if Ingext is working, if the site is healthy, whether ingestion is active, whether there are router or pipe errors (and which pipe is failing), how much data is being dropped at routers or sinks, how much data is being egressed (by event type and destination), whether ingestion has spiked or suddenly stopped (anomalies/outages), or whether any queues are backing up (backlog) — or any phrasing like "check the health", "is data coming in?", "is the site healthy?", "run a health check", "monitor site health", "check Ingext status", "is ingestion working?", "any errors in the routers?", "which pipe is erroring?", "how much data is being dropped?", "how much are we egressing?", "did ingestion spike or drop?", "are the queues backing up?", "any backlog?". Always use this skill for any question about whether the Ingext platform is ingesting data correctly, whether the pipeline is erroring or dropping data, how much is being egressed, whether ingestion looks anomalous, whether queues are backed up, or whether users are logging in — even if the user doesn't say "health check" explicitly.
---

# Ingext Site Health Monitor

Assess whether an Ingext site is healthy by running up to seven diagnostic checks — login activity,
data ingress, router/pipe errors, router/sink drops, egress (by event type and destination),
ingestion anomalies, and queue backlog — and reporting a clear pass/fail status for each.

## When to use

Trigger whenever the user asks about site health, data ingestion status, or whether the platform is working — e.g.:

- "Check the health of the site"
- "Is data flowing into Ingext?"
- "Run a health check"
- "Is the site healthy?"
- "Is ingestion working?"
- "What's the status of our Ingext instance?"

## Overview

A site is considered **healthy** when data is actively flowing (ingress) with no router/pipe errors
and no ingestion anomalies, queues are not backing up, and real (non-internal) users are logging in. The
skill runs up to seven independent checks — login activity, data ingress, router/pipe errors,
router/sink drops, egress (by event type and destination), ingestion anomalies, and queue backlog —
and aggregates them into a single status report (HTML).

## Monitoring window (default 7 days)

The report is **not fixed to 7 days** — it covers whatever period the user asks for (e.g. "last 24
hours", "past 14 days", "this month"). **Default to 7 days** when the user doesn't specify one.

Pick the window once, up front, and use it **consistently across every check**. In the steps below,
`<window>` is a placeholder for the chosen period — substitute the real value everywhere it appears:

- **PromQL duration** (for `increase()` / `rate()` lookbehind and ranges): `24h`, `7d`, `14d`,
  `30d`, etc. Default `7d`.
- **Relative offset** (for `from`): `-<window>` → `-24h`, `-7d`, `-30d`, …
- **Epoch-ms** (for the login `audit_search` `rangeFrom`): `now − <window-in-ms>`.
- **Anomaly range interval**: scale the step so the trend has ~100–200 points — roughly `10m` for a
  24h window, `1h` for 7d, `3h`–`6h` for 30d.

Compute the human-readable reporting period from the window (start = now − window, end = now) and
show it in the report header. Wherever the text below says "7 days" / "(window)", it means the selected
window.

## Step 1 — Check for a list_accounts tool

Look through the tools available in your current session for anything matching `list_accounts` (exact or near match — e.g. `list_accounts`, `get_accounts`, `listAccounts`).

- **Found**: Call it to get the list of all accounts. Present the accounts in the report's summary section and note that account enumeration succeeded. Skip to Step 4 (since listing accounts is itself a positive health signal).
- **Not found** (the common case today): Proceed to Step 2. Do not mention this to the user — just move on quietly.

## Step 2 — Login activity check (audit_search)

This check answers: *Are real (non-internal) users logging in?*

**Call `audit_search`** with:
- `query`: `"action:login"`
- `rangeFrom`: epoch milliseconds for the start of the window (now − `<window-in-ms>`; the 7-day default is now − 7 × 86400 × 1000)
- `rangeTo`: epoch milliseconds for now
- `limit`: 100

**Evaluate the result:**

Scan the returned events. First filter to **successful logins only** — an event is successful if it has **no `error` field** (or `error` is null/absent). Discard any event where `error` is present and non-null, as these are failed login attempts.

From the successful logins, classify each by the `email` field (or `username` if `email` is absent) as **internal** or **external**. The following are all considered internal domains:
- `@fluencysecurity.com`
- `@ingext.io`
- `@security.do`

Any email not ending in one of those three domains is **external**.

Count all groups:
- `successful_count` — events with no error field
- `failed_count` — events with an error field (track but don't use for pass/fail)
- `internal_count` — successful logins from internal domains
- `external_count` — successful logins from all other domains

Determine the result:
- If `external_count > 0` → **LOGIN CHECK: PASS** — real external users are actively logging in.
- If `external_count == 0` and `internal_count > 0` → **LOGIN CHECK: FAIL** — successful logins exist but only internal users.
- If `successful_count == 0` → **LOGIN CHECK: FAIL** — no successful logins at all.

Save: `total_count`, `successful_count`, `failed_count`, `internal_count`, `external_count`, and a sample of up to 3 external email addresses (redacted to `u***@domain.com` for display) to use in the report.

## Step 3 — Data ingress check (prom_query)

This check answers: *Is data flowing into the platform?*

Query the platform metrics store (VictoriaMetrics) directly via `prom_query` instead of running an
FPL report. The most direct "data entering the platform" signal is the **bytes received by all
datasources** — the `platform_component_bytes` counter with `component="datasource"` and
`action="input"` (`input` = data received by the source). These are monotonic counters, so wrap
them in `increase()` over the `<window>` (default 7 days).

**Call `prom_query`** with:
- `query`: `sum(increase(platform_component_bytes{component="datasource", action="input"}[<window>]))`
- `time`: omit (defaults to now)

Optionally make two more calls for richer evidence (run them in the same message):
- Event count: `sum(increase(platform_component_total{component="datasource", action="input"}[<window>]))`
- Top sources: `sum by (application) (increase(platform_component_bytes{component="datasource", action="input"}[<window>]))`

> Tool name: the metrics tools are exposed on the connected Fluency / Ingext MCP connector,
> prefixed with the connector ID (e.g. `mcp__<uuid>__prom_query`). If multiple Ingext connectors
> are connected and the user hasn't named a site, ask which tenant to query.

**Evaluate the result:**

The response is `{ "resultType": "vector", "series": [ ... ] }`. Read the total from the first
series' single point: `series[0].points[0].value` (an aggregated `sum(...)` returns one series with
no labels). Treat an empty `series` array as `0`.

- If the value is **> 0** → **INGRESS CHECK: PASS** — data is flowing.
- If the value is **0** (or `series` is empty) → **INGRESS CHECK: FAIL** — no data ingested in the
  selected window.

If `prom_query` returns an error, mark this check as **UNKNOWN** rather than FAIL, and note the
error in the report.

Save: the total ingress **bytes** (headline evidence for the KPI strip and panel), the event count,
and the per-application breakdown (top sources) for the report.

## Step 4 — Router / pipe error & drop check (prom_query)

This check answers: *Are any routers throwing processing errors (and which pipe), and how much data
is being dropped at routers/sinks?*

Only the `error` action counts as a failure. **Do not** treat `abort` or `drop` as errors —
`abort` means a pipe deliberately handed the event to the next pipe in the same router (normal
routing), and `drop` is an intentional discard. Only `action="error"` is a real failure.

**Step 4a — router-level errors.** Call `prom_query` with:
- `query`: `sum by (id, application) (increase(platform_component_total{component="router", action="error"}[<window>]))`

This returns one series per router (`id` = `rt_*`, `application` = its app). Sum the values:

- If the total is **0** (every router series is 0, or `series` is empty) → **ERROR CHECK: PASS** —
  no router errors in the selected window. **Skip Step 4b.**
- If any router has a value **> 0** → **ERROR CHECK: FAIL** — record each offending router
  (`id` + `application` + error count), then proceed to Step 4b to find the pipe.

**Step 4b — drill into the pipe (only if errors were found).** Each router contains one or more
pipes; pipe-level processing errors live in `platform_processor`. Call `prom_query` with:
- `query`: `sum by (pipe, processor) (increase(platform_processor_total{action="error"}[<window>]))`

Report every pipe with a value **> 0** — list the `pipe` ID, its `processor` name, and the error
count. These are the pipes responsible for the errors. (If a router showed errors but no pipe does,
note that the error is at the router level, not within a pipe.)

If `prom_query` errors, mark this check **UNKNOWN** and note it.

**Step 4c — sink & router drops.** Drops are events discarded at a router or sink
(`action="drop"`). Report the **total events dropped** (use the event-count counter, not bytes) and
where. Call `prom_query` with:
- `query`: `sum by (component, id, application) (increase(platform_component_total{component=~"router|datasink", action="drop"}[<window>]))`

Sum all values for the headline "total events dropped (window)". List any component (`component` + `id` +
`application`) with a value **> 0** as a drop source. Drops are **not always a failure** — filter
rules legitimately discard noise — so treat this as informational:

- Report the total dropped and the per-component breakdown regardless.
- Flag **DROP: HIGH** (contributes to DEGRADED) only if dropped events are a **significant fraction
  of ingress** — say **> 5%** of the Step 3 ingress **event count**. Otherwise **DROP: OK**.

Save: total router errors / offending pipes, total events dropped, and the per-component drop
breakdown for the report.

## Step 5 — Egress check (prom_query)

This check answers: *Is data flowing out of the platform, and to where?* Egress is the output volume
measured at the sinks. Report it broken down by **event type** and by **destination**.

**Call `prom_query` twice** (in the same message):
- By event type: `sum by (eventType) (increase(platform_egress_bytes[<window>]))`
- By destination: `sum by (dest) (increase(platform_egress_bytes[<window>]))`

Each returns one series per `eventType` / `dest` carrying its window byte total. Either grouping sums
to the same overall egress total.

- If total egress is **> 0** → **EGRESS CHECK: PASS** — data is flowing out. Report the per-eventType
  breakdown (top types) and the per-dest breakdown (e.g. `eventwatch` vs `datalake`).
- If total egress is **0** (or `series` is empty) → **EGRESS CHECK: FAIL** — nothing is being
  egressed despite ingress; data may be stuck before the sinks.

If `prom_query` errors, mark this check **UNKNOWN** and note it.

Save: total egress bytes, the per-eventType breakdown, and the per-dest breakdown for the report.

## Step 6 — Ingestion anomaly check (prom_query_range)

This check answers: *Has any datasource's ingestion spiked or suddenly stopped?* It replaces the
static "Data Ingressed" KPI with a live anomaly signal.

**Evaluate each datasource independently — not the aggregate.** Data arrives from different sources
(syslog collectors, cloud APIs, etc.), so a single source stopping is invisible in a platform-wide
sum (other sources keep the total high). A spike or outage must therefore be detected **per
datasource**.

**Call `prom_query_range`** to get the per-source ingress rate trend over the window:
- `query`: `sum by (application) (rate(platform_component_bytes{component="datasource", action="input"}[1h]))`
- `from`: `-<window>`
- `to`: `-0h`  (literal `now` is rejected — use `-0h`)
- `interval`: scale to the window so the trend has ~100–200 points (`10m` for 24h, `1h` for 7d,
  `3h`–`6h` for 30d). The inner `rate(...[1h])` smoothing window can stay `1h` for multi-day windows;
  for a sub-day window drop it to `~5m` so short spikes/outages aren't averaged away.

This returns a matrix with **one series per datasource** (`application`), each a list of points
(`{timestamp, value}` = that source's ingress bytes/sec). Evaluate **each series on its own**:

1. Compute that source's own baseline = the **median** of its points.
2. **Skip inactive sources** — if a series is ~0 across the whole window, that datasource simply
   isn't sending data (not configured / idle); it is **not** an outage. Only sources with a
   meaningful baseline (> 0) are candidates for outage detection.
3. **Spike** — any bucket greater than **5× that source's own median** (and clearly above its norm).
   Record the source, timestamp(s), and magnitude (e.g. "FluencyCollector ~250× on 11 Jun").
4. **Outage** — for an active source, a bucket dropping to ~0 while its baseline is clearly > 0
   means that source stopped. Pay special attention to the **most recent** buckets: if a source's
   last 1–2 buckets are ~0 while it was previously non-zero, that source is in an **ongoing outage**
   — often an **external issue at that datasource** (the upstream collector/API is down), not a
   platform fault. Name the affected datasource(s).

Determine the result (worst case across sources):
- No source has a spike or outage → **ANOMALY CHECK: PASS** — all sources steady.
- One or more sources spiked, or had a past (recovered) outage, but all active sources currently
  flowing → **ANOMALY CHECK: WARN** — list the affected source(s) and event(s).
- One or more active sources are currently stopped → **ANOMALY CHECK: FAIL** — list the stopped
  datasource(s); note the outage is likely external to that source.

If `prom_query_range` errors, mark this check **UNKNOWN** and note it.

Save: the per-datasource anomaly findings (source, type, when, magnitude), and the per-source trend
points (for the report). Always attribute spikes/outages to the **specific datasource**, never to
"ingestion" as a whole.

## Step 7 — Queue backlog check (prom_query)

This check answers: *Are any internal management queues backing up right now?* It uses the
`ingext_queue_length` **gauge** — an instantaneous value, so query it **raw** (no `rate()` /
`increase()`, no `*_over_time`). Look at the **current value only**, not historical data.

**Call `prom_query` once**:
- Current depth by service: `sum by (service) (ingext_queue_length)`

This returns one series per `service` (`behavior`, `ml`, `datalake`, `eventwatch`) with its current
queue depth. **A queue length over ~1000 indicates a significant backlog.** Evaluate:

- All services **≤ 1000** → **QUEUE CHECK: PASS** — no backlog.
- Any service **> 1000** → **QUEUE CHECK: FAIL** — backlog right now. Note the service(s) and current
  depth.

If `prom_query` errors, mark this check **UNKNOWN** and note it.

Save: the current queue depth per service, and any service over the 1000 threshold, for the report.

## Step 8 — Determine overall health

Combine the checks (Login, Ingress, Error, Drops, Egress, Anomaly, Queue). Apply the first rule that
matches, in order:

1. **❌ UNHEALTHY** — Ingress FAIL (no data at all) **and** Login FAIL; **or** Egress FAIL (ingress
   present but nothing egressing). (A single datasource stopping is **not** platform-wide UNHEALTHY —
   that is a per-source outage, handled below.)
2. **⚠️ DEGRADED** — any of: Anomaly FAIL (one or more datasources currently stopped — name them),
   Anomaly WARN (a datasource spiked or had a past outage), Error FAIL (router/pipe errors present),
   DROP HIGH (drops > 5% of ingress), Queue FAIL (any service queue currently over ~1000), Ingress
   FAIL/UNKNOWN, or Login FAIL (no external logins) while another signal is positive.
3. **⚠️ UNCERTAIN** — the checks that ran are mostly UNKNOWN, so health can't be assessed.
4. **✅ HEALTHY** — Ingress PASS, Error PASS, Egress PASS, Anomaly PASS, Queue PASS, drops OK, and
   Login PASS (external logins present).

State the single most important reason next to the overall badge (e.g. "DEGRADED — errors in the
Office365_AdjustmentsV2 pipe", "DEGRADED — FluencyCollector ingestion spike on 12 Jun", "DEGRADED —
AWSCloudTrail datasource stopped", or "DEGRADED — datalake queue backlog (3,400)"). Always name the
specific datasource / processor / service, never raw component IDs.

## Step 9 — Write the HTML report

Produce a self-contained single-file HTML report and save it to the output directory as `ingext_health_<YYYYMMDD>.html`.

**Time period:** Before writing the report, compute the human-readable reporting period from the selected window (start = now − window, end = now), and format it as `"DD MMM YYYY – DD MMM YYYY"` (e.g. `"15 May 2026 – 22 May 2026"`). For sub-day windows include the time (e.g. `"17 Jun 08:00 – 17 Jun 20:00 UTC"`). Display this prominently in the header as the reporting period, and state the window length (e.g. "last 7 days", "last 24 hours").

### Report structure

```
Header bar          — "Ingext Site Health Report" + date + overall badge
                      Reporting period: "DD MMM YYYY – DD MMM YYYY"
──────────────────────────────────────────────────────
KPI strip (4 cards) — Overall Status | External Logins (window) | Errors / Drops (window) | Ingestion Anomaly
                      • Ingestion Anomaly card replaces the old "Data Ingressed" card:
                        show worst-case status across datasources (Normal / Spike / Outage)
                        color-coded, naming the source (e.g. "FluencyCollector spike 11 Jun"
                        or "AWSCloudTrail outage").
                      • Errors / Drops card: error count + total events dropped over the window
                        (0 errors = green; flag amber if DROP HIGH).
──────────────────────────────────────────────────────
Check panels (7)    — One card per check:

  Login Activity panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Login breakdown table:
        Successful logins  │  <successful_count>  │ (no error)
          – Internal       │  <internal_count>    │ fluencysecurity.com / ingext.io / security.do
          – External       │  <external_count>    │ customer / external users
        Failed logins      │  <failed_count>      │ (error present)
        ────────────────────────────────────────────
        Total attempts     │  <total_count>
    • If external logins > 0: sample of up to 3 redacted external addresses
    • What the result means

  Data Ingress panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Key evidence: total bytes & events ingested (window) from datasource input,
      plus the top source applications from the per-application breakdown
    • What the result means

  Router / Pipe Errors & Drops panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Errors: if PASS, "No router or pipe errors in the selected window."
      If FAIL, table of offending routers (application · error count) and
      the responsible pipes (processor name · error count)
    • Drops: total events dropped (window) + per-component breakdown (component type ·
      application · event count); note DROP OK vs DROP HIGH (> 5% of ingress events)
    • Note that abort is excluded — only true errors are counted as errors
    • What the result means

  Egress panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Total egress bytes (window)
    • Breakdown by destination (eventwatch vs datalake) — small bar or table
    • Breakdown by event type (top types) — table
    • What the result means

  Ingestion Anomaly panel (per datasource):
    • Check name & description
    • Result badge (PASS / WARN / FAIL)
    • Per-datasource status — list any source that spiked or stopped, named
      explicitly (e.g. "FluencyCollector — spike ~250× on 11 Jun";
      "AWSCloudTrail — outage, stopped 3h ago"). If all clear, say so.
    • For a flagged source, show its own trend sparkline + magnitude vs its baseline
    • Note that a per-source outage is often an external issue at that datasource
    • What the result means

  Queue Backlog panel:
    • Check name & description
    • Result badge (PASS / FAIL)
    • Table of current queue depth per service
      (behavior, ml, datalake, eventwatch)
    • Threshold note: > 1000 = significant backlog
    • What the result means

──────────────────────────────────────────────────────
Interpretation      — 2–3 sentence plain-English summary of findings
Next steps          — 2–4 action items if anything is degraded/unhealthy
                      (omit or shorten if everything is healthy)
──────────────────────────────────────────────────────
Footer              — "Powered by Ingext · <date>"
```

### Styling guidelines

- **Do not display raw component IDs** (`rt_*`, `sink_*`, `pipe_*`, `src_*`) anywhere in the
  report. Always refer to components by their human-readable names — application name (e.g.
  "Office365"), processor name (e.g. "Office365_AdjustmentsV2"), and component type (router / sink /
  datasource). IDs may be used internally to run queries, but must never appear in the output.
- Use inline CSS only — no external dependencies.
- Color scheme:
  - HEALTHY / PASS: `#22c55e` (green)
  - DEGRADED / UNKNOWN: `#f59e0b` (amber)
  - UNHEALTHY / FAIL: `#ef4444` (red)
  - Background: `#0f172a` (dark navy), card background: `#1e293b`
  - Body text: `#e2e8f0`, muted text: `#94a3b8`
- Max width `780px`, centered, responsive.
- The overall status badge should be prominent — large font, full-width banner color.

## Step 10 — Share

Link to the HTML file with a `computer://` path. Add one sentence in chat summarizing the overall status (e.g., "The site looks healthy — external logins detected, no router/pipe errors, and ingestion steady over the selected window." or "Degraded — an ingestion spike on 12 Jun and errors in pipe_xxxx.").

## Failure modes

- **`audit_search` errors**: Mark the login check as UNKNOWN, note the error in the report, continue to the ingress check.
- **`prom_query` errors**: Mark the ingress check as UNKNOWN, note the error in the report.
- **`prom_query` returns an empty `series`**: Treat as ingress value 0 → INGRESS CHECK: FAIL (no data in the selected window), not UNKNOWN.
- **Both checks UNKNOWN**: Report can't determine health. Tell the user to check connector configuration.
- **No output directory**: Write to `/tmp/` and share the path.
