#!/usr/bin/env python3
"""Render a GDPR (Regulation (EU) 2016/679) companion view of the NIST 800-53 evidence (HTML + CSV).

  build_report.py --summary compliance_summary.json --out report.html [--csv report.csv] --tenant NAME --site Develop

compliance_summary.json is written by `compliance-assessment/scripts/build_report.py --summary-json`. This script
collects nothing. Each row lists the 800-53 control groups it relates to, with their statuses exactly as returned.
The mapping is an indicative analyst crosswalk, labelled as such; related is not equivalent, and nothing here is a finding of GDPR compliance or an Article 42 certification.
"""
import argparse, collections, csv, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B"
STATUS = {"supported": ("Supported", GRN), "partial": ("Partial", AMB), "not_observed": ("Not observed", GRY), "needs_manual_review": ("Needs manual review", "#1D4ED8")}
META = {'authority': 'a supervisory authority, a court or an accredited certification body',
 'eyebrow': 'Data protection evidence',
 'full': 'GDPR (Regulation (EU) 2016/679)',
 'name': 'GDPR',
 'note': 'GDPR articles that technical and organisational security evidence can support',
 'result': 'a finding of GDPR compliance or an Article 42 certification',
 'sub': 'Companion view of the NIST SP 800-53 evidence',
 'title': 'GDPR security-of-processing evidence'}
ROWS = [('Art. 32(1)(b)',
  'Ongoing confidentiality, integrity and availability of processing systems: access control',
  ['AC-2', 'AC-7', 'IA-2 / IA-5'],
  'Access evidence is not scoped to systems that process personal data.'),
 ('Art. 32(1)(b), (d)',
  'Monitoring, logging and regular testing of security measures',
  ['AU-2 / AU-12', 'SI-4', 'AU-6'],
  'Logs often contain personal data themselves; review cadence is not evidenced.'),
 ('Art. 32(1)(d), 32(2)',
  'Regular testing and assessment; risk assessment',
  ['RA-5'],
  'Vulnerability scanning supports testing; it is not a data protection risk assessment.'),
 ('Art. 32(1)(b)',
  'Protection of systems against malicious code and network threats',
  ['SI-3', 'SC-7'],
  'Agent coverage, rules and segmentation were not evaluated.'),
 ('Art. 33, 34, 33(5)',
  'Breach detection, notification (72 hours) and documentation',
  ['IR-4 / IR-5'],
  'Detection and handling evidence only; notification decisions, timing and records must come from the controller.'),
 ('Art. 5(1)(e), 5(2)',
  'Storage limitation and accountability for log retention',
  ['AU-4 / AU-11'],
  'Retention was not collected; logs that hold personal data need a defined, justified period.'),
 ('Art. 30 / 32',
  'Records of processing and knowledge of systems in scope',
  ['CM-8'],
  'An asset inventory supports, but is not, the record of processing activities.'),
 ('Art. 24 / 5(2)',
  'Responsibility of the controller: policies and demonstrable accountability',
  ['AC-1 / IA-1 / IR-1'],
  'Data protection policies are customer documents.')]
NOT_COVERED = ['Lawful basis, purpose limitation, data minimisation and accuracy (Article 5 and 6)',
 'Data subject rights: access, erasure, portability and objection (Articles 12 to 22)',
 'Data protection by design and by default (Article 25) as design decisions, and data protection impact assessments (Article 35)',
 'Records of processing activities (Article 30), the Data Protection Officer (Articles 37 to 39) and processor contracts (Article 28)',
 'International transfers (Articles 44 to 49)',
 'Encryption and pseudonymisation of personal data, which telemetry does not show (Article 32(1)(a))']
EXTRA_LIMITS = ['GDPR is a regulation, not a control framework: these rows are security measures that support Article 32, not a determination of compliance.']

