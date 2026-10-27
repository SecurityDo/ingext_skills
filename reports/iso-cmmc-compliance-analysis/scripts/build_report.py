#!/usr/bin/env python3
"""Render ISO/IEC 27001:2022 and CMMC companion views of the 800-53 evidence (HTML + CSV).

  build_report.py --summary compliance_summary.json --out companion.html [--csv companion.csv]
                  --tenant NAME --site Develop [--framework iso|cmmc|both]

compliance_summary.json is written by `compliance-assessment/scripts/build_report.py --summary-json`. This script
collects nothing. Each companion row lists the 800-53 control groups it relates to, with their statuses exactly as
returned. The mapping is an indicative analyst crosswalk, labelled as such; related is not equivalent.
"""
import argparse, collections, csv, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY = "#1C2B45", "#B91C1C", "#B45309", "#15803D", "#64748B"
STATUS = {"supported": ("Supported", GRN), "partial": ("Partial", AMB), "not_observed": ("Not observed", GRY), "needs_manual_review": ("Needs manual review", "#1D4ED8")}
# companion control -> (framework, id, title, related 800-53 groups (as named by compliance-assessment), caveat)
ISO = [
    ("A.5.1", "Policies for information security", ["AC-1 / IA-1 / IR-1"], "Policy documents are customer-supplied; also read ISO clause 5.2 (policy)."),
    ("A.5.9", "Inventory of information and other associated assets", ["CM-8"], "Directory and Qualys inventories were not reconciled to an asset register."),
    ("A.5.15 / A.5.16 / A.5.18", "Access control; identity management; access rights", ["AC-2"], "Account-review cadence is not evidenced by telemetry."),
    ("A.5.17 / A.8.5", "Authentication information; secure authentication", ["IA-2 / IA-5", "AC-7"], "MFA registration is not enforcement; lockout configuration not collected."),
    ("A.5.24 / A.5.25 / A.5.26", "Incident management planning, assessment and response", ["IR-4 / IR-5"], "A documented response procedure must come from the customer."),
    ("A.8.7", "Protection against malware", ["SI-3"], "Agent coverage and detections are not evaluated."),
    ("A.8.8", "Management of technical vulnerabilities", ["RA-5"], "Vulnerability findings and remediation timelines are not queried."),
    ("A.8.15", "Logging", ["AU-2 / AU-12", "AU-6", "AU-4 / AU-11"], "Retention and protection of logs are not collected."),
    ("A.8.16", "Monitoring activities", ["SI-4", "AU-6"], "Monitoring volume is shown; review cadence is not."),
    ("A.8.20 / A.8.22", "Network security; segregation of networks", ["SC-7"], "Rules, denied traffic and segmentation are not evaluated."),
]
CMMC = [
    ("AC.L1-3.1.1", "Authorized access control", ["AC-2"], "Account-review cadence is not evidenced by telemetry."),
    ("AC.L2-3.1.8", "Unsuccessful logon attempts", ["AC-7"], "Lockout and throttling configuration not collected."),
    ("IA.L1-3.5.1 / IA.L1-3.5.2", "Identify and authenticate users", ["IA-2 / IA-5"], "Registration is not enforcement."),
    ("IA.L2-3.5.3", "Multifactor authentication", ["IA-2 / IA-5"], "Conditional Access enforcement and MFA coverage must be confirmed for privileged and network access."),
    ("AU.L2-3.3.1", "System auditing (create and retain audit records)", ["AU-2 / AU-12", "AU-4 / AU-11"], "Retention period not collected."),
    ("AU.L2-3.3.5", "Audit correlation", ["AU-6"], "Review cadence not evidenced."),
    ("CM.L2-3.4.1", "System baselining (inventory)", ["CM-8"], "Inventories not reconciled to a baseline."),
    ("IR.L2-3.6.1 / IR.L2-3.6.2", "Incident handling and reporting", ["IR-4 / IR-5"], "A documented response and reporting procedure must come from the customer."),
    ("RA.L2-3.11.2", "Vulnerability scan", ["RA-5"], "Scan frequency and findings not queried."),
    ("SC.L1-3.13.1", "Boundary protection", ["SC-7"], "Rules and segmentation not evaluated."),
    ("SI.L1-3.14.2", "Malicious code protection", ["SI-3"], "Agent coverage and detections not evaluated."),
    ("SI.L2-3.14.6 / SI.L2-3.14.7", "Monitor communications; identify unauthorized use", ["SI-4"], "Monitoring volume is shown; coverage of all communications is not."),
]
NOTE = {"iso": "ISO/IEC 27001:2022 Annex A", "cmmc": "CMMC 2.0 Level 2 practices (aligned to NIST SP 800-171 Rev. 2)"}


