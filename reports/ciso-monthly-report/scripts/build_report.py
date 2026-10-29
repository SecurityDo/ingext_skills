#!/usr/bin/env python3
"""Render the CISO Monthly SOC (M-SOC) report for one tenant and one month.

Every figure, table row count, chart and score is computed here from the saved tool results
in --evidence-dir. The analyst writes only the narrative (narrative.json); it may refer to
computed values with {{name}} placeholders, and any other number it contains is listed as a
warning so it can be checked against the evidence.

  build_report.py --evidence-dir DIR --narrative narrative.json --tenant acme --tenant-name "Example Corp" \
                  --month 2026-09 --out report.html [--prepared YYYY-MM-DD] [--logo assets/fluency_logo.svg]

Evidence files in DIR (see references/evidence.md):
  cases.json          behavior_summary_search, riskScore >= 3000, the month (one result, or an array of pages)
  cases_prev.json     the same for the prior month (optional; without it the deltas show as GAP)
  events.json         prom_query: sum by (index) (increase(lake_ingress_count[<days>d])) at the start of the next month (optional)
  events_prev.json    the same for the prior month (optional; the metrics store may not reach back that far)
  health.json         from the health-status-report skill: installed-application status and resource-feed ages (optional)
  admins.json         {"checked": [upn], "admins": {upn: [role]}} from get_azure_user_record (optional)
  compliance_summary.json   written by compliance-assessment's build_report.py --summary-json (optional)
Only cases.json is required. A missing optional file turns the sections that need it into a visible
GAP; nothing is filled in.
"""
import argparse, calendar, collections, datetime, hashlib, html, json, os, re, sys

E = html.escape
MONO = "ui-monospace,Menlo,Consolas,monospace"
SANS = "-apple-system,'Segoe UI',Inter,Helvetica,Arial,sans-serif"
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
RAG = {"Green": GRN, "Amber": AMB, "Red": RED}
TREND = {"improving": "↑ Improving", "stable": "→ Stable", "declining": "↓ Declining"}
MIN_WORDS = 150
ASSISTANT = "AI-Assistant"
# keyword -> category for the five rolling-trend categories (matched against behaviorRules text)
CATEGORIES = [
    ("Threat & Attack", ("phish", "malware", "brute", "lateral", "exploit", "threat_intelligence", "threat_management", "risky", "highrisk", "high_risk", "spray", "unauthorized_api", "root_console_login_failed")),
    ("Endpoint", ("sentinelone", "falcon", "defender_endpoint", "msdefender:endpoint", "edr_", "_edr", "malware_protection")),
    ("Identity & Access", ("userloggedin", "authentication_method", "consent", "role_assignment", "add_member", "user_added", "user_disabled", "user_updated", "mfa", "signin", "sign-in", "service_principal", "update_application", "addpolicy", "updatepolicy", "mimecast_audit_login", "guest", "okta", "console_login", "login_without", "credentials_updated", "iam_", "root_console")),
    ("Network & Perimeter", ("fortigate", "firewall", "vpn", "dns", "zscaler", "netskope", "meraki", "network", "security_group", "security_configuration")),
    ("Vulnerability", ("vulnerab", "qualys", "cve", "tenable")),
]

# House design: navy hero, KPI cards, numbered section headings, rounded tables, pills, print rules. All classes; no external assets.
CSS = """:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#2563eb;--red:#B91C1C;--amb:#B45309;--grn:#15803D}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,'Segoe UI',Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:34px 0 76px}
.hero-row{display:flex;align-items:center;justify-content:space-between;gap:24px}
.hero-id{display:flex;align-items:center;gap:18px}
.logo{background:#fff;border-radius:12px;padding:8px;display:flex;flex:none}.logo svg{display:block;width:52px;height:52px}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em;color:#fff}
.hero p{margin:0;color:#c7d4ee;font-size:14px}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}.chip b{color:#fff}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-top:-50px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 14px 12px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:28px;line-height:1.1;color:var(--c)}.kpi span{display:block;color:var(--mut);font-size:11px;font-weight:600;margin-top:5px;line-height:1.35}
.posture{display:flex;flex-wrap:wrap;align-items:stretch;margin-top:16px;background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(15,26,51,.04)}
.posture>div{display:flex;align-items:center;gap:12px;padding:14px 20px}
.posture .k{font:700 11px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.14em;color:var(--mut)}
.posture .big{font-size:20px;font-weight:800;color:var(--c)}
.posture .pill-rag{background:var(--c);color:#fff;border-radius:999px;padding:4px 16px;font-size:16px;font-weight:800;letter-spacing:.04em}
.posture .sep{border-left:1px solid var(--line)}
.posture .facts{flex:1;flex-wrap:wrap;gap:6px 26px;color:#475569;font-size:13.5px}
.chap{margin:42px 0 0;padding:16px 22px;background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);border-radius:12px;display:flex;align-items:baseline;gap:18px;color:#fff}
.chap .cn{font:600 12px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.16em;color:#9db4e0}.chap .ct{font-size:21px;font-weight:700}
section{padding:6px 0 4px}
.sec{display:flex;align-items:center;gap:10px;margin:30px 0 10px;flex-wrap:wrap}
.sec h2,h2.plain{margin:0;font-size:19px;font-weight:700;color:var(--navy)}
.sec .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:3px 9px;font-weight:600;font-family:ui-monospace,Menlo,Consolas,monospace}
.flag{font:600 10.5px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em;color:#92400e;background:#fffbeb;border:1px solid #fcd34d;border-radius:999px;padding:5px 11px}
p.para{font-size:14.5px;line-height:1.7;color:#334155;margin:0 0 14px;max-width:880px}
p.lead{font-size:14.5px;line-height:1.7;color:var(--mut);margin:18px 0 0;max-width:880px}
.finding{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:12px 18px;margin:10px 0;max-width:880px;font-size:14px;line-height:1.6;color:#1e3a8a}
.caveat{border-left:4px solid var(--amb);background:#fffbeb;border-radius:0 10px 10px 0;padding:12px 18px;margin:12px 0;max-width:880px}.caveat p{margin:0;font-size:13.5px;line-height:1.65;color:#78350f}
.gap{margin:12px 0;font:400 12px/1.6 ui-monospace,Menlo,Consolas,monospace;color:var(--mut);max-width:880px}
.gap span{display:inline-block;border:1px solid #cbd5e1;background:#f8fafc;border-radius:999px;padding:1px 9px;font-weight:600;margin-right:6px}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin:10px 0 18px}
table{border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed;font-size:12.5px}
th{background:#f1f5f9;color:#475569;text-align:left;font:600 10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;text-transform:uppercase;letter-spacing:.07em;padding:10px 10px;border-bottom:1px solid var(--line);position:sticky;top:0}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top;line-height:1.5;color:#334155;overflow-wrap:anywhere}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
td:first-child{border-left:4px solid var(--navy);font-weight:600;color:var(--navy)}
tr.hl td{background:#fffbeb}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
.fig{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin:14px 0;box-shadow:0 1px 4px rgba(15,26,51,.04)}
.fig .ft{font:600 11px/1.4 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);margin-bottom:12px}
.fig svg{display:block;max-width:100%;height:auto}
.fig p{margin:10px 0 0;font-size:12px;color:var(--mut)}
.dec{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:20px 0;overflow:hidden}
.dec .dh{padding:11px 20px;background:var(--navy);font:600 11px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.14em;color:#fff}
.dec .cards{display:grid;gap:12px;padding:14px}
.dec .card{border:1px solid var(--line);border-left:4px solid var(--red);border-radius:10px;padding:12px 14px;display:flex;gap:12px;background:#fff}
.dec .card b{font:700 20px/1 ui-monospace,Menlo,Consolas,monospace;color:var(--red)}.dec .card p{margin:0;font-size:14px;line-height:1.6}
.note{font-size:13px;color:#475569;margin:0 0 8px;max-width:880px}
h3{font-size:15px;color:var(--navy);margin:18px 0 8px}
.foot{margin-top:36px;padding:16px 0 40px;border-top:1px solid var(--line);color:var(--mut);font-size:12px}
@media (max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}.hero-row{flex-wrap:wrap}}
@media (max-width:620px){.kpis{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}.wrap{padding:0 16px}.dec .cards{grid-template-columns:1fr!important}}
@media print{.kpis{margin-top:16px}body{background:#fff;font-size:12.5px}.hero,.chap,.kpi,.pill,.pill-rag,.posture,.dec .dh,.finding,.caveat,.sec .n,.flag,.gap span,.fig,tr.hl td,th,td:first-child,.logo{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.kpi,.fig,.card,.finding,.caveat,.dec,.posture{break-inside:avoid}.chap,.sec,h3{break-after:avoid}th{position:static}.kpi,.fig,.posture,.tw{box-shadow:none}.hero{padding-bottom:70px}}
"""


