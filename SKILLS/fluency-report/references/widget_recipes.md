# Widget Recipes

Copy-paste-ready HTML snippets for the body of a Fluency report. Every recipe
uses only the CSS classes already shipped in `assets/base_template.html` — no
external libraries. **Do not add Chart.js or any other CDN dependency** — the
Cowork rendering environment blocks external scripts.

The agent picks recipes based on the data shape from `run_report`, drops them
into the right placeholder (`{{kpi_strip}}` / `{{main_grid}}` /
`{{summary_html}}` / `{{next_steps_items}}`), and ships the file.

---

## KPI card

Single big number with a label and an optional note. Drop into `{{kpi_strip}}`.

```html
<div class="kpi">
  <div class="kpi-label">Total Alerts</div>
  <div class="kpi-value red">9</div>
  <div class="kpi-note">8 still new</div>
</div>
```

Colour modifiers on `.kpi-value`: `red`, `blue`, `navy`, `green`, `amber`.
Pick by signal — high alert volume → red, healthy posture → green, neutral
counts → blue or default (no class = dark).

A typical strip is 4–6 cards. Examples:

- Total events / Open alerts / Top severity / Active rules
- Total findings / Critical / High / Medium / Low
- Posture grade / Trend / Peak day / Top user

## KPI strip — minimal example

```html
<div class="kpi"><div class="kpi-label">Active Rules</div><div class="kpi-value">15</div><div class="kpi-note">rules fired</div></div>
<div class="kpi"><div class="kpi-label">Total Alerts</div><div class="kpi-value red">9</div><div class="kpi-note">+3 vs last week</div></div>
<div class="kpi"><div class="kpi-label">Top User</div><div class="kpi-value navy">3</div><div class="kpi-note">sngcobo@…</div></div>
<div class="kpi"><div class="kpi-label">Max CVSS</div><div class="kpi-value amber">8.1</div><div class="kpi-note">openssh KEV</div></div>
```

---

## Panel — table with severity rows

Fits any "rows of records" object. The `.sev-high|sev-med|sev-low` row classes
tint the row; the inline pills colour the severity column.

```html
<div class="panel col-6">
  <div class="panel-header">
    <h2 class="panel-title">Top Behaviour Rules</h2>
    <span class="panel-subtitle">15 rules · 9 alerts</span>
  </div>
  <table class="data">
    <colgroup>
      <col>
      <col style="width:64px">
      <col style="width:46px">
      <col style="width:64px">
      <col style="width:64px">
    </colgroup>
    <thead>
      <tr><th>Rule</th><th>Platform</th><th style="text-align:center">Count</th><th>Category</th><th>Severity</th></tr>
    </thead>
    <tbody>
      <tr class="sev-high">
        <td class="wrap">O365_AzureAD_UserLoggedIn</td>
        <td>O365</td>
        <td style="text-align:center;font-family:'JetBrains Mono',monospace">5</td>
        <td>Identity</td>
        <td><span class="pill high">High</span></td>
      </tr>
      <tr class="sev-med">
        <td class="wrap">O365_User_Updated</td>
        <td>O365</td>
        <td style="text-align:center;font-family:'JetBrains Mono',monospace">3</td>
        <td>Identity</td>
        <td><span class="pill med">Med</span></td>
      </tr>
      <!-- ... -->
    </tbody>
  </table>
</div>
```

Rules of thumb:
- `<col style="width:N">` to pin column widths so long names don't push numeric columns
- Add `class="wrap"` on cells that should multi-line (rule names, usernames)
- `font-family: 'JetBrains Mono'` on numeric cells for vertical alignment

Severity buckets:
- CVSS: `>=7 high`, `>=4 med`, else `low`
- Alert count vs max: `count >= max → high`, `count >= 2 → med`, else `low`
- Status: `new → high`, `in_progress → med`, `closed → low`

---

## Panel — line chart (pure SVG, time-series)

No Chart.js. Pre-compute all `(x, y)` coordinates from the data, then emit a
static SVG. The CSS classes `.svg-chart`, `.chart-axis`, `.chart-gridline`,
`.chart-line`, and `.chart-area` are already defined in `base_template.html`.

