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
    ap.add_argument("--framework", choices=("iso", "cmmc", "both"), default="both")
    a = ap.parse_args()
    try:
        d = json.load(open(a.summary))
        st = {r["control"]: r for r in d["rows"]}
    except (OSError, ValueError, KeyError) as e:
        sys.exit("cannot read compliance_summary.json (%s). Run compliance-assessment with --summary-json first." % e)
    fw = [("iso", ISO), ("cmmc", CMMC)] if a.framework == "both" else [(a.framework, ISO if a.framework == "iso" else CMMC)]
    css = ("body{font-family:Arial,Helvetica,sans-serif;color:#1e293b;max-width:1000px;margin:24px auto;padding:0 16px;font-size:13px}"
           "h1{color:%s;margin:0}h2{color:%s;border-bottom:2px solid %s;padding-bottom:4px;margin-top:28px}"
           "table{border-collapse:collapse;width:100%%;margin:6px 0}th,td{border:1px solid #cbd5e1;padding:4px 8px;text-align:left;vertical-align:top}"
           "th{background:#f1f5f9}.muted{color:%s}.box{border:1px solid #cbd5e1;border-left:5px solid %s;padding:10px 14px;margin:10px 0;background:#f8fafc}") % (NAVY, NAVY, NAVY, GRY, NAVY)
    o = ["<!doctype html><html><head><meta charset='utf-8'><title>ISO and CMMC Compliance Analysis</title><style>%s</style></head><body>" % css,
         "<h1>ISO/IEC 27001 and CMMC Compliance Analysis</h1><p class='muted'>%s &middot; %s &middot; period %s</p>" % (E(a.tenant), E(a.site), E(d.get("period", ""))),
         "<div class='box'><b>Read this first.</b> The evidence is rooted in NIST SP 800-53 Rev. 5 and was collected by compliance-assessment. "
         "These companion rows are <b>mapped or related</b> to that evidence by an indicative analyst crosswalk. They are <b>not equivalent</b>: "
         "an ISO control or CMMC practice is not shown to be met by a related 800-53 status. CMMC wording is advisory. "
         "Nothing here is an ISO certification, a CMMC assessment result or an attestation. Not observed means not collected in this run.</div>"]
    csv_rows = []
    summ = {}
    for key, table in fw:
        o.append("<h2>%s</h2><table><thead><tr><th>Control</th><th>Title</th><th>Related 800-53 controls and status</th><th>Caveat</th></tr></thead><tbody>" % E(NOTE[key]))
        strong, none, need = [], [], []
        for cid, title, groups, cav in table:
            rel = [(g, st[g]["status"]) if g in st else (g, None) for g in groups]
            cell = "<br>".join("%s %s" % (E(g), pill(s) if s else "<span class='muted'>not in this run</span>") for g, s in rel)
            o.append("<tr><td style='white-space:nowrap'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (E(cid), E(title), cell, E(cav)))
            sts = [s for _, s in rel]
            if sts and all(s == "supported" for s in sts):
                strong.append(cid)
            elif sts and all(s in ("not_observed", None) for s in sts):
                none.append(cid)
            else:
                need.append(cid)
            for g, s in rel:
                csv_rows.append([NOTE[key], cid, title, g, s or "not in this run", cav])
        summ[key] = (strong, none, need)
        o.append("</tbody></table>")
        o.append("<p><b>Strongest mapped areas</b> (every related 800-53 group supported): %s.<br><b>Not observed</b> (every related group not observed): %s.<br>"
                 "<b>Evidence still required before audit or assessor use</b> (partial, mixed or manual review): %s.</p>" % (
                     E(", ".join(strong) or "none"), E(", ".join(none) or "none"), E(", ".join(need) or "none")))
    o.append("<h2>Limits</h2><ul><li>The mapping is the analyst's and is indicative; confirm it against ISO/IEC 27001:2022 Annex A and the CMMC assessment guide before audit use.</li>"
             "<li>The CMMC rows follow Level 2 practices; Level 1 practices are the same wording where the identifier starts L1.</li>"
             "<li>ISO clauses 4 to 10 (the management system) are not evidenced by telemetry and are not covered.</li>"
             "<li>Statuses are the 800-53 statuses returned by compliance-assessment; a companion row never raises one.</li></ul></body></html>")
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
