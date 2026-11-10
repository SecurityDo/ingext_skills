#!/usr/bin/env python3
"""Scope coverage and evidence integrity for the disclosure report. No event search is needed.

  platform_evidence.py --tables tables.json --asof YYYY-MM-DD [--windows-archive windows_archive.json]
                       [--rules ../assets/rating_rules.json] -o platform_evidence.json

  --tables           the list_data_tables reply (streamTables / resourceTables); metadata only.
  --windows-archive  download_report_archive of WindowsSrv_Activity_Report (objects win_trend and sources), last 30 days.
                     The sum of win_trend.logsCleared (Event 1102 and 104) is the log-clearing count. A tenant with no
                     archived days leaves evidence integrity as "not checked".

Retention is not measured: every tenant keeps 12 months of logs (platform guarantee, assets/rating_rules.json).
"""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def rows_of(obj):
    """Rows of one report object: table.rows as dicts, or value.table with columns and rows."""
    t = obj.get("table") or (obj.get("value") or {}).get("table") or {}
    rows = t.get("rows") or []
    cols = [c if isinstance(c, str) else c.get("name") for c in (t.get("columns") or [])]
    out = []
    for r in rows:
        out.append(r if isinstance(r, dict) else dict(zip(cols, r)))
    return out


def windows_clearing(path):
    d = json.load(open(path))
    days = d.get("days") if isinstance(d, dict) else d
    count = events = ndays = 0
    for day in days or []:
        objs = ((day.get("result") or {}).get("objects")) or day.get("objects") or []
        trend = [o for o in objs if o.get("name") == "win_trend"]
        if not trend:
            continue
        ndays += 1
        for r in rows_of(trend[0]):
            count += int(r.get("logsCleared") or 0); events += int(r.get("events") or 0)
    return {"count": count, "days": ndays, "events": events, "source": "WindowsSrv_Activity_Report archive"} if ndays else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True); ap.add_argument("--asof", required=True); ap.add_argument("--windows-archive")
    ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json")); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    rules = json.load(open(a.rules))
    tb = json.load(open(a.tables))
    names = [t["name"] for t in (tb.get("streamTables") or [])] + [t["name"] for t in (tb.get("resourceTables") or [])]
    low = {n.lower(): n for n in names}
    scope = {}
    for cat, spec in rules["scope_categories"].items():
        hit = sorted({low[k] for k in low for pat in spec["tables"] if pat.lower() in k})
        scope[cat] = {"label": spec["label"], "present": bool(hit), "tables": hit}
    clearing = windows_clearing(a.windows_archive) if a.windows_archive else None
    if clearing and clearing["events"] and not scope["endpoint"]["present"]:
        scope["endpoint"] = {"label": rules["scope_categories"]["endpoint"]["label"], "present": True, "tables": ["WindowsAudit (archived report)"]}
    out = {"asof": a.asof, "tables_present": sorted(names), "scope": scope,
           "retention": {"guaranteed_days": rules["retention"]["guaranteed_days"], "source": "platform guarantee"}, "clearing": clearing}
    json.dump(out, open(a.out, "w"), indent=1)
    print("scope present: %s | clearing %s | wrote %s" % (", ".join(k for k, v in scope.items() if v["present"]) or "none",
          ("%d events in %d days" % (clearing["count"], clearing["days"])) if clearing else "not checked", a.out))


if __name__ == "__main__":
    main()
