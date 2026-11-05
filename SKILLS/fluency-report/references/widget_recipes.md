# Widget Recipes — Fluency editorial report

Copy-paste HTML for a Fluency report. The look is the Fluency Security **posture** style: white paper,
IBM Plex Sans body with IBM Plex Mono labels and numbers, a brandline over a black rule, a large black
title, a KPI strip with status tags, a three-column band, `§N` sections of flat prose, mono tables,
black/gray/blue bars, one gray callout and one black "Net read" box, recommended actions and a
methodology block. **No cards, no gradients, no rounded boxes, no Chart.js or CDN scripts** — everything is
HTML/CSS or inline SVG, and the HTML prints to US Letter PDF unchanged.

Palette (use only these): ink `#111`, text `#242424`, gray `#777`, rules `#d8d8d8`, **red `#b3242e`**
(P1 / exposed), **blue `#175d9a`** (links, "clean", lead bar), **amber `#a06c00`** (review). Never add other colours.

## Template placeholders (`assets/base_template.html`)

| Placeholder | Fill with |
|---|---|
| `{{report_title}}` | Plain title, e.g. `Acme Inc — Microsoft 365 identity & access posture`. No markup. |
| `{{cover_eyebrow}}` | Document type for the brandline, e.g. `Microsoft 365 identity & access posture` (shows in gray mono caps, top right). |
| `{{report_lead}}` | 1–2 sentences: what the report covers and the headline finding. |
| `{{cover_meta}}` | Gray mono meta line: `Acme Inc (acme.example) · Tenant acme · 14 days · Read-only`. Plain text, `·` separated. |
| `{{report_date}}` | `DD MMM YYYY`. |
| `{{cover_kpis}}` | 4–5 `.kpi` cells (below). |
| `{{report_band}}` | Optional three-column band (below) or empty string. |
| `{{sections}}` | All `§N` sections, concatenated. |
| `{{report_actions}}` | Optional recommended-actions block (below) or empty string. |
| `{{report_method}}` | Methodology paragraphs: data source, window, how figures were derived, limits. |
| `{{footer_page_info}}` | `Title · Tenant`. |
| `{{footer_data_date}}` | `DD MMM YYYY`. |

Substitute with plain `str.replace`. Replace every placeholder (use `""` for optional ones). Do not print or cat the template —
it embeds the fonts and is large; fill it in code.

## KPI strip — `{{cover_kpis}}`

Big mono number, mono caps label, optional status tag. `%` and units go in `<small>`. Colour a number `red`/`blue`/`amber` only
when it is the finding.

```html
<div class="kpi"><div class="kpi-value">606</div><div class="kpi-label">Active accounts</div></div>
<div class="kpi"><div class="kpi-value red">54.6<small>%</small></div><div class="kpi-label">MFA coverage</div><span class="tag red">275 without MFA</span></div>
<div class="kpi"><div class="kpi-value">8</div><div class="kpi-label">Global admins</div><span class="tag blue">Baseline ≤ 2</span></div>
<div class="kpi"><div class="kpi-value">100<small>%</small></div><div class="kpi-label">OAuth-app reach</div><span class="tag amber">Review consent</span></div>
<div class="kpi"><div class="kpi-value">3 <small>/ 5</small></div><div class="kpi-label">Audit tests clean</div><span class="tag o-blue">No action</span></div>
```

Tags: `red` filled (problem) · `blue` filled (baseline / info) · `amber` outlined (review) · `o-blue` outlined (clean / no action) ·
`o-red` outlined red · `gray` neutral. Priority tags: `p1` red filled, `p2` amber outlined, `p3` gray.

## Three-column band — `{{report_band}}`

```html
<div class="band">
  <div><h4>01 — What is exposed</h4><p>275 active accounts sign in with a password only…</p></div>
  <div><h4>02 — What is already right</h4><p>No phishable MFA factors…</p></div>
  <div><h4>03 — What to fix first</h4><p>Cut Global Administrators to two named accounts…</p></div>
</div>
```

