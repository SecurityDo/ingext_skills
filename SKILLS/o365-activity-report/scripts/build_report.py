#!/usr/bin/env python3
"""
o365-activity-report : build_report.py

Turns raw account-wide Office365-datalake KQL results (saved by the agent as
JSON) into a single self-contained HTML activity report: a KPI strip, a
timechart of events over the window, and ranked breakdown tables.

The report is rendered DETERMINISTICALLY from the saved query output — the
script never invents a figure. Any query file that is missing or returns zero
rows renders an explicit "no data in this window" panel, and a "Data sources"
appendix lists every file with its row count so each number is traceable.

Usage:
  python3 build_report.py \
    --workdir /tmp/o365_act \
    --focus   exchange \            # all | exchange | mailitemsaccessed
    --tenant  "acme" \
    --from-ms 1773862340254 \
    --to-ms   1781638340254 \
    --bin     1h \
    --output  /tmp/o365_act/o365_activity.html \
    [--pdf    /tmp/o365_act/o365_activity.pdf]

Expected files in --workdir (raw kql_search output is fine — see SKILL.md).
All are optional; a missing/empty file becomes a truthful "no data" panel:
  overview.json     single-row KPIs
  timechart.json    (timestamp, [series], events)  -> line chart
  operations.json   Operation, events, ...          (exchange/all)
  workload.json     Workload, events, ...           (all)
  top_users.json    UserId, events, ...             (exchange/all)
  top_ips.json      ClientIPAddress, events|accesses, ...
  top_mailboxes.json MailboxOwnerUPN, accesses, ... (mailitemsaccessed)
  logontype.json    LogonType, accesses            (mailitemsaccessed)
"""
import argparse, json, os, html as _H, datetime as dt

# ----------------------------- parsing --------------------------------------
def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return None

def table_to_dicts(obj):
    """Accept raw kql_search output (or already-extracted forms) -> list[dict]."""
    if obj is None:
        return []
    data = obj
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], dict):
            data = obj["data"]
        if isinstance(data, dict) and "Tables" in data and data["Tables"]:
            t = data["Tables"][0]
            cols = [c.get("ColumnName", c.get("name")) for c in t["Columns"]]
            return [dict(zip(cols, r)) for r in t.get("Rows", [])]
        if "objects" in obj and obj["objects"]:   # FPL-style fallback
            try:
                tbl = obj["objects"][0]["table"]
                cols = [c["name"] for c in tbl["columns"]]
                rows = tbl["rows"]
                if rows and isinstance(rows[0], dict):
                    return rows
                return [dict(zip(cols, r)) for r in rows]
            except Exception:
                return []
    if isinstance(obj, list):
        return obj
    return []

def load_rows(workdir, name):
    return table_to_dicts(load(os.path.join(workdir, name)))

def num(x):
    try:
        if isinstance(x, bool):
            return int(x)
        return int(x)
    except Exception:
        try:
            return float(x)
        except Exception:
            return 0

def is_number(x):
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return True
    try:
        float(x)
        return True
    except Exception:
        return False

