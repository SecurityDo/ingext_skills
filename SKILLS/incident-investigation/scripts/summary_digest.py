#!/usr/bin/env python3
"""Digest a behavior_summary_search response.

    python3 summary_digest.py summary.json                      # every key in the response
    python3 summary_digest.py summary.json user@corp.com        # one entity's daily history
    python3 summary_digest.py summary.json user@corp.com --ai   # + the AI-assist verdict
    python3 summary_digest.py summary.json --rule AzureAD_User_Add_Authentication_Method

`--query` on `eventwatch search_summary` is a free-text match, not a key filter:
searching for one username returns every summary whose document mentions it,
which on a shared domain is most of the tenant. Filter on `key` here instead.

`--rule` is the base-rate check: how many DISTINCT entities fired one rule in the
window, and how many of those became incidents. Run it before believing any
single-entity verdict.
"""

import datetime
import json
import sys
from collections import Counter


def load(path):
    body = json.load(open(path))
    return [h["_source"] for h in body["response"]["hits"]["hits"]]


def ts(ms):
    if not ms:
        return "-"
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def daily(rows, key):
    rows = [r for r in rows if (r.get("key") or "").lower() == key.lower()]
    rows.sort(key=lambda r: r.get("from") or 0)
    if not rows:
        print("no summaries for {} -- check the key's exact spelling in the "
              "unfiltered listing".format(key))
        return
    print("{} -- {} daily summaries\n".format(key, len(rows)))
    for r in rows:
        flag = "INCIDENT" if r.get("incident") else ""
        print("{}  {} -> {}  n={:<4} risk={:<6} {:<9} {}".format(
            r.get("dayIndex"), ts(r.get("from")), ts(r.get("to")),
            r.get("count", 0), r.get("riskScore", 0), flag,
            ",".join(r.get("behaviorRules") or [])))
    scores = [r.get("riskScore", 0) for r in rows]
    peak = max(scores)
    others = [s for s in scores if s != peak]
    print("\npeak {}  |  next highest {}  |  median {}".format(
        peak, max(others) if others else 0,
        sorted(scores)[len(scores) // 2]))


def base_rate(rows, rule):
    hit = [r for r in rows if rule in (r.get("behaviorRules") or [])]
    keys = set(r.get("key") for r in hit)
    inc = [r for r in hit if r.get("incident")]
    print("rule: {}".format(rule))
    print("  summaries carrying it : {}".format(len(hit)))
    print("  distinct entities     : {}".format(len(keys)))
    print("  raised as incidents   : {}".format(len(inc)))
    print("  riskScore spread      : {}".format(
        Counter(r.get("riskScore") for r in hit).most_common()))
    if len(keys) > 5:
        print("\n  >5 entities fired this rule in the window. That is a fleet "
              "pattern (a rollout, a policy change, a vendor push), not a "
              "targeted event. Identify the campaign before writing a verdict.")
    print()
    for r in sorted(inc, key=lambda x: -(x.get("riskScore") or 0))[:20]:
        print("  {:<42} {} risk={:<6} risks={}".format(
            r.get("key"), r.get("dayIndex"), r.get("riskScore"), r.get("risks")))


def ai_verdict(rows, key):
    """The AI-assist workflow leaves its result as a JSON string in comments[]."""
    for r in rows:
        if (r.get("key") or "").lower() != key.lower():
            continue
        for c in r.get("comments") or []:
            if c.get("username") != "AI-Assistant":
                continue
            try:
                v = json.loads(c["content"])
            except Exception:
                print(c["content"])
                continue
            print("--- AI-assist verdict on {} ---".format(r.get("dayIndex")))
            print("actionable : {}".format(v.get("actionable")))
            print("severity   : {}".format(v.get("severity")))
            print("close      : {}".format(v.get("close")))
            print("summary    : {}\n".format(v.get("summary")))
            for w in v.get("workflowList") or []:
                res = w.get("result", {})
                print("  [{}] actionable={} -- {}".format(
                    w.get("workflow_name"), res.get("actionable"),
                    res.get("summary")))
            print("\nkeyQuestions:")
            for q in v.get("keyQuestions") or []:
                print("  - {}".format(q))


def overview(rows):
    print("{} summaries, {} distinct keys\n".format(
        len(rows), len(set(r.get("key") for r in rows))))
    agg = {}
    for r in rows:
        k = r.get("key")
        cur = agg.setdefault(k, {"n": 0, "peak": 0, "inc": 0})
        cur["n"] += 1
        cur["peak"] = max(cur["peak"], r.get("riskScore") or 0)
        cur["inc"] += 1 if r.get("incident") else 0
    for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["peak"])[:40]:
        print("  {:<44} days={:<4} peak={:<6} incidents={}".format(
            k, v["n"], v["peak"], v["inc"]))


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    rows = load(argv[1])
    rest = argv[2:]

    if "--rule" in rest:
        base_rate(rows, rest[rest.index("--rule") + 1])
        return
    key = next((a for a in rest if not a.startswith("--")), None)
    if not key:
        overview(rows)
        return
    daily(rows, key)
    if "--ai" in rest:
        print()
        ai_verdict(rows, key)


if __name__ == "__main__":
    main(sys.argv)