def load(d, name, required=False):
    p = os.path.join(d, name)
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        if required:
            sys.exit("%s is missing or not JSON (%s). Save the tool result under that name; see references/evidence.md" % (name, e))
        return None


def hm(sec):
    if sec is None:
        return "n/a"
    sec = int(sec)
    return "%dh %02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm" % (sec // 60)


def hours(sec):
    return sec / 3600.0


def pct_change(a, b):
    return "n/a" if not b else "%+.0f%%" % ((a - b) * 100.0 / b)


def signed(a, b):
    return "+%d" % (a - b) if a > b else str(a - b)


def band(score):
    return ("Critical", RED) if score >= 18 else ("High", "#C2410C") if score >= 11 else ("Medium", AMB) if score >= 6 else ("Low", GRN)


def pill(t, col):
    return '<span class="pill" style="--c:%s">%s</span>' % (col, E(t))


# ---------- html helpers ----------
def chapter(n, title):
    return '<div class="chap"><span class="cn">CHAPTER %d</span><span class="ct">%s</span></div><section>' % (n, E(title))


def sec(num, title, flag=""):
    f = ('<span class="flag">%s</span>' % E(flag)) if flag else ""
    return '<div class="sec"><span class="n">%02d</span><h2>%s</h2>%s</div>' % (num, E(title), f)


def para(t):
    return '<p class="para">%s</p>' % t


def lead(t):
    return '<p class="lead">%s</p>' % t


def callouts(items):
    return "".join('<div class="finding"><strong>Finding —</strong> %s</div>' % t for t in items)


def gap(t, kind="GAP"):
    return '<p class="gap"><span>%s</span>%s</p>' % (kind, t)


def table(heads, rows, widths, hl=None):
    th = "".join('<th style="width:%s">%s</th>' % (widths[i], E(h)) for i, h in enumerate(heads))
    body = ""
    for i, r in enumerate(rows):
        cls = ' class="hl"' if hl and hl.get(i) else ""
        body += "<tr%s>%s</tr>" % (cls, "".join("<td>%s</td>" % c for c in r))
    return '<div class="tw"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, body)


def figure(title, svg, note=""):
    return '<div class="fig"><div class="ft">%s</div>%s%s</div>' % (E(title), svg, ("<p>%s</p>" % note) if note else "")


def hbars(data, width=760, label_w=250, color=NAVY, fmt=str):
    mx = max([r[1] for r in data] + [1])
    out = '<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (width, 26 * len(data) + 4)
    for i, r in enumerate(data):
        col = r[2] if len(r) > 2 else color
        y, bw = i * 26, (width - label_w - 70) * r[1] / mx
        out += ('<text x="0" y="%d" font-size="12" fill="#1f2937" font-family="%s">%s</text><rect x="%d" y="%d" width="%d" height="16" fill="#eef2f7" rx="4"/><rect x="%d" y="%d" width="%.1f" height="16" fill="%s" rx="4"/>'
                '<text x="%.1f" y="%d" font-size="12" fill="#1f2937" font-family="%s">%s</text>') % (y + 17, SANS, E(r[0]), label_w, y + 4, width - label_w - 70, label_w, y + 4, max(bw, 1), col, label_w + bw + 8, y + 17, MONO, E(fmt(r[1])))
    return out + "</svg>"


def heatmap(risks):
    cells = collections.defaultdict(list)
    for r in risks:
        cells[(r["likelihood"], r["impact"])].append(r["id"])
    svg = '<svg viewBox="0 0 520 300" width="100%" role="img">'
    for L in range(1, 6):
        for I in range(1, 6):
            x, y = 50 + (I - 1) * 92, 250 - L * 46
            svg += '<rect x="%d" y="%d" width="88" height="42" fill="%s" opacity="0.22" rx="6"/><text x="%d" y="%d" font-size="11" fill="#475569" font-family="%s" text-anchor="end">%d</text>' % (x, y, band(L * I)[1], x + 84, y + 15, MONO, L * I)
            if cells.get((L, I)):
                svg += '<text x="%d" y="%d" font-size="13" font-weight="700" fill="%s" font-family="%s" text-anchor="middle">%s</text>' % (x + 44, y + 32, NAVY, MONO, E(" ".join(cells[(L, I)])))
    return svg + '<text x="270" y="290" font-size="11" fill="#64748B" text-anchor="middle" font-family="%s">IMPACT 1 → 5</text><text x="10" y="150" font-size="11" fill="#64748B" font-family="%s" transform="rotate(-90 10 150)" text-anchor="middle">LIKELIHOOD 1 → 5</text></svg>' % (SANS, SANS)


# ---------- computation ----------
def parse_iso(t):
    try:
        txt = re.sub(r"(\.\d{6})\d+", r"\1", str(t).replace("Z", "+00:00"))
        d = datetime.datetime.fromisoformat(txt)
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def classify(case):
    rules = " ".join(case.get("behaviorRules") or []).lower()
    hits = [name for name, kws in CATEGORIES if any(k in rules for k in kws)]
    return hits[0] if hits else "Other"


def short_class(c):
    c = (c or "")
    return "Benign Positive" if c.startswith("Benign") else "False Positive" if c.startswith("False") else "True Positive" if c.startswith("True") else "Undetermined" if c.startswith("Undeterm") else "Unclassified"


def norm_cases(res):
    """Cases (the _source of each behavior summary) from one result or an array of pages; plus the reported total."""
    if res is None:
        return None, None
    pages = res if isinstance(res, list) else [res]
    cases, total = [], None
    for pg in pages:
        for d in pg.get("documents", []):
            c = dict(d.get("source") or d.get("_source") or {})
            if c:
                cases.append(c)
        total = pg.get("total", total)
    return cases, total


def ms(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def pctile(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(p / 100.0 * len(v) + 0.5)) - 1))]


