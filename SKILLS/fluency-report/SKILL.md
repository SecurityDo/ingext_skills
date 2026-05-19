---
name: fluency-report
description: Run a Fluency / Ingext FPL report and turn its result into a single-page HTML summary tailored to the data — KPI cards, charts, tables, and a short written interpretation. Trigger when the user says any phrasing of "run a Fluency report" or "run an Ingext report" — e.g. "run a Fluency report", "run the Ingext IngestionRate report", "give me a Fluency report on top alerted users", "build a Fluency summary for the IngestionRate report". The skill ALWAYS starts by listing the available reports via the FPL `list_reports` tool and matching the user's request against that list. If no report matches, the skill responds that the report doesn't exist and lists what does exist — it never invents or substitutes a report. Once a real match is found, it runs the report, reads the result, and produces a Fluency-branded single-page HTML summary using the bundled `assets/base_template.html` plus the widget recipes in `references/widget_recipes.md`.
---

# Fluency / Ingext Report

Run any Fluency / Ingext FPL report on demand and turn its `objects[]`
result into a single-page, browser-friendly HTML summary — KPI cards,
charts, tables, and a short written interpretation tailored to whatever
data came back. The HTML is the deliverable; the user opens it in a
browser.

This skill works against **any** report in the user's FPL catalog and
synthesizes the layout from the data shape. Some reports may have
dedicated partner skills with hand-built templates for specific data
shapes — if such a skill is installed and the user's request matches one
of its reports, defer to it for a richer presentation.

## When to use

Trigger on any phrasing of the form **"run a Fluency report"** or
**"run an Ingext report"**. Recognised forms include:

- "Run a Fluency report"
- "Run an Ingext report"
- "Run the Fluency `<ReportName>` report"
- "Give me a Fluency summary on `<topic>`"
- "Build an Ingext report for `<ReportName>`"
- "Pull the Fluency `<ReportName>` report and summarize it"

Fluency and Ingext are interchangeable in the user's vocabulary — Ingext
is the company, Fluency is the product. Treat both triggers identically.

### When to defer

If a dedicated partner skill is installed and the user's request matches
one of its supported reports, defer to that skill — its hand-built
templates produce a nicer-looking page for those specific data shapes.

## Pipeline

The skill is mostly an orchestration: the agent does the work, the bundled
files give it the building blocks.

```
1. list_reports                          (FPL MCP tool)
2. match user query → report name
   ├─ no match  → respond "no such report", list what's available, stop
   └─ match     → continue
3. run_report (sync or non-sync — see Step 3 detail below)
   ├─ sync mode  → result returned directly
   └─ non-sync  → poll get_report_task until completed/aborted
                  → call get_report_result to fetch data
4. read result.objects[]
5. compose body from widget recipes      (references/widget_recipes.md)
6. fill the bundled base template        (assets/base_template.html)
7. write <output-dir>/<report-name>.html
8. share computer:// link to the .html
```

### Step 1 — list available reports

Always call `list_reports` first, even if the user named a specific report.
This is the source of truth for what's runnable; matching against the
user's training data or guesses is not acceptable.

- Tool: `mcp__…__list_reports`
- Save the returned list of report names. The agent uses this list both
  to validate the user's request and to render an "available reports"
  fallback if no match is found.

### Step 2 — match the user's request against the catalog

Try matches in this order:

1. **Exact, case-insensitive** match against a report name in the catalog.
2. **Substring** match (user's query as a contiguous substring of a
   catalog name, or vice-versa). If exactly one match, use it. If
   multiple, ask the user which one.
3. **Token overlap** — split user query and catalog names on `_` and
   non-alphanumerics, find the catalog name that shares the most tokens.
   Only accept this as a match if it's clearly unambiguous.

If no match passes any of these, **stop**. Respond with:

> The report `<query>` doesn't exist in your Fluency catalog. Available
> reports are: `<bullet list of catalog names>`. Do you want to run one
> of these?

Do NOT invent a report, do NOT substitute a similar one, do NOT proceed.
The user must pick a real catalog entry.

If the user said something generic like "run a Fluency report" with no
report name at all, list the catalog and ask which one they want.

### Step 3 — run the matched report

Choose the mode based on what the user requested. Default to **sync mode**
unless the user explicitly says "non-sync", "async", or "background".

#### Sync mode (default)

- Tool: `mcp__…__run_report`
- `name`: the matched report name (exact, as it appears in the catalog)
- `syncMode`: `true`
- `arguments`: pass `from`, `to`, `id`, etc. only if the user specified them

The response contains the full result directly. Save it:

```bash
echo '<the run_report result>' > /tmp/fluency_report.json
```

Skip to **Step 4**.

#### Non-sync mode

Use this when the user says "run in non-sync mode", "async", or "background".

**3a.** Call `mcp__…__run_report` **without** `syncMode` (or with `syncMode: false`).
The response will contain a task object with an `id` and a `status` field.
Record the `task_id`.

**3b.** Poll `mcp__…__get_report_task` with `task_id` in a loop:

```
while true:
    response = get_report_task(task_id)
    status   = response.status          # e.g. "registered", "running", "completed", "aborted"

    if status == "registered" or status == "running":
        wait 5 seconds
        continue
    elif status == "completed" or status == "aborted":
        break
    else:
        # unexpected status — surface it and stop
        raise error
```

Tell the user the current status on each poll so they can see progress
(e.g. "Task registered, waiting…", "Task running, waiting…").

**3c.** Once status is `"completed"` or `"aborted"`, call
`mcp__…__get_report_result` with `task_id` to fetch the full result object.
Save it:

```bash
echo '<the get_report_result result>' > /tmp/fluency_report.json
```

