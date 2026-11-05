---
name: fluency-report
version: 1.0.2
description: Run a Fluency / Ingext FPL report and turn its result into a branded HTML report (and matching PDF) tailored to the data — KPI strip, charts, tables, and written analysis. Trigger when the user says any phrasing of "run a Fluency report" or "run an Ingext report" — e.g. "run a Fluency report", "run the Ingext IngestionRate report", "give me a Fluency report on top alerted users", "build a Fluency summary for the IngestionRate report". The skill ALWAYS starts by listing the available reports via the FPL `list_reports` tool and matching the user's request against that list. If no report matches, the skill responds that the report doesn't exist and lists what does exist — it never invents or substitutes a report. Once a real match is found, it runs the report, reads the result, and produces a Fluency-branded HTML report using the bundled `assets/base_template.html` plus the widget recipes in `references/widget_recipes.md`.
---

# Fluency / Ingext Report

Run any Fluency / Ingext FPL report on demand and turn its `objects[]`
result into a **executive-grade HTML report** in the Fluency editorial style — a title block with KPI strip,
a numbered section per domain of the data, bars and ranked tables, written
analysis, recommended actions, and a methodology block, all tailored to whatever
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

To **build or fix** a report or dashboard (panels, layout, charts that read zero) rather than
run one, use **fpl-report-dashboard**.

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

Open `references/widget_recipes.md` for the exact markup. **All charts are inline SVG or CSS — do NOT add Chart.js or any
CDN/script dependency; the render environment blocks external scripts.** The look is the Fluency Security posture style:
white paper, IBM Plex, black rules, one blue / one red / one amber. No cards, gradients or extra colours.

The document is one continuous editorial page flow, not a stack of dashboard panels:

1. **Title block** — plain title, a one- or two-sentence lead, a gray mono meta line.
2. **KPI strip** — 4–5 headline numbers, each with a mono caps label and (where useful) a status tag.
3. **Three-column band** (optional) — *01 What is exposed · 02 What is already right · 03 What to fix first*.
4. **§1 Executive summary** — prose; a gray callout for caveats; the black **Net read** box.
5. **§2 … §N** — one section per domain of the data: a sentence of framing, then a table **or** bars, then a small gray footnote.
6. **Recommended actions** — rows with a timing label, a P1 / P2 / P3 tag and the action.
7. **Methodology** — source, window, how figures were derived, limits.

Draw charts with the helpers in `scripts/fluency_brand.py` (vertical, grouped and stacked columns, grouped and stacked bars, heatmap, scatter, line, donut; see the recipes). Map `objects[]` onto sections: scalar/overview objects → KPI strip and §1; ranked top-N objects → a section with a table or bars;
time series → an inline SVG line (black line, gray grid). Do not render every object the same way, and do not stop at one page.

#### Explain the results, don't just display them

Lead with the **so-what**; quantify and compare (shares, ratios, deltas); name the specific users, IPs, rules or values;
say what to verify and why; separate routine signal from anomalies. Avoid empty intensifiers. Keep paragraphs short and bold at
most one phrase per paragraph.

### Step 6 — fill the base template

`assets/base_template.html` has these placeholders (details and markup in `references/widget_recipes.md`). Fill them with plain
`str.replace` in code — **do not print or cat the template file** (it embeds the fonts and is large):

| Placeholder | Fill with |
|---|---|
| `{{report_title}}` | Plain title, e.g. `Acme Inc — Office 365 Exchange activity` (no markup) |
| `{{cover_eyebrow}}` | Document type shown top right in gray mono caps, e.g. `Network security review` |
| `{{report_lead}}` | 1–2 sentence description: what the report covers and the headline finding |
| `{{cover_meta}}` | Gray mono meta line: tenant · period · source · access (plain text, `·` separated) |
| `{{report_date}}` | `DD MMM YYYY` |
| `{{cover_kpis}}` | 4–5 `.kpi` cells |
| `{{report_band}}` | Optional three-column band, else `""` |
| `{{sections}}` | All `§N` sections concatenated |
| `{{report_actions}}` | Optional recommended-actions block, else `""` |
| `{{report_method}}` | Methodology paragraphs |
| `{{footer_page_info}}` | `Title · Tenant` |
| `{{footer_data_date}}` | `DD MMM YYYY` |

Branding is fixed: brandline (lock mark + FLUENCY SECURITY), black title, closing footer line. There is no customer-branded variant.

### Step 7 — write the file

The template is self-contained (fonts and mark are inlined), so there is no assets folder to copy. Output stem: lowercased,
snake-cased report name (e.g. `domain_monitoring_report.html`). Write the populated HTML to `<output-dir>/<stem>.html`.

For a PDF, run `node scripts/render_pdf.mjs --input <stem>.html --output <stem>.pdf` (US Letter, same CSS as the HTML, no
paged footer; needs Playwright and Chromium). The PDF matches the HTML.

### Step 8 — share

Provide a `computer://` link to the `.html` file. Add a short summary in
chat (one or two sentences) calling out the highest-signal finding from
the data.

## Output

A single self-contained HTML file in the Fluency editorial style, plus an optional PDF rendered from it:

- Pure HTML/CSS/SVG — no external scripts, fonts or images; renders identically offline
- Brandline (lock mark + FLUENCY SECURITY), black title block, KPI strip, §-numbered sections, mono tables, closing footer line
- Prints to US Letter with the same styling; the PDF is generated from the HTML, not rebuilt separately

Build the report to flow across as many pages as the content needs; prefer completeness (full top-N tables, not just a few rows).
Only fit it onto one page when the user asks for a one-pager.

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
│   └── base_template.html        # Fluency editorial template with named placeholders
└── references/
    └── widget_recipes.md         # Copy-paste HTML for KPIs, bands, sections, tables, bars, actions
```

## Reference

- `assets/base_template.html` — the populated HTML scaffold; placeholders
  listed in Step 6 above
- `references/widget_recipes.md` — every widget the agent might want to
  drop into `{{cover_kpis}}`, `{{sections}}` or `{{report_actions}}`, with the exact CSS class
  names the base template ships with


## Chart gallery: the source of truth

`assets/chart_gallery.html` / `assets/chart_gallery.pdf` show every chart, table and component with the exact `fluency_brand` call that draws it.
It is generated by `scripts/chart_gallery.py` from the same helpers the reports use. Report scripts and report skills draw charts only through
these helpers (never hand-written SVG, Chart.js or inline bar markup). To add a component: write it in `fluency_brand.py`, add an entry to
`ENTRIES` in `chart_gallery.py`, run `python3 scripts/chart_gallery.py`.