CHECKS = [('Art. 32', 'Security of processing: administrator MFA', 'admin_mfa', None, 'Appropriate measures depend on risk; MFA is one example.'),
          ('Art. 32', 'Security of processing: audit event sources', 'sources', None, 'Not scoped to personal data processing systems.'),
          ('Art. 33', 'Detecting personal data breaches: incident handling', 'triage', None, 'Detection only; the 72-hour notification duty is not evidenced.'),
          ('Art. 33', 'Detecting personal data breaches: threat findings', 'threat', None, 'Only GuardDuty findings are visible here.'),
          ('Art. 32', 'Security of processing: known exploitable vulnerabilities', 'vuln_expl', None, 'Not scoped to personal data processing systems.'),
          ('Art. 32', 'Security of processing: malware protection', 'av_current', None, 'Defender antivirus only; not scoped to personal data systems.')]

# ---- Framework-specific checks and evidence coverage (computed from the summary facts; collects nothing) ----
RES = {"ok": ("No gap seen", GRN), "review": ("Review", AMB), "gap": ("Gap seen", RED), "na": ("Not evaluable", GRY)}


def _facts(d):
    f = d.get("facts") or {}
    hy = f.get("hygiene") or {}
    ev = f.get("events") or {}
    inc = f.get("incidents") or {}
    ct = f.get("cloudtrail") or {}
    hist = [h for h in (f.get("history") or []) if h.get("days") is not None]
    srcs = [v for v in (ev.get("office365"), ev.get("signin"), ev.get("directory_audit"), ev.get("windows_audit"), ct.get("events")) if v]
    srcs += [x["events"] for x in (f.get("sources") or []) if x.get("events") and x.get("table") != "CloudTrail"]
    return {"admins": hy.get("admins"), "admin_gap": hy.get("admins_no_mfa"), "enabled": hy.get("enabled"), "user_gap": hy.get("enabled_no_mfa"),
            "signin": ev.get("signin"), "failed": ev.get("signin_failed"), "root": ct.get("root_events"),
            "inc_total": inc.get("total"), "inc_new": inc.get("new"), "gd": f.get("guardduty"),
            "hist_days": min((h["days"] for h in hist), default=None), "hist_bounded": any(h.get("at_least") for h in hist), "sources": len(srcs) if (ev or srcs) else None, "mde": f.get("defender"), "scan": f.get("scanners_endpoint")}


def _admin_mfa(F, p):
    if F["admins"] is None or F["admin_gap"] is None:
        return "na", "MFA registration of administrators was not collected."
    if F["admin_gap"] == 0:
        return "ok", "All %d administrator accounts have MFA registered. Registration is not enforcement." % F["admins"]
    return "gap", "%d of %d administrator accounts have no MFA registered." % (F["admin_gap"], F["admins"])


def _all_mfa(F, p):
    if F["enabled"] is None or F["user_gap"] is None:
        return "na", "MFA registration of users was not collected."
    if F["user_gap"] == 0:
        return "ok", "All %d enabled users have MFA registered. Registration is not enforcement." % F["enabled"]
    return "gap", "%d of %d enabled users have no MFA registered." % (F["user_gap"], F["enabled"])


def _logons(F, p):
    if not F["signin"] or F["failed"] is None:
        return "na", "Sign-in failures were not collected."
    return "na", "%.1f%% of Entra sign-ins failed (%s of %s). The lockout threshold was not collected, so the limit itself cannot be checked." % (100.0 * F["failed"] / F["signin"], "{:,}".format(F["failed"]), "{:,}".format(F["signin"]))


def _log_sources(F, p):
    k = F["sources"]
    if k is None:
        return "na", "Event volumes were not collected."
    return ("ok" if k >= 2 else "review" if k == 1 else "gap"), "Audit events were collected from %d sources in the period." % k


def _triage(F, p):
    if F["inc_total"] is None:
        return "na", "Incident status was not collected."
    if not F["inc_new"]:
        return "ok", "None of the %d incidents in the window is still new." % F["inc_total"]
    return ("gap" if F["inc_new"] == F["inc_total"] else "review"), "%d of %d incidents in the window are still marked new." % (F["inc_new"], F["inc_total"])


def _threat(F, p):
    g = F["gd"]
    if not g:
        return "na", "No GuardDuty data was collected."
    if not g.get("high_open"):
        return "ok", "No high-severity GuardDuty finding is open in the snapshot (%d findings)." % g.get("findings", 0)
    return "review", "%d high-severity GuardDuty findings are open in the snapshot." % g["high_open"]


