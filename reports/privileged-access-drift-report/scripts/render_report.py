#!/usr/bin/env python3
"""Render the Privileged Access Drift report (HTML + PDF) in the Fluency editorial style.

  render_report.py findings.json [OUT_DIR] [--date DDMonYY] [--no-pdf]

Writes Privileged_Access_Drift_<Tenant>_<DDMonYY>.html and .pdf. findings.json is the output of rate_evidence.py (reviewed). The layout
is fixed; every text field is plain text and is escaped here. Uses the Fluency brand kit of the `fluency-report` skill.
"""
import argparse, datetime, json, os, re
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
SEV = {"critical": ("Critical", "red", "sev-high"), "high": ("High", "amber", "sev-med"), "medium": ("Medium", "gray", "sev-low"), "low": ("Low", "gray", "sev-low")}
KIND = {"drift": ("Drift", "red"), "good": ("Hardening", "blue"), "change": ("Change", "gray")}
TIER = {0: ("Tier 0", "red"), 1: ("Tier 1", "amber"), 2: ("Tier 2", "blue")}
RATING_KPI = {"High": "red", "Elevated": "amber", "Moderate": "gray", "Low": "blue"}


def plain(s):
    return re.sub(r"<[^>]+>", "", s or "")


def build(d, out_dir, date_override=None, pdf=True):
    when = datetime.datetime.strptime(d["assessment_date"], "%Y-%m-%d"); tenant = d["tenant"]
    stamp = date_override or when.strftime("%d%b%y")
    kp = [fb.kpi("Drift rating", d["drift_rating"], color=RATING_KPI.get(d["drift_rating"], ""))] + [fb.kpi(k["label"], k["value"], note=k.get("note", "")) for k in d["kpis"]]
    cnt = {s: sum(1 for f in d["findings"] if f["severity"] == s) for s in SEV}
    body = fb.section(1, d["headline"], "".join("<p>%s</p>" % e(p) for p in d["summary"]))
    body += fb.band([("Critical", "<p><b>%d</b></p>" % cnt["critical"]), ("High", "<p><b>%d</b></p>" % cnt["high"]), ("Medium", "<p><b>%d</b></p>" % (cnt["medium"] + cnt["low"]))])
    body += '<div class="callout act"><p class="tag">Decision</p><h4>CISO decision</h4><p>%s</p></div>' % e(d["ciso_ask"][:1].upper() + d["ciso_ask"][1:])
    if d["timeline"]:
        trow = [["<b>%s</b>" % e(t["date"]), fb.tag(*KIND[t["kind"]]), e(t["event"])] for t in d["timeline"]]
        body += fb.section(2, "Privilege changes, %s" % e(d["period_label"]), fb.table(["When", "Kind", "What happened"], trow, widths=["16%", "12%", "72%"], raw_cols=(0, 1, 2)))
    items = []
    for i, f in enumerate(d["findings"], 1):
        lab, kind, rc = SEV[f["severity"]]
        det = fb.table(["What changed", "Why it matters"], [[f["finding"], f["risk"]]], widths=["50%", "50%"], row_class=lambda r, c=rc: c)
        items.append('<div style="break-inside:avoid"><h3>%02d &nbsp;%s</h3><p style="margin:-4px 0 6px">%s</p>%s<p><b>Recommendation.</b> %s</p><p class="fn">Owner: %s &middot; Target: %s%s</p></div>' % (
            i, e(f["title"]), fb.tag(lab, kind), det, e(f["recommendation"]), e(f["owner"]), e(f["timeframe"]), (" &middot; MITRE: %s" % e(f["mitre"])) if f.get("mitre") else ""))
    body += fb.section(3, "Where privilege has drifted", "".join(items) if items else "<p>No finding crossed a rating rule in this window.</p>")
    if d["non_human"]:
        nrow = [["<b>%s</b><br><span class=\"fn\">%s</span>" % (e(x["identity"]), e(x["publisher"])), e(datetime.datetime.strptime(x["granted"], "%Y-%m-%d").strftime("%d %b").lstrip("0") if len(x["granted"]) == 10 else x["granted"]), e(", ".join(x["permissions"][:8]) + (" and %d more" % (len(x["permissions"]) - 8) if len(x["permissions"]) > 8 else "")), fb.tag(*TIER[x["tier"]])] for x in d["non_human"]]
        body += fb.section(4, "Applications granted privilege in the window", fb.table(["Application", "Granted", "Permissions", "Tier"], nrow, widths=["28%", "10%", "50%", "12%"], raw_cols=(0, 1, 2, 3)) +
                           '<p class="fn">Tier 0 = can take over the tenant (assign roles, change Conditional Access or authentication methods, create app credentials, read LAPS or BitLocker keys). Tier 1 = tenant-wide read or write of business data. Tier 2 = scoped or read-only operational access.</p>')
    rrow = [["<b>%s</b>" % e(r["role"]), str(r["holders"]), str(r["enabled"]), str(r["disabled"]), e(r["note"])] for r in d["role_inventory"]]
    body += fb.section(5, "Directory role holders today", fb.table(["Role", "Holders", "Enabled", "Disabled", "Note"], rrow, widths=["34%", "10%", "10%", "10%", "36%"], num_cols=(1, 2, 3), raw_cols=(0, 1, 2, 3, 4)))
    if d["strengths"]:
        body += fb.section(6, "What is working", "<ul>%s</ul>" % "".join("<li>%s</li>" % e(s) for s in d["strengths"]))
    body += fb.section(7, "Coverage gaps", "<ul>%s</ul>" % "".join("<li>%s</li>" % e(g) for g in d["coverage_gaps"]))
    body += fb.section(8, "Alerts to add so drift is caught as it happens", fb.table(["Detection", "Logic"], [[x["name"], x["logic"]] for x in d["detections_to_add"]], widths=["30%", "70%"]))
    ev = "".join("<li>%s: %s</li>" % (e(x["source"]), e(x["reference"])) for x in d["evidence"])
    method = ("<p>Measured read-only from %s's Fluency / Ingext tenant on %s over %d days: the Entra role-holder snapshot, directory audit and sign-in logs, and the application permission grants. "
              "Drift is privilege granted, made permanent or expanded in the window, net of removals. Application permissions are classed Tier 0 to 2 by their ability to take over the tenant or reach business data "
              "(assets/rating_rules.json). The rating is High for a tier-0 grant, a role assigned outside PIM that is not reversed, an unresolved PIM alert or administrator single-factor sign-ins above 50%%; "
              "Elevated for permanent grants, more than four Global Administrators, administrators without MFA or single-factor sign-ins above 10%% (the last two are Fluency proposals). "
              "Individual administrators are not named; applications and shared accounts are.</p><ul>%s</ul>" % (e(tenant), when.strftime("%d %B %Y"), d["window_days"], ev))
    title = "Privileged Access Drift"
    doc = fb.page(title, "CISO Rpt 2 · Confidential", body=body,
                  subtitle="How %s's administrator, role and application privileges have changed over the last %d days, and where standing privilege has grown beyond what the business intends." % (plain(tenant), d["window_days"]),
                  meta="Prepared by Fluency Security · Connector: %s · %s · Window: %s" % (plain(tenant), when.strftime("%d %B %Y"), d["period_label"]),
                  kpis=kp, method=method, footer_left="Fluency Security · CISO Rpt 2 · Privileged Access Drift", data_date=when.strftime("%d %b %Y"))
    os.makedirs(out_dir, exist_ok=True)
    base = "Privileged_Access_Drift_%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "", plain(tenant)), stamp)
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
