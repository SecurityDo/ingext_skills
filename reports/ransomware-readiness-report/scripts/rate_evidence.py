#!/usr/bin/env python3
"""Turn the three evidence files into pillar colours, ranked issues and a draft findings.json.

Usage: rate_evidence.py --resource resource_evidence.json [--windows windows_evidence.json]
                        [--entra entra_evidence.json] --tenant "Name" [--rules assets/rating_rules.json]
                        [--out draft_findings.json]

The colours and issue severities come only from assets/rating_rules.json (edit the thresholds there). Each issue
carries the rule's text with the numbers filled in; the analyst may sharpen the wording, check the summary and board
ask, and render with render_report.py. A source that is missing makes its pillars amber, "not measurable".
"""
import argparse, html, json, os, re
from datetime import datetime

SEV = {"Critical": 0, "High": 1, "Medium": 2}
OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
NAMES = {"vnc": "VNC", "teamviewer": "TeamViewer", "pdq": "PDQ", "anydesk": "AnyDesk", "splashtop": "Splashtop",
         "manageengine": "ManageEngine", "screenconnect": "ScreenConnect", "atera": "Atera", "rustdesk": "RustDesk",
         "bigfix": "BigFix", "ivanti": "Ivanti", "kaseya": "Kaseya", "logmein": "LogMeIn"}
MISSING = []


def get(ev, path):
    cur = ev
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def short_os(n):
    n = re.sub(r"\b(Pro|Home|Standard|Datacenter|Enterprise)\b", "", n).replace("Windows Server", "Server")
    return re.sub(r"\s+", " ", n).strip()


