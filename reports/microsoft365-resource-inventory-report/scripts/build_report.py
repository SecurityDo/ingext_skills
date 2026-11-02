#!/usr/bin/env python3
"""Build the Microsoft 365 Resource Inventory report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv users.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site Develop] [--top 50] [--no-actors]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}). This script never
queries a tenant. The resource tables are SNAPSHOTS of the directory at the time of the daily run: days are never
added together. The report shows the LATEST archived day in the period (the state nearest the end of the period) and
a small per-day table to see change. Lists name users (personal data); --no-actors drops them. A day that is not
archived is a GAP; a scan the tenant could not run is "not available", never zero.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, os, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
SCANS = [("o365res_users", "office365User", "Users and MFA"), ("o365res_devices", "office365Device", "Devices"),
         ("o365res_ca", "office365ConditionalAccessPolicy", "Conditional Access"),
         ("o365res_apps", "office365Application", "App registrations"),
         ("o365res_app_secrets", "app registration client secrets", "Client secrets"),
         ("o365res_app_perms", "app registration permissions", "App-only permissions"),
         ("o365res_enterprise", "office365InstalledApp", "Enterprise applications"),
         ("o365res_groups", "office365Group", "Groups"),
         ("o365res_noncompliant_users", "non-compliant users (no MFA registered)", "Users without MFA"),
         ("o365res_licensed_users", "licensed users", "Licensed users")]
LIMITS = [
    "The tables are snapshots of the directory taken by the daily run, not event logs. The report shows the latest archived day in the period; days are never added. A backfill cannot rebuild a past state: it records the directory as it is when the backfill runs.",
    "The user lists (users without MFA, licensed users) name people, so the report is personal data. Share it only with the customer who owns the data, or build it with --no-actors.",
    "MFA registration is not MFA enforcement. A user with no registration record is not known to lack MFA: when no user has a registration record, the MFA figures are not known and the lists are empty.",
    "An administrator is any user with the isAdmin flag or at least one directory role. A non-compliant user is an enabled user with no MFA registered; guests and members are both listed and the type column tells them apart.",
    "Device managed and compliance figures count only devices that report the field; zero reported means the tenant does not report it, not that every device is unmanaged.",
    "App permissions are what registrations request, not what an administrator consented to. Secret and permission counts never include secret values.",
    "Enterprise applications are service principals (the table is named office365InstalledApp but holds no device software).",
    "A day missing from the archive is a gap, not zero. A scan the tenant could not run is 'not available', not zero.",
    "These facts are related to NIST 800-53 controls (AC-2, AC-6, IA-2, IA-5, CM-8, CA-7), not equivalent to them. This report is not a compliance determination, certification or attestation.",
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
.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-size:12px;margin-bottom:4px}
.card svg{width:100%;height:auto;display:block}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
td.bar{width:24%}.bar i{display:block;height:8px;border-radius:4px;background:var(--c);min-width:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media screen and (max-width:760px){.g2{grid-template-columns:1fr}.kpis,.kpis.two,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
table.wide{table-layout:fixed;font-size:11px}table.wide th,table.wide td{padding:6px 8px;word-break:break-word;overflow-wrap:anywhere}
.kpi b{font-size:26px}.kpi b{word-break:break-word}
h2,h3{break-after:avoid}tr{break-inside:avoid}
.bigp{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;padding:14px 22px;margin-top:14px;break-inside:avoid}.bigp span{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);font-weight:700}.bigp b{display:block;font-size:56px;line-height:1.05;color:var(--c);letter-spacing:-.02em}.bigp small{display:block;color:var(--mut);font-size:12px}
"""

def n(v):
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return "{:,}".format(v) if isinstance(v, int) else str(v)


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def pct(a, b):
    return "%.0f%%" % (100.0 * a / b) if b else "n/a"


def truthy(v):
    return v is True or str(v).lower() == "true"


def rows_of(t):
    return (t or {}).get("rows") or []


def roles_text(s):
    try:
        v = json.loads(s) if isinstance(s, str) else s
        return ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v or ""))
    except ValueError:
        return str(s or "")


def load(paths):
    """({day: {entry, tables{name: rows}, status{source: (state, detail)}}}, {day: non-completed state})."""
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
            dd = {"entry": en, "tables": {}, "status": {}}
            for o in res.get("objects", []):
                nm = o.get("name", "")
                if nm == "sources":
                    for r in rows_of(o.get("table")):
                        s = r.get("source")
                        if r.get("status") == "ok":
                            dd["status"].setdefault(s, ("ok", ""))
                        else:
                            dd["status"][s] = ("not available", r.get("detail") or "")
                else:
                    dd["tables"][nm] = rows_of(o.get("table"))
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = dd
    return done, other


def days_between(a, b):
    x, y, out = dt.date.fromisoformat(a), dt.date.fromisoformat(b), []
    while x <= y:
        out.append(x.isoformat())
        x += dt.timedelta(days=1)
    return out


def scan_state(dd, src):
    s = dd["status"].get(src)
    return s[0] if s else "ok"


def one(dd, tbl):
    r = dd["tables"].get(tbl) or []
    return r[0] if r else None


def kpi(label, value, color, small=""):
    return "<div class='kpi' style='--c:%s'><span>%s</span><b>%s</b><small>%s</small></div>" % (color, E(label), E(str(value)), E(small))


def na(title, why):
    return "<div class='card' style='--c:%s;margin-top:14px'><b>%s</b><span class='mut'>Not available: %s</span></div>" % (AMB, E(title), E(why or "the tenant could not run this scan"))


def gtable(title, sub, headers, rows, top, widths=None):
    """rows: lists of cell values; numbers are right-aligned. cls: optional list of per-column classes."""
    if not rows:
        return "<div class='card' style='--c:%s;margin-top:14px'><b>%s</b><span class='mut'>None.</span></div>" % (GRN, E(title))
    shown = rows[:top]
    hdr = "".join("<th%s>%s</th>" % (" class='r'" if isinstance(shown[0][i], (int, float)) else "", E(h)) for i, h in enumerate(headers))
    body = []
    for r in shown:
        body.append("<tr>%s</tr>" % "".join("<td class='%s'>%s</td>" % ("r" if isinstance(v, (int, float)) else "", E(n(v) if isinstance(v, (int, float)) else str(v))) for v in r))
    if len(rows) > top:
        body.append("<tr><td class='mut' colspan='%d'>(%d more in the CSV)</td></tr>" % (len(headers), len(rows) - top))
    return ("<div><h3 style='margin:18px 0 2px;font-size:14px;color:%s'>%s</h3><p class='sub'>%s</p>"
            "<div class='tw'><table class='dt wide'>%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></div>" % (NAVY, E(title), E(sub), ("<colgroup>%s</colgroup>" % "".join("<col style='width:%d%%'>" % w for w in widths)) if widths else "", hdr, "".join(body)))


def kv(title, sub, pairs):
    rows = [[k, v] for k, v in pairs]
    return gtable(title, sub, ["Measure", "Count"], rows, 999)


def bars(series, days, color, title):
    """Bar chart of one metric per archived day; a day with no archive is a dashed gap."""
    W, H, L, B = 480, 110, 6, 18
    mx = max([v for v in series.values()] + [1])
    bw = (W - 2 * L) / max(len(days), 1)
    o = ["<svg viewBox='0 0 %d %d' role='img' aria-label='%s'>" % (W, H, E(title)),
         "<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#e2e8f0'/>" % (L, H - B, W - L, H - B)]
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


def bigp(label, value, sub, color):
    return "<div class='bigp' style='--c:%s'><span>%s</span><b>%s</b><small>%s</small></div>" % (color, E(label), E(str(value)), E(sub))


