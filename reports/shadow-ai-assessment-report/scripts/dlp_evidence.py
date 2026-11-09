#!/usr/bin/env python3
"""Aggregate evidence from the archived DLP_Activity_Report (Office 365 section) into dlp_evidence.json.

  dlp_evidence.py <archive.json> [more.json ...] [-o dlp_evidence.json]

Input: download_report_archive results (days[] of {entry, result.objects}) or one get_report_result, for the daily report
DLP_Activity_Report. Objects read: o365_trend, o365_rules, o365_infoTypes, o365_alerts, sources. The `o365_actors`
object (user names, personal data) is never read. Daily results are additive: counts are summed; a day with no completed
result is a gap, never zero. Counts and policy, workload and information-type names only: no user, file, subject or matched value.

What the report can and cannot show: it sees only policies that matched. Zero matches cannot separate "no DLP policy" from "no
sensitive data moved", so a tenant with no matches is reported as not measurable. Policy coverage, user overrides, sharing and
web or AI egress are not in this report.
"""
import json, sys
from collections import Counter

AI_WORKLOAD = "ExtendedApplications"          # the Microsoft 365 Copilot DLP policy (record type 263)


def results(doc):
    if "days" in doc:
        for d in doc["days"]:
            if d.get("result"):
                yield d["entry"].get("completedOn", ""), d["result"]["objects"]
    else:
        yield "", (doc.get("result") or doc)["objects"]


def rows(o):
    t = (o.get("value") or o).get("table")
    return t["rows"] if t else []


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def build(paths):
    days, tr, rules, infos, alerts, src = {}, Counter(), Counter(), {}, Counter(), {}
    for p in paths:
        for done, objs in results(json.load(open(p))):
            by = {o["name"]: o for o in objs}
            if "o365_trend" not in by:
                continue
            days[done or len(days)] = 1
            for r in rows(by["o365_trend"]):
                for k in ("matchEvents", "undoEvents", "enforcedEvents"):
                    tr[k] += num(r.get(k))
            for r in rows(by.get("o365_rules", {})):
                rules[(r.get("workload"), r.get("policy"), r.get("ruleName"), r.get("mode"), r.get("severity"))] += num(r.get("events"))
            for r in rows(by.get("o365_infoTypes", {})):
                k = r.get("infoType")
                e = infos.setdefault(k, [0, 0]); e[0] += num(r.get("events")); e[1] += num(r.get("instances"))
            for r in rows(by.get("o365_alerts", {})):
                if r.get("Operation") == "AlertTriggered":
                    alerts[r.get("severity")] += num(r.get("events"))
            for r in rows(by.get("sources", {})):
                src[r.get("source")] = r.get("status")
    ev = {"days": len(days), "gaps": []}
    ok = bool(src) and all(v == "ok" for k, v in src.items() if "trend" in k)
    total = tr["matchEvents"]
    if not days:
        ev.update(measurable=False); ev["gaps"].append("No completed DLP_Activity_Report day was found in the archive: DLP is not measurable.")
        return ev
    if not ok or total == 0:
        ev.update(measurable=False)
        ev["gaps"].append("No DLP rule matches in the window (or the Office 365 table is missing): this cannot separate 'no DLP policy' from 'no sensitive data moved', so DLP is not measurable.")
        return ev
    wl, sev, pol, rl = Counter(), Counter(), set(), set()
    ai_hits = ai_enf = 0
    for (w, p, r, m, s), n in rules.items():
        wl[w] += n; sev[s] += n; pol.add(p); rl.add(r)
        if w == AI_WORKLOAD:
            ai_hits += n; ai_enf += n if m == "Enable" else 0
    ev.update(measurable=True,
              matches={"total": total, "undo": tr["undoEvents"], "enforced": tr["enforcedEvents"], "test_mode": total - tr["enforcedEvents"],
                       "enforced_share": round(tr["enforcedEvents"] / total, 3), "undo_share": round(tr["undoEvents"] / total, 3),
                       "workloads": dict(wl.most_common()), "policies": len(pol), "rules": len(rl), "severity": dict(sev.most_common())},
              ai={"dlp_rule_hits": ai_hits, "enforced_hits": ai_enf, "unenforced_hits": ai_hits - ai_enf},
              info_types=[{"name": k, "events": v[0], "instances": v[1]} for k, v in sorted(infos.items(), key=lambda kv: -kv[1][0])[:10]],
              alerts={"total": sum(alerts.values()), "by_severity": dict(alerts)})
    ev["gaps"] += ["Policy coverage is not visible: a workload with no matches may have no DLP policy.",
                   "User overrides, external sharing, bulk downloads and web or AI egress are not in this report; AI evidence is limited to the Microsoft 365 Copilot DLP policy."]
    return ev


if __name__ == "__main__":
    a = sys.argv[1:]; out = "dlp_evidence.json"
    if "-o" in a:
        i = a.index("-o"); out = a[i + 1]; del a[i:i + 2]
    json.dump(build(a), open(out, "w"), indent=1); print("wrote", out)
