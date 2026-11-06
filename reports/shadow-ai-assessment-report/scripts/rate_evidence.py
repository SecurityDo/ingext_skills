#!/usr/bin/env python3
"""Turn ai_evidence.json into a draft findings.json (paths, posture, services, findings, recommendations).

  rate_evidence.py evidence.json --tenant "Example Manufacturing" --date 2026-11-06 [--out draft_findings.json]

Risk levels and posture come only from assets/rating_rules.json and the original skill's scoring, so the same evidence
always gives the same rating. Board-safe: counts and service names only, never users, hosts or IPs.
"""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "..", "assets", "rating_rules.json")))
ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def plural(n, w):
    return "%d %s%s" % (n, w, "" if n == 1 else "s")


def build(ev, tenant, date):
    paths, findings, recs, dets, gaps = [], [], [], [], list(ev.get("gaps", []))
    nonfp = []
    # ---- path 1
    s = ev["saas"]
    if s["status"] == "no_data":
        paths.append({"id": "saas", "status": "no_data", "risk": "none", "headline": "No Entra application data: not assessed.", "sources": [], "metrics": []})
    else:
        svcs = s["services"]; nonfp = [x for x in svcs if not x["first_party"]]
        if s["persistent_content_access_apps"]:
            risk = "high"
        elif any(x["users"] or x["unverified"] or x["tier"] == "T1" for x in nonfp):
            risk = "medium"
        elif svcs:
            risk = "low"
        else:
            risk = "none"
        users = sum(x["users"] for x in nonfp)
        names = ", ".join(x["service"] for x in nonfp) or "none"
        head = ("%s found in Entra (%s); %s have granted access." % (plural(len(nonfp), "third-party AI service"), names, plural(s["users_with_ai_grant"], "user"))
                if svcs else "No AI applications found in Entra.")
        paths.append({"id": "saas", "status": "assessed", "risk": risk, "headline": head,
                      "sources": ["office365Application", "office365InstalledApp", "office365User"],
                      "metrics": [{"label": "AI services", "value": str(len(svcs))}, {"label": "users with a grant", "value": str(s["users_with_ai_grant"])},
                                  {"label": "unverified publishers", "value": str(s["unverified_third_party"])}]})
        t1 = [x for x in nonfp if x["tier"] == "T1" and (x["users"] or x["unverified"])]
        if t1:
            findings.append({"severity": "medium", "path": "saas", "title": "Consumer-grade AI services connected to the tenant",
                             "detail": "%s (Tier 1: may keep or train on prompts) %s granted access by %s without a verified publisher." % (
                                 ", ".join(x["service"] for x in t1), "have been", plural(sum(x["users"] for x in t1), "user")),
                             "evidence": "Entra applications and user grants.", "mitre": "T1528"})
            recs.append({"horizon": "Immediate", "title": "Review and revoke unverified AI grants", "detail": "Confirm the business need for each Tier 1 service; revoke the grant and require admin consent for new AI apps.", "owner": "M365 / IAM admin"})
        chat = [x for x in nonfp if x["users"] >= 10]
        if chat:
            findings.append({"severity": "medium", "path": "saas", "title": "Widely used AI service with no approved-AI list",
                             "detail": "%s is connected for %s. %s" % (", ".join("%s (%s)" % (x["service"], plural(x["users"], "user")) for x in chat),
                                                                       "users across the organization",
                                                                       "No approved-AI list was supplied, so the service is reported as unverified rather than unsanctioned."),
                             "evidence": "Entra user grants.", "mitre": ""})
            recs.append({"horizon": "30 days", "title": "Publish an approved-AI list", "detail": "Record which AI services are approved, at which tier and for which data, so use can be reported as sanctioned or not.", "owner": "CISO / Legal"})
        if s["persistent_content_access_apps"]:
            findings.append({"severity": "high", "path": "saas", "title": "AI apps with persistent access to mail or files",
                             "detail": "%s hold a content-read permission together with offline access and have no verified publisher." % plural(s["persistent_content_access_apps"], "AI app"),
                             "evidence": "Entra application permissions.", "mitre": "T1528"})
            recs.insert(0, {"horizon": "Immediate", "title": "Revoke persistent AI access", "detail": "Remove the grants and block user consent for applications asking for mail, files or sites access.", "owner": "M365 / IAM admin"})
        dets.append({"name": "New OAuth consent to an AI-classified app", "logic": "Office365 'Consent to application' where the target app matches the AI catalog", "path": "saas"})
    # ---- path 2 and 4 (no source)
    paths.append({"id": "network", "status": "no_data", "risk": "none", "headline": "Not assessed: no archived report carries proxy, DNS or firewall traffic to AI services.", "sources": [], "metrics": []})
    d4 = {"id": "data", "status": "no_data", "risk": "none", "headline": "Not assessed: no DLP source on this tenant.", "sources": [], "metrics": []}
    c = ev["data"].get("context")
    if c:
        d4["headline"] += " %s file downloads over %s archived days are context only." % (format(c["file_downloads"], ","), c["days"])
    # ---- path 3
    e = ev["endpoint"]
    if e["status"] == "no_data":
        p3 = {"id": "endpoint", "status": "no_data", "risk": "none", "headline": "No endpoint software inventory: not assessed.", "sources": [], "metrics": []}
    else:
        r = R["endpoint"]; desk = [x for x in e["ai_desktop"] if x["service"] != "Microsoft Copilot"]
        dh = max([x["hosts"] for x in desk] or [0]); share = dh / max(e["hosts_with_inventory"], 1)
        lh = e["local_llm_hosts"]
        if lh >= r["local_runner_hosts_high"]: risk = "high"
        elif lh >= r["local_runner_hosts_medium"] or share >= r["desktop_share_medium"]: risk = "medium"
        elif desk: risk = "low"
        else: risk = "none"
        p3 = {"id": "endpoint", "status": "assessed", "risk": risk,
              "headline": ("Local model runners on %s." % plural(lh, "host")) if lh else
              ("No local model runners; AI desktop apps (%s) on up to %s of %s." % (", ".join(x["service"] for x in desk) or "none", plural(dh, "host"), plural(e["hosts_with_inventory"], "inventoried host"))),
              "sources": ["sentinelOneApplication"],
              "metrics": [{"label": "AI desktop services", "value": str(len(desk))}, {"label": "local LLM hosts", "value": str(lh)}]}
        if lh:
            findings.append({"severity": "high" if risk == "high" else "medium", "path": "endpoint", "title": "Local LLM runners on corporate devices",
                             "detail": "Local model software (%s) is installed on %s. Models run offline on company data and bypass network controls." % (", ".join(x["service"] for x in e["local_runners"]), plural(lh, "device")),
                             "evidence": "Endpoint software inventory.", "mitre": ""})
            recs.append({"horizon": "Immediate", "title": "Contain local LLM runners", "detail": "Confirm the business need with device owners; remove or move to an approved, isolated environment.", "owner": "Endpoint team"})
        if desk:
            findings.append({"severity": "medium" if share >= r["desktop_share_medium"] else "low", "path": "endpoint", "title": "AI desktop applications installed",
                             "detail": "%s are installed, the most common on %s." % (", ".join("%s (%s)" % (x["service"], plural(x["hosts"], "host")) for x in desk), plural(dh, "host")),
                             "evidence": "Endpoint software inventory.", "mitre": ""})
            recs.append({"horizon": "90 days", "title": "Add AI desktop apps to the software policy", "detail": "State which AI clients are approved; remove the rest through the endpoint tool.", "owner": "Endpoint team"})
        dets.append({"name": "Local LLM runner installed", "logic": "Software inventory delta where a name matches Ollama, LM Studio, GPT4All, Jan, llama.cpp, koboldcpp, text-generation-webui or LocalAI", "path": "endpoint"})
    paths.append(p3); paths.append(d4)
    # ---- path 5
    d = ev["detection"]
    if d["status"] == "no_data":
        p5 = {"id": "detection", "status": "no_data", "risk": "none", "headline": "EventWatch rule list not supplied: not assessed.", "sources": [], "metrics": []}
    else:
        n = len(d["ai_specific"]); risk = "low" if n else "medium"
        p5 = {"id": "detection", "status": "assessed", "risk": risk,
              "headline": "%s enabled rule(s) specific to AI use; %s generic consent rule(s)." % (n, len(d["consent_rules"])),
              "sources": ["eventwatch_rule_list"], "metrics": [{"label": "AI-specific rules", "value": str(n)}, {"label": "consent rules", "value": str(len(d["consent_rules"]))}]}
        if not n:
            findings.append({"severity": "medium", "path": "detection", "title": "No detection is specific to AI use",
                             "detail": "%s generic consent rule(s) exist, but nothing alerts on a new AI service, an AI-classified consent or a local model runner." % len(d["consent_rules"]),
                             "evidence": "EventWatch rule catalog.", "mitre": ""})
            recs.append({"horizon": "30 days", "title": "Enable the proposed AI detections", "detail": "Add the detections listed in this report so new AI adoption is seen as it happens.", "owner": "Fluency SOC"})
    paths.append(p5)
    order = ["saas", "network", "endpoint", "data", "detection"]
    paths.sort(key=lambda p: order.index(p["id"]))
    # ---- posture
    lv = [p["risk"] for p in paths if p["status"] == "assessed"]
    top = max(lv or ["none"], key=lambda k: ORDER[k])
    ladder = R["posture"]["ladder"]; i = ladder.index(R["posture"]["base"][top])
    if sum(1 for k in lv if ORDER[k] >= 2) >= R["posture"]["raise_if_paths_medium_or_worse"]:
        i = min(i + 1, len(ladder) - 1)
    posture = ladder[i]
    na = [p["id"] for p in paths if p["status"] != "assessed"]
    reason = "Highest assessed path risk is %s across %d of 5 paths; %d paths could not be assessed with the evidence available." % (top, len(lv), len(na))
    # ---- services table
    svc_rows = []
    for x in (s.get("services") or []):
        risk = "none" if x["first_party"] else ("high" if x["persistent_content_access"] else "medium" if (x["tier"] == "T1" or x["users"] or x["unverified"]) else "low")
        svc_rows.append({"service": x["service"], "category": x["category"], "tier": x["tier"], "seen_in": ["saas"], "users": x["users"], "hosts": 0,
                         "volume": "n/a", "status": x["status"], "risk": risk})
    for x in (e.get("ai_desktop") or []):
        row = next((r for r in svc_rows if r["service"].split(" /")[0] == x["service"].split(" /")[0]), None)
        if row: row["hosts"] = x["hosts"]; row["seen_in"].append("endpoint")
        else: svc_rows.append({"service": x["service"], "category": "Desktop client", "tier": "-", "seen_in": ["endpoint"], "users": 0, "hosts": x["hosts"], "volume": "n/a", "status": "unverified", "risk": "low"})
    hi = s.get("persistent_content_access_apps", 0) if s["status"] == "assessed" else 0
    kp = {"ai_services": len(svc_rows), "users": s.get("users_with_ai_grant", 0), "hosts": e.get("hosts_with_ai", 0),
          "upload_volume": "n/a", "high_risk_apps": hi, "local_llm_hosts": e.get("local_llm_hosts", 0)}
    summary = ["%s uses generative AI. %s AI services are connected to Entra and %s have granted them access." % (tenant, kp["ai_services"], plural(kp["users"], "user"))]
    if kp["local_llm_hosts"] == 0 and e["status"] == "assessed":
        summary.append("No local model runners were found in the endpoint software inventory.")
    summary.append("Network traffic to AI services and data-exposure signals could not be assessed from the evidence available, so the posture reflects only the paths that were measured.")
    return {"tenant": tenant, "grid_account": "", "assessment_date": date, "prepared_for": "Chief Information Security Officer",
            "sanctioned_list_provided": ev.get("sanctioned_list_provided", False), "posture": posture, "posture_reason": reason,
            "executive_summary": summary, "kpis": kp, "paths": paths, "services": svc_rows, "findings": findings,
            "recommendations": recs, "detections_to_add": dets, "coverage_gaps": gaps,
            "evidence": [{"source": x, "reference": "resource dump", "note": ""} for x in ev.get("sources", [])]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("evidence"); ap.add_argument("--tenant", required=True)
    ap.add_argument("--date", required=True); ap.add_argument("--out", default="draft_findings.json")
    a = ap.parse_args()
    json.dump(build(json.load(open(a.evidence)), a.tenant, a.date), open(a.out, "w"), indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