def detection_ms(c):
    """When the incident was detected (incidentDetectionTime), in epoch ms, or None. There is no fallback: the summary's
    own `from` is a two-minute bucket label of the first event and is not comparable."""
    t = parse_iso(c.get("incidentDetectionTime"))
    if t is not None:
        return int(t.timestamp() * 1000), True
    return None, False


def case_times(c):
    """Seconds to first response (any comment), to first human response, and to close, all from incidentDetectionTime; and whether the assistant closed the case."""
    start, _ = detection_ms(c)
    cm = sorted(((ms(x.get("createdOn")), x.get("username") or "", x.get("actions") or []) for x in c.get("comments") or [] if ms(x.get("createdOn")) is not None), key=lambda t: t[0])
    first = (max(0, cm[0][0] - start) / 1000.0) if cm and start is not None else None
    human = next((max(0, t[0] - start) / 1000.0 for t in cm if t[1] != ASSISTANT), None) if start is not None else None
    close, by_ai = None, None
    if c.get("status") in ("closed", "resolved"):
        if start is not None:
            end = max([ms(c.get("updatedOn")) or 0] + [t[0] for t in cm])
            close = max(0, end - start) / 1000.0
        closing = [t for t in cm if any("closed" in str(a).lower() and "status" in str(a).lower() for a in t[2])]
        by_ai = bool(closing) and closing[-1][1] == ASSISTANT
    return first, human, close, by_ai


def case_metrics(cases):
    m = {"cases": len(cases), "unacked": sum(1 for c in cases if c.get("status") == "new")}
    closed = [c for c in cases if c.get("status") in ("closed", "resolved")]
    m["closed"] = len(closed)
    cl = collections.Counter(short_class(c.get("classification")) for c in closed)
    m.update(tp=cl.get("True Positive", 0), fp=cl.get("False Positive", 0), bp=cl.get("Benign Positive", 0), und=cl.get("Undetermined", 0), unclassified=cl.get("Unclassified", 0))
    t = [case_times(c) for c in cases]
    firsts, humans = [x[0] for x in t if x[0] is not None], [x[1] for x in t if x[1] is not None]
    closes = [x[2] for x in t if x[2] is not None]
    m["no_detection_time"] = sum(1 for c in cases if not detection_ms(c)[1])
    has_ai = lambda c: any((cm.get("username") or "") == ASSISTANT for cm in (c.get("comments") or []))
    m.update(ai_processed=sum(1 for c in cases if has_ai(c)), escalated=sum(1 for c in cases if c.get("status") == "new" and has_ai(c)),
             not_run=sum(1 for c in cases if c.get("status") == "new" and not has_ai(c)))
    m.update(mttr_p50=pctile(firsts, 50), mttr_p90=pctile(firsts, 90), mttr_samples=len(firsts), human_p50=pctile(humans, 50), human_p90=pctile(humans, 90),
             mttc_p50=pctile(closes, 50), mttc_p90=pctile(closes, 90), mttc_samples=len(closes), closed_by_ai=sum(1 for x in t if x[3]), no_human=sum(1 for c in cases if not any((cm.get("username") or "") != ASSISTANT for cm in (c.get("comments") or []))))
    m["human_n"] = len(cases) - m["no_human"]
    return m


def shape_id(c):
    return hashlib.md5("|".join(sorted(c.get("behaviorRules") or [])).encode()).hexdigest()[:8]


def events_ingested(res):
    """Total and per-index datalake ingest as a prom_query result returns it, without the behavior index (the engine's own output, not ingested events)."""
    if not res or not res.get("series"):
        return None
    by = {}
    for sr in res["series"]:
        idx = (sr.get("metric") or {}).get("index", "all")
        pts = sr.get("points") or []
        if pts:
            by[idx] = int(round(float(pts[-1]["value"])))
    by = {k: v for k, v in by.items() if "behavior" not in k.lower()}
    return {"total": sum(by.values()), "by_index": sorted(by.items(), key=lambda kv: -kv[1])}


def compute(ev, month):
    y, mo = map(int, month.split("-"))
    v = {"year": y, "month": mo, "month_name": calendar.month_name[mo], "last_day": calendar.monthrange(y, mo)[1]}
    cases, total = norm_cases(ev["cases"])
    if not cases:
        sys.exit("cases.json holds no behavior summaries; a month with no flagged case needs no report from this skill")
    if total is not None and total != len(cases) and total < 10000:
        warnings.append("cases.json holds %d of %s cases; page with offset and merge the results into one array" % (len(cases), total))
    pcases, ptotal = norm_cases(ev.get("cases_prev"))
    if pcases is not None and ptotal is not None and ptotal != len(pcases) and ptotal < 10000:
        warnings.append("cases_prev.json holds %d of %s cases; page with offset and merge" % (len(pcases), ptotal))
    for c in cases:
        c["_shape"] = shape_id(c)
    v.update(case_metrics(cases))
    evi, evp = events_ingested(ev.get("events")), events_ingested(ev.get("events_prev"))
    v["events_total"] = evi["total"] if evi else None
    v["events_by_index"] = evi["by_index"] if evi else []
    if evp:
        v["events_total_prev"] = evp["total"]
    v["tickets"] = len(cases)
    if v["no_detection_time"]:
        warnings.append("%d of %d cases have no incidentDetectionTime and are left out of the response and close times" % (v["no_detection_time"], len(cases)))
    v["case_rows"] = cases
    v["days"] = collections.Counter(int(str(c["dayIndex"])[-2:]) for c in cases if c.get("dayIndex"))
    v["cat_cur"] = collections.Counter(classify(c) for c in cases)
    if pcases is not None:
        pm = case_metrics(pcases)
        v.update({k + "_prev": val for k, val in pm.items()})
        if pm["no_detection_time"]:
            warnings.append("prior month: %d of %d cases have no incidentDetectionTime and are left out of its response and close times, so the month-over-month times are not like for like" % (pm["no_detection_time"], len(pcases)))
        v["cat_prev"] = collections.Counter(classify(c) for c in pcases)
        v["prev_rows"] = pcases
    else:
        v["cat_prev"] = None
    for name, _ in CATEGORIES + [("Other", ())]:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        v["cat_" + slug] = v["cat_cur"].get(name, 0)
        if v["cat_prev"] is not None:
            v["cat_prev_" + slug] = v["cat_prev"].get(name, 0)
    shapes = collections.defaultdict(lambda: {"n": 0, "rules": None, "closed": 0, "new": 0})
    for c in cases:
        sh = shapes[c["_shape"]]
        sh["n"] += 1
        sh["rules"] = ", ".join(sorted(c.get("behaviorRules") or [])) or "(no rule)"
        sh["new" if c.get("status") == "new" else "closed"] += 1
    v["shapes"] = sorted(shapes.items(), key=lambda kv: (-kv[1]["n"], kv[0]))
    known = {}
    for k, val in v.items():
        if isinstance(val, (int, float)):
            known[k] = val
    for k in list(v):
        if k.startswith(("mttr_p", "mttc_p", "human_p")) and isinstance(v.get(k), (int, float)):
            known[k + "_h"] = hours(v[k])
    return v, known


