#!/usr/bin/env python3
"""Fluency report brand kit — one editorial look for every Fluency / Ingext HTML and PDF report.

The look follows the Fluency Security posture sample: white paper, IBM Plex Sans + Mono,
a brandline (lock mark + FLUENCY SECURITY) over a black rule, a large black title,
a KPI strip with status tags, a three-column band, §-numbered sections, flat mono tables,
black/gray/blue bars, a callout, recommended actions and a methodology block.

Vendor this folder next to a report script (fluency_brand.py, brand.css, fluency_mark.png,
the plex-*.woff2 files, render_pdf.mjs), then:

    import fluency_brand as fb
    html = fb.page(title="Acme — Application health", eyebrow="Application health",
                   subtitle="One-paragraph lead.", meta="Tenant acme · Last 24 hours · Read-only",
                   kpis=[fb.kpi("Running", 12, tag=fb.tag("2 in error", "red"))],
                   band=[("01 — What is exposed", "<p>…</p>"), ("02 — What is already right", "<p>…</p>"),
                         ("03 — What to fix first", "<p>…</p>")],
                   body=fb.section(1, "Executive summary", "<p>…</p>") + fb.table(["A", "B"], rows, num_cols=(1,)),
                   steps=[("This week", "Do the thing.", "P1")],
                   method="<p>How this was produced.</p>")
    open("report.html", "w").write(html)
    fb.to_pdf("report.html", "report.pdf")        # same CSS, US Letter

Older scripts that build their own markup can call fb.apply_brand(html) to restyle it in place.
Everything is inlined (fonts, mark, CSS): one self-contained file, identical offline.
"""
import base64, datetime, html as _html, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _b64(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _font_faces():
    out = []
    for fam, files in (("IBM Plex Sans", (300, 400, 500, 600, 700)), ("IBM Plex Mono", (400, 500))):
        stem = "plex-sans" if "Sans" in fam else "plex-mono"
        for wt in files:
            n = "%s-%d.woff2" % (stem, wt)
            if os.path.exists(os.path.join(HERE, n)):
                out.append("@font-face{font-family:'%s';font-style:normal;font-weight:%d;font-display:block;src:url(data:font/woff2;base64,%s) format('woff2')}" % (fam, wt, _b64(n)))
    return "\n".join(out)


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


MARK_URI = "data:image/png;base64," + _b64("fluency_mark.png")
CSS = _font_faces() + "\n" + _read("brand.css")
SITE = "https://fluencysecurity.com"


def esc(v):
    return _html.escape("" if v is None else str(v), quote=True)


def today():
    return datetime.date.today().strftime("%d %b %Y")


# -- chrome ---------------------------------------------------------------

def logo_img():
    return '<img src="%s" alt="Fluency">' % MARK_URI


def logo_chip():          # kept for older scripts: now just the mark
    return logo_img()


def brandline(doc_type=""):
    """Top line: lock mark + FLUENCY SECURITY on the left, document type on the right, black rule under it."""
    return ('<div class="brandline"><div class="bl-l"><img src="%s" alt="">Fluency Security</div><div class="bl-r">%s</div></div>'
            % (MARK_URI, esc(doc_type)))


def hero(eyebrow, title, subtitle="", meta="", chips=None, fields=None):
    """Title block: big black title, gray lead, thick black rule, gray mono meta line.
    `eyebrow` is the document type (shown in the brandline). `fields` [(label, value)] and `chips` join the meta line."""
    bits = []
    if meta:
        bits.append(esc(meta))
    for k, v in (fields or []):
        bits.append("%s %s" % (esc(k), esc(v)))
    for c in (chips or []):
        bits.append(c)
    bits.append("Generated %s" % today())
    return (brandline(eyebrow) + '<div class="hero"><div class="hero-in"><img class="hero-mark" src="%s" alt="">'
            '<h1 class="hero-title">%s</h1>%s<p class="hero-meta">%s</p></div></div>'
            % (MARK_URI, esc(title), ('<p class="hero-sub">%s</p>' % esc(subtitle)) if subtitle else "", " · ".join(bits)))


def footer(left, data_date=None, cls="footer"):
    return ('<div class="%s"><div>%s</div><div>Data as at %s · <a href="%s" target="_blank" rel="noopener">fluencysecurity.com</a></div></div>'
            % (cls, esc(left), esc(data_date or today()), SITE))


# -- components -----------------------------------------------------------

def tag(text, kind="gray"):
    """Status tag. kind: red (filled) · blue (filled) · amber (outlined) · o-red · o-blue/clean · fill-amber · gray · p1 p2 p3"""
    return '<span class="tag %s">%s</span>' % (esc(kind), esc(text))


def pill(text, kind="info"):          # older name; high/med/low/ok/info still work
    return '<span class="pill %s">%s</span>' % (esc(kind), esc(text))


def priority(p):
    return tag(p, {"P1": "p1", "P2": "p2", "P3": "p3"}.get(str(p).upper(), "gray"))


def _num(value):
    s = esc(value)
    m = re.match(r"^([\d,.\-+]+)(%|[a-zA-Z]{1,3})?$", str(value).strip())
    if m and m.group(2):
        return '%s<small>%s</small>' % (esc(m.group(1)), esc(m.group(2)))
    return s


def kpi(label, value, note="", color="", tag=None, tag_kind="gray"):
    """One KPI cell: big mono number, mono caps label, optional status tag (string or tag() html). `note` shows as small gray text."""
    c = (" " + color) if color in ("red", "blue", "amber") else ""
    if not re.match(r"^[\d,.\-+$]+[%a-zA-Z]{0,3}$", str(value).strip()) and len(str(value)) > 6:
        c += " txt"                                            # a word or phrase, not a figure: smaller type so it fits the cell
    t = ""
    if tag:
        t = tag if str(tag).startswith("<") else globals()["tag"](tag, tag_kind)
    return ('<div class="kpi"><div class="kpi-value%s">%s</div><div class="kpi-label">%s</div>%s%s</div>'
            % (c, _num(value), esc(label), t, ('<div class="kpi-note">%s</div>' % esc(note)) if note else ""))


def kpi_strip(kpis):
    return '<div class="kpi-strip">%s</div>' % "".join(kpis)


def band(items):
    """Three-column band: items = [(heading, html), ...] e.g. 01 — What is exposed / 02 — What is already right / 03 — What to fix first."""
    return '<div class="band">%s</div>' % "".join('<div><h4>%s</h4>%s</div>' % (esc(h), t if t.lstrip().startswith("<") else "<p>%s</p>" % t) for h, t in items)


def section(n, title, body_html=""):
    return '<h2><span class="n">%s</span>%s</h2>%s' % (esc(n), esc(title), body_html)


def panel(title, inner, col=12, subtitle=""):
    sub = ('<span class="panel-subtitle">%s</span>' % esc(subtitle)) if subtitle else ""
    return ('<div class="panel col-%d"><div class="panel-header"><h3 class="panel-title">%s</h3>%s</div>%s</div>'
            % (col, esc(title), sub, inner))


def table(headers, rows, widths=None, num_cols=(), row_class=None, raw_cols=(), total_last=False, foot=""):
    """rows: list of lists. Cells are escaped unless their column index is in raw_cols (use for tags).
    row_class(row)->'sev-high'|'sev-med'|'sev-low'|''.  total_last bolds the last row. foot = small gray note under the table."""
    cg = ("<colgroup>%s</colgroup>" % "".join('<col style="width:%s">' % w for w in widths)) if widths else ""
    th = "".join('<th class="%s">%s</th>' % ("num" if i in num_cols else "", esc(h)) for i, h in enumerate(headers))
    body = []
    for ri, r in enumerate(rows):
        cls = (row_class(r) if row_class else "") or ""
        if total_last and ri == len(rows) - 1:
            cls += " total"
        tds = "".join('<td class="%s">%s</td>' % ("num" if i in num_cols else "wrap", c if i in raw_cols else esc(c)) for i, c in enumerate(r))
        body.append('<tr class="%s">%s</tr>' % (cls.strip(), tds))
    f = ('<p class="fn">%s</p>' % foot) if foot else ""
    return '<table class="data">%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table>%s' % (cg, th, "".join(body), f)


def bar_rows(items, color=None, fmt=lambda v: "{:,}".format(v), lead_blue=True):
    """items: [(label, value[, colour[, value_text]])] -> horizontal bars on light tracks; the leading bar is blue, the rest gray.
    A third element sets that bar's colour (meaning, e.g. red for critical); a fourth replaces the printed value."""
    top = max([it[1] for it in items] + [1])
    rows = []
    for i, it in enumerate(items):
        label, v = it[0], it[1]
        col = legacy_color(it[2]) if len(it) > 2 and it[2] else color
        vtext = it[3] if len(it) > 3 and it[3] is not None else fmt(v)
        w = max(1.5, 100.0 * v / top) if v else 0
        style = "width:%.1f%%" % w + ((";background:%s" % col) if col else "")
        cls = "bar-fill" + (" blue" if (lead_blue and i == 0 and not col) else (" gray" if not col else ""))
        rows.append('<div class="bar-row"><div class="bar-label" title="%s">%s</div><div class="bar-track"><div class="%s" style="%s"></div></div><div class="bar-val">%s</div></div>'
                    % (esc(label), esc(label), cls, style, esc(vtext)))
    return '<div class="bar-rows">%s</div>' % "".join(rows)


def stack_bar(black_pct, left_label="", right_label=""):
    """Stacked black/white bar (e.g. MFA coverage)."""
    return ('<div class="stack"><i class="k" style="width:%.1f%%"></i><i class="w" style="width:%.1f%%"></i></div>'
            '<div class="legend"><span>%s</span><span>%s</span></div>' % (black_pct, 100 - black_pct, esc(left_label), esc(right_label)))


def donut(segments, center_big="", center_cap=""):
    """segments: [(label, value, '#hex')]  — use #111 / #8a8a8a / #175d9a / #b3242e / #a06c00 only."""
    total = float(sum(v for _, v, _ in segments)) or 1.0
    acc, stops = 0.0, []
    for _, v, col in segments:
        a, b = acc / total * 360, (acc + v) / total * 360
        stops.append("%s %.2fdeg %.2fdeg" % (col, a, b))
        acc += v
    legend = "".join('<div class="legend-row"><span class="legend-swatch" style="background:%s"></span>%s — <b>%s</b></div>' % (col, esc(l), esc("{:,}".format(v))) for l, v, col in segments)
    return ('<div class="donut-wrap"><div style="position:relative;width:112px;height:112px;flex-shrink:0"><div class="donut-ring" style="background:conic-gradient(%s)"></div>'
            '<div class="donut-center"><div class="big">%s</div><div class="cap">%s</div></div></div><div class="donut-legend">%s</div></div>'
            % (",".join(stops), esc(center_big), esc(center_cap), legend))


def callout(kind, tag_text, heading, text):
    """Gray callout with a colored left border. kind: good (blue) · watch (amber) · act (red) · dark (black 'Net read' box)."""
    k = kind if kind in ("good", "watch", "act", "dark") else "good"
    return '<div class="callout %s"><p class="tag">%s</p><h4>%s</h4><p>%s</p></div>' % (k, esc(tag_text), esc(heading), esc(text))


def callouts(items):
    return '<div class="callouts">%s</div>' % "".join(items)


def netread(heading, text_html):
    """Black box with white text (the sample's 'Net read')."""
    return '<div class="callout dark"><h4>%s</h4><p>%s</p></div>' % (esc(heading), text_html)


def note(text_html, kind=""):
    return '<div class="note %s"><p>%s</p></div>' % (esc(kind), text_html)


def next_steps(steps, title="Recommended actions"):
    """steps: [(when, action_html)] or [(when, action_html, 'P1'|'P2'|'P3')]"""
    items = []
    for st in steps:
        pr = (priority(st[2]) + "&nbsp; ") if len(st) > 2 and st[2] else ""
        items.append('<div class="ns-item"><div class="ns-when">%s</div><div class="ns-act">%s%s</div></div>' % (esc(st[0]), pr, st[1]))
    return '<div class="next-steps"><h2>%s</h2><div class="ns-grid">%s</div></div>' % (esc(title), "".join(items))


def methodology(html_text, title="Methodology"):
    return '<div class="method"><h2>%s</h2>%s</div>' % (esc(title), html_text)


# -- charts: vertical columns, grouped / stacked bars, heatmap, scatter, line -------------------------
SERIES = ["#111111", "#175d9a", "#8a8a8a", "#a06c00", "#b3242e", "#bdbdbd"]   # series colours, in order


def _fmt(v):
    if isinstance(v, float) and not v.is_integer():
        return "{:,.1f}".format(v)
    return "{:,}".format(int(v))


def _nice_max(m):
    if m <= 0:
        return 1
    import math
    e = 10 ** int(math.floor(math.log10(m)))
    for k in (1, 2, 2.5, 5, 10):
        if m <= k * e:
            return k * e
    return 10 * e


def _legend(names, colors):
    if len(names) < 2:
        return ""
    return '<div class="legend">%s</div>' % "".join('<span><em style="background:%s"></em>%s</span>' % (c, esc(n)) for n, c in zip(names, colors))


def _norm_series(series, n):
    """series: [values] | [(name, [values])] -> (names, [[v..]])"""
    if series and not isinstance(series[0], (list, tuple)):
        return [""], [list(series)]
    return [s[0] for s in series], [list(s[1]) for s in series]


def column_chart(labels, series, mode="group", height=190, colors=None, show_values=True, y_label=""):
    """Vertical column chart as inline SVG. series: [values] for one series, or [(name, [values]), ...].
    mode: 'group' (side by side) or 'stack'. First series is black, then blue, gray, amber, red."""
    names, data = _norm_series(series, len(labels))
    gaps = [[v is None for v in d] for d in data]            # None = no data that day: a hatched gap, never a zero bar
    data = [[0 if v is None else v for v in d] for d in data]
    colors = colors or (["#175d9a"] if len(data) == 1 else SERIES)
    W, H, L, R, T, B = 640, height, 38, 8, 14, 30
    pw, ph = W - L - R, H - T - B
    if mode == "stack":
        tops = [sum(d[i] for d in data) for i in range(len(labels))]
    else:
        tops = [max(d[i] for d in data) for i in range(len(labels))]
    ymax = _nice_max(max(tops + [1]))
    n = len(labels); slot = pw / float(n)
    o = ['<svg class="svg-chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, esc(y_label or "Column chart"))]
    if any(any(g) for g in gaps):
        o.append('<defs><pattern id="gap" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="4" fill="#fff"/><line x1="0" y1="0" x2="0" y2="4" stroke="#a06c00" stroke-width="1.2"/></pattern></defs>')
    for k in range(6):
        y = T + ph - ph * k / 5.0
        o.append('<line class="chart-gridline" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="chart-axis" x="%d" y="%.1f" text-anchor="end">%s</text>' % (L, W - R, y, y, L - 5, y + 3, _fmt(ymax * k / 5.0)))
    gap = min(10, slot * 0.25)
    for i, lab in enumerate(labels):
        x0 = L + slot * i + gap / 2.0; bw = slot - gap
        if mode == "stack":
            acc = 0
            for si, d in enumerate(data):
                v = d[i]
                if v <= 0:
                    continue
                h = ph * v / ymax; y = T + ph - ph * acc / ymax - h; acc += v
                o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"><title>%s %s: %s</title></rect>' % (x0, y, bw, h, colors[si % len(colors)], esc(names[si]), esc(lab), _fmt(v)))
            if show_values and acc and n <= 16:
                o.append('<text class="chart-axis" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (x0 + bw / 2, T + ph - ph * acc / ymax - 3, _fmt(acc)))
        else:
            m = len(data); w = bw / m
            for si, d in enumerate(data):
                v = d[i]; h = ph * v / ymax
                if gaps[si][i]:
                    o.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="url(#gap)" stroke="#a06c00" stroke-width="0.5"><title>%s: no data</title></rect>' % (x0 + w * si, T, max(w - (1 if m > 1 else 0), 1), ph, esc(lab)))
                    continue
                o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"><title>%s %s: %s</title></rect>' % (x0 + w * si, T + ph - h, max(w - (1 if m > 1 else 0), 1), h, colors[si % len(colors)], esc(names[si]), esc(lab), _fmt(v)))
                if show_values and m == 1 and n <= 16 and v:
                    o.append('<text class="chart-axis" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (x0 + w / 2, T + ph - h - 3, _fmt(v)))
        if n <= 16 or i % max(1, n // 12) == 0:
            o.append('<text class="chart-axis" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x0 + bw / 2, H - 12, esc(lab)))
    o.append('<line x1="%d" x2="%d" y1="%d" y2="%d" stroke="#111" stroke-width="1"/></svg>' % (L, W - R, T + ph, T + ph))
    gapnote = '<div class="legend"><span><em style="background:repeating-linear-gradient(45deg,#fff 0 2px,#a06c00 2px 3px);border:1px solid #a06c00"></em>No data that day</span></div>' if any(any(g) for g in gaps) else ""
    return '<div class="fig">%s%s%s</div>' % ("".join(o), _legend(names, colors), gapnote)


def bars_multi(labels, series, mode="group", colors=None, fmt=_fmt):
    """Horizontal grouped or stacked bars. series: [(name, [values per label]), ...]; mode 'group' | 'stack'."""
    names, data = _norm_series(series, len(labels))
    colors = colors or SERIES
    if mode == "stack":
        top = max([sum(d[i] for d in data) for i in range(len(labels))] + [1])
    else:
        top = max([v for d in data for v in d] + [1])
    rows = []
    for i, lab in enumerate(labels):
        if mode == "stack":
            segs = "".join('<div style="width:%.2f%%;background:%s;height:100%%" title="%s: %s"></div>' % (100.0 * d[i] / top, colors[si % len(colors)], esc(names[si]), esc(fmt(d[i]))) for si, d in enumerate(data) if d[i] > 0)
            track = '<div class="bar-track" style="display:flex;height:10px">%s</div>' % segs
            val = fmt(sum(d[i] for d in data))
        else:
            track = "".join('<div class="bar-track" style="height:7px;margin:1px 0"><div class="bar-fill" style="width:%.2f%%;background:%s" title="%s: %s"></div></div>' % (100.0 * d[i] / top, colors[si % len(colors)], esc(names[si]), esc(fmt(d[i]))) for si, d in enumerate(data))
            track = "<div>%s</div>" % track
            val = " / ".join(fmt(d[i]) for d in data)
        rows.append('<div class="bar-row"><div class="bar-label" title="%s">%s</div>%s<div class="bar-val">%s</div></div>' % (esc(lab), esc(lab), track, esc(val)))
    return '<div class="bar-rows">%s</div>%s' % ("".join(rows), _legend(names, colors))


def heatmap(row_labels, col_labels, matrix, tone="blue", show_values=True, fmt=_fmt, row_header="", vmax=None):
    """Heatmap as an HTML grid (prints cleanly). matrix[r][c] numbers (None = blank). tone: blue | gray | red | amber."""
    ramps = {"blue": (238, 243, 248, 23, 93, 154), "gray": (244, 244, 244, 17, 17, 17), "red": (250, 238, 238, 179, 36, 46), "amber": (250, 244, 230, 160, 108, 0)}
    r0, g0, b0, r1, g1, b1 = ramps.get(tone, ramps["blue"])
    vals = [v for row in matrix for v in row if v is not None]
    top = float(vmax if vmax is not None else (max(vals) if vals else 1)) or 1.0
    head = "<th>%s</th>%s" % (esc(row_header), "".join('<th class="num" style="text-align:center;padding:0 2px 7px">%s</th>' % esc(c) for c in col_labels))
    body = []
    for lab, row in zip(row_labels, matrix):
        cells = []
        for v in row:
            if v is None:
                cells.append('<td style="padding:0"></td>')
                continue
            t = max(0.0, min(1.0, v / top))
            col = "rgb(%d,%d,%d)" % (r0 + (r1 - r0) * t, g0 + (g1 - g0) * t, b0 + (b1 - b0) * t)
            fg = "#fff" if t > 0.55 else "#242424"
            txt = esc(fmt(v)) if (show_values and v) else ""
            cells.append('<td style="background:%s;color:%s;text-align:center;font:400 9.5px var(--mono);padding:6px 2px;border:1px solid #fff;border-bottom:1px solid #fff" title="%s / %s: %s">%s</td>' % (col, fg, esc(lab), "", esc(fmt(v)), txt))
        body.append('<tr><td style="white-space:nowrap;padding:0 10px 0 0;border:0;font-size:11px">%s</td>%s</tr>' % (esc(lab), "".join(cells)))
    return '<table class="data heat" style="table-layout:auto"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, "".join(body))


LEVEL_FILL = ["#f2f2f2", "#f3e6c8", "#efc9cc", "#b3242e"]       # none / watch / high / critical, light to strong


def matrix_grid(cells, n_rows=5, n_cols=5, level=None, row_title="", col_title="", row_label=None, col_label=None):
    """Labelled grid for a risk matrix (likelihood x impact) or any two-axis category grid.
    cells: {(row, col): text} with 1-based indices; row n_rows is drawn at the top.
    level(row, col) -> 0..3 picks the fill (gray, amber tint, red tint, red) so bands read without colour names."""
    row_label = row_label or (lambda r: str(r)); col_label = col_label or (lambda c: str(c))
    level = level or (lambda r, c: 0)
    head = "".join('<th class="num" style="text-align:center">%s</th>' % esc(col_label(c)) for c in range(1, n_cols + 1))
    body = []
    for r in range(n_rows, 0, -1):
        tds = []
        for c in range(1, n_cols + 1):
            lv = max(0, min(3, level(r, c)))
            fg = "#fff" if lv == 3 else "#242424"
            tds.append('<td style="background:%s;color:%s;text-align:center;font:500 10.5px var(--mono);padding:9px 4px;border:1px solid #fff">%s</td>' % (LEVEL_FILL[lv], fg, esc(cells.get((r, c), ""))))
        body.append('<tr><td style="white-space:nowrap;border:0;padding-right:10px;font:500 10.5px var(--mono);color:#777">%s</td>%s</tr>' % (esc(row_label(r)), "".join(tds)))
    cap = '<p class="fn" style="text-align:center;margin-top:4px">%s</p>' % esc(col_title) if col_title else ""
    top = '<p class="fn" style="margin:0 0 4px">%s</p>' % esc(row_title) if row_title else ""
    return '%s<table class="data heat" style="table-layout:fixed"><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table>%s' % (top, head, "".join(body), cap)


def scatter(points, x_label="", y_label="", height=240, colors=None, r=3.5):
    """Scatter plot as inline SVG. points: [(x, y)] or grouped {name: [(x, y), ...]}. Black dots; groups use the series colours."""
    groups = points if isinstance(points, dict) else {"": list(points)}
    colors = colors or SERIES
    allp = [p for g in groups.values() for p in g]
    W, H, L, R, T, B = 640, height, 44, 12, 12, 38
    pw, ph = W - L - R, H - T - B
    xmax = _nice_max(max([p[0] for p in allp] + [1])); ymax = _nice_max(max([p[1] for p in allp] + [1]))
    xmin = 0; ymin = 0
    o = ['<svg class="svg-chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, esc("%s vs %s" % (y_label, x_label) if x_label else "Scatter plot"))]
    for k in range(6):
        y = T + ph - ph * k / 5.0; x = L + pw * k / 5.0
        o.append('<line class="chart-gridline" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="chart-axis" x="%d" y="%.1f" text-anchor="end">%s</text>' % (L, W - R, y, y, L - 5, y + 3, _fmt(ymax * k / 5.0)))
        o.append('<line class="chart-gridline" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/><text class="chart-axis" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x, x, T, T + ph, x, T + ph + 14, _fmt(xmax * k / 5.0)))
    o.append('<line x1="%d" x2="%d" y1="%d" y2="%d" stroke="#111"/><line x1="%d" x2="%d" y1="%d" y2="%d" stroke="#111"/>' % (L, W - R, T + ph, T + ph, L, L, T, T + ph))
    for gi, (name, pts) in enumerate(groups.items()):
        c = colors[gi % len(colors)]
        for p in pts:
            o.append('<circle cx="%.1f" cy="%.1f" r="%s" fill="%s" fill-opacity=".75"><title>%s(%s, %s)</title></circle>' % (L + pw * p[0] / xmax, T + ph - ph * p[1] / ymax, r, c, esc(name + " " if name else ""), _fmt(p[0]), _fmt(p[1])))
    if x_label:
        o.append('<text class="chart-axis" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (L + pw / 2, H - 4, esc(x_label)))
    if y_label:
        o.append('<text class="chart-axis" x="10" y="%.1f" text-anchor="middle" transform="rotate(-90 10 %.1f)">%s</text>' % (T + ph / 2, T + ph / 2, esc(y_label)))
    o.append("</svg>")
    names = [k for k in groups if k]
    return '<div class="fig">%s%s</div>' % ("".join(o), _legend(names, colors) if names else "")


def line_chart(labels, series, height=190, colors=None, y_label=""):
    """Line chart as inline SVG. series: [values] or [(name, [values]), ...]. First series black, then blue, gray, amber, red."""
    names, data = _norm_series(series, len(labels))
    colors = colors or SERIES
    W, H, L, R, T, B = 640, height, 38, 8, 12, 28
    pw, ph = W - L - R, H - T - B
    ymax = _nice_max(max([v for d in data for v in d] + [1])); n = len(labels)
    o = ['<svg class="svg-chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, esc(y_label or "Line chart"))]
    for k in range(6):
        y = T + ph - ph * k / 5.0
        o.append('<line class="chart-gridline" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="chart-axis" x="%d" y="%.1f" text-anchor="end">%s</text>' % (L, W - R, y, y, L - 5, y + 3, _fmt(ymax * k / 5.0)))
    xs = [L + (pw * i / float(max(n - 1, 1))) for i in range(n)]
    for si, d in enumerate(data):
        pts = " ".join("%.1f,%.1f" % (xs[i], T + ph - ph * v / ymax) for i, v in enumerate(d))
        o.append('<polyline fill="none" stroke="%s" stroke-width="1.8" stroke-linejoin="round" points="%s"/>' % (colors[si % len(colors)], pts))
    step = max(1, n // 10)
    for i in range(0, n, step):
        o.append('<text class="chart-axis" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (xs[i], H - 10, esc(labels[i])))
    o.append("</svg>")
    return '<div class="fig">%s%s</div>' % ("".join(o), _legend(names, colors))


def gauge(value, label="", heading="", text="", max_value=100, color="#175d9a"):
    """Single-figure ring with a short interpretation beside it. value 0..max_value."""
    pct = max(0.0, min(100.0, 100.0 * float(value) / float(max_value)))
    return ('<div class="gauge"><div style="position:relative;width:96px;height:96px;flex-shrink:0"><div class="gauge-ring" style="background:conic-gradient(%s 0 %.1f%%,#e2e2e2 %.1f%% 100%%)"></div>'
            '<div class="c" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center"><div class="s">%s</div><div class="t">%s</div></div></div>'
            '<div class="gauge-txt"><h4>%s</h4><p>%s</p></div></div>' % (color, pct, pct, esc(_fmt(value)), esc(label), esc(heading), esc(text)))


def segment_bar(segments, total=None):
    """One proportional strip split into coloured segments with a count legend. segments: [(label, value)] (series colours in order)."""
    total = float(total or sum(v for _, v in segments) or 1)
    strip = "".join('<div style="width:%.2f%%;background:%s;height:100%%" title="%s: %s"></div>' % (100.0 * v / total, SERIES[i % len(SERIES)], esc(l), esc(_fmt(v))) for i, (l, v) in enumerate(segments) if v > 0)
    leg = "".join('<span><em style="background:%s"></em>%s: %s</span>' % (SERIES[i % len(SERIES)], esc(l), esc(_fmt(v))) for i, (l, v) in enumerate(segments))
    return '<div style="display:flex;height:12px;background:#e2e2e2;margin:8px 0 6px">%s</div><div class="legend">%s</div>' % (strip, leg)


def sparkline(values, width=96, height=22, color="#111111"):
    """Tiny inline trend line for a table cell or KPI. Returns an <svg> fragment."""
    vals = list(values)
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals); span = (hi - lo) or 1.0
    pts = " ".join("%.1f,%.1f" % (1 + (width - 2) * i / float(len(vals) - 1), height - 2 - (height - 4) * (v - lo) / span) for i, v in enumerate(vals))
    return ('<svg viewBox="0 0 %d %d" width="%d" height="%d" style="vertical-align:middle"><polyline fill="none" stroke="%s" stroke-width="1.4" stroke-linejoin="round" points="%s"/>'
            '<circle cx="%.1f" cy="%.1f" r="1.8" fill="%s"/></svg>' % (width, height, width, height, color, pts, 1 + (width - 2), height - 2 - (height - 4) * (vals[-1] - lo) / span, color))


# -- documents ------------------------------------------------------------

def page(title, eyebrow, body="", subtitle="", meta="", kpis=None, summary="", steps=None, chips=None,
         footer_left=None, data_date=None, extra_css="", band=None, method="", fields=None):
    """A complete branded document. `body` is HTML (sections, tables, callouts). `band` = [(heading, html)] x3."""
    parts = [hero(eyebrow, title, subtitle, meta, chips, fields)]
    if kpis:
        parts.append(kpi_strip(kpis))
    if band:
        parts.append(globals()["band"](band))
    if summary:
        parts.append('<div class="summary">%s</div>' % summary)
    if body:
        parts.append(body)
    if steps:
        parts.append(next_steps(steps))
    if method:
        parts.append(methodology(method))
    parts.append(footer(footer_left or title, data_date))
    return shell(title, '<div class="page">%s</div>' % "".join(parts), extra_css)


def shell(title, body_html, extra_css=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="fluency-brand" content="1"><title>%s · Fluency Report</title><style>%s%s</style></head><body>%s</body></html>'
            % (esc(title), CSS, extra_css, body_html))


# -- restyling older reports ---------------------------------------------

def _split_rules(css):
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j == -1:
            break
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        yield css[i:j].strip(), css[j + 1:k - 1]
        i = k


_BRAND_CLASSES = None
_BRAND_VARS = None


def _brand_index():
    global _BRAND_CLASSES, _BRAND_VARS
    if _BRAND_CLASSES is None:
        _BRAND_CLASSES = set(re.findall(r"\.([A-Za-z_][\w-]*)", CSS))
        _BRAND_VARS = set(re.findall(r"(--[\w-]+)\s*:", CSS))
    return _BRAND_CLASSES, _BRAND_VARS


def carry_over_css(legacy):
    """Keep only what the brand sheet does not already define: rules using a class the brand has never heard of,
    and custom properties with new names. Everything else is dropped so the brand look always wins."""
    classes, vars_ = _brand_index()
    out = []
    for pre, body in _split_rules(legacy):
        if pre.startswith("@media"):
            inner = carry_over_css(body)
            if inner.strip() and "print" in pre:
                out.append("%s{%s}" % (pre, inner))
            continue
        if pre.startswith("@"):
            continue
        if pre.strip() == ":root":
            decls = [d for d in body.split(";") if d.strip() and d.split(":")[0].strip() not in vars_]
            if decls:
                out.append(":root{%s}" % ";".join(decls))
            continue
        cls = set(re.findall(r"\.([A-Za-z_][\w-]*)", pre))
        if cls and (cls - classes):
            out.append("%s{%s}" % (pre, body))
    return "\n".join(out)


LEGACY_COLORS = {  # colours older report scripts hard-code in inline styles / SVG -> the editorial palette
    "#14213d": "#111111", "#1d2a52": "#111111", "#0e1530": "#111111", "#1a1f2c": "#111111",
    "#b45309": "#a06c00", "#e8a01e": "#a06c00", "#d97706": "#a06c00", "#f59e0b": "#a06c00",
    "#b91c1c": "#b3242e", "#c0161c": "#b3242e", "#e81e25": "#b3242e", "#dc2626": "#b3242e",
    "#1d4ed8": "#175d9a", "#2d65a1": "#175d9a", "#457fc1": "#175d9a", "#15803d": "#175d9a", "#1f9d55": "#175d9a",
    "#0f766e": "#175d9a", "#2563eb": "#175d9a", "#7c3aed": "#8a8a8a", "#5b4b8a": "#8a8a8a", "#6d28d9": "#8a8a8a",
    "#7f1d1d": "#b3242e", "#475569": "#444444", "#64748b": "#8a8a8a", "#6b7385": "#8a8a8a", "#94a3b8": "#8a8a8a", "#e2e8f0": "#e2e2e2", "#eef0f4": "#e2e2e2", "#e3e6ec": "#d8d8d8",
}


_CSSVARS = {"var(--blue)": "#175d9a", "var(--red)": "#b3242e", "var(--amber)": "#a06c00", "var(--green)": "#175d9a", "var(--gray)": "#8a8a8a", "var(--ink)": "#111111"}


def legacy_color(c, default="#175d9a"):
    """Map a colour an older script passes (hex, or a CSS variable) onto the editorial palette."""
    c = (c or "").strip()
    if c.lower() in LEGACY_COLORS:
        return LEGACY_COLORS[c.lower()]
    return _CSSVARS.get(c, c if re.match(r"^#[0-9a-fA-F]{6}$", c) else default)


def semantic_color(c):
    """Return the palette colour only when it carries meaning (red / amber), else None so bar_rows uses its default lead-blue / gray."""
    c = legacy_color(c, default="")
    return c if c in ("#b3242e", "#a06c00") else None


def remap_colors(doc):
    """Remap legacy hex colours outside <style> blocks to the editorial palette."""
    parts = re.split(r"(<style[^>]*>.*?</style>)", doc, flags=re.S | re.I)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: LEGACY_COLORS.get(m.group(0).lower(), m.group(0)), parts[i])
    return "".join(parts)


def apply_brand(doc, eyebrow=None, keep_css=True, footer_left=None, data_date=None):
    """Restyle an older report document in place.

    - replaces its <style> blocks with the brand CSS (rules for report-specific classes are carried over)
    - puts the brandline above the first .hero and the large lock mark into it
    - appends the standard footer
    The body markup is untouched, so existing report logic keeps working."""
    doc = remap_colors(doc)
    styles = re.findall(r"<style[^>]*>.*?</style>", doc, flags=re.S | re.I)
    legacy = carry_over_css("\n".join(re.sub(r"</?style[^>]*>", "", s, flags=re.I) for s in styles)) if keep_css else ""
    doc = re.sub(r"<style[^>]*>.*?</style>", "", doc, flags=re.S | re.I)
    block = '<meta name="fluency-brand" content="1"><style>%s\n%s</style>' % (CSS, legacy)
    doc = doc.replace("</head>", block + "</head>", 1) if "</head>" in doc else block + doc
    m = re.search(r"<title>(.*?)</title>", doc, flags=re.S)
    ttl = re.sub(r"\s*·\s*Fluency Report$", "", _html.unescape(m.group(1))) if m else "Report"
    hero_re = re.compile(r"""<div class=["']?hero["']?>""")
    if hero_re.search(doc) and 'class="brandline"' not in doc:
        # drop legacy hero chrome (old logo chips, hero-top) and any eyebrow paragraph that duplicates the brandline
        em = re.search(r"""<(?:p|div) class=["']?(?:hero-eyebrow|eyebrow)["']?>(.*?)</(?:p|div)>""", doc, flags=re.S)
        label = eyebrow or (_html.unescape(re.sub("<[^>]+>", "", em.group(1))) if em else ttl)
        if em and not eyebrow:
            doc = doc.replace(em.group(0), "", 1)
        doc = hero_re.sub(lambda mm: brandline(label) + mm.group(0), doc, count=1)
        doc = re.sub(r"""(<div class=["']?hero["']?>\s*<div class=["']?wrap["']?>)""", lambda mm: mm.group(1) + '<img class="hero-mark" src="%s" alt="">' % MARK_URI, doc, count=1)
    elif 'class="brandline"' not in doc:
        doc = re.sub(r"<body[^>]*>", lambda mm: mm.group(0) + brandline(eyebrow or ttl), doc, count=1)
    if not re.search(r"""class=["']?(brand-foot|footer)["']?[ >]""", doc):
        left = footer_left or ("%s · %s" % (ttl, eyebrow) if eyebrow else ttl)
        doc = re.sub(r"</body>", lambda mm: footer(left, data_date, "brand-foot") + "</body>", doc, count=1)
    return doc


# -- PDF ------------------------------------------------------------------

def to_pdf(html_path, pdf_path, title=None):
    """Render with the bundled US-Letter renderer (Playwright + Chromium via node)."""
    script = os.path.join(HERE, "render_pdf.mjs")
    cmd = ["node", script, "--input", html_path, "--output", pdf_path]
    if title:
        cmd += ["--title", title]
    subprocess.run(cmd, check=True)
    return pdf_path


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "pdf":
        to_pdf(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else re.sub(r"\.html?$", ".pdf", sys.argv[2]))
    else:
        print(__doc__)
