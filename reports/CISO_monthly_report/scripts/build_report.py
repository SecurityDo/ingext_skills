#!/usr/bin/env python3
"""Render the CISO Monthly SOC (M-SOC) report for one tenant and one month.

Every figure, table row count, chart and score is computed here from the saved raw tool results
in --evidence-dir. The analyst writes only the narrative (narrative.json); it may refer to
computed values with {{name}} placeholders, and any other number it contains is listed as a
warning so it can be checked against the evidence.

  build_report.py --evidence-dir DIR --narrative narrative.json --tenant acme --tenant-name "Example Corp" \
                  --month 2026-09 --out report.html [--prepared YYYY-MM-DD] [--logo assets/fluency_logo.svg]

Evidence files in DIR (each a saved tool result, see references/evidence.md):
  metrics.json  metrics_prev.json   summarize_case_metrics, current and prior month
  fingerprints.json                 summarize_case_fingerprints (min_cases 1), current month
  repeat.json   repeat_prev.json    categorize_repeat_actors, current and prior month
  cases.json    cases_prev.json     list_cases, status ["*"], current and (optional) prior month
  sources.json                      evaluate_data_sources
  compliance.json                   assess_compliance_posture
A missing required file stops the run. A missing optional file (prior-month ones, compliance) turns
the sections that need it into a visible GAP; nothing is filled in.
"""
import argparse, calendar, collections, datetime, html, json, os, re, sys

E = html.escape
MONO = "'IBM Plex Mono',ui-monospace,Menlo,monospace"
SANS = "'Libre Franklin',Arial,Helvetica,sans-serif"
NAVY, RED, AMB, GRN, GRY = "#1C2B45", "#AD0015", "#C9962B", "#4E7A5D", "#8B93A3"
RAG = {"Green": GRN, "Amber": AMB, "Red": RED}
TREND = {"improving": "↑ Improving", "stable": "→ Stable", "declining": "↓ Declining"}
MIN_WORDS = 150
# keyword -> category for the five rolling-trend categories (matched against behaviorRules text)
CATEGORIES = [
    ("Threat & Attack", ("phish", "malware", "brute", "lateral", "exploit", "threat_intelligence", "threat_management", "risky", "highrisk", "high_risk", "spray", "unauthorized_api", "root_console_login_failed")),
    ("Endpoint", ("sentinelone", "falcon", "defender_endpoint", "msdefender:endpoint", "edr_", "_edr", "malware_protection")),
    ("Identity & Access", ("userloggedin", "authentication_method", "consent", "role_assignment", "add_member", "user_added", "user_disabled", "user_updated", "mfa", "signin", "sign-in", "service_principal", "update_application", "addpolicy", "updatepolicy", "mimecast_audit_login", "guest", "okta", "console_login", "login_without", "credentials_updated", "iam_", "root_console")),
    ("Network & Perimeter", ("fortigate", "firewall", "vpn", "dns", "zscaler", "netskope", "meraki", "network", "security_group", "security_configuration")),
    ("Vulnerability", ("vulnerab", "qualys", "cve", "tenable")),
]


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
    return ("Critical", RED) if score >= 18 else ("High", "#D98E32") if score >= 11 else ("Medium", AMB) if score >= 6 else ("Low", GRN)


def pill(t, col):
    return '<span style="display:inline-block;background:%s;color:#fff;font:600 10.5px/1 %s;padding:4px 8px;letter-spacing:.06em">%s</span>' % (col, MONO, E(t))


# ---------- html helpers ----------
def chapter(n, title):
    return ('<div style="margin:48px 0 0;padding:20px 72px;background:%s;display:flex;align-items:baseline;gap:20px"><span style="font:600 13px/1 %s;letter-spacing:.16em;color:#8FA3C8">CHAPTER %d</span>'
            '<span style="font-size:22px;font-weight:700;color:#fff">%s</span></div><section style="padding:32px 72px 8px">') % (NAVY, MONO, n, E(title))


def sec(num, title, flag=""):
    f = ('<span style="font:600 11px/1 %s;letter-spacing:.1em;color:#8A6508;background:#FBF3DD;border:1px solid #E5CF8E;padding:5px 10px">%s</span>' % (MONO, E(flag))) if flag else ""
    return '<div style="display:flex;align-items:baseline;gap:14px;margin:36px 0 16px"><span style="font:600 15px/1 %s;color:%s">%02d</span><h2 style="margin:0;font-size:22px;font-weight:700;color:%s">%s</h2>%s</div>' % (MONO, RED, num, NAVY, E(title), f)


