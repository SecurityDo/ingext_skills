#!/usr/bin/env python3
"""Aggregate Shadow AI evidence for ONE tenant from resource dumps (aggregate counts only, board-safe).

  ai_evidence.py <dump_dir> [-o evidence.json] [--rules rules.json] [--entra entra_evidence.json] [--sanctioned sanctioned.json]

Reads, when present in <dump_dir> (.jsonl.gz or .jsonl): office365Application, office365InstalledApp, office365User,
sentinelOneApplication. Path 2 (network egress) and path 4 (data exposure) have no archived-report source and are
reported "not assessed". --rules is the eventwatch_rule_list output (one or more saved results merged) for path 5.
--sanctioned is an optional JSON list of approved AI service names (as in assets/ai_catalog.json).
"""
import argparse, collections, gzip, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(HERE, "..", "assets", "ai_catalog.json")))
SVC = [(s, re.compile(s["rx"], re.I)) for s in CAT["services"]]
RUN = [(s, re.compile(s["rx"], re.I)) for s in CAT["local_runners"]]
RULE_RX = re.compile(CAT["rule_rx"], re.I)
HIGH = set(CAT["high_risk_scopes"]); CONTENT = set(CAT["content_scopes"])


def load(d, name):
    for ext in (".jsonl.gz", ".jsonl"):
        p = os.path.join(d, name + ext)
        if os.path.exists(p):
            op = gzip.open if ext.endswith("gz") else open
            with op(p, "rt") as f:
                for l in f:
                    if l.strip():
                        j = json.loads(l)
                        yield j.get("@" + name, j)
            return
    return None


def rows(d, name):
    g = load(d, name)
    return None if g is None else list(g)


def match(name, table=SVC):
    n = (name or "").strip()
    for s, rx in table:
        if rx.search(n):
            return s
    return None