def derive(r, w):
    d = {}
    eol = (r.get("endpoint") or {}).get("eol_os") or {}
    merged = {}
    for k, v in eol.items():
        merged[short_os(k)] = merged.get(short_os(k), 0) + v
    d["eol_total"] = sum(merged.values())
    d["eol_text"] = ", ".join(f"{v} {k}" for k, v in sorted(merged.items(), key=lambda x: -x[1])) or "none"
    ap = [(k, v) for k, v in ((r.get("endpoint") or {}).get("eol_approaching") or {}).items() if v]
    out = []
    for k, v in ap:
        m = re.match(r"Windows (Server \d+) \(extended support ends (.+)\)", k)
        out.append(f"{v} {m.group(1)} hosts reach the end of extended support on {m.group(2)}" if m else f"{v} {k}")
    d["approaching_eol_text"] = "; ".join(out) or "no systems are approaching end of support"
    ep = r.get("endpoint") or {}
    vend = list((ep.get("vendors") or {}).keys())
    d["edr_name"] = " and ".join(vend) if vend else "endpoint"
    st = ep.get("stale") or 0
    srv = (ep.get("stale_by_type") or {}).get("server", 0)
    d["stale7_split"] = f"{st - srv} workstations and {srv} servers" if srv else f"{st} workstations"
    days = ep.get("stale_days_by_vendor") or {}
    d["stale_window_text"] = (f"{list(days.values())[0]} days" if len(set(days.values())) == 1
                              else " or ".join(f"{v} days ({k})" for k, v in sorted(days.items(), key=lambda x: x[1]))) if days else "7 days"
    th = r.get("threats") or {}
    d["mitigation_sentence"] = (f"Of {th.get('total')} threats in the last {th.get('window_days')} days, {th.get('on_detect_only_agent')} were on agents that only detect, "
                                f"and {th.get('unmitigated')} was not mitigated.") if th else ""
    tools = r.get("remote_tools") or []
    san = [t for t in tools if t.get("status") == "sanctioned"]
    oth = [t for t in tools if t.get("status") != "sanctioned"]
    nm = lambda f: NAMES.get(f, f.title())
    parts = [f"{nm(t['family'])} ({t['endpoints']} endpoints" + (f", {t['servers']} servers" if t.get("servers") else "") + ")" for t in san]
    d["remote_sanctioned_text"] = (" and ".join(parts) + (" are" if len(parts) > 1 else " is") + " treated as the organization's own tool" + ("s." if len(parts) > 1 else ".")) if parts else ""
    n_o = r.get("remote_other_endpoints") or 0
    other_list = ", ".join(f"{nm(t['family'])} {t['endpoints']}" for t in oth)
    d["remote_other_sentence"] = f"A further {n_o} endpoints run other remote-access tools ({other_list})." if n_o else ""
    d["remote_title"] = "End-of-life systems and remote-access tool sprawl" if n_o else "End-of-life systems"
    d["remote_headline_tail"] = f" and {n_o} endpoints with extra remote tools" if n_o else ""
    d["remote_other_text"] = ", ".join(f"{nm(t['family'])} {t['endpoints']}" for t in oth) or "none"
    hard = [h for h in (r.get("hardening") or []) if h.get("possible_reporting_gap")]
    pick = []
    for key in ["ransomware", "psexec", "safe mode", "lsass", "office"]:
        for h in hard:
            if key in h["configurationName"].lower() and h not in pick:
                pick.append(h); break
    pick = (pick + [h for h in hard if h not in pick])[:3]
    q = [f'"{h["configurationName"]}"' for h in pick]
    d["hardening_examples"] = (", ".join(q[:-1]) + (" and " if len(q) > 1 else "") + q[-1]) if q else "several rules"
    cg = [h for h in (r.get("hardening") or []) if "credential guard" in h["configurationName"].lower() and "lsass" not in h["configurationName"].lower()]
    d["credential_guard_off"] = f"{cg[0]['noncompliant']} of {cg[0]['devices']}" if cg else "n/a"
    sw = [s for s in ((r.get("vulnerabilities") or {}).get("top_software") or []) if not s["software"].startswith(("windows_", "android"))][:2]
    pretty = lambda s: s.replace("_", " ").title()
    d["vuln_drivers_text"] = ", ".join(f"unpatched {pretty(s['software'])} on {s['devices']} devices" if i == 0 else f"{pretty(s['software'])} on {s['devices']}" for i, s in enumerate(sw)) or "see the software list"
    sc = r.get("scanner_tools") or []
    d["scanner_text"] = f"A network-scanning tool ({sc[0]['tool']}) is installed on {sc[0]['endpoints']} endpoints." if sc else ""
    ca = r.get("conditional_access") or {}
    d["mfa_policy_text"] = (f"None of the {ca.get('enabled')} enabled conditional-access policies requires MFA for all users." if ca.get("mfa_all_users") == 0
                            else f"{ca.get('mfa_all_users')} conditional-access policies require MFA for all users." if ca else "")
    sg = r.get("strong_controls") or []
    d["strong_controls_count"] = len(sg)
    ex = []
    for key in ["wdigest", "smbv1", "firewall", "smartscreen", "cloud-delivered", "bitlocker"]:
        for s in sg:
            if key in s["configurationName"].lower() and s["configurationName"] not in ex:
                ex.append(s["configurationName"]); break
    d["strong_controls_examples"] = ", ".join('"' + e.replace("'", "") + '"' for e in ex[:3]) or "several"
    r.update(d)
    if w:
        lc = w.get("log_clearing") or {}
        lc["ids_text"] = " and ".join(f"{v} for event ID {k}" for k, v in sorted((lc.get("by_event_id") or {}).items(), reverse=True)) or "no event IDs recorded"
        cov = w.get("coverage") or {}
        w["pattern_text"] = "not yet known" if cov.get("archived_days", 0) < cov.get("expected_days", 0) else "shown in the daily counts"
        w.setdefault("persistence", {})["suspect_count"] = len((w.get("persistence") or {}).get("suspect_names") or [])


def test(ev, t):
    v = get(ev, t["path"])
    if v is None:
        return False
    ref = t["value"]
    if "ratio_of" in t:
        base = get(ev, t["ratio_of"])
        if base in (None, 0):
            return False
        ref = t["value"] * base
    try:
        return OPS[t["op"]](v, ref)
    except TypeError:
        return False


