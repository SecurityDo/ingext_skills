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


def pill(s):
    lbl, col = STATUS.get(s, (s, GRY))
    return '<span style="background:%s;color:#fff;border-radius:3px;padding:1px 7px;font-size:11px;white-space:nowrap">%s</span>' % (col, E(lbl))


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
    period = d.get("period", "")
    unlocked = [(r["control"], NEXT.get(r["control"], "")) for r in rows if r["status"] in ("not_observed", "partial")]
    css = ("body{font-family:Arial,Helvetica,sans-serif;color:#1e293b;max-width:1000px;margin:24px auto;padding:0 16px;font-size:13px}"
           "h1{color:%s;margin:0}h2{color:%s;border-bottom:2px solid %s;padding-bottom:4px;margin-top:28px}"
           "table{border-collapse:collapse;width:100%%;margin:6px 0}th,td{border:1px solid #cbd5e1;padding:4px 8px;text-align:left;vertical-align:top}"
           "th{background:#f1f5f9}.muted{color:%s}.box{border:1px solid #cbd5e1;border-left:5px solid %s;padding:10px 14px;margin:10px 0;background:#f8fafc}"
           ".kpi{display:inline-block;border:1px solid #cbd5e1;border-radius:6px;padding:8px 14px;margin:0 8px 8px 0}.kpi b{display:block;font-size:22px}") % (NAVY, NAVY, NAVY, GRY, NAVY)
    o = ["<!doctype html><html><head><meta charset='utf-8'><title>NIST 800-53 Compliance Analysis</title><style>%s</style></head><body>" % css]
    o.append("<h1>NIST SP 800-53 Rev. 5 Compliance Analysis</h1><p class='muted'>%s &middot; %s &middot; period %s</p>" % (E(a.tenant), E(a.site), E(period)))
    o.append("<div class='box'><b>Scope.</b> Framework: NIST SP 800-53 Rev. 5, the root framework; %d control groups. "
             "<b>Live evidence:</b> collected from the tenant's connector for the period above, by compliance-assessment. "
             "It is a reduced, evidence-led view, not the full control catalogue. It does not certify or attest compliance, and "
             "\"not observed\" means the evidence was not collected in this run, not that a control failed.</div>" % len(rows))
    o.append("".join("<div class='kpi'><b style='color:%s'>%d</b>%s</div>" % (STATUS[k][1], cnt.get(k, 0), STATUS[k][0]) for k in STATUS))
    o.append("<h2>Control by control</h2><table><thead><tr><th>Control</th><th>Title</th><th>Status</th><th>Evidence state</th><th>What the evidence showed</th><th>Next evidence</th></tr></thead><tbody>")
    for r in rows:
        nxt = NEXT.get(r["control"], "") if r["status"] != "supported" else "Maintain; re-collect next period"
        o.append("<tr><td style='white-space:nowrap'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            E(r["control"]), E(r["title"]), pill(r["status"]), E(EVIDENCE_STATE.get(r["status"], "")), E(r.get("evidence", "")), E(nxt)))
    o.append("</tbody></table>")
    o.append("<h2>Highest-value evidence to collect next</h2>")
    if unlocked:
        # group controls that share a next-evidence source
        o.append("<ol>%s</ol>" % "".join("<li><b>%s</b>: %s</li>" % (E(c), E(n)) for c, n in unlocked))
    else:
        o.append("<p>Every control group has evidence in this run.</p>")
    if a.view:
        o.append("<h2>Child view: %s</h2><p class='muted'>Indicative category-level crosswalk, the analyst's mapping and not NIST's official one; confirm against NIST's published mappings before relying on it. The 800-53 control stays the lineage.</p>" %
                 ("CSF 2.0 and NIST SP 800-171 Rev. 3" if a.view == "both" else "CSF 2.0" if a.view == "csf" else "NIST SP 800-171 Rev. 3"))
        heads = ["800-53 control", "Status"] + (["CSF 2.0 category"] if a.view in ("csf", "both") else []) + (["800-171 Rev. 3 family"] if a.view in ("800-171", "both") else [])
        o.append("<table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % h for h in heads))
        for r in rows:
            c = CROSS.get(r["control"], ("not mapped", "not mapped"))
            cells = [E(r["control"]), pill(r["status"])] + ([E(c[0])] if a.view in ("csf", "both") else []) + ([E(c[1])] if a.view in ("800-171", "both") else [])
            o.append("<tr>%s</tr>" % "".join("<td>%s</td>" % x for x in cells))
        o.append("</tbody></table>")
    o.append("<h2>Limits</h2><ul><li>Statuses and evidence text come from compliance-assessment and are used as returned.</li>"
             "<li>Resource-table counts are snapshots as of the dump; event counts are for the period.</li>"
             "<li>Policy and procedure controls can only be evidenced by customer documents.</li>"
             "<li>Never read this as certification, attestation or full compliance.</li></ul></body></html>")
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
