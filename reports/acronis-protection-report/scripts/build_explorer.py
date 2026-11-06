#!/usr/bin/env python3
"""Interactive explorer for the Acronis Protection archive: one self-contained HTML page.

Reads the download_report_archive JSON files (--archive may repeat or use a glob) and embeds the per-day metrics and the
per-day keyed rows, so the page recomputes any date range in the browser. No search is run. A day without an archived
result is a gap, never zero. It has the same layout as the Microsoft 365 / Entra activity explorer: tabs, date presets and
pickers, KPI cards with the change against the preceding period, a drag-to-select daily chart, facet panels and tables.

  build_explorer.py --archive 'oct.json' --archive 'nov.json' --tenant acme --client "Acme Ltd" --out explorer.html

The page is a fragment (title, style, markup, script) like the Entra explorer, for publishing with the Artifact tool. Add
--standalone to wrap it in a full HTML document for opening the file directly in a browser.
Hosts and Acronis unit names are in the page; e-mail addresses in unit names are removed.
"""
import argparse, datetime, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE_TYPES = ("UpdateVapm", "UpdateAgent", "Download", "DownloadInstaller", "AutoUpdateStandby")


def unit(u):
    return re.sub(r"\s*\(.*\)\s*$", "", u or "") or "(none)"


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def parse_ts(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)