def render(ev, nar, v, args, logo):
    A = []
    P = nar.get("placeholders", {})
    tenant, tname, month = args.tenant, args.tenant_name, args.month
    mname = "%s %d" % (v["month_name"], v["year"])
    prep = args.prepared or datetime.date.today().isoformat()

    def sub(t):
        def f(m):
            k = m.group(1)
            if k in P:
                return str(P[k])
            if k in v and isinstance(v[k], (int, float)):
                return hm(v[k]) if k.startswith(("mttr", "mttc")) and not k.endswith("_h") and not k.endswith("samples") else str(v[k])
            if k.endswith("_h") and k[:-2] in v:
                return "%.1f hours" % hours(v[k[:-2]])
            warnings.append("unknown placeholder {{%s}}" % k)
            return m.group(0)
        return re.sub(r"\{\{(\w+)\}\}", f, t)

    def paras(lst):
        return "".join(para(sub(x)) for x in lst)

    rag, trend = nar["rag"], nar["trend"]
    A.append('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s</style></head><body>' % (E("CISO Monthly SOC Report - %s - %s" % (tname, mname)), CSS))
    # masthead
    A.append('<header class="hero"><div class="wrap"><div class="hero-row"><div class="hero-id"><div class="logo">%s</div><div><div class="eyebrow">Managed SOC · Monthly Report</div><h1>CISO Monthly SOC Report</h1><p>%s — %s</p></div></div></div>'
             '<div class="chips"><span class="chip">Tenant <b>%s</b></span><span class="chip">1–%d %s %d (UTC)</span><span class="chip">Prepared %s</span><span class="chip">Read-only telemetry</span></div></div></header><main class="wrap">'
             % (logo, E(tname), E(mname), E(tenant), v["last_day"], v["month_name"], v["year"], E(prep)))

    def kpi(val, label, c=NAVY):
        return '<div class="kpi" style="--c:%s"><b>%s</b><span>%s</span></div>' % (c, val, label)
    A.append('<div class="kpis">%s</div>' % "".join([
        kpi(v["cases"], "Cases flagged (riskScore ≥ 3000)"), kpi(v["closed"], "Closed", GRN), kpi(v["unacked"], "Unacknowledged", RED),
        kpi(hm(v["mttr_p50"]), "Median time to first response", BLU), kpi(hm(v["mttc_p50"]), "Median time to close", BLU), kpi(v["tp"], "True positives (of %d closed)" % v["closed"])]))
    col = RAG[rag]
    A.append('<div class="posture" style="--c:%s"><div><span class="k">POSTURE</span><span class="pill-rag">%s</span></div>'
             '<div class="sep"><span class="k">TREND</span><span class="big" style="font-size:16px">%s</span></div>'
             '<div class="facts sep"><span><strong>%d</strong> cases reviewed</span><span><strong style="color:%s">%d</strong> unacknowledged</span><span><strong>%d</strong> true positives</span></div></div>'
             % (col, rag.upper(), TREND[trend], v["cases"], RED, v["unacked"], v["tp"]))

    # chapter 1
    A.append(chapter(1, "Where Things Stand") + sec(1, "Executive Summary", "%s · %s" % (rag.upper(), TREND[trend].upper())))
    A.append(paras(nar["exec_summary"]))
    dec = nar["decisions"][:2]
    A.append('<div class="dec"><div class="dh">%s</div><div class="cards" style="grid-template-columns:%s">%s</div></div>'
             % ("TWO DECISIONS FOR LEADERSHIP" if len(dec) == 2 else "DECISION FOR LEADERSHIP", "1fr 1fr" if len(dec) == 2 else "1fr",
                "".join('<div class="card"><b>%d</b><p>%s</p></div>' % (i + 1, sub(d)) for i, d in enumerate(dec))))
    if nar.get("caveat"):
        A.append('<div class="caveat"><p><strong>Caveat —</strong> %s</p></div>' % sub(nar["caveat"]))
    A.append("</section>")

    def chap(n, title):
        return chapter(n, title)

    def analysis(ch):
        c = nar["chapters"][str(ch)]
        words = len(re.sub(r"<[^>]+>", " ", " ".join(sub(x) for x in c["analysis"])).split())
        if words < MIN_WORDS:
            warnings.append("chapter %d analysis has %d words, the contract needs at least %d" % (ch, words, MIN_WORDS))
        if not 1 <= len(c["callouts"]) <= 3:
            warnings.append("chapter %d needs 1-3 callouts, has %d" % (ch, len(c["callouts"])))
        return c

    # chapter 2
    c2 = analysis(2)
    A.append(chap(2, "What Happened This Month") + lead(sub(c2["intro"])) + sec(2, "Security Events Overview"))
    pv = "cases_prev" in v
    evp = v.get("events_total_prev")
    rows = [["Events written to the datalake",
             ("%s" % "{:,}".format(v["events_total"])) if v["events_total"] is not None else "[GAP]", ("{:,}".format(evp)) if evp is not None else "[GAP]",
             ("%s (%s)" % (signed(v["events_total"], evp), pct_change(v["events_total"], evp))) if (evp is not None and v["events_total"] is not None) else "[GAP]"]]
    rows.append(["Tickets flagged for review (score 3,000 or more)", "<b>%d</b>" % v["cases"], str(v["cases_prev"]) if pv else "[GAP]", ("%s (%s)" % (signed(v["cases"], v["cases_prev"]), pct_change(v["cases"], v["cases_prev"]))) if pv else "[GAP]"])
    for lab, k in (("Processed by the AI assistant", "ai_processed"), ("Closed", "closed"), ("Escalated: still new after the AI ran", "escalated"), ("Not yet run by the AI (still new)", "not_run"),
                   ("True positive (of closed)", "tp"), ("False positive (of closed)", "fp"), ("Benign positive (of closed)", "bp")):
        rows.append([lab, str(v[k]), str(v[k + "_prev"]) if pv else "[GAP]", signed(v[k], v[k + "_prev"]) if pv else "[GAP]"])
    A.append(table(["Measure", mname.split()[0], "Prior month", "Change"], rows, ["46%", "18%", "18%", "18%"], {3: 1, 5: 1}))
    funnel = ([("Events written to the datalake", v["events_total"], GRY)] if v["events_total"] is not None else []) + [("Tickets flagged (3,000 or more)", v["cases"], NAVY), ("Processed by the AI assistant", v["ai_processed"], NAVY), ("Closed", v["closed"], GRN), ("Escalated: still new after the AI ran", v["escalated"], RED)]
    A.append(figure("From events to escalated tickets, %s" % mname, hbars(funnel, label_w=290, fmt=lambda x: "{:,}".format(x)),
                    "Tickets below a score of 3,000 are not counted. An escalated ticket is one still new after the AI assistant ran on it. Events are the lake_ingress_count values by index as the metric returns them, without the behavior index; an event written to more than one index appears in each."))
    A.append(figure("Cases by day, %s" % mname, hbars([("%s %02d" % (v["month_name"][:3], d), n) for d, n in sorted(v["days"].items())], label_w=70), "Days with no flagged case are omitted. The day is the case's dayIndex."))
    A.append(paras(c2["analysis"]) + callouts([sub(x) for x in c2["callouts"]]))
    A.append(sec(3, "Rolling Trends", "PARTIAL" if not v["cat_prev"] else ""))
    trows = []
    for name, _ in CATEGORIES:
        n = v["cat_cur"].get(name, 0)
        ex = [c for c in v["case_rows"] if classify(c) == name][:2]
        evid = ("%d case(s); e.g. %s" % (n, "; ".join(E(c["key"]) + " (" + E(str(c["dayIndex"])) + ")" for c in ex))) if n else "No cases in this category"
        dl = "%s (was %d)" % (signed(n, v["cat_prev"].get(name, 0)), v["cat_prev"].get(name, 0)) if v["cat_prev"] is not None else "[GAP]"
        trows.append([E(name).replace("&amp;", "&amp;"), evid, dl, sub(nar.get("trend_notes", {}).get(name, "—"))])
    other = v["cat_cur"].get("Other", 0)
    if other:
        trows.append(["Other", "%d case(s) matched no category" % other, "[GAP]" if v["cat_prev"] is None else "—", "—"])
    A.append(table(["Category", "%s evidence" % v["month_name"], "vs prior month", "Narrative"], trows, ["17%", "36%", "14%", "33%"]))
    if v["cat_prev"] is None:
        A.append(gap("Prior-month category counts need the prior month's case list (cases_prev.json). Deltas are marked GAP until it is supplied.", "PARTIAL"))
    A.append("</section>")

    # chapter 3
    c3 = analysis(3)
    A.append(chap(3, "What The Patterns Tell Us") + lead(sub(c3["intro"])) + sec(4, "Repeat Offenders"))
    cnt_cur = collections.Counter(c.get("key") for c in v["case_rows"])
    cnt_prev = collections.Counter(c.get("key") for c in v.get("prev_rows", [])) if pv else None
    adm = ev.get("admins")
    admins = {k.lower(): v for k, v in (adm or {}).get("admins", {}).items()}
    checked = {k.lower() for k in (adm or {}).get("checked", [])} | set(admins)
    cf = (ev.get("compliance") or {}).get("facts") or {}
    if cf.get("directory_users"):               # the user dump covers every directory account
        for k, roles in (cf.get("admins") or {}).items():
            admins.setdefault(k.lower(), roles)
        checked |= {u.lower() for u in cf["directory_users"]} | set(admins)
    actors = sorted([k for k, n in cnt_cur.items() if n >= 2], key=lambda k: (-cnt_cur[k], k))
    cohorts = {"Admin Watch": [k for k in actors if k.lower() in admins], "Repeat Offender": [k for k in actors if k.lower() in checked and k.lower() not in admins],
               "Repeat actor (admin status not checked)": [k for k in actors if k.lower() not in checked]}
    if not adm and not cf.get("directory_users"):
        A.append(gap("No administrator information was supplied (admins.json, or the user dump through compliance_summary.json), so admin accounts are not separated from other repeat actors.", "GAP"))
    why = nar.get("repeat_why", {})
    for label, keys in cohorts.items():
        if keys:
            rows = [[E(k), label, str(cnt_cur[k]), "—" if cnt_prev is None else (str(cnt_prev[k]) if cnt_prev[k] else "below threshold"), signed(cnt_cur[k], cnt_prev[k]) if cnt_prev is not None and cnt_prev[k] else "n/a", sub(why.get(k, "—"))] for k in keys]
            A.append(table(["Identifier", "Category", "This month", "Prior month", "Delta", "Why it repeats"], rows, ["27%", "13%", "9%", "14%", "7%", "30%"]))
        elif label in ("Admin Watch", "Repeat Offender") and (adm or cf.get("directory_users")):
            A.append('<p class="note"><strong>%s:</strong> none identified among the accounts checked.</p>' % label)
    if not actors:
        A.append('<p class="note">No user, host or application had two or more cases this month.</p>')
    A.append(figure("Most repeated case shapes (same rule combination), %s" % mname, hbars([(sh["rules"][:46] + ("…" if len(sh["rules"]) > 46 else ""), sh["n"]) for _, sh in v["shapes"][:7]], label_w=330)))
    A.append(paras(c3["analysis"]) + callouts([sub(x) for x in c3["callouts"]]))
    A.append(sec(5, "Root-Cause Themes", "PARTIAL"))
    A.append(table(["Theme", "Cases", "Linked users and assets", "Evidence", "Confidence"], [[E(r[0]), E(str(r[1])), E(r[2]), E(r[3]), E(r[4])] for r in nar["root_causes"]], ["23%", "8%", "29%", "28%", "12%"]))
    A.append(gap("No root-cause source exists on the connector. These themes are an analyst grouping of the top fingerprints and repeat actors; the counts can overlap.", "PARTIAL"))
    A.append("</section>")

    # chapter 4
    c4 = analysis(4)
    hl = ev.get("health")
    apps_h = hl["applications"] if hl else None
    stc = (hl or {}).get("counts", {})
    attn_apps = [r for r in (apps_h or []) if r["status"] != "running"]
    feeds = hl.get("resourceFeeds") if hl else None
    stale = [f for f in (feeds or []) if f["stale"]]
    A.append(chap(4, "What We Can And Cannot See") + lead(sub(c4["intro"])) + sec(6, "Operational Exposure"))
    if hl is None:
        cov = ["[GAP] installed-application health was not collected (health.json from the health-status-report skill)", "—"]
    else:
        parts = ["%d running" % stc.get("running", 0)] + ["%d %s" % (stc[k], k) for k in ("error", "attention", "disabled", "other") if stc.get(k)]
        cov = ["%d installed application(s): %s%s. %s" % (len(apps_h), ", ".join(parts),
                                                           (" (" + "; ".join(E("%s %s: %s" % (r["displayName"], r["status"], ", ".join(r["labels"]))) for r in attn_apps) + ")") if attn_apps else "",
                                                           "Status from the connector state only; traffic and errors were not available." if hl["mode"] == "state_only" else "Status from state, errors, 24-hour traffic and last activity."),
               "; ".join(E("%s / %s: %.0f days old%s" % (f["resource"], f["customer"], f["ageDays"] or 0, ", empty" if f["empty"] else "")) for f in stale) or ("No stale resource feeds" if feeds is not None else "[GAP] resource-feed freshness not collected")]
    rows = [["Coverage &amp; Health", cov[0], cov[1]]]
    comp_facts = (ev.get("compliance") or {}).get("facts") or {}

    def nn(x):
        return "{:,}".format(x) if isinstance(x, (int, float)) else "not collected"

    def default_exposure(key):
        """What the compliance-assessment facts support, used when the narrative gives nothing for this area."""
        f = comp_facts
        if not f:
            return None
        if key == "o365_hygiene":
            parts = []
            hy_ = f.get("hygiene")
            if hy_:
                parts.append("%s directory users (%s enabled, %s disabled, %s guests, %s with an admin role)" % (nn(hy_["users"]), nn(hy_["enabled"]), nn(hy_["disabled"]), nn(hy_["guests"]), nn(hy_["admins"])))
                if hy_.get("mfa_known"):
                    parts.append("%s of %s enabled users have registered MFA and %s of %s administrators lack it" % (nn(hy_["enabled_mfa_registered"]), nn(hy_["enabled"]), nn(hy_["admins_no_mfa"]), nn(hy_["admins"])))
            elif f.get("users"):
                parts.append("%s directory users (%s enabled)" % (nn(f["users"]["users"]), nn(f["users"]["enabled"])))
            ca_ = f.get("conditional_access")
            parts.append("%s Conditional Access policies (%s enforced, %s report-only)" % (nn(ca_["total"]), nn(ca_["enforced"]), nn(ca_["report_only"])) if ca_ else "Conditional Access policies not collected")
            dv_ = f.get("devices")
            if dv_:
                parts.append("%s of %s directory devices had no sign-in in the 90 days before the period ended" % (nn(dv_["stale_90d"]), nn(dv_["devices"])))
            ev_ = f.get("events") or {}
            if ev_.get("signin"):
                parts.append("%s of %s sign-ins failed" % (nn(ev_["signin_failed"]), nn(ev_["signin"])))
            return {"evidence": "; ".join(parts) + ".", "limit": "A snapshot of the resource tables, not the report month. MFA registration is not MFA enforcement, and password age and recent sign-in by user were not evaluated."}
        if key == "environment_changes":
            cats = f.get("audit_categories") or []
            ct_ = f.get("cloudtrail")
            if not cats and not ct_:
                return None
            parts = []
            if cats:
                parts.append("Directory audit events by category: " + "; ".join("%s %s" % (c, nn(n_)) for c, n_ in cats[:5]))
            if ct_ and ct_.get("iam_changes") is not None:
                parts.append("CloudTrail: %s IAM change events and %s root-account events" % (nn(ct_["iam_changes"]), nn(ct_.get("root_events"))))
            return {"evidence": "; ".join(parts) + ".", "limit": "Counts of audit events, not a list of changes. Who changed what needs a query on the audit table."}
        if key == "vulnerability_highlights":
            q = f.get("qualys_hosts")
            if q:
                return {"evidence": "The Qualys inventory has %s hosts." % nn(q), "limit": "Vulnerability findings were not queried; only the host inventory was counted."}
            return {"evidence": "[GAP] no vulnerability scanner data: the tenant has no Qualys host inventory.", "limit": "—"}
        return None
    for name, key in (("O365 Hygiene", "o365_hygiene"), ("Environment Changes", "environment_changes"), ("Vulnerability Highlights", "vulnerability_highlights")):
        t = nar.get("exposure", {}).get(key) or default_exposure(key)
        rows.append([name, sub(t["evidence"]) if t else "[GAP] not assessed from this evidence", sub(t["limit"]) if t else "—"])
    A.append(table(["Area", "What the evidence shows", "Limit"], rows, ["20%", "45%", "35%"], {0: 1} if (stale or attn_apps) else None))
    fig = ([("Applications running", stc.get("running", 0), GRN), ("Applications in error", stc.get("error", 0), RED), ("Applications needing attention", stc.get("attention", 0) + stc.get("disabled", 0) + stc.get("other", 0), AMB)] if hl else []) + \
          ([("Resource feeds current", len(feeds) - len(stale), GRN), ("Resource feeds stale or empty", len(stale), RED)] if feeds is not None else [])
    A.append(figure("Installed applications and resource feeds", hbars(fig or [("Nothing collected", 0, GRY)], label_w=240),
                    "Application status follows the Fluency 9 Applications page (health-status-report skill). A Running application can still feed a stale resource feed."))
    A.append(paras(c4["analysis"]) + callouts([sub(x) for x in c4["callouts"]]))
    A.append(sec(7, "Monitoring Blind Spots", "PARTIAL"))
    A.append(table(["Category", "Source", "What cannot be detected", "Remediation", "Risk"], [[E(r[0]), sub(r[1]), sub(r[2]), sub(r[3]), E(r[4])] for r in nar["blind_spots"]], ["18%", "24%", "24%", "26%", "8%"]))
    A.append("</section>")

    # chapter 5
    c5 = analysis(5)
    risks = nar["risks"]
    for r in risks:
        r["score"] = r["likelihood"] * r["impact"]
    A.append(chap(5, "What's At Risk") + lead(sub(c5["intro"])) + sec(8, "Attack Pathway Observations") + paras(nar["pathways"]))
    A.append(gap("Pathways are narrative. They are not a formal ATT&CK coverage claim; approved ATT&CK mappings are required for that.", "NOTE"))
    A.append(sec(9, "Telemetry-Derived Risk Register", "PARTIAL"))
    A.append(table(["ID", "Category", "Risk", "Description", "Business impact", "L", "I", "Score", "Band", "Mitigation"],
                   [[E(r["id"]), E(r["category"]), E(r["name"]), sub(r["description"]), sub(r["business_impact"]), str(r["likelihood"]), str(r["impact"]), "<b>%d</b>" % r["score"], pill(*band(r["score"])), sub(r["mitigation"])] for r in risks],
                   ["5%", "11%", "12%", "14%", "11%", "4%", "4%", "6%", "10%", "23%"]))
    bc = collections.Counter(band(r["score"])[0] for r in risks)
    A.append(figure("Risk register heat map (likelihood × impact)", heatmap(risks), "Likelihood and impact are analyst-entered. Bands: 1–5 Low, 6–10 Medium, 11–17 High, 18–25 Critical. This register: %s." % ", ".join("%d %s" % (n, b) for b, n in sorted(bc.items(), key=lambda x: -["Low", "Medium", "High", "Critical"].index(x[0])))))
    A.append(paras(c5["analysis"]) + callouts([sub(x) for x in c5["callouts"]]))
    A.append(gap("The connector has no telemetry-risk scoring. Likelihood and impact are analyst placeholders.", "PARTIAL"))
    A.append("</section>")

    # chapter 6
    c6 = analysis(6)
    A.append(chap(6, "How Our Defences Performed") + lead(sub(c6["intro"])) + sec(10, "Control Effectiveness", "GAP"))
    A.append(gap("Control effectiveness (controls doing the most work, exclusions, stale agents) is not available through the connector. The structure is kept; no rows are invented.", "GAP"))
    A.append(sec(11, "Response Performance"))

    def faster(a, b):
        if a is None or not b:
            return "n/a"
        ch = (a - b) * 100.0 / b
        return "%.0f%% %s" % (abs(ch), "faster" if ch < 0 else "slower")
    rows = [["Time to detect (MTTD)", "0 s", "0 s", "Not meaningful: a case is created at its first event"]]
    for lab, k in (("Time to first response (assistant or analyst), median", "mttr_p50"), ("Time to first response, slowest 10%", "mttr_p90"), ("Time to first analyst response, median", "human_p50"), ("Time to close, median", "mttc_p50"), ("Time to close, slowest 10%", "mttc_p90")):
        n_prev = v.get("mttc_samples_prev" if k.startswith("mttc") else "mttr_samples_prev", 0) if pv else 0
        usable = pv and n_prev >= 3 and v.get(k + "_prev") is not None
        rows.append([lab, hm(v.get(k)), (hm(v.get(k + "_prev")) + (" (n=%d)" % n_prev if n_prev < 3 else "")) if pv else "[GAP]", faster(v.get(k), v.get(k + "_prev")) if usable else ("[GAP] too few prior cases carry incidentDetectionTime" if pv else "[GAP]")])
    rows.append(["Cases with an analyst (not assistant) comment", "%d of %d" % (v["human_n"], v["cases"]), ("%d of %d" % (v["human_n_prev"], v["cases_prev"])) if pv else "[GAP]", "—"])
    rows.append(["Closed cases closed by the automated assistant", "%d of %d" % (v["closed_by_ai"], v["closed"]), ("%d of %d" % (v["closed_by_ai_prev"], v["closed_prev"])) if pv else "[GAP]", "—"])
    rows.append(["True positives (of closed)", "%d of %d" % (v["tp"], v["closed"]), "%d of %d" % (v["tp_prev"], v["closed_prev"]) if pv else "[GAP]", "—"])
    A.append(table(["Measure", mname.split()[0], "Prior month", "Note"], rows, ["34%", "16%", "16%", "34%"]))
    ok_prev = pv and v.get("mttr_samples_prev", 0) >= 3
    bars = [("Median first response", v["mttr_p50"] or 0, NAVY)] + ([("Prior median first response", v["mttr_p50_prev"], GRY)] if ok_prev and v.get("mttr_p50_prev") is not None else []) + ([("Slowest-10% first response", v["mttr_p90"], NAVY)] if v.get("mttr_p90") is not None else []) + ([("Prior slowest-10%", v["mttr_p90_prev"], GRY)] if ok_prev and v.get("mttr_p90_prev") is not None else [])
    A.append(figure("Time to first response", hbars(bars, label_w=230, fmt=hm)))
    A.append(paras(c6["analysis"]) + callouts([sub(x) for x in c6["callouts"]]))
    A.append(gap("Response and close times run from incidentDetectionTime and use only the cases that carry it: %d of %d this month%s." % (v["cases"] - v["no_detection_time"], v["cases"], (", %d of %d last month" % (v["cases_prev"] - v["no_detection_time_prev"], v["cases_prev"])) if pv else ""), "NOTE"))
    A.append(gap("A response here means the first comment on a case, by the automated assistant (%s) or an analyst. %d of %d cases have no analyst comment, and %d of %d closed cases were closed by the assistant; read the first-response times as the assistant's, not the SOC team's." % (ASSISTANT, v["no_human"], v["cases"], v["closed_by_ai"], v["closed"]), "NOTE"))
    A.append(sec(12, "Escalation Log", "GAP"))
    A.append(gap("The SOC escalation log is not available through the connector. No escalations are listed and none are inferred.", "GAP"))
    A.append('<div class="sec"><h2>Governance &amp; Compliance Posture</h2><span class="flag">NIST SP 800-53 REV. 5 · EVIDENCE AID</span></div>')
    comp = ev.get("compliance")
    rows_c = (comp or {}).get("rows") or []
    if not rows_c:
        A.append(gap("No compliance evidence was supplied (compliance_summary.json from the compliance-assessment skill), so no posture is shown.", "GAP"))
        comp = None
    else:
        ccount = collections.Counter(r["status"] for r in rows_c)
        A.append(figure("Control groups assessed: %d (NIST SP 800-53 Rev. 5)" % len(rows_c), hbars([("Supported", ccount.get("supported", 0), GRN), ("Partial", ccount.get("partial", 0), AMB), ("Not observed", ccount.get("not_observed", 0), GRY), ("Needs manual review", ccount.get("needs_manual_review", 0), NAVY)], label_w=170)))
        notobs = [r for r in rows_c if r["status"] == "not_observed"]
        A.append(para("The evidence <strong>supports %d, partly supports %d and did not observe %d</strong> of %d control groups; %d need customer documentation. Not observed: %s. These come from the compliance-assessment skill, which maps the tenant's own telemetry onto the controls; a control that is not observed means evidence was not collected, not that the control failed." %
                      (ccount.get("supported", 0), ccount.get("partial", 0), ccount.get("not_observed", 0), len(rows_c), ccount.get("needs_manual_review", 0), E(", ".join("%s (%s)" % (r["control"], r["title"]) for r in notobs) or "none"))))
    A.append(gap("This is an evidence analysis aid, not certification or attestation. 'Supported' means the evidence supports the control, never that the tenant is compliant. Movement against the prior month needs the compliance-assessment run for that month.", "NOTE"))
    A.append("</section>")

    # chapter 7
    c7 = analysis(7)
    A.append(chap(7, "What Needs To Happen Next") + lead(sub(c7["intro"])) + sec(13, "Actionable Remediation Plan", "PARTIAL"))
    rm = nar["remediation"]
    for r in rm:
        if not re.match(r"\d{4}-\d{2}-\d{2}$", r["due"]):
            warnings.append("remediation action '%s' needs a calendar due date (YYYY-MM-DD), got '%s'" % (r["action"][:40], r["due"]))
    A.append(table(["Action", "Owner", "Due", "Priority", "Risk", "Evidence"], [[sub(r["action"]), E(r["owner"]), E(r["due"]), pill(r["priority"], RED if r["priority"] == "High" else AMB if r["priority"] == "Medium" else GRN), E(r.get("risk", "—")), sub(r["evidence"])] for r in rm], ["32%", "14%", "11%", "9%", "6%", "28%"]))
    pc = collections.Counter(r["priority"] for r in rm)
    A.append(figure("Actions by priority", hbars([(k, pc[k], {"High": RED, "Medium": AMB, "Low": GRN}[k]) for k in ("High", "Medium", "Low") if pc[k]], label_w=100)))
    A.append(paras(c7["analysis"]) + callouts([sub(x) for x in c7["callouts"]]))
    A.append(sec(14, "Items Requiring Client Action"))
    A.append(table(["Action", "Owner", "Due", "Why it matters", "Risk"], [[sub(r["action"]), E(r["owner"]), E(r["due"]), sub(r["why"]), E(r.get("risk", "—"))] for r in nar["client_actions"]], ["38%", "16%", "11%", "27%", "8%"]))
    A.append("</section>")

    # chapter 8
    A.append(chap(8, "How We're Moving Forward") + sec(15, "What We Improved This Month", "GAP"))
    A.append(paras(nar.get("improvements", [])))
    A.append(gap("The SOC change log (tuning, new detections, log sources onboarded, playbook updates) is not available through the connector. No changes are listed and none are inferred.", "GAP"))
    A.append(sec(16, "Appendix"))
    h3 = '<h3>%s%s</h3>'
    inv = []
    if hl:
        inv.append(["Installed applications", "%d (%s mode)" % (len(apps_h), "state-only" if hl["mode"] == "state_only" else "full")])
        for r in apps_h:
            inv.append([E(str(r["application"]) + ((" (" + str(r["instance"]) + ")") if r.get("instance") else "")), E("%s%s" % (r["status"], (": " + ", ".join(r["labels"])) if r["status"] != "running" else ""))])
    for f in feeds or []:
        inv.append([E("%s / %s (resource feed)" % (f["resource"], f["customer"])), E("%s%s" % ("stale, " if f["stale"] else "current, ", ("%.1f days old" % f["ageDays"]) if f["ageDays"] is not None else "age unknown"))])
    if not inv:
        inv.append(["Inventory", "[GAP] not collected"])
    A.append(h3 % ("", "A. Log source inventory") + table(["Item", "Status"], inv, ["40%", "60%"]))
    A.append(h3 % ("", "B. Case shapes cited") + table(["Shape id", "Rules", "Cases"], [[E(h), E(sh["rules"]), str(sh["n"])] for h, sh in v["shapes"]], ["14%", "74%", "12%"]))
    A.append(h3 % ("", "C. ATT&CK") + '<p class="note">[GAP] No approved ATT&amp;CK mapping source is available through the connector, so no technique table is shown and no coverage is claimed.</p>')
    tools = "behavior_summary_search" + (", the health-status-report evaluation" if hl else "") + (", get_azure_user_record" if adm else "") + (", and the compliance-assessment evidence" if comp else "")
    A.append(h3 % ("", "D. Methodology") + '<p class="note" style="line-height:1.65">Scope: tenant %s. Window: 1–%d %s %d UTC%s. Read-only calls: %s. Sections marked GAP or PARTIAL could not be computed from these tools. A case is a cluster of events for one user, host or application on one day; a case shape is the combination of rules that fired; a benign positive is activity that looked suspicious but was expected.</p>'
             % (E(tenant), v["last_day"], v["month_name"], v["year"], "; prior month compared" if pv else "", tools))
    A.append('</section><footer class="foot">Fluency Managed SOC · %s · %s · Generated from read-only telemetry. Not a certification or attestation.</footer></main></body></html>' % (E(tname), E(mname)))
    return "".join(A)


