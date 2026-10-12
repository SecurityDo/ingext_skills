#!/usr/bin/env python3
"""Deploy (add or update) an fpl_report with its reportConfig and arguments.

`ingext processor add` cannot carry reportConfig or arguments, so this posts the full
entry to platform_processor_dao. Prefer the MCP processor_add / processor_update tools
where the tenant has them.

    INGEXT_SITE_URL=https://<provider>.app.ingext.io INGEXT_TOKEN=... \
      deploy_report.py --meta fplProcessors/meta/X.json --script fplProcessors/code/X.js \
                       --account <tenant> --name X_test [--update]

--name defaults to "<meta name>_test" and the entry is deployed with id 0 (site-local),
so it never collides with the released copy. The token is read from the environment and
never printed.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--account", required=True, help="tenant, without the acc- prefix")
    ap.add_argument("--name", help="deployed name (default: <meta name>_test)")
    ap.add_argument("--update", action="store_true", help="update an existing entry")
    args = ap.parse_args()

    site = os.environ.get("INGEXT_SITE_URL")
    token = os.environ.get("INGEXT_TOKEN")
    if not site or not token:
        sys.exit("set INGEXT_SITE_URL and INGEXT_TOKEN")

    meta = json.load(open(args.meta))
    if meta.get("type") != "fpl_report":
        sys.exit("meta type is %r, expected fpl_report" % meta.get("type"))
    entry = dict(meta)
    entry["id"] = 0
    entry["name"] = args.name or meta["name"] + "_test"
    entry["description"] = "TEST: " + meta.get("description", "")
    entry["scriptText"] = open(args.script).read()
    for k in ("gitPath", "createdOn", "updatedOn"):
        entry.pop(k, None)

    keys = [p["key"] for p in entry["reportConfig"]["panels"]]
    ids = [l["id"] for l in entry["reportConfig"]["layout"]]
    if sorted(keys) != sorted(ids):
        sys.exit("panel keys and layout ids differ: %s" % sorted(set(keys) ^ set(ids)))

    body = json.dumps({"function": "platform_processor_dao",
                       "kargs": {"action": "update" if args.update else "add",
                                 "args": {"entry": entry}}}).encode()
    url = "%s/api/ds/platform_processor_dao?gridaccount=%s" % (
        site.rstrip("/"), urllib.parse.quote(args.account))
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %d: %s" % (e.code, e.read().decode()[:500]))
    if out.get("verdict") != "OK":
        sys.exit("%s: %s" % (out.get("verdict"), out.get("exception")))
    print("%s %s on %s" % ("updated" if args.update else "added", entry["name"], args.account))


if __name__ == "__main__":
    main()