def _root(F, p):
    if F["root"] is None:
        return "na", "Root-account activity was not collected."
    if not F["root"]:
        return "ok", "No events by the AWS root identity in the period."
    return "review", "%s events by the AWS root identity in the period; confirm each was expected." % "{:,}".format(F["root"])


def _history(F, p):
    days = F["hist_days"]
    if days is None:
        return "na", "History depth was not measured."
    if days >= p:
        return "ok", "The shortest observed history is %d days; %d are asked for. This is what exists, not the configured retention." % (days, p)
    if F["hist_bounded"]:
        return "na", "At least %d days observed on the shortest source; the query window limited the measure, and %d are asked for." % (days, p)
    return "gap", "The shortest observed history is %d days against %d asked for. This is how far back records exist; it can reflect when a source was connected rather than a retention setting." % (days, p)


def _scan(F, key):
    return (F.get("scan") or {}).get(key)


def _mde(F, key):
    return (F.get("mde") or {}).get(key)


def _vuln_found(F, p):
    v = _mde(F, "vuln")
    t = _scan(F, "tenable")
    q = _scan(F, "qualys")
    if not (v or t or q):
        return "na", "No vulnerability scanner data (Defender, Tenable or Qualys) was collected."
    parts, gap = [], False
    if v:
        parts.append("Defender reports %s findings across %s devices." % ("{:,}".format(v["findings"]), "{:,}".format(v["devices"])))
    if t:
        parts.append("Tenable scanned %s of %s assets in the 30 days before the period ended (%s authenticated)." % ("{:,}".format(t.get("scanned_recent", 0)), "{:,}".format(t.get("assets", 0)), "{:,}".format(t.get("authenticated", 0))))
        if t.get("assets") and t.get("scanned_recent", 0) < 0.95 * t["assets"]:
            gap = True
    if q and q.get("hosts"):
        stale = q.get("never_scanned", 0) + q.get("stale_scan", 0)
        parts.append("Qualys has %s of %s hosts without a recent scan." % ("{:,}".format(stale), "{:,}".format(q["hosts"])))
        if stale:
            gap = True
    parts.append("Scan cadence and rescans are not evidenced.")
    return ("review" if gap else "ok"), " ".join(parts)

def _vuln_expl(F, p):
    v = _mde(F, "vuln")
    if not v:
        return "na", "Defender vulnerability data was not collected."
    if v.get("exploit"):
        return "gap", "%s findings on %s devices have a verified, public or exploit-kit exploit." % ("{:,}".format(v["exploit"]), "{:,}".format(v["exploit_devices"]))
    return "ok", "None of the %s findings has a known exploit." % "{:,}".format(v["findings"])


def _vuln_aged(F, p):
    v = _mde(F, "vuln")
    if not v:
        return "na", "Defender vulnerability data was not collected."
    if v.get("critical_aged"):
        return "review", "%s of %s critical findings were first seen more than 30 days before the period ended. The patching deadline itself is not known." % ("{:,}".format(v["critical_aged"]), "{:,}".format(v["critical"]))
    return "ok", "No critical finding was first seen more than 30 days before the period ended (%s critical in all)." % "{:,}".format(v.get("critical", 0))