def fires(ev, rule):
    ok = all(test(ev, t) for t in rule.get("when", []))
    if ok and rule.get("when_any"):
        ok = any(test(ev, t) for t in rule["when_any"])
    return ok


def fill(text, ev):
    def sub(m):
        v = get(ev, m.group(1))
        if v is None:
            MISSING.append(m.group(1)); return "?"
        if isinstance(v, int) and not isinstance(v, bool) and v >= 1000:
            return f"{v:,}"
        return html.escape(str(v), quote=False) if isinstance(v, str) else str(v)
    return re.sub(r"\{([rwn]\.[\w.]+)\}", sub, text)


def overall(pillars):
    red = [p["name"].lower() for p in pillars if p["status"] == "red"]
    amber = [p for p in pillars if p["status"] == "amber"]
    if any(k in n for n in red for k in ("backup", "endpoint", "prevention")):
        return "Elevated Risk"
    if len(red) >= 2:
        return "High Risk"
    return "Resilient" if not red and not amber else "Moderate Risk"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resource"); ap.add_argument("--windows"); ap.add_argument("--entra")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--rules", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "rating_rules.json"))
    ap.add_argument("--out", default="draft_findings.json")
    a = ap.parse_args()
    load = lambda p: json.load(open(p)) if p and os.path.exists(p) else None
    r, w, n = load(a.resource) or {}, load(a.windows), load(a.entra)
    rules = json.load(open(a.rules))
    derive(r, w)
    ev = {"r": r, "w": w or {}, "n": n or {}}
    order = [q["id"] for q in rules["rules"]]
    fired = {}
    for rule in rules["rules"]:
        if fires(ev, rule) and not any(s in fired for s in rule.get("suppress_if", [])):
            fired[rule["id"]] = rule
    byp = {}
    for rule in fired.values():
        byp.setdefault(rule["pillar"], []).append(rule)
    pillars, gaps = [], []
    for pd in rules["pillars"]:
        rs = sorted(byp.get(pd["key"], []), key=lambda x: (SEV[x["severity"]], order.index(x["id"])))
        missing = [x for x in pd["needs"] if get(ev, x) is None]
        status = "green"
        if any(x["severity"] == "Critical" or x.get("pillar_status") == "red" for x in rs):
            status = "red"
        elif rs:
            status = "amber"
        detail = fill(rs[0]["headline"], ev) if rs else "No material issues"
        cov = get(ev, pd["coverage"]) if pd.get("coverage") else None
        partial = bool(cov and cov.get("archived_days", 0) < cov.get("expected_days", 0))
        if missing and not rs:
            status, detail = "amber", "Not measurable, visibility gap"
        elif partial and status == "green":
            status, detail = "amber", f"Evidence covers {cov['archived_days']} of {cov['expected_days']} days"
        if missing:
            gaps.append(f"{html.unescape(pd['name'])}: no data for {', '.join(missing)}")
        pillars.append({"name": pd["name"], "status": status, "detail": detail})
    issues = []
    for rule in sorted(fired.values(), key=lambda x: (SEV[x["severity"]], order.index(x["id"])))[:10]:
        issues.append({"severity": rule["severity"], "title": fill(rule["title"], ev), "finding": fill(rule["finding"], ev),
                       "why": rule["why"], "recommendation": rule["recommendation"], "owner": rule["owner"],
                       "target": rule["target"], "mitre": rule["mitre"], "_rule": rule["id"],
                       "_action": fill(rule["action"], ev), "_outcome": rule["outcome"]})
    strengths = [fill(s["text"], ev) for s in rules["strengths"] if all(test(ev, t) for t in s["when"])]
    rating = overall(pillars)
    roadmap = []
    for lo, hi, label in [(0, 14, "0&ndash;14 days"), (15, 30, "15&ndash;30 days"), (31, 60, "31&ndash;60 days"), (61, 10**6, "61&ndash;90 days")]:
        items = [i for i in issues if lo <= int(re.match(r"\d+", i["target"]).group()) <= hi]
        if items:
            up = lambda t: t[0].upper() + t[1:]
            roadmap.append({"window": label, "actions": "; ".join(dict.fromkeys(up(i["_action"]) for i in items)) + ".",
                            "outcome": "; ".join(dict.fromkeys(up(i["_outcome"]) for i in items)) + "."})
    c = sum(i["severity"] == "Critical" for i in issues)
    h = sum(i["severity"] == "High" for i in issues)
    m = sum(i["severity"] == "Medium" for i in issues)
    cov_n = (n or {}).get("coverage") or {}
    cov_w = (w or {}).get("coverage") or {}
    try:
        snap = datetime.strptime(r.get("generated", ""), "%Y-%m-%d").strftime("%-d %b %Y")
    except ValueError:
        snap = "date unknown"
    window = (f"Resource snapshots {snap}; "
              + (f"sign-ins {cov_n['archived_days']} of {cov_n['expected_days']} days archived" if cov_n else "sign-ins not available") + "; "
              + (f"Windows audit {cov_w['archived_days']} of {cov_w['expected_days']} days archived" if cov_w else "Windows audit not available"))
    allgaps = [g for src in (r, w, n) if src for g in src.get("gaps", [])] + gaps
    headline = {"Elevated Risk": "Not yet ransomware-ready, but the fixes are well defined", "High Risk": "Not yet ransomware-ready, but the fixes are well defined",
                "Moderate Risk": "Reasonable foundations, with gaps to close", "Resilient": "Well prepared; keep it that way"}[rating]
    top = [i["title"] for i in issues[:2]]
    crit = [i for i in issues if i["severity"] == "Critical"] or issues[:1]
    lc = lambda s: s[0].lower() + s[1:] if s else s
    draft = {
        "tenant": a.tenant, "assessment_date": datetime.now().strftime("%Y-%m-%d"), "evidence_window": window,
        "overall_rating": rating, "kpi_label": "Device Secure Score", "kpi_value": str(r.get("secure_score", "n/a")),
        "summary_headline": headline,
        "summary": f"{c} critical, {h} high and {m} medium issues across the eight pillars. " + (strengths[0] + " " if strengths else "")
                   + ("Most urgent: " + "; ".join(top) + "." if top else "No material issues were found."),
        "board_ask": ("approve immediate action on " + "; ".join(lc(i["_action"]) + f" ({i['target']})" for i in crit)
                      + ", and sponsor a 90-day hardening program to close the remaining findings. Most actions use tools the organization already licenses.") if issues
                     else "keep the current controls under review.",
        "pillars": pillars, "issues": [{k: v for k, v in i.items() if not k.startswith("_")} for i in issues],
        "roadmap": roadmap, "strengths": strengths,
        "methodology": (f"Findings were derived from {html.escape(a.tenant)}&rsquo;s Fluency / Ingext datalake: endpoint, vulnerability, hardening, identity and conditional-access snapshots, "
                        f"the archived Entra sign-in activity report and the archived Windows server activity report. Evidence window: {window}. Pillar colours and issue severities follow the thresholds in rating_rules.json. "
                        "Unprotected-device counts match Defender discovery to the EDR agent inventory (SentinelOne or CrowdStrike) by hostname, count only active Windows, Linux and Mac devices, and may include a small number of guest devices. "
                        "Recovery ability is inferred from backup products and versions, not proven by restore tests. The conditional-access MFA check counts policies requiring MFA for all users and cannot see exclusions. MFA registration status and the MFA status of individual admin-portal sign-ins could not be measured. No individual users or hosts are named in this report."),
        "_review": {"rules_fired": list(fired), "evidence_gaps": allgaps, "unresolved_placeholders": sorted(set(MISSING)),
                    "note": "Colours and severities are rule-based. Sharpen the wording and check the summary and board ask before rendering."}}
    json.dump(draft, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"overall": rating, "pillars": [(p["name"], p["status"], p["detail"]) for p in pillars],
                      "issues": [(i["severity"], i["title"]) for i in issues], "fired": list(fired),
                      "missing_placeholders": sorted(set(MISSING)), "gaps": allgaps}, indent=1))


if __name__ == "__main__":
    main()