STYLE = """
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
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-46px}
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
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi,.panel{break-inside:avoid}th{position:static}.kpi,.pill,.bar i,td.ctl,.card,.read{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
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
    ap.add_argument("--framework", choices=("iso", "cmmc", "both"), default="both")
    a = ap.parse_args()
    try:
        d = json.load(open(a.summary))
        st = {r["control"]: r for r in d["rows"]}
    except (OSError, ValueError, KeyError) as e:
        sys.exit("cannot read compliance_summary.json (%s). Run compliance-assessment with --summary-json first." % e)
    fw = [("iso", ISO), ("cmmc", CMMC)] if a.framework == "both" else [(a.framework, ISO if a.framework == "iso" else CMMC)]
    cnt = collections.Counter(r["status"] for r in d["rows"])
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>ISO and CMMC Compliance Analysis</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Compliance evidence analysis</div>"
             "<h1>ISO/IEC 27001:2022 and CMMC 2.0</h1><p>Companion view of the NIST SP 800-53 evidence</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>Related, not equivalent</span></div></div></div><div class='wrap'>" % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(d.get("period", ""))))
    o.append("<div class='kpis'>%s</div>" % "".join("<div class='kpi' style='--c:%s'><b>%d</b><span>800-53 %s</span></div>" % (STATUS[k][1], cnt.get(k, 0), STATUS[k][0]) for k in STATUS))
    o.append("<div class='read'><b>Read this first.</b> The evidence is rooted in NIST SP 800-53 Rev. 5 and was collected by compliance-assessment. "
             "The rows below are <b>mapped or related</b> to it by an indicative analyst crosswalk. They are <b>not equivalent</b>: a related 800-53 status does not show an ISO control or CMMC practice is met. "
             "CMMC wording is advisory. Nothing here is an ISO certification, a CMMC assessment result or an attestation. Not observed means not collected in this run.</div>")
    csv_rows, summ = [], {}
    for num, (key, table) in enumerate(fw, 1):
        o.append("<h2><span class='n'>%d</span>%s</h2>" % (num, E(NOTE[key])))
        strong, none, need, body_rows = [], [], [], []
        for cid, title, groups, cav in table:
            rel = [(g, st[g]["status"]) if g in st else (g, None) for g in groups]
            sts = [s for _, s in rel]
            if sts and all(s == "supported" for s in sts):
                strong.append(cid)
                rc = STATUS["supported"][1]
            elif sts and all(s in ("not_observed", None) for s in sts):
                none.append(cid)
                rc = STATUS["not_observed"][1]
            else:
                need.append(cid)
                rc = STATUS["partial"][1]
            cell = "<div class='rel'>%s</div>" % "".join("<span style='--c:%s'><em></em>%s &middot; %s</span>" % (
                STATUS[s][1] if s else GRY, E(g), E(STATUS[s][0]) if s else "not in this run") for g, s in rel)
            body_rows.append("<tr><td class='ctl' style='--c:%s'>%s</td><td><b>%s</b><div class='cav'>%s</div></td><td>%s</td></tr>" % (rc, E(cid), E(title), E(cav), cell))
            for g, s in rel:
                csv_rows.append([NOTE[key], cid, title, g, s or "not in this run", cav])
        summ[key] = (strong, none, need)
        o.append("<div class='sum'><div style='--c:%s'><b>Strongest mapped (%d)</b><span>%s</span></div><div style='--c:%s'><b>Not observed (%d)</b><span>%s</span></div><div style='--c:%s'><b>Evidence still needed (%d)</b><span>%s</span></div></div>" % (
            GRN, len(strong), E(", ".join(strong) or "none"), GRY, len(none), E(", ".join(none) or "none"), AMB, len(need), E(", ".join(need) or "none")))
        o.append("<p class='sub'>The stripe shows the weakest related evidence: green when every related 800-53 group is supported, grey when none was observed, amber otherwise.</p>")
        o.append("<div class='tw'><table><thead><tr><th>Control</th><th>Title and caveat</th><th>Related 800-53 groups and status</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(body_rows))
    o.append("<div class='foot'><b>Limits</b><ul><li>The mapping is the analyst's and is indicative; confirm it against ISO/IEC 27001:2022 Annex A and the CMMC assessment guide before audit use.</li>"
             "<li>The CMMC rows follow Level 2 practices; Level 1 practices are the same wording where the identifier starts L1.</li>"
             "<li>ISO clauses 4 to 10 (the management system) are not evidenced by telemetry and are not covered.</li>"
             "<li>Statuses are the 800-53 statuses returned by compliance-assessment; a companion row never raises one.</li></ul></div></div></body></html>")
    with open(a.out, "w") as f:
        f.write("\n".join(o))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["framework", "control", "title", "related_800_53", "related_status", "caveat"])
            w.writerows(csv_rows)
    print({k: tuple(len(x) for x in v) for k, v in summ.items()}, "(strong, not observed, still needed)")


if __name__ == "__main__":
    main()