def _av_current(F, p):
    a = _mde(F, "av")
    s1 = _scan(F, "sentinelone")
    fc = _scan(F, "falcon")
    if not ((a and a.get("devices")) or s1 or fc):
        return "na", "No endpoint-protection health data (Defender, SentinelOne or Falcon) was collected."
    parts, level = [], "ok"
    def bump(x):
        nonlocal level
        order = ["ok", "review", "gap"]
        if order.index(x) > order.index(level):
            level = x
    if a and a.get("devices"):
        stale = a.get("sig_stale", 0)
        parts.append("Defender: %s of %s devices have out-of-date signatures and %s an out-of-date platform." % ("{:,}".format(stale), "{:,}".format(a["devices"]), "{:,}".format(a.get("platform_stale", 0))))
        bump("gap" if stale >= 0.05 * a["devices"] else ("review" if stale else "ok"))
    if s1:
        bad = s1.get("out_of_date", 0) + s1.get("not_protect", 0) + s1.get("infected", 0)
        parts.append("SentinelOne: %s of %s agents out of date, %s not in protect mode, %s with active threats." % ("{:,}".format(s1.get("out_of_date", 0)), "{:,}".format(s1.get("agents", 0)), "{:,}".format(s1.get("not_protect", 0)), "{:,}".format(s1.get("infected", 0))))
        bump("gap" if s1.get("agents") and bad >= 0.05 * s1["agents"] else ("review" if bad or s1.get("unresolved") else "ok"))
    if fc:
        bad = fc.get("reduced", 0) + fc.get("no_prevention", 0) + fc.get("not_seen_recent", 0)
        parts.append("Falcon: %s of %s sensors in reduced functionality, %s without a prevention policy." % ("{:,}".format(fc.get("reduced", 0)), "{:,}".format(fc.get("sensors", 0)), "{:,}".format(fc.get("no_prevention", 0))))
        bump("gap" if fc.get("sensors") and bad >= 0.05 * fc["sensors"] else ("review" if bad else "ok"))
    return level, " ".join(parts)

def _config(F, p):
    c = _mde(F, "config")
    if not c or not c.get("checks"):
        return "na", "Defender secure-configuration data was not collected."
    share = 100.0 * c.get("noncompliant", 0) / c["checks"]
    txt = "%s of %s applicable checks are failing (%.0f%%), across %s devices." % ("{:,}".format(c.get("noncompliant", 0)), "{:,}".format(c["checks"]), share, "{:,}".format(c.get("devices_with_gaps", 0)))
    return ("review" if share >= 25 else "ok"), txt


def _mde_inventory(F, p):
    m = _mde(F, "machines")
    t = _scan(F, "tenable")
    s1 = _scan(F, "sentinelone")
    fc = _scan(F, "falcon")
    if not ((m and m.get("devices")) or t or s1 or fc):
        return "na", "No device inventory (Defender, Tenable, SentinelOne or Falcon) was collected."
    parts, review = [], False
    if m and m.get("devices"):
        parts.append("Defender lists %s devices: %s onboarded, %s can be onboarded, %s with an inactive or impaired sensor." % ("{:,}".format(m["devices"]), "{:,}".format(m.get("onboarded", 0)), "{:,}".format(m.get("can_onboard", 0)), "{:,}".format(m.get("inactive", 0))))
        review = review or bool(m.get("can_onboard"))
    for label, x, k in (("Tenable assets", t, "assets"), ("SentinelOne agents", s1, "agents"), ("Falcon sensors", fc, "sensors")):
        if x and x.get(k):
            parts.append("%s: %s." % (label, "{:,}".format(x[k])))
    parts.append("The inventories were not reconciled with one another.")
    return ("review" if review else "ok"), " ".join(parts)

CHECKFN = {"admin_mfa": _admin_mfa, "all_mfa": _all_mfa, "logons": _logons, "sources": _log_sources, "triage": _triage, "threat": _threat, "root": _root, "history": _history, "vuln_found": _vuln_found, "vuln_expl": _vuln_expl, "vuln_aged": _vuln_aged, "av_current": _av_current, "config": _config, "mde_inventory": _mde_inventory}


