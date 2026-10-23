---
name: health-status-report
version: 1.0.0
description: >-
  Produce a Data-Source Health & Status report for ONE Ingext/Fluency tenant: which configured
  data sources are ok, in error or inactive over the last 24 hours, which resource fetchers
  (Office 365 resource watch, Qualys, LDAP) have gone stale, and what the SOC would be blind to.
  Evaluates each source from the platform's own throughput counters read through the tenant's
  MCP connector (stream topology, 24-hour datasource and pipe counters, resource dump
  freshness), then renders HTML, PDF and a per-source CSV. USE THIS SKILL for "data source
  health", "is everything healthy", "what's broken", "are my sources reporting", "stale
  sources", "blind spots", "health report for tenant X". DO NOT use it for platform-wide health
  of a site (logins, queues, egress; use ingext-health-monitor) or to investigate one incident.
---

# Data-Source Health & Status Report

Answers: is the customer's telemetry actually flowing, and what is broken, stale or quiet? It is
read-only and never changes the tenant. This is a port of the Fluency MSSP `evaluate_data_sources`
engine onto the connector's own tools: the same four-counter vocabulary and three verdicts, with
the inputs read from `prom_query`, `stream_list_configs` and `list_resource_dumps`.

`ingext-health-monitor` answers the platform-wide questions (are users logging in, are queues
backed up, how much is egressed). This skill answers the per-source one.

## The verdict rules (the only rules that decide health)

Per source, from the 24-hour counters. Top wins.

| # | Condition | Verdict |
|---|---|---|
| 1 | The source is a resource fetcher (no router; application Qualys, LDAP, Salesforce, `*ResourceWatch`, `*API`) | **ok** on throughput; its health is the freshness check |
| 2 | `bytes_errored` above the noise floor (at least 1 KB and 0.01% of throughput), or source-side errors above 0 | **error**. Page-worthy |
| 3 | `bytes_received == 0` and `bytes_passed == 0` | **inactive**. A quiet source; not a finding |
| 4 | Otherwise | **ok** |

- `bytes_dropped` is intentional filtering. `bytes_aborted` means the record was forwarded to the
  next pipe. Neither is ever an error.
- A resource fetcher with `bytes_passed = 0` is by design. Its index must have been written within
  24 hours, otherwise it raises `source_stale_resources`, which counts as an error.
- Never invent "degraded", "warning" or "amber". The verdict surface is ok / error / inactive.
- Tenant verdict: error if any source is in error or any fetcher is stale; otherwise ok if any
  source is ok; otherwise inactive. No sources at all is `no_sources_configured`, which is not
  healthy: the tenant is not being monitored.

## Data integrity (non-negotiable)

Every figure is computed by `scripts/build_report.py` from the raw tool results you saved. Never
type a number into the HTML. If `prom_query` fails, stop: the counters are the only input to a
verdict, and a failed pull is not a healthy tenant. Say "status unknown" for anything you could
not collect.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. For a provider-wide view, repeat per account and never merge tenants into one report. |
| Window | Fixed at the last 24 hours. |

## Step 1 — Collect (save each raw result under the name shown)

Run these in parallel and save each tool's raw JSON exactly as returned. Do not summarise or
retype numbers from memory.

| File | Tool and arguments |
|---|---|
| `streams.json` | `stream_list_configs` |
| `bytes.json` | `prom_query`, query: `sum by (id, application, component, action) (increase(platform_component_bytes{component=~"datasource\|pipe"}[24h])) > 0` |
| `counts.json` | `prom_query`, the same query on `platform_component_total` |
| `dumps.json` | `list_resource_dumps` (optional; without it, resource fetchers show freshness "unknown") |

The `> 0` filter drops zero series; the script reads a missing series as 0.

## Step 2 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --tenant acme --tenant-name "Example Corp" \
  --site Develop --out WORKDIR/report.html --csv WORKDIR/sources.csv
```

`--stale-hours` defaults to 24. `--captured-at` defaults to now (UTC).

## Step 3 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp Data-Source Health & Status Report"
```

The renderer needs Playwright and a Chrome or Chromium binary. It looks for Chrome in the usual
macOS, Linux and Windows paths (override with `--chrome` or `CHROME_PATH`) and for Playwright in
the current folder, the input's folder and the global npm root.

QA before delivering: if `pdftoppm` exists, look at every page (footer on every page, no clipped
text, tables inside the page); otherwise check in print media that each table has
`scrollWidth <= clientWidth`. If you cannot look at the pages, say so in the hand-off.

## Reading the result

- **Error:** act first. Name the source and quote the counter that put it there.
- **Stale resource fetcher:** its resource index has not been written within the limit. The
  connector may have stopped, or it may run on a slower schedule than daily; check before paging.
- **Inactive:** nothing received and nothing passed in 24 hours. Say explicitly that this is not
  a finding, and that "always quiet" cannot be told from "stopped" without a baseline.
- Lead with the rollup, for example "0 error / 3 inactive / 8 ok".

## Accuracy discipline

- Quote counters; do not paraphrase them. Keep the counter values separate from the verdict.
- Sources on one router share its pipe counters. The script splits them in proportion to the
  bytes each source received (evenly if none received anything), so a source that received
  nothing is never credited with another source's throughput.
- Freshness uses the newest resource dump written for a source (the dump `customer` equals the
  source name), not a live index query.
- Not in this data, and not claimed: platform alert text, disabled state, last-active times
  (a source with errors cannot be shown to have recovered, so it stays in error), and the
  configured-versus-discovered integration cross-check.
- Application for a source with no traffic is taken from its name prefix when no metric series
  names it.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically.