def build_interactive(path, a, done, in_period, expected, last, gaps, hashes, nc, lic, perlic, L):
    """One self-contained interactive HTML file: tabs, searchable/sortable/filterable user tables, hover trend charts."""
    one_ = lambda dd, t: (one(dd, t) or None)
    days = {}
    for d in in_period:
        t = done[d]
        days[d] = {"users": one_(t, "o365res_users"), "devices": one_(t, "o365res_devices"), "apps": one_(t, "o365res_apps"),
                   "secrets": one_(t, "o365res_app_secrets"), "perms": one_(t, "o365res_app_perms"), "enterprise": one_(t, "o365res_enterprise"), "groups": one_(t, "o365res_groups")}
    scans = []
    for tbl, src, title in SCANS:
        s = L["status"].get(src, ("ok", ""))
        scans.append([title, src, "available" if s[0] == "ok" and tbl in L["tables"] else ("not available" if s[0] != "ok" else "missing from archive"), s[1][:160]])
    nc_rows = [] if a.no_actors else [{"userPrincipalName": r.get("userPrincipalName") or "", "displayName": r.get("displayName") or "", "userType": r.get("userType") or "",
               "finding": r.get("finding") or "", "isAdmin": truthy(r.get("isAdmin")), "roles": roles_text(r.get("roles"))}
              for r in sorted(nc, key=lambda r: (not truthy(r.get("isAdmin")), str(r.get("userPrincipalName")).lower()))]
    lic_rows = [] if a.no_actors else [{"userPrincipalName": r.get("userPrincipalName") or "", "displayName": r.get("displayName") or "", "userType": r.get("userType") or "",
                "accountEnabled": truthy(r.get("accountEnabled")), "licenseCount": num(r.get("licenseCount")), "licenses": r.get("licenses") or ""} for r in lic]
    data = {"tenant": a.tenant, "site": a.site, "from": expected[0], "to": expected[-1], "asOf": last, "noActors": a.no_actors,
            "latest": days[last], "ca": L["tables"].get("o365res_ca") or [], "nc": nc_rows, "ncCount": len(nc), "lic": lic_rows, "perlic": perlic.most_common(),
            "days": days, "dayList": list(in_period), "expected": expected[-90:], "gaps": gaps, "hashes": hashes, "scans": scans,
            "status": {k: list(v) for k, v in L["status"].items()}, "limits": LIMITS}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    open(path, "w").write("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Microsoft 365 Resource Inventory</title><style>%s</style></head><body>"
        "<header><div class='w'><div class='eyebrow'>Microsoft 365 / Entra</div><h1 id='ttl'></h1><div id='chips'></div></div></header><nav><div class='w'></div></nav><main id='main'></main>"
        "<script id='data' type='application/json'>%s</script><script>%s</script></body></html>" % (INTER_CSS, blob, INTER_JS))