def load(paths):
    done, other = {}, {}
    files = []
    for p in paths:
        files.extend(sorted(glob.glob(p)) or [p])
    for p in files:
        try:
            doc = json.load(open(p))
        except (OSError, ValueError) as e:
            sys.exit("cannot read %s (%s). Save the download_report_archive result as JSON first." % (p, e))
        for dy in doc.get("days", []):
            en = dy.get("entry") or {}
            key = (en.get("rangeFrom") or "")[:10]
            res = dy.get("result")
            if not key:
                continue
            if en.get("state") != "completed" or not res:
                other.setdefault(key, en.get("state") or "no result")
                continue
            if key in done and (done[key]["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            tables = {o["name"]: (o.get("table") or {}).get("rows") or [] for o in res.get("objects", []) if o.get("name")}
            done[key] = {"entry": en, "T": tables}
    return done, other


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="append", required=True, help="download_report_archive JSON (repeatable, globs ok)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--client", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--standalone", action="store_true", help="wrap in a full HTML document (doctype, charset, viewport)")
    a = ap.parse_args()
    done, other = load(a.archive)
    if not done:
        sys.exit("no completed day in the archive files; check coverage with list_report_archive first (nothing was searched)")
    for k, v in sorted(done.items()):
        bad = [r["source"] for r in v["T"].get("sources", []) if r.get("status") != "ok"]
        if bad:
            sys.exit("archived day %s has source(s) not available (%s): backfill it with force=true or leave it out" % (k, bad))
    days = sorted(done)
    # every calendar day between the first and last archived day is shown; one that is not completed is a gap
    first, last = datetime.date.fromisoformat(days[0]), datetime.date.fromisoformat(days[-1])
    allday = [(first + datetime.timedelta(n)).isoformat() for n in range((last - first).days + 1)]

    out = {"tenant": a.tenant, "client": a.client, "days": allday, "other": other, "d": {}, "al": [], "ic": [], "tr": [], "uf": [], "bk": []}
    for dy in days:
        T = done[dy]["T"]
        tr = (T.get("acr_trend") or [{}])[0]
        acts = [r for r in T.get("acr_activities", []) if r.get("activityType") in UPDATE_TYPES]
        bk = T.get("acr_backup", [])
        out["d"][dy] = {
            "events": num(tr.get("events")), "alertEvents": num(tr.get("alertEvents")), "activityEvents": num(tr.get("activityEvents")),
            "incidentEvents": num(tr.get("incidentEvents")), "alertsActive": len(T.get("acr_alerts", [])),
            "edrTriggers": len(T.get("acr_edr_triggers", [])),
            "updRuns": sum(num(r.get("runs")) for r in acts), "updFail": sum(num(r.get("notOk")) for r in acts),
            "bkRuns": sum(num(r.get("runs")) for r in bk), "bkOk": sum(num(r.get("ok")) for r in bk),
            "bkFail": sum(num(r.get("failed")) for r in bk), "bkGb": round(sum(num(r.get("gbProcessed")) for r in bk), 1),
        }
        for r in T.get("acr_alerts", []):
            out["al"].append([dy, r.get("alertId"), r.get("alertType") or "", r.get("device") or "", (r.get("severity") or "").lower(),
                              num(r.get("events")), 1 if num(r.get("resolved")) else 0, r.get("domain") or r.get("process") or ""])
        for r in T.get("acr_incidents", []):
            out["ic"].append([dy, r.get("shortId"), r.get("host") or "", r.get("lastState") or "", r.get("lastMitigation") or "",
                              r.get("transferredTo") or "", num(r.get("events"))])
        for r in T.get("acr_edr_triggers", []):
            out["tr"].append([dy, r.get("incident"), r.get("device") or "", r.get("mitigation") or "", r.get("trigger") or "", r.get("detection") or ""])
        for r in T.get("acr_update_failures", []):
            out["uf"].append([dy, (r.get("agentId") or "")[:8], unit(r.get("unit")), r.get("activityType") or "", num(r.get("failed")), r.get("errorCode") or ""])
        for r in bk:
            try:
                errs = json.loads(r["errors"]) if isinstance(r.get("errors"), str) else (r.get("errors") or [])
            except ValueError:
                errs = []
            out["bk"].append([dy, r.get("device") or "", r.get("plan") or "", num(r.get("runs")), num(r.get("ok")), num(r.get("failed")),
                              num(r.get("gbProcessed")), errs])

    # Inventory: one snapshot, the latest day written by the schedule (within 8 hours of the day's end), else the latest day.
    def lag(k):
        en = done[k]["entry"]
        try:
            return (parse_ts(en["createdOn"]) - parse_ts(en["rangeTo"])).total_seconds() / 3600.0
        except (KeyError, ValueError):
            return 0.0

    sched = [k for k in days if lag(k) <= 8]
    sd = (sched or days)[-1]
    T = done[sd]["T"]
    if not T.get("acr_agent_summary"):
        sys.exit("snapshot day %s has no acr_agent_summary row" % sd)
    S = T["acr_agent_summary"][0]
    asof = parse_ts(S["asOf"])
    out["snap"] = {"day": sd, "backfilled": sd not in sched, "asOf": asof.strftime("%-d %b %Y") + " 00:00 UTC"}
    out["inv"] = {
        "summary": {k: S.get(k) for k in ("agents", "online", "offline", "onLatest", "behind", "latestInstaller", "defsStale", "defsStaleOnline",
                                           "noActiveProtection", "duplicateHosts", "units")},
        "defsAge": [[r["bucket"], num(r["agents"])] for r in T.get("acr_defs_age", [])],
        "versions": [[r["version"], num(r["agents"]), bool(r.get("isLatest"))] for r in sorted(T.get("acr_versions", []), key=lambda r: -num(r["agents"]))],
        "units": [[unit(r["unit"]), num(r["agents"]), num(r["online"]), num(r["stale"])] for r in sorted(T.get("acr_units", []), key=lambda r: -num(r["agents"]))],
        "stale": [[r["host"], unit(r["unit"]), bool(r["online"]), r["days"] if isinstance(r.get("days"), (int, float)) else 0, r.get("installer") or "", r.get("os") or ""]
                  for r in T.get("acr_stale_agents", [])],
        "noAp": [[r["host"], unit(r["unit"]), r.get("installer") or "", r.get("days") if isinstance(r.get("days"), (int, float)) else "no data"]
                 for r in T.get("acr_no_active_protection", [])],
        "dups": [[r["host"], num(r["records"]), " / ".join(unit(x) for x in re.split(r"(?<=\)) / ", r.get("units") or "")), r.get("states") or ""]
                 for r in T.get("acr_duplicates", [])],
    }

    tpl = open(os.path.join(HERE, "explorer_template.html"), encoding="utf-8").read()
    data = json.dumps(out, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("__DATA__", data)
    if a.standalone:
        html = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + html + "</body></html>"
    open(a.out, "w", encoding="utf-8").write(html)
    print("%s: %d archived days (%s to %s), %d not completed, %d KB%s" % (
        a.out, len(days), days[0], days[-1], len([d for d in allday if d not in done]), len(html) // 1024,
        ", snapshot is from a backfilled day" if out["snap"]["backfilled"] else ""))


if __name__ == "__main__":
    main()