### Coordinate maths

The template is sized for A4 — use these plot dimensions so the chart height
matches the narrower, compact layout:

```
Plot area:  x ∈ [45, 510],  y ∈ [12, 135]
            width = 465,     height = 123
viewBox: "0 0 540 160"

For n data points (index i = 0 … n-1):
  x_i = 45 + i × (465 / (n - 1))
  y_i = 135 − ((value_i − min) / (max − min)) × 123

Round to 1 decimal place.
```

Build the `points` string as space-separated `"x,y"` pairs.

For the **area fill** polygon, prepend the bottom-left corner `(45, 135)` and
append the bottom-right corner `(lastX, 135)`.

Choose 4 evenly-spaced y-axis gridlines (at y=135, 94, 53, 12) and label them
with the corresponding data values.

For the x-axis, place labels at y=150 — every 4th–6th data point to avoid crowding.

### Example

```html
<div class="panel col-8">
  <div class="panel-header">
    <h2 class="panel-title">Alert Volume — Last 14 Days</h2>
    <span class="panel-subtitle">9 alerts total</span>
  </div>
  <!--
    14 data points: [2,0,0,2,2,0,1,0,0,0,1,0,0,1]
    min=0, max=2, range=2
    x_step = 465/13 ≈ 35.8   y_scale = 123/2 = 61.5
    Pre-computed points:
      i=0:  (45,  12)   [value=2, max]
      i=1:  (81,  135)  [value=0]
      i=3:  (152, 135)  [value=0]
      i=4:  (188, 12)   [value=2]
      ...
  -->
  <svg class="svg-chart" viewBox="0 0 540 160" xmlns="http://www.w3.org/2000/svg">
    <!-- Gridlines at y=135, 94, 53, 12 -->
    <line class="chart-gridline" x1="45" y1="135" x2="510" y2="135"/>
    <line class="chart-gridline" x1="45" y1="94"  x2="510" y2="94"/>
    <line class="chart-gridline" x1="45" y1="53"  x2="510" y2="53"/>
    <line class="chart-gridline" x1="45" y1="12"  x2="510" y2="12"/>
    <!-- Y labels -->
    <text class="chart-axis" x="40" y="138" text-anchor="end">0</text>
    <text class="chart-axis" x="40" y="97"  text-anchor="end">1</text>
    <text class="chart-axis" x="40" y="56"  text-anchor="end">2</text>
    <!-- X labels (every ~4 points) -->
    <text class="chart-axis" x="45"  y="150" text-anchor="middle">Apr 17</text>
    <text class="chart-axis" x="188" y="150" text-anchor="middle">Apr 21</text>
    <text class="chart-axis" x="331" y="150" text-anchor="middle">Apr 25</text>
    <text class="chart-axis" x="510" y="150" text-anchor="middle">Apr 30</text>
    <!-- Area fill -->
    <polygon class="chart-area" points="45,135 45,12 81,135 117,135 152,135 188,12 224,12 260,74 295,135 331,135 367,135 402,135 438,74 474,135 510,74 510,135"/>
    <!-- Line -->
    <polyline class="chart-line" points="45,12 81,135 117,135 152,135 188,12 224,12 260,74 295,135 331,135 367,135 402,135 438,74 474,135 510,74"/>
    <!-- Dots -->
    <circle cx="45"  cy="12"  r="3" fill="#c0161c"/>
    <circle cx="81"  cy="135" r="3" fill="#2d65a1"/>
    <circle cx="117" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="152" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="188" cy="12"  r="3" fill="#c0161c"/>
    <circle cx="224" cy="12"  r="3" fill="#c0161c"/>
    <circle cx="260" cy="74"  r="3" fill="#2d65a1"/>
    <circle cx="295" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="331" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="367" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="402" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="438" cy="74"  r="3" fill="#2d65a1"/>
    <circle cx="474" cy="135" r="3" fill="#2d65a1"/>
    <circle cx="510" cy="74"  r="3" fill="#2d65a1"/>
  </svg>
</div>
```