def para(t):
    return '<p style="font-size:15px;line-height:1.7;color:#2E3646;margin:0 0 14px;max-width:860px">%s</p>' % t


def lead(t):
    return '<p style="font-size:15px;line-height:1.7;color:#4A5262;margin:0 0 8px;max-width:860px">%s</p>' % t


def callouts(items):
    return "".join('<div style="border-left:4px solid %s;background:#F4F6FA;padding:12px 18px;margin:10px 0;max-width:860px;font-size:14px;line-height:1.6;color:%s"><strong>Finding —</strong> %s</div>' % (RED, NAVY, t) for t in items)


def gap(t, kind="GAP"):
    return '<p style="margin:12px 0;font:400 12px/1.6 %s;color:#6B7484;max-width:860px"><span style="border:1px solid #C9CFD9;padding:1px 6px;font-weight:600;margin-right:6px">%s</span>%s</p>' % (MONO, kind, t)


def table(heads, rows, widths, hl=None):
    th = "".join('<th style="text-align:left;font:600 10.5px/1.4 %s;letter-spacing:.08em;text-transform:uppercase;color:#6B7484;padding:8px 10px;border-bottom:2px solid %s;width:%s">%s</th>' % (MONO, NAVY, widths[i], E(h)) for i, h in enumerate(heads))
    body = ""
    for i, r in enumerate(rows):
        bg = ' style="background:%s"' % hl[i] if hl and hl.get(i) else ""
        body += "<tr%s>%s</tr>" % (bg, "".join('<td style="padding:9px 10px;border-bottom:1px solid #E3E7ED;font-size:12.5px;line-height:1.5;color:#2E3646;vertical-align:top;overflow-wrap:anywhere">%s</td>' % c for c in r))
    return '<table style="border-collapse:collapse;width:100%%;table-layout:fixed;margin:10px 0 18px"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (th, body)


def figure(title, svg, note=""):
    return ('<div style="border:1px solid #DDE1E8;padding:18px 20px;margin:16px 0;max-width:860px"><div style="font:600 11px/1.4 %s;letter-spacing:.1em;text-transform:uppercase;color:#6B7484;margin-bottom:12px">%s</div>%s%s</div>'
            % (MONO, E(title), svg, ('<p style="margin:10px 0 0;font-size:12px;color:#6B7484">%s</p>' % note) if note else ""))


def hbars(data, width=760, label_w=250, color=NAVY, fmt=str):
    mx = max([r[1] for r in data] + [1])
    out = '<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (width, 26 * len(data) + 4)
    for i, r in enumerate(data):
        col = r[2] if len(r) > 2 else color
        y, bw = i * 26, (width - label_w - 70) * r[1] / mx
        out += ('<text x="0" y="%d" font-size="12" fill="#2E3646" font-family="%s">%s</text><rect x="%d" y="%d" width="%.1f" height="16" fill="%s" rx="2"/>'
                '<text x="%.1f" y="%d" font-size="12" fill="#2E3646" font-family="%s">%s</text>') % (y + 17, SANS, E(r[0]), label_w, y + 4, max(bw, 1), col, label_w + bw + 8, y + 17, MONO, E(fmt(r[1])))
    return out + "</svg>"


def heatmap(risks):
    cells = collections.defaultdict(list)
    for r in risks:
        cells[(r["likelihood"], r["impact"])].append(r["id"])
    svg = '<svg viewBox="0 0 520 300" width="100%" role="img">'
    for L in range(1, 6):
        for I in range(1, 6):
            x, y = 50 + (I - 1) * 92, 250 - L * 46
            svg += '<rect x="%d" y="%d" width="88" height="42" fill="%s" opacity="0.22"/><text x="%d" y="%d" font-size="11" fill="#2E3646" font-family="%s" text-anchor="end">%d</text>' % (x, y, band(L * I)[1], x + 84, y + 15, MONO, L * I)
            if cells.get((L, I)):
                svg += '<text x="%d" y="%d" font-size="13" font-weight="700" fill="%s" font-family="%s" text-anchor="middle">%s</text>' % (x + 44, y + 32, NAVY, MONO, E(" ".join(cells[(L, I)])))
    return svg + '<text x="270" y="290" font-size="11" fill="#6B7484" text-anchor="middle" font-family="%s">IMPACT 1 → 5</text><text x="10" y="150" font-size="11" fill="#6B7484" font-family="%s" transform="rotate(-90 10 150)" text-anchor="middle">LIKELIHOOD 1 → 5</text></svg>' % (SANS, SANS)


