#!/usr/bin/env python3
"""Render a FedRAMP (NIST SP 800-53 Rev. 5 baselines) companion view of the NIST 800-53 evidence (HTML + CSV).

  build_report.py --summary compliance_summary.json --out report.html [--csv report.csv] --tenant NAME --site Develop

compliance_summary.json is written by `compliance-assessment/scripts/build_report.py --summary-json`. This script
collects nothing. Each row lists the 800-53 control groups it relates to, with their statuses exactly as returned.
The mapping is an indicative analyst crosswalk, labelled as such; related is not equivalent, and nothing here is a FedRAMP authorization, a 3PAO assessment or an Authority to Operate.
"""
import argparse, collections, csv, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B"
STATUS = {"supported": ("Supported", GRN), "partial": ("Partial", AMB), "not_observed": ("Not observed", GRY), "needs_manual_review": ("Needs manual review", "#1D4ED8")}
META = {'authority': 'the FedRAMP PMO, a Third Party Assessment Organization (3PAO) and the authorizing official',
 'eyebrow': 'Federal cloud authorization evidence',
 'full': 'FedRAMP (NIST SP 800-53 Rev. 5 baselines)',
 'name': 'FedRAMP',
 'note': 'NIST SP 800-53 Rev. 5 controls in the FedRAMP Low, Moderate and High baselines',
 'result': 'a FedRAMP authorization, a 3PAO assessment or an Authority to Operate',
 'sub': 'Control-level view of the NIST SP 800-53 evidence',
 'title': 'FedRAMP Rev. 5 baselines'}
ROWS = [('AU-2, AU-12',
  'Event logging; audit record generation',
  ['AU-2 / AU-12'],
  'FedRAMP sets the auditable events and parameters; they were not compared.'),
 ('AU-4, AU-11',
  'Audit log storage capacity; audit record retention',
  ['AU-4 / AU-11'],
  'Retention and capacity are baseline parameters and were not collected.'),
 ('AU-6', 'Audit record review, analysis and reporting', ['AU-6'], 'Review frequency is a baseline parameter and is not evidenced.'),
 ('SI-4', 'System monitoring', ['SI-4'], 'Monitoring volume is shown; monitoring of inbound and outbound traffic is not evaluated.'),
 ('IR-4, IR-5',
  'Incident handling; incident monitoring',
  ['IR-4 / IR-5'],
  'The incident response plan and US-CERT reporting must come from the provider.'),
 ('AC-2', 'Account management', ['AC-2'], 'Account types, inactivity and review parameters were not evaluated.'),
 ('AC-7', 'Unsuccessful logon attempts', ['AC-7'], 'FedRAMP sets the lockout threshold and duration; the configuration was not collected.'),
 ('IA-2, IA-5',
  'Identification and authentication; authenticator management',
  ['IA-2 / IA-5'],
  'MFA registration is not enforcement; FIPS-validated authenticators were not checked.'),
 ('CM-8', 'System component inventory', ['CM-8'], 'Inventories were not reconciled to the inventory in the System Security Plan.'),
 ('RA-5',
  'Vulnerability monitoring and scanning',
  ['RA-5'],
  'Scan frequency and remediation timelines are baseline parameters and were not evidenced.'),
 ('SC-7', 'Boundary protection', ['SC-7'], 'The authorization boundary, rules and segmentation were not evaluated.'),
 ('SI-3', 'Malicious code protection', ['SI-3'], 'Agent coverage and detections were not evaluated.'),
 ('AC-1, IA-1, IR-1', 'Policy and procedures', ['AC-1 / IA-1 / IR-1'], 'Policies are provider documents.')]
NOT_COVERED = ['The authorization boundary, the System Security Plan and the control implementation statements',
 'Moderate and High baseline control enhancements for these controls (for example account and audit enhancements) and every other control family in '
 'the baseline',
 'FedRAMP parameter values (for example lockout, retention and scan frequency), which the baseline sets',
 'FIPS 140 validated cryptography, supply chain and personnel controls',
 'Continuous monitoring deliverables and the Plan of Action and Milestones (POA&M)',
 'The 3PAO assessment and the authorization decision']
EXTRA_LIMITS = ['All 13 control groups here are present in the FedRAMP Low, Moderate and High baselines; the Moderate and High baselines add enhancements that were '
 'not evaluated.']

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
    o.append("<div class='kpis'>%s</div>" % "".join("<div class='kpi' style='--c:%s'><b>%d</b><span>800-53 %s</span></div>" % (STATUS[k][1], cnt.get(k, 0), STATUS[k][0]) for k in STATUS))
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
    o.append("<h2><span class='n'>1</span>%s</h2>" % E(META["note"]))
    o.append("<div class='sum'><div style='--c:%s'><b>Strongest mapped (%d)</b><span>%s</span></div><div style='--c:%s'><b>Not observed (%d)</b><span>%s</span></div><div style='--c:%s'><b>Evidence still needed (%d)</b><span>%s</span></div></div>" % (
        GRN, len(strong), E(", ".join(strong) or "none"), GRY, len(none), E(", ".join(none) or "none"), AMB, len(need), E(", ".join(need) or "none")))
    o.append("<p class='sub'>The stripe shows the weakest related evidence: green when every related 800-53 group is supported, grey when none was observed, amber otherwise.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Requirement</th><th>Title and caveat</th><th>Related 800-53 groups and status</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(body_rows))
    o.append("<h2><span class='n'>2</span>Not evidenced by telemetry</h2><p class='sub'>These parts of %s are outside what this report can show, so a clean table is not a clean bill of health.</p>" % E(META["name"]))
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