## Section — the unit of the document

A blue mono `§N` over a bold heading, then flat prose. Use the heading as a plain-English statement or question
("Privileged role footprint", "Who is driving the activity"). Sections flow continuously; do not force page breaks.

```html
<h2><span class="n">1</span>Executive summary</h2>
<p>Lead with the so-what. <strong>Bold the one phrase</strong> per paragraph that carries the finding.</p>
```

(The `§` is added by CSS; put only the number in `.n`.) Sub-headings inside a section are plain `<h3>`.

## Callouts

Gray box, blue left border — a caveat or reading note:

```html
<div class="callout"><h4>Read the MFA figure with two caveats</h4><p>Zero weak-factor findings does not prove…</p></div>
```
Border colour by meaning: default blue, `callout watch` amber, `callout act` red.

Black box with white text — the one "Net read" per report, at the end of the executive summary:

```html
<div class="callout dark"><h4>Net read</h4><p>Where MFA exists it is strong; the gap is coverage, not quality.</p></div>
```

## Tables

Mono caps header over a black rule, thin gray row rules, right-aligned mono numbers (`class="num"` on `th` and `td`),
bold total row (`class="total"`), small gray footnote (`<p class="fn">`). Put tags in cells for status.

```html
<table class="data">
 <colgroup><col style="width:22%"><col style="width:14%"><col style="width:64%"></colgroup>
 <thead><tr><th>Account</th><th class="num">Roles held</th><th>Primary roles (top 2)</th></tr></thead>
 <tbody>
  <tr><td>admin-a</td><td class="num">2</td><td>Global Administrator · SharePoint Administrator</td></tr>
  <tr><td>admin-b</td><td class="num">10</td><td>AI Administrator · Exchange Administrator <span class="tag red">10 roles</span></td></tr>
  <tr class="total"><td>Total</td><td class="num">12</td><td></td></tr>
 </tbody>
</table>
<p class="fn">Account labels are placeholders. Role counts are exact.</p>
```

Result tags in a status column: `<span class="tag fill-amber">Above baseline</span>`, `<span class="tag amber">Review</span>`,
`<span class="tag o-blue">Clean</span>`, `<span class="tag gray">Unknown</span>`. Row emphasis: `class="sev-high|sev-med|sev-low"`
puts a coloured bar on the first cell. Two small tables side by side: wrap in `<div class="two">…</div>`.

## Bars

Label left, mono value right; the leading bar blue, the rest gray on light tracks.

```html
<div class="bar-rows">
  <div class="bar-row"><div class="bar-label">Global Administrator</div><div class="bar-track"><div class="bar-fill blue" style="width:100%"></div></div><div class="bar-val">8</div></div>
  <div class="bar-row"><div class="bar-label">Application Administrator</div><div class="bar-track"><div class="bar-fill" style="width:25%"></div></div><div class="bar-val">2</div></div>
</div>
<p class="fn">25 assignments across 9 accounts.</p>
```
Fills: default gray · `blue` · `ink` (black) · `red` · `amber`. Widths are a percentage of the series maximum.

Part-to-whole (e.g. MFA coverage): `<div class="stack"><i class="k" style="width:54.6%"></i><i class="w" style="width:45.4%"></i></div>`
followed by `<div class="legend"><span>331 with MFA</span><span>275 password only</span></div>`.

Time series, columns, heatmaps and scatter plots: use the chart helpers below.

## Chart helpers (Python)