If status was `"aborted"`, render a minimal error page explaining the report
was aborted, and stop — do not attempt to parse partial data.

### Step 4 — read the result

The result has shape `{"objects": [{"name": "...", "table": {"columns":
[...], "rows": [...]}}, ...]}`. Walk the objects and decide what each one
should become in the HTML. Heuristics:

- **Single-row object** with a few scalar columns → a KPI card. If
  there are several of these, group them into a KPI strip.
- **Multi-row object with a numeric column** → a chart. Time-series
  (with a date/timestamp column) → line chart. Categorical with `key` and
  `doc_count` → bar chart or donut. Top-N tables → bar chart with rule
  names on the axis.
- **Multi-row object with several columns** → a table panel, one row per
  catalog row. If there's an obvious severity / score / status column,
  colour the rows accordingly.
- **`distributor`-style branding object** → footer / header chrome.

Use judgement — don't render every object identically. The goal is a
report a security operator would actually want to read.

### Step 5 — compose the body

Open `references/widget_recipes.md` for copy-paste snippets. Common
building blocks:

- **KPI card** — single big number + label + small note line
- **KPI strip** — 4–6 KPI cards in a row
- **Table panel** — title + subtitle + a `<table>` with severity-coded rows
- **Line chart** — Chart.js line, for time-series counts or scores
- **Bar chart** — Chart.js bar, for top-N categorical
- **Donut chart** — Chart.js doughnut, for category distribution
- **Summary block** — short paragraph interpreting the highest-signal
  numbers (e.g. "Alert volume is up 40% week-over-week, driven by a single
  rule")
- **Next steps** — three to six numbered actions, each with a "this
  week / within 14 days / quarterly" timing tag

Layout the body as a CSS grid of panels. Two or three columns scale well
across screen sizes; the base template's container is responsive.

### Step 6 — fill the base template

The bundled template `assets/base_template.html` has these placeholders:

| Placeholder | Fill with |
|---|---|
| `{{report_title}}` | The matched report's name, humanised (e.g. `Domain_Monitoring_Report` → "Domain Monitoring") |
| `{{report_subtitle}}` | One-line description of what the report covers |
| `{{report_date}}` | The current date, formatted `DD MMM YYYY` |
| `{{report_meta}}` | Optional period / data-window line, leading with ` · ` (e.g. ` · Last 14 days`) |
| `{{kpi_strip}}` | The KPI cards row (HTML fragment) |
| `{{main_grid}}` | The grid of charts and tables (HTML fragment) |
| `{{summary_html}}` | A 2–4 sentence interpretation of the data |
| `{{next_steps_items}}` | Six (or fewer) numbered next-step blocks |
| `{{footer_data_date}}` | The current date, formatted `DD MMM YYYY` |
| `{{footer_page_info}}` | `Fluency Report · the human title` |

Substitute via simple `str.replace`. Don't introduce a templating engine.

Branding is hardcoded — every report shows the Fluency / Ingext logo in
the header and "powered by Fluency" in the footer. There's no
distributor / customer-branded variant; the agent doesn't need to pull
or override anything to get the chrome right.

### Step 7 — write the file and copy the logo asset

Before writing the HTML, ensure the output directory has an `assets/` subfolder
containing `logo2.png`. Copy it from the skill's own `assets/logo2.png`:

```bash
mkdir -p <output-dir>/assets
cp <skill-dir>/assets/logo2.png <output-dir>/assets/logo2.png
```

The base template references the logo as `assets/logo2.png` (relative to the
HTML file), so this copy step is required for the logo to appear.

### Step 7b — write the file

Output stem: lowercased, snake-cased report name (e.g.
`domain_monitoring_report.html`). Write the populated HTML
to `<output-dir>/<stem>.html`.

### Step 8 — share

Provide a `computer://` link to the `.html` file. Add a short summary in
chat (one or two sentences) calling out the highest-signal finding from
the data.

## Output

A single HTML file:

- Self-contained (pure SVG/CSS charts — no external JS dependencies, all styling inline)
- Browser-friendly (responsive width, readable on a laptop screen)
- Fluency-branded chrome (header bar, footer with distributor, palette)
- A body that's tailored to the report's data shape

The HTML is the primary deliverable. The template is designed to be
**A4-native** — `max-width: 760px`, 12px base font, compact spacing — so it
prints at 1:1 scale on A4 paper without any scaling or text shrinkage.

If the user wants a PDF, use the **html-to-pdf** skill immediately after
generating the HTML. The correct flags are:

```bash
# Standard A4 PDF — runs without scaling, single page
--format=A4 --margin=12mm,12mm,12mm,12mm
```

Do not use `--scale` or `--one-page` unless the report is unusually dense
and overflows A4 at 1:1.

## Failure modes

- **Report doesn't exist.** Don't run anything. Reply with the catalog
  list and ask the user to pick a real report. See Step 2.
- **`list_reports` returns empty.** The user has no FPL connector
  configured, or no reports are visible to their account. Tell them
  plainly and stop.
- **`run_report` errors out.** Surface the error, don't try to render a
  half-empty page.
- **Result has no `objects[]`.** Render a minimal page with the report
  name and a note that it returned no data.
- **Bundled template missing.** Re-installing the skill is the fix.

## Layout

```
fluency_report/
├── SKILL.md
├── assets/
│   └── base_template.html        # Fluency-branded chrome with named placeholders
└── references/
    └── widget_recipes.md         # Copy-paste HTML/JS snippets for KPIs, charts, tables
```

## Reference

- `assets/base_template.html` — the populated HTML scaffold; placeholders
  listed in Step 6 above
- `references/widget_recipes.md` — every widget the agent might want to
  drop into `{{main_grid}}` or `{{kpi_strip}}`, with the exact CSS class
  names the base template ships with
