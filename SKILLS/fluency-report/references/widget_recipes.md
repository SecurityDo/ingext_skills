# Widget Recipes — Executive Report

Copy-paste-ready HTML for a Fluency **executive** report. The template
(`assets/base_template.html`) is a multi-page document: a full-page **cover**
followed by one or more numbered **section sheets**. Every recipe uses only the
classes shipped in the template — **no Chart.js, no CDN scripts** (the Cowork
render environment blocks them). All charts are pure inline SVG / CSS.

The agent fills the cover placeholders, then assembles section sheets into the
single `{{sections}}` placeholder.

## Template placeholders

| Placeholder | Fill with |
|---|---|
| `{{report_title}}` | Humanised report name; wrap the second line in `<span class="accent">…</span>` for the red highlight |
| `{{cover_eyebrow}}` | Small uppercase kicker above the title (e.g. "Network Security Review") |
| `{{report_lead}}` | 1–2 sentence executive description of what the report covers and what it found |
| `{{confidential_tag}}` | e.g. `Confidential · Internal` |
| `{{cover_meta}}` | 3–4 `.meta-field` blocks (reporting period, generated, tenant, source) |
| `{{cover_kpis}}` | 4–5 `.cover-kpi` cards — the headline numbers |
| `{{sections}}` | All section sheets, concatenated |
| `{{footer_page_info}}` | e.g. `Fluency Report · <human title> · <tenant>` |

Substitute via simple `str.replace`. Don't introduce a templating engine.

---

## Cover (page 1)

The cover chrome is in the template; you only fill the placeholders.

### `{{cover_meta}}` — labelled fields

```html
<div class="meta-field"><div class="label">Reporting Period</div><div class="value">04–05 Jun 2026</div></div>
<div class="meta-field"><div class="label">Generated</div><div class="value">05 Jun 2026</div></div>
<div class="meta-field"><div class="label">Tenant</div><div class="value">Altron Group</div></div>
<div class="meta-field"><div class="label">Source</div><div class="value">FortiGate Traffic Logs</div></div>
```

### `{{cover_kpis}}` — headline numbers

```html
<div class="cover-kpi"><div class="v">17.0M</div><div class="l">Traffic Events</div></div>
<div class="cover-kpi"><div class="v blue">336.9 GB</div><div class="l">Total Traffic</div></div>
<div class="cover-kpi"><div class="v amber">232 GB</div><div class="l">Inbound</div></div>
<div class="cover-kpi"><div class="v green">105 GB</div><div class="l">Outbound</div></div>
<div class="cover-kpi"><div class="v">76,452</div><div class="l">Unique Sources</div></div>
```

Value colour modifiers: `green`, `amber`, `red`, `blue` (default = white).

---

## Section sheet — the unit of the document

Every major section is one `.sheet`. In print each starts on a fresh A4 page.
Header (eyebrow + title + subtitle), then the body, then a footer.

```html
<section class="sheet">
  <div class="sheet-head">
    <p class="sec-eyebrow">02 · Activity Overview</p>
    <h2 class="sec-title">What happened on the network</h2>
    <p class="sec-sub">Every flow, grouped by direction and ranked by volume.</p>
  </div>
  <div class="sheet-body">
    <!-- panels / two-col blocks / analysis go here -->
  </div>
  <div class="sheet-foot">
    <span>02 · Activity Overview</span>
    <span>Network Security Review · 05 Jun 2026</span>
  </div>
</section>
```

