#!/usr/bin/env python3
"""Reduce the raw list_connectors and list_integrations results to the fields the report needs.

The raw results carry credentials and keys in their config and inputParameters. Nothing in this
report needs them, so this script keeps only names, ids, types, state and wiring, and the raw
files should be deleted afterwards.

  scrub_connectors.py --connectors RAW_CONNECTORS.json --integrations RAW_INTEGRATIONS.json --out-dir WORKDIR

Writes WORKDIR/apps.json and WORKDIR/integrations.json.
"""
import argparse, json, os, sys


def load(path):
    with open(path) as f:
        return json.load(f)


def uid(res):
    return ((res or {}).get("metadata") or {}).get("uid")


def scrub_app(entry):
    tpl = entry.get("appTemplate") or {}
    cfg = entry.get("config") or {}
    spec = (tpl.get("application") or {}).get("spec") or {}
    routers = {name: r for name, r in (tpl.get("routers") or {}).items()}
    integ = {name: i for name, i in (tpl.get("integrations") or {}).items()}
    sources = []
    for name, s in (tpl.get("dataSources") or {}).items():
        sp = s.get("spec") or {}
        conf = sp.get("config") or {}
        ref = None
        for v in conf.values():
            if isinstance(v, dict) and (v.get("integration") or v.get("integrationName")):
                ref = v.get("integration") or v.get("integrationName")
        itype = ((integ.get(ref) or {}).get("spec") or {}).get("type") if ref else None
        sources.append({"id": uid(s), "name": name, "type": sp.get("type"), "integration": itype,
                        "router": sp.get("router") or None, "disabled": bool(sp.get("disable", False))})
    return {
        "application": entry.get("application"),
        "instance": cfg.get("instance"),
        "displayName": spec.get("displayName") or cfg.get("displayName") or entry.get("application"),
        "instanceName": cfg.get("displayName"),
        "category": spec.get("category"),
        "state": entry.get("state"),
        "errorMsg": entry.get("errorMsg") or None,
        "sources": sources,
        "routers": [{"id": uid(r), "name": n} for n, r in routers.items()],
        "pipes": [{"id": uid(p), "name": n, "router": (p.get("spec") or {}).get("router")} for n, p in (tpl.get("pipes") or {}).items()],
        "sinks": [{"id": uid(k), "name": n} for n, k in (tpl.get("dataSinks") or {}).items()],
        "integrations": [{"id": uid(i), "name": n, "type": (i.get("spec") or {}).get("type")} for n, i in integ.items()],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connectors", required=True)
    ap.add_argument("--integrations", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    try:
        conns, ints = load(a.connectors), load(a.integrations)
    except (OSError, ValueError) as e:
        sys.exit("cannot read a raw result: %s" % e)
    apps = [scrub_app(e) for e in conns.get("entries", [])]
    integ = [{"id": e.get("id"), "name": e.get("name"), "integration": e.get("integration"), "inUse": bool(e.get("inUse", False))}
             for e in ints.get("entries", [])]
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump({"entries": apps}, open(os.path.join(a.out_dir, "apps.json"), "w"), indent=1)
    json.dump({"entries": integ}, open(os.path.join(a.out_dir, "integrations.json"), "w"), indent=1)
    print("wrote apps.json (%d applications) and integrations.json (%d)" % (len(apps), len(integ)))


if __name__ == "__main__":
    main()
