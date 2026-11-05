#!/usr/bin/env python3
"""Ransomware-readiness evidence from WindowsSrv_Activity_Report results.

Usage: windows_evidence.py <result.json> [more.json ...] [--days 30] [-o windows_evidence.json]

Each input is either a download_report_archive result ({"days":[{"entry","result"}]}) or one
get_report_result / run_report result ({"result":{"objects":[...]}}). Daily results are additive:
the per-day trend rows are summed and the facet counts are summed by value. Aggregate counts only;
no host, user or IP names are written. No input = visibility gap, never zeros.
"""
import json, re, sys
from collections import Counter

SUSPECT = re.compile(r"psexe|paexec|csexec|remcom|winexe|meterpreter|cobalt|beacon|ngrok|rclone|mimikatz|"
                     r"screenconnect|anydesk|teamviewer|atera|rustdesk|\\\\\\\\|cmd\.exe|powershell", re.I)


def objects(doc):
    if "days" in doc:
        for d in doc["days"]:
            if d.get("result"):
                yield d["result"]["objects"]
    else:
        yield (doc.get("result") or doc)["objects"]


def table(o):
    t = (o.get("value") or o).get("table")
    return t["rows"] if t else []


def facet(o, key):
    om = (o.get("value") or o)["orderedMap"]
    out = {}
    for k, v in zip(om["keys"], om["values"]):
        if k != key:
            continue
        for r in (v.get("sx") or {}).get("fplRows", []):
            a, b = r["values"][0]["v"], r["values"][1]["v"]
            out[a.get("string", "")] = b.get("int", 0)
    return out


def main(paths, out, expected=30):
    days = 0
    tot = Counter()
    cov = {}
    ev = {"gaps": []}
    persist, tamper_ev, tamper_actor, patterns = Counter(), Counter(), Counter(), Counter()
    clear_days = set()
    status = Counter()
    perday = {}
    for p in paths:
        doc = json.load(open(p))
        if doc.get("coverage"):
            cov = doc["coverage"]
        for objs in objects(doc):
            byname = {o["name"]: o for o in objs}
            tr = table(byname.get("win_trend", {}))
            perday[tr[0]["Date"][:10] if tr else "?%d" % len(perday)] = byname
    for date, byname in sorted(perday.items()):
        if True:
            for r in table(byname.get("win_trend", {})):
                days += 1
                for k, v in r.items():
                    if isinstance(v, (int, float)) and k != "Date":
                        tot[k] += v
                if r.get("logsCleared"):
                    clear_days.add(r.get("Date"))
            if "win_facets" in byname:
                persist.update(facet(byname["win_facets"], "persistItem"))
                tamper_ev.update(facet(byname["win_facets"], "tamperEvent"))
                tamper_actor.update(facet(byname["win_facets"], "tamperActor"))
            for r in table(byname.get("win_failed_source", {})):
                patterns[r.get("pattern")] += 1
            for r in table(byname.get("sources", {})):
                status[(r.get("source"), r.get("status"))] += 1
    if not days:
        ev["gaps"].append("No WindowsSrv_Activity_Report result: Windows audit pillar is not measurable (visibility gap)")
        json.dump(ev, open(out, "w"), indent=2); print(json.dumps(ev, indent=2)); return
    if any(s != "ok" for (_, s) in status):
        ev["gaps"].append("Some report scans were not available: " + ", ".join(sorted({f"{a}={b}" for (a, b) in status if b != "ok"})))
    keep = ["events", "logsCleared", "auditPolicyChanges", "servicesInstalled", "tasksCreated", "accountCreated",
            "accountDeleted", "accountDisabled", "accountEnabled", "groupAdds", "passwordChanges", "lockouts", "logonsOk",
            "logonsFailed", "ntlmFailures", "kerberosFailures", "explicitCreds", "privLogons", "rdpLogons", "networkLogons",
            "powershellScripts", "processCreations"]
    ev["days_covered"] = days
    ev["coverage"] = {"expected_days": cov.get("expected", expected), "archived_days": days,
                      "missing_days": cov.get("missing", max(0, expected - days))}
    if ev["coverage"]["archived_days"] < ev["coverage"]["expected_days"]:
        ev["gaps"].append("Windows audit covers %d of %d expected days; counts are for the archived days only"
                          % (days, ev["coverage"]["expected_days"]))
    ev["totals"] = {k: tot[k] for k in keep if k in tot}
    ev["log_clearing"] = {"events": tot["logsCleared"], "days_with_clears": len(clear_days),
                          "by_event_id": {k: v for k, v in tamper_ev.items() if k in ("1102", "104")},
                          "clears_with_no_recorded_actor": tamper_actor.get("(not recorded)", 0)}
    ps = {k: v for k, v in persist.items() if k not in ("(none)", "")}
    ev["persistence"] = {"distinct_items": len(ps), "services": sum(1 for k in ps if k.startswith("Service:")),
                         "tasks": sum(1 for k in ps if k.startswith("Task:")),
                         "suspect_names": sorted(k for k in ps if SUSPECT.search(k))}
    ev["failed_logon_sources"] = dict(patterns)
    json.dump(ev, open(out, "w"), indent=2)
    print(json.dumps(ev, indent=2))


if __name__ == "__main__":
    a = sys.argv[1:]
    out = "windows_evidence.json"
    exp = 30
    if "--days" in a:
        i = a.index("--days"); exp = int(a[i + 1]); a = a[:i] + a[i + 2:]
    if "-o" in a:
        i = a.index("-o"); out = a[i + 1]; a = a[:i] + a[i + 2:]
    if not a:
        sys.exit(__doc__)
    main(a, out, exp)
