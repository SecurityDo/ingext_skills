#!/usr/bin/env python3
"""Read the office365InstalledApp resource dump locally and write the application-to-publisher map (the only thing the archives do not carry).

  dump_evidence.py --apps office365InstalledApp.jsonl.gz -o apps.json

--apps  the office365InstalledApp dump (get_resource_dump_url, format jsonl; .jsonl, .jsonl.gz or .parquet).
Writes apps.json: a list of {appId, displayName, verified}, where verified is the verified publisher name ('' when the application is not verified).
Applications only: no user is read. drift_evidence.py --apps joins the application ids in the archived grants to this map.
"""
import argparse, gzip, json


def records(path):
    if path.endswith(".parquet"):
        import pandas as pd
        for r in pd.read_parquet(path).to_dict("records"):
            yield r
        return
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def flat(rec):
    """The object itself, whether the dump wraps it (value / source / data) or not."""
    for k in ("value", "source", "data", "record"):
        if isinstance(rec.get(k), dict):
            return rec[k]
    return rec


def get(rec, path, default=None):
    if path in rec:
        return rec[path]
    cur = rec
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apps", required=True); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    rows, seen = [], set()
    for rec in records(a.apps):
        u = flat(rec); aid = get(u, "appId")
        if aid and aid not in seen:
            seen.add(aid)
            rows.append({"appId": aid, "displayName": get(u, "displayName") or "", "verified": str(get(u, "verifiedPublisher.displayName") or "")})
    json.dump(rows, open(a.out, "w"))
    print("applications %d (%d verified) | wrote %s" % (len(rows), sum(1 for r in rows if r["verified"]), a.out))


if __name__ == "__main__":
    main()
