---
name: application-health
version: 1.0.0
description: >-
  Work out the health of every installed application on ONE Ingext/Fluency tenant, with the same
  status logic as the Fluency 9 Applications page (Running, Error, Attention, Disabled, Other),
  and save it as health.json for other skills and reports to use. USE THIS SKILL for "are the
  applications healthy", "which connectors are in error", "is everything running", "what is the
  state of the installed applications", or as the first step of health-status-report and
  CISO_monthly_report. Reads the tenant's connector (list_connector_config where the connector has
  it, else list_connectors), removes credentials, and evaluates locally. Read-only. DO NOT use it
  for site-wide health such as logins, queues and egress (ingext-health-monitor) or for a
  finished report document (health-status-report).
---

# Application health

Decides, for each installed application instance, whether it is Running, in Error, needs Attention,
has a Disabled source, or is Other, and writes the result to `health.json`. It is read-only and never
changes the tenant. Other skills reuse it instead of repeating the logic:

- `health-status-report` renders `health.json` as a customer report (HTML, PDF, CSV).
- `CISO_monthly_report` reads `health.json` for the coverage and health section.

## Two modes

| Mode | Collect with | What you get |
|---|---|---|
| **full** | `list_connector_config` (only some connectors have it) | state, errors and alerts, live components, last-active times, 24-hour traffic in and out, error bytes, the disable setting |
| **state only** | `list_connectors` | each application's connector state and nothing else |

Use full when the connector offers it. Fall back to state only when it does not, and say so: the
report then cannot see a failing source, a source with no recent data or a missing component, and an
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
  written by its sinks. A resource source (Office 365 resource watch, Qualys, LDAP, SentinelOne API and
  the others in `NO_CONNECTION` in the script) does not count unless it is connected to a router. An
  application whose only sources are resource sources has no traffic view and is Running when its
  connector is.
- **Inactive:** not in error, no traffic, and either state `Inactive` or a component (a non-resource
  source, router, pipe or sink) with no entry in `lastActive`, which covers the 24-hour window the
  connector reports.
- **Missing component:** a pending `action` names a resource that is not a live component. Resource
  types `collector`, `datalakeIndex`, `resourceGroup` and `routerSource` are ignored; a `routerPipe` id is
  split on `-` first; an `invitation` counts only while the state is `WaitingForConsent`.
- **Error bytes** are kept per component but do not change the status, as on the page.
- **Resource feeds** (optional `list_resource_dumps`): each feed's age and record count. A feed is stale
  when its dump is over a day old or has no records. This is informational and never changes a status:
  a connector can read Running while its feed is weeks old.

## Credentials (read this before collecting)

`list_connector_config` and `list_connectors` return credentials in clear text (client secrets, HEC and
integration tokens, token URLs). Never keep the raw result in the work folder or the repository, never
quote it, and never paste it into a report. Run the matching script, which keeps only what the
evaluation needs, then delete the raw file.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names. Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. Repeat per account for a provider-wide view; never merge tenants. |

## Step 1 — Collect

| Mode | Call | Reduce |
|---|---|---|
| full | `list_connector_config(account)`; the result is large, so the harness saves it to a file | `python3 scripts/scrub_config.py --config RAW.json --out WORKDIR/apps.json`, then delete RAW |
| state only | `list_connectors(account)` | `python3 scripts/reduce_connectors.py --raw RAW.json --out WORKDIR/connectors.json`, then delete RAW |
| both, optional | `list_resource_dumps(account)` | save as `WORKDIR/dumps.json` |

If a result arrives inline instead of as a file, write it to a scratch file outside the work folder
and run the script on that. If the connector list cannot be collected, stop: a failed pull is not a
healthy tenant.

## Step 2 — Evaluate

```bash
python3 scripts/evaluate_health.py --apps WORKDIR/apps.json [--dumps WORKDIR/dumps.json] --out WORKDIR/health.json
python3 scripts/evaluate_health.py --connectors WORKDIR/connectors.json [--dumps WORKDIR/dumps.json] --out WORKDIR/health.json
```

`--captured-at` defaults to the capture time in `apps.json`, else now (UTC). The fields of `health.json`
are listed in `references/health_json.md`.

## Reading the result

- Lead with the counts, for example "10 running / 1 attention / 2 error".
- **Error** first: name the application and quote its state or message.
- **Attention:** say which reason (waiting for consent, missing component, inactive).
- **Running is not proof of fresh data.** Read the resource-feed ages next to the counts.
- **Inactive** can be correct and harmless, for example a syslog listener nobody sends to.
- Always repeat the `limits` in `health.json`, especially in state-only mode.

## Accuracy discipline

- Every value is computed by `scripts/evaluate_health.py`; never type a figure.
- Only the latest alert of each error state is kept, so alert history is not shown.
- The Error, Disabled and Missing paths are verified on synthetic data built from a real result, not
  on a real failing application: no tenant tested had an error state.
- Quote counters; do not paraphrase them.
