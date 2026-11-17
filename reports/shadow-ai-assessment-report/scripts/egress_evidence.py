#!/usr/bin/env python3
"""Aggregate path 2 (network egress to AI services) from the archived egress reports into egress_evidence.json.

  egress_evidence.py <archive.json> [more.json ...] [-o egress_evidence.json]

Inputs: download_report_archive results (days[] of {entry, result.objects}) or one get_report_result, for either or both of
  Fortigate_Traffic_Activity_Report  objects traffic_dims, sources   (never traffic_talkers: internal hosts and addresses)
  Zscaler_Web_Activity_Report        objects web_dims, sources
The product is detected from the objects in each day, so the files can be given in any order and mixed.
FortiGate: traffic_dims rows are (dim, val, outcome) with events, bytesOut, bytesIn. device (every event) gives the total, app (application
| category) shows whether the firewall names applications, genaiApp (GenAI only), genaiSource (source address | host | application),
genaiDestination (address | country | application) and genaiPolicy give the detail. Zscaler: web_dims rows are (isGenAI, app, category,
appClass, domain, outcome) with events, bytesOut, bytesIn, users, devices (distinct per row and day); Zscaler classifies GenAI itself and
records the requested domain.
Counts, application names, destination domains and countries only: no address, host, user or device name is written. Events and volumes add
across days. Distinct internal sources (FortiGate) and users (Zscaler) cannot, so the figure is the busiest day's count, a lower bound (for
Zscaler the largest single application-and-domain row of the day, so it is a lower bound again).

What it can and cannot show. FortiGate sees the application name and category, the destination address and country, not the domain; a tenant
whose policies do not run Application Control has no application names and is reported as "no_app_control" (not assessed), never clean.
Zscaler sees the domain but only for web traffic through the proxy; its DNS and firewall logs are not read. A product with no archived day is
not assessed; proxies other than these, and other firewalls, are not covered.
"""
import argparse, json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(HERE, "..", "assets", "ai_catalog.json")))
SVC = [(s, re.compile(s["rx"], re.I)) for s in CAT["services"]]
FIRST_PARTY = {"Microsoft Copilot"}
NOT_REC = "(not recorded)"
NAMES = {"fortigate": "FortiGate", "zscaler": "Zscaler"}


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


def truth(v):
    return v is True or str(v).lower() in ("true", "1")


def service(app):
    for s, rx in SVC:
        if rx.search(app or ""):
            return s
    return None


class Product:
    def __init__(self, key):
        self.key, self.days, self.ok, self.bad = key, {}, 0, []
        self.total = self.named = 0
        self.apps = defaultdict(lambda: {"events": 0, "blocked": 0, "bytes_out": 0, "category": "", "domains": defaultdict(int)})
        self.peak = defaultdict(int); self.countries, self.policies = set(), set(); self.src_by_day = defaultdict(set)

    def scan(self, day, by, dims, scan_name):
        self.days[day] = 1
        for r in rows(by.get("sources", {})):
            if str(r.get("source", "")).endswith(scan_name):
                if r.get("status") == "ok":
                    self.ok += 1
                else:
                    self.bad.append(r.get("detail") or "not available")
        for r in rows(by[dims]):
            ev = num(r.get("events"))
            if self.key == "zscaler":
                self.total += ev; self.named += ev
                if not truth(r.get("isGenAI")):
                    continue
                a = self.apps[str(r.get("app") or NOT_REC)]
                a["events"] += ev; a["bytes_out"] += num(r.get("bytesOut")); a["category"] = r.get("category") or ""
                a["domains"][str(r.get("domain") or NOT_REC)] += ev
                if r.get("outcome") == "blocked":
                    a["blocked"] += ev
                self.peak[day] = max(self.peak[day], num(r.get("users")))
                continue
            dim, parts = r.get("dim"), [x.strip() for x in str(r.get("val") or "").split(" | ")]
            if dim == "device":
                self.total += ev
            elif dim == "app" and parts[0] != NOT_REC:
                self.named += ev
            elif dim == "genaiApp":
                a = self.apps[parts[0]]
                a["events"] += ev; a["bytes_out"] += num(r.get("bytesOut")); a["category"] = parts[1] if len(parts) > 1 else ""
                if r.get("outcome") == "blocked":
                    a["blocked"] += ev
            elif dim == "genaiSource":
                self.src_by_day[day].add(" | ".join(parts[:2]))
            elif dim == "genaiDestination" and len(parts) > 1:
                self.countries.add(parts[1])
            elif dim == "genaiPolicy":
                self.policies.add(parts[0])
        if self.key == "fortigate":
            self.peak[day] = len(self.src_by_day[day])