def parse_ts(v):
    """epoch-ms | epoch-s | ISO8601 -> aware UTC datetime (or None)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
        n = float(v)
        if n > 1e12:      # milliseconds
            n /= 1000.0
        elif n > 1e15:    # microseconds
            n /= 1e6
        try:
            return dt.datetime.fromtimestamp(n, dt.timezone.utc)
        except Exception:
            return None
    s = str(v).replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None

def esc(x):
    return _H.escape("" if x is None else str(x))

def humanize(col):
    import re
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(col))
    s = s.replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else s

def fmt_num(x):
    n = num(x)
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.1f}"

def fmt_ts(v):
    d = parse_ts(v)
    return d.strftime("%Y-%m-%d %H:%M") if d else esc(v)

PALETTE = ["#4493f8", "#3fb950", "#f0a020", "#f85149", "#a371f7",
           "#39c5cf", "#db61a2", "#e3b341", "#7ee787", "#ff9bce"]

# ----------------------------- panels ---------------------------------------
def panel(title, body, accent=""):
    cls = "r" if accent == "r" else ""
    return f'<section><h3 class="{cls}">{esc(title)}</h3>{body}</section>'

def nodata(msg="No data returned for this panel in the selected window."):
    return f'<p class="note nd">&#9679; {esc(msg)}</p>'

def render_kpis(rows):
    """Single-row overview dict -> KPI strip (one card per numeric column)."""
    if not rows:
        return None
    row = rows[0]
    cards = []
    for col, val in row.items():
        if not is_number(val):
            continue
        low = str(col).lower()
        cls = "warn" if ("fail" in low or "external" in low) and num(val) > 0 else ""
        cards.append(
            f'<div class="kpi {cls}"><div class="n">{fmt_num(val)}</div>'
            f'<div class="l">{esc(humanize(col))}</div></div>'
        )
    if not cards:
        return None
    return f'<div class="kpis">{"".join(cards)}</div>'

def detect_timechart_cols(rows):
    """-> (time_col, value_col, series_col|None)."""
    cols = list(rows[0].keys())
    time_col = "timestamp" if "timestamp" in cols else None
    if time_col is None:
        for c in cols:
            if parse_ts(rows[0].get(c)) is not None and "time" in c.lower():
                time_col = c; break
    if time_col is None:
        for c in cols:
            if parse_ts(rows[0].get(c)) is not None:
                time_col = c; break
    if time_col is None:
        return None, None, None
    prefer_val = ["events", "accesses", "count_", "count", "logins", "value", "total"]
    value_col = next((c for c in prefer_val if c in cols), None)
    if value_col is None:
        value_col = next((c for c in cols if c != time_col and is_number(rows[0].get(c))), None)
    if value_col is None:
        return time_col, None, None
    series_col = next((c for c in cols
                       if c not in (time_col, value_col) and not is_number(rows[0].get(c))), None)
    return time_col, value_col, series_col

def render_timechart(rows, bin_label=""):
    if not rows:
        return None
    time_col, value_col, series_col = detect_timechart_cols(rows)
    if not time_col or not value_col:
        return None
    # series -> ordered list of (datetime, value)
    series = {}
    for row in rows:
        d = parse_ts(row.get(time_col))
        if d is None:
            continue
        key = str(row.get(series_col)) if series_col else "events"
        series.setdefault(key, []).append((d, num(row.get(value_col))))
    if not series:
        return None
    for k in series:
        series[k].sort(key=lambda p: p[0])
    all_t = sorted({p[0] for pts in series.values() for p in pts})
    all_v = [p[1] for pts in series.values() for p in pts]
    if not all_t or not all_v:
        return None
    tmin, tmax = all_t[0], all_t[-1]
    vmax = max(all_v) or 1
    span = (tmax - tmin).total_seconds() or 1.0

    W, H = 900, 320
    PL, PR, PT, PB = 58, 20, 18, 46
    iw, ih = W - PL - PR, H - PT - PB
    def X(d): return PL + iw * ((d - tmin).total_seconds() / span)
    def Y(v): return PT + ih * (1 - (v / vmax))

    parts = [f'<svg class="tc" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" role="img">']
    # y gridlines + labels (0, 25, 50, 75, 100%)
    for frac in (0, .25, .5, .75, 1):
        y = PT + ih * (1 - frac); val = int(round(vmax * frac))
        parts.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{PL-8}" y="{y+3:.1f}" class="ylab">{val:,}</text>')
    # x ticks (~6)
    n_ticks = min(6, len(all_t))
    for i in range(n_ticks):
        d = tmin + dt.timedelta(seconds=span * (i / max(1, n_ticks - 1)))
        x = X(d)
        lab = d.strftime("%m-%d %H:%M")
        parts.append(f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{PT+ih}" class="grid vg"/>')
        parts.append(f'<text x="{x:.1f}" y="{H-PB+18}" class="xlab" text-anchor="middle">{lab}</text>')
    # one polyline per series
    ordered = sorted(series.items(), key=lambda kv: -sum(v for _, v in kv[1]))
    for i, (name, pts) in enumerate(ordered):
        color = PALETTE[i % len(PALETTE)]
        d = " ".join(f'{"M" if j == 0 else "L"}{X(t):.1f},{Y(v):.1f}' for j, (t, v) in enumerate(pts))
        if len(ordered) == 1:  # single series: subtle area fill
            area = d + f' L{X(pts[-1][0]):.1f},{PT+ih:.1f} L{X(pts[0][0]):.1f},{PT+ih:.1f} Z'
            parts.append(f'<path d="{area}" fill="{color}" opacity="0.10"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{esc(name)}</span>'
        for i, (name, _) in enumerate(ordered))
    binnote = f" (per {esc(bin_label)} bin)" if bin_label else ""
    return (f'<div class="chartwrap">{"".join(parts)}</div>'
            f'<div class="legend">{legend}</div>'
            f'<p class="note">Events over the reporting window{binnote}, UTC.</p>')

def render_table(rows, bar_col=None, ts_cols=("lastSeen", "firstSeen", "timestamp")):
    if not rows:
        return None
    cols = list(rows[0].keys())
    barmax = max((num(r.get(bar_col)) for r in rows), default=0) if bar_col else 0
    head = "".join(f"<th>{esc(humanize(c))}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if c == bar_col and barmax:
                pct = 100.0 * num(v) / barmax
                cells.append(
                    f'<td><div class="volwrap"><span class="vol">'
                    f'<span class="volfill" style="width:{pct:.1f}%"></span></span>'
                    f'<span class="voln">{fmt_num(v)}</span></div></td>')
            elif c in ts_cols:
                cells.append(f'<td class="mono">{fmt_ts(v)}</td>')
            elif is_number(v):
                cells.append(f'<td>{fmt_num(v)}</td>')
            else:
                mono = "mono" if any(k in c.lower() for k in ("ip", "user", "mailbox", "id")) else ""
                cells.append(f'<td class="{mono}">{esc(v)}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

# ----------------------------- report ---------------------------------------
FOCUS_TITLES = {
    "all": "Office 365 Activity",
    "exchange": "Office 365 Exchange Activity",
    "mailitemsaccessed": "Office 365 MailItemsAccessed Activity",
}

# (filename, section title, render-kind, bar-column) per focus.
PANELS = {
    "exchange": [
        ("timechart.json",  "Activity timechart",        "chart", None),
        ("operations.json", "Top Exchange operations",   "table", "events"),
        ("top_users.json",  "Most active users",         "table", "events"),
        ("top_ips.json",    "Top source IP addresses",   "table", "events"),
    ],
    "all": [
        ("timechart.json",  "Activity timechart (by workload)", "chart", None),
        ("workload.json",   "Activity by workload",      "table", "events"),
        ("operations.json", "Top operations",            "table", "events"),
        ("top_users.json",  "Most active users",         "table", "events"),
        ("top_ips.json",    "Top source IP addresses",   "table", "events"),
    ],
    "mailitemsaccessed": [
        ("timechart.json",     "MailItemsAccessed timechart (external vs internal)", "chart", None),
        ("top_mailboxes.json", "Most-accessed mailboxes", "table", "accesses"),
        ("top_ips.json",       "Source IPs accessing mail", "table", "accesses"),
        ("logontype.json",     "Access by logon type",    "table", "accesses"),
    ],
}

def data_derived_headline(focus, overview_rows, tc_rows):
    bits = []
    if overview_rows:
        row = overview_rows[0]
        prim = "TotalAccesses" if focus == "mailitemsaccessed" else "TotalEvents"
        if prim in row:
            noun = "accesses" if focus == "mailitemsaccessed" else "events"
            bits.append(f"{fmt_num(row[prim])} {noun}")
        for k, lbl in (("UniqueMailboxes", "mailboxes"), ("UniqueUsers", "users"),
                       ("UniqueActors", "actors"), ("UniqueClientIPs", "IPs")):
            if k in row and num(row[k]):
                bits.append(f"{fmt_num(row[k])} {lbl}")
        if num(row.get("ExternalAccess", 0)):
            bits.append(f"{fmt_num(row['ExternalAccess'])} external")
    # busiest bin from the timechart (real data only)
    if tc_rows:
        tcol, vcol, scol = detect_timechart_cols(tc_rows)
        if tcol and vcol:
            agg = {}
            for r in tc_rows:
                d = parse_ts(r.get(tcol))
                if d is None:
                    continue
                agg[d] = agg.get(d, 0) + num(r.get(vcol))
            if agg:
                peak = max(agg.items(), key=lambda kv: kv[1])
                bits.append(f"busiest bin {peak[0].strftime('%m-%d %H:%M')}Z ({fmt_num(peak[1])})")
    return "; ".join(bits[:6])

def build(a):
    wd = a.workdir
    focus = a.focus if a.focus in PANELS else "exchange"
    overview = load_rows(wd, "overview.json")
    tc_rows = load_rows(wd, "timechart.json")

    fmt_win = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%b %d %Y %H:%M")
    win = f"{fmt_win(a.from_ms)} &rarr; {fmt_win(a.to_ms)} UTC"
    headline = data_derived_headline(focus, overview, tc_rows) or "No matching events in the selected window."

    # A file that was never written (save step failed) is a DIFFERENT thing from a
    # file that exists but returned zero rows (a truthful empty window). The first
    # is a broken build that must not ship looking finished; the second is fine.
    def fstatus(fname, nrows):
        if not os.path.exists(os.path.join(wd, fname)):
            return "missing"
        return "ok" if nrows else "empty"

    # KPI strip
    kpi_html = render_kpis(overview) or (
        nodata("overview.json was not saved — re-run the overview query and save it.")
        if fstatus("overview.json", len(overview)) == "missing"
        else nodata("No overview counts for this window."))

    # panels
    manifest = [("overview.json", len(overview), fstatus("overview.json", len(overview)))]
    sections = []
    for fname, title, kind, barcol in PANELS[focus]:
        rows = tc_rows if kind == "chart" else load_rows(wd, fname)
        st = fstatus(fname, len(rows))
        manifest.append((fname, len(rows), st))
        if st == "missing":
            body = nodata(f"{fname} was not saved — this query's result never reached the "
                          f"build step, so the panel is blank. Re-run the query and save it.")
        elif kind == "chart":
            body = render_timechart(rows, a.bin) or nodata("No time-series events to chart.")
        else:
            body = render_table(rows, bar_col=barcol) or nodata()
        sections.append(panel(title, body))

    missing = [f for f, _, s in manifest if s == "missing"]

    # data-source appendix (provenance)
    STLAB = {"ok": "ok",
             "empty": '<span class=nd>empty (no rows in window)</span>',
             "missing": '<span class=nd>MISSING — not saved</span>'}
    src_rows = "".join(
        f"<tr><td class=mono>{esc(f)}</td><td>{n:,}</td><td>{STLAB[s]}</td></tr>"
        for f, n, s in manifest)
    appendix = panel("Data sources",
                     f'<table><thead><tr><th>Query file</th><th>Rows</th><th>Status</th></tr></thead>'
                     f'<tbody>{src_rows}</tbody></table>'
                     f'<p class="note">Every figure above is rendered directly from these saved KQL '
                     f'results. <b>empty</b> = the query ran and returned no rows for the window. '
                     f'<b>MISSING</b> = the result was never saved to file, so its panel is blank for a '
                     f'build reason, not a data reason — re-run and save it.</p>')

    # A loud, unmissable banner when required results never reached the renderer, so a
    # half-empty report can never be mistaken for a real "quiet window".
    banner = ""
    if missing:
        banner = (f'<div class="banner">&#9888; <b>INCOMPLETE REPORT</b> — {len(missing)} of '
                  f'{len(manifest)} query result(s) were not saved and are missing from this build: '
                  f'<span class=mono>{esc(", ".join(missing))}</span>. The blank panels below are blank '
                  f'because that data never reached the renderer — <b>not</b> because the window was '
                  f'empty. Re-run the missing queries, save each to its file in the workdir, and rebuild.'
                  f'</div>')

    title = FOCUS_TITLES.get(focus, "Office 365 Activity")
    gen = dt.datetime.fromtimestamp(a.to_ms / 1000, dt.timezone.utc).strftime("%b %d %Y %H:%M")
    tenant = esc(a.tenant or "—")

    HTML = f"""<!DOCTYPE html><html lang=en><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width, initial-scale=1.0">
