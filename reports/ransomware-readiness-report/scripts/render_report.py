#!/usr/bin/env python3
"""Render the Ransomware Readiness board report (HTML + PDF) in the Fluency editorial style.

  render_report.py findings.json [OUT_DIR] [--date DDMonYY] [--no-pdf]

Writes Ransomware_Readiness_<Tenant>_<DDMonYY>.html and .pdf. The layout is fixed; the findings file supplies the
words and numbers. The overall rating is computed from the pillar statuses (see rate()), not taken on trust.
Schema: assets/sample_findings_acme.json. Text fields are HTML: escape & < > as &amp; &lt; &gt;.
"""
import argparse, datetime, json, os, re, sys
import os as _os, sys as _sys, glob as _glob
def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
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
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

SEV_TAG = {"Critical": "red", "High": "amber", "Medium": "blue"}
SEV_ROW = {"Critical": "sev-high", "High": "sev-med", "Medium": "sev-low"}
PILLAR_TAG = {"red": ("At risk", "red"), "amber": ("Needs work", "amber"), "green": ("Healthy", "o-blue")}
KEY = ("backup", "endpoint", "prevention")      # a red pillar here makes the whole posture "Elevated Risk"


def rate(pillars):
    """Overall rating from the pillar statuses (playbook scoring guidance)."""
    red = [p for p in pillars if p["status"] == "red"]
    amber = [p for p in pillars if p["status"] == "amber"]
    if any(k in re.sub(r"&amp;|[^a-z ]", "", p["name"].lower()) for p in red for k in KEY):
        return "Elevated Risk"
    if len(red) >= 2:
        return "High Risk"
    if not red and not amber:
        return "Resilient"
    return "Moderate Risk"


def plain(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&")


def build(d, out_dir, date_override=None, pdf=True):
    when = datetime.datetime.strptime(d["assessment_date"], "%Y-%m-%d")
    tenant = d["tenant"]
    stamp = date_override or when.strftime("%d%b%y")
    rating = rate(d["pillars"])
    if d.get("overall_rating") and d["overall_rating"] != rating:
        print("note: overall_rating %r in the findings differs from the computed %r; using the computed value" % (d["overall_rating"], rating))
    n = {s: sum(1 for i in d["issues"] if i["severity"] == s) for s in ("Critical", "High", "Medium")}
    rating_tag = {"Elevated Risk": "red", "High Risk": "red", "Moderate Risk": "amber", "Resilient": "o-blue"}[rating]
    kpis = [fb.kpi("Overall rating", rating, color={"red": "red", "amber": "amber"}.get(rating_tag, "")),
            fb.kpi("Critical issues", n["Critical"], color="red" if n["Critical"] else ""),
            fb.kpi("High issues", n["High"], color="amber" if n["High"] else ""),
            fb.kpi(d.get("kpi_label", "Secure score"), d.get("kpi_value", "n/a"))]

    # 1. Executive summary
    body = fb.section(1, d["summary_headline"].replace("&amp;", "&"), "<p>%s</p>" % d["summary"])
    body += '<div class="callout act"><h4>Board ask</h4><p>%s</p></div>' % (d["board_ask"][:1].upper() + d["board_ask"][1:])

    # 2. Scorecard: eight pillars
    rows = [[p["name"], fb.tag(*PILLAR_TAG[p["status"]]), p["detail"]] for p in d["pillars"]]
    body += fb.section(2, "Eight pillars of ransomware resilience",
                       fb.table(["Pillar", "Status", "What the evidence shows"], rows, widths=["26%", "16%", "58%"], raw_cols=(0, 1, 2),
                                row_class=lambda r: {"red": "sev-high", "amber": "sev-med"}.get(
                                    next((p["status"] for p in d["pillars"] if p["name"] == r[0]), ""), "sev-low")))

    # 3. Priority findings
    items = []
    for i, it in enumerate(d["issues"], 1):
        head = '<h3>%02d &nbsp;%s</h3><p style="margin:-4px 0 6px">%s</p>' % (i, it["title"], fb.tag(it["severity"], SEV_TAG[it["severity"]]))
        two = fb.table(["What we found", "Why the board should care"], [[it["finding"], it["why"]]], widths=["58%", "42%"], raw_cols=(0, 1),
                       row_class=lambda r, s=it["severity"]: SEV_ROW[s])
        rec = '<div class="callout"><h4>Recommendation</h4><p>%s</p></div>' % it["recommendation"]
        meta = '<p class="fn">Owner: %s &middot; Target: %s &middot; MITRE: %s</p>' % (it["owner"], it["target"], it["mitre"])
        items.append('<div style="break-inside:avoid">%s%s%s%s</div>' % (head, two, rec, meta))
    body += fb.section(3, "Priority findings and recommendations", "".join(items))

    # 4. Roadmap
    rm = [[r["window"], r["actions"], r["outcome"]] for r in d["roadmap"]]
    body += fb.section(4, "90-day remediation plan", fb.table(["Window", "Actions", "Outcome"], rm, widths=["14%", "54%", "32%"], raw_cols=(0, 1, 2)))

    # 5. Strengths
    body += fb.section(5, "Strengths to maintain", "<ul>%s</ul>" % "".join("<li>%s</li>" % s for s in d["strengths"]))

    title = "Ransomware Readiness Report"
    doc = fb.page(title, "Ransomware readiness \u00b7 board confidential", body=body,
                  subtitle="An evidence-based assessment of %s\u2019s ability to prevent, withstand and recover from a ransomware attack, derived from live security telemetry." % plain(tenant),
                  meta="Prepared by Fluency Security \u00b7 Connector: %s \u00b7 Assessment date: %s \u00b7 Evidence window: %s" % (plain(tenant), when.strftime("%d %B %Y"), plain(d.get("evidence_window", ""))),
                  kpis=kpis, method="<p>%s</p>" % d["methodology"],
                  footer_left="Fluency Security \u00b7 Ransomware Readiness \u00b7 %s" % plain(tenant), data_date=when.strftime("%d %b %Y"))
    os.makedirs(out_dir, exist_ok=True)
    base = "Ransomware_Readiness_%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "", plain(tenant)), stamp)
    hp = os.path.join(out_dir, base + ".html")
    open(hp, "w", encoding="utf-8").write(doc)
    out = [hp]
    if pdf:
        try:
            pp = os.path.join(out_dir, base + ".pdf")
            fb.to_pdf(hp, pp, title=title)
            out.append(pp)
        except Exception as e:
            print("PDF step skipped (%s)" % e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings")
    ap.add_argument("out_dir", nargs="?", default=".")
    ap.add_argument("--date", help="run date stamp DDMonYY (default: the assessment date)")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    for p in build(json.load(open(a.findings, encoding="utf-8")), a.out_dir, a.date, not a.no_pdf):
        print(p)


if __name__ == "__main__":
    main()