INTER_CSS = ':root{--red:#B91C1C;--blu:#1D4ED8;--amb:#B45309;--grn:#15803D;--gry:#64748B;--bg:#f4f6fa;--card:#fff;--ink:#1f2937;--m:#64748b;--line:#e2e8f0;--acc:#1d4ed8;--navy:#14213d}\n@media(prefers-color-scheme:dark){:root{--red:#f87171;--blu:#7aa7ff;--amb:#fbbf24;--grn:#4ade80;--gry:#94a3b8;--bg:#0f1523;--card:#182033;--ink:#e5ebf7;--m:#8b9bb8;--line:#26324b;--acc:#6ea0ff;--navy:#e5ebf7}}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}\nheader{background:linear-gradient(135deg,#0f1a33,#1d3461);color:#fff;padding:26px 0 18px}.w{max-width:1180px;margin:0 auto;padding:0 20px}\n.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}h1{margin:4px 0 8px;font-size:26px}\n.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:2px 11px;font-size:12px;margin:0 8px 4px 0}\nnav{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);overflow-x:auto;white-space:nowrap}nav .w{display:flex;gap:2px}\nnav button{background:none;border:0;border-bottom:3px solid transparent;color:var(--m);font:600 13px inherit;padding:12px 14px;cursor:pointer}nav button.on{color:var(--acc);border-color:var(--acc)}\nmain{padding:18px 20px 48px;max-width:1180px;margin:0 auto}.g{display:grid;gap:12px}.k4{grid-template-columns:repeat(4,1fr)}.c2{grid-template-columns:repeat(2,1fr)}\n@media(max-width:800px){.k4,.c2{grid-template-columns:repeat(2,1fr)}}\n.k{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--c);border-radius:10px;padding:12px 14px}.k[data-go]{cursor:pointer}.k[data-go]:hover{box-shadow:0 2px 10px rgba(0,0,0,.12)}\n.k b{display:block;font-size:26px;color:var(--c);line-height:1.15}.k span{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--m);font-weight:600}.k small{display:block;color:var(--m);font-size:11px}\n.p{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:12px}.p:first-child{margin-top:0}.p h3{margin:0 0 8px;font-size:14px}.warn{border-left:4px solid #B45309;background:rgba(180,83,9,.1)}.read{border-left:4px solid var(--acc)}\ntable{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--m);padding:8px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--card);cursor:pointer;white-space:nowrap}td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:break-word;word-break:normal}td:nth-child(3){min-width:64px}.r{text-align:right;font-variant-numeric:tabular-nums}\n.tw{max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:8px}.m{color:var(--m)}.sm{font-size:12px}\n.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}input[type=search],select,button{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit}input[type=search]{min-width:220px;flex:1}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}\n.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600;background:rgba(180,83,9,.15);color:var(--amb);white-space:nowrap}.pill.bad{background:rgba(185,28,28,.15);color:var(--red)}\n.stack{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}.stack i{display:block}.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}\n.row{display:grid;grid-template-columns:34% 1fr 60px;gap:8px;align-items:center;margin:4px 0;font-size:12px;cursor:pointer;border-radius:4px;padding:1px 4px}.row:hover{background:var(--line)}.lb{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row b{text-align:right}\n.bar2{background:var(--line);height:8px;border-radius:4px;overflow:hidden}.bar2 i{display:block;height:100%;background:var(--acc)}\n.chart{width:100%;height:auto}.gl{stroke:var(--line)}.ax{fill:var(--m);font-size:11px}.gp{fill:#f59e0b;opacity:.35}\n@media print{nav{display:none}.tw{max-height:none}}\n.big{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;padding:16px 22px}.big span{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--m);font-weight:700}.big b{display:block;font-size:60px;line-height:1.05;color:var(--c);letter-spacing:-.02em;margin:2px 0}.big small{display:block;color:var(--m);font-size:12px}.big[data-go]{cursor:pointer}\n'
INTER_JS = 'const D=JSON.parse(document.getElementById(\'data\').textContent);\nconst $=s=>document.querySelector(s);\nconst esc=v=>String(v==null?\'\':v).replace(/[&<>"\']/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[c]));\nconst fmt=v=>typeof v===\'number\'?v.toLocaleString():esc(v);\nconst L=D.latest, U=L.users||null;\nconst TABS=[[\'ov\',\'Overview\'],[\'us\',\'Users without MFA\'],[\'li\',\'Licenses\'],[\'ap\',\'Applications\'],[\'dv\',\'Devices and policies\'],[\'gr\',\'Groups\'],[\'tr\',\'Trends\'],[\'cv\',\'Coverage\']];\nlet tab=\'ov\';\nconst CM={\'#14213d\':\'var(--navy)\',\'#B91C1C\':\'var(--red)\',\'#1D4ED8\':\'var(--blu)\',\'#B45309\':\'var(--amb)\',\'#15803D\':\'var(--grn)\',\'#64748B\':\'var(--gry)\'};const cc=c=>CM[c]||c;\nfunction kpi(l,v,c,s,go){c=cc(c);return `<div class="k" style="--c:${c}" ${go?`data-go="${go}"`:\'\'}><span>${esc(l)}</span><b>${esc(v)}</b><small>${esc(s||\'\')}</small></div>`}\nfunction big(l,v,sub,c,go){c=cc(c);return `<div class="big" style="--c:${c}" ${go?`data-go="${go}"`:\'\'}><span>${esc(l)}</span><b>${esc(v)}</b><small>${esc(sub||\'\')}</small></div>`}\nfunction na(t,why){return `<div class="p warn"><b>${esc(t)}</b> not available: ${esc(why||\'the tenant could not run this scan\')}</div>`}\nfunction kv(t,pairs){return `<div class="p"><h3>${esc(t)}</h3><table>${pairs.map(([k,v])=>`<tr><td>${esc(k)}</td><td class="r">${fmt(v)}</td></tr>`).join(\'\')}</table></div>`}\nfunction stack(parts,total){if(!total)return\'\';return `<div class="stack">${parts.filter(p=>p[1]).map(p=>`<i title="${esc(p[0])}: ${p[1].toLocaleString()}" style="width:${100*p[1]/total}%;background:${p[2]}"></i>`).join(\'\')}</div><div class="m sm">${parts.map(p=>`<span class="lg"><i style="background:${p[2]}"></i>${esc(p[0])} ${p[1].toLocaleString()}</span>`).join(\' \')}</div>`}\nfunction pct(a,b){return b?Math.round(100*a/b)+\'%\':\'n/a\'}\nfunction st(src){const s=D.status[src];return s?s[0]:\'ok\'}\n/* generic searchable, sortable, paged table */\nfunction dt(id,cols,rows,opts){opts=opts||{};const S={q:\'\',sort:null,dir:1,page:0,size:25,f:{}};const root=document.createElement(\'div\');root.className=\'p\';\n const filters=(opts.filters||[]);\n function view(){let r=rows.filter(x=>{for(const f of filters){const v=S.f[f.key];if(v&&String(x[f.key])!==v&&!(f.fn&&f.fn(x,v)))return false}\n  if(S.q){const q=S.q.toLowerCase();if(!cols.some(c=>String(x[c.k]==null?\'\':x[c.k]).toLowerCase().includes(q)))return false}return true});\n  if(S.sort){const k=S.sort;r=r.slice().sort((a,b)=>{const x=a[k],y=b[k];return (typeof x===\'number\'&&typeof y===\'number\'?x-y:String(x).localeCompare(String(y)))*S.dir})}return r}\n function draw(){const r=view(),pages=Math.max(1,Math.ceil(r.length/S.size));if(S.page>=pages)S.page=pages-1;const sl=r.slice(S.page*S.size,(S.page+1)*S.size);\n  root.innerHTML=`<h3>${esc(opts.title||\'\')} <span class="m">(${r.length.toLocaleString()} of ${rows.length.toLocaleString()})</span></h3><div class="bar">\n   <input type="search" placeholder="Search" value="${esc(S.q)}" data-a="q">\n   ${filters.map(f=>`<select data-f="${f.key}"><option value="">${esc(f.label)}: all</option>${f.opts.map(o=>`<option ${S.f[f.key]===o?\'selected\':\'\'}>${esc(o)}</option>`).join(\'\')}</select>`).join(\'\')}\n   <select data-a="size">${[25,50,100,250].map(n=>`<option ${n===S.size?\'selected\':\'\'}>${n}</option>`).join(\'\')}</select>\n   <button data-a="csv">Export CSV</button></div>\n   <div class="tw"><table><thead><tr>${cols.map(c=>`<th data-s="${c.k}" class="${c.num?\'r\':\'\'}">${esc(c.h)}${S.sort===c.k?(S.dir>0?\' ▲\':\' ▼\'):\'\'}</th>`).join(\'\')}</tr></thead><tbody>${sl.map(x=>`<tr>${cols.map(c=>`<td class="${c.num?\'r\':\'\'}">${c.pill?`<span class="pill ${x[c.k]===\'Admin without MFA\'?\'bad\':\'\'}">${esc(x[c.k])}</span>`:fmt(x[c.k])}</td>`).join(\'\')}</tr>`).join(\'\')||`<tr><td colspan="${cols.length}" class="m">No rows match.</td></tr>`}</tbody></table></div>\n   <div class="bar"><button data-a="prev" ${S.page?\'\':\'disabled\'}>Prev</button><span class="m">Page ${S.page+1} of ${pages}</span><button data-a="next" ${S.page<pages-1?\'\':\'disabled\'}>Next</button></div>`;\n  const q=root.querySelector(\'[data-a=q]\');q.oninput=e=>{S.q=e.target.value;S.page=0;const p=e.target.selectionStart;draw();const n=root.querySelector(\'[data-a=q]\');n.focus();n.setSelectionRange(p,p)};\n  root.querySelectorAll(\'[data-f]\').forEach(s=>s.onchange=e=>{S.f[s.dataset.f]=e.target.value;S.page=0;draw()});\n  root.querySelector(\'[data-a=size]\').onchange=e=>{S.size=+e.target.value;S.page=0;draw()};\n  root.querySelector(\'[data-a=prev]\').onclick=()=>{S.page--;draw()};root.querySelector(\'[data-a=next]\').onclick=()=>{S.page++;draw()};\n  root.querySelectorAll(\'th[data-s]\').forEach(h=>h.onclick=()=>{if(S.sort===h.dataset.s)S.dir*=-1;else{S.sort=h.dataset.s;S.dir=1}draw()});\n  root.querySelector(\'[data-a=csv]\').onclick=()=>{const q=v=>\'"\'+String(v==null?\'\':v).replace(/"/g,\'""\')+\'"\';const t=[cols.map(c=>q(c.h)).join(\',\')].concat(view().map(x=>cols.map(c=>q(x[c.k])).join(\',\'))).join(\'\\n\');const a=document.createElement(\'a\');a.href=URL.createObjectURL(new Blob([t],{type:\'text/csv\'}));a.download=(opts.file||\'export\')+\'.csv\';a.click()}}\n root.draw=draw;root._S=S;draw();return root}\nconst V={};\nV.ov=()=>{const c=document.createElement(\'div\');if(!U){c.innerHTML=na(\'Users\',(D.status.office365User||[])[1]);return c}\n const known=U.registrationKnown>0;\n c.innerHTML=`<div class="g k4">${kpi(\'Users\',U.users.toLocaleString(),\'#14213d\',U.enabled.toLocaleString()+\' enabled, \'+U.disabled.toLocaleString()+\' disabled\')}${kpi(\'Administrators\',U.admins,\'#1D4ED8\',\'isAdmin or any directory role\')}${kpi(\'Enabled, no MFA\',known?U.enabledNoMfa.toLocaleString():\'unknown\',known&&U.enabledNoMfa?\'#B91C1C\':\'#15803D\',known?pct(U.enabledNoMfa,U.enabled)+\' of enabled users\':\'no MFA registration data\',\'us\')}${kpi(\'Admins, no MFA\',known?U.adminsNoMfa:\'unknown\',known&&U.adminsNoMfa?\'#B91C1C\':\'#15803D\',\'enabled administrators\',\'us\')}</div>\n ${known?`<div class="p" style="margin-top:12px"><h3>Enabled users by MFA registration</h3>${stack([[\'MFA registered\',U.enabledMfaRegistered,\'#15803D\'],[\'No MFA\',U.enabledNoMfa,\'#B91C1C\']],U.enabled)}</div>`:\'\'}\n <div class="g k4" style="margin-top:12px">${L.devices?kpi(\'Devices\',L.devices.devices.toLocaleString(),\'#14213d\',L.devices.nonCompliant+\' non-compliant, \'+L.devices.stale90d+\' stale\',\'dv\'):\'\'}${L.apps?kpi(\'App registrations\',L.apps.apps,\'#1D4ED8\',(L.secrets?L.secrets.expired+\' expired secrets\':\'\'),\'ap\'):\'\'}${L.enterprise?kpi(\'Enterprise apps\',L.enterprise.total.toLocaleString(),\'#B45309\',L.enterprise.thirdParty+\' third party\',\'ap\'):\'\'}${L.groups?kpi(\'Groups\',L.groups.groups.toLocaleString(),\'#14213d\',L.groups.publicGroups+\' public\',\'gr\'):\'\'}</div>\n <div class="p read" style="margin-top:12px">State as of <b>${esc(D.asOf)}</b>. Directory tables are snapshots: figures are the latest archived day, never a sum of days. MFA registration is not MFA enforcement.</div>`;\n c.querySelectorAll(\'[data-go]\').forEach(k=>k.onclick=()=>show(k.dataset.go));return c};\nV.us=()=>{const c=document.createElement(\'div\');if(D.noActors){c.innerHTML=\'<div class="p warn">User lists were left out (built with no-actors).</div>\';return c}\n if(U&&!U.registrationKnown){c.innerHTML=na(\'Users without MFA\',\'the tenant reports no MFA registration, so the list is empty and is not knowledge that everyone has MFA\');return c}\n if(U)c.insertAdjacentHTML(\'beforeend\',\'<div class="g k4" style="margin-bottom:12px">\'+kpi(\'Users\',U.users.toLocaleString(),\'#14213d\',U.enabled.toLocaleString()+\' enabled, \'+U.disabled.toLocaleString()+\' disabled\')+kpi(\'Enabled, no MFA\',U.enabledNoMfa.toLocaleString(),U.enabledNoMfa?\'#B91C1C\':\'#15803D\',pct(U.enabledNoMfa,U.enabled)+\' of enabled users\')+kpi(\'Admins, no MFA\',U.adminsNoMfa,U.adminsNoMfa?\'#B91C1C\':\'#15803D\',\'of \'+U.admins+\' administrators\')+kpi(\'Guests\',U.guests.toLocaleString(),\'#64748B\',\'userType Guest\')+\'</div>\');\n const rows=D.nc.map(r=>Object.assign({},r,{adm:r.isAdmin?\'Yes\':\'No\'}));\n c.appendChild(dt(\'nc\',[{k:\'userPrincipalName\',h:\'User\'},{k:\'displayName\',h:\'Name\'},{k:\'userType\',h:\'Type\'},{k:\'finding\',h:\'Finding\',pill:1},{k:\'roles\',h:\'Directory roles\'}],rows,{title:\'Enabled users with no MFA registered\',file:\'users_no_mfa\',filters:[{key:\'finding\',label:\'Finding\',opts:[\'Admin without MFA\',\'Enabled user without MFA\']},{key:\'userType\',label:\'Type\',opts:[...new Set(rows.map(r=>r.userType))].filter(Boolean)}]}));\n if(U&&D.nc.length!==U.enabledNoMfa){const w=document.createElement(\'div\');w.className=\'p warn\';w.textContent=\'The list has \'+D.nc.length+\' users but the summary counts \'+U.enabledNoMfa+\': the archived list is incomplete.\';c.appendChild(w)}return c};\nV.li=()=>{const c=document.createElement(\'div\');if(st(\'licensed users\')!==\'ok\'){c.innerHTML=na(\'Licensed users\',(D.status[\'licensed users\']||[])[1]);return c}\n const max=Math.max(1,...D.perlic.map(x=>x[1]));let sel=\'\';\n const bx=document.createElement(\'div\');bx.className=\'p\';bx.innerHTML=`<h3>Users per license <span class="m">(click a license to filter the users below)</span></h3>`+D.perlic.slice(0,40).map(([k,v])=>`<div class="row" data-l="${esc(k)}"><span class="lb">${esc(k)}</span><span class="bar2"><i style="width:${100*v/max}%"></i></span><b>${v.toLocaleString()}</b></div>`).join(\'\');\n c.appendChild(bx);\n if(!D.noActors){const t=dt(\'li\',[{k:\'userPrincipalName\',h:\'User\'},{k:\'displayName\',h:\'Name\'},{k:\'userType\',h:\'Type\'},{k:\'acct\',h:\'Account\'},{k:\'licenseCount\',h:\'Licenses\',num:1},{k:\'licenses\',h:\'License names\'}],D.lic.map(r=>Object.assign({},r,{acct:r.accountEnabled?\'Enabled\':\'Disabled\'})),{title:\'Licensed users\',file:\'licensed_users\',filters:[{key:\'acct\',label:\'Account\',opts:[\'Enabled\',\'Disabled\']}]});c.appendChild(t);\n  bx.querySelectorAll(\'[data-l]\').forEach(r=>r.onclick=()=>{const q=t.querySelector(\'[data-a=q]\');q.value=r.dataset.l;q.oninput({target:q})})}return c};\nV.ap=()=>{const c=document.createElement(\'div\');const a=L.apps,s=L.secrets,p=L.perms,e=L.enterprise;let h=\'\';\n c.innerHTML=(a?`<div class="g k4">${kpi(\'App registrations\',a.apps,\'#14213d\',a.multiTenant+\' multi-tenant\')}${kpi(\'Client secrets\',(s||a).secrets,\'#1D4ED8\',a.certificates+\' certificates\')}${kpi(\'Expired secrets\',s?s.expired:\'n/a\',s&&s.expired?\'#B91C1C\':\'#15803D\',s?s.expiring90d+\' expire within 90 days\':\'\')}${kpi(\'App-only access\',p?p.appsAppOnly:\'n/a\',\'#B45309\',\'request an application permission\')}</div>`:na(\'App registrations\',(D.status.office365Application||[])[1]))+\'<div class="g c2" style="margin-top:12px" id="ag"></div>\';\n const g=c.querySelector(\'#ag\');\n if(a)g.insertAdjacentHTML(\'beforeend\',kv(\'Registrations\',[[\'App registrations\',a.apps],[\'With no secret or certificate\',a.appsNoCredentials],[\'Secrets\',a.secrets],[\'Certificates\',a.certificates],[\'Multi-tenant audience\',a.multiTenant]]));\n if(s)g.insertAdjacentHTML(\'beforeend\',kv(\'Client secret tests\',[[\'Client secrets\',s.secrets],[\'Expired\',s.expired],[\'Expiring within 90 days\',s.expiring90d],[\'Valid for more than 730 days\',s.longLived]]));\n if(e)g.insertAdjacentHTML(\'beforeend\',kv(\'Enterprise applications\',[[\'Total\',e.total],[\'Enabled\',e.enabled],[\'Disabled\',e.disabled],[\'Microsoft-owned\',e.microsoftOwned],[\'Registered in this tenant\',e.registeredHere],[\'Third party\',e.thirdParty],[\'User assignment required\',e.assignmentRequired],[\'With credentials\',e.withCredentials]]));else g.insertAdjacentHTML(\'beforeend\',na(\'Enterprise applications\',(D.status.office365InstalledApp||[])[1]));return c};\nV.dv=()=>{const c=document.createElement(\'div\');const d=L.devices;\n c.innerHTML=(d?`<div class="g k4">${kpi(\'Devices\',d.devices.toLocaleString(),\'#14213d\',\'\')}${kpi(\'Managed\',d.managedKnown?d.managed.toLocaleString():\'not reported\',\'#1D4ED8\',d.managedKnown?\'of \'+d.managedKnown.toLocaleString()+\' reporting\':\'\')}${kpi(\'Non-compliant\',d.complianceKnown?d.nonCompliant.toLocaleString():\'not reported\',d.nonCompliant?\'#B91C1C\':\'#15803D\',d.complianceKnown?\'of \'+d.complianceKnown.toLocaleString()+\' reporting\':\'\')}${kpi(\'Stale (90 days)\',d.stale90d.toLocaleString(),\'#B45309\',\'no sign-in for 90 days\')}</div>`:na(\'Devices\',(D.status.office365Device||[])[1]))+\'<div style="margin-top:12px" id="cax"></div>\';\n const x=c.querySelector(\'#cax\');if(st(\'office365ConditionalAccessPolicy\')!==\'ok\')x.innerHTML=na(\'Conditional Access policies\',(D.status.office365ConditionalAccessPolicy||[])[1]);\n else{const lab={enabled:\'Enabled (enforced)\',enabledForReportingButNotEnforced:\'Report-only\',disabled:\'Disabled\'};x.innerHTML=`<div class="p"><h3>Conditional Access policies by state</h3><table>${D.ca.length?D.ca.map(r=>`<tr><td>${esc(lab[r.state]||r.state)}</td><td class="r">${r.policies}</td></tr>`).join(\'\'):\'<tr><td class="m">No policies.</td></tr>\'}</table></div>`}return c};\nV.gr=()=>{const c=document.createElement(\'div\');const g=L.groups;if(!g){c.innerHTML=na(\'Groups\',(D.status.office365Group||[])[1]);return c}\n c.innerHTML=`<div class="g k4">${kpi(\'Groups\',g.groups.toLocaleString(),\'#14213d\',g.securityEnabled.toLocaleString()+\' security, \'+g.microsoft365.toLocaleString()+\' Microsoft 365\')}${kpi(\'Public\',g.publicGroups,\'#B45309\',\'\')}${kpi(\'Role-assignable\',g.roleAssignable,\'#1D4ED8\',\'can hold directory roles\')}${kpi(\'Empty\',g.emptyGroups,\'#64748B\',\'no members\')}</div><div style="margin-top:12px">${kv(\'Group counts\',[[\'Groups\',g.groups],[\'Security-enabled\',g.securityEnabled],[\'Microsoft 365\',g.microsoft365],[\'Dynamic membership\',g.dynamicGroups],[\'Public\',g.publicGroups],[\'Role-assignable\',g.roleAssignable],[\'Empty\',g.emptyGroups],[\'Membership entries\',g.membersTotal]])}</div><p class="m sm">Names and members are not collected.</p>`;return c};\nconst METRICS=[[\'users\',\'users\',\'Users\'],[\'users\',\'enabledNoMfa\',\'Enabled users without MFA\'],[\'users\',\'adminsNoMfa\',\'Administrators without MFA\'],[\'users\',\'admins\',\'Administrators\'],[\'users\',\'guests\',\'Guests\'],[\'devices\',\'nonCompliant\',\'Non-compliant devices\'],[\'devices\',\'stale90d\',\'Stale devices (90 days)\'],[\'secrets\',\'expired\',\'Expired client secrets\'],[\'secrets\',\'expiring90d\',\'Secrets expiring in 90 days\'],[\'apps\',\'apps\',\'App registrations\'],[\'enterprise\',\'thirdParty\',\'Third-party enterprise apps\'],[\'groups\',\'groups\',\'Groups\'],[\'groups\',\'publicGroups\',\'Public groups\']];\nV.tr=()=>{const c=document.createElement(\'div\');const days=D.days;const have=D.dayList;\n if(have.length<2){c.innerHTML=\'<div class="p warn">Only one archived day in the period, so there is no trend yet. Trends appear once the daily archive holds two or more days.</div>\';return c}\n const avail=METRICS.filter(m=>have.filter(d=>days[d][m[0]]&&days[d][m[0]][m[1]]!=null).length>1);let cur=0;\n c.innerHTML=`<div class="p"><div class="bar"><select id="mt">${avail.map((m,i)=>`<option value="${i}">${esc(m[2])}</option>`).join(\'\')}</select><label class="m"><input type="checkbox" id="zb" checked> start at zero</label></div><div id="ch"></div></div><div id="tb" style="margin-top:12px"></div>`;\n function draw(){const m=avail[cur];const all=D.expected;const ser={};have.forEach(d=>{const v=days[d][m[0]]&&days[d][m[0]][m[1]];if(v!=null)ser[d]=v});const vals=Object.values(ser);let lo=$(\'#zb\').checked?0:Math.min(...vals),hi=Math.max(...vals);if(hi===lo){hi=lo+1}\n  const W=900,H=260,l=48,r=14,t=14,b=30,pw=W-l-r,ph=H-t-b;const X=i=>l+(all.length>1?i*pw/(all.length-1):pw/2),Y=v=>t+ph-(v-lo)/(hi-lo)*ph;\n  let s=`<svg viewBox="0 0 ${W} ${H}" class="chart">`;for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=Y(v);s+=`<line x1="${l}" x2="${W-r}" y1="${y}" y2="${y}" class="gl"/><text x="${l-6}" y="${y+4}" text-anchor="end" class="ax">${Math.round(v).toLocaleString()}</text>`}\n  all.forEach((d,i)=>{if(!(d in ser))s+=`<rect x="${X(i)-3}" y="${t}" width="6" height="${ph}" class="gp"><title>${d}: not archived</title></rect>`});\n  const pts=all.map((d,i)=>d in ser?[X(i),Y(ser[d]),d,ser[d]]:null).filter(Boolean);\n  s+=`<polyline fill="none" stroke="var(--acc)" stroke-width="2.5" points="${pts.map(p=>p[0]+\',\'+p[1]).join(\' \')}"/>`;pts.forEach(p=>s+=`<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="var(--acc)"><title>${p[2]}: ${p[3].toLocaleString()}</title></circle>`);\n  const step=Math.ceil(all.length/8);all.forEach((d,i)=>{if(i%step===0||i===all.length-1)s+=`<text x="${X(i)}" y="${H-8}" text-anchor="middle" class="ax">${d.slice(5)}</text>`});$(\'#ch\').innerHTML=s+\'</svg>\';\n  const f=ser[Object.keys(ser)[0]],la=ser[Object.keys(ser).pop()],dl=la-f;\n  $(\'#tb\').innerHTML=`<div class="p"><h3>${esc(m[2])}: ${la.toLocaleString()} <span class="m">(${dl===0?\'no change\':(dl>0?\'up \':\'down \')+Math.abs(dl).toLocaleString()+\' since \'+Object.keys(ser)[0]})</span></h3><div class="tw"><table><thead><tr><th>Day</th><th class="r">Value</th><th class="r">Change</th></tr></thead><tbody>${Object.keys(ser).map((d,i,a)=>`<tr><td>${d}</td><td class="r">${ser[d].toLocaleString()}</td><td class="r">${i?(ser[d]-ser[a[i-1]]>0?\'+\':\'\')+(ser[d]-ser[a[i-1]]).toLocaleString():\'\'}</td></tr>`).join(\'\')}</tbody></table></div></div>`}\n $(\'#mt\',c);setTimeout(()=>{$(\'#mt\').onchange=e=>{cur=+e.target.value;draw()};$(\'#zb\').onchange=draw;draw()},0);return c};\nV.cv=()=>{const c=document.createElement(\'div\');\n c.innerHTML=`<div class="p"><b>${D.dayList.length} of ${D.expected.length}</b> days archived in the period (${esc(D.from)} to ${esc(D.to)}). Report date: <b>${esc(D.asOf)}</b>.</div>${D.gaps.length?`<div class="p warn" style="margin-top:12px">Missing days: ${D.gaps.map(g=>esc(g[0])+\' (\'+esc(g[1])+\')\').join(\', \')}. A gap is not an unchanged directory. A backfill records the directory as it is now, not as it was.</div>`:\'\'}${D.hashes.length>1?\'<div class="p warn" style="margin-top:12px">The report script changed during the period: compare days with care.</div>\':\'\'}\n <div class="p" style="margin-top:12px"><h3>Scans</h3><table><thead><tr><th>Scan</th><th>Source</th><th>State</th><th>Detail</th></tr></thead><tbody>${D.scans.map(s=>`<tr><td>${esc(s[0])}</td><td class="m">${esc(s[1])}</td><td>${esc(s[2])}</td><td class="m">${esc(s[3])}</td></tr>`).join(\'\')}</tbody></table></div>\n <div class="p" style="margin-top:12px"><h3>Limits</h3><ul>${D.limits.map(x=>`<li>${esc(x)}</li>`).join(\'\')}</ul></div>`;return c};\nfunction show(t){tab=t;document.querySelectorAll(\'nav button\').forEach(b=>b.classList.toggle(\'on\',b.dataset.t===t));const m=$(\'#main\');m.innerHTML=\'\';m.appendChild(V[t]());m.querySelectorAll(\'[data-go]\').forEach(k=>k.onclick=()=>show(k.dataset.go));location.hash=t}\n$(\'nav .w\').innerHTML=TABS.map(t=>`<button data-t="${t[0]}">${t[1]}</button>`).join(\'\');\ndocument.querySelectorAll(\'nav button\').forEach(b=>b.onclick=()=>show(b.dataset.t));\n$(\'#chips\').innerHTML=[D.site,D.from+\' to \'+D.to,\'state as of \'+D.asOf,D.dayList.length+\' of \'+D.expected.length+\' days archived\'].filter(Boolean).map(x=>`<span class="chip">${esc(x)}</span>`).join(\'\');\n$(\'#ttl\').textContent=(D.tenant||\'Tenant\')+\' Microsoft 365 Resource Inventory\';document.title=$(\'#ttl\').textContent;\nshow(TABS.some(t=>t[0]===location.hash.slice(1))?location.hash.slice(1):\'ov\');\n'


