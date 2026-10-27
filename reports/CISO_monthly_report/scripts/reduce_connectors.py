#!/usr/bin/env python3
"""Reduce a raw list_connectors (or list_connector_config) result to {"entries": [{"application", "state"}]}.

The raw results carry credentials in clear text (API keys, HEC and integration tokens). The report
needs only each application and its state, so save only the output of this script and delete the raw file.

  reduce_connectors.py --raw RAW.json --out connectors.json
"""
import argparse, json, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        with open(a.raw) as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("cannot read %s: %s" % (a.raw, e))
    out = []
    for e in raw.get("entries", []):
        st = e.get("state")
        if isinstance(st, dict):          # list_connector_config nests the state
            st = st.get("state")
        out.append({"application": e.get("application"), "instance": e.get("instance"), "state": st})
    with open(a.out, "w") as f:
        json.dump({"entries": out}, f, indent=1)
    print("wrote %s (%d applications)" % (a.out, len(out)))


if __name__ == "__main__":
    main()
