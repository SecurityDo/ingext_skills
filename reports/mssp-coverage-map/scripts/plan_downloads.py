#!/usr/bin/env python3
"""List the dumps to download for the coverage map, from each account's resources.json.

  plan_downloads.py --evidence-dir DIR

Prints one line per dump: account, resource, customer, record count and the file to save it as. Call
get_resource_dump_url(account, resource, customer) for each, then
  curl -sf -o DIR/<account>/<file> "<url>"
The link expires in 15 minutes; never read it into the conversation. An account with none of the four
resources, or only empty ones, needs nothing.
"""
import argparse, json, os, re, sys

WANTED = {"office365User": "users", "falconAgent": "falcon", "sentinelOneAgent": "sentinelone", "msDefenderMachine": "defender"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    a = ap.parse_args()
    try:
        accts = json.load(open(os.path.join(a.evidence_dir, "accounts.json")))["entries"]
    except (OSError, ValueError, KeyError) as e:
        sys.exit("accounts.json is missing or unreadable: %s" % e)
    total = 0
    for ac in accts:
        try:
            res = json.load(open(os.path.join(a.evidence_dir, ac["name"], "resources.json")))
        except (OSError, ValueError):
            print("%s: no resources.json (save the list_resource_dumps result first)" % ac["name"])
            continue
        want = [e for e in res.get("entries", []) if e.get("resource") in WANTED and e.get("count")]   # an empty dump holds nothing to download
        if not want:
            print("%s: no office365User or EDR dump listed" % ac["name"])
        for e in want:
            cust = re.sub(r"[^A-Za-z0-9]+", "-", e.get("customer") or "default").strip("-")
            print("%s | %s | %s | %s records | %s_%s.jsonl.gz" % (ac["name"], e["resource"], e.get("customer"), e.get("count"), WANTED[e["resource"]], cust))
            total += 1
    print("%d dump(s) to download" % total)


if __name__ == "__main__":
    main()
