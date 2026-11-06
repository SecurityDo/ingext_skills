#!/usr/bin/env python3
"""Render the Shadow AI Assessment (HTML + PDF) in the Fluency editorial style.

  render_report.py findings.json [OUT_DIR] [--date DDMonYY] [--no-pdf]

Writes Shadow_AI_Assessment_<Tenant>_<DDMonYY>.html and .pdf. The layout is fixed; findings.json supplies the words and
numbers (shape of assets/sample_findings.json, the original skill's schema). Posture is recomputed from the path
risks (rating_rules.json); a mismatch is reported. Text fields are HTML: escape & < > as &amp; &lt; &gt;.
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

RULES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "rating_rules.json")))
ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
RISK_TAG = {"high": ("High", "red"), "medium": ("Medium", "amber"), "low": ("Low", "o-blue"), "none": ("None", "gray")}
SEV_ROW = {"high": "sev-high", "medium": "sev-med", "low": "sev-low"}
PATH_NAME = {"saas": "SaaS AI (Entra)", "network": "Network egress", "endpoint": "Endpoint software", "data": "Data exposure", "detection": "Detection coverage"}
HORIZON = ["Immediate", "30 days", "90 days"]


def plain(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&")


def posture(paths):
    lv = [p["risk"] for p in paths if p["status"] == "assessed"]
    top = max(lv or ["none"], key=lambda k: ORDER[k])
    lad = RULES["posture"]["ladder"]; i = lad.index(RULES["posture"]["base"][top])
    if sum(1 for k in lv if ORDER[k] >= 2) >= RULES["posture"]["raise_if_paths_medium_or_worse"]:
        i = min(i + 1, len(lad) - 1)
    return lad[i]


def pathtag(p):
    return fb.tag("Not assessed", "gray") if p["status"] != "assessed" else fb.tag(*RISK_TAG[p["risk"]])


def build(d, out_dir, date_override=None, pdf=True):
    when = datetime.datetime.strptime(d["assessment_date"], "%Y-%m-%d"); tenant = d["tenant"]
    stamp = date_override or when.strftime("%d%b%y")
    post = posture(d["paths"])
    if d.get("posture") and d["posture"] != post:
        print("note: posture %r in the findings differs from the computed %r; using the computed value" % (d["posture"], post))
    k = d["kpis"]
    kpis = [fb.kpi("Posture", post, color={"High": "red", "Elevated": "red", "Moderate": "amber"}.get(post, "")),
            fb.kpi("AI services", k["ai_services"]), fb.kpi("Users", k["users"]), fb.kpi("Hosts", k["hosts"]),
            fb.kpi("High-risk apps", k["high_risk_apps"], color="red" if k["high_risk_apps"] else ""),
            fb.kpi("Local LLM hosts", k["local_llm_hosts"], color="red" if k["local_llm_hosts"] else "")]
    body = fb.section(1, "Executive summary", "".join("<p>%s</p>" % p for p in d["executive_summary"]))
    body += '<div class="callout act"><h4>Why this posture</h4><p>%s</p></div>' % d["posture_reason"]
    rows = [[PATH_NAME[p["id"]], pathtag(p), p["headline"], "; ".join("%s %s" % (m["value"], m["label"]) for m in p["metrics"]) or "-"] for p in d["paths"]]
    body += fb.section(2, "Five evidence paths", fb.table(["Path", "Risk", "What the evidence shows", "Key figures"], rows, widths=["17%", "15%", "44%", "24%"], raw_cols=(0, 1, 2, 3),
                       row_class=lambda r, ps=d["paths"]: next((SEV_ROW.get(p["risk"], "sev-low") if p["status"] == "assessed" else "sev-low" for p in ps if PATH_NAME[p["id"]] == r[0]), "sev-low")))
    if d["services"]:
        sr = [[s["service"], s["category"], s["tier"], s["users"] or "-", s["hosts"] or "-", s["status"].capitalize(), fb.tag(*RISK_TAG[s["risk"]])] for s in d["services"]]
        body += fb.section(3, "AI services observed", fb.table(["Service", "Category", "Tier", "Users", "Hosts", "Approval", "Risk"], sr,
                           widths=["24%", "20%", "7%", "9%", "9%", "17%", "14%"], num_cols=(3, 4), raw_cols=(6,)))
        if not d.get("sanctioned_list_provided"):
            body += fb.note("No approved-AI list was supplied, so approval is shown as unverified rather than unsanctioned. Tier 1: consumer tools that may keep or train on prompts; Tier 2: reputable vendors whose consumer tiers lack enterprise controls; Tier 3: enterprise offerings.")
    if d["findings"]:
        items = []
        for i, f in enumerate(d["findings"], 1):
            items.append('<div style="break-inside:avoid"><h3>%02d &nbsp;%s</h3><p style="margin:-4px 0 6px">%s</p>%s<p class="fn">Path: %s &middot; Evidence: %s%s</p></div>' % (
                i, f["title"], fb.tag(*RISK_TAG[f["severity"]]),
                fb.table(["What we found"], [[f["detail"]]], widths=["100%"], raw_cols=(0,), row_class=lambda r, s=f["severity"]: SEV_ROW[s]),
                PATH_NAME[f["path"]], f["evidence"], (" &middot; MITRE: %s" % f["mitre"]) if f.get("mitre") else ""))
        body += fb.section(4, "Key findings", "".join(items))
    steps = [(r["horizon"], "<b>%s.</b> %s <span class=\"fn\">Owner: %s</span>" % (r["title"], r["detail"], r["owner"])) for h in HORIZON for r in d["recommendations"] if r["horizon"] == h]
    if d["detections_to_add"]:
        body += fb.section(5, "Proposed continuous detections", fb.table(["Detection", "Logic", "Path"], [[x["name"], x["logic"], PATH_NAME[x["path"]]] for x in d["detections_to_add"]], widths=["30%", "52%", "18%"]))
    body += fb.section(6, "Coverage gaps", "<ul>%s</ul>" % "".join("<li>%s</li>" % g for g in d["coverage_gaps"]))
    ev = "".join("<li>%s: %s %s</li>" % (e["source"], e["reference"], e.get("note", "")) for e in d["evidence"])
    method = ("<p>Five evidence paths are assessed where data exists: SaaS AI through Entra applications and user grants, network egress, endpoint "
              "software, data exposure and detection coverage. A path without data is reported as not assessed, never as clean. Posture is the highest "
              "assessed path risk (None or Low: Low; Medium: Moderate; High: Elevated), raised one level when three or more paths are Medium or worse. "
              "Numeric cut-offs not stated in the original assessment are Fluency proposals (assets/rating_rules.json). Counts only: no users, hosts or addresses are named.</p><ul>%s</ul>" % ev)
    title = "Shadow AI Assessment"
    doc = fb.page(title, "Shadow AI · CISO briefing", body=body, steps=steps,
                  subtitle="Where generative AI is already in use at %s, how it is connected to company data, and what is not yet visible." % plain(tenant),
                  meta="Prepared by Fluency Security · Prepared for: %s · Assessment date: %s" % (d.get("prepared_for", "CISO"), when.strftime("%d %B %Y")),
                  kpis=kpis, method=method, footer_left="Fluency Security · Shadow AI Assessment · %s" % plain(tenant), data_date=when.strftime("%d %b %Y"))
    os.makedirs(out_dir, exist_ok=True)
    base = "Shadow_AI_Assessment_%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "", plain(tenant)), stamp)
    hp = os.path.join(out_dir, base + ".html"); open(hp, "w", encoding="utf-8").write(doc); out = [hp]
    if pdf:
        try:
            pp = os.path.join(out_dir, base + ".pdf"); fb.to_pdf(hp, pp, title=title); out.append(pp)
        except Exception as e:
            print("PDF step skipped (%s)" % e)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("findings"); ap.add_argument("out_dir", nargs="?", default=".")
    ap.add_argument("--date"); ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    for p in build(json.load(open(a.findings, encoding="utf-8")), a.out_dir, a.date, not a.no_pdf):
        print(p)


if __name__ == "__main__":
    main()
