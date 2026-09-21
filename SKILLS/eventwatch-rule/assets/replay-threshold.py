#!/usr/bin/env python3
"""Replay real events against candidate aggregation thresholds.

An aggregation rule's threshold is a claim about the data. This checks it against
the data, by computing the maximum count in any sliding window, per key.

    ingext datalake search --index default --query '<selector>' \
        --from <ms> --to <ms> --limit 500 --output /tmp/hits.json

    replay-threshold.py /tmp/hits.json --key '@fortigate.user' --window 4h
    replay-threshold.py /tmp/hits.json --key '@fortigate.user' --exclude '@fortigate.reason=wrong vdom (0:0) or time expired'
    replay-threshold.py /tmp/hits.json --key '@fortigate.user' --overlap '@fortigate.tunneltype'

Remember the rule fires at N+1: "gt3" in the table below means operands [3, 0].
"""
import argparse, collections, json, re, sys


def get(src, path):
    if path in src:                       # flat, e.g. '@timestamp'
        return src[path]
    head, _, rest = path.partition(".")
    cur = src.get(head)
    for part in rest.split(".") if rest else []:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def parse_window(text):
    m = re.fullmatch(r"(\d+)([smhd])", text.strip())
    if not m:
        sys.exit("--window must look like 30m, 4h, 1d")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * 1000


def max_in_window(pairs, window_ms):
    """pairs: [(ts_ms, key)] -> {key: max count in any window}"""
    by = collections.defaultdict(list)
    for ts, k in pairs:
        by[k].append(ts)
    out = collections.Counter()
    for k, tss in by.items():
        tss.sort()
        best, j = 0, 0
        for i, t in enumerate(tss):       # two pointers, O(n) per key
            while tss[j] < t - window_ms:
                j += 1
            best = max(best, i - j + 1)
        out[k] = best
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hits", help="JSON from 'ingext datalake search --output'")
    ap.add_argument("--key", required=True, help="field path to key on, e.g. @fortigate.user")
    ap.add_argument("--window", default="4h", help="sliding window (default 4h)")
    ap.add_argument("--ts", default="@timestamp", help="timestamp field (ms)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="'field=value' to drop before counting (repeatable)")
    ap.add_argument("--skip", action="append", default=["N/A", ""],
                    help="key values to ignore (default: N/A and empty)")
    ap.add_argument("--overlap",
                    help="field path: report keys carrying >1 distinct value (double-count check)")
    a = ap.parse_args()

    doc = json.load(open(a.hits))
    hits = doc.get("hits", {}).get("hits") or doc.get("hits") or []
    if not hits:
        sys.exit("no hits in %s -- was --limit high enough?" % a.hits)

    rows, dropped = [], 0
    for h in hits:
        src = h.get("_source", h)
        keep = True
        for ex in a.exclude:
            f, _, v = ex.partition("=")
            if str(get(src, f)) == v:
                keep = False
                break
        if not keep:
            dropped += 1
            continue
        rows.append(src)

    print("events: %d total, %d after --exclude" % (len(hits), len(rows)))
    if len(hits) >= 500:
        print("  NOTE: hit the search --limit; counts may be truncated")

    pairs = [(get(r, a.ts), str(get(r, a.key))) for r in rows]
    pairs = [(t, k) for t, k in pairs if t and k not in a.skip and k != "None"]
    if not pairs:
        sys.exit("no events left with a usable key at %s" % a.key)

    w = parse_window(a.window)
    peaks = max_in_window(pairs, w)

    print("\n=== max in any %s window, by %s ===" % (a.window, a.key))
    for k, v in peaks.most_common(10):
        print("   %-44s %d" % (k, v))

    print("\n=== alerts per replay period at candidate thresholds ===")
    print("   " + "  ".join("gt%d:%d" % (t, sum(1 for v in peaks.values() if v > t))
                            for t in (1, 2, 3, 4, 5, 7, 9, 10)))
    best = max(peaks.values())
    print("\n   highest single key peaked at %d, so any threshold >= %d never fires." % (best, best))

    if a.overlap:
        multi = collections.defaultdict(set)
        for r in rows:
            k = str(get(r, a.key))
            if k in a.skip:
                continue
            multi[k].add(str(get(r, a.overlap)))
        n_multi = sum(1 for s in multi.values() if len(s) > 1)
        print("\n=== double-count check on %s ===" % a.overlap)
        print("   %d of %d keys carry more than one value" % (n_multi, len(multi)))
        if n_multi > len(multi) / 2:
            print("   WARNING: most keys see several event variants -- the selector is")
            print("            probably matching several stages of one logical action.")
        seen = collections.Counter()
        for s in multi.values():
            for v in s:
                seen[v] += 1
        for v, c in seen.most_common(6):
            print("     %-28s on %d keys" % (v, c))


if __name__ == "__main__":
    main()
