---
name: health-status-report
version: 1.2.0
description: >-
  Produce an Installed Applications Health report for ONE Ingext/Fluency tenant as HTML, PDF and a
  per-application CSV, using the same status logic as the Fluency 9 Applications page: each
  installed application instance is Running, Error, Attention, Disabled or Other, with its
  last-24-hour traffic, last-active time and error bytes by component where the connector provides
  them. Renders the health.json that the application-health skill produces. USE THIS SKILL for
  "health report for tenant X", "which of our applications are in error", "applications status
  report". DO NOT use it for platform-wide health (ingext-health-monitor), for one incident, or to
  collect and evaluate the health data itself (application-health). PREREQUISITE: install the
  application-health skill first; this report cannot run without its health.json.
---

# Installed Applications Health Report

> **Prerequisite: install the `application-health` skill before using this one.** This report does not
> collect or evaluate anything itself; it renders the `health.json` that `application-health` writes.
> Without that skill installed there is nothing to render.

Answers: which installed applications are running, which are in error, and which need
attention? It is read-only and never changes the tenant. The collection and the status logic live in
the **application-health** skill, so this report agrees with that skill, with the Fluency 9
Applications page and with every other report that reads its `health.json`. This skill lays the result
out for a customer.

`ingext-health-monitor` answers the platform-wide questions (users logging in, queue backlog,
egress). This skill answers the per-application one.

## Data integrity (non-negotiable)

Every figure is computed by `application-health` from the saved connector results and only laid out
here. Never type a number into the HTML. If the connector list cannot be collected, stop: a failed
pull is not a healthy tenant. Say "status unknown" for anything that was not collected.

## Step 1 — Get health.json

Run the **application-health** skill for the tenant. Use its full mode (`list_connector_config`) when the
connector has that tool; its state-only fallback (`list_connectors`) gives a thinner report with no
traffic, errors or last-active times, and the report says so. Add `list_resource_dumps` to show how old
each resource feed is. The result is `WORKDIR/health.json`. Credentials are removed by that skill's
scripts; never keep a raw connector result in `WORKDIR`.

## Step 2 — Build

```bash
python3 scripts/build_report.py --health WORKDIR/health.json --tenant acme --tenant-name "Example Corp" \
  --site Develop --out WORKDIR/report.html --csv WORKDIR/applications.csv
```

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
- **Running is not proof of fresh data.** The report lists resource sources with the age of their
  newest dump, informational only.
- **Inactive** can be correct and harmless, for example a syslog listener nobody sends to.
- Repeat the limits listed in `health.json`, especially when the run was state only.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically.
