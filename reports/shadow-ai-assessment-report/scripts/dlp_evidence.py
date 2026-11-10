#!/usr/bin/env python3
"""Aggregate evidence from the archived DLP_Activity_Report (Office 365 section) into dlp_evidence.json.

  dlp_evidence.py <archive.json> [more.json ...] [-o dlp_evidence.json]

Input: download_report_archive results (days[] of {entry, result.objects}) or one get_report_result, for the daily report
DLP_Activity_Report. Objects read: o365_trend, o365_rules, o365_infoTypes, o365_alerts, o365_undos, o365_policyConfig, o365_policyChanges,
o365_sharing, sources (the last four and the trend columns undoDocModified and falsePositiveReports come from the 2026-11 report version; an
older archive still works and is flagged). The `o365_actors`
object (user names, personal data) is never read. Daily results are additive: counts are summed; a day with no completed
result is a gap, never zero. Counts and policy, workload and information-type names only: no user, file, subject or matched value.

What the report can and cannot show: it sees only policies that matched. Zero matches cannot separate "no DLP policy" from "no
sensitive data moved", so a tenant with no matches is reported as not measurable. Undo events are split by reason: an undo with the
reason DocumentModified means the file was edited, not that a user released the match, so `undo_share` counts only the other undos
(`undo_total_share` counts all). The policy configuration reads only policies created or changed inside the log retention window.
Policy inventory, overrides with a justification, bulk downloads and web or AI egress are not in this report.
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
    split = False                                  # trend carries undoDocModified (report version with reason split)
    reasons, ov_actions, cfg, changes, sharing = Counter(), Counter(), {}, Counter(), Counter()
    have = {"o365_undos": False, "o365_policyConfig": False, "o365_policyChanges": False, "o365_sharing": False}
    for p in paths:
        for done, objs in results(json.load(open(p))):
            by = {o["name"]: o for o in objs}
            if "o365_trend" not in by:
                continue
            days[done or len(days)] = 1
            for r in rows(by["o365_trend"]):
                for k in ("matchEvents", "undoEvents", "enforcedEvents", "undoDocModified", "falsePositiveReports"):
                    tr[k] += num(r.get(k))
                split = split or "undoDocModified" in r
            for r in rows(by.get("o365_rules", {})):
                rules[(r.get("workload"), r.get("policy"), r.get("ruleName"), r.get("mode"), r.get("severity"))] += num(r.get("events"))
            for r in rows(by.get("o365_infoTypes", {})):
                k = r.get("infoType")
                e = infos.setdefault(k, [0, 0]); e[0] += num(r.get("events")); e[1] += num(r.get("instances"))
            for r in rows(by.get("o365_alerts", {})):
                if r.get("Operation") == "AlertTriggered":
                    alerts[r.get("severity")] += num(r.get("events"))
            for name in have:
                have[name] = have[name] or name in by
            for r in rows(by.get("o365_undos", {})):
                reasons[r.get("reason")] += num(r.get("events"))
                if r.get("reason") != "DocumentModified":
                    for act in str(r.get("overriddenActions") or "").strip("[]").replace('"', "").split(","):
                        if act.strip() and act.strip() != "(none)":
                            ov_actions[act.strip()] += num(r.get("events"))
            for r in rows(by.get("o365_policyConfig", {})):
                e = cfg.setdefault(str(r.get("Operation")).lower(), Counter()); e["events"] += num(r.get("events"))
                for k in ("exchange", "sharepoint", "onedrive", "teams", "endpoint", "allowOverride", "blockAccess", "generateAlert"):
                    e[k] += num(r.get(k))
                if str(r.get("Operation")).lower().endswith("dlpcompliancepolicy") and r.get("mode") not in (None, "(not set)"):
                    e["mode:" + str(r.get("mode"))] += num(r.get("events"))
            for r in rows(by.get("o365_policyChanges", {})):
                changes[str(r.get("Operation"))] += num(r.get("events"))
            for r in rows(by.get("o365_sharing", {})):
                sharing[str(r.get("Operation"))] += num(r.get("events"))
            for r in rows(by.get("sources", {})):
                src[r.get("source")] = r.get("status")
    ev = {"days": len(days), "gaps": []}
    ok = bool(src) and all(v == "ok" for k, v in src.items() if "trend" in k)
    total = tr["matchEvents"]
    if not days:
        ev.update(measurable=False); ev["gaps"].append("No completed DLP_Activity_Report day was found in the archive: DLP is not measurable.")
        return ev
    if not ok:
        ev.update(measurable=False)
        ev["gaps"].append("The report's Office 365 DLP trend scan was not available on the archived days (a script error or a missing table), so match counts are unavailable and DLP is not measurable.")
        return ev
    if total == 0:
        ev.update(measurable=False)
        ev["gaps"].append("No DLP rule matches in the window: this cannot separate 'no DLP policy' from 'no sensitive data moved', so DLP is not measurable.")
        return ev
    wl, sev, pol, rl = Counter(), Counter(), set(), set()
    ai_hits = ai_enf = 0
    for (w, p, r, m, s), n in rules.items():
        wl[w] += n; sev[s] += n; pol.add(p); rl.add(r)
        if w == AI_WORKLOAD:
            ai_hits += n; ai_enf += n if m == "Enable" else 0
    other_undo = tr["undoEvents"] - tr["undoDocModified"] if split else tr["undoEvents"]
    ev.update(measurable=True,
              matches={"total": total, "undo": tr["undoEvents"], "undo_doc_modified": tr["undoDocModified"] if split else None,
                       "undo_other": other_undo, "enforced": tr["enforcedEvents"], "test_mode": total - tr["enforcedEvents"],
                       "enforced_share": round(tr["enforcedEvents"] / total, 3), "undo_share": round(other_undo / total, 3),
                       "undo_total_share": round(tr["undoEvents"] / total, 3),
                       "workloads": dict(wl.most_common()), "policies": len(pol), "rules": len(rl), "severity": dict(sev.most_common())},
              ai={"dlp_rule_hits": ai_hits, "enforced_hits": ai_enf, "unenforced_hits": ai_hits - ai_enf},
              info_types=[{"name": k, "events": v[0], "instances": v[1]} for k, v in sorted(infos.items(), key=lambda kv: -kv[1][0])[:10]],
              alerts={"total": sum(alerts.values()), "by_severity": dict(alerts)})
    # user overrides: false-positive reports and the undo reasons (counts only)
    ev["overrides"] = {"reason_split": split, "false_positive_reports": tr["falsePositiveReports"] if split else None,
                       "undo_reasons": dict(reasons.most_common()) if have["o365_undos"] else None,
                       "overridden_actions": dict(ov_actions.most_common()) if have["o365_undos"] else None}
    # policy configuration seen in the window (policies created or changed, not an inventory)
    if have["o365_policyConfig"]:
        pol, rul = cfg.get("new-dlpcompliancepolicy", Counter()), Counter()
        for k in ("new-dlpcomplianceRule".lower(), "set-dlpcompliancerule"):
            rul.update(cfg.get(k, Counter()))
        pol_all = Counter(); [pol_all.update(v) for k, v in cfg.items() if k.endswith("dlpcompliancepolicy")]
        ev["policy_config"] = {"available": True, "policies_created": pol["events"], "policies_changed": cfg.get("set-dlpcompliancepolicy", Counter())["events"],
                               "locations_covered": [x for x in ("exchange", "sharepoint", "onedrive", "teams", "endpoint") if pol[x]],
                               "rules_changed": rul["events"], "rules_allow_override": rul["allowOverride"], "rules_block_access": rul["blockAccess"],
                               "modes": {k[5:]: v for k, v in pol_all.items() if k.startswith("mode:")},
                               "changes_total": sum(changes.values()) if have["o365_policyChanges"] else None}
    else:
        ev["policy_config"] = {"available": False}
    # sharing volume (links and invitations; volume, not sensitive data)
    if have["o365_sharing"]:
        g = lambda *ks: sum(v for k, v in sharing.items() if k.lower() in [x.lower() for x in ks])
        ev["sharing"] = {"available": True, "anonymous_links_created": g("AnonymousLinkCreated"), "anonymous_link_uses": g("AnonymousLinkUsed"),
                         "company_links_created": g("CompanyLinkCreated"), "sharing_links_created": g("SharingLinkCreated"),
                         "invitations": g("SharingInvitationCreated"), "inheritance_broken": g("SharingInheritanceBroken"), "total": sum(sharing.values())}
    else:
        ev["sharing"] = {"available": False}
    ev["gaps"] += ["Policy coverage is only partly visible: new or changed policies show the locations they cover, but a workload with no matches may still have no DLP policy." if ev["policy_config"]["available"]
                   else "Policy coverage is not visible: a workload with no matches may have no DLP policy.",
                   "User overrides with a justification have no audit event; only false-positive reports, undo reasons and rules that allow override are counted." if split
                   else "Undo events are not split by reason in this archive, so the undo share includes edited documents and overstates user releases.",
                   "Bulk downloads and web or AI egress are not in this report; AI evidence is limited to the Microsoft 365 Copilot DLP policy."]
    if ev["sharing"]["available"]:
        ev["gaps"].append("Sharing counts are link and invitation volume, not proof that sensitive data was shared.")
    return ev


if __name__ == "__main__":
    a = sys.argv[1:]; out = "dlp_evidence.json"
    if "-o" in a:
        i = a.index("-o"); out = a[i + 1]; del a[i:i + 2]
    json.dump(build(a), open(out, "w"), indent=1); print("wrote", out)
