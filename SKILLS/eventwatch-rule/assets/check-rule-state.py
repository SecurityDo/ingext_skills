#!/usr/bin/env python3
"""Assert a deployed EventWatch rule matches what you released, and report its enabled state.

A released rule reaches a tenant on a sync you do not control. This checks the
content that actually landed -- a field you changed, not the id -- and exits
non-zero until it matches, so it can be polled:

    until check-rule-state.py --spec spec.json; do sleep 30; done

Spec is a JSON list; every key except "name" is optional:

    [{"name": "Fortigate_SSLVPN_Login",
      "must":     ["@fortigate.reason"],      # field paths required in mustFilters
      "must_not": ["@fortigate.user"],        # field paths required in mustNotFilters
      "no_attr":  ["TunnelIP"],               # attribute aliases that must be gone
      "threshold": 3},                        # aggregation operands[0]
     {"name": "Other_Rule", "threshold": 3, "must_not": ["@fortigate.reason"]}]

Prints the enabled state too: rule_toggle FLIPS rather than sets, and the
disabled flag is a per-tenant override that survives a sync, so read it before
toggling anything.
"""
import argparse, json, subprocess, sys


def rule_get(name):
    # NOTE: ingext eventwatch rule_get writes its JSON to STDERR, not stdout.
    p = subprocess.run(["ingext", "eventwatch", "rule_get", "--name", name],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode()
    i = out.find("{")
    if i < 0:
        return None
    try:
        return json.loads(out[i:])
    except ValueError:
        return None


def check(spec):
    name = spec["name"]
    d = rule_get(name)
    if d is None:
        print("%-44s ABSENT" % name)
        return False

    must = [f["field"] for f in d["eventSelector"].get("mustFilters") or []]
    mnot = [f["field"] for f in d["eventSelector"].get("mustNotFilters") or []]
    attrs = [a["aliase"] for a in d["behaviorRule"].get("attributes") or []]
    det = (d["behaviorRule"].get("rules") or [{}])[0]

    problems = []
    for f in spec.get("must", []):
        if f not in must:
            problems.append("missing mustFilter %s" % f)
    for f in spec.get("must_not", []):
        if f not in mnot:
            problems.append("missing mustNotFilter %s" % f)
    for al in spec.get("no_attr", []):
        if al in attrs:
            problems.append("attribute %s still present" % al)
    if "threshold" in spec:
        got = det.get("aggregation", {}).get("match", {}).get("operands", [None])[0]
        if got != spec["threshold"]:
            problems.append("threshold gt%s, want gt%s" % (got, spec["threshold"]))

    state = "disabled" if d.get("disabled") else "ENABLED"
    print("%-44s %-9s id=%-7s %s" % (
        name, state, d.get("id"), "OK" if not problems else "; ".join(problems)))
    return not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="JSON file, or '-' for stdin")
    a = ap.parse_args()
    specs = json.load(sys.stdin if a.spec == "-" else open(a.spec))
    ok = all([check(s) for s in specs])          # list(): check them all, do not short-circuit
    print("\n%s" % ("all rules match the released content"
                    if ok else "NOT yet in the expected state"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
