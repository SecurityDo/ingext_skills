#!/usr/bin/env python3
"""Build the FortiGate Security Activity report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv report.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site Conekt] [--top 10] [--no-actors]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}); several files and
several days per file are merged. This script never queries a tenant. Rules: the per-day trend rows are summed; the
per-entity tables (device, country, source, user, anomaly, admin, blocked) are summed by key, with the distinct counts
(sources, usernames, countries, devices, hosts) reported as the PEAK single day, never added; a missing value is 0; a
day that is not archived is a GAP, never zero. --no-actors drops every table that names a user or an IP address.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
METRICS = ["failedLogins", "sessionExpiries", "sslSessions", "ipsecTunnelsUp", "ipsecTunnelsDown", "appCtrlBlocks",
           "webFilterBlocks", "ipsAnomalies", "adminLogins", "adminLoginsFailed", "adminConfigChanges"]
LABEL = {"failedLogins": "Failed SSL-VPN logins", "sessionExpiries": "Portal session expiries", "sslSessions": "SSL-VPN sessions",
         "ipsecTunnelsUp": "IPsec tunnels up", "ipsecTunnelsDown": "IPsec tunnels down", "appCtrlBlocks": "App-control blocks",
         "webFilterBlocks": "Web-filter blocks", "ipsAnomalies": "IPS / DoS anomalies", "adminLogins": "Admin logins",
         "adminLoginsFailed": "Failed admin logins", "adminConfigChanges": "Admin config changes"}
SHORT = {"failedLogins": "Failed VPN", "sessionExpiries": "Expiries", "sslSessions": "SSL sess.", "ipsecTunnelsUp": "IPsec up",
         "ipsecTunnelsDown": "IPsec down", "appCtrlBlocks": "App ctrl", "webFilterBlocks": "Web filter", "ipsAnomalies": "Anomalies",
         "adminLogins": "Adm. login", "adminLoginsFailed": "Adm. fail", "adminConfigChanges": "Adm. chg"}
# table name -> (key columns, summed columns, peak columns, earliest column, latest column)
TABLES = {
    "fg_failed_device": (["device"], ["failures"], ["sources", "countries", "usernames"], "firstSeen", "lastSeen"),
    "fg_failed_country": (["country"], ["failures"], ["sources", "usernames"], None, None),
    "fg_failed_source": (["remip"], ["failures"], ["usernames"], "firstSeen", "lastSeen"),
    "fg_failed_user": (["user"], ["failures"], ["sources", "countries", "devices"], "firstSeen", "lastSeen"),
    "fg_vpn_user": (["user"], ["sessions"], ["sources", "countries", "devices"], "firstSeen", "lastSeen"),
    "fg_anomaly": (["attack", "severity"], ["events"], ["sources"], "firstSeen", "lastSeen"),
    "fg_admin": (["admin"], ["loginsOk", "loginsFailed", "changes"], [], None, "lastSeen"),
    "fg_blocked": (["control", "item"], ["blocks"], ["hosts"], None, None),
}
ACTOR_TABLES = ("fg_failed_source", "fg_failed_user", "fg_vpn_user", "fg_admin")
SEC_FAMILY = [  # indicative, related not equivalent
    ("Remote access and failed sign-ins", "AC-7, AC-17, IA-2", "failed SSL-VPN logins, sessions, IPsec tunnels, sources and countries"),
    ("Boundary protection and filtering", "SC-7, SI-4", "application-control and web-filter blocks, IPS and DoS anomalies"),
    ("Administrator accounts and changes", "AC-2, AC-6, CM-3, CM-5", "admin logins, failed admin logins, configuration changes"),
    ("Audit events recorded", "AU-2, AU-12", "events scanned per day, archive coverage"),
]
LIMITS = [
    "The tables name users and source IP addresses (top 100 a day each), so the report is personal data. Share it only with the customer who owns the data, or build it with --no-actors.",
    "Per-entity tables keep the top 100 rows of each archived day, so a range total for an entity outside a day's top 100 is a lower bound. Distinct counts are the peak single day, never added across days.",
    "Only FortiGate event and UTM logs are scanned (VPN, system, application-control, web-filter, anomaly). Traffic logs, bandwidth and policy hits are not in this report.",
    "Failed SSL-VPN logins exclude the portal session expiry (reason 'wrong vdom (0:0) or time expired'), counted separately. FortiOS leaves the user name empty on most failures, shown as (not recorded).",
    "An archived day is a snapshot taken a few hours after the day ended; events that arrive later are not added.",
    "A day missing from the archive is a gap, not zero activity. A source the tenant lacks is 'not available', not zero.",
    "These counts are related to NIST 800-53 controls, not equivalent to them. This report is not a compliance determination, certification or attestation.",
]

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
.kpis.two{margin-top:14px;grid-template-columns:repeat(4,1fr)}
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
@media screen and (max-width:760px){.kpis,.kpis.two,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def n(v):
    return "{:,}".format(int(v))


def pct(a, b):
    return "%.2f%%" % (100.0 * a / b) if b else "n/a"


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


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
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = {"entry": en, "tables": tables}
    return done, other


def merge_trend(done):
    daily = {}
    for day, d in done.items():
        tot = collections.Counter()
        for r in d["tables"].get("fg_trend", []):
            for m in METRICS:
                tot[m] += num(r.get(m))
        daily[day] = tot
    return daily


def merge_table(done, name):
    keys, sums, peaks, first, last = TABLES[name]
    out = {}
    for d in done.values():
        for r in d["tables"].get(name, []):
            k = tuple(str(r.get(c) if r.get(c) not in (None, "") else "(not recorded)") for c in keys)
            o = out.setdefault(k, {"sum": collections.Counter(), "peak": collections.Counter(), "first": None, "last": None, "days": 0})
            o["days"] += 1
            for c in sums:
                o["sum"][c] += num(r.get(c))
            for c in peaks:
                o["peak"][c] = max(o["peak"][c], num(r.get(c)))
            if first and r.get(first) and (o["first"] is None or r[first] < o["first"]):
                o["first"] = r[first]
            if last and r.get(last) and (o["last"] is None or r[last] > o["last"]):
                o["last"] = r[last]
    return out


def source_status(done):
    """{source: Counter(ok/not available)} and the error text of the latest not-available row."""
    st, detail = collections.defaultdict(collections.Counter), {}
    for d in done.values():
        for r in d["tables"].get("sources", []):
            st[r.get("source")][r.get("status")] += 1
            if r.get("status") != "ok" and r.get("detail"):
                detail[r.get("source")] = r.get("detail")
    return st, detail


def bars(series, days, color, title):
    W, H, L, B = 480, 120, 6, 18
    mx = max([v for v in series.values()] + [1])
    bw = (W - 2 * L) / max(len(days), 1)
    o = ["<svg viewBox='0 0 %d %d' role='img' aria-label='%s'>" % (W, H, E(title))]
    o.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#e2e8f0'/>" % (L, H - B, W - L, H - B))
    for i, d in enumerate(days):
        x = L + i * bw
        if d not in series:
            o.append("<rect x='%.1f' y='6' width='%.1f' height='%d' fill='#fef3c7' stroke='#f59e0b' stroke-dasharray='2 2'/>" % (x + 0.5, max(bw - 1, 1), H - B - 6))
            continue
        h = (H - B - 8) * series[d] / mx
        o.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'><title>%s: %s</title></rect>" % (x + 0.5, H - B - h, max(bw - 1, 1), h, color, d, n(series[d])))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b'>%s</text>" % (L, H - 4, days[0] if days else ""))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b' text-anchor='end'>%s</text>" % (W - L, H - 4, days[-1] if days else ""))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b' text-anchor='end'>max %s</text>" % (W - L, 10, n(mx)))
    o.append("</svg>")
    return "".join(o)


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
        rows.append("<tr><td class='mut'>(%d more)</td><td class='r'>%s</td>%s<td></td></tr>" % (len(items) - top, n(rest), "<td></td>" * (len(headers) - 2)))
    return ("<div style='break-inside:avoid'><h3 style='margin:18px 0 2px;font-size:14px;color:%s'>%s</h3><p class='sub'>%s</p>"
            "<div class='tw'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></div>" % (NAVY, E(title), E(sub), hdr, "".join(rows)))


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def short(ts):
    return (ts or "")[:16].replace("T", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--summary-json")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-actors", action="store_true", help="omit tables that name users and IP addresses")
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
    daily = merge_trend(done)
    merged = {t: merge_table(done, t) for t in TABLES}
    stat, stat_detail = source_status(done)
    missing = [d for d in expected if d not in done]
    hashes = collections.Counter(v["entry"].get("env", {}).get("scriptHash", "?") for v in done.values())
    T = collections.Counter()
    for c in daily.values():
        T.update(c)
    blocked = T["appCtrlBlocks"] + T["webFilterBlocks"]
    nodata = bool(stat) and all(c.get("ok", 0) == 0 for c in stat.values())
    period = "%s to %s" % (dfrom, dto)
    top = a.top
    actors = not a.no_actors

    summary = {"period": period, "days_expected": len(expected), "days_archived": len(done), "missing_days": missing,
               "non_completed": other, "script_hashes": dict(hashes), "no_fortigate_data": nodata,
               "totals": {m: T[m] for m in METRICS}, "blocked_total": blocked,
               "daily": {d: {m: daily[d][m] for m in METRICS} for d in sorted(daily)},
               "sources": {s: dict(c) for s, c in stat.items()}, "actors_included": actors}
    for t in TABLES:
        if t in ACTOR_TABLES and not actors:
            continue
        keys, sums, peaks, _, _ = TABLES[t]
        summary[t] = [dict(zip(keys, k), **{c: r["sum"][c] for c in sums}, **{"peak_" + c: r["peak"][c] for c in peaks})
                      for k, r in sorted(merged[t].items(), key=lambda kv: -kv[1]["sum"][sums[0]])[:100]]
    if a.summary_json:
        json.dump(summary, open(a.summary_json, "w"), indent=1)

    cov_col = GRN if not missing else (AMB if len(missing) < len(expected) / 2 else RED)
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>FortiGate Security Activity Report</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Network security activity</div><h1>FortiGate Security Activity Report</h1>"
             "<p>SSL-VPN failed logins and access, IPsec tunnels, application-control and web-filter blocks, IPS anomalies and administrator activity, built from the archived daily runs.</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d of %d days archived</span><span class='chip'>Counts, not a determination</span>%s</div></div></div><div class='wrap'>"
             % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(done), len(expected),
                "" if actors else "<span class='chip'>User and IP tables omitted</span>"))

    def kpi(label, val, color, small=""):
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span>%s</div>" % (color, n(val), E(label), "<small>%s</small>" % E(small) if small else "")
    o.append("<div class='kpis'>%s%s%s%s</div>" % (
        kpi("Failed SSL-VPN logins", T["failedLogins"], RED if T["failedLogins"] else GRN, "%s portal expiries not counted" % n(T["sessionExpiries"])),
        kpi("SSL-VPN sessions", T["sslSessions"], NAVY, "%s IPsec up, %s down" % (n(T["ipsecTunnelsUp"]), n(T["ipsecTunnelsDown"]))),
        kpi("Blocks", blocked, AMB, "%s app control, %s web filter" % (n(T["appCtrlBlocks"]), n(T["webFilterBlocks"]))),
        kpi("IPS / DoS anomalies", T["ipsAnomalies"], RED if T["ipsAnomalies"] else GRN)))
    o.append("<div class='kpis two'>%s%s%s%s</div>" % (
        kpi("Admin logins", T["adminLogins"], NAVY), kpi("Failed admin logins", T["adminLoginsFailed"], RED if T["adminLoginsFailed"] else GRN),
        kpi("Admin config changes", T["adminConfigChanges"], BLU), kpi("Days archived", len(done), cov_col, "of %d expected" % len(expected))))

    o.append("<div class='read'><b>Read this first.</b> Every figure comes from the daily archive of the Fortigate_Security_Activity_Report scheduled report; "
             "nothing was searched live. The numbers are counts of FortiGate event and UTM log records, related to NIST 800-53 access, boundary and change controls. "
             "They are not a compliance determination. Zero means no matching event on an archived day; a day that is not archived is a gap, and a source the tenant lacks is not available.</div>")
    if nodata:
        o.append("<div class='gap'><b>No FortiGate data.</b> Every scan on every archived day reports the NetworkFortigateEvent table as not available. This tenant does not collect FortiGate events (or the table has a different name); the counts above are not zeros of activity.</div>")
    hl = []
    if T["failedLogins"]:
        top_src = sorted(merged["fg_failed_source"].items(), key=lambda kv: -kv[1]["sum"]["failures"])[:1]
        hl.append("%s failed SSL-VPN login(s) from up to %s source address(es) on the busiest day." % (n(T["failedLogins"]), n(max([r["peak"]["sources"] for r in merged["fg_failed_device"].values()] + [0]))))
        spray = [k for k, r in merged["fg_failed_source"].items() if r["peak"]["usernames"] >= 10]
        if spray and actors:
            hl.append("%d source address(es) tried 10 or more user names in one day (credential spray pattern)." % len(spray))
    if T["adminLoginsFailed"]:
        hl.append("%s failed administrator login(s)." % n(T["adminLoginsFailed"]))
    if T["adminConfigChanges"]:
        hl.append("%s administrator configuration change(s)." % n(T["adminConfigChanges"]))
    if T["ipsAnomalies"]:
        hl.append("%s IPS / DoS anomaly event(s)." % n(T["ipsAnomalies"]))
    if not hl:
        hl.append("No failed SSL-VPN logins, failed admin logins, configuration changes or IPS / DoS anomalies on the archived days.")
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

    # 2 trend
    o.append("<h2><span class='n'>2</span>Daily trend</h2><p class='sub'>One bar per UTC day. Hatched amber columns are days missing from the archive.</p><div class='cards'>")
    for m, c in (("failedLogins", RED), ("sslSessions", NAVY), ("webFilterBlocks", AMB), ("adminConfigChanges", BLU)):
        o.append("<div class='card' style='--c:%s'><b>%s per day</b>%s</div>" % (c, LABEL[m], bars({d: daily[d][m] for d in daily}, expected, c, LABEL[m])))
    o.append("</div>")
    hdr = "".join("<th class='r'>%s</th>" % SHORT[m] for m in METRICS)
    body = []
    for d in expected:
        if d in daily:
            body.append("<tr><td class='mono d'>%s</td>%s</tr>" % (d[5:], "".join("<td class='r'>%s</td>" % n(daily[d][m]) for m in METRICS)))
        else:
            body.append("<tr><td class='mono d'>%s</td><td colspan='%d' class='mut'>not archived (gap)</td></tr>" % (d[5:], len(METRICS)))
    body.append("<tr><td><b>Total</b></td>%s</tr>" % "".join("<td class='r'><b>%s</b></td>" % n(T[m]) for m in METRICS))
    o.append("<div class='tw' style='margin-top:14px'><table class='dt'><thead><tr><th>Day</th>%s</tr></thead><tbody>%s</tbody></table></div>" % (hdr, "".join(body)))

    # 3 failed logins
    o.append("<h2><span class='n'>3</span>Failed SSL-VPN logins</h2><p class='sub'>Credential failures, portal session expiries excluded. Distinct counts are the busiest single day, never added across days.</p>")
    o.append(ranked("By firewall device", "Failures per FortiGate.", merged["fg_failed_device"],
                    ["Device", "Failures", "Sources (peak day)", "User names (peak day)", "Countries (peak day)"],
                    lambda k, r: [(n(r["sum"]["failures"]), "r"), (n(r["peak"]["sources"]), "r"), (n(r["peak"]["usernames"]), "r"), (n(r["peak"]["countries"]), "r")],
                    "failures", RED, top))
    o.append(ranked("By source country", "Where the failed logins come from.", merged["fg_failed_country"],
                    ["Country", "Failures", "Sources (peak day)", "User names (peak day)"],
                    lambda k, r: [(n(r["sum"]["failures"]), "r"), (n(r["peak"]["sources"]), "r"), (n(r["peak"]["usernames"]), "r")],
                    "failures", RED, top))
    if actors:
        def pat(k, r):
            u, f = r["peak"]["usernames"], r["sum"]["failures"]
            return "Credential spray" if u >= 10 else ("Brute force" if f >= 50 else "Probe")
        o.append(ranked("Top source addresses", "Many user names from one address is a spray, many failures with few names is brute force, the rest is probing. Lower bound: top 100 a day.", merged["fg_failed_source"],
                        ["Source address", "Failures", "User names (peak day)", "Pattern", "First seen", "Last seen"],
                        lambda k, r: [(n(r["sum"]["failures"]), "r"), (n(r["peak"]["usernames"]), "r"), (pat(k, r), ""), (short(r["first"]), "d"), (short(r["last"]), "d")],
                        "failures", RED, top))
        o.append(ranked("Top user names", "(not recorded) is a failure where FortiOS left the user name empty.", merged["fg_failed_user"],
                        ["User name", "Failures", "Sources (peak day)", "Countries (peak day)", "Devices (peak day)"],
                        lambda k, r: [(n(r["sum"]["failures"]), "r"), (n(r["peak"]["sources"]), "r"), (n(r["peak"]["countries"]), "r"), (n(r["peak"]["devices"]), "r")],
                        "failures", RED, top))

    # 4 access
    o.append("<h2><span class='n'>4</span>Remote access and tunnels</h2><p class='sub'>Established SSL-VPN tunnels and IPsec tunnel state changes.</p>")
    if actors:
        o.append(ranked("SSL-VPN sessions by user", "Tunnels established per user; lower bound (top 100 a day).", merged["fg_vpn_user"],
                        ["User", "Sessions", "Sources (peak day)", "Countries (peak day)", "Devices (peak day)"],
                        lambda k, r: [(n(r["sum"]["sessions"]), "r"), (n(r["peak"]["sources"]), "r"), (n(r["peak"]["countries"]), "r"), (n(r["peak"]["devices"]), "r")],
                        "sessions", NAVY, top))
    o.append("<div class='panel' style='margin-top:12px'>IPsec tunnels up <b>%s</b>, down <b>%s</b>. A large gap between the two over a period can mean flapping or a tunnel that did not return.</div>"
             % (n(T["ipsecTunnelsUp"]), n(T["ipsecTunnelsDown"])))

    # 5 threats
    o.append("<h2><span class='n'>5</span>Blocks and anomalies</h2><p class='sub'>Application-control and web-filter blocks, and IPS / DoS anomaly events.</p>")
    o.append(ranked("Blocked applications and web categories", "Blocks per application (app control) or category (web filter); hosts are the busiest day's distinct internal hosts.", merged["fg_blocked"],
                    ["Control / item", "Blocks", "Hosts (peak day)"],
                    lambda k, r: [(n(r["sum"]["blocks"]), "r"), (n(r["peak"]["hosts"]), "r")], "blocks", AMB, top))
    o.append(ranked("IPS and DoS anomalies", "By attack type and severity.", merged["fg_anomaly"],
                    ["Attack / severity", "Events", "Sources (peak day)"],
                    lambda k, r: [(n(r["sum"]["events"]), "r"), (n(r["peak"]["sources"]), "r")], "events", RED, top))

    # 6 admin
    o.append("<h2><span class='n'>6</span>Administrator activity</h2><p class='sub'>Admin logins, failed logins and configuration changes (Edit, Add, Delete).</p>")
    if actors:
        o.append(ranked("By administrator account", "Lower bound: top 100 a day.", merged["fg_admin"],
                        ["Admin", "Changes", "Logins ok", "Logins failed", "Last seen"],
                        lambda k, r: [(n(r["sum"]["changes"]), "r"), (n(r["sum"]["loginsOk"]), "r"), (n(r["sum"]["loginsFailed"]), "r"), (short(r["last"]), "d")],
                        "changes", BLU, top))
    else:
        o.append("<div class='panel'>Account names are omitted in this build. Totals: %s logins, %s failed, %s configuration changes.</div>" % (n(T["adminLogins"]), n(T["adminLoginsFailed"]), n(T["adminConfigChanges"])))

    # 7 mapping + limits
    o.append("<h2><span class='n'>7</span>What these counts relate to</h2><p class='sub'>Indicative crosswalk to NIST SP 800-53 Rev. 5. Related, not equivalent.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Area</th><th>800-53 controls</th><th>Counts that relate</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td>%s</td><td class='mono'>%s</td><td>%s</td></tr>" % (E(x), E(y), E(z)) for x, y, z in SEC_FAMILY))
    o.append("<div class='foot'><b>Limits</b><ul>%s</ul><p>Source: archive of the scheduled report Fortigate_Security_Activity_Report. No live search was run to build this report.</p></div>" % "".join("<li>%s</li>" % E(l) for l in LIMITS))
    o.append("</div></body></html>")
    open(a.out, "w").write("".join(o))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["section", "key", "metric", "count"])
            for d in expected:
                if d in daily:
                    for m in METRICS:
                        w.writerow(["daily", d, m, daily[d][m]])
                else:
                    w.writerow(["daily", d, "gap", ""])
            for m in METRICS:
                w.writerow(["total", dfrom + ".." + dto, m, T[m]])
            for t, (keys, sums, peaks, _, _) in TABLES.items():
                if t in ACTOR_TABLES and not actors:
                    continue
                for k, r in sorted(merged[t].items(), key=lambda kv: -kv[1]["sum"][sums[0]]):
                    for c in sums:
                        w.writerow([t, " / ".join(k), c, r["sum"][c]])
                    for c in peaks:
                        w.writerow([t, " / ".join(k), "peak_day_" + c, r["peak"][c]])
    print("period %s: %d of %d days archived, %s failed VPN logins, %s blocks, %d gap day(s)%s"
          % (period, len(done), len(expected), n(T["failedLogins"]), n(blocked), len(missing), ", NO FORTIGATE DATA" if nodata else ""))


if __name__ == "__main__":
    main()
