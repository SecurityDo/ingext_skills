#!/usr/bin/env python3
"""Build the FortiGate Traffic Activity report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv report.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site NAME] [--top 10] [--no-actors]

Each --archive file is the saved result of download_report_archive for Fortigate_Traffic_Activity_Report (days[] of
{entry, result}); several files and several days per file are merged. This script never queries a tenant. Rules: the
per-day trend rows and every per-entity table are summed (events, blocked events and byte volumes all add across days);
a missing value is 0; a day that is not archived is a GAP, never zero; a day archived twice counts once (the latest run).
--no-actors drops every table that names an internal host or an IP address. The summary JSON carries the GenAI evidence
(per application, source, destination and policy) for the separate GenAI Egress report.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, sys
import os as _os, sys as _sys, glob as _glob
def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
    here = _os.path.dirname(_os.path.abspath(__file__)); home = _os.path.expanduser("~")
    cands = [_os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = _os.path.dirname(up); cands.append(_os.path.join(up, "fluency-report", "scripts"))
    cands += [_os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += _glob.glob(_os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and _os.path.exists(_os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")
_sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

STYLE = """
:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px 48px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:38px 0 70px}
.hero .wrap{padding-bottom:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}
.hero p{margin:0;color:#c7d4ee;font-size:14px}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-46px}
.kpis.row2{margin-top:14px;grid-template-columns:repeat(4,1fr)}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:30px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}.kpi small{display:block;color:var(--mut);font-size:11px;margin-top:2px}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.gap{border-left:4px solid #B45309;background:#fff7ed;border-radius:0 10px 10px 0;padding:12px 18px;margin-top:12px;color:#7c2d12}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
td.d{white-space:nowrap}
table.dt{font-size:11px}table.dt th,table.dt td{padding:6px 6px}table.dt th{letter-spacing:.02em}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.mut{color:var(--mut)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-size:12px;margin-bottom:4px}
.card svg{width:100%;height:auto;display:block}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
td.bar{width:24%}.bar i{display:block;height:8px;border-radius:4px;background:var(--c);min-width:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media screen and (max-width:760px){.kpis,.kpis.row2,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

E = html.escape
STYLE += "@media print{h2,h3,.sub{break-after:avoid;page-break-after:avoid}}"
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
REPORT = "Fortigate_Traffic_Activity_Report"
METRICS = ["events", "blocked", "bytesOut", "bytesIn", "genaiEvents", "genaiBytesOut"]
LABEL = {"events": "Log events", "blocked": "Blocked events", "bytesOut": "Bytes sent (out)", "bytesIn": "Bytes received (in)",
         "genaiEvents": "GenAI events", "genaiBytesOut": "GenAI bytes sent"}
# table name -> (key columns, summed columns)
TABLES = {
    "traffic_app": (["appName", "appCategory", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "traffic_service": (["serviceName", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "traffic_country": (["country", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "traffic_policy": (["policy", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "traffic_talkers": (["source", "host"], ["events", "blocked", "bytesOut", "bytesIn"]),
    "genai_app": (["appName", "appCategory", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "genai_source": (["source", "host", "appName", "outcome"], ["events", "bytesOut", "bytesIn"]),
    "genai_destination": (["destination", "country", "appName"], ["events", "bytesOut", "bytesIn"]),
    "genai_policy": (["policy", "appName", "outcome"], ["events", "bytesOut", "bytesIn"]),
}
ACTOR_TABLES = ("traffic_talkers", "genai_source", "genai_destination")
LIMITS = [
    "The source and destination tables name internal hosts and IP addresses, so the report is personal data. Share it only with the customer who owns the data, or build it with --no-actors.",
    "Top-N tables keep the largest rows of each archived day, so a range total for a row outside a day's top N is a lower bound. Distinct hosts or addresses are not counted because they cannot be added across days.",
    "Volumes are per-record deltas of the session byte counters (cumulative counters fall back only when a record has no delta). Events are log records, not sessions: a long session writes several records.",
    "Traffic logs carry no host name or URL, so destinations are identified by application, address and country, never by domain.",
    "GenAI traffic is what the firewall's Application Control labelled GenAI, or an application name that matches a known GenAI service. A firewall policy without Application Control writes no application name, so its GenAI use is not visible here; the share of events without an application name is shown as the coverage of this view.",
    "Only FortiGate traffic (forward) logs are scanned. VPN, administrator, web-filter and IPS events are in the FortiGate Security Activity report.",
    "An archived day is a snapshot taken a few hours after the day ended; events that arrive later are not added.",
    "A day missing from the archive is a gap, not zero activity. A scan the tenant could not run is 'not available', not zero.",
]

def n(v):
    return "{:,}".format(int(v))


def num(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def human(v):
    v = float(v or 0)
    for unit, size in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(v) >= size:
            return "%.2f %s" % (v / size, unit) if size >= 1e9 else "%.1f %s" % (v / size, unit)
    return "%d B" % v


def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "n/a"


ROWS_CAP = 8000   # the processor keeps at most this many rows of traffic_dims; a day at this size was truncated
# traffic_dims dim -> (virtual table, columns the val is split into). val parts are joined with " | ".
DIMS = {
    "app": ("traffic_app", ["appName", "appCategory"]),
    "service": ("traffic_service", ["serviceName"]),
    "country": ("traffic_country", ["country"]),
    "policy": ("traffic_policy", ["policy"]),
    "genaiApp": ("genai_app", ["appName", "appCategory"]),
    "genaiPolicy": ("genai_policy", ["policy", "appName"]),
    "genaiSource": ("genai_source", ["source", "host", "appName"]),
    "genaiDestination": ("genai_destination", ["destination", "country", "appName"]),
}


def expand_dims(tables):
    """Split the archived traffic_dims rows (dim, val, outcome, events, bytesOut, bytesIn) into the per-topic tables the
    merge works on. Returns the number of dims rows (to detect a result truncated at the processor's row cap)."""
    rows = tables.get("traffic_dims") or []
    trend = []
    for r in rows:
        dim, val = r.get("dim"), str(r.get("val") or "")
        ev, bo, bi = num(r.get("events")), num(r.get("bytesOut")), num(r.get("bytesIn"))
        blocked = r.get("outcome") == "blocked"
        if dim in ("device", "genaiDevice"):
            dev, _, day = val.partition(" | ")
            t = {"Date": day, "device": dev, "events": 0, "blocked": 0, "bytesOut": 0, "bytesIn": 0, "genaiEvents": 0, "genaiBytesOut": 0}
            if dim == "device":
                t.update(events=ev, blocked=ev if blocked else 0, bytesOut=bo, bytesIn=bi)
            else:
                t.update(genaiEvents=ev, genaiBytesOut=bo)
            trend.append(t)
        elif dim in DIMS:
            name, cols = DIMS[dim]
            parts = val.split(" | ", len(cols) - 1)
            parts += ["(not recorded)"] * (len(cols) - len(parts))
            row = dict(zip(cols, parts), outcome=r.get("outcome"), events=ev, bytesOut=bo, bytesIn=bi)
            tables.setdefault(name, []).append(row)
    if trend:
        tables["traffic_trend"] = trend
    return len(rows)


def load(paths):
    """{day: {'entry', 'tables': {name: [rows]}}} for completed days, plus {day: state} for the others."""
    done, other, files = {}, {}, []
    for p in paths:
        files.extend(sorted(glob.glob(p)) or [p])
    for p in files:
        try:
            d = json.load(open(p))
        except (OSError, ValueError) as e:
            sys.exit("cannot read %s (%s). Save the download_report_archive result as JSON first." % (p, e))
        for day in d.get("days", []):
            en = day.get("entry") or {}
            key = (en.get("rangeFrom") or "")[:10]
            res = day.get("result")
            if not key:
                continue
            if en.get("state") != "completed" or not res:
                other.setdefault(key, en.get("state") or "no result")
                continue
            tables = {}
            for o in res.get("objects", []):
                t = o.get("table") or {}
                tables[o.get("name")] = t.get("rows") or []
            ndims = expand_dims(tables)
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = {"entry": en, "tables": tables, "truncated": ndims >= ROWS_CAP}
    return done, other


def merge_trend(done):
    """{day: Counter of METRICS} and {device: Counter of METRICS} (a day's rows are summed over devices)."""
    daily, devices = {}, collections.defaultdict(collections.Counter)
    for day, d in done.items():
        tot = collections.Counter()
        for r in d["tables"].get("traffic_trend", []):
            dev = str(r.get("device") or "(not recorded)")
            for m in METRICS:
                v = num(r.get(m))
                tot[m] += v
                devices[dev][m] += v
        daily[day] = tot
    return daily, devices


def merge_table(done, name):
    keys, sums = TABLES[name]
    out = {}
    for d in done.values():
        for r in d["tables"].get(name, []):
            k = tuple(str(r.get(c) if r.get(c) not in (None, "") else "(not recorded)") for c in keys)
            o = out.setdefault(k, {"sum": collections.Counter()})
            for c in sums:
                o["sum"][c] += num(r.get(c))
    return out


def source_status(done):
    st, detail = collections.defaultdict(collections.Counter), {}
    for d in done.values():
        for r in d["tables"].get("sources", []):
            st[r.get("source")][r.get("status")] += 1
            if r.get("status") != "ok" and r.get("detail"):
                detail[r.get("source")] = r.get("detail")
    return st, detail


def bars(series, days, color, title, as_bytes=False):
    """One column per calendar day. A day without data is a hatched gap, never a zero bar."""
    days = [str(d) for d in days]
    vals = [(series[d] / 1e9 if as_bytes else series[d]) if d in series else None for d in days]
    return fb.column_chart([d[5:] for d in days], [(title, vals)], colors=[fb.legacy_color(color)], height=140,
                           show_values=False, y_label=title + (" (GB)" if as_bytes else ""))


def ranked(title, sub, merged, headers, cells, sortcol, color, top, total=None):
    """Top-N table. cells(key, row) -> list of (text, css) for the columns after the key."""
    items = sorted(merged.items(), key=lambda kv: -kv[1]["sum"][sortcol])
    items = [kv for kv in items if kv[1]["sum"][sortcol]]
    if not items:
        return "<div class='card' style='--c:%s;margin-top:14px'><b>%s</b><span class='mut'>None in this period.</span></div>" % (color, E(title))
    shown = items[:top]
    mx = shown[0][1]["sum"][sortcol]
    hdr = "".join("<th%s>%s</th>" % (" class='r'" if i else "", E(h)) for i, h in enumerate(headers)) + "<th></th>"
    rows = []
    for k, r in shown:
        cs = "".join("<td class='%s'>%s</td>" % (c, E(t)) for t, c in cells(k, r))
        rows.append("<tr><td class='mono'>%s</td>%s<td class='bar'><i style='--c:%s;width:%.0f%%'></i></td></tr>"
                    % (E(" / ".join(k)), cs, color, 100.0 * r["sum"][sortcol] / mx))
    rest = sum(r["sum"][sortcol] for _, r in items[top:])
    if rest:
        rows.append("<tr><td class='mut'>(%d more)</td><td class='r'>%s</td>%s<td></td></tr>"
                    % (len(items) - top, human(rest) if sortcol.startswith("bytes") else n(rest), "<td></td>" * (len(headers) - 2)))
    return ("<div style='break-inside:avoid'><h3 style='margin:18px 0 2px;font-size:14px;color:%s'>%s</h3><p class='sub'>%s</p>"
            "<div class='tw'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></div>" % (NAVY, E(title), E(sub), hdr, "".join(rows)))


def by_first_key(merged, idx=0):
    """Re-key a merged table on one key column (summing the others away): used for category and outcome roll-ups."""
    out = {}
    for k, r in merged.items():
        o = out.setdefault((k[idx],), {"sum": collections.Counter()})
        o["sum"].update(r["sum"])
    return out


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interactive", help="also write the self-contained interactive HTML (tabs, search, sort, filters, CSV export)")
    ap.add_argument("--csv")
    ap.add_argument("--summary-json")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-actors", action="store_true", help="omit tables that name internal hosts and IP addresses")
    a = ap.parse_args()

    done, other = load(a.archive)
    if not done:
        sys.exit("no completed archived day in the input. Backfill or wait for the schedule; nothing is estimated.")
    first, last = min(done), max(done)
    dfrom, dto = a.dfrom or first, a.dto or last
    expected = days_between(dfrom, dto)
    done = {k: v for k, v in done.items() if dfrom <= k <= dto}
    if not done:
        sys.exit("no archived day falls inside %s to %s." % (dfrom, dto))
    daily, devices = merge_trend(done)
    merged = {t: merge_table(done, t) for t in TABLES}
    stat, stat_detail = source_status(done)
    missing = [d for d in expected if d not in done]
    hashes = collections.Counter(v["entry"].get("env", {}).get("scriptHash", "?") for v in done.values())
    T = collections.Counter()
    for c in daily.values():
        T.update(c)
    nodata = bool(stat) and all(c.get("ok", 0) == 0 for c in stat.values())
    period = "%s to %s" % (dfrom, dto)
    top = a.top
    actors = not a.no_actors

    app_events = sum(r["sum"]["events"] for r in merged["traffic_app"].values())
    noapp_events = sum(r["sum"]["events"] for k, r in merged["traffic_app"].items() if k[0] == "(not recorded)")
    app_cov = None if not app_events else 100.0 * (app_events - noapp_events) / app_events
    ga_apps = collections.defaultdict(collections.Counter)
    for k, r in merged["genai_app"].items():
        ga_apps[k[0]].update(r["sum"])
        ga_apps[k[0]]["blocked_events" if k[2] == "blocked" else "allowed_events"] += r["sum"]["events"]
    ga_blocked = sum(c["blocked_events"] for c in ga_apps.values())
    ga_events = sum(c["events"] for c in ga_apps.values())
    ga_out = sum(c["bytesOut"] for c in ga_apps.values())
    ga_in = sum(c["bytesIn"] for c in ga_apps.values())

    summary = {"truncated_days": sorted(k for k, v in done.items() if v.get("truncated")), "period": period, "days_expected": len(expected), "days_archived": len(done), "missing_days": missing,
               "non_completed": other, "script_hashes": dict(hashes), "no_fortigate_data": nodata, "actors_included": actors,
               "totals": {m: T[m] for m in METRICS}, "application_name_coverage_pct": app_cov,
               "daily": {d: {m: daily[d][m] for m in METRICS} for d in sorted(daily)},
               "devices": {k: dict(v) for k, v in devices.items()},
               "genai": {"events": ga_events, "blocked_events": ga_blocked, "bytesOut": ga_out, "bytesIn": ga_in,
                         "apps": {k: dict(v) for k, v in ga_apps.items()}},
               "sources": {s: dict(c) for s, c in stat.items()}}
    for t in TABLES:
        if t in ACTOR_TABLES and not actors:
            continue
        keys, sums = TABLES[t]
        summary[t] = [dict(zip(keys, k), **{c: r["sum"][c] for c in sums})
                      for k, r in sorted(merged[t].items(), key=lambda kv: -kv[1]["sum"]["events"])[:200]]
    if a.summary_json:
        json.dump(summary, open(a.summary_json, "w"), indent=1)

    cov_col = GRN if not missing else (AMB if len(missing) < len(expected) / 2 else RED)
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>FortiGate Traffic Activity Report</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Network traffic activity</div><h1>FortiGate Traffic Activity Report</h1>"
             "<p>Firewall traffic volume, blocks, applications, destinations, policies and internal hosts, with a generative-AI summary, built from the archived daily runs.</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d of %d days archived</span><span class='chip'>Counts, not a determination</span>%s</div></div></div><div class='wrap'>"
             % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(done), len(expected),
                "" if actors else "<span class='chip'>Host and address tables omitted</span>"))

    def kpi(label, val, color, small="", fmt=n):
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span>%s</div>" % (color, fmt(val), E(label), "<small>%s</small>" % E(small) if small else "")
    o.append("<div class='kpis'>%s%s%s%s</div>" % (
        kpi("Log events", T["events"], NAVY, "%s of them blocked" % pct(T["blocked"], T["events"])),
        kpi("Blocked events", T["blocked"], AMB if T["blocked"] else GRN, "firewall action deny"),
        kpi("Sent (out)", T["bytesOut"], BLU, "client to server", human),
        kpi("Received (in)", T["bytesIn"], BLU, "server to client", human)))
    o.append("<div class='kpis row2'>%s%s%s%s</div>" % (
        kpi("GenAI events", ga_events, RED if ga_events else GRN, "%d application(s)" % len(ga_apps)),
        kpi("GenAI sent", ga_out, RED if ga_out else GRN, "%s of %s total out" % (pct(ga_out, T["bytesOut"]), human(T["bytesOut"])), human),
        kpi("Application names", app_cov if app_cov is not None else 0, GRN if (app_cov or 0) >= 70 else AMB,
            "of events carry an application", lambda v: "%.0f%%" % v),
        kpi("Days archived", len(done), cov_col, "of %d expected" % len(expected))))

    o.append("<div class='read'><b>Read this first.</b> Every figure comes from the daily archive of the Fortigate_Traffic_Activity_Report scheduled report; "
             "nothing was searched live. Volumes are the per-record deltas of the session byte counters, so long sessions are not double counted. "
             "Events are log records, not sessions. Zero means no matching event on an archived day; a day that is not archived is a gap, and a scan the tenant could not run is not available.</div>")
    if nodata:
        o.append("<div class='gap'><b>No FortiGate traffic data.</b> Every scan on every archived day reports the NetworkFortigateTraffic table as not available. This tenant does not collect FortiGate traffic logs (or the table has a different name); the counts above are not zeros of activity.</div>")
    if app_cov is not None and app_cov < 70:
        o.append("<div class='gap'><b>Application names are missing on %.0f%% of events.</b> The GenAI figures count only traffic the firewall identified; GenAI use through policies without Application Control is not visible, so they are a lower bound.</div>" % (100 - app_cov))
    hl = []
    if T["events"]:
        hl.append("%s log events, %s sent and %s received; %s were blocked." % (n(T["events"]), human(T["bytesOut"]), human(T["bytesIn"]), pct(T["blocked"], T["events"])))
    if ga_events:
        lead = sorted(ga_apps.items(), key=lambda kv: -kv[1]["bytesOut"])[:3]
        hl.append("GenAI traffic: %s events to %d application(s), %s sent (%s blocked events). Most data sent to %s."
                  % (n(ga_events), len(ga_apps), human(ga_out), n(ga_blocked), ", ".join("%s (%s)" % (k, human(v["bytesOut"])) for k, v in lead)))
    else:
        hl.append("No GenAI traffic was identified on the archived days (see the application-name coverage above before reading that as none).")
    ctry = [(k[0], r["sum"]["bytesOut"]) for k, r in merged["traffic_country"].items() if k[0] not in ("Reserved", "(not recorded)") and k[1] == "allowed"]
    ctry_tot = collections.Counter()
    for c, b in ctry:
        ctry_tot[c] += b
    if ctry_tot:
        c, b = ctry_tot.most_common(1)[0]
        hl.append("Most data sent to a public destination country went to %s (%s)." % (c, human(b)))
    if actors and merged["traffic_talkers"]:
        k, r = max(merged["traffic_talkers"].items(), key=lambda kv: kv[1]["sum"]["bytesOut"])
        hl.append("Largest sender: %s (%s sent)." % (" / ".join(x for x in k if x != "(not recorded)") or "(not recorded)", human(r["sum"]["bytesOut"])))
    o.append("<div class='panel' style='margin-top:14px'><b>Worth a look</b><ul style='margin:6px 0 0;padding-left:20px'>%s</ul></div>" % "".join("<li>%s</li>" % E(h) for h in hl))

    # 1 coverage
    o.append("<h2><span class='n'>1</span>Archive coverage</h2><p class='sub'>What this report is built from, and which scans the tenant could run.</p>")
    srows = []
    for s in sorted(stat):
        c = stat[s]
        okd, nad = c.get("ok", 0), c.get("not available", 0)
        label = "available" if okd and not nad else ("not available" if nad and not okd else "partial")
        col = GRN if label == "available" else (RED if label == "not available" else AMB)
        srows.append("<tr><td>%s</td><td><span class='pill' style='--c:%s'>%s</span></td><td class='r'>%d ok / %d n.a.</td><td class='mono'>%s</td></tr>"
                     % (E(s), col, label, okd, nad, E((stat_detail.get(s) or "")[:90])))
    o.append("<div class='tw'><table><tbody><tr><td>Days archived</td><td colspan='3' class='r'><span class='pill' style='--c:%s'>%d of %d</span></td></tr>"
             "<tr><td>Script version(s)</td><td colspan='3' class='r mono'>%s</td></tr></tbody></table></div>"
             % (cov_col, len(done), len(expected), E(", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common()))))
    if srows:
        o.append("<div class='tw'><table><thead><tr><th>Scan</th><th>Status</th><th class='r'>Days</th><th>Error</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(srows))
    if missing:
        o.append("<div class='gap'><b>Gap.</b> %d day(s) are not in the archive and are not counted as zero: %s. Run a backfill for them, then rebuild.%s</div>"
                 % (len(missing), E(", ".join(missing[:31]) + (" ..." if len(missing) > 31 else "")),
                    " Non-completed runs: " + E(", ".join("%s=%s" % kv for kv in sorted(other.items()))) + "." if other else ""))
    if len(hashes) > 1:
        o.append("<div class='gap'><b>Script changed during the period.</b> More than one script version produced these days; confirm the counts are defined the same way before comparing days.</div>")

    trunc = sorted(k for k, v in done.items() if v.get("truncated"))
    trunc_days = trunc
    if trunc:
        o.append("<div class='gap'><b>Result truncated.</b> On %d day(s) the dimensions scan returned the maximum %d rows (%s), so its smallest rows were dropped and the lower-ranked applications, services, countries or hosts are missing. Totals are still complete only if the device rows were kept; treat the tables as lower bounds.</div>" % (len(trunc), ROWS_CAP, E(", ".join(trunc[:10]))))

    # 2 trend
    o.append("<h2><span class='n'>2</span>Daily trend</h2><p class='sub'>One bar per UTC day. Hatched amber columns are days missing from the archive.</p><div class='cards'>")
    for m, c, b in (("events", NAVY, False), ("blocked", AMB, False), ("bytesOut", BLU, True), ("genaiBytesOut", RED, True)):
        o.append("<div class='card' style='--c:%s'><b>%s per day</b>%s</div>" % (c, LABEL[m], bars({d: daily[d][m] for d in daily}, expected, c, LABEL[m], b)))
    o.append("</div>")
    hdr = "".join("<th class='r'>%s</th>" % h for h in ("Events", "Blocked", "Sent", "Received", "GenAI ev.", "GenAI sent"))
    body = []
    for d in expected:
        if d in daily:
            c = daily[d]
            body.append("<tr><td class='mono d'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r'>%s</td></tr>"
                        % (d[5:], n(c["events"]), n(c["blocked"]), human(c["bytesOut"]), human(c["bytesIn"]), n(c["genaiEvents"]), human(c["genaiBytesOut"])))
        else:
            body.append("<tr><td class='mono d'>%s</td><td colspan='6' class='mut'>not archived (gap)</td></tr>" % d[5:])
    body.append("<tr><td><b>Total</b></td><td class='r'><b>%s</b></td><td class='r'><b>%s</b></td><td class='r'><b>%s</b></td><td class='r'><b>%s</b></td><td class='r'><b>%s</b></td><td class='r'><b>%s</b></td></tr>"
                % (n(T["events"]), n(T["blocked"]), human(T["bytesOut"]), human(T["bytesIn"]), n(T["genaiEvents"]), human(T["genaiBytesOut"])))
    o.append("<div class='tw' style='margin-top:14px'><table class='dt'><thead><tr><th>Day</th>%s</tr></thead><tbody>%s</tbody></table></div>" % (hdr, "".join(body)))

    # 3 applications
    o.append("<h2><span class='n'>3</span>Applications and categories</h2><p class='sub'>What the firewall identified, by total bytes. (not recorded) is traffic with no application name.</p>")
    cats = by_first_key(merged["traffic_app"], 1)
    o.append(ranked("By application category", "Category assigned by Application Control.", cats, ["Category", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "events", NAVY, top))
    appsum = {}
    for k, r in merged["traffic_app"].items():
        x = appsum.setdefault((k[0], k[1]), {"sum": collections.Counter()})
        x["sum"].update(r["sum"])
        x["sum"]["bytes"] += r["sum"]["bytesOut"] + r["sum"]["bytesIn"]
        if k[2] == "blocked":
            x["sum"]["blocked"] += r["sum"]["events"]
    o.append(ranked("Top applications", "Application / category. Blocked is the events the firewall denied.", appsum,
                    ["Application / category", "Events", "Blocked", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (n(r["sum"]["blocked"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")],
                    "bytes", BLU, top))

    # 4 services
    o.append("<h2><span class='n'>4</span>Services</h2><p class='sub'>Service and outcome, by events. A service the firewall could not name shows as (unnamed tcp port) or (unnamed udp port).</p>")
    o.append(ranked("Top services", "Service / outcome.", merged["traffic_service"], ["Service / outcome", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "events", NAVY, top))

    # 5 countries
    o.append("<h2><span class='n'>5</span>Destination countries</h2><p class='sub'>Where traffic goes, by bytes sent. Reserved is private address space.</p>")
    o.append(ranked("By destination country", "Country / outcome.", merged["traffic_country"], ["Country / outcome", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "bytesOut", BLU, top))

    # 6 policies and devices
    o.append("<h2><span class='n'>6</span>Policies and devices</h2><p class='sub'>Which firewall policies carry the traffic and which firewalls report it. Policy 0 denies are the implicit deny.</p>")
    o.append(ranked("By firewall policy", "Policy id / outcome.", merged["traffic_policy"], ["Policy / outcome", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "events", NAVY, top))
    devm = {(k,): {"sum": v} for k, v in devices.items()}
    o.append(ranked("By reporting device", "Per FortiGate.", devm, ["Device", "Events", "Blocked", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (n(r["sum"]["blocked"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")],
                    "events", NAVY, top))

    # 7 internal hosts
    o.append("<h2><span class='n'>7</span>Internal hosts</h2><p class='sub'>The largest senders, by bytes sent (top 100 a day).</p>")
    if actors:
        o.append(ranked("Top internal senders", "Address / host name.", merged["traffic_talkers"], ["Address / host", "Events", "Blocked", "Sent", "Received"],
                        lambda k, r: [(n(r["sum"]["events"]), "r"), (n(r["sum"]["blocked"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")],
                        "bytesOut", BLU, top))
    else:
        o.append("<div class='panel'>Host and address tables are omitted in this build.</div>")

    # 8 GenAI
    o.append("<h2><span class='n'>8</span>Generative AI traffic</h2><p class='sub'>Traffic the firewall labelled GenAI, or whose application name matches a known GenAI service. "
             "The same evidence feeds the separate GenAI Egress report, which gives the full analysis.</p>")
    o.append(ranked("By GenAI application", "Application / category / outcome.", merged["genai_app"], ["Application / category / outcome", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "bytesOut", RED, top))
    o.append(ranked("By firewall policy", "Which policy allows or blocks each GenAI application.", merged["genai_policy"], ["Policy / application / outcome", "Events", "Sent", "Received"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "events", RED, top))
    if actors:
        o.append(ranked("Top internal sources", "Address / host / application / outcome (top 300 a day).", merged["genai_source"], ["Source / application / outcome", "Events", "Sent", "Received"],
                        lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "bytesOut", RED, top))
        o.append(ranked("Top destinations", "Destination address / country / application (no host name in the logs).", merged["genai_destination"], ["Destination / country / application", "Events", "Sent", "Received"],
                        lambda k, r: [(n(r["sum"]["events"]), "r"), (human(r["sum"]["bytesOut"]), "r"), (human(r["sum"]["bytesIn"]), "r")], "bytesOut", RED, top))

    # 9 limits
    o.append("<div class='foot'><b>Limits</b><ul>%s</ul><p>Source: archive of the scheduled report %s. No live search was run to build this report.</p></div>" % ("".join("<li>%s</li>" % E(l) for l in LIMITS), REPORT))
    o.append("</div></body></html>")
    open(a.out, "w").write(fb.apply_brand("".join(o)))


    if a.interactive:
        def roll(t, names, oi=None):
            """merged table -> flat rows keyed by names; outcome (key index oi) becomes the blocked column."""
            out = {}
            for k, r in merged[t].items():
                key = tuple(x for i, x in enumerate(k) if i != oi)
                o = out.setdefault(key, dict(zip(names, key), events=0, blocked=0, bytesOut=0, bytesIn=0))
                o["events"] += r["sum"]["events"]
                o["bytesOut"] += r["sum"]["bytesOut"]
                o["bytesIn"] += r["sum"]["bytesIn"]
                if oi is not None and k[oi] == "blocked":
                    o["blocked"] += r["sum"]["events"]
                if "blocked" in r["sum"]:
                    o["blocked"] += r["sum"]["blocked"]
            rows = sorted(out.values(), key=lambda x: -x["bytesOut"])[:5000]
            for x in rows:
                x["bytes"] = x["bytesOut"] + x["bytesIn"]
            return rows
        apps = roll("traffic_app", ["app", "category"], 2)
        for x in apps:
            x["name"] = x["app"]
        daily_rows = []
        for d in expected:
            c = daily.get(d)
            daily_rows.append(dict({"day": d, "gap": c is None}, **{m: (c[m] if c is not None else 0) for m in METRICS}))
        dev_rows = [dict(name=k, events=v["events"], blocked=v["blocked"], bytesOut=v["bytesOut"], bytesIn=v["bytesIn"]) for k, v in sorted(devices.items(), key=lambda kv: -kv[1]["events"])]
        srcs = [{"source": s, "status": ("available" if c.get("ok") and not c.get("not available") else "not available" if c.get("not available") and not c.get("ok") else "partial"),
                 "days": "%d ok / %d n.a." % (c.get("ok", 0), c.get("not available", 0)), "detail": (stat_detail.get(s) or "")[:160]} for s, c in sorted(stat.items())]
        def named(rows, field):
            for x in rows:
                x["name"] = x[field]
            return rows
        gapps = named(roll("genai_app", ["app", "category"], 2), "app")
        data = {"meta": {"tenant": a.tenant, "site": a.site, "period": period, "days": len(done), "expected": len(expected), "missing": missing,
                         "truncated": trunc_days, "hashes": ", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common()), "appCoverage": app_cov,
                         "noData": nodata, "actors": actors},
                "totals": {m: T[m] for m in METRICS}, "genai": {"events": ga_events, "blocked": ga_blocked, "bytesOut": ga_out, "bytesIn": ga_in, "apps": len(ga_apps)},
                "daily": daily_rows, "apps": apps,
                "services": named(roll("traffic_service", ["service"], 1), "service"),
                "countries": named(roll("traffic_country", ["country"], 1), "country"),
                "policies": named(roll("traffic_policy", ["policy"], 1), "policy"),
                "devices": dev_rows, "genaiApps": gapps,
                "genaiPolicies": roll("genai_policy", ["policy", "app"], 2),
                "talkers": roll("traffic_talkers", ["source", "host"]) if actors else [],
                "genaiSources": roll("genai_source", ["source", "host", "app"], 3) if actors else [],
                "genaiDests": roll("genai_destination", ["destination", "country", "app"]) if actors else [],
                "sources": srcs, "limits": LIMITS}
        tpl = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "assets", "interactive_template.html"), encoding="utf-8").read()
        tpl = tpl.replace("{{title}}", E((a.tenant or "Tenant") + " FortiGate Traffic Activity Report")).replace("{{data}}", json.dumps(data, default=str).replace("</", "<\\/"))
        open(a.interactive, "w", encoding="utf-8").write(tpl)

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["section", "key", "metric", "value"])
            for d in expected:
                if d in daily:
                    for m in METRICS:
                        w.writerow(["daily", d, m, daily[d][m]])
                else:
                    w.writerow(["daily", d, "gap", ""])
            for m in METRICS:
                w.writerow(["total", dfrom + ".." + dto, m, T[m]])
            for dev, c in sorted(devices.items()):
                for m in METRICS:
                    w.writerow(["device", dev, m, c[m]])
            for t, (keys, sums) in TABLES.items():
                if t in ACTOR_TABLES and not actors:
                    continue
                for k, r in sorted(merged[t].items(), key=lambda kv: -kv[1]["sum"]["events"]):
                    for c in sums:
                        w.writerow([t, " / ".join(k), c, r["sum"][c]])
    print("period %s: %d of %d days archived, %s events, %s out, %s GenAI events, %d gap day(s)%s"
          % (period, len(done), len(expected), n(T["events"]), human(T["bytesOut"]), n(ga_events), len(missing), ", NO FORTIGATE TRAFFIC DATA" if nodata else ""))


if __name__ == "__main__":
    main()