Number sections `01`, `02`, … in the eyebrow and footer. Keep the title a short
plain-English question or statement ("Who is driving the activity", "Where
access came from"), and the subtitle one line.

---

## Block title (with colour dot)

Label a block inside a sheet. Dot colours: default blue, `.red`, `.green`,
`.amber`, `.navy`.

```html
<p class="block-title"><span class="dot"></span>Operations by event count</p>
```

## Two-column layout

For "chart + narrative" or "table + mini-chart" rows. Variants: `.wide-left`,
`.wide-right` shift the 50/50 split.

```html
<div class="two-col wide-left">
  <div><!-- left: table or chart --></div>
  <div><!-- right: donut / gauge / note --></div>
</div>
```

## Analysis prose

The written interpretation — **as important as the widgets**. Bold the key
figures. One to three short paragraphs per section.

```html
<div>
  <p class="block-title"><span class="dot"></span>Analysis</p>
  <div class="prose">
    <p><b>A single destination (193 GB)</b> absorbed 57% of all traffic across
    941K sessions — far above any other endpoint. Concentration this high is
    normal for backup, CDN or replication flows, but warrants a one-time check
    that the endpoint is sanctioned.</p>
    <p>Inbound outweighed outbound roughly <b>2:1</b> (232 GB vs 105 GB),
    consistent with routine download and sync rather than bulk egress.</p>
  </div>
</div>
```

Lead with the **so-what**, quantify and compare (shares, ratios, per-event
averages, outliers), flag what to verify and why. Stay factual and specific —
name the IPs / users / rules. Avoid empty intensifiers.

---

## KPI strip (inside a section)

```html
<div class="kpi-strip">
  <div class="kpi"><div class="kpi-label">Total Events</div><div class="kpi-value navy">17.0M</div><div class="kpi-note">FortiGate logs</div></div>
  <div class="kpi"><div class="kpi-label">Inbound</div><div class="kpi-value amber">232 GB</div><div class="kpi-note">69% of volume</div></div>
  <div class="kpi"><div class="kpi-label">Outbound</div><div class="kpi-value green">105 GB</div><div class="kpi-note">31% of volume</div></div>
  <div class="kpi"><div class="kpi-label">Top Talker</div><div class="kpi-value red">57%</div><div class="kpi-note">one destination</div></div>
</div>
```

## Callout band (Healthy / Watch / Act)

The at-a-glance posture read — ideal in the executive-summary section. Use
exactly the three states `good` / `watch` / `act`.

```html
<div class="callouts">
  <div class="callout good"><p class="tag">● Healthy</p><h4>Broad, normal distribution</h4><p>76K sources / 23K destinations with a ~2:1 inbound bias — routine browse/sync/download.</p></div>
  <div class="callout watch"><p class="tag">● Watch</p><h4>Single endpoint dominates</h4><p>One destination took 57% of all bytes. Confirm it is a sanctioned service.</p></div>
  <div class="callout act"><p class="tag">● Act</p><h4>Large internal pull</h4><p>Host 172.29.110.34 received 30 GB from one external host — verify the download.</p></div>
</div>
```

## Risk gauge

A single-figure posture dial. Band by colour: Low → `--green`, Elevated →
`--amber`, High → `--red`. Set the same colour on the gradient and the `.s`.

```html
<div class="gauge">
  <div class="gauge-ring" style="background:conic-gradient(var(--amber) 0 57%, var(--bd2) 57% 100%)">
    <div class="c"><div class="s" style="color:var(--amber)">57%</div><div class="t">Top dst</div></div>
  </div>
  <div class="gauge-txt"><h4>Bandwidth is concentrated</h4><p>One destination carries 57% of all bytes; the top 10 carry 82%. Normal for backup/CDN flows — validate each top endpoint once.</p></div>
</div>
```

## Note strip

One-line emphasis: caveat, data gap, or "bottom line". Tints: default amber,
`.blue` (info), `.green` (all-clear), `.red` (act).

```html
<div class="note green"><div class="ic">✓</div><p><b>Bottom line:</b> nothing here requires an incident response — two validation tasks only.</p></div>
<div class="note"><div class="ic">⚠</div><p><b>Verify:</b> 203.0.113.17 moved 2.2 GB in just 18 sessions — large per-session transfer.</p></div>
<div class="note blue"><div class="ic">ℹ</div><p>Internal vs external scope is inferred from RFC1918 ranges; geo-enrichment is unavailable this run.</p></div>
```

---

## Table — with share bar, pills, severity rows

`<col>` widths keep numeric columns aligned. `class="num"` = right-aligned
mono. Inline `.cellbar` gives a share column; `.pill` tags a category;
`.sev-*` tints a whole row.

```html
<table class="data">
  <colgroup><col><col style="width:70px"><col style="width:150px"><col style="width:60px"><col style="width:70px"><col style="width:78px"></colgroup>
  <thead><tr><th>Mailbox Owner</th><th style="text-align:right">Events</th><th>Share</th><th style="text-align:right">Ops</th><th style="text-align:right">Src IPs</th><th>Profile</th></tr></thead>
  <tbody>
    <tr>
      <td title="chris@…">chris@fluencysecurity.com</td>
      <td class="num">644</td>
      <td><div class="cellbar"><i style="width:100%"></i></div></td>
      <td class="num">5</td>
      <td class="num">46</td>
      <td><span class="pill power">Power</span></td>
    </tr>
    <tr>
      <td title="patrick@…">patrick.evans@fluencysecurity.com</td>
      <td class="num">111</td>
      <td><div class="cellbar"><i style="width:17%"></i></div></td>
      <td class="num">5</td>
      <td class="num">16</td>
      <td><span class="pill active">Active</span></td>
    </tr>
  </tbody>
</table>
```

Pills available: `high` (red), `med` (amber), `low` (blue), `ok`/`benign`
(green), `info`/`service` (grey), `power` (navy), `active` (blue outline),
`light` (grey outline), `endpoint` (amber tint), `msauth` (blue tint).
`.cellbar > i` colour: default blue, `.amber`, `.red`. Width = value ÷ max × 100.

Severity buckets: CVSS `>=7 high / >=4 med / else low`; count-vs-max
`==max high / >=2 med / else low`; status `new high / in_progress med / closed low`.

## Bar chart (pure CSS)

Width % = value ÷ series-max × 100. Highlight the top bar in red/amber inline.

```html
<p class="block-title"><span class="dot"></span>Top Source IPs</p>
<div class="bar-rows">
  <div class="bar-row"><div class="bar-label">172.29.110.34</div><div class="bar-track"><div class="bar-fill" style="width:100%;background:var(--red)"></div></div><div class="bar-val">30.9 GB</div></div>
  <div class="bar-row"><div class="bar-label">203.0.113.19</div><div class="bar-track"><div class="bar-fill" style="width:29%;background:var(--amber)"></div></div><div class="bar-val">9.0 GB</div></div>
  <div class="bar-row"><div class="bar-label">10.194.4.11</div><div class="bar-track"><div class="bar-fill" style="width:20%"></div></div><div class="bar-val">6.3 GB</div></div>
</div>
```

## Donut chart (with count legend)

Cumulative percentages drive the `conic-gradient`. Legend rows can carry a
right-aligned `.val` count. Optional centred total via `.donut-center`.

```html
<p class="block-title"><span class="dot green"></span>Traffic by direction</p>
<div class="donut-wrap">
  <div style="position:relative">
    <div class="donut-ring" style="background:conic-gradient(var(--amber) 0 68.9%, var(--green) 68.9% 100%)"></div>
    <div class="donut-center"><div class="big">337 GB</div><div class="cap">Total</div></div>
  </div>
  <div class="donut-legend">
    <div class="legend-row"><div class="legend-swatch" style="background:var(--amber)"></div><span>Inbound</span><span class="val">232 GB</span></div>
    <div class="legend-row"><div class="legend-swatch" style="background:var(--green)"></div><span>Outbound</span><span class="val">105 GB</span></div>
  </div>
</div>
```

When one slice dominates (>90%), the ring is almost one colour — that's
intentional and reads as impact; ship it as-is.

## Line chart (pure SVG, time-series)

Pre-compute coordinates; the `.svg-chart` / `.chart-*` classes are defined.
Plot area `x ∈ [45, 510]`, `y ∈ [12, 135]`, viewBox `0 0 540 160`.
`x_i = 45 + i·(465/(n-1))`, `y_i = 135 − ((v−min)/(max−min))·123`.

```html
<svg class="svg-chart" viewBox="0 0 540 160" xmlns="http://www.w3.org/2000/svg">
  <line class="chart-gridline" x1="45" y1="135" x2="510" y2="135"/>
  <line class="chart-gridline" x1="45" y1="74"  x2="510" y2="74"/>
  <line class="chart-gridline" x1="45" y1="12"  x2="510" y2="12"/>
  <polygon class="chart-area" points="45,135 45,40 188,90 331,30 510,60 510,135"/>
  <polyline class="chart-line" points="45,40 188,90 331,30 510,60"/>
  <circle cx="331" cy="30" r="3" fill="#c0161c"/>
</svg>
```

---

## Action plan cards (governance section)

Numbered, full-width, with a right-aligned timing pill. Number-square colour by
urgency: `--red` (this week), `--blue` (14–30 days), `--navy` (quarterly).

```html
<div class="action-list">
  <div class="action">
    <div class="action-num" style="background:var(--red)">1</div>
    <div class="action-body"><h4>Validate the top-talker destination</h4><p>Confirm 203.0.113.18 (193 GB, 57% of traffic) is a sanctioned service, not exfiltration.</p></div>
    <div class="action-when">This week</div>
  </div>
  <div class="action">
    <div class="action-num" style="background:var(--blue)">4</div>
    <div class="action-body"><h4>Baseline per-host volumes</h4><p>Set thresholds so future spikes surface automatically.</p></div>
    <div class="action-when">Within 14 days</div>
  </div>
  <div class="action">
    <div class="action-num" style="background:var(--navy)">6</div>
    <div class="action-body"><h4>Review logging coverage</h4><p>Confirm all firewalls feed the tenant; tune top-talker alerting.</p></div>
    <div class="action-when">Quarterly</div>
  </div>
</div>
```

(The legacy `.next-steps` / `.ns-item` grid still works if you prefer a compact
block, but `.action` cards are the executive default.)

---

## Appendix — methodology grid + brand close

Two-column labelled notes that document how the figures were derived, then a
centred brand block and an info disclaimer.

```html
<div class="method-grid">
  <div class="method-item"><span class="mk">▶</span><p><b>Source.</b> FortiGate traffic logs via the Ingext datalake.</p></div>
  <div class="method-item"><span class="mk">▶</span><p><b>Window.</b> Trailing 24h, 04 Jun 22:01 – 05 Jun 22:01 UTC.</p></div>
  <div class="method-item"><span class="mk">▶</span><p><b>Scope.</b> 17.0M events · 76,452 sources · 23,324 destinations.</p></div>
  <div class="method-item"><span class="mk">▶</span><p><b>Volume basis.</b> Per-session byte deltas; sent = egress, received = ingress.</p></div>
</div>
<div class="divider"></div>
<div class="note blue"><div class="ic">ℹ</div><p>This report summarises observed traffic and does not assert intent. Items flagged "verify" are statistical outliers for human review, not confirmed incidents.</p></div>
<div class="brand-block"><div class="bm">Fluency Security</div><div class="bs">Network Security Review · Generated 05 Jun 2026 · Confidential</div></div>
```

---

## Report structure blueprint

A full executive report is the cover plus these sheets (adapt the section names
to the report's domain — these are the Office 365 Exchange set as a model):

1. **Cover** — title, lead, meta fields, headline KPIs.
2. **01 · Executive Summary** — lead paragraph, callout band (Healthy/Watch/Act),
   two-col posture interpretation + risk gauge, "bottom line" note.
3. **02 · Activity Overview** — KPI strip, two-col (bar chart + donut),
   divider, **Analysis** prose.
4. **03 · <Who/What is driving it>** — a ranked detail table (with share bars +
   pills), two-col Analysis + mini concentration chart.
5. **04 · <Where it came from / infrastructure>** — source table + footprint
   donut, a second detail table, a "sanctioned / verify" note.
6. **05 · Governance & Recommendations** — high-impact change tables with
   impact/verdict pills, then the numbered **action plan**.
7. **06 · Appendix** — methodology grid, disclaimer note, brand close.

Smaller reports can collapse to cover + Exec Summary + 2–3 sheets + Appendix,
but always keep: a cover, a callout band, at least one chart, full detail
tables, per-section Analysis prose, an action plan, and an appendix.

## Branding

Hardcoded. The dark cover shows the Fluency logo in a white chip with a
`Confidential` tag; every sheet footer and the cover read "Powered by Fluency".
The skill copies `logo2.png` into the output's `assets/` folder at render time,
so `src="assets/logo2.png"` resolves. Nothing to override per report.
