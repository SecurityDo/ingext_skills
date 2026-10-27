#!/usr/bin/env python3
"""Render the NIST SP 800-53 Rev. 5 control-by-control analysis (HTML + CSV) from compliance-assessment results.

  build_report.py --summary compliance_summary.json --out nist.html [--csv controls.csv] --tenant NAME --site Develop
                  [--view csf|800-171|both]

compliance_summary.json is written by `compliance-assessment/scripts/build_report.py --summary-json`. This
script collects nothing and invents nothing: statuses and evidence text are the ones that file carries, used
exactly as returned. "Not observed" means the evidence was not collected; it is never shown as a failure.
The CSF 2.0 and 800-171 views are an indicative category-level crosswalk, labelled as such.
"""
import argparse, collections, csv, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY = "#1C2B45", "#B91C1C", "#B45309", "#15803D", "#64748B"
STATUS = {"supported": ("Supported", GRN), "partial": ("Partial", AMB), "not_observed": ("Not observed", GRY), "needs_manual_review": ("Needs manual review", "#1D4ED8")}
EVIDENCE_STATE = {"supported": "Observed in the window", "partial": "Partly observed", "not_observed": "Not collected in this run (not a failure)",
                  "needs_manual_review": "Customer-supplied documents only"}
# control group -> what to collect next, in connector terms (analyst guidance)
NEXT = {
    "AU-2 / AU-12": "Another event table (list_data_tables), so two or more sources are logging",
    "SI-4": "behavior_summary_search over the window",
    "AU-6": "A review-cadence record from the customer (who reviews, how often)",
    "IR-4 / IR-5": "The customer's documented response procedure and incident tickets with owners",
    "AC-2": "office365User dump (list_resource_dumps) and an account-review record",
    "AC-7": "AzureSigninLogs events and the lockout and throttling configuration",
    "IA-2 / IA-5": "office365ConditionalAccessPolicy and office365User dumps (MFA registration)",
    "CM-8": "office365Device and qualysHost dumps, reconciled against an asset register",
    "RA-5": "qualysHost dump and a vulnerability findings export",
    "AU-4 / AU-11": "Retention settings per table and storage capacity (not available from the tools; ask the platform owner)",
    "SC-7": "A firewall or network table (FortiGate, Zscaler, Meraki and similar) and rule review",
    "SI-3": "An endpoint-protection source (SentinelOne, CrowdStrike Falcon, Defender) and agent coverage",
    "AC-1 / IA-1 / IR-1": "The customer's policy documents",
}
# indicative category-level crosswalk: CSF 2.0 category and 800-171 Rev. 3 family
CROSS = {
    "AU-2 / AU-12": ("PR.PS Platform Security; DE.CM Continuous Monitoring", "03.03 Audit and Accountability"),
    "SI-4": ("DE.CM Continuous Monitoring", "03.14 System and Information Integrity"),
    "AU-6": ("DE.AE Adverse Event Analysis", "03.03 Audit and Accountability"),
    "IR-4 / IR-5": ("RS.MA Incident Management; RS.AN Incident Analysis", "03.06 Incident Response"),
    "AC-2": ("PR.AA Identity Management, Authentication and Access Control", "03.01 Access Control"),
    "AC-7": ("PR.AA Identity Management, Authentication and Access Control", "03.01 Access Control"),
    "IA-2 / IA-5": ("PR.AA Identity Management, Authentication and Access Control", "03.05 Identification and Authentication"),
    "CM-8": ("ID.AM Asset Management", "03.04 Configuration Management"),
    "RA-5": ("ID.RA Risk Assessment", "03.11 Risk Assessment"),
    "AU-4 / AU-11": ("PR.PS Platform Security", "03.03 Audit and Accountability"),
    "SC-7": ("PR.IR Technology Infrastructure Resilience", "03.13 System and Communications Protection"),
    "SI-3": ("DE.CM Continuous Monitoring; PR.PS Platform Security", "03.14 System and Information Integrity"),
    "AC-1 / IA-1 / IR-1": ("GV.PO Policy", "03.15 Planning (policy and procedures)"),
}


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
    ap.add_argument("--view", choices=("csf", "800-171", "both"))
    a = ap.parse_args()
    try:
        d = json.load(open(a.summary))
        rows = d["rows"]
    except (OSError, ValueError, KeyError) as e:
        sys.exit("cannot read compliance_summary.json (%s). Run compliance-assessment with --summary-json first." % e)
    cnt = collections.Counter(r["status"] for r in rows)
    total = len(rows) or 1
    period = d.get("period", "")
    gaps = [(r["control"], NEXT.get(r["control"], "")) for r in rows if r["status"] in ("not_observed", "partial")]
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>NIST SP 800-53 Compliance Analysis</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Compliance evidence analysis</div>"
             "<h1>NIST SP 800-53 Rev. 5</h1><p>Control-by-control reading of the tenant's own telemetry</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d control groups</span></div></div></div><div class='wrap'>" % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(rows)))
    o.append("<div class='kpis'>%s</div>" % "".join("<div class='kpi' style='--c:%s'><b>%d</b><span>%s</span></div>" % (STATUS[k][1], cnt.get(k, 0), STATUS[k][0]) for k in STATUS))
    o.append("<div class='panel'><b>Evidence picture</b><div class='bar'>%s</div><div class='legend'>%s</div></div>" % (
        "".join("<i style='width:%.1f%%;background:%s'></i>" % (100.0 * cnt.get(k, 0) / total, STATUS[k][1]) for k in STATUS),
        "".join("<span><em style='background:%s'></em>%s %d</span>" % (STATUS[k][1], STATUS[k][0], cnt.get(k, 0)) for k in STATUS)))
    o.append("<div class='read'><b>Read this first.</b> Framework: NIST SP 800-53 Rev. 5, the root framework, as a reduced evidence-led view of %d control groups. "
             "The evidence is live for the period, collected from the tenant's connector by compliance-assessment. This is an evidence aid, not a certification or attestation. "
             "<b>Not observed</b> means the evidence was not collected in this run; it is not a failed control.</div>" % len(rows))
    o.append("<h2><span class='n'>1</span>Control by control</h2><p class='sub'>Statuses and evidence are shown exactly as compliance-assessment returned them.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Control</th><th>Title</th><th>Status</th><th>What the evidence showed</th><th>Next evidence</th></tr></thead><tbody>")
    for r in rows:
        col = STATUS.get(r["status"], ("", GRY))[1]
        nxt = NEXT.get(r["control"], "") if r["status"] != "supported" else "Maintain; re-collect next period"
        o.append("<tr><td class='ctl' style='--c:%s'>%s</td><td><b>%s</b></td><td>%s<div class='state'>%s</div></td><td>%s</td><td class='mut'>%s</td></tr>" % (
            col, E(r["control"]), E(r["title"]), pill(r["status"]), E(EVIDENCE_STATE.get(r["status"], "")), E(r.get("evidence", "")), E(nxt)))
    o.append("</tbody></table></div>")
    o.append("<h2><span class='n'>2</span>Highest-value evidence to collect next</h2><p class='sub'>Controls with partial or no evidence, and the source that would move them.</p>")
    if gaps:
        o.append("<div class='cards'>%s</div>" % "".join("<div class='card' style='--c:%s'><b>%s</b>%s</div>" % (
            STATUS[next(r["status"] for r in rows if r["control"] == c)][1], E(c), E(n)) for c, n in gaps))
    else:
        o.append("<div class='panel'>Every control group has evidence in this run.</div>")
    if a.view:
        o.append("<h2><span class='n'>3</span>Child view: %s</h2><p class='sub'>Indicative category-level crosswalk, the analyst's mapping and not NIST's official one; confirm it against NIST's published mappings before relying on it. The 800-53 control stays the lineage.</p>" %
                 ("CSF 2.0 and NIST SP 800-171 Rev. 3" if a.view == "both" else "CSF 2.0" if a.view == "csf" else "NIST SP 800-171 Rev. 3"))
        heads = ["800-53 control", "Status"] + (["CSF 2.0 category"] if a.view in ("csf", "both") else []) + (["800-171 Rev. 3 family"] if a.view in ("800-171", "both") else [])
        o.append("<div class='tw'><table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % h for h in heads))
        for r in rows:
            c = CROSS.get(r["control"], ("not mapped", "not mapped"))
            col = STATUS.get(r["status"], ("", GRY))[1]
            cells = ["<td class='ctl' style='--c:%s'>%s</td>" % (col, E(r["control"])), "<td>%s</td>" % pill(r["status"])] + (["<td>%s</td>" % E(c[0])] if a.view in ("csf", "both") else []) + (["<td>%s</td>" % E(c[1])] if a.view in ("800-171", "both") else [])
            o.append("<tr>%s</tr>" % "".join(cells))
        o.append("</tbody></table></div>")
    o.append("<div class='foot'><b>Limits</b><ul><li>Statuses and evidence text come from compliance-assessment and are used as returned.</li>"
             "<li>Resource-table counts are snapshots as of the dump; event counts are for the period.</li>"
             "<li>Policy and procedure controls can only be evidenced by customer documents.</li>"
             "<li>Never read this as certification, attestation or full compliance.</li></ul></div></div></body></html>")
    with open(a.out, "w") as f:
        f.write("\n".join(o))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["control", "title", "status", "evidence_state", "evidence", "next_evidence", "csf_2_0", "sp800_171_r3"])
            for r in rows:
                c = CROSS.get(r["control"], ("", ""))
                w.writerow([r["control"], r["title"], r["status"], EVIDENCE_STATE.get(r["status"], ""), r.get("evidence", ""), NEXT.get(r["control"], "") if r["status"] != "supported" else "", c[0], c[1]])
    print("%d control groups: %s" % (len(rows), dict(cnt)))


if __name__ == "__main__":
    main()
