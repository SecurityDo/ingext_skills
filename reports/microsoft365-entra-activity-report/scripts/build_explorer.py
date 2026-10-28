#!/usr/bin/env python3
"""Interactive explorer for the Microsoft 365 and Entra Activity archive: one self-contained HTML page.

Reads the same download_report_archive JSON files as build_report.py (--archive may repeat or use a glob) and
embeds the per-day metrics and facets, so the page recomputes any date range in the browser. No search is run.
Counts only: no user names, no distinct-user figures. A day without an archived result is a gap, never zero.

  build_explorer.py --archive 'sep.json' --archive 'oct.json' --tenant audit --out explorer.html
"""
import argparse, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_report as b  # noqa: E402  (load() and SOURCES are shared with the report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="append", required=True, help="download_report_archive JSON (repeatable, globs ok)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    done, other = b.load(a.archive)
    if not done:
        sys.exit("no completed day in the archive files; check coverage with list_report_archive first (nothing was searched)")
    days = sorted(done)
    out = {"tenant": a.tenant, "days": days, "other": other, "sources": [], "d": {}, "f": {}, "have": {}}
    for s in b.SOURCES:
        k = s["key"]
        out["sources"].append({"key": k, "title": s["title"], "eyebrow": s["eyebrow"], "table": s["table"],
                               "metrics": [[m[0], m[1]] for m in s["metrics"]], "kpis": s["kpis"],
                               "facets": [[f[0], f[1], f[2], f[3]] for f in s["facets"]]})
        out["d"][k], out["f"][k] = {}, {f[0]: {} for f in s["facets"]}
        for dy in days:
            dd = done[dy]
            if dd["have"][k] != "ok":
                continue
            tot = collections.Counter()
            for r in dd["trend"].get(k, []):
                for m in s["metrics"]:
                    tot[m[0]] += int(r.get(m[0]) or 0)
            out["d"][k][dy] = dict(tot)
            for f in s["facets"]:
                c = dd["facets"].get(k, {}).get(f[0], {})
                if c:
                    out["f"][k][f[0]][dy] = c
    for dy in days:
        out["have"][dy] = {s["key"]: done[dy]["have"][s["key"]] for s in b.SOURCES}
    tpl = open(os.path.join(HERE, "explorer_template.html"), encoding="utf-8").read()
    data = json.dumps(out, separators=(",", ":")).replace("</", "<\\/")
    open(a.out, "w", encoding="utf-8").write(tpl.replace("__DATA__", data))
    print("%s: %d days (%s to %s), %d not completed" % (a.out, len(days), days[0], days[-1], len(other)))


if __name__ == "__main__":
    main()
