#!/usr/bin/env python3
"""Aggregate path 2 (network egress to AI services) from the archived Fortigate_Traffic_Activity_Report into egress_evidence.json.

  egress_evidence.py <archive.json> [more.json ...] [-o egress_evidence.json]

Input: download_report_archive results (days[] of {entry, result.objects}) or one get_report_result, for the daily report
Fortigate_Traffic_Activity_Report, objects traffic_dims and sources only (never traffic_talkers: internal hosts and addresses).
Rows of traffic_dims are (dim, val, outcome) with events, bytesOut, bytesIn. Read: device (every event, so its sum is the total), app
(application | category, to see whether the firewall names applications), genaiApp (application | category, GenAI events only),
genaiSource (source address | host | application) and genaiDestination (destination address | country | application), genaiPolicy.
Counts, application names and countries only: no address and no host name is written. Events and volumes add across days. Distinct
internal sources cannot, so the figure is the busiest day's count (a lower bound).

What it can and cannot show: FortiGate firewalls only, by application name and category, not by domain or URL. A tenant whose
firewall policies do not run Application Control has no application names; that is reported as "no_app_control" (not assessed),
never as clean, because "sources" cannot tell the two apart. A tenant with no archived day is "no_data".
"""
import argparse, json, os, re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(HERE, "..", "assets", "ai_catalog.json")))
SVC = [(s, re.compile(s["rx"], re.I)) for s in CAT["services"]]
FIRST_PARTY = {"Microsoft Copilot"}
NOT_REC = "(not recorded)"


def results(doc):
    if "days" in doc:
        for d in doc["days"]:
            if d.get("result"):
                yield (d.get("entry") or {}).get("rangeFrom", ""), d["result"]["objects"]
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


def service(app):
    for s, rx in SVC:
        if rx.search(app or ""):
            return s
    return None


def build(paths, rules):
    days, total, named = {}, 0, 0
    apps = defaultdict(lambda: {"events": 0, "blocked": 0, "bytes_out": 0, "category": ""})
    src_by_day, countries, policies = defaultdict(set), set(), set()
    ok, bad = 0, []
    for p in paths:
        for done, objs in results(json.load(open(p))):
            by = {o["name"]: o for o in objs}
            if "traffic_dims" not in by:
                continue
            day = done or str(len(days))
            days[day] = 1
            for r in rows(by.get("sources", {})):
                if str(r.get("source", "")).endswith("dimensions"):
                    if r.get("status") == "ok":
                        ok += 1
                    else:
                        bad.append(r.get("detail") or "not available")
            for r in rows(by["traffic_dims"]):
                dim, val, ev = r.get("dim"), str(r.get("val") or ""), num(r.get("events"))
                parts = [x.strip() for x in val.split(" | ")]
                if dim == "device":
                    total += ev
                elif dim == "app" and parts[0] != NOT_REC:
                    named += ev
                elif dim == "genaiApp":
                    a = apps[parts[0]]
                    a["events"] += ev; a["bytes_out"] += num(r.get("bytesOut")); a["category"] = parts[1] if len(parts) > 1 else ""
                    if r.get("outcome") == "blocked":
                        a["blocked"] += ev
                elif dim == "genaiSource":
                    src_by_day[day].add(" | ".join(parts[:2]))
                elif dim == "genaiDestination" and len(parts) > 1:
                    countries.add(parts[1])
                elif dim == "genaiPolicy":
                    policies.add(parts[0])
    out = {"status": "no_data", "days": len(days), "gaps": [], "sources": []}
    if not days:
        out["gaps"].append("No archived Fortigate_Traffic_Activity_Report day: network egress to AI services is not assessed (FortiGate only; other firewalls, proxies and DNS are not covered).")
        return out
    if ok < len(days):
        out["gaps"].append("The FortiGate traffic scan was not available on %d of %d archived days (%s); those days are not counted." % (len(days) - ok, len(days), (bad[0] if bad else "no detail")[:120]))
    out["sources"].append("Fortigate_Traffic_Activity_Report archive")
    out["total_events"], out["named_share"] = total, round(named / total, 3) if total else 0.0
    if total == 0:
        out["gaps"].append("The archived FortiGate days hold no traffic: network egress is not assessed.")
        return out
    if out["named_share"] < rules["app_named_share_min"]:
        out["status"] = "no_app_control"
        out["gaps"].append("FortiGate traffic carries no application names (%.0f%% of events), so Application Control is not enabled on the policies and AI use cannot be told from other traffic. Network egress is not assessed; it is not clean." % (100 * out["named_share"]))
        return out
    svcs = {}
    for name, a in apps.items():
        s = service(name)
        key = s["name"] if s else name
        e = svcs.setdefault(key, {"service": key, "category": (s or {}).get("category") or a["category"], "tier": (s or {}).get("tier", "-"),
                                  "first_party": key in FIRST_PARTY, "events": 0, "blocked": 0, "bytes_out": 0})
        e["events"] += a["events"]; e["blocked"] += a["blocked"]; e["bytes_out"] += a["bytes_out"]
    sv = sorted(svcs.values(), key=lambda x: -x["events"])
    g = sum(x["events"] for x in sv)
    out.update({"status": "assessed", "genai_events": g, "genai_share": round(g / total, 5), "genai_blocked": sum(x["blocked"] for x in sv),
                "genai_bytes_out": sum(x["bytes_out"] for x in sv), "services": sv,
                "non_first_party_allowed": sum(x["events"] - x["blocked"] for x in sv if not x["first_party"]),
                "sources_peak_day": max([len(v) for v in src_by_day.values()] or [0]), "countries": sorted(countries), "policies": len(policies)})
    out["gaps"].append("Network egress covers FortiGate only, by application name and category (no domain or URL); other firewalls, proxies and DNS are not covered. Distinct internal sources are the busiest day's count (a lower bound).")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archives", nargs="+"); ap.add_argument("-o", "--out", default="egress_evidence.json")
    ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    a = ap.parse_args()
    ev = build(a.archives, json.load(open(a.rules))["network"])
    json.dump(ev, open(a.out, "w"), indent=1)
    print("egress %s | days %d | genai events %s | wrote %s" % (ev["status"], ev["days"], ev.get("genai_events", "n/a"), a.out))


if __name__ == "__main__":
    main()
