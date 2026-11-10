#!/usr/bin/env python3
"""Evidence retention and scope coverage for the disclosure report.

  platform_evidence.py --tables tables.json --retention retention.json --asof YYYY-MM-DD
                       [--clearing clearing.json] [--rules ../assets/rating_rules.json] -o platform_evidence.json

  --tables     the list_data_tables reply (streamTables / resourceTables) for the tenant.
  --retention  {"<Table>": {"first": "<earliest timestamp>", "last": "<latest>", "n": <rows>}, ...}, one entry per key
               table, from `summarize first=min(<time>), last=max(<time>), n=count()` over the last 12 months
               (time column: `timestamp`, or `TimeGenerated` for the Azure tables).
  --clearing   optional {"count": <n>, "days": <window>} for domain-controller / Windows security-log clearing events
               (Event 1102 / 104). Without it, evidence integrity is reported as not checked.

Retention is the age of the oldest event held, so it can only understate a longer retention policy; the report says so.
"""
import argparse, datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def parse(ts):
    ts = str(ts).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True); ap.add_argument("--retention", required=True); ap.add_argument("--asof", required=True)
    ap.add_argument("--clearing"); ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json")); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    rules = json.load(open(a.rules)); asof = datetime.datetime.strptime(a.asof, "%Y-%m-%d")
    tb = json.load(open(a.tables))
    names = [t["name"] for t in (tb.get("streamTables") or [])] + [t["name"] for t in (tb.get("resourceTables") or [])]
    low = {n.lower(): n for n in names}
    scope = {}
    for cat, spec in rules["scope_categories"].items():
        hit = sorted({low[k] for k in low for pat in spec["tables"] if pat.lower() in k})
        scope[cat] = {"label": spec["label"], "present": bool(hit), "tables": hit}
    ret = json.load(open(a.retention))
    held = {}
    for t, v in ret.items():
        f = parse(v.get("first")) if v.get("first") else None
        if f:
            held[t] = {"days": (asof - f).days, "first": f.strftime("%Y-%m-%d"), "rows": v.get("n")}
    days = [v["days"] for v in held.values()]
    out = {"asof": a.asof, "tables_present": sorted(names), "scope": scope,
           "retention": {"tables": held, "min_days": min(days) if days else None, "max_days": max(days) if days else None},
           "clearing": None}
    if a.clearing:
        c = json.load(open(a.clearing)); out["clearing"] = {"count": int(c.get("count", 0)), "days": int(c.get("days", 30))}
    json.dump(out, open(a.out, "w"), indent=1)
    print("retention %s-%s days over %d tables | scope present: %s | wrote %s" % (
        out["retention"]["min_days"], out["retention"]["max_days"], len(held), ", ".join(k for k, v in scope.items() if v["present"]) or "none", a.out))


if __name__ == "__main__":
    main()
