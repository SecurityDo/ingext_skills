---
name: health-status-report
version: 1.0.0
description: >-
  Produce an Installed Applications Health report for ONE Ingext/Fluency tenant, using the same
  status logic as the Fluency 9 Applications page: each installed application instance is
  Running, Error, Attention (inactive, missing component, waiting for consent, aborted),
  Disabled or Other, with its last-24-hour traffic in and out and error bytes by component.
  Reads the tenant's MCP connector (installed applications, stream configuration, integrations,
  platform byte counters), removes credentials from the raw results, evaluates locally, and
  renders HTML, PDF and a per-application CSV. USE THIS SKILL for "are my applications
  healthy", "what's broken", "which connectors are in error", "is everything running",
  "installed applications status", "health report for tenant X". DO NOT use it for platform-wide
  health of a site (logins, queues, egress; use ingext-health-monitor) or for one incident.
---

# Installed Applications Health Report

Answers: which installed applications are running, which are in error, and which need
attention? It is read-only and never changes the tenant. The status logic is a port of the
Fluency 9 Applications page (`ApplicationsPage.tsx`, `activity.ts`, `traffic.ts`), so the report
agrees with what a customer sees in the product.

`ingext-health-monitor` answers the platform-wide questions (users logging in, queue backlog,
egress). This skill answers the per-application one.

## Status rules (first match wins)

Per installed application instance.

| Status | Condition |
|---|---|
| **Error** | Connector state is `Aborted`, or the instance carries an error message |
| **Disabled** | Any source of the application is disabled |
| **Attention** | Inactive, or a missing component, or state `WaitingForConsent` or `Aborted` |
| **Running** | Traffic in the last 24 hours, or connector state `Running` |
| **Other** | Anything else |

- **Traffic:** input is the 24-hour bytes received by the application's sources; output is the
  bytes written by its sinks. A resource source (Office 365 resource watch, Qualys, LDAP,
  SentinelOne API, and the others in `NO_CONNECTION` in the script) does not count unless it is
  connected to a router. An application whose only sources are resource sources has no traffic
  view at all, and is Running when its connector is.
- **Inactive:** not in error, no traffic, and either state `Inactive` or a component (an enabled
  non-resource source, router, pipe or sink) that has never carried data.
- **Missing component:** a resource the application was installed with (source, router, pipe, sink,
  integration) no longer exists in the live configuration.
- **Error bytes** are shown per component but do not change the status, as on the page.

## Data integrity (non-negotiable)

Every figure is computed by `scripts/build_report.py` from the saved results. Never type a number
into the HTML. If the connector list or the traffic counters cannot be collected, stop: a failed
pull is not a healthy tenant. Say "status unknown" for anything you could not collect.

## Credentials (read this before collecting)

`list_connectors`, `get_connector` and `list_integrations` return credentials in clear text
(API keys, HEC tokens, integration keys) despite their descriptions. Never save those raw results
into the work folder or the repository, never quote them, and never paste them into the report.
`scripts/scrub_connectors.py` keeps only names, ids, types, state and wiring.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. For a provider-wide view repeat per account; never merge tenants into one report. |
| Window | Last 24 hours for traffic; 90 days for "has ever carried data". |

## Step 1 — Collect

Run in parallel. Save each result under the name shown, in the work folder `WORKDIR`.

| File | Tool and arguments |
|---|---|
| raw connectors | `list_connectors`. Large results are saved by the harness to a file; otherwise write the result to a scratch file **outside** `WORKDIR` |
| raw integrations | `list_integrations`, same handling |
| `streams.json` | `stream_list_configs` |
| `bytes24.json` | `prom_query`: `sum by (id, component, action) (increase(platform_component_bytes{action=~"input\|output\|error"}[24h])) > 0` |
| `active90.json` | `prom_query`: `sum by (component, id) (increase(platform_component_bytes[90d])) > 0` |
| `dumps.json` | `list_resource_dumps` (optional; informational freshness of resource sources) |

Then scrub, and delete the raw files:

```bash
python3 scripts/scrub_connectors.py --connectors RAW_CONNECTORS.json --integrations RAW_INTEGRATIONS.json --out-dir WORKDIR
rm RAW_CONNECTORS.json RAW_INTEGRATIONS.json
```

The `> 0` filter drops zero series; the script reads a missing series as 0. If `stream_list_configs`
or `list_integrations` fails, the missing-component check is skipped and the report says so.

## Step 2 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --tenant acme --tenant-name "Example Corp" \
  --site Develop --out WORKDIR/report.html --csv WORKDIR/applications.csv
```

`--captured-at` defaults to now (UTC).

## Step 3 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp Installed Applications Health Report"
```

The renderer needs Playwright and a Chrome or Chromium binary. It looks for Chrome in the usual
macOS, Linux and Windows paths (override with `--chrome` or `CHROME_PATH`) and for Playwright in
the current folder, the input's folder and the global npm root.

QA before delivering: if `pdftoppm` exists, look at every page (footer on every page, no clipped
text, tables inside the page); otherwise check in print media that each table has
`scrollWidth <= clientWidth`. If you cannot look at the pages, say so in the hand-off.

## Reading the result

- Lead with the counts, for example "10 running / 1 attention / 2 error".
- **Error** first: name the application and quote its state or message.
- **Attention:** say which reason (waiting for consent, missing component, inactive).
- **Running is not proof of fresh data.** A connector can read Running while its index is days
  old. The report lists resource sources with the age of their newest dump, informational only.
- An application with no sources (for example the AI assistant) is Running when its connector is.

## Accuracy discipline

- Not available through the connector, and not claimed: platform alert and error history per
  component, disabled flags where the template carries none, and last-active times. An
  application with a recent platform alert but a Running connector therefore shows as Running.
- "Never carried data" uses 90 days of counters, which is a stand-in for the page's last-active
  time, not the same field.
- A shared sink (such as the event-watch sink) counts toward every application that lists it, as
  the page's own output total does.
- Quote counters; do not paraphrase them.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically.
