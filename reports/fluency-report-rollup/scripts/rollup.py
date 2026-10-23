#!/usr/bin/env python3
"""Assemble a week / month / quarter report from archived daily runs.

Input: one or more saved download_report_archive responses (JSON, either the
bare response or {"verdict","response"}). Output: one result in the same
objects[] shape a report run returns, plus the coverage it was built from.

    python3 rollup.py --spec spec.json --out month.json day1.json [day2.json ...]

The spec says, per output table, how dailies combine. See
references/merge_rules.md for every mode and how to choose one.
"""
import argparse, json, sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # python < 3.9
    ZoneInfo = None


def load_days(paths):
    days, coverage, meta = {}, [], {}
    for p in paths:
        with open(p) as f:
            doc = json.load(f)
        resp = doc.get("response", doc)
        meta.setdefault("name", resp.get("name"))
        meta.setdefault("timezone", resp.get("timezone"))
        if resp.get("coverage"):
            coverage.append(resp["coverage"])
        for d in resp.get("days") or []:
            entry = d.get("entry") or {}
            if entry.get("state") != "completed" or not d.get("result"):
                continue
            # A day downloaded twice (overlapping calls) counts once.
            days[entry["rangeFrom"]] = d
    return [days[k] for k in sorted(days)], coverage, meta


def tables(result):
    out = {}
    for o in result.get("objects") or []:
        if "table" in o:
            out[o["name"]] = o["table"].get("rows") or []
    return out


def parse_rfc3339(s):
    # strptime's %z only takes "-0400" before python 3.7; drop fractions too.
    s = s.replace("Z", "+00:00")
    body, sign, off = s[:19], s[-6], s[-6:]
    if sign not in "+-":
        raise ValueError(f"bad RFC 3339 time {s!r}")
    return datetime.strptime(body + off.replace(":", ""), "%Y-%m-%dT%H:%M:%S%z")


def num(v):
    return v if isinstance(v, (int, float)) else 0


def keyed(day_tables, t, spec):
    """sum / max / min / last over rows grouped by spec['key']."""
    mode = spec["mode"]
    key = spec["key"] if isinstance(spec["key"], list) else [spec["key"]]
    cols = spec.get("columns") or []
    acc = OrderedDict()
    for tb in day_tables:
        for r in tb.get(t, []):
            k = tuple(r.get(c) for c in key)
            row = acc.get(k)
            # "last" keeps the newest day's row (snapshot tables); the first
            # sighting of a key starts from its own row in every mode.
            if row is None or mode == "last":
                acc[k] = dict(r)
                continue
            for c in cols:
                v = r.get(c)
                if mode == "sum":
                    row[c] = num(row.get(c)) + num(v)
                elif mode == "max" and v is not None:
                    row[c] = v if row.get(c) is None else max(row[c], v)
                elif mode == "min" and v is not None:
                    row[c] = v if row.get(c) is None else min(row[c], v)
            # carry descriptive columns from the newest day
            for c, v in r.items():
                if c not in cols and c not in key:
                    row[c] = v
    return list(acc.values())


def timebucket(days, t, spec, loc):
    """Concatenate time-series rows, keep each bucket once, optionally roll up."""
    tcol = spec["time"]
    fmt = spec.get("format", "%Y/%m/%d %H:%M")
    step = parse_step(spec.get("step", "1h"))
    label_end = spec.get("label", "end") == "end"
    cols = spec.get("columns") or []
    rollup = spec.get("rollup")  # None, "1d", or "1mo"
    out = OrderedDict()
    dropped = 0
    for d in days:
        e = d["entry"]
        lo = parse_rfc3339(e["rangeFrom"]).astimezone(loc)
        hi = parse_rfc3339(e["rangeTo"]).astimezone(loc)
        for r in tables(d["result"]).get(t, []):
            ts = datetime.strptime(str(r.get(tcol)), fmt).replace(tzinfo=loc)
            start = ts - step if label_end else ts
            # Each daily run also returns the bucket that straddles its start
            # (the previous day's last bucket). Keep a bucket only in the run
            # whose day it starts in, or it is counted twice.
            if not (lo <= start < hi):
                dropped += 1
                continue
            if rollup == "1d":
                k = start.strftime("%Y-%m-%d")
            elif rollup == "1mo":
                k = start.strftime("%Y-%m")
            else:
                k = start.strftime(fmt)
            row = out.setdefault(k, {tcol: k})
            for c in cols:
                row[c] = num(row.get(c)) + num(r.get(c))
    return list(out.values()), dropped


def parse_step(s):
    n, unit = int(s[:-1]), s[-1]
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def top(built, spec):
    rows = list(built[spec["from"]])
    by = spec["by"]
    rows.sort(key=lambda r: num(r.get(by)), reverse=not spec.get("ascending", False))
    return rows[: spec.get("n", 10)]


def aggregate(built, spec):
    rows = built[spec["from"]]
    out = {}
    for name, how in spec["columns"].items():
        op = how[0]
        if op == "sum":
            out[name] = sum(num(r.get(how[1])) for r in rows)
        elif op == "count":
            out[name] = len(rows)
        elif op == "distinct":
            out[name] = len({r.get(how[1]) for r in rows})
        elif op == "max":
            out[name] = max((num(r.get(how[1])) for r in rows), default=0)
        elif op == "min":
            out[name] = min((num(r.get(how[1])) for r in rows), default=0)
        else:
            raise SystemExit(f"aggregate: unknown op {op!r} for {name}")
    return [out]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    with open(a.spec) as f:
        spec = json.load(f)
    days, coverage, meta = load_days(a.files)
    if not days:
        raise SystemExit("no completed days in the input")
    tzname = spec.get("labelTimezone") or meta.get("timezone") or "UTC"
    loc = timezone.utc if tzname == "UTC" or ZoneInfo is None else ZoneInfo(tzname)

    day_tables = [tables(d["result"]) for d in days]
    built, notes = OrderedDict(), []
    for t, s in spec["tables"].items():
        mode = s["mode"]
        if mode in ("sum", "max", "min", "last"):
            built[t] = keyed(day_tables, t, s)
        elif mode == "timebucket":
            built[t], dropped = timebucket(days, t, s, loc)
            notes.append(f"{t}: dropped {dropped} bucket(s) outside their own day")
        elif mode == "concat":
            built[t] = [r for tb in day_tables for r in tb.get(t, [])]
        elif mode == "top":
            built[t] = top(built, s)
        elif mode == "aggregate":
            built[t] = aggregate(built, s)
        elif mode == "drop":
            continue
        else:
            raise SystemExit(f"{t}: unknown mode {mode!r}")

    first, last = days[0]["entry"], days[-1]["entry"]
    result = {
        "name": meta.get("name"),
        "timezone": meta.get("timezone"),
        "from": first["rangeFrom"],
        "to": last["rangeTo"],
        "days": len(days),
        "scriptHashes": sorted({(d["entry"].get("env") or {}).get("scriptHash", "") for d in days} - {""}),
        "coverage": coverage,
        "notes": notes,
        "objects": [
            {"name": t, "table": {"rowCount": len(rows), "rows": rows}} for t, rows in built.items()
        ],
    }
    with open(a.out, "w") as f:
        json.dump(result, f, indent=1)
    print(f"{result['name']}: {len(days)} days {result['from']} .. {result['to']} -> {a.out}")
    for n in notes:
        print("  " + n)


if __name__ == "__main__":
    sys.exit(main())