def build(paths, rules):
    prods = {"fortigate": Product("fortigate"), "zscaler": Product("zscaler")}
    for p in paths:
        for done, objs in results(json.load(open(p))):
            by = {o["name"]: o for o in objs}
            if "traffic_dims" in by:
                prods["fortigate"].scan(done or str(len(prods["fortigate"].days)), by, "traffic_dims", "dimensions")
            if "web_dims" in by:
                prods["zscaler"].scan(done or str(len(prods["zscaler"].days)), by, "web_dims", "transactions")
    out = {"status": "no_data", "days": 0, "products": [], "gaps": [], "sources": []}
    svcs, assessed = {}, []
    peak = g_ev = g_blk = g_out = total = 0
    countries, policies = set(), set()
    for key, pr in prods.items():
        name = NAMES[key]
        if not pr.days:
            continue
        info = {"product": name, "days": len(pr.days), "status": "assessed"}
        out["days"] = max(out["days"], len(pr.days)); out["sources"].append({"fortigate": "Fortigate_Traffic_Activity_Report archive", "zscaler": "Zscaler_Web_Activity_Report archive"}[key])
        if pr.ok < len(pr.days):
            out["gaps"].append("The %s scan was not available on %d of %d archived days (%s); those days are not counted." % (name, len(pr.days) - pr.ok, len(pr.days), (pr.bad[0] if pr.bad else "no detail")[:120]))
        share = round(pr.named / pr.total, 3) if pr.total else 0.0
        info["total_events"], info["named_share"] = pr.total, share
        if pr.total == 0:
            info["status"] = "no_data"; out["gaps"].append("The archived %s days hold no traffic: that product is not assessed." % name)
        elif key == "fortigate" and share < rules["app_named_share_min"]:
            info["status"] = "no_app_control"
            out["gaps"].append("FortiGate traffic carries no application names (%.0f%% of events), so Application Control is not enabled on the policies and AI use cannot be told from other traffic. FortiGate is not assessed; it is not clean." % (100 * share))
        if info["status"] == "assessed":
            assessed.append(key)
            for n_, a in pr.apps.items():
                s = service(n_); k = s["name"] if s else n_
                e = svcs.setdefault(k, {"service": k, "category": (s or {}).get("category") or a["category"], "tier": (s or {}).get("tier", "-"), "first_party": k in FIRST_PARTY,
                                        "events": 0, "blocked": 0, "bytes_out": 0, "products": [], "_dom": defaultdict(int)})
                e["events"] += a["events"]; e["blocked"] += a["blocked"]; e["bytes_out"] += a["bytes_out"]
                if name not in e["products"]: e["products"].append(name)
                for d_, v in a["domains"].items():
                    e["_dom"][d_] += v
            info["genai_events"] = sum(a["events"] for a in pr.apps.values())
            peak = max(peak, max(pr.peak.values() or [0])); total += pr.total
            countries |= pr.countries; policies |= pr.policies
        out["products"].append(info)
    if not out["products"]:
        out["gaps"].append("No archived Fortigate_Traffic_Activity_Report or Zscaler_Web_Activity_Report day: network egress to AI services is not assessed (other firewalls, proxies and DNS are not covered).")
        return out
    if not assessed:
        out["status"] = "no_app_control" if any(p["status"] == "no_app_control" for p in out["products"]) else "no_data"
        return out
    sv = sorted(svcs.values(), key=lambda x: -x["events"])
    for x in sv:
        x["domains"] = [d for d, _ in sorted(x.pop("_dom").items(), key=lambda kv: -kv[1]) if d != NOT_REC][:5]
    g = sum(x["events"] for x in sv)
    out.update({"status": "assessed", "total_events": total, "genai_events": g, "genai_share": round(g / total, 5) if total else 0.0, "genai_blocked": sum(x["blocked"] for x in sv),
                "genai_bytes_out": sum(x["bytes_out"] for x in sv), "services": sv, "non_first_party_allowed": sum(x["events"] - x["blocked"] for x in sv if not x["first_party"]),
                "sources_peak_day": peak, "countries": sorted(countries), "policies": len(policies)})
    out["gaps"].append("Network egress covers %s only (%s). Other firewalls, proxies and DNS are not covered. Distinct internal sources or users are the busiest day's figure, a lower bound." % (
        " and ".join(NAMES[k] for k in assessed), "FortiGate by application name and category, Zscaler web traffic by application and domain"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archives", nargs="+"); ap.add_argument("-o", "--out", default="egress_evidence.json")
    ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    a = ap.parse_args()
    ev = build(a.archives, json.load(open(a.rules))["network"])
    json.dump(ev, open(a.out, "w"), indent=1)
    print("egress %s | products %s | genai events %s | wrote %s" % (ev["status"], ",".join(p["product"] for p in ev["products"]) or "none", ev.get("genai_events", "n/a"), a.out))


if __name__ == "__main__":
    main()
