#!/usr/bin/env python3
"""Ransomware-readiness identity evidence from the archived Entra activity report.

Usage: entra_evidence.py <archive.json> [more.json ...] [-o entra_evidence.json]

Input: download_report_archive results (or one get_report_result) of the scheduled report
Office365_Entra_Activity_Report (the name this tenant family archives it under; the parser reads
object names signin_trend, signin_facets, audit_trend, sources, so it does not depend on the report name).
Daily results are additive: trends are summed per metric, facets summed by value; a day with no completed
result is a gap, never zero. Counts only; no user, IP or application-owner names are written.
"""
import json, re, sys
from collections import Counter

ADMIN_APP = re.compile(r"azure portal|microsoft azure|azure cli|azure powershell|azure resource manager|entra admin|"
                       r"azure active directory|microsoft graph (command|powershell)|microsoft 365 admin|admin cent|"
                       r"exchange admin|intune|microsoft admin portal|defender (portal|for)|security (center|portal)", re.I)
LEGACY = re.compile(r"exchange activesync|imap|pop|smtp|authenticated smtp|other clients|mapi over http|offline address|"
                    r"exchange web services|autodiscover|reporting web services|universal outlook", re.I)
SIGN = ["events", "failed", "interactive", "mfaRequired", "singleFactorOk", "caFailures", "risky", "guests", "legacyAuth"]
AUD = ["events", "failed", "userChanges", "groupChanges", "roleChanges", "appChanges", "policyChanges", "passwordEvents"]


def results(doc):
    if "days" in doc:
        for d in doc["days"]:
            if d.get("result"):
                yield d["entry"].get("completedOn", ""), d["entry"].get("env", {}).get("scriptHash"), d["result"]["objects"]
    else:
        yield "", None, (doc.get("result") or doc)["objects"]


def rows(o):
    t = (o.get("value") or o).get("table")
    return t["rows"] if t else []


def facet(o, key):
    om = (o.get("value") or o).get("orderedMap")
    out = Counter()
    if not om:
        return out
    for k, v in zip(om["keys"], om["values"]):
        if k == key:
            for r in (v.get("sx") or {}).get("rows", []):
                out[str(r.get(key))] += r.get("count_", 0) or 0
    return out


def main(paths, out):
    perday = {}
    hashes = set()
    for p in paths:
        for done, h, objs in results(json.load(open(p))):
            byname = {o["name"]: o for o in objs}
            tr = rows(byname.get("signin_trend", {}))
            date = tr[0]["Date"][:10] if tr else (done or "")[:10] + "?"
            if date not in perday or done >= perday[date][0]:
                perday[date] = (done, byname)
            if h:
                hashes.add(h)
    ev = {"gaps": []}
    if not perday:
        ev["gaps"].append("No Entra activity archive: sign-in checks are not measurable (visibility gap)")
        json.dump(ev, open(out, "w"), indent=2); print(json.dumps(ev, indent=2)); return
    sign, aud = Counter(), Counter()
    auth, risk, ca, app, client, utype, proto = (Counter() for _ in range(7))
    unavailable = Counter()
    for date, (_, b) in sorted(perday.items()):
        for r in rows(b.get("signin_trend", {})):
            for m in SIGN:
                sign[m] += r.get(m) or 0
        for r in rows(b.get("audit_trend", {})):
            for m in AUD:
                aud[m] += r.get(m) or 0
        if "signin_facets" in b:
            auth.update(facet(b["signin_facets"], "authRequirement")); risk.update(facet(b["signin_facets"], "riskLevel"))
            ca.update(facet(b["signin_facets"], "caStatus")); app.update(facet(b["signin_facets"], "app"))
            client.update(facet(b["signin_facets"], "clientApp")); utype.update(facet(b["signin_facets"], "userType"))
            proto.update(facet(b["signin_facets"], "protocol"))
        for r in rows(b.get("sources", {})):
            if r.get("status") != "ok":
                unavailable[r.get("source")] += 1
    for s in unavailable:
        ev["gaps"].append(f"{s} not available on {unavailable[s]} archived scan(s)")
    ev["days_covered"] = len(perday)
    ev["script_versions"] = len(hashes)
    if len(hashes) > 1:
        ev["gaps"].append("The archived script changed inside the window; counts are summed but days may not be strictly comparable")
    ev["signins"] = {m: sign[m] for m in SIGN}
    ok = sign["events"] - sign["failed"]
    ev["signins"]["single_factor_share_pct"] = round(100 * sign["singleFactorOk"] / ok, 1) if ok else None
    ev["auth_requirement"] = dict(auth)
    ev["risk_levels"] = {k: v for k, v in risk.items() if k not in ("none", "(not recorded)", "", "hidden")}
    if risk and set(risk) <= {"hidden", "(not recorded)", ""}:
        ev["gaps"].append("Sign-in risk levels are hidden (the tenant lacks Entra ID Protection licensing): risky sign-ins are not measurable")
    ev["ca_status"] = dict(ca)
    ev["conditional_access_applied_signins"] = sum(v for k, v in ca.items() if k.lower() not in ("notapplied", "(not recorded)", ""))
    ev["conditional_access_applied_share_pct"] = round(100 * ev["conditional_access_applied_signins"] / sum(ca.values()), 1) if ca else None
    ev["user_types"] = dict(utype)
    ev["legacy_clients"] = {k: v for k, v in client.items() if LEGACY.search(k)}
    ev["admin_portal_signins"] = {"events": sum(v for k, v in app.items() if ADMIN_APP.search(k)),
                                  "apps": sorted(k for k in app if ADMIN_APP.search(k))}
    ev["directory_changes"] = {m: aud[m] for m in AUD}
    ev["gaps"].append("Single-factor status of admin-portal sign-ins is not joint in the archive (apps and auth requirement are separate facets); "
                      "admin MFA is judged from conditional-access policies and the single-factor share")
    json.dump(ev, open(out, "w"), indent=2)
    print(json.dumps(ev, indent=2))


if __name__ == "__main__":
    a = sys.argv[1:]
    out = "entra_evidence.json"
    if "-o" in a:
        i = a.index("-o"); out = a[i + 1]; a = a[:i] + a[i + 2:]
    if not a:
        sys.exit(__doc__)
    main(a, out)