# ---------- computation ----------
def classify(case):
    rules = " ".join(case.get("behaviorRules") or []).lower()
    hits = [name for name, kws in CATEGORIES if any(k in rules for k in kws)]
    return hits[0] if hits else "Other"


def short_class(c):
    c = (c or "")
    return "Benign Positive" if c.startswith("Benign") else "False Positive" if c.startswith("False") else "True Positive" if c.startswith("True") else "Undetermined" if c.startswith("Undeterm") else "Unclassified"


def compute(ev, month):
    y, m = map(int, month.split("-"))
    last = calendar.monthrange(y, m)[1]
    v = {"year": y, "month": m, "month_name": calendar.month_name[m], "last_day": last}
    cur, prev = ev["metrics"], ev.get("metrics_prev")
    for label, m in (("metrics.json", cur), ("metrics_prev.json", prev)):
        if m and (m.get("capped") or m.get("reported_total", m["case_count"]) != m["case_count"]):
            warnings.append("%s covers %s of %s cases (the call was capped); pull it again with a higher sample_cap or the totals and response times are partial" % (label, m["case_count"], m.get("reported_total")))
    cl_cases = (ev.get("cases") or {})
    if cl_cases.get("reported_total") is not None and cl_cases["reported_total"] != len(cl_cases.get("cases", [])):
        warnings.append("cases.json holds %d of %s cases; page with offset and merge" % (len(cl_cases.get("cases", [])), cl_cases["reported_total"]))
    mt = cur["metrics"]
    v.update(cases=cur["case_count"], unacked=cur["unacked_count"], closed=cur["closed_count"], mttr_p50=mt["mttr"]["p50_seconds"], mttr_p90=mt["mttr"]["p90_seconds"],
             mttc_p50=mt["mttc"]["p50_seconds"], mttc_p90=mt["mttc"]["p90_seconds"], mttr_samples=mt["mttr"]["sample_n"])
    cl = cur["effective_classifications"]["counts"]
    v.update(tp=cl.get("True Positive", 0), fp=cl.get("False Positive", 0), bp=cl.get("Benign Positive", 0), und=cl.get("Undetermined", 0))
    v["open_status_new"] = v["unacked"]
    if prev:
        pm = prev["metrics"]
        pc = prev["effective_classifications"]["counts"]
        v.update(cases_prev=prev["case_count"], unacked_prev=prev["unacked_count"], closed_prev=prev["closed_count"], mttr_p50_prev=pm["mttr"]["p50_seconds"], mttr_p90_prev=pm["mttr"]["p90_seconds"],
                 mttc_p50_prev=pm["mttc"]["p50_seconds"], mttc_p90_prev=pm["mttc"]["p90_seconds"], tp_prev=pc.get("True Positive", 0), fp_prev=pc.get("False Positive", 0), bp_prev=pc.get("Benign Positive", 0))
    cases = (ev.get("cases") or {}).get("cases", [])
    v["case_rows"] = cases
    v["days"] = collections.Counter(int(str(c["dayIndex"])[-2:]) for c in cases)
    v["cat_cur"] = collections.Counter(classify(c) for c in cases)
    pcases = (ev.get("cases_prev") or {}).get("cases")
    v["cat_prev"] = collections.Counter(classify(c) for c in pcases) if pcases is not None else None
    for name, _ in CATEGORIES + [("Other", ())]:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        v["cat_" + slug] = v["cat_cur"].get(name, 0)
        if v["cat_prev"] is not None:
            v["cat_prev_" + slug] = v["cat_prev"].get(name, 0)
    v["mttr_note_mismatch"] = v["unacked"] > 0 and mt["mttr"]["sample_n"] >= v["cases"] and v["unacked"] > 0
    # numbers the narrative may legitimately cite
    known = {}
    for k, val in v.items():
        if isinstance(val, (int, float)):
            known[k] = val
    for k in ("mttr_p50", "mttr_p90", "mttc_p50", "mttc_p90", "mttr_p50_prev", "mttr_p90_prev", "mttc_p50_prev", "mttc_p90_prev"):
        if k in v:
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
    A.append('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title>'
             '<style>html,body{margin:0;background:#EEF0F4}body{font-family:%s;color:#2E3646}</style></head><body><div style="max-width:1080px;margin:0 auto;background:#fff;box-shadow:0 0 40px rgba(28,43,69,.08)">' % (E("CISO Monthly SOC Report - %s - %s" % (tname, mname)), SANS))
    # masthead
    A.append('<header style="padding:56px 72px 0"><div style="display:flex;align-items:center;justify-content:space-between;gap:24px;padding-bottom:28px;border-bottom:3px solid %s"><div style="display:flex;align-items:center;gap:18px">%s'
             '<div><div style="font:600 12px/1 %s;letter-spacing:.18em;color:%s;text-transform:uppercase">Managed SOC · Monthly Report</div><h1 style="margin:8px 0 0;font-size:34px;font-weight:800;color:%s">CISO Monthly SOC Report</h1></div></div>'
             '<div style="text-align:right;font:400 12px/1.8 %s;color:#6B7484"><div style="font-size:20px;font-weight:600;color:%s">%s — %s</div><div>Tenant <strong>%s</strong> · 1–%d %s %d (UTC)</div><div>Prepared %s · Read-only telemetry</div></div></div>'
             % (NAVY, logo, MONO, RED, NAVY, MONO, NAVY, E(tname), E(mname), E(tenant), v["last_day"], v["month_name"], v["year"], E(prep)))
    col = RAG[rag]
    A.append('<div style="display:flex;align-items:stretch;margin-top:24px;border:1px solid %s;background:#FBF3DD"><div style="display:flex;align-items:center;gap:14px;padding:16px 24px;background:%s"><span style="font:700 13px/1 %s;letter-spacing:.14em;color:#fff">POSTURE</span><span style="font-size:22px;font-weight:800;color:#fff">%s</span></div>'
             '<div style="display:flex;align-items:center;gap:14px;padding:16px 24px;border-right:1px solid %s"><span style="font:600 11px/1 %s;letter-spacing:.14em;color:#6B7484">TREND</span><span style="font-size:16px;font-weight:700;color:%s">%s</span></div>'
             '<div style="flex:1;display:flex;flex-wrap:wrap;align-items:center;gap:8px 28px;padding:16px 24px;font-size:13.5px;color:#4A5262"><span><strong>%d</strong> cases reviewed</span><span><strong style="color:%s">%d</strong> unacknowledged</span><span><strong>%d</strong> true positives</span></div></div>'
             % (col, col, MONO, rag.upper(), col, MONO, col, TREND[trend], v["cases"], RED, v["unacked"], v["tp"]))

    def kpi(val, label, c=NAVY):
        return '<div style="background:#fff;padding:16px 14px"><div style="font-size:26px;font-weight:800;color:%s">%s</div><div style="font-size:11px;font-weight:600;color:#6B7484;margin-top:4px;line-height:1.35">%s</div></div>' % (c, val, label)
    A.append('<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:#DDE1E8;border:1px solid #DDE1E8;margin-top:20px">%s</div></header>' % "".join([
        kpi(v["cases"], "Cases flagged (riskScore ≥ 3000)"), kpi(v["closed"], "Closed"), kpi(v["unacked"], "Unacknowledged", RED),
        kpi(hm(v["mttr_p50"]), "Median time to first response"), kpi(hm(v["mttc_p50"]), "Median time to close"), kpi(v["tp"], "True positives (of %d closed)" % v["closed"])]))

    # chapter 1
    A.append(chapter(1, "Where Things Stand") + sec(1, "Executive Summary", "%s · %s" % (rag.upper(), TREND[trend].upper())))
    A.append(paras(nar["exec_summary"]))
    dec = nar["decisions"][:2]
    A.append('<div style="border:1px solid %s;margin:22px 0;max-width:900px"><div style="padding:12px 22px;background:%s;font:600 12px/1 %s;letter-spacing:.14em;color:#fff">%s</div><div style="display:grid;grid-template-columns:%s">%s</div></div>'
             % (NAVY, NAVY, MONO, "TWO DECISIONS FOR LEADERSHIP" if len(dec) == 2 else "DECISION FOR LEADERSHIP", "1fr 1fr" if len(dec) == 2 else "1fr",
                "".join('<div style="padding:18px 22px;display:flex;gap:14px;%s"><span style="font:700 22px/1 %s;color:%s">%d</span><p style="margin:0;font-size:14px;line-height:1.6">%s</p></div>' % ("border-right:1px solid #DDE1E8;" if i == 0 and len(dec) == 2 else "", MONO, RED, i + 1, sub(d)) for i, d in enumerate(dec))))
    if nar.get("caveat"):
        A.append('<div style="border-top:3px solid %s;background:#FBF3DD;padding:14px 22px;max-width:860px"><p style="margin:0;font-size:13.5px;line-height:1.65;color:#5C4A12"><strong>Caveat —</strong> %s</p></div>' % (AMB, sub(nar["caveat"])))
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
    rows = [["Cases flagged for review", "<b>%d</b>" % v["cases"], str(v["cases_prev"]) if pv else "[GAP]", ("%s (%s)" % (signed(v["cases"], v["cases_prev"]), pct_change(v["cases"], v["cases_prev"]))) if pv else "[GAP]"]]
    for lab, k in (("Closed", "closed"), ("Unacknowledged (open, status new)", "unacked"), ("True positive (of closed)", "tp"), ("False positive (of closed)", "fp"), ("Benign positive (of closed)", "bp")):
        rows.append([lab, str(v[k]), str(v[k + "_prev"]) if pv else "[GAP]", signed(v[k], v[k + "_prev"]) if pv else "[GAP]"])
    A.append(table(["Measure", mname.split()[0], "Prior month" if pv else "Prior month", "Change"], rows, ["46%", "18%", "18%", "18%"], {2: "#FBF3DD"}))
    A.append(figure("Cases by day, %s" % mname, hbars([("%s %02d" % (v["month_name"][:3], d), n) for d, n in sorted(v["days"].items())], label_w=70), "Days with no flagged case are omitted. The day is the case's dayIndex."))
    A.append(paras(c2["analysis"]) + callouts([sub(x) for x in c2["callouts"]]))
    A.append(gap("Alerts processed versus escalated is not exposed to reporting tools, so the denominator behind the flagged cases is unknown.", "GAP"))
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
    rep, repp = ev["repeat"], ev.get("repeat_prev")
    coh = rep["cohorts"]
    if not rep.get("admin_lookup_ok", True):
        A.append(gap("The administrator lookup failed, so admin accounts could not be separated from other repeat actors.", "GAP"))
    pmap = {}
    if repp:
        for grp in ("admin_watch", "repeat_offenders", "unclassified"):
            for a in repp["cohorts"].get(grp, []):
                pmap[a["key"]] = a["case_count"]
    why = nar.get("repeat_why", {})
    for grp, label in (("admin_watch", "Admin Watch"), ("repeat_offenders", "Repeat Offender"), ("unclassified", "Unclassified")):
        rows = []
        for a in coh.get(grp, []):
            pc = pmap.get(a["key"])
            rows.append([E(a["key"]), label, str(a["case_count"]), "—" if repp is None else str(pc if pc is not None else "below threshold"), signed(a["case_count"], pc) if pc is not None else "n/a",
                         sub(why.get(a["key"], "—"))])
        if rows:
            A.append(table(["Identifier", "Category", "This month", "Prior month", "Delta", "Why it repeats"], rows, ["27%", "13%", "9%", "14%", "7%", "30%"]))
        elif grp != "unclassified":
            A.append('<p style="font-size:13px;color:#4A5262;margin:0 0 8px"><strong>%s:</strong> none identified%s.</p>' % (label, " (the administrator lookup succeeded, so this is a real result)" if grp == "admin_watch" and rep.get("admin_lookup_ok", True) else ""))
    fps = sorted(ev["fingerprints"]["fingerprints"], key=lambda f: -f["case_count_in_window_live"])[:7]
    A.append(figure("Most repeated case shapes (fingerprints), %s" % mname, hbars([(f["rules_str"][:46] + ("…" if len(f["rules_str"]) > 46 else ""), f["case_count_in_window_live"]) for f in fps], label_w=330)))
    A.append(paras(c3["analysis"]) + callouts([sub(x) for x in c3["callouts"]]))
    A.append(sec(5, "Root-Cause Themes", "PARTIAL"))
    A.append(table(["Theme", "Cases", "Linked users and assets", "Evidence", "Confidence"], [[E(r[0]), E(str(r[1])), E(r[2]), E(r[3]), E(r[4])] for r in nar["root_causes"]], ["23%", "8%", "29%", "28%", "12%"]))
    A.append(gap("Backend root-cause support does not exist yet. These themes are an analyst grouping of the top fingerprints and repeat actors; the counts can overlap.", "PARTIAL"))
    A.append("</section>")

    # chapter 4
    c4 = analysis(4)
    src = next(iter(ev["sources"]["tenants"].values()))
    bh = src.get("by_health", {})
    stale = [f for f in src.get("findings", []) if f.get("kind") == "source_stale_resources"]
    rf = src.get("resource_freshness", [])
    A.append(chap(4, "What We Can And Cannot See") + lead(sub(c4["intro"])) + sec(6, "Operational Exposure"))
    rows = [["Coverage &amp; Health", "%d configured source(s): %d ok, %d warning, %d error, %d inactive in the last 24 hours. Platform verdict: %s." % (src.get("configured_source_count", 0), bh.get("ok", 0), bh.get("warning", 0), bh.get("error", 0), bh.get("inactive", 0), E(str(src.get("verdict")))),
             "; ".join(E("%s %s: %s" % (f.get("integration"), f.get("resource_type"), f.get("probe_age_human") or "stale")) for f in stale) or "No stale resource feeds"]]
    for name, key in (("O365 Hygiene", "o365_hygiene"), ("Environment Changes", "environment_changes"), ("Vulnerability Highlights", "vulnerability_highlights")):
        t = nar.get("exposure", {}).get(key)
        rows.append([name, sub(t["evidence"]) if t else "[GAP] not assessed from this evidence", sub(t["limit"]) if t else "—"])
    A.append(table(["Area", "What the evidence shows", "Limit"], rows, ["20%", "45%", "35%"], {0: "#FBF3DD"} if stale else None))
    A.append(figure("Data-source health, last 24 h", hbars([("OK", bh.get("ok", 0), GRN), ("Warning", bh.get("warning", 0), AMB), ("Error", bh.get("error", 0), RED), ("Inactive", bh.get("inactive", 0), GRY), ("Stale resource feeds", len(stale), RED),
                                                            ("Empty resource feeds", sum(1 for r in rf if r.get("status") == "empty"), AMB)], label_w=190)))
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
                   ["5%", "11%", "13%", "15%", "11%", "4%", "4%", "6%", "8%", "23%"]))
    bc = collections.Counter(band(r["score"])[0] for r in risks)
    A.append(figure("Risk register heat map (likelihood × impact)", heatmap(risks), "Likelihood and impact are analyst-entered. Bands: 1–5 Low, 6–10 Medium, 11–17 High, 18–25 Critical. This register: %s." % ", ".join("%d %s" % (n, b) for b, n in sorted(bc.items(), key=lambda x: -["Low", "Medium", "High", "Critical"].index(x[0])))))
    A.append(paras(c5["analysis"]) + callouts([sub(x) for x in c5["callouts"]]))
    A.append(gap("Backend telemetry-risk scoring is not available. Likelihood and impact are analyst placeholders.", "PARTIAL"))
    A.append("</section>")

    # chapter 6
    c6 = analysis(6)
    A.append(chap(6, "How Our Defences Performed") + lead(sub(c6["intro"])) + sec(10, "Control Effectiveness", "GAP"))
    A.append(gap("Control effectiveness (controls doing the most work, exclusions, stale agents) is not exposed to reporting tools. The structure is kept; no rows are invented.", "GAP"))
    A.append(sec(11, "Response Performance"))

    def faster(a, b):
        if a is None or not b:
            return "n/a"
        ch = (a - b) * 100.0 / b
        return "%.0f%% %s" % (abs(ch), "faster" if ch < 0 else "slower")
    rows = [["Time to detect (MTTD)", "0 s", "0 s", "Not meaningful: cases are created at the first event"]]
    for lab, k in (("Time to first response, median", "mttr_p50"), ("Time to first response, slowest 10%", "mttr_p90"), ("Time to close, median", "mttc_p50"), ("Time to close, slowest 10%", "mttc_p90")):
        rows.append([lab, hm(v[k]), hm(v.get(k + "_prev")) if pv else "[GAP]", faster(v[k], v.get(k + "_prev")) if pv else "[GAP]"])
    rows.append(["True positives (of closed)", "%d of %d" % (v["tp"], v["closed"]), "%d of %d" % (v["tp_prev"], v["closed_prev"]) if pv else "[GAP]", "—"])
    A.append(table(["Measure", mname.split()[0], "Prior month", "Note"], rows, ["30%", "18%", "18%", "34%"]))
    bars = [("Median response", hours(v["mttr_p50"]), NAVY)] + ([("Prior median response", hours(v["mttr_p50_prev"]), GRY)] if pv else []) + [("Slowest-10% response", hours(v["mttr_p90"]), NAVY)] + ([("Prior slowest-10% response", hours(v["mttr_p90_prev"]), GRY)] if pv else [])
    A.append(figure("Time to first response, hours", hbars(bars, label_w=230, fmt=lambda x: "%.1f h" % x)))
    A.append(paras(c6["analysis"]) + callouts([sub(x) for x in c6["callouts"]]))
    if v["mttr_note_mismatch"]:
        A.append(gap("Every case has a response time (%d of %d) although %d are still status new, so automated assistant comments may be counted as a response. The analyst response time may be longer." % (v["mttr_samples"], v["cases"], v["unacked"]), "NOTE"))
    A.append(sec(12, "Escalation Log", "GAP"))
    A.append(gap("The SOC escalation log is not exposed to reporting tools. No escalations are listed and none are inferred.", "GAP"))
    A.append('<div style="display:flex;align-items:baseline;gap:14px;margin:36px 0 12px"><h2 style="margin:0;font-size:20px;font-weight:700;color:%s">Governance &amp; Compliance Posture</h2><span style="font:600 11px/1 %s;color:#8A6508;background:#FBF3DD;border:1px solid #E5CF8E;padding:5px 10px">NIST SP 800-53 REV. 5 · EVIDENCE AID</span></div>' % (NAVY, MONO))
    comp = ev.get("compliance")
    if not comp or comp.get("assessment_type") == "assessment_skeleton_no_fluency_calls" or not (comp.get("live_collection") or {}).get("counts", {}).get("collected"):
        A.append(gap("No live compliance evidence was collected, so no posture is shown. A skeleton is never rendered as a result.", "GAP"))
        comp = None
    else:
        cc = comp["counts"]
        lc = comp["live_collection"]["counts"]
        total = sum(cc.values())
        A.append(figure("Control posture, %d root controls" % total, hbars([("Supported", cc.get("supported", 0), GRN), ("Partial", cc.get("partial", 0), AMB), ("Not observed", cc.get("not_observed", 0), GRY), ("Unsupported", cc.get("unsupported", 0), RED)], label_w=150)))
        notobs = re.findall(r"\n\s+([A-Z]{2}-\d+),([^,]+),[^,]*,not_observed", "\n" + comp.get("findings_toon", ""))
        failed = [s for s in comp["live_collection"].get("collection_log", []) if s.get("status") in ("failed", "error")]
        A.append(para("The evidence <strong>supports %d, partly supports %d and did not observe %d</strong> of %d mapped controls; %d are unsupported. Not observed: %s. Collection succeeded for %d source(s), failed for %d and skipped %d. A failed or skipped source is a collection gap, not a verdict." %
                      (cc.get("supported", 0), cc.get("partial", 0), cc.get("not_observed", 0), total, cc.get("unsupported", 0), E(", ".join("%s (%s)" % (a, b.strip()) for a, b in notobs) or "none"), lc.get("collected", 0), lc.get("failed", 0), lc.get("skipped", 0))))
        for fs in failed:
            A.append(gap("Collection failed: %s. Treat the controls that depend on it as a gap." % E(str(fs.get("source_key"))), "GAP"))
    A.append(gap("This is an evidence analysis aid, not certification or attestation. 'Supported' means the evidence supports the control, never that the tenant is compliant. Movement against the prior month needs a prior assessment (compare_compliance_assessments).", "NOTE"))
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
    A.append(gap("The SOC change log (tuning, new detections, log sources onboarded, playbook updates) is not exposed to reporting tools. No changes are listed and none are inferred.", "GAP"))
    A.append(sec(16, "Appendix"))
    h3 = '<h3 style="font-size:16px;color:%s;margin:16px 0 8px">%s</h3>'
    inv = [["Configured sources", "%d: %d ok, %d warning, %d error, %d inactive" % (src.get("configured_source_count", 0), bh.get("ok", 0), bh.get("warning", 0), bh.get("error", 0), bh.get("inactive", 0))],
           ["Integrations", E(", ".join(src.get("configured_integrations", [])) or "none")]]
    for r in rf:
        inv.append([E("%s %s" % (r.get("integration"), r.get("resource_type"))), E("%s%s" % (r.get("status"), (", " + r["age_human"]) if r.get("age_human") else ""))])
    A.append(h3 % (NAVY, "A. Log source inventory") + table(["Item", "Status"], inv, ["40%", "60%"]))
    A.append(h3 % (NAVY, "B. Fingerprints cited") + table(["Hash", "Rules", "Cases"], [[E(f["hash"][:8]), E(f["rules_str"]), str(f["case_count_in_window_live"])] for f in sorted(ev["fingerprints"]["fingerprints"], key=lambda f: -f["case_count_in_window_live"])], ["14%", "74%", "12%"]))
    mit = sum(f["mitre_attack"]["mapped_case_count"] for f in ev["fingerprints"]["fingerprints"])
    techs = collections.Counter()
    for f in ev["fingerprints"]["fingerprints"]:
        for t in f.get("mitre_attack", {}).get("techniques", []) or []:
            techs[(t.get("tactic"), t.get("technique_id"), t.get("technique_name"))] += t.get("case_count", 0)
    A.append(h3 % (NAVY, "C. ATT&CK") + '<p style="font-size:13px;color:#4A5262;max-width:860px">%d of %d cases map to approved ATT&amp;CK techniques. %s</p>' % (mit, v["cases"], "No technique table is shown." if mit == 0 else "Supporting material only: a technique counts once per case that carries it, and only approved local mappings count as coverage."))
    if techs:
        A.append(table(["Tactic", "Technique", "Cases"], [[E(str(a)), E("%s %s" % (b, c)), str(n)] for (a, b, c), n in sorted(techs.items(), key=lambda x: (-x[1], str(x[0])))], ["26%", "56%", "18%"]))
    tools = "summarize_case_metrics, summarize_case_fingerprints, categorize_repeat_actors, list_cases, evaluate_data_sources" + (", assess_compliance_posture" if comp else "")
    A.append(h3 % (NAVY, "D. Methodology") + '<p style="font-size:13px;line-height:1.65;color:#4A5262;max-width:860px">Scope: tenant %s. Window: 1–%d %s %d UTC%s. Read-only calls: %s. Sections marked GAP or PARTIAL could not be computed from these tools. A case is a cluster of events for one user, host or application on one day; a fingerprint is the combination of rules that fired; a benign positive is activity that looked suspicious but was expected.</p>'
             % (E(tenant), v["last_day"], v["month_name"], v["year"], "; prior month compared" if pv else "", tools))
    A.append('</section><footer style="margin-top:40px;padding:22px 72px;border-top:3px solid %s;font:400 11px/1.6 %s;color:#6B7484">Fluency Managed SOC · %s · %s · Generated from read-only telemetry. Not a certification or attestation.</footer></div></body></html>' % (NAVY, MONO, E(tname), E(mname)))
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
    ev = {"metrics": load(d, "metrics.json", True), "metrics_prev": load(d, "metrics_prev.json"), "fingerprints": load(d, "fingerprints.json", True), "repeat": load(d, "repeat.json", True),
          "repeat_prev": load(d, "repeat_prev.json"), "cases": load(d, "cases.json", True), "cases_prev": load(d, "cases_prev.json"), "sources": load(d, "sources.json", True), "compliance": load(d, "compliance.json")}
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
