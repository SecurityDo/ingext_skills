#!/usr/bin/env python3
"""Render the Regulatory Disclosure Readiness report (HTML + PDF) in the Fluency editorial style.

  render_report.py findings.json [OUT_DIR] [--date DDMonYY] [--no-pdf]

Writes Regulatory_Disclosure_Readiness_<Tenant>_<DDMonYY>.html and .pdf. findings.json is the output of rate_evidence.py
(reviewed). The layout is fixed; every text field is plain text and is escaped here. The overall rating is recomputed
from the capability statuses it shipped with only as a display check; the rating itself comes from rate_evidence.py.
"""
import argparse, datetime, json, os, re, sys
import os as _os, sys as _sys, glob as _glob


def _find_brand_kit():
    here = _os.path.dirname(_os.path.abspath(__file__)); home = _os.path.expanduser("~")
    cands = [_os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = _os.path.dirname(up); cands.append(_os.path.join(up, "fluency-report", "scripts"))
    cands += [_os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += _glob.glob(_os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and _os.path.exists(_os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")


_sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # from the fluency-report skill

e = fb.esc
READY = {"ready": ("Ready", "blue"), "partial": ("Partial", "amber"), "not ready": ("Not ready", "red"), "confirm": ("Confirm", "o-blue"), "n/a": ("Not applicable", "gray")}
SEV = {"critical": ("Critical", "red", "sev-high"), "high": ("High", "amber", "sev-med"), "medium": ("Medium", "gray", "sev-low"), "low": ("Low", "gray", "sev-low")}
CTL = {"met": ("Met", "blue"), "partial": ("Partial", "amber"), "gap": ("Gap", "red")}
RATING_KPI = {"Not ready": "red", "Partially ready": "amber", "Ready": "blue"}


def plain(s):
    return re.sub(r"<[^>]+>", "", s or "")


def rtag(k):
    t, c = READY[k]
    return fb.tag(t, c)


def build(d, out_dir, date_override=None, pdf=True):
    when = datetime.datetime.strptime(d["assessment_date"], "%Y-%m-%d"); tenant = d["tenant"]
    stamp = date_override or when.strftime("%d%b%y")
    kp = [fb.kpi("Disclosure readiness", d["readiness_rating"], color=RATING_KPI.get(d["readiness_rating"], ""))]
    for k in d["kpis"]:
        kp.append(fb.kpi(k["label"], k["value"], note=k.get("note", ""), color="red" if k["value"] in ("0", "Not evidenced") and "decision" in k["label"].lower() else ""))
    cnt = {s: sum(1 for f in d["findings"] if f["severity"] == s) for s in SEV}
    # 1 summary
    body = fb.section(1, d["headline"], "".join("<p>%s</p>" % e(p) for p in d["summary"]))
    body += fb.band([("Critical", "<p><b>%d</b></p>" % cnt["critical"]), ("High", "<p><b>%d</b></p>" % cnt["high"]), ("Medium", "<p><b>%d</b></p>" % (cnt["medium"] + cnt["low"]))])
    body += '<div class="callout act"><p class="tag">Decision</p><h4>CISO decision</h4><p>%s</p></div>' % e(d["ciso_ask"][:1].upper() + d["ciso_ask"][1:])
    # 2 regimes
    rows = []
    for r in d["regimes"]:
        clock = "<ul>%s</ul>" % "".join("<li><b>%s</b> %s</li>" % (e(c["when"]), e(c["what"])) for c in r["clock"])
        rows.append(["<b>%s</b><br>%s" % (e(r["regime"]), rtag(r["readiness"])), e(r["scope"]) + "<br><b>Applies:</b> " + e(r["applicability"]), clock, e(r["gap"])])
    body += fb.section(2, "Reporting obligations and readiness", fb.table(["Regime", "Scope and applicability", "Clock", "Gap"], rows, widths=["16%", "38%", "26%", "20%"], raw_cols=(0, 1, 2, 3)))
    body += fb.note(e(d["regimes_note"]))
    # 3 clock test
    items = [(c["step"], max(c["pct"], 0), c["color"], c["label"]) for c in d["clock_test"]]
    body += fb.section(3, "How long each step takes today versus the tightest deadline", fb.bar_rows(items, lead_blue=False, fmt=lambda v: "%d%%" % v) + '<p class="fn">%s</p>' % e(d["clock_note"]))
    # 4 capabilities
    crow = [["<b>%s</b><br><span class=\"fn\">%s</span>" % (e(c["capability"]), e(c["why"])), e(c["evidence"]), e(c["target"]), rtag(c["status"])] for c in d["capabilities"]]
    body += fb.section(4, "Disclosure capabilities measured from SIEM evidence", fb.table(["Capability", "Evidence", "Needed for", "Status"], crow, widths=["24%", "46%", "12%", "18%"], raw_cols=(0, 1, 2, 3)))
    # 5 register
    brow = [["<b>%s</b>" % e(b["bucket"]), e(b["count"]), e(b["note"])] for b in d["backlog"]]
    body += fb.section(5, "Open and unclassified security cases", fb.table(["Bucket", "Cases", "What it means for disclosure"], brow, widths=["36%", "10%", "54%"], num_cols=(1,), raw_cols=(0, 1, 2)))
    # 6 findings
    items = []
    for i, f in enumerate(d["findings"], 1):
        lab, kind, rc = SEV[f["severity"]]
        det = fb.table(["What we found", "Why it matters"], [[f["finding"], f["risk"]]], widths=["50%", "50%"], row_class=lambda r, c=rc: c)
        items.append('<div style="break-inside:avoid"><h3>%02d &nbsp;%s</h3><p style="margin:-4px 0 6px">%s</p>%s<p><b>Recommendation.</b> %s</p><p class="fn">Owner: %s &middot; Target: %s%s</p></div>' % (
            i, e(f["title"]), fb.tag(lab, kind), det, e(f["recommendation"]), e(f["owner"]), e(f["timeframe"]), (" &middot; MITRE: %s" % e(f["mitre"])) if f.get("mitre") and f["mitre"] != "-" else ""))
    body += fb.section(6, "Readiness findings", "".join(items))
    # 7 control map
    mrow = [["<b>%s</b>" % e(c["control"]), e(c["frameworks"]), fb.tag(*CTL[c["status"]]), e(c["evidence"])] for c in d["control_map"]]
    body += fb.section(7, "Incident-reporting requirements against evidence", fb.table(["Control", "Framework references", "Status", "Evidence"], mrow, widths=["28%", "24%", "10%", "38%"], raw_cols=(0, 1, 2, 3)))
    # 8 strengths / gaps / detections
    if d["strengths"]:
        body += fb.section(8, "What is already working", "<ul>%s</ul>" % "".join("<li>%s</li>" % e(s) for s in d["strengths"]))
    body += fb.section(9, "Proposed continuous detections", fb.table(["Detection", "Logic"], [[x["name"], x["logic"]] for x in d["detections_to_add"]], widths=["30%", "70%"]))
    body += fb.section(10, "Coverage gaps", "<ul>%s</ul>" % "".join("<li>%s</li>" % e(g) for g in d["coverage_gaps"]))
    ev = "".join("<li>%s: %s</li>" % (e(x["source"]), e(x["reference"])) for x in d["evidence"])
    method = ("<p>Measured read-only from %s's Fluency / Ingext tenant on %s: the %d-day case register (behavior summaries at risk 3,000 or more), the open cases and a closed sample, "
              "the earliest event held in the key log tables, and the log sources present. Time to triage and to a human decision come from the case comment thread. "
              "Readiness for each regime is the worst of the capabilities its clock depends on; the overall rating is Not ready when an escalated case has no human decision beyond the tightest deadline, "
              "when a quarter or more of open cases are older than 14 days, or when no reportability determination exists. Cut-offs not stated in the original assessment are Fluency proposals "
              "(assets/rating_rules.json). Regulatory summaries are for readiness planning, not legal advice. Counts only: no individuals, hosts or addresses are named.</p><ul>%s</ul>" % (e(tenant), when.strftime("%d %B %Y"), d["window_days"], ev))
    title = "Regulatory Disclosure Readiness"
    doc = fb.page(title, "Board Rpt 3 · Board confidential", body=body,
                  subtitle="Could %s detect, assess and report a significant cyber incident inside the deadlines set by the SEC (Form 8-K), the EU NIS2 Directive and DORA, and its customer contracts? Measured from SIEM evidence over the last %d days." % (plain(tenant), d["window_days"]),
                  meta="Prepared by Fluency Security · Connector: %s · %s · Window: %s" % (plain(tenant), when.strftime("%d %B %Y"), d["period_label"]),
                  kpis=kp, method=method, footer_left="Fluency Security · Board Rpt 3 · Regulatory Disclosure Readiness", data_date=when.strftime("%d %b %Y"))
    os.makedirs(out_dir, exist_ok=True)
    base = "Regulatory_Disclosure_Readiness_%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "", plain(tenant)), stamp)
    hp = os.path.join(out_dir, base + ".html"); open(hp, "w", encoding="utf-8").write(doc); out = [hp]
    if pdf:
        try:
            pp = os.path.join(out_dir, base + ".pdf"); fb.to_pdf(hp, pp, title=title); out.append(pp)
        except Exception as ex:
            print("PDF step skipped (%s)" % ex)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("findings"); ap.add_argument("out_dir", nargs="?", default=".")
    ap.add_argument("--date"); ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    for p in build(json.load(open(a.findings, encoding="utf-8")), a.out_dir, a.date, not a.no_pdf):
        print(p)


if __name__ == "__main__":
    main()