warnings = []


def check_numbers(nar, known):
    """List numeric tokens in the narrative that are not computed values or placeholders."""
    allowed = set()
    for k, val in known.items():
        for fmt in ("%d", "%.1f", "%.0f"):
            try:
                allowed.add(fmt % val)
            except TypeError:
                pass
    allowed.update(str(x) for x in range(0, 13))
    text = json.dumps({k: nar[k] for k in nar if k not in ("risks", "remediation", "client_actions", "placeholders")}, ensure_ascii=False)
    text = re.sub(r"\{\{\w+\}\}", " ", text)
    text = re.sub(r"O365|\b(?:Office|Microsoft)\s?365\b|\b800-53\b|\bRev\.? 5\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:ci-[0-9a-f]+|[0-9a-f]{8,}|\d{4}-\d{2}-\d{2})\b", " ", text)
    odd = sorted({t for t in re.findall(r"\d[\d,.]*\d|\d", text) if t.replace(",", "") not in allowed and t not in allowed})
    if odd:
        warnings.append("numbers in the narrative that are not computed placeholders (verify each against the evidence): " + ", ".join(odd[:40]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prepared")
    ap.add_argument("--logo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fluency_logo.svg"))
    a = ap.parse_args()
    d = a.evidence_dir
    ev = {"cases": load(d, "cases.json", True), "cases_prev": load(d, "cases_prev.json"), "health": load(d, "health.json"), "events": load(d, "events.json"), "events_prev": load(d, "events_prev.json"),
          "admins": load(d, "admins.json"), "compliance": load(d, "compliance_summary.json")}
    try:
        with open(a.narrative) as f:
            nar = json.load(f)
        with open(a.logo) as f:
            logo = re.sub(r'width="\d+px" height="\d+px"', 'width="52" height="52"', f.read())
    except (OSError, ValueError) as e:
        sys.exit("cannot read narrative or logo: %s" % e)
    for k in ("rag", "trend", "exec_summary", "decisions", "chapters", "root_causes", "blind_spots", "pathways", "risks", "remediation", "client_actions"):
        if k not in nar:
            sys.exit("narrative.json lacks '%s'; see references/narrative.md" % k)
    if nar["rag"] not in RAG or nar["trend"] not in TREND:
        sys.exit("rag must be one of %s and trend one of %s" % (list(RAG), list(TREND)))
    for ch in range(2, 8):
        if str(ch) not in nar["chapters"]:
            sys.exit("narrative.json chapters lacks '%d'" % ch)
    v, known = compute(ev, a.month)
    html_doc = render(ev, nar, v, a, logo)
    check_numbers(nar, known)
    with open(a.out, "w") as f:
        f.write(html_doc)
    print("wrote %s | %d cases, %d unacknowledged, %d true positives" % (a.out, v["cases"], v["unacked"], v["tp"]))
    for w in warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