<title>{esc(title)} — {tenant}</title><style>
:root{{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--line:#2a3340;--txt:#e6edf3;--muted:#9aa7b4;--blue:#4493f8;--amber:#f0a020;--red:#f85149;--green:#3fb950}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:14px;line-height:1.5}}
.wrap{{max-width:1000px;margin:0 auto;padding:30px 22px 60px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px;flex-wrap:wrap;gap:14px}}
.brand{{font-weight:700;font-size:17px;letter-spacing:.5px}}.brand span{{color:var(--blue)}}
h1{{font-size:21px;margin:4px 0 6px}}.sub{{color:var(--muted);font-size:13px;max-width:70ch}}
.mono{{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace}}
.meta{{text-align:right;font-size:12px;color:var(--muted)}}.meta b{{color:var(--txt)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:0 0 26px}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}
.kpi .n{{font-size:24px;font-weight:700}}.kpi .l{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
.kpi.warn .n{{color:var(--amber)}}
.banner{{background:rgba(248,81,73,.12);border:1px solid var(--red);border-radius:8px;padding:12px 15px;margin:0 0 18px;color:#f7b0ad;font-size:13px;line-height:1.5}}
section{{margin-bottom:28px}}h3{{font-size:15px;border-left:3px solid var(--blue);padding-left:10px;margin:0 0 13px}}h3.r{{border-color:var(--red)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle;overflow-wrap:anywhere}}
th{{background:var(--panel2);color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}}
tbody tr:last-child td{{border-bottom:none}}
.volwrap{{display:flex;align-items:center;gap:8px;min-width:120px}}
.vol{{position:relative;flex:1;height:8px;background:var(--panel2);border-radius:5px;overflow:hidden;min-width:50px}}
.volfill{{position:absolute;left:0;top:0;bottom:0;background:var(--blue);border-radius:5px}}
.voln{{font-variant-numeric:tabular-nums;min-width:52px;text-align:right}}
.chartwrap{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 6px 4px}}
svg.tc{{width:100%;height:auto;display:block}}
svg.tc .grid{{stroke:#243040;stroke-width:1}}svg.tc .vg{{stroke-dasharray:2 4}}
svg.tc .ylab{{fill:var(--muted);font-size:11px;text-anchor:end;font-family:ui-monospace,monospace}}
svg.tc .xlab{{fill:var(--muted);font-size:11px;font-family:ui-monospace,monospace}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:8px 2px 0}}
.legend i{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}}
.note{{color:var(--muted);font-size:12px;margin-top:8px}}.nd{{color:var(--amber)}}
.lead{{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:8px;padding:12px 15px;margin:0 0 22px}}
footer{{border-top:1px solid var(--line);margin-top:36px;padding-top:14px;color:var(--muted);font-size:11px}}
@media(max-width:640px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><div class=wrap>
<header>
<div><div class=brand>FLUENCY<span>&middot;</span>Ingext</div>
<h1>{esc(title)}</h1>
<div class="sub">Account-wide Microsoft 365 audit activity, queried from the Office365 datalake with KQL.</div></div>
<div class=meta><div>Tenant: <b>{tenant}</b></div><div>Window: <b>{win}</b></div>
<div>Generated: <b>{gen} UTC</b></div><div>Source: <b>Office365 datalake (KQL)</b></div></div>
</header>

{banner}

<div class="lead">{esc(headline)}</div>

{kpi_html}

{"".join(sections)}

{appendix}

<footer>Generated by the o365-activity-report skill from the Office365 datalake via KQL.
Every value is rendered directly from the saved query results; no figures are synthesized.
Timestamps are UTC.</footer>
</div></body></html>"""

    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    open(a.output, "w").write(HTML)
    print("HTML written:", a.output)

    if a.pdf:
        try:
            from weasyprint import HTML as WHTML
            override = "<style>table{font-size:11px}td,th{overflow-wrap:anywhere}</style>"
            WHTML(string=HTML.replace("</head>", override + "</head>", 1)).write_pdf(a.pdf)
            print("PDF written:", a.pdf)
        except Exception as e:
            print("PDF step skipped (", e, ")")

    return missing

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", required=True)
    p.add_argument("--focus", default="exchange", choices=["all", "exchange", "mailitemsaccessed"])
    p.add_argument("--tenant", default="")
    p.add_argument("--from-ms", dest="from_ms", type=int, required=True)
    p.add_argument("--to-ms", dest="to_ms", type=int, required=True)
    p.add_argument("--bin", default="")
    p.add_argument("--output", required=True)
    p.add_argument("--pdf", default="")
    missing = build(p.parse_args())
    if missing:
        import sys
        print("INCOMPLETE: query results never saved (panels blank for a build reason, "
              "not a data reason): " + ", ".join(missing), file=sys.stderr)
        print("Re-run each missing query, save its raw result to <workdir>/<name>.json, "
              "then rebuild. Do not deliver this report as-is.", file=sys.stderr)
        sys.exit(3)

if __name__ == "__main__":
    main()
