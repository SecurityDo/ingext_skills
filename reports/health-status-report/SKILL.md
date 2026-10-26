---
name: health-status-report
version: 1.1.0
description: >-
  Produce an Installed Applications Health report for ONE Ingext/Fluency tenant, using the same
  status logic as the Fluency 9 Applications page: each installed application instance is
  Running, Error, Attention (inactive, missing component, waiting for consent) or Other, with
  its last-24-hour traffic in and out, last-active time and error bytes by component.
  Reads the tenant's MCP connector with one list_connector_config call (installed applications,
  live components, errors, last-active, byte counters), removes credentials, evaluates locally, and
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
| **Error** | Connector state is `Aborted`, or the instance carries `errors` or `errorStates` |
| **Attention** | Inactive, or a missing component, or state `WaitingForConsent` |
| **Running** | Traffic in the last 24 hours, or connector state `Running` |
| **Other** | Anything else |

- **Traffic:** input is the 24-hour bytes received by the application's sources; output is the
  bytes written by its sinks. A resource source (Office 365 resource watch, Qualys, LDAP,
  SentinelOne API, and the others in `NO_CONNECTION` in the script) does not count unless it is
  connected to a router. An application whose only sources are resource sources has no traffic
  view at all, and is Running when its connector is.
- **Inactive:** not in error, no traffic, and either state `Inactive` or a component (a
  non-resource source, router, pipe or sink) with no entry in `lastActive`, which covers the 24-hour
  window the connector reports.
- **Missing component:** a resource the application was installed with (source, router, pipe, sink,
  integration) exists in no installed application's live configuration. A sink shared between
  applications (the event-watch sink) is live in only one of them, so the check uses all of them.
- **Error bytes** are shown per component but do not change the status, as on the page.

## Data integrity (non-negotiable)

Every figure is computed by `scripts/build_report.py` from the saved results. Never type a number
into the HTML. If the connector list or the traffic counters cannot be collected, stop: a failed
pull is not a healthy tenant. Say "status unknown" for anything you could not collect.

## Credentials (read this before collecting)

`list_connector_config` returns credentials in clear text (client secrets, token URLs, keys) inside
each application's config and integrations. Never keep the raw result in `WORKDIR` or the
repository, never quote it, and never paste it into the report. The harness saves a large result
to a file outside the work folder; run `scripts/scrub_config.py` on that file, then delete it.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. For a provider-wide view repeat per account; never merge tenants into one report. |
| Window | The 24 hours the connector reports. |

## Step 1 — Collect

| File | Tool and arguments |
|---|---|
| raw config | `list_connector_config` with the tenant account. The result is large, so the harness saves it to a file; use that file. |
| `dumps.json` | `list_resource_dumps` (optional; informational freshness of resource sources) |

Then scrub, and delete the raw file:

```bash
python3 scripts/scrub_config.py --config RAW_LIST_CONNECTOR_CONFIG.json --out WORKDIR/apps.json
rm RAW_LIST_CONNECTOR_CONFIG.json
```

`list_connector_config` may be deployed on only some connectors. If the tool is absent, stop and
say so; the older `list_connectors` + `stream_list_configs` + `prom_query` collection is not
supported by this version.

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
- **Inactive** can be correct and harmless, for example a syslog listener nobody sends to.
- An application with no sources (for example the AI assistant) is Running when its connector is.

## Accuracy discipline

- Not available through the connector, and not claimed: a disabled flag, so the page's Disabled
  status is not produced.
- Last-active times and error states come from the connector's own fields. Both were empty or
  unpopulated on the tenant tested, so the Error path is verified only by its logic, not by a
  real error.
- Quote counters; do not paraphrase them.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically.