def stack(parts, total):
    """Horizontal stacked bar: parts = [(label, value, color)]."""
    if not total:
        return ""
    segs = "".join("<div title='%s: %s' style='width:%.2f%%;background:%s'></div>" % (E(l), n(v), 100.0 * v / total, c) for l, v, c in parts if v)
    leg = " &nbsp; ".join("<span><i style='display:inline-block;width:10px;height:10px;border-radius:2px;background:%s;margin-right:4px'></i>%s %s</span>" % (c, E(l), n(v)) for l, v, c in parts)
    return "<div style='display:flex;height:14px;border-radius:7px;overflow:hidden;background:#e2e8f0;margin:10px 0 6px'>%s</div><div class='mut' style='font-size:12px'>%s</div>" % (segs, leg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interactive", help="also write a self-contained interactive HTML file to this path")
    ap.add_argument("--csv")
    ap.add_argument("--summary-json")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to", dest="to")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--no-actors", action="store_true")
    a = ap.parse_args()

    done, other = load(a.archive)
    if not done:
        sys.exit("no completed archived day in the files given")
    have = sorted(done)
    frm, to = a.frm or have[0], a.to or have[-1]
    expected = days_between(frm, to)
    in_period = [d for d in have if frm <= d <= to]
    if not in_period:
        sys.exit("no archived day between %s and %s (archive holds %s to %s)" % (frm, to, have[0], have[-1]))
    last = in_period[-1]
    L = done[last]
    gaps = [(d, other.get(d, "not archived")) for d in expected if d not in done]
    hashes = sorted({done[d]["entry"].get("env", {}).get("scriptHash", "") for d in in_period} - {""})
    st = lambda src: L["status"].get(src, ("ok", ""))

    u, dv, ap_, sec, perm, ent, grp = (one(L, t) for t in ("o365res_users", "o365res_devices", "o365res_apps", "o365res_app_secrets", "o365res_app_perms", "o365res_enterprise", "o365res_groups"))
    ca = L["tables"].get("o365res_ca") or []
    nc = L["tables"].get("o365res_noncompliant_users") or []
    lic = L["tables"].get("o365res_licensed_users") or []
    g = lambda r, k: num((r or {}).get(k))
    U = lambda k: g(u, k)

    sections = []
    # 1 accounts and MFA
    if u:
        known = U("registrationKnown") > 0
        enabled = U("enabled")
        k = "".join([kpi("Users", n(U("users")), NAVY, "%s enabled, %s disabled" % (n(enabled), n(U("disabled")))),
                     kpi("Administrators", n(U("admins")), BLU, "isAdmin or any directory role"),
                     kpi("Enabled, no MFA", n(U("enabledNoMfa")) if known else "unknown", RED if known and U("enabledNoMfa") else GRN,
                         ("%s of enabled users" % pct(U("enabledNoMfa"), enabled)) if known else "no MFA registration data"),
                     kpi("Admins, no MFA", n(U("adminsNoMfa")) if known else "unknown", RED if known and U("adminsNoMfa") else GRN, "enabled administrators")])
        bar = stack([("MFA registered", U("enabledMfaRegistered"), GRN), ("No MFA", U("enabledNoMfa"), RED)], enabled) if known else ""
        sections.append(("Accounts and MFA", "Account hygiene and MFA registration for enabled users, as of %s." % last,
            "<div class='kpis two'>%s</div><div class='panel' style='margin-top:14px'><b>Enabled users by MFA registration</b>%s</div>%s" % (k, bar,
            kv("Account counts", "", [("Users", U("users")), ("Enabled", enabled), ("Disabled", U("disabled")), ("Guests", U("guests")), ("Administrators", U("admins")),
                ("Users with an MFA registration record", U("registrationKnown")), ("Enabled with MFA registered", U("enabledMfaRegistered")), ("Enabled without MFA", U("enabledNoMfa")), ("Administrators without MFA", U("adminsNoMfa"))]))))
    else:
        sections.append(("Accounts and MFA", "", na("Users", st("office365User")[1])))

    # 2 users without MFA
    if a.no_actors:
        body2 = "<div class='gap'>User lists were left out (built with --no-actors). Counts are in section 1.</div>"
    elif u and not U("registrationKnown"):
        body2 = na("Users without MFA", "the tenant reports no MFA registration, so the list is empty and is not knowledge that everyone has MFA")
    else:
        nc_sorted = sorted(nc, key=lambda r: (not truthy(r.get("isAdmin")), str(r.get("userPrincipalName")).lower()))
        rows = [[r.get("userPrincipalName") or "", r.get("displayName") or "", r.get("userType") or "", r.get("finding") or "", roles_text(r.get("roles"))] for r in nc_sorted]
        body2 = gtable("Enabled users with no MFA registered", "One row per user, administrators first. %s users in total (%s administrators)." % (n(len(nc)), n(sum(1 for r in nc if truthy(r.get("isAdmin"))))),
                       ["User", "Name", "Type", "Finding", "Directory roles"], rows, a.top, [27, 17, 10, 16, 30])
        if u and len(nc) != U("enabledNoMfa"):
            body2 += "<div class='gap'>The list has %s users but the summary counts %s: the archived list is incomplete.</div>" % (n(len(nc)), n(U("enabledNoMfa")))
    if u:
        tiles = "<div class='kpis two'>%s</div>" % "".join([kpi("Users", n(U("users")), NAVY, "%s enabled, %s disabled" % (n(U("enabled")), n(U("disabled")))),
            kpi("Enabled, no MFA", n(U("enabledNoMfa")) if U("registrationKnown") else "unknown", RED if U("registrationKnown") and U("enabledNoMfa") else GRN, "%s of enabled users" % pct(U("enabledNoMfa"), U("enabled"))),
            kpi("Admins, no MFA", n(U("adminsNoMfa")) if U("registrationKnown") else "unknown", RED if U("registrationKnown") and U("adminsNoMfa") else GRN, "of %s administrators" % n(U("admins"))),
            kpi("Guests", n(U("guests")), GRY, "userType Guest")])
        body2 = tiles + body2
    sections.append(("Users without MFA", "The accounts that fail the MFA registration test.", body2))

    # 3 devices
    if dv:
        k = "".join([kpi("Devices", n(g(dv, "devices")), NAVY, ""),
                     kpi("Managed", n(g(dv, "managed")) if g(dv, "managedKnown") else "not reported", BLU, ("of %s devices reporting the field" % n(g(dv, "managedKnown"))) if g(dv, "managedKnown") else ""),
                     kpi("Non-compliant", n(g(dv, "nonCompliant")) if g(dv, "complianceKnown") else "not reported", RED if g(dv, "nonCompliant") else GRN, ("of %s devices reporting the field" % n(g(dv, "complianceKnown"))) if g(dv, "complianceKnown") else ""),
                     kpi("Stale (90 days)", n(g(dv, "stale90d")), AMB, "no sign-in for 90 days")])
        sections.append(("Devices", "Entra-registered devices as of %s." % last, "<div class='kpis two'>%s</div>" % k))
    else:
        sections.append(("Devices", "", na("Devices", st("office365Device")[1])))

    # 4 conditional access
    if st("office365ConditionalAccessPolicy")[0] != "ok":
        sections.append(("Conditional Access", "", na("Conditional Access policies", st("office365ConditionalAccessPolicy")[1])))
    else:
        label = {"enabled": "Enabled (enforced)", "enabledForReportingButNotEnforced": "Report-only", "disabled": "Disabled"}
        rows = [[label.get(r.get("state"), r.get("state")), num(r.get("policies"))] for r in ca]
        tot = sum(r[1] for r in rows)
        sections.append(("Conditional Access", "Policies by state as of %s (%s in total)." % (last, n(tot)), gtable("Conditional Access policies by state", "Report-only policies log but do not enforce.", ["State", "Policies"], rows, 99)))

    # 5 apps
    if ap_:
        k = "".join([kpi("App registrations", n(g(ap_, "apps")), NAVY, "%s multi-tenant" % n(g(ap_, "multiTenant"))),
                     kpi("Client secrets", n(g(sec, "secrets") if sec else g(ap_, "secrets")), BLU, "%s certificates" % n(g(ap_, "certificates"))),
                     kpi("Expired secrets", n(g(sec, "expired")) if sec else "n/a", RED if sec and g(sec, "expired") else GRN, "%s expire within 90 days" % n(g(sec, "expiring90d")) if sec else ""),
                     kpi("Apps with app-only access", n(g(perm, "appsAppOnly")) if perm else "n/a", AMB, "request an application permission")])
        sec_rows = [("Client secrets", g(sec, "secrets")), ("Expired", g(sec, "expired")), ("Expiring within 90 days", g(sec, "expiring90d")), ("Valid for more than 730 days", g(sec, "longLived"))] if sec else []
        sections.append(("App registrations", "Credential hygiene and requested permissions as of %s." % last,
            "<div class='kpis two'>%s</div>%s" % (k, kv("Registrations", "", [("App registrations", g(ap_, "apps")), ("With no secret or certificate", g(ap_, "appsNoCredentials")), ("Secrets", g(ap_, "secrets")), ("Certificates", g(ap_, "certificates")), ("Multi-tenant audience", g(ap_, "multiTenant"))])
            + (kv("Client secret tests", "Dates are tested against the end of the run window.", sec_rows) if sec else na("Client secret tests", st("app registration client secrets")[1])))))
    else:
        sections.append(("App registrations", "", na("App registrations", st("office365Application")[1])))

    # 6 enterprise
    if ent:
        k = "".join([kpi("Enterprise apps", n(g(ent, "total")), NAVY, "%s enabled, %s disabled" % (n(g(ent, "enabled")), n(g(ent, "disabled")))),
                     kpi("Third party", n(g(ent, "thirdParty")), AMB, "other publishers"),
                     kpi("Microsoft-owned", n(g(ent, "microsoftOwned")), GRY, ""),
                     kpi("With credentials", n(g(ent, "withCredentials")), BLU, "secret or certificate")])
        sections.append(("Enterprise applications", "Service principals as of %s." % last, "<div class='kpis two'>%s</div>%s" % (k,
            kv("Enterprise application counts", "", [("Total", g(ent, "total")), ("Microsoft-owned", g(ent, "microsoftOwned")), ("Registered in this tenant", g(ent, "registeredHere")), ("Third party", g(ent, "thirdParty")), ("User assignment required", g(ent, "assignmentRequired")), ("With credentials", g(ent, "withCredentials"))]))))
    else:
        sections.append(("Enterprise applications", "", na("Enterprise applications", st("office365InstalledApp")[1])))

    # 7 groups
    if grp:
        k = "".join([kpi("Groups", n(g(grp, "groups")), NAVY, "%s security, %s Microsoft 365" % (n(g(grp, "securityEnabled")), n(g(grp, "microsoft365")))),
                     kpi("Public groups", n(g(grp, "publicGroups")), AMB, ""),
                     kpi("Role-assignable", n(g(grp, "roleAssignable")), BLU, "can hold directory roles"),
                     kpi("Empty groups", n(g(grp, "emptyGroups")), GRY, "no members")])
        sections.append(("Groups", "Group shape as of %s. Names and members are not collected." % last, "<div class='kpis two'>%s</div>%s" % (k,
            kv("Group counts", "Memberships are entries, not people.", [("Groups", g(grp, "groups")), ("Security-enabled", g(grp, "securityEnabled")), ("Microsoft 365", g(grp, "microsoft365")), ("Dynamic membership", g(grp, "dynamicGroups")), ("Public", g(grp, "publicGroups")), ("Role-assignable", g(grp, "roleAssignable")), ("Empty", g(grp, "emptyGroups")), ("Membership entries", g(grp, "membersTotal"))]))))
    else:
        sections.append(("Groups", "", na("Groups", st("office365Group")[1])))

    # 8 licenses
    perlic = collections.Counter()
    for r in lic:
        for nm in [x.strip() for x in str(r.get("licenses") or "").split(", ") if x.strip()]:
            perlic[nm] += 1
    if st("licensed users")[0] != "ok":
        body8 = na("Licensed users", st("licensed users")[1])
    else:
        body8 = gtable("Users per license", "Licensed users (enabled or not) holding each license. A user with several licenses counts under each.", ["License", "Users"], [[k_, v] for k_, v in perlic.most_common()], 40)
        if not a.no_actors:
            rows = [[r.get("userPrincipalName") or "", r.get("displayName") or "", r.get("userType") or "", "Enabled" if truthy(r.get("accountEnabled")) else "Disabled", num(r.get("licenseCount")), r.get("licenses") or ""] for r in lic]
            body8 += gtable("Licensed users", "%s users hold at least one license." % n(len(lic)), ["User", "Name", "Type", "Account", "Licenses", "License names"], rows, a.top, [23, 14, 9, 10, 8, 36])
    sections.append(("Licenses", "Licensed users as of %s: %s users, %s distinct licenses." % (last, n(len(lic)), n(len(perlic))), body8))

    # 9 change and trends (only when two or more days are archived)
    if len(in_period) > 1:
        TR = [("Users", "o365res_users", "users", NAVY, 1), ("Enabled users without MFA", "o365res_users", "enabledNoMfa", RED, -1),
              ("Administrators without MFA", "o365res_users", "adminsNoMfa", RED, -1), ("Administrators", "o365res_users", "admins", BLU, 0),
              ("Non-compliant devices", "o365res_devices", "nonCompliant", AMB, -1), ("Expired client secrets", "o365res_app_secrets", "expired", RED, -1),
              ("App registrations", "o365res_apps", "apps", BLU, 0), ("Groups", "o365res_groups", "groups", NAVY, 0)]
        cards, drows = [], []
        for label, tbl, col, color, good in TR:
            ser = {d: g(one(done[d], tbl), col) for d in in_period if one(done[d], tbl) is not None}
            if len(ser) < 2:
                continue
            f, l_ = ser[in_period[0]] if in_period[0] in ser else ser[sorted(ser)[0]], ser[sorted(ser)[-1]]
            dl = l_ - f
            drows.append([label, f, l_, ("+" if dl > 0 else "") + n(dl), ("+" if dl > 0 else "") + pct(dl, f) if f else "n/a"])
            arrow = "no change" if dl == 0 else ("%s%s since %s" % ("up " if dl > 0 else "down ", n(abs(dl)), sorted(ser)[0]))
            cards.append("<div class='card' style='--c:%s'><b>%s: %s <span class='mut'>(%s)</span></b>%s</div>" % (color, E(label), n(l_), E(arrow), bars(ser, expected[-60:], color, label)))
        body9 = "<div class='cards'>%s</div>%s" % ("".join(cards), gtable("First to last archived day", "Change from %s to %s. A drop in a risk measure is an improvement; the directory is a state, so days are compared, never added." % (in_period[0], last),
                  ["Measure", "First day", "Last day", "Change", "Change %"], drows, 99))
        sections.append(("Trends over the period", "The directory as each archived day saw it (%d days)." % len(in_period), body9))
        rows = []
        for d in in_period:
            t = done[d]
            uu, d2, s2, g2 = one(t, "o365res_users"), one(t, "o365res_devices"), one(t, "o365res_app_secrets"), one(t, "o365res_groups")
            rows.append([d, g(uu, "users"), g(uu, "admins"), g(uu, "enabledNoMfa"), g(uu, "adminsNoMfa"), g(d2, "nonCompliant"), g(s2, "expired"), g(g2, "groups")])
        sections.append(("Archived days", "One row per archived day.", gtable("Archived days", "", ["Day", "Users", "Admins", "No MFA", "Admins no MFA", "Non-compl. devices", "Expired secrets", "Groups"], rows[-45:], 99)))

    # coverage
    cov = ["<div class='panel'>Archived days in period: <b>%d of %d</b>. Report date (latest archived day): <b>%s</b>.</div>" % (len(in_period), len(expected), last)]
    if gaps:
        cov.append("<div class='gap'>Missing days: %s. A gap is not an unchanged directory. A backfill records the directory as it is now, not as it was on that day.</div>" % ", ".join("%s (%s)" % g_ for g_ in gaps[:20]) + ("" if len(gaps) <= 20 else " and %d more" % (len(gaps) - 20)))
    if len(hashes) > 1:
        cov.append("<div class='gap'>The report script changed during the period (%d versions): compare days with care.</div>" % len(hashes))
    rows = []
    for tbl, src, title in SCANS:
        s = L["status"].get(src, ("ok", "" if L["tables"].get(tbl) is not None else ""))
        present = tbl in L["tables"]
        rows.append([title, src, "available" if s[0] == "ok" and present else ("not available" if s[0] != "ok" else "missing from archive"), s[1][:120]])
    cov.append(gtable("Scans", "From the sources table of the latest archived day.", ["Scan", "Source", "State", "Detail"], rows, 99))
    sections.append(("Coverage and limits", "", "".join(cov) + "<ul>%s</ul>" % "".join("<li>%s</li>" % E(x) for x in LIMITS)))

    # html
    title = "%s Microsoft 365 Resource Inventory" % (a.tenant or "Tenant")
    chips = "".join("<span class='chip'>%s</span>" % E(c) for c in [a.site, "%s to %s" % (frm, to), "state as of %s" % last, "%d of %d days archived" % (len(in_period), len(expected))] if c)
    head = "<div class='hero'><div class='wrap'><div class='eyebrow'>Microsoft 365 / Entra</div><h1>%s</h1><p>Directory facts from the archived daily snapshot: accounts, MFA, devices, Conditional Access, applications and groups.</p><div class='chips'>%s</div></div></div>" % (E(title), chips)
    parts = []
    for i, (h, sub, body) in enumerate(sections, 1):
        parts.append("<h2><span class='n'>%d</span>%s</h2><p class='sub'>%s</p>%s" % (i, E(h), E(sub), body))
    open(a.out, "w").write("<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>%s</style></head><body>%s<div class='wrap'>%s<p class='mut' style='margin-top:30px'>Generated from the report archive only. Generated %s.</p></div></body></html>" % (E(title), STYLE, head, "".join(parts), dt.date.today().isoformat()))

    if a.interactive:
        build_interactive(a.interactive, a, done, in_period, expected, last, gaps, hashes, nc, lic, perlic, L)
        print("wrote %s (interactive)" % a.interactive)
    if a.csv:
        base = os.path.splitext(a.csv)[0]
        if not a.no_actors:
            with open(a.csv, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["userPrincipalName", "displayName", "userType", "finding", "isAdmin", "roles", "asOf"])
                for r in sorted(nc, key=lambda r: (not truthy(r.get("isAdmin")), str(r.get("userPrincipalName")).lower())):
                    w.writerow([r.get("userPrincipalName"), r.get("displayName"), r.get("userType"), r.get("finding"), truthy(r.get("isAdmin")), roles_text(r.get("roles")), last])
            with open(base + "_licensed.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["userPrincipalName", "displayName", "userType", "accountEnabled", "licenseCount", "licenses", "asOf"])
                for r in lic:
                    w.writerow([r.get("userPrincipalName"), r.get("displayName"), r.get("userType"), r.get("accountEnabled"), r.get("licenseCount"), r.get("licenses"), last])
        with open(base + "_summary.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["table", "measure", "value", "asOf"])
            for tbl, _, _ in SCANS[:8]:
                for r in L["tables"].get(tbl) or []:
                    for k_, v in r.items():
                        if k_ not in ("asOf",) and not isinstance(v, (dict, list)):
                            w.writerow([tbl, (r.get("state") + ":" if r.get("state") and k_ != "state" else "") + k_, v, last])
    if a.summary_json:
        json.dump({"tenant": a.tenant, "from": frm, "to": to, "asOf": last, "daysArchived": len(in_period), "daysExpected": len(expected), "gapDays": [d for d, _ in gaps],
                   "scriptHashes": hashes, "users": u, "devices": dv, "conditionalAccess": ca, "apps": ap_, "secrets": sec, "appOnly": perm, "enterprise": ent, "groups": grp,
                   "usersWithoutMfa": len(nc), "licensedUsers": len(lic), "usersPerLicense": dict(perlic), "noActors": a.no_actors}, open(a.summary_json, "w"), indent=1, default=str)
    print("wrote %s (as of %s, %d of %d days)" % (a.out, last, len(in_period), len(expected)))


if __name__ == "__main__":
    main()
