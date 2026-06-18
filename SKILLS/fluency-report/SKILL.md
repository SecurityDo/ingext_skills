---
name: fluency-report
version: 1.0.0
description: Run a Fluency / Ingext FPL report and turn its result into a single-page HTML summary tailored to the data — KPI cards, charts, tables, and a short written interpretation. Trigger when the user says any phrasing of "run a Fluency report" or "run an Ingext report" — e.g. "run a Fluency report", "run the Ingext IngestionRate report", "give me a Fluency report on top alerted users", "build a Fluency summary for the IngestionRate report". The skill ALWAYS starts by listing the available reports via the FPL `list_reports` tool and matching the user's request against that list. If no report matches, the skill responds that the report doesn't exist and lists what does exist — it never invents or substitutes a report. Once a real match is found, it runs the report, reads the result, and produces a Fluency-branded single-page HTML summary using the bundled `assets/base_template.html` plus the widget recipes in `references/widget_recipes.md`.
---

# Fluency / Ingext Report

Run any Fluency / Ingext FPL report on demand and turn its `objects[]`
result into a **multi-page, executive-grade HTML report** — a branded cover,
a numbered section per domain of the data, charts, ranked tables, written
analysis, an action plan, and a methodology appendix, all tailored to whatever
data came back. The HTML is the deliverable; the user opens it in a browser.

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

#### Time arguments — always ISO 8601 / RFC3339

When a report takes a time window (`from` / `to`), **always bind them as
absolute ISO 8601 / RFC3339 UTC timestamps**, e.g. `2026-06-04T22:01:32Z`.
Do **not** pass relative expressions like `-24h`, `now`, or FortiGate-style
snap syntax (`-1d@d`, `@d`) as argument values — even when those appear as
the report's stored `defaultValue`, they are not reliably parsed when passed
through `run_report`, and a malformed window can make the report hang until
it times out.

Resolve the user's phrasing to a concrete UTC range first:

- "last 24 hours" → `from = now − 24h`, `to = now`
- "yesterday" → previous calendar day `00:00:00Z` … `23:59:59Z`
- "last 7 days" → `from = now − 7d`, `to = now`
- an explicit range → convert both endpoints to `…Z` UTC

Compute the timestamps with the shell (e.g. `date -u +"%Y-%m-%dT%H:%M:%SZ"`
and `date -u -d '24 hours ago' …`) so the values are exact, then pass them
as `arguments`. If the user specifies no window, omit `from`/`to` and let the
report apply its own defaults.

#### Sync mode (default)

- Tool: `mcp__…__run_report`
- `name`: the matched report name (exact, as it appears in the catalog)
- `syncMode`: `true`
- `arguments`: pass `from`, `to`, `id`, etc. only if the user specified a
  window — and bind `from`/`to` as ISO 8601 / RFC3339 UTC timestamps (see
  "Time arguments" above)

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

Open `references/widget_recipes.md` for copy-paste snippets. **All charts
are pure inline SVG or CSS — do NOT add Chart.js or any other CDN/script
dependency; the Cowork render environment blocks external scripts.** The
recipes file is the source of truth for the exact class names and markup.

#### Build an executive, multi-page document — not a single dashboard

The template is a **paginated executive report**: a full-page **cover** plus a
series of numbered **section sheets** (`.sheet`), each starting on a fresh A4
page with its own header (numbered eyebrow + title + subtitle) and footer. You
fill the cover placeholders, then assemble the section sheets into
`{{sections}}`. Aim for the look and depth of a partner-grade report: a cover
with embedded KPIs, an executive summary, one section per domain of the data,
a governance / action-plan section, and a methodology appendix.

Standard structure (adapt the section names to the report's domain — the
`widget_recipes.md` "Report structure blueprint" has the full model):

1. **Cover** — title (with a red accent line), executive lead sentence,
   meta fields (period / generated / tenant / source), 4–5 headline KPIs.
2. **01 · Executive Summary** — a lead paragraph, the Healthy/Watch/Act
   callout band, a two-column posture interpretation + risk gauge, and a
   "bottom line" note.
3. **02 … N · One section per domain of the data** — each with a KPI strip or
   ranked detail table, at least one chart (bar / donut / line), and a written
   **Analysis** block. Use the section title as a plain-English question
   ("Who is driving the activity", "Where access came from").
4. **Governance & Recommendations** — high-impact items in tables with
   impact/verdict pills, then the numbered **action plan** (`.action` cards
   with timing pills).
5. **Appendix** — a methodology grid documenting how the figures were derived,
   a disclaimer note, and the brand close.

Map the report's `objects[]` onto these sections: scalar/overview objects →
cover KPIs + Activity Overview; ranked top-N objects → their own detail
sections with a table **and** a chart; anything time-series → a line chart.
Don't render every object identically, and don't stop at one page — a real
report runs several sheets.

Core building blocks:

- **KPI card** — single big number + label + small note line
- **KPI strip** — 4–6 KPI cards in a row
- **Summary block** — short paragraph interpreting the highest-signal
  numbers (e.g. "Alert volume is up 40% week-over-week, driven by a single
  rule"), rendered as a blue-accented lead card
- **Table panel** — title + subtitle + a `<table class="data">` with
  severity-coded rows (`.sev-high/med/low`) and inline `.pill`s
- **Line chart** — pure SVG, for time-series counts or scores (pre-compute
  all `(x,y)` coordinates; the `.svg-chart` / `.chart-*` classes are defined)
- **Bar chart** — pure CSS, for top-N categorical (`.bar-rows` / `.bar-fill`,
  widths as a percentage of the series max)
- **Donut chart** — pure CSS `conic-gradient` (`.donut-ring`), optionally with
  a centred total via `.donut-center`
- **Inline volume bars** — `.vol` / `.vol-fill` for an at-a-glance count
  column inside a table
- **Next steps** — three to six numbered actions, each with a "this
  week / within 14 days / quarterly" timing tag

Richer components shipped by the upgraded template (use them to make the
page read like a briefing, not a data dump):

- **Callout band** — three signal-coded cards (`.callout good/watch/act`)
  for an at-a-glance Healthy / Watch / Act posture read, ideal directly
  under the KPI strip
- **Risk gauge** — a single-figure `conic-gradient` dial (`.gauge`) with a
  centred label and a short interpretation beside it
- **Note strip** — a one-line emphasis banner (`.note`, with `.blue` / `.green`
  tints) for a caveat, data gap, or "bottom line"

Layout the body as a 12-column CSS grid of `.panel`s (`.col-4/5/6/7/8/12`).
Two or three columns scale well; below 640px every panel collapses to full
width automatically.

#### Default composition — use the full toolkit

Unless the user asks for something minimal, **every** report should combine
all four of these, not just a table dump:

1. **KPI strip + summary** — the headline numbers, then a 2–4 sentence
   written interpretation of what they mean.
2. **A callout band** (`.callout good/watch/act`) — translate the data into
   a Healthy / Watch / Act posture read so a non-analyst grasps the takeaway
   at a glance. Add a **risk gauge** or **note strip** when there's a single
   figure or caveat worth spotlighting.
3. **At least one chart** — a bar chart for top-N / categorical data, a donut
   for a part-to-whole split, or a line chart for anything time-series. Charts
   are pure SVG/CSS (no Chart.js). Pick the chart that fits the data shape;
   don't force one.
4. **Full detail tables** — the underlying rows (complete top-N, not just the
   first few), with severity/scope `.pill`s and `.sev-*` row tints where a
   column warrants it.

A good report reads top-down as: *headline → what it means → where to look →
the evidence*.

#### Explain the results, don't just display them

The written word is as important as the widgets. For each major section, add a
short, plain-English interpretation alongside the numbers:

- Lead with the **so-what**: what the figure implies, not just its value
  (e.g. "one destination carries 57% of all bytes — concentration this high
  is normal for backup/CDN flows but warrants a one-time check", not just
  "57%").
- **Quantify and compare**: ratios, shares of total, per-event averages,
  outliers, week-over-week or window-over-window deltas where the data allows.
- **Flag what to verify** and why it matters, distinguishing routine signal
  from genuine anomalies.
- Stay **factual and specific** — name the IPs, users, rules, or values.
  Avoid empty intensifiers ("alarming", "concerning"); let the numbers carry
  the weight.

The panel subtitles, note strips, and callout body text are all good places
to put one-line explanations close to the data they describe.

### Step 6 — fill the base template

The bundled template `assets/base_template.html` is a **multi-page executive
document**: a full-page cover followed by the section sheets you assemble. It
has these placeholders:

| Placeholder | Fill with |
|---|---|
| `{{report_title}}` | The matched report's name, humanised. Wrap the second line in `<span class="accent">…</span>` for the red highlight (e.g. `Office 365 Exchange<br><span class="accent">Activity Review</span>`) |
| `{{cover_eyebrow}}` | Small uppercase kicker above the title (e.g. "Network Security Review") |
| `{{report_lead}}` | 1–2 sentence executive description: what the report covers and the top-line finding |
| `{{confidential_tag}}` | e.g. `Confidential · Internal` |
| `{{cover_meta}}` | 3–4 `.meta-field` blocks — reporting period, generated date, tenant, source |
| `{{cover_kpis}}` | 4–5 `.cover-kpi` cards — the headline numbers |
| `{{sections}}` | Every section sheet, concatenated (see Step 5) |
| `{{footer_page_info}}` | `Fluency Report · <human title> · <tenant>` |

Substitute via simple `str.replace`. Don't introduce a templating engine. The
exact markup for the cover fields and every section component is in
`references/widget_recipes.md`.

Branding is hardcoded — the dark **hero header** shows the Fluency / Ingext
logo inside a white "logo chip", and the footer reads "powered by Fluency".
There's no distributor / customer-branded variant; the agent doesn't need
to pull or override anything to get the chrome right. `{{report_title}}` and
`{{report_subtitle}}` render in the hero; the subtitle has room for a full
sentence describing what the report covers, so use it.

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
- Fluency-branded chrome (dark cover with logo chip + Confidential tag, per-section footers reading "powered by Fluency", brand palette)
- A multi-page, sectioned executive document tailored to the report's data

The HTML is the primary deliverable. It renders as a **cover page plus a stack
of section sheets** (each `width: 800px`, ~12.5px base font). For print / PDF
the `@media print` rules drop the floating-card chrome and put the cover and
each section on its own A4 page at 1:1 scale.

**Multi-page by default.** Unless the user explicitly asks for a single page
(e.g. "fit it on one page", "one-pager"), build the report to flow naturally
across **multiple A4 pages**. Don't compress or drop content to squeeze it
onto one sheet — prefer completeness: a full KPI strip, the summary, callout
band, the relevant charts, full top-N tables (not just the top few rows), a
methodology/note strip where useful, and the next-steps block. The print CSS
keeps each card, panel, and table row intact across page boundaries, so a
longer body paginates cleanly. Only collapse to a single page when the user
asks for it.

If the user wants a PDF, use the **html-to-pdf** skill immediately after
generating the HTML. The correct flags are:

```bash
# Standard A4 PDF — multi-page, no scaling; content flows across pages
--format=A4 --margin=12mm,12mm,12mm,12mm
```

Render multi-page by default — do **not** pass `--one-page` or `--scale`
unless the user explicitly asked for a single-page output. If they did,
add `--one-page` (and only then) so the whole report is collapsed onto one
sheet.

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