def verified(a):
    vp = a.get("verifiedPublisher") or {}
    return bool(isinstance(vp, dict) and (vp.get("displayName") or vp.get("verifiedPublisherId")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump_dir"); ap.add_argument("-o", "--out", default="evidence.json")
    ap.add_argument("--rules"); ap.add_argument("--entra"); ap.add_argument("--sanctioned")
    a = ap.parse_args()
    sanctioned = {s.lower() for s in json.load(open(a.sanctioned))} if a.sanctioned else None
    gaps, sources = [], []
    ev = {"sanctioned_list_provided": sanctioned is not None}

    apps, sps, users, s1 = (rows(a.dump_dir, n) for n in ("office365Application", "office365InstalledApp", "office365User", "sentinelOneApplication"))
    for n, v in (("office365Application", apps), ("office365InstalledApp", sps), ("office365User", users)):
        (sources if v is not None else gaps).append(n if v is not None else
            "%s dump missing: SaaS AI evidence is incomplete" % n)

    # ---- Path 1: SaaS AI through Entra
    if apps is None and sps is None:
        ev["saas"] = {"status": "no_data"}
    else:
        apps, sps, users = apps or [], sps or [], users or []
        reg_ids = {x.get("appId") for x in apps}
        owners = collections.Counter(x.get("appOwnerOrganizationId") for x in sps if x.get("appId") in reg_ids)
        tenant_org = owners.most_common(1)[0][0] if owners else None
        svc = collections.OrderedDict()

        def slot(s):
            return svc.setdefault(s["name"], {"service": s["name"], "category": s["category"], "tier": s["tier"],
                                              "first_party": bool(s.get("first_party")), "registered_apps": 0, "service_principals": 0,
                                              "verified": 0, "unverified": 0, "tenant_owned": 0, "users": 0,
                                              "scopes": set(), "scopes_unresolved": 0})
        for x in apps:                                   # apps registered in this tenant (its own integrations)
            s = match(x.get("displayName"))
            if not s:
                continue
            e = slot(s); e["registered_apps"] += 1; e["tenant_owned"] += 1
            for r in x.get("requiredResourceAccess") or []:
                for ra in r.get("resourceAccess") or []:
                    if ra.get("permission"):
                        e["scopes"].add(ra["permission"])
                    else:
                        e["scopes_unresolved"] += 1
        for x in sps:                                    # service principals (apps usable in the tenant)
            s = match(x.get("displayName")) or match(x.get("appDisplayName"))
            if not s or x.get("appId") in reg_ids:
                continue
            e = slot(s); e["service_principals"] += 1
            if x.get("appOwnerOrganizationId") == CAT["microsoft_owner_org"]:
                e["first_party"] = True
            if verified(x):
                e["verified"] += 1
            elif x.get("appOwnerOrganizationId") not in (tenant_org, CAT["microsoft_owner_org"]):
                e["unverified"] += 1
        user_any, per = set(), collections.defaultdict(set)
        for u in users:
            for nm in u.get("oauth2Applications") or []:
                s = match(nm if isinstance(nm, str) else (nm or {}).get("displayName"))
                if s:
                    per[s["name"]].add(u.get("id")); user_any.add(u.get("id"))
        for nm, ids in per.items():
            if nm not in svc:
                s = next(s for s, _ in SVC if s["name"] == nm); slot(s)
            svc[nm]["users"] = len(ids)
        out = []
        for e in svc.values():
            sc = sorted(e.pop("scopes")); e["high_risk_scopes"] = [x for x in sc if x in HIGH]
            e["content_scope"] = any(x in CONTENT for x in sc)
            e["offline_access"] = "offline_access" in sc
            e["status"] = ("sanctioned" if sanctioned and e["service"].lower() in sanctioned
                           else "unsanctioned" if sanctioned is not None else "unverified")
            e["persistent_content_access"] = e["content_scope"] and e["offline_access"] and e["verified"] == 0 and not e["first_party"]
            out.append(e)
        ev["saas"] = {"status": "assessed", "services": out, "users_with_ai_grant": len(user_any),
                      "ai_services": len(out), "users_total": len(users),
                      "registered_ai_apps": sum(e["registered_apps"] for e in out),
                      "ai_service_principals": sum(e["service_principals"] for e in out),
                      "unverified_third_party": sum(e["unverified"] for e in out),
                      "persistent_content_access_apps": sum(1 for e in out if e["persistent_content_access"]),
                      "t1_services": sum(1 for e in out if e["tier"] == "T1"),
                      "scopes_unresolved": sum(e["scopes_unresolved"] for e in out)}
        if any(e["scopes_unresolved"] for e in out):
            gaps.append("Granted permission names are not in the application dump for some AI apps (only ids): high-risk scope checks cover apps whose permissions are named.")
        gaps.append("Per-user grants are matched by application name; grant scopes and consent time are not in the user dump.")

    # ---- Path 3: endpoint AI software
    if s1 is None:
        ev["endpoint"] = {"status": "no_data"}
        gaps.append("No endpoint software inventory dump (sentinelOneApplication): endpoint AI software and local model runners not assessed.")
    else:
        sources.append("sentinelOneApplication")
        host_svc, host_run = collections.defaultdict(set), collections.defaultdict(set); hosts = set()
        for x in s1:
            h = x.get("agentId") or x.get("agentComputerName"); hosts.add(h)
            r = match(x.get("name"), RUN)
            if r:
                host_run[r["name"]].add(h); continue
            s = match(x.get("name"))
            if s and (x.get("publisher") or "") != "" or s:
                if s:
                    host_svc[s["name"]].add(h)
        all_run = set().union(*host_run.values()) if host_run else set()
        all_ai = set().union(*[v for k, v in host_svc.items() if k != "Microsoft Copilot"]) if host_svc else set()
        ev["endpoint"] = {"status": "assessed", "hosts_with_inventory": len(hosts),
                          "ai_desktop": [{"service": k, "hosts": len(v)} for k, v in sorted(host_svc.items(), key=lambda kv: -len(kv[1]))],
                          "local_runners": [{"service": k, "hosts": len(v)} for k, v in sorted(host_run.items(), key=lambda kv: -len(kv[1]))],
                          "hosts_with_ai": len(all_ai | all_run), "local_llm_hosts": len(all_run)}

    # ---- Paths 2 and 4: no archived source
    ev["network"] = {"status": "no_data"}
    gaps.append("Network egress (proxy, DNS, firewall) to AI services is not assessed: no archived report carries it.")
    ev["data"] = {"status": "no_data"}
    gaps.append("Data exposure (DLP matches coinciding with AI use) is not assessed: no DLP source; bulk downloads are only context.")
    if a.entra and os.path.exists(a.entra):
        o = (json.load(open(a.entra)).get("o365") or {})
        if o.get("fileDownloads") is not None:
            ev["data"]["context"] = {"file_downloads": o.get("fileDownloads"), "days": o.get("days")}

    # ---- Path 5: detection coverage
    if a.rules and os.path.exists(a.rules):
        seen = {}
        txt = json.load(open(a.rules))
        for blob in (txt if isinstance(txt, list) else [txt]):
            for r in blob.get("rules", []):
                seen[r["id"]] = r
        ai = [r for r in seen.values() if RULE_RX.search(r["name"]) and not r.get("disabled")]
        ev["detection"] = {"status": "assessed", "rules_checked": len(seen),
                           "relevant_rules": [r["name"] for r in ai],
                           "ai_specific": [r["name"] for r in ai if re.search(r"chatgpt|openai|copilot|llm|genai|gen_ai|shadow_ai|ollama", r["name"], re.I)],
                           "consent_rules": [r["name"] for r in ai if re.search(r"consent", r["name"], re.I)]}
    else:
        ev["detection"] = {"status": "no_data"}
        gaps.append("EventWatch rule list not supplied: detection coverage not assessed.")
    ev["gaps"], ev["sources"] = gaps, sources
    json.dump(ev, open(a.out, "w"), indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
