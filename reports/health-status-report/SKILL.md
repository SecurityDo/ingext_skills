---
name: health-status-report
version: 1.2.1
description: >-
  Produce an Installed Applications Health report for ONE Ingext/Fluency tenant as HTML, PDF and a
  per-application CSV, using the same status logic as the Fluency 9 Applications page: each
  installed application instance is Running, Error, Attention, Disabled or Other, with its
  last-24-hour traffic, last-active time and error bytes by component where the connector provides
  them. Reads the tenant's connector (list_connector_config, else list_connectors), removes
  credentials, evaluates locally and also saves health.json for other reports to reuse. USE THIS
  SKILL for "health report for tenant X", "which of our applications are in error", "is everything
  running", "applications status report". DO NOT use it for platform-wide health (logins, queues,
  egress; use ingext-health-monitor) or for one incident.
---

# Installed Applications Health Report

Answers: which installed applications are running, which are in error, and which need attention? It is
read-only and never changes the tenant. The status logic is a port of the Fluency 9 Applications page
(`ApplicationsPage.tsx`, `activity.ts`, `traffic.ts`), so the report agrees with what a customer sees in
the product.

`ingext-health-monitor` answers the platform-wide questions (users logging in, queue backlog, egress).
This skill answers the per-application one.

The evaluation writes `health.json` before any report is built. Other skills reuse that file:
`ciso-monthly-report` reads it for its coverage and health section, so install this skill before using
that one. To get only the data, stop after Step 2.

## Two modes

| Mode | Collect with | What you get |
|---|---|---|
| **full** | `list_connector_config` (only some connectors have it) | state, errors and alerts, live components, last-active times, 24-hour traffic in and out, error bytes, the disable setting |
| **state only** | `list_connectors` | each application's connector state and nothing else |

Use full when the connector offers it. Fall back to state only when it does not, and say so: the report
then cannot see a failing source, a source with no recent data or a missing component, and an
application with any of those still reads Running.

## Status rules (first match wins, full mode)

| Status | Condition |
|---|---|
| **Error** | State `Aborted`, or an error message, or an `errorStates` entry with `errors`, or whose last alert was raised in the hour before the pull (older alerts do not count) |
| **Disabled** | Any source has `disable` set |
| **Attention** | Inactive, or a missing component, or state `WaitingForConsent` or `Aborted` |
| **Running** | Traffic in the last 24 hours, or connector state `Running` |
| **Other** | Anything else |

State-only mode maps the connector state alone: `Running` is Running, `Aborted` is Error,
`WaitingForConsent` and `Inactive` are Attention, anything else is Other.

- **Traffic:** input is the 24-hour bytes received by the application's sources; output is the bytes
  written by its sinks. A resource source (Office 365 resource watch, Qualys, LDAP, SentinelOne API and the
  others in `NO_CONNECTION` in the script) does not count unless it is connected to a router. An
  application whose only sources are resource sources has no traffic view and is Running when its
  connector is.
- **Inactive:** not in error, no traffic, and either state `Inactive` or a component (a non-resource
  source, router, pipe or sink) with no entry in `lastActive`, which covers the 24-hour window the
  connector reports.
- **Missing component:** a pending `action` names a resource that is not a live component. Resource types
  `collector`, `datalakeIndex`, `resourceGroup` and `routerSource` are ignored; a `routerPipe` id is split
  on `-` first; an `invitation` counts only while the state is `WaitingForConsent`.
- **Error bytes** are shown per component but do not change the status, as on the page.
- **Resource feeds** (optional `list_resource_dumps`): each feed's age and record count. A feed is stale
  when its dump is over a day old or has no records. This is informational and never changes a status: a
  connector can read Running while its feed is weeks old.

## Data integrity (non-negotiable)

Every figure is computed by `scripts/evaluate_health.py` from the saved results and only laid out by
`scripts/build_report.py`. Never type a number into the HTML. If the connector list cannot be collected,
stop: a failed pull is not a healthy tenant. Say "status unknown" for anything that was not collected.

## Credentials (read this before collecting)

`list_connector_config` and `list_connectors` return credentials in clear text (client secrets, HEC and
integration tokens, token URLs). Never keep the raw result in `WORKDIR` or the repository, never quote it,
and never paste it into the report. Run the matching script, which keeps only what the evaluation needs,
then delete the raw file.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. For a provider-wide view repeat per account; never merge tenants into one report. |
| Window | The 24 hours the connector reports. |

## Step 1 — Collect

| Mode | Call | Reduce |
|---|---|---|
| full | `list_connector_config(account)`; the result is large, so the harness saves it to a file | `python3 scripts/scrub_config.py --config RAW.json --out WORKDIR/apps.json`, then delete RAW |
| state only | `list_connectors(account)` | `python3 scripts/reduce_connectors.py --raw RAW.json --out WORKDIR/connectors.json`, then delete RAW |
| both, optional | `list_resource_dumps(account)` | save as `WORKDIR/dumps.json` |

If a result arrives inline instead of as a file, write it to a scratch file outside `WORKDIR` and run the
script on that.

## Step 2 — Evaluate

```bash
python3 scripts/evaluate_health.py --apps WORKDIR/apps.json [--dumps WORKDIR/dumps.json] --out WORKDIR/health.json
python3 scripts/evaluate_health.py --connectors WORKDIR/connectors.json [--dumps WORKDIR/dumps.json] --out WORKDIR/health.json
```

`--captured-at` defaults to the capture time in `apps.json`, else now (UTC). The fields of `health.json` are
listed in `references/health_json.md`.

## Step 3 — Build

```bash
python3 scripts/build_report.py --health WORKDIR/health.json --tenant acme --tenant-name "Example Corp" \
  --site Develop --out WORKDIR/report.html --csv WORKDIR/applications.csv
```

## Step 4 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp Installed Applications Health Report"
```

The renderer needs Playwright and a Chrome or Chromium binary. It looks for Chrome in the usual macOS,
Linux and Windows paths (override with `--chrome` or `CHROME_PATH`) and for Playwright in the current
folder, the input's folder and the global npm root.

QA before delivering: if `pdftoppm` exists, look at every page (footer on every page, no clipped text,
tables inside the page); otherwise check in print media that each table has `scrollWidth <= clientWidth`.
If you cannot look at the pages, say so in the hand-off.

## Reading the result

- Lead with the counts, for example "10 running / 1 attention / 2 error".
- **Error** first: name the application and quote its state or message.
- **Attention:** say which reason (waiting for consent, missing component, inactive).
- **Running is not proof of fresh data.** The report lists resource sources with the age of their newest
  dump, informational only.
- **Inactive** can be correct and harmless, for example a syslog listener nobody sends to.
- An application with no sources (for example the AI assistant) is Running when its connector is.
- Repeat the limits listed in `health.json`, especially when the run was state only.

## Accuracy discipline

- Only the latest alert of each error state is kept, so alert history is not shown.
- The Error, Disabled and Missing paths are verified on synthetic data built from a real result, not on a
  real failing application: no tenant tested had an error state.
- Quote counters; do not paraphrase them.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the HTML and PDF
first. Do not post automatically.