def _checks_html(d):
    F = _facts(d)
    rows = []
    for ref, title, fn, p, cav in CHECKS:
        res, txt = CHECKFN[fn](F, p)
        lbl, col = RES[res]
        rows.append("<tr><td class='ctl' style='--c:%s'>%s</td><td><b>%s</b><div class='cav'>%s</div></td><td><span class='pill' style='--c:%s'>%s</span></td><td>%s</td></tr>" % (col, E(ref), E(title), E(cav), col, E(lbl), E(txt)))
    return ("<h2><span class='n'>2</span>Framework-specific checks</h2><p class='sub'>Checks that look at this framework's own wording rather than only the 800-53 status. Thresholds are the analyst's, evidence is one month of telemetry, "
            "and &lsquo;No gap seen&rsquo; is an observation about the evidence, not a statement that a requirement is met.</p>"
            "<div class='tw'><table><thead><tr><th>Reference</th><th>Check</th><th>Result</th><th>What the evidence shows</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(rows))


def _fw_cov(st):
    vals = []
    S = lambda g: (st[g]["status"] if isinstance(st[g], dict) else st[g])
    for cid, title, groups, cav in ROWS:
        sc = [(1.0 if S(g) == "supported" else 0.5 if S(g) == "partial" else 0.0) for g in groups if g in st and S(g) != "needs_manual_review"]
        if sc:
            vals.append(sum(sc) / len(sc))
    return int(round(100.0 * sum(vals) / len(vals))) if vals else None


def _cov_kpi(d, st):
    now = _fw_cov(st)
    sub = ""
    pr = d.get("prior")
    if pr and pr.get("rows"):
        was = _fw_cov({r["control"]: r["status"] for r in pr["rows"]})
        if now is not None and was is not None:
            diff = now - was
            sub = "<small class='%s'>%s vs %s</small>" % ("up" if diff > 0 else "down" if diff < 0 else "", ("%+d pts" % diff) if diff else "No change", E(pr.get("period", "")))
    return "<div class='kpi' style='--c:#14213d'><b>%s</b><span>Evidence coverage</span>%s</div>" % ("%d%%" % now if now is not None else "n/a", sub)


def _fw_kpis(d, st, strong, none, need):
    n = len(ROWS)
    F = _facts(d)
    res = [CHECKFN[fn](F, p)[0] for ref, title, fn, p, cav in CHECKS]
    flag = sum(1 for r in res if r in ("gap", "review"))
    gap = sum(1 for r in res if r == "gap")
    k = lambda col, big, lab, sub: "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span><small>%s</small></div>" % (col, big, lab, sub)
    t = [_cov_kpi(d, st),
         k(GRN, len(strong), "Requirements strongly mapped", "of %d in this view" % n),
         k(AMB, len(need), "Requirements needing evidence", "of %d in this view" % n),
         k(GRY, len(none), "Requirements not observed", "of %d in this view" % n),
         k(RED if gap else AMB if flag else GRN, flag, "Checks to review", "%d gap seen &middot; %d checks in all" % (gap, len(res)))]
    return "<div class='kpis'>%s</div>" % "".join(t)


STYLE = """
.kpi small{display:block;margin-top:4px;font-size:11px;color:var(--mut)}.up{color:#15803D!important}.down{color:#B91C1C!important}

:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#2563eb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px 48px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:38px 0 70px}
.hero .wrap{padding-bottom:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}
.hero p{margin:0;color:#c7d4ee;font-size:14px}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-top:-46px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:32px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-top:18px;box-shadow:0 1px 4px rgba(15,26,51,.04)}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}.bar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:16px;color:var(--mut);font-size:12px}.legend em{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0}
td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
td.ctl{border-left:4px solid var(--c);white-space:nowrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;color:var(--navy)}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
.mut{color:var(--mut)}.state{font-size:12px;color:var(--mut)}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.rel{display:flex;flex-wrap:wrap;gap:6px}.rel span{display:inline-flex;align-items:center;gap:6px;background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:2px 9px;font-size:12px;font-family:ui-monospace,Menlo,Consolas,monospace}.rel em{width:9px;height:9px;border-radius:50%;background:var(--c);display:inline-block}
.sum{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0 4px}.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-top:4px solid var(--c)}.sum b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin-bottom:4px}.sum span{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--navy)}.cav{font-size:12px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;margin-bottom:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media (max-width:760px){.kpis,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{h2,h2+p{break-after:avoid}body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi,.panel{break-inside:avoid}th{position:static}.kpi,.pill,.bar i,td.ctl,.card,.read{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""



def pill(s):
    lbl, col = STATUS.get(s, (s, GRY))
    return '<span class="pill" style="--c:%s">%s</span>' % (col, E(lbl))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    try:
        d = json.load(open(a.summary))
        st = {r["control"]: r for r in d["rows"]}
    except (OSError, ValueError, KeyError) as e:
        sys.exit("cannot read compliance_summary.json (%s). Run compliance-assessment with --summary-json first." % e)
    cnt = collections.Counter(r["status"] for r in d["rows"])
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>%s Companion Analysis</title><style>%s</style></head><body>" % (E(META["full"]), STYLE)]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>%s</div><h1>%s</h1><p>%s</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>Related, not equivalent</span></div></div></div><div class='wrap'>" % (
                 E(META["eyebrow"]), E(META["title"]), E(META["sub"]), E(a.tenant or "Tenant"), E(a.site or "Connector"), E(d.get("period", ""))))
    kpi_idx = len(o)
    o.append("")
    o.append("<div class='read'><b>Read this first.</b> The evidence is rooted in NIST SP 800-53 Rev. 5 and was collected by compliance-assessment. "
             "The rows below are <b>mapped or related</b> to it by an indicative analyst crosswalk. They are <b>not equivalent</b>: a related 800-53 status does not show a %s requirement is met. "
             "Only %s can issue %s. Not observed means not collected in this run, not a failed control.</div>" % (E(META["name"]), META["authority"], META["result"]))
    strong, none, need, body_rows, csv_rows = [], [], [], [], []
    for cid, title, groups, cav in ROWS:
        rel = [(g, st[g]["status"]) if g in st else (g, None) for g in groups]
        sts = [s for _, s in rel]
        if sts and all(s == "supported" for s in sts):
            strong.append(cid); rc = STATUS["supported"][1]
        elif sts and all(s in ("not_observed", None) for s in sts):
            none.append(cid); rc = STATUS["not_observed"][1]
        else:
            need.append(cid); rc = STATUS["partial"][1]
        cell = "<div class='rel'>%s</div>" % "".join("<span style='--c:%s'><em></em>%s &middot; %s</span>" % (
            STATUS[s][1] if s else GRY, E(g), E(STATUS[s][0]) if s else "not in this run") for g, s in rel)
        body_rows.append("<tr><td class='ctl' style='--c:%s'>%s</td><td><b>%s</b><div class='cav'>%s</div></td><td>%s</td></tr>" % (rc, E(cid), E(title), E(cav), cell))
        for g, s in rel:
            csv_rows.append([META["full"], cid, title, g, s or "not in this run", cav])
    o[kpi_idx] = _fw_kpis(d, st, strong, none, need)
    o.append("<h2><span class='n'>1</span>%s</h2>" % E(META["note"]))
    o.append("<div class='sum'><div style='--c:%s'><b>Strongest mapped (%d)</b><span>%s</span></div><div style='--c:%s'><b>Not observed (%d)</b><span>%s</span></div><div style='--c:%s'><b>Evidence still needed (%d)</b><span>%s</span></div></div>" % (
        GRN, len(strong), E(", ".join(strong) or "none"), GRY, len(none), E(", ".join(none) or "none"), AMB, len(need), E(", ".join(need) or "none")))
    o.append("<p class='sub'>The stripe shows the weakest related evidence: green when every related 800-53 group is supported, grey when none was observed, amber otherwise.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Requirement</th><th>Title and caveat</th><th>Related 800-53 groups and status</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(body_rows))
    o.append(_checks_html(d))
    o.append("<h2><span class='n'>3</span>Not evidenced by telemetry</h2><p class='sub'>These parts of %s are outside what this report can show, so a clean table is not a clean bill of health.</p>" % E(META["name"]))
    o.append("<div class='cards'>%s</div>" % "".join("<div class='card' style='--c:%s'>%s</div>" % (GRY, E(x)) for x in NOT_COVERED))
    o.append("<div class='foot'><b>Limits</b><ul><li>The mapping is the analyst's and is indicative; confirm it against the current text of %s before relying on it.</li>"
             "<li>Statuses are the 800-53 statuses returned by compliance-assessment; a row never raises one.</li>"
             "<li>Resource-table counts are snapshots as of the dump; event counts are for the period.</li>%s"
             "<li>Never read this as certification, attestation or a compliance finding.</li></ul></div></div></body></html>" % (
                 E(META["full"]), "".join("<li>%s</li>" % E(x) for x in EXTRA_LIMITS)))
    with open(a.out, "w") as f:
        f.write("\n".join(o))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["framework", "requirement", "title", "related_800_53", "related_status", "caveat"])
            w.writerows(csv_rows)
    print("%d requirements: %d strongest, %d not observed, %d still needed" % (len(ROWS), len(strong), len(none), len(need)))


if __name__ == "__main__":
    main()