Tip: use `fill="#c0161c"` on the peak-value dot(s) to highlight them, and add
an `<text>` annotation next to the peak with the value.

---

## Panel — horizontal bar chart (pure CSS)

No Chart.js. Use `.bar-rows` / `.bar-row` / `.bar-track` / `.bar-fill` — all
defined in `base_template.html`. Width percentages are relative to the maximum
value in the series (max = 100%).

```html
<div class="panel col-6">
  <div class="panel-header">
    <h2 class="panel-title">Top Alerted Users</h2>
    <span class="panel-subtitle">7 identities</span>
  </div>
  <div class="bar-rows" style="margin-top:8px;">
    <!-- width = (value / max_value) * 100  -->
    <div class="bar-row">
      <div class="bar-label">sngcobo@…</div>
      <div class="bar-track"><div class="bar-fill" style="width:100%;background:#c0161c"></div></div>
      <div class="bar-val">5</div>
    </div>
    <div class="bar-row">
      <div class="bar-label">app@sharepoint</div>
      <div class="bar-track"><div class="bar-fill" style="width:60%"></div></div>
      <div class="bar-val">3</div>
    </div>
    <div class="bar-row">
      <div class="bar-label">bmuobeleni</div>
      <div class="bar-track"><div class="bar-fill" style="width:40%"></div></div>
      <div class="bar-val">2</div>
    </div>
    <div class="bar-row">
      <div class="bar-label">drohan</div>
      <div class="bar-track"><div class="bar-fill" style="width:20%"></div></div>
      <div class="bar-val">1</div>
    </div>
    <div class="bar-row">
      <div class="bar-label">tthomas</div>
      <div class="bar-track"><div class="bar-fill" style="width:20%"></div></div>
      <div class="bar-val">1</div>
    </div>
  </div>
</div>
```

`bar-fill` colour: default `--blue`; override inline with `style="background:#c0161c"` for the top entry or any entry that warrants highlighting.

---

## Panel — donut chart (pure CSS, conic-gradient)

No Chart.js. Use `.donut-ring` with an inline `background: conic-gradient(…)`
matching the data percentages, plus `.donut-legend` for the key.

### How to build the gradient

Convert each value to a cumulative percentage of the total, then write:

```css
background: conic-gradient(
  COLOR_A  0%  PCT_A%,
  COLOR_B  PCT_A%  PCT_AB%,
  COLOR_C  PCT_AB% 100%
);
```

### Example (5 categories summing to 100%)

```html
<div class="panel col-4">
  <div class="panel-header">
    <h2 class="panel-title">Alerts by Category</h2>
    <span class="panel-subtitle">9 alerts</span>
  </div>
  <div class="donut-wrap" style="margin-top:12px;">
    <div class="donut-ring" style="background:conic-gradient(
      #c0161c  0%   44.4%,
      #e81e25 44.4% 66.7%,
      #2d65a1 66.7% 80.0%,
      #457fc1 80.0% 91.1%,
      #8a92a3 91.1% 100%
    )"></div>
    <div class="donut-legend">
      <div class="legend-row"><div class="legend-swatch" style="background:#c0161c"></div><span>Identity — 44%</span></div>
      <div class="legend-row"><div class="legend-swatch" style="background:#e81e25"></div><span>OAuth — 22%</span></div>
      <div class="legend-row"><div class="legend-swatch" style="background:#2d65a1"></div><span>Mail — 13%</span></div>
      <div class="legend-row"><div class="legend-swatch" style="background:#457fc1"></div><span>Files — 11%</span></div>
      <div class="legend-row"><div class="legend-swatch" style="background:#8a92a3"></div><span>AppMgmt — 9%</span></div>
    </div>
  </div>
</div>
```

When one category dominates (>90%), the donut will be almost entirely one
colour — that's intentional and visually impactful; show it as-is.

---

## Panel — inline volume bars (no chart engine)

For top-N tables where you want a visual at-a-glance count column. Pure CSS.

