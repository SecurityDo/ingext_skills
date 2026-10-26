#!/usr/bin/env python3
"""Reduce the raw list_connector_config result to the fields the report needs.

The raw result carries credentials (client secrets, tokens, URLs) in each application's config and
integrations. Nothing in this report needs them, so this script keeps only names, ids, types,
state, errors, last-active times and 24-hour byte totals, and the raw file should be deleted
afterwards.

  scrub_config.py --config RAW_LIST_CONNECTOR_CONFIG.json --out apps.json
"""
import argparse, json, sys


def uid(res):
    return ((res or {}).get("metadata") or {}).get("uid")


def short(v):
    return json.dumps(v)[:300]


def scrub(e):
    tpl = (e.get("state") or {}).get("appTemplate") or {}
    cfg = (e.get("state") or {}).get("config") or {}
    spec = ((tpl.get("application") or {}).get("spec")) or {}
    tpl_ids = [uid(r) for k in ("routers", "dataSources", "dataSinks", "pipes", "integrations") for r in (tpl.get(k) or {}).values()]
    sources = []
    for s in e.get("sources") or []:
        plug = s.get("plugin") or {}
        sources.append({"id": s.get("id"), "name": s.get("name"), "type": s.get("type"), "integration": plug.get("integration") or None})
    traffic = {}
    ends = []
    for m in e.get("metrics") or []:
        if m.get("unit") != "bytes":
            continue
        ends.extend(m.get("slots") or [])
        t = traffic.setdefault(m["id"], {})
        t[m["action"]] = t.get(m["action"], 0) + sum(int(v or 0) for v in m.get("values") or [])
    return {
        "application": e.get("application"),
        "instance": e.get("instance"),
        "displayName": spec.get("displayName") or e.get("application"),
        "instanceName": cfg.get("displayName"),
        "state": (e.get("state") or {}).get("state"),
        "errors": short(e["errors"]) if e.get("errors") else None,
        "errorStates": short(e["errorStates"]) if e.get("errorStates") else None,
        "sources": sources,
        "routers": [{"id": r.get("id"), "name": r.get("name")} for r in e.get("routers") or []],
        "pipes": [{"id": p.get("id"), "name": p.get("name")} for p in e.get("pipes") or []],
        "sinks": [{"id": k.get("id"), "name": k.get("name")} for k in e.get("sinks") or []],
        "integrations": [{"id": i.get("id"), "name": i.get("name")} for i in e.get("integrations") or []],
        "templateIds": [i for i in tpl_ids if i],
        "lastActive": e.get("lastActive") or {},
        "traffic": traffic,
    }, (max(ends) if ends else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        with open(a.config) as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("cannot read the raw result: %s" % e)
    apps, ends = [], []
    for e in raw.get("entries", []):
        app, end = scrub(e)
        apps.append(app)
        if end:
            ends.append(end)
    with open(a.out, "w") as f:
        json.dump({"capturedAtMs": max(ends) if ends else None, "entries": apps}, f, indent=1)
    print("wrote %s (%d applications)" % (a.out, len(apps)))


if __name__ == "__main__":
    main()