`fluency_brand` (in this skill's `scripts/`) draws these as inline SVG or CSS from your numbers, so the geometry, ticks, grid and
colours are always correct and on-brand. Prefer them to hand-built SVG:

```python
import sys; sys.path.insert(0, "<skill-dir>/scripts"); import fluency_brand as fb
fb.column_chart(labels, [v, ...])                                   # vertical columns, one series (blue)
fb.column_chart(labels, [("Success", [..]), ("Failed", [..])], mode="group")   # grouped columns
fb.column_chart(labels, [("Success", [..]), ("Failed", [..])], mode="stack")   # stacked columns, total above each
fb.bars_multi(labels, [("A", [..]), ("B", [..])], mode="group"|"stack")        # horizontal grouped / stacked bars
fb.heatmap(row_labels, col_labels, matrix, tone="blue"|"gray"|"red"|"amber", row_header="Day / hour")
fb.scatter([(x, y), ...], x_label="", y_label="")                   # or {"Windows": [(x, y)...], "Linux": [...]} for groups
fb.line_chart(labels, [("Sign-ins", [..]), ("Failed", [..])])       # time series
fb.bar_rows([(label, value), ...])  ·  fb.stack_bar(54.6, "331 with MFA", "275 password only")
fb.donut([(label, value, "#111111"), ...], center_big="606", center_cap="accounts")   # part-to-whole, palette colours only
fb.segment_bar([("Onboarded", 380), ("Can be onboarded", 25), ...])                    # one proportional strip + legend
fb.gauge(72, label="score", heading="Posture score", text="One line of interpretation.")  # single-figure ring
fb.sparkline([3, 5, 4, 9, 12])                                                          # tiny trend for a table cell or KPI
```

Series colours run black, blue, gray, amber, red, light gray (a single series is blue). Use a heatmap for two-dimensional counts
(day × hour, user × application), grouped columns to compare categories over time, stacked columns or bars for a total split by
status, and a scatter for two measures per item (for example exploitable CVEs against days since last seen). Each helper returns an
HTML fragment to drop into `{{sections}}` under a `§N` heading, with a one-line gray footnote saying what it shows.

## Recommended actions — `{{report_actions}}`

```html
<div class="next-steps"><h2>Recommended actions</h2><div class="ns-grid">
  <div class="ns-item"><div class="ns-when">This week — admins</div><div class="ns-act"><span class="tag p1">P1</span>&nbsp; Cut Global Administrators to two named accounts with break-glass.</div></div>
  <div class="ns-item"><div class="ns-when">Within 14 days — MFA</div><div class="ns-act"><span class="tag p2">P2</span>&nbsp; Enforce MFA through Conditional Access.</div></div>
  <div class="ns-item"><div class="ns-when">Quarterly — hygiene</div><div class="ns-act"><span class="tag p3">P3</span>&nbsp; Review guest lifecycle.</div></div>
</div></div>
```

## Writing the analysis

Lead with the so-what, quantify and compare (shares, ratios, deltas), name the specific users / IPs / rules, say what to verify and why,
and separate routine signal from anomalies. No empty intensifiers. Keep paragraphs short; one bolded phrase per paragraph at most.

## Structure blueprint

1. Title block + KPI strip + optional three-column band.
2. `§1 Executive summary` — prose, one gray callout for caveats, the black Net read.
3. `§2…§N` one section per domain of the data: a sentence of framing, a table **or** bars, a footnote.
4. Recommended actions (P1 / P2 / P3).
5. Methodology — source, window, derivation, limits; closing footer line.

## Branding

Fixed by the template: brandline (lock mark + FLUENCY SECURITY), black title, closing footer line. There is no customer-branded variant.


## Chart gallery: the source of truth

`assets/chart_gallery.html` / `assets/chart_gallery.pdf` show every chart, table and component with the exact `fluency_brand` call that draws it.
It is generated by `scripts/chart_gallery.py` from the same helpers the reports use. Report scripts and report skills draw charts only through
these helpers (never hand-written SVG, Chart.js or inline bar markup). To add a component: write it in `fluency_brand.py`, add an entry to
`ENTRIES` in `chart_gallery.py`, run `python3 scripts/chart_gallery.py`.