```html
<table class="data">
  <thead><tr><th>Rule</th><th style="width:60px;text-align:center">Count</th><th style="width:80px">Volume</th></tr></thead>
  <tbody>
    <tr>
      <td class="wrap">O365_AzureAD_UserLoggedIn</td>
      <td style="text-align:center;font-family:'JetBrains Mono',monospace">5</td>
      <td><div class="vol"><div class="vol-fill red" style="width:100%"></div></div></td>
    </tr>
    <tr>
      <td class="wrap">O365_User_Updated</td>
      <td style="text-align:center;font-family:'JetBrains Mono',monospace">3</td>
      <td><div class="vol"><div class="vol-fill" style="width:60%"></div></div></td>
    </tr>
  </tbody>
</table>
```

`vol-fill` colour modifiers: default `--blue`, `.red`, `.amber`. Width is the
row's value as a percentage of the max in the column.

---

## Summary block

A short paragraph (or two) that names the highest-signal finding in plain
English. Drop into `{{summary_html}}`.

```html
<p>
  <strong>9 alerts</strong> fired across <strong>15 rules</strong> in the
  last 14 days, peaked at <strong>2 alerts</strong> on 17 Apr. Activity is
  concentrated on identity events — <strong>analyst@partner.example.com</strong>
  triggered 3 of those alerts via O365_AzureAD_UserLoggedIn.
</p>
<p>
  Five OpenSSH KEV exposures remain active at <strong>CVSS 8.1</strong>;
  patching the SSH stack is the highest-impact action this week.
</p>
```

Keep it factual. Don't editorialise ("alarming", "concerning") — let the
numbers carry the weight.

---

## Next-steps item

Drop into `{{next_steps_items}}`. Three to six items is the right range.

```html
<div class="ns-item">
  <div class="ns-num" style="background:var(--red)">1</div>
  <div>
    <div class="ns-when">This week</div>
    <div class="ns-act">Patch SSH stack — 5 active KEV exposures at CVSS 8.1 (openssh).</div>
  </div>
</div>
```

Number-circle colours by urgency: `var(--red)` for items 1–3 (this week / 14 days),
`var(--blue)` for 30-day items, `var(--navy)` for quarterly.

Six-item example:

```html
<div class="ns-item"><div class="ns-num" style="background:var(--red)">1</div><div><div class="ns-when">This week</div><div class="ns-act">Patch SSH stack — 5 active KEV exposures at CVSS 8.1.</div></div></div>
<div class="ns-item"><div class="ns-num" style="background:var(--red)">2</div><div><div class="ns-when">This week</div><div class="ns-act">Investigate analyst@partner.example.com (3 alerts).</div></div></div>
<div class="ns-item"><div class="ns-num" style="background:var(--red)">3</div><div><div class="ns-when">Within 14 days</div><div class="ns-act">Review O365 OAuth consent grants — reduce admin-consent surface.</div></div></div>
<div class="ns-item"><div class="ns-num" style="background:var(--blue)">4</div><div><div class="ns-when">Within 14 days</div><div class="ns-act">Tune AzureAD UserLoggedIn rule — highest-volume trigger.</div></div></div>
<div class="ns-item"><div class="ns-num" style="background:var(--blue)">5</div><div><div class="ns-when">Within 30 days</div><div class="ns-act">Confirm closure SLA — only 1 of 9 alerts closed this period.</div></div></div>
<div class="ns-item"><div class="ns-num" style="background:var(--navy)">6</div><div><div class="ns-when">Quarterly</div><div class="ns-act">Identity-rule review — promote stable rules out of monitoring.</div></div></div>
```

---

## Layout guide for `{{main_grid}}`

The grid is 12 columns wide. Common arrangements:

- **2 panels side-by-side**: two `col-6` panels
- **Three small panels**: three `col-4` panels
- **Hero + side panel**: `col-8` + `col-4`
- **Wide chart on top, two below**: `col-12` + two `col-6`

Below 880px wide, every panel collapses to full width automatically.

---

## Branding

Branding is hardcoded in `assets/base_template.html` — the header logo is an
inline SVG brand mark (no network request needed), and the footer always reads
"powered by Fluency". Nothing to fill in or override per report.
