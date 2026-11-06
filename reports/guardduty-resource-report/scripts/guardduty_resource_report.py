#!/usr/bin/env python3
"""AWS GuardDuty resource report: findings by severity, type, account, resource and day in one page.

Archive only. Reads the archived daily runs of the scheduled FPL report GuardDuty_Resource_Report (the
download_report_archive output for one Fluency / Ingext account), merges the archived days (new findings and updates add up; the snapshot is the latest day) and writes
facts.json, four CSVs, a Fluency-branded print HTML page and a self-contained interactive HTML file.
Standard library plus the fluency-report brand kit (charts and PDF). It never queries the tenant.

  guardduty_resource_report.py check  --archive FILE [FILE ...]
  guardduty_resource_report.py render --archive FILE [FILE ...] --work DIR --account NAME [--customer TEXT]
"""
import argparse, collections, csv, datetime as dt, html, json, os, shutil, sys
import os as _os, sys as _sys, glob as _glob
def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
    here = _os.path.dirname(_os.path.abspath(__file__)); home = _os.path.expanduser("~")
    cands = [_os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = _os.path.dirname(up); cands.append(_os.path.join(up, "fluency-report", "scripts"))
    cands += [_os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += _glob.glob(_os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and _os.path.exists(_os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")
_sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

REPORT = "GuardDuty_Resource_Report"
ACTIVE_HOURS = 168          # a finding updated within this many hours before the end of the window is "active"
MAX_AGE_DAYS = 3            # an archived day older than this is flagged as out of date
FINDINGS_CAP = 200          # the archive lists at most this many findings
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
TABLES = ["gdres_summary", "gdres_findings", "gdres_types", "gdres_accounts", "gdres_resources", "gdres_daily", "gdres_created", "gdres_repeat", "gdres_snapshot"]
BANDS = ["High", "Medium", "Low"]
BAND_COLOR = {"High": "#b3242e", "Medium": "#a06c00", "Low": "#175d9a"}
STATUS_COLOR = {"Needs action": "#b3242e", "Watch": "#a06c00", "Low priority": "#8a8a8a", "Archived": "#175d9a"}


# ---------------------------------------------------------------- loading
SUMMARY = "gdres_summary"

def _tables_of(res):
    tables = {}
    for o in res.get("objects") or []:
        tb = o.get("table") or {}
        tables[o.get("name")] = tb.get("rows") or []
    return tables


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int(v):
    n = _num(v)
    return int(n) if n == int(n) else n


def _covered(summ, rng):
    """(asOf, days covered, window): a run with windowDays N covers the N UTC days ending the day before asOf."""
    as_of = str(summ.get("asOf") or rng)[:10]
    try:
        end = dt.date.fromisoformat(as_of)
    except ValueError:
        return as_of, [], 1
    w = max(1, int(_num(summ.get("windowDays")) or 1))
    return as_of, [(end - dt.timedelta(days=i + 1)).isoformat() for i in range(w)], w


def _sum_by(runs, name, keys, sums=(), maxes=(), mins=(), pick=None, limit=None, order=None):
    """Merge one table across runs. Rows with the same key are combined: `sums` add, `maxes` and `mins` keep the largest and smallest,
    every other column comes from the row of the latest run (or from the row with the largest `pick` column)."""
    out = {}
    for r in runs:                                          # runs are in date order, so later rows overwrite plain columns
        for row in r["tables"].get(name, []):
            k = tuple(str(row.get(c) or "") for c in keys)
            cur = out.get(k)
            if cur is None:
                cur = dict(row)
                for c in sums:
                    cur[c] = _int(row.get(c))
                out[k] = cur
                continue
            for c in sums:
                cur[c] = _int(cur.get(c)) + _int(row.get(c))
            for c in maxes:
                if _num(row.get(c)) > _num(cur.get(c)) or (str(row.get(c) or "") > str(cur.get(c) or "") and not _num(row.get(c))):
                    cur[c] = row.get(c)
            for c in mins:
                if row.get(c) and (not cur.get(c) or str(row.get(c)) < str(cur.get(c))):
                    cur[c] = row.get(c)
            if pick is None or _num(row.get(pick)) >= _num(cur.get(pick)):
                for c, v in row.items():
                    if c not in sums and c not in maxes and c not in mins and c not in keys:
                        cur[c] = v
    rows = list(out.values())
    if order:
        rows.sort(key=order)
    return rows[:limit] if limit else rows


def _plan(paths):
    """Read the archive file(s) into runs sorted by date and decide which ones are merged.
    Returns (kept_runs, latest_run, info) or None. Daily runs (windowDays 1) are merged; if there are none, the latest run alone is used."""
    if isinstance(paths, str):
        paths = [paths]
    cands = []
    for path in paths or []:
        if not path or not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("days"), list):
            for d in data["days"]:
                res = d.get("result")
                ent = d.get("entry") or {}
                if res and (ent.get("state") in (None, "completed", "Completed", "complete", "done")):
                    cands.append((str(ent.get("rangeTo") or ""), str(ent.get("completedOn") or ""), res))
        elif isinstance(data, dict):
            cands.append(("", "", data.get("result") or data))
    runs = []
    for rng, done, res in cands:
        tb = _tables_of(res)
        if tb.get(SUMMARY):
            as_of, cov, w = _covered(tb[SUMMARY][0], rng)
            runs.append({"rng": rng, "done": done, "tables": tb, "asOf": as_of, "cov": cov, "w": w})
    if not runs:
        return None
    runs.sort(key=lambda r: (r["asOf"], r["rng"], r["done"]))
    latest = runs[-1]
    daily = [r for r in runs if r["w"] == 1]
    legacy = len(runs) - len(daily)
    if not daily:                                    # only 30-day snapshots: the old behaviour, latest day alone
        return [latest], latest, {"legacy": True, "legacyIgnored": 0, "overlap": False, "covered": latest["cov"], "gaps": [], "expected": 1,
                                  "days": len(runs), "firstDay": runs[0]["rng"], "lastDay": runs[-1]["rng"]}
    by_day = {}
    for r in daily:                                  # the same day archived twice: the latest run wins
        by_day[r["asOf"]] = r
    kept = [by_day[k] for k in sorted(by_day)]
    covered = sorted(d for r in kept for d in r["cov"])
    first, last = covered[0], covered[-1]
    expected = (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1
    d0 = dt.date.fromisoformat(first)
    have = set(covered)
    gaps = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(expected) if (d0 + dt.timedelta(days=i)).isoformat() not in have]
    return kept, kept[-1], {"legacy": False, "legacyIgnored": legacy, "overlap": len(daily) != len(kept), "covered": covered, "gaps": gaps,
                            "expected": expected, "days": len(covered), "firstDay": first, "lastDay": last}


def _band(m):
    m = _num(m)
    return "High" if m >= 7 else ("Medium" if m >= 4 else "Low")


def _period_notes(arc):
    """Notes on the archived period: gaps, runs left out, a day archived twice, or a legacy 30-day archive."""
    n = []
    if arc.get("legacy"):
        n.append("This archive holds only 30-day runs from before the daily schedule, so the latest day is used and days are not added together. "
                 "The alert and finding counts cover the 30 days before that run.")
        return n
    gaps = arc.get("gaps") or []
    if gaps:
        n.append("No archived run covers %d day%s in this period (%s%s). Those days are missing from the counts; they are not zero."
                 % (len(gaps), "" if len(gaps) == 1 else "s", ", ".join(gaps[:6]), ", ..." if len(gaps) > 6 else ""))
    if arc.get("legacyIgnored"):
        n.append("%d earlier 30-day run%s from before the daily schedule %s left out, because their windows overlap each other."
                 % (arc["legacyIgnored"], "" if arc["legacyIgnored"] == 1 else "s", "was" if arc["legacyIgnored"] == 1 else "were"))
    if arc.get("overlap"):
        n.append("A day archived more than once is counted once, using its latest run.")
    return n


def load_archive(paths):
    """Read download_report_archive output (one or more files). Returns
    {"asOf", "days", "firstDay", "lastDay", "expected", "gaps", "legacy", "tables": {name: [row dicts]}} or None.
    The finding snapshot (gdres_snapshot) is the resource table on the latest completed day. The finding tables are merged across every
    archived day: a finding is counted on the day it was created (gdres_findings, gdres_types, gdres_accounts, gdres_resources,
    gdres_repeat, gdres_created and the new* counts), updates add up, one row per day is kept once (the latest run wins), and the
    distinct counts (accounts, regions, resource types) are taken from the merged tables."""
    plan = _plan(paths)
    if not plan:
        return None
    kept, latest, info = plan
    tables = dict(latest["tables"])
    if not info["legacy"]:
        for name in ("gdres_daily", "gdres_created"):
            byday = {}
            for r in kept:
                for row in r["tables"].get(name, []):
                    byday[str(row.get("day") or "")[:10]] = row
            tables[name] = [byday[k] for k in sorted(byday) if k]
        seen, finds = set(), []
        for r in reversed(kept):
            for row in r["tables"].get("gdres_findings", []):
                if row.get("id") not in seen:
                    seen.add(row.get("id"))
                    finds.append(row)
        finds.sort(key=lambda x: (-_num(x.get("severity")), str(x.get("lastUpdate") or "")), reverse=False)
        tables["gdres_findings"] = finds[:200]
        tables["gdres_types"] = _sum_by(kept, "gdres_types", ["type"], sums=["findings", "updates"], maxes=["maxSeverity", "resources", "accounts", "lastUpdate"], mins=["firstUpdate"],
                                        order=lambda x: (-_num(x.get("maxSeverity")), -_num(x.get("findings"))), limit=100)
        for row in tables["gdres_types"]:
            row["band"] = _band(row.get("maxSeverity"))
        tables["gdres_accounts"] = _sum_by(kept, "gdres_accounts", ["account", "region"], sums=["findings", "high", "medium", "low", "updates"], maxes=["resources", "lastUpdate"],
                                           order=lambda x: (-_num(x.get("high")), -_num(x.get("findings"))), limit=100)
        tables["gdres_resources"] = _sum_by(kept, "gdres_resources", ["resourceType", "resource"], sums=["findings", "updates"], maxes=["maxSeverity", "types", "lastUpdate"], mins=["firstUpdate"],
                                            order=lambda x: (-_num(x.get("maxSeverity")), -_num(x.get("findings")), -_num(x.get("updates"))), limit=100)
        for row in tables["gdres_resources"]:
            row["band"] = _band(row.get("maxSeverity"))
        have = {}
        for r in kept:
            for row in r["tables"].get("gdres_repeat", []):
                have[row.get("id")] = row
        tables["gdres_repeat"] = sorted(have.values(), key=lambda x: -_num(x.get("updates")))[:25]
        summ = dict(latest["tables"][SUMMARY][0])
        runs = [r["tables"][SUMMARY][0] for r in kept]
        for c in ("events", "newFindings", "newHigh", "newMedium", "newLow"):
            summ[c] = sum(_int(s.get(c)) for s in runs)
        # the headline counts are the findings raised in the period, the same basis as the merged tables
        summ["findings"], summ["high"], summ["medium"], summ["low"] = summ["newFindings"], summ["newHigh"], summ["newMedium"], summ["newLow"]
        summ["repeat10"] = max([_int(s.get("repeat10")) for s in runs] or [0])
        summ["active24h"] = _int(runs[-1].get("active24h"))           # findings updated on the latest day
        summ["active7d"] = max([_int(s.get("findings")) for s in runs[-7:]] or [0])      # at least: the busiest of the last 7 days
        summ["accounts"] = len({row.get("account") for row in tables["gdres_accounts"]})
        summ["regions"] = len({row.get("region") for row in tables["gdres_accounts"]})
        summ["resourceTypes"] = len({row.get("resourceType") for row in tables["gdres_resources"]})
        summ["resources"] = len(tables["gdres_resources"])
        fu = [str(s.get("firstUpdate")) for s in runs if s.get("firstUpdate")]
        lu = [str(s.get("lastUpdate")) for s in runs if s.get("lastUpdate")]
        summ["firstUpdate"], summ["lastUpdate"] = (min(fu) if fu else ""), (max(lu) if lu else "")
        summ["windowDays"] = info["days"]
        tables[SUMMARY] = [summ]

    return {"asOf": str(latest["tables"][SUMMARY][0].get("asOf") or latest["rng"])[:10], "days": info["days"], "firstDay": info["firstDay"], "lastDay": info["lastDay"],
            "expected": info["expected"], "gaps": info["gaps"], "legacy": info["legacy"], "legacyIgnored": info["legacyIgnored"], "overlap": info["overlap"],
            "tables": tables}


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def n_of(r, k):
    try:
        return int(float(r.get(k) or 0))
    except (TypeError, ValueError):
        return 0


def f_of(r, k):
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def num(n):
    return "{:,}".format(int(n))


def sev(x):
    return ("%g" % x) if x == int(x) else ("%.1f" % x)


def day(s):
    s = str(s or "")
    return "" if s in ("", "null", "None") else s[:10]


def parse_ts(s):
    s = str(s or "")
    if s in ("", "null", "None"):
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def band_of(v):
    return "High" if v >= 7 else "Medium" if v >= 4 else "Low"


# ---------------------------------------------------------------- check
def sources_down(arc):
    rows = arc["tables"].get("sources", [])
    names = ("GuardDuty (findings)", "GuarddutyFinding (snapshot)")
    return all(r.get("status") != "ok" for r in rows if r.get("source") in names) and any(r.get("source") in names for r in rows)


def cmd_check(args):
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM  no completed day with a gdres_summary table in the archive file(s): the report cannot run")
        return 1
    now = dt.datetime.now(dt.timezone.utc)
    s = arc["tables"]["gdres_summary"][0]
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    level, note = "ok", ""
    if sources_down(arc):
        level, note = "PROBLEM", "both GuardDuty tables were not available on the latest day (no GuardDuty import on the tenant)"
    elif age > MAX_AGE_DAYS:
        level, note = "PROBLEM", "latest archived day is %d days old" % age
    elif not n_of(s, "findings") and not n_of(s, "snapshot"):
        note = "no findings in the window and none in the current snapshot"
    print("%-8s %-28s asOf=%s days_in_file=%d findings=%s high=%s snapshot=%s %s" % (level, REPORT, arc["asOf"], arc["days"], s.get("findings"), s.get("high"), s.get("snapshot"), note))
    for r in [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]:
        print("         query not available: %s %s" % (r.get("source"), str(r.get("detail") or "")[:100]))
    missing = [t for t in TABLES if t not in arc["tables"]]
    if missing:
        print("         tables absent (an older script version?): %s" % ", ".join(missing))
    return 1 if level == "PROBLEM" else 0


# ---------------------------------------------------------------- analysis
def score_finding(band, archived, last, as_of):
    """Attention score of one finding. Archived findings score 0. Otherwise severity band (High 3, Medium 2, Low 1) plus 1 when the
    finding was updated within the last 7 days of the window. 3 or more Needs action, 2 Watch, 1 Low priority."""
    if archived:
        return 0, "Archived", ["archived in GuardDuty"]
    base = {"High": 3, "Medium": 2}.get(band, 1)
    reasons = ["%s severity" % band.lower()]
    active = last is not None and (as_of - last).total_seconds() <= ACTIVE_HOURS * 3600
    if active:
        reasons.append("updated in the last 7 days")
    elif last is not None:
        reasons.append("last updated %d days before the end of the window" % max(0, (as_of - last).days))
    score = base + (1 if active else 0)
    return score, ("Needs action" if score >= 3 else "Watch" if score == 2 else "Low priority"), reasons


def analyse(arc, now):
    tb = arc["tables"]
    s = tb["gdres_summary"][0]
    as_of = dt.datetime.fromisoformat(arc["asOf"]).replace(tzinfo=dt.timezone.utc)
    window = n_of(s, "windowDays") or 30

    def finding(r, snap):
        v = f_of(r, "severity")
        last = parse_ts(r.get("lastUpdate"))
        arch = str(r.get("archived")).lower() == "true"
        b = band_of(v)
        sc, st, why = score_finding(b, arch, last, as_of)
        upd = n_of(r, "updates")
        if upd >= 10 and not arch:
            why.append("%d updates in the window" % upd)
        return {"id": r.get("id") or "", "type": r.get("type") or "", "category": r.get("category") or "", "severity": v, "band": b, "title": r.get("title") or "",
                "account": r.get("account") or "", "region": r.get("region") or "", "resourceType": r.get("resourceType") or "", "resource": r.get("resource") or "",
                "principal": r.get("principal") or "", "action": r.get("action") or "", "created": day(r.get("created")), "first": day(r.get("firstUpdate")),
                "last": day(r.get("lastUpdate")), "updates": upd, "eventCount": n_of(r, "eventCount"), "archived": "yes" if arch else "no",
                "inSnapshot": r.get("inSnapshot") or r.get("inWindow") or "", "score": sc, "state": st, "reasons": "; ".join(why)}

    finds = [finding(r, False) for r in tb.get("gdres_findings", [])]
    finds.sort(key=lambda x: (-x["score"], -x["severity"], "".join(chr(255 - ord(c)) for c in x["last"])))
    snap = []
    for r in tb.get("gdres_snapshot", []):
        x = finding(r, True)
        x["inWindow"] = r.get("inWindow") or ""
        snap.append(x)

    types = [{"type": r.get("type") or "", "category": r.get("category") or "", "severity": f_of(r, "maxSeverity"), "band": r.get("band") or band_of(f_of(r, "maxSeverity")),
              "findings": n_of(r, "findings"), "updates": n_of(r, "updates"), "resources": n_of(r, "resources"), "accounts": n_of(r, "accounts"),
              "first": day(r.get("firstUpdate")), "last": day(r.get("lastUpdate"))} for r in tb.get("gdres_types", [])]
    cats = collections.OrderedDict()
    for t in types:
        c = cats.setdefault(t["category"] or "(none)", {"category": t["category"] or "(none)", "types": 0, "findings": 0, "updates": 0, "severity": 0.0})
        c["types"] += 1; c["findings"] += t["findings"]; c["updates"] += t["updates"]; c["severity"] = max(c["severity"], t["severity"])
    categories = sorted(cats.values(), key=lambda c: (-c["severity"], -c["findings"]))
    for c in categories:
        c["band"] = band_of(c["severity"])
    accounts = [{"account": r.get("account") or "", "region": r.get("region") or "", "findings": n_of(r, "findings"), "high": n_of(r, "high"), "medium": n_of(r, "medium"),
                 "low": n_of(r, "low"), "updates": n_of(r, "updates"), "resources": n_of(r, "resources"), "last": day(r.get("lastUpdate"))} for r in tb.get("gdres_accounts", [])]
    resources = [{"resourceType": r.get("resourceType") or "", "resource": r.get("resource") or "", "findings": n_of(r, "findings"), "severity": f_of(r, "maxSeverity"),
                  "band": r.get("band") or band_of(f_of(r, "maxSeverity")), "types": n_of(r, "types"), "updates": n_of(r, "updates"), "first": day(r.get("firstUpdate")),
                  "last": day(r.get("lastUpdate")), "topType": r.get("topType") or ""} for r in tb.get("gdres_resources", [])]
    repeat = [{"id": r.get("id") or "", "type": r.get("type") or "", "severity": f_of(r, "severity"), "band": r.get("band") or "", "resource": r.get("resource") or "",
               "updates": n_of(r, "updates"), "eventCount": n_of(r, "eventCount"), "first": day(r.get("firstUpdate")), "last": day(r.get("lastUpdate"))} for r in tb.get("gdres_repeat", [])]

    # one row per day of the window, zero where nothing happened
    by_day = {day(r.get("day")): r for r in tb.get("gdres_daily", [])}
    created = {day(r.get("day")): r for r in tb.get("gdres_created", [])}
    daily = []
    start = (as_of - dt.timedelta(days=window)).date()
    for i in range(window):
        d = (start + dt.timedelta(days=i)).isoformat()
        r, c = by_day.get(d, {}), created.get(d, {})
        daily.append({"day": d, "events": n_of(r, "events"), "findings": n_of(r, "findings"), "high": n_of(r, "highFindings"), "medium": n_of(r, "mediumFindings"),
                      "low": n_of(r, "lowFindings"), "new": n_of(c, "newFindings"), "newHigh": n_of(c, "newHigh")})

    state = collections.Counter(x["state"] for x in finds)
    findings_n = n_of(s, "findings")
    summary = {k: n_of(s, k) for k in ["findings", "events", "high", "medium", "low", "archived", "active24h", "active7d", "newFindings", "repeat10", "accounts", "regions",
                                       "resourceTypes", "resources", "snapshot", "snapshotHigh", "snapshotMedium", "snapshotLow", "snapshotOnly"]}
    summary.update({"windowDays": window, "firstUpdate": day(s.get("firstUpdate")), "lastUpdate": day(s.get("lastUpdate"))})
    facts = {
        "account": "", "generated": now.isoformat(), "asOf": arc["asOf"], "archive": {"days": arc["days"], "firstDay": arc["firstDay"], "lastDay": arc["lastDay"]},
        "summary": summary,
        "status": {"needsAction": state["Needs action"], "watch": state["Watch"], "lowPriority": state["Low priority"], "archived": state["Archived"],
                   "listed": len(finds), "listedCap": FINDINGS_CAP, "truncated": len(finds) < findings_n},
        "categories": categories, "types": types, "accounts": accounts, "resources": resources, "daily": daily, "repeat": repeat,
    }
    return facts, finds, snap


# ---------------------------------------------------------------- narrative
def default_narrative(f):
    s, st = f["summary"], f["status"]
    if not s["findings"]:
        return ["<p>GuardDuty raised <strong>no findings</strong> in the %d days to %s. %s finding%s in the current snapshot.</p>" % (s["windowDays"], esc(f["asOf"]), num(s["snapshot"]), "" if s["snapshot"] == 1 else "s")]
    s1 = ("<p>In the %d days to %s GuardDuty raised <strong>%s new findings</strong> across %s account%s and %s region%s: <strong>%s high</strong>, %s medium and %s low severity. "
          "<strong>%s need action</strong> and %s are worth watching; %s were updated in the last 7 days (at least) and %s were updated 10 or more times.</p>"
          % (s["windowDays"], esc(f["asOf"]), num(s["findings"]), num(s["accounts"]), "" if s["accounts"] == 1 else "s", num(s["regions"]), "" if s["regions"] == 1 else "s",
             num(s["high"]), num(s["medium"]), num(s["low"]), num(st["needsAction"]), num(st["watch"]), num(s["active7d"]), num(s["repeat10"])))
    top = f["types"][0] if f["types"] else None
    big = max(f["types"], key=lambda t: t["findings"], default=None)
    s2 = ("<p>The findings touch <strong>%s resources</strong> of %s type%s. The most severe finding type is <strong>%s</strong> (severity %s)%s. "
          "GuardDuty re-sends a finding each time it sees more of the same activity, so <strong>%s findings were updated 10 or more times</strong> (%s updates in total).</p>"
          % (num(s["resources"]), num(s["resourceTypes"]), "" if s["resourceTypes"] == 1 else "s", esc(top["type"]) if top else "n/a", sev(top["severity"]) if top else "n/a",
             (", and the most common is %s with %s finding%s" % (esc(big["type"]), num(big["findings"]), "" if big["findings"] == 1 else "s")) if big and big is not top else "",
             num(s["repeat10"]), num(s["events"])))
    gone = max(0, s["findings"] - (s["snapshot"] - s["snapshotOnly"]))
    s3 = ("<p>GuardDuty's own list currently holds %s finding%s (%s high). %s finding%s from the window %s no longer in that list.</p>"
          % (num(s["snapshot"]), "" if s["snapshot"] == 1 else "s", num(s["snapshotHigh"]), num(gone), "" if gone == 1 else "s", "is" if gone == 1 else "are"))
    return [s1, s2, s3]


def default_steps(f):
    s, st = f["summary"], f["status"]
    out = []
    highs = [x for x in f["types"] if x["band"] == "High"]
    if s["high"]:
        out.append({"when": "This week", "tone": "urgent", "text": "Investigate the %d high severity finding%s (%s) in the GuardDuty console: confirm the activity was expected, then rotate any credentials or isolate any resource involved."
                    % (s["high"], "" if s["high"] == 1 else "s", ", ".join(t["type"] for t in highs[:3]))})
    med = [x for x in f["types"] if x["band"] == "Medium"]
    if s["medium"]:
        out.append({"when": "Within 14 days", "tone": "normal", "text": "Review the %d medium severity finding%s (%s)." % (s["medium"], "" if s["medium"] == 1 else "s", ", ".join(t["type"] for t in med[:3]))})
    rep = f["repeat"][0] if f["repeat"] else None
    if rep:
        out.append({"when": "Within 14 days", "tone": "normal", "text": "Findings such as %s on %s keep being updated (%d updates). Close the exposure behind them, for example by restricting the inbound rule that GuardDuty reports, so they stop recurring." % (rep["type"], rep["resource"] or "the same resource", rep["updates"])})
    if s["findings"]:
        out.append({"when": "Within 30 days", "tone": "normal", "text": "Archive findings that have been reviewed or are expected, so that GuardDuty's list shows what is still open."})
    out.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare the number of high and medium findings and recurring finding types with the previous quarter."})
    return out[:6]


# ---------------------------------------------------------------- html helpers
def panel(title, body, cols=6, sub="", cls=""):
    return ('<div class="panel col-%d %s"><div class="panel-header"><h3 class="panel-title">%s</h3>%s</div>%s</div>'
            % (cols, cls, esc(title), '<span class="panel-subtitle">%s</span>' % esc(sub) if sub else "", body))


def bars(items, total=None, color="var(--blue)", empty="No data."):
    """Horizontal bars (shared chart helper): name, count and share of the total."""
    items = [i for i in items if i["count"]]
    if not items:
        return '<p class="panel-subtitle">%s</p>' % esc(empty)
    col = fb.semantic_color(color)
    rows = []
    for i in items:
        name = str(i["name"])
        label = name if len(name) <= 44 else name[:41] + "..."
        rows.append((label, i["count"], col, fb._fmt(i["count"]) + ((" \u00b7 %s%%" % pct(i["count"], total)) if total else "")))
    return fb.bar_rows(rows)


def table(headers, rows, widths=None, cls="data"):
    cg = "<colgroup>%s</colgroup>" % "".join('<col style="width:%s">' % w for w in widths) if widths else ""
    th = "".join("<th>%s</th>" % esc(h) for h in headers)
    body = "".join("<tr%s>%s</tr>" % (' class="%s"' % r[1] if isinstance(r, tuple) and r[1] else "", "".join(r[0] if isinstance(r, tuple) else r)) for r in rows)
    return '<table class="%s">%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, cg, th, body)


def td(x, wrap=False):
    return '<td%s>%s</td>' % (' class="wrap"' if wrap else "", esc(x))


def tdn(x):
    return '<td class="num">%s</td>' % (num(x) if isinstance(x, int) else esc(x))


def chip(text, color):
    return '<span class="st"><i style="background:%s"></i>%s</span>' % (color, esc(text))


def kpi(label, value, color, note=""):
    return ('<div class="kpi"><div class="kpi-value %s">%s</div><div class="kpi-label">%s</div>%s</div>'
            % (color, esc(value), esc(label), '<div class="kpi-note">%s</div>' % esc(note) if note else ""))


def daily_chart(daily):
    """Findings updated per day, stacked by severity band (shared chart helper)."""
    return fb.column_chart([d["day"][5:] for d in daily],
                           [(b, [d[b.lower()] for d in daily]) for b in ("Low", "Medium", "High")],
                           mode="stack", colors=[BAND_COLOR["Low"], BAND_COLOR["Medium"], BAND_COLOR["High"]], height=200, y_label="Findings updated per day")


# ---------------------------------------------------------------- render
def coverage_notes(arc, f, now):
    notes = []
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    notes.append("Built from the archived %s: %d archived day%s from %s to %s. A finding is counted on the day it was created, so the findings, types, accounts and resources add up across the days; "
                 "updates are added up too. The list of current findings is the resource table on %s (the latest day). The finding types, severities and counts are as they stood on the day each finding was created."
                 % (REPORT, arc["days"], "" if arc["days"] == 1 else "s", arc["firstDay"] or "?", arc["lastDay"] or "?", arc["asOf"]))
    notes.extend(_period_notes(arc))
    if age > MAX_AGE_DAYS:
        notes.append("The latest archived day is %d days old, so these figures are not current. Check the scheduled report." % age)
    st, s = f["status"], f["summary"]
    if st["truncated"]:
        notes.append("The archive lists the first %d of %d findings (highest severity first), so the findings table and findings.csv are cut. The counts above cover every finding in the window." % (st["listed"], s["findings"]))
    if s["snapshotOnly"]:
        notes.append("%d finding%s in GuardDuty's current list %s not updated in the window and %s not in the findings table." % (s["snapshotOnly"], "" if s["snapshotOnly"] == 1 else "s", "was" if s["snapshotOnly"] == 1 else "were", "is" if s["snapshotOnly"] == 1 else "are"))
    notes.append("GuardDuty sends an update every time it counts more of the same activity, so one finding can appear many times. Findings are counted once, by id, at their latest update; \"updates\" is the number of times that finding was updated in the window.")
    notes.append("Findings older than the window that were not updated in it do not appear, even if they are still open in GuardDuty.")
    bad = [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]
    if bad:
        notes.append("These queries did not run on the archived day and their panels are empty: %s." % ", ".join(str(r.get("source")) for r in bad))
    notes.append("Not in the archive, so not shown: IP addresses and the raw activity behind each finding.")
    return notes


def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM: no completed archived day with a gdres_summary table; nothing to report", file=sys.stderr)
        return 1
    if sources_down(arc):
        print("PROBLEM: both GuardDuty tables were not available on the archived day; nothing to report", file=sys.stderr)
        return 1
    f, finds, snap = analyse(arc, now)
    f["account"] = args.account
    s, st = f["summary"], f["status"]
    notes = coverage_notes(arc, f, now)
    f["notes"] = notes
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}

    kp = [
        kpi("Findings raised", num(s["findings"]), "navy", "%s updates in %d days" % (num(s["events"]), s["windowDays"])),
        kpi("High severity", num(s["high"]), "red" if s["high"] else "green", "%s medium, %s low" % (num(s["medium"]), num(s["low"]))),
        kpi("Need action", num(st["needsAction"]), "red" if st["needsAction"] else "green", "%s more on watch" % num(st["watch"])),
        kpi("Active, last 7 days", num(s["active7d"]), "amber" if s["active7d"] else "green", "%s in the last 24 hours" % num(s["active24h"])),
        kpi("New in window", num(s["newFindings"]), "blue", "first raised in %d days" % s["windowDays"]),
        kpi("Resources affected", num(s["resources"]), "navy", "%s resource type%s" % (num(s["resourceTypes"]), "" if s["resourceTypes"] == 1 else "s")),
    ]

    g = []
    total = s["findings"] or 1
    bandrows = [{"name": b, "count": s[b.lower()], "color": BAND_COLOR[b]} for b in BANDS]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * x["count"] / total, x["color"], x["name"], x["count"]) for x in bandrows if x["count"])
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %s</span>' % (x["color"], x["name"], num(x["count"])) for x in bandrows)
    attn = [{"name": k, "count": v, "color": STATUS_COLOR[k]} for k, v in (("Needs action", st["needsAction"]), ("Watch", st["watch"]), ("Low priority", st["lowPriority"]), ("Archived", st["archived"]))]
    g.append(panel("Findings by severity", stack + legend + '<div style="height:8px"></div>' + bars(attn, s["findings"] or None), 6, "%s findings; attention rating below" % num(s["findings"])))
    cb = [{"name": c["category"], "count": c["findings"], "color": BAND_COLOR[c["band"]]} for c in f["categories"][:8]]
    g.append(panel("Findings by category", bars(cb, s["findings"] or None, empty="No findings."), 6, "colored by the most severe finding type in each category"))
    if any(d["findings"] for d in f["daily"]):
        lg = '<div class="legend">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s severity</span>' % (BAND_COLOR[b], b) for b in BANDS)
        g.append(panel("Findings updated per day", lg + daily_chart(f["daily"]), 12, "distinct findings updated per UTC day, %d days; hover a bar for the day" % s["windowDays"]))
    tr = [[td(t["type"], True), '<td>%s</td>' % chip("%s %s" % (t["band"], sev(t["severity"])), BAND_COLOR[t["band"]]), tdn(t["findings"]), tdn(t["updates"]), tdn(t["resources"]), td(t["last"])] for t in f["types"][:10]]
    g.append(panel("Finding types", table(["Type", "Severity", "Findings", "Updates", "Resources", "Last update"], tr, ["38%", "16%", "11%", "11%", "11%", "13%"]) if tr else '<p class="panel-subtitle">No findings.</p>', 12,
                   "%d type%s; top 10 by severity" % (len(f["types"]), "" if len(f["types"]) == 1 else "s")))
    ar = [[td(a["account"]), td(a["region"]), tdn(a["findings"]), tdn(a["high"]), tdn(a["medium"]), tdn(a["low"])] for a in f["accounts"][:8]]
    g.append(panel("Accounts and regions", table(["Account", "Region", "Findings", "High", "Medium", "Low"], ar, ["27%", "19%", "14%", "13%", "14%", "13%"]) if ar else '<p class="panel-subtitle">None.</p>', 6, "%s account%s, %s region%s" % (num(s["accounts"]), "" if s["accounts"] == 1 else "s", num(s["regions"]), "" if s["regions"] == 1 else "s")))
    rr = [[td(r["resourceType"]), td(r["resource"], True), tdn(r["findings"]), td(sev(r["severity"])), tdn(r["updates"])] for r in f["resources"][:8]]
    g.append(panel("Affected resources", table(["Type", "Resource", "Findings", "Severity", "Updates"], rr, ["18%", "36%", "14%", "16%", "16%"]) if rr else '<p class="panel-subtitle">None.</p>', 6, "top 8 by severity"))
    rp = [[td(r["type"], True), td(r["resource"], True), tdn(r["updates"]), tdn(r["eventCount"]), td(r["last"])] for r in f["repeat"][:8]]
    g.append(panel("Findings that keep recurring", table(["Type", "Resource", "Updates", "GuardDuty count", "Last update"], rp, ["34%", "24%", "12%", "16%", "14%"]) if rp else '<p class="panel-subtitle">No finding was updated 10 or more times.</p>', 12,
                   "updated 10 or more times in the window; GuardDuty count is how often it saw the activity"))
    new7 = sum(d["new"] for d in f["daily"][-7:])
    snaprows = [[td("Findings in GuardDuty's current list"), tdn(s["snapshot"])], [td("  of which high severity"), tdn(s["snapshotHigh"])],
                [td("Not updated in the window"), tdn(s["snapshotOnly"])], [td("Findings updated in the window"), tdn(s["findings"])], [td("First raised in the last 7 days"), tdn(new7)]]
    g.append(panel("Current list and window", table(["Measure", "Findings"], snaprows, ["76%", "24%"]), 12, "the current list is the GuardDuty resource table; the window is the update history"))

    cap = args.max_listed
    shown = [x for x in finds if x["state"] != "Low priority" and x["state"] != "Archived"] or finds
    rows = [([('<td class="wrap">%s</td>' % esc(x["title"])), td(x["type"], True), td(x["resource"], True), '<td>%s</td>' % chip(x["state"], STATUS_COLOR.get(x["state"], "#8a8a8a")), td(x["last"]),
              tdn(x["updates"]), td(x["reasons"], True)], "") for x in shown[:cap]]
    note = "" if len(shown) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(shown))
    app = [panel("Findings needing attention", table(["Finding", "Type", "Resource", "Status", "Last update", "Updates", "Why"], rows, ["20%", "17%", "13%", "11%", "9%", "7%", "23%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No findings in the window.</p>', 12, "%d of %s%s" % (len(shown), num(st["needsAction"] + st["watch"]), note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Source.</b> The archived daily run of the scheduled report %s for %s. Each run covers one day. A finding is counted on the day it was created, and the days are added up; the current list is the resource table on the latest day. The period is %d archived day(s).</div>'
              '<div><b>Counting.</b> GuardDuty re-sends a finding each time it sees more of the same activity. A finding is counted once, by its id, at its latest update. Updates is the number of times it was sent in the window.</div>'
              '<div><b>Severity.</b> GuardDuty severity: 7 or more High, 4 up to 7 Medium, below 4 Low.</div>'
              '<div><b>Attention rating.</b> A finding scores High 3, Medium 2, Low 1, plus 1 when it was updated in the last 7 days of the window. Archived findings score 0. 3 or more is Needs action, 2 is Watch, 1 is Low priority.</div>'
              '<div><b>Resource.</b> The instance, the EKS cluster, the S3 bucket or the access key owner the finding is about.</div>'
              '<div><b>GuardDuty count.</b> How many times GuardDuty saw the activity behind the finding; it is not the number of updates in the window.</div></div>'
              % (REPORT, esc(f["asOf"]), s["windowDays"]))
    app.append(panel("How to read this report", method, 12))
    app.append(panel("Data notes", '<div class="method">%s</div>' % "".join("<div>%s</div>" % esc(x) for x in notes), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(x.get("tone"), "var(--navy)"), i + 1, esc(x.get("when", "")), esc(x.get("text", ""))) for i, x in enumerate(steps))

    subtitle = args.customer or args.account
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "AWS GuardDuty Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong> · as of <strong>%s</strong>" % (esc(args.account), esc(f["asOf"])),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "GuardDuty resource report · %s" % esc(subtitle), "footer_data_date": esc(f["asOf"]),
    }
    for k, val in page.items():
        tpl = tpl.replace("{{%s}}" % k, val)
    with open(os.path.join(args.work, "guardduty_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    def out_csv(name, header, rows_):
        with open(os.path.join(args.work, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header + ["as_of"])
            for r in rows_:
                w.writerow(list(r) + [f["asOf"]])

    out_csv("findings.csv", ["finding_id", "type", "category", "severity", "band", "title", "account", "region", "resource_type", "resource", "principal", "action", "created", "first_update",
                             "last_update", "updates_in_window", "guardduty_count", "archived", "in_current_list", "score", "state", "reasons"],
            [[x["id"], x["type"], x["category"], sev(x["severity"]), x["band"], x["title"], x["account"], x["region"], x["resourceType"], x["resource"], x["principal"], x["action"],
              x["created"], x["first"], x["last"], x["updates"], x["eventCount"], x["archived"], x["inSnapshot"], x["score"], x["state"], x["reasons"]] for x in finds])
    out_csv("types.csv", ["type", "category", "max_severity", "band", "findings", "updates", "resources", "accounts", "first_update", "last_update"],
            [[t["type"], t["category"], sev(t["severity"]), t["band"], t["findings"], t["updates"], t["resources"], t["accounts"], t["first"], t["last"]] for t in f["types"]])
    out_csv("resources.csv", ["resource_type", "resource", "findings", "max_severity", "band", "types", "updates", "first_update", "last_update", "top_type"],
            [[r["resourceType"], r["resource"], r["findings"], sev(r["severity"]), r["band"], r["types"], r["updates"], r["first"], r["last"], r["topType"]] for r in f["resources"]])
    out_csv("daily.csv", ["day", "updates", "findings", "high", "medium", "low", "new_findings", "new_high"],
            [[d["day"], d["events"], d["findings"], d["high"], d["medium"], d["low"], d["new"], d["newHigh"]] for d in f["daily"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "guardduty_resource_report_interactive.html"), args, f, finds, snap, arc, notes)

    print("as of %s | findings %s (high %d, medium %d, low %d), updates %s, resources %s" % (f["asOf"], num(s["findings"]), s["high"], s["medium"], s["low"], num(s["events"]), num(s["resources"])))
    print("needs action %d, watch %d, low priority %d, archived %d (findings table lists %d)" % (st["needsAction"], st["watch"], st["lowPriority"], st["archived"], st["listed"]))
    print("active last 7 days %d, last 24 hours %d | new in window %d | updated 10+ times %d | current list %d (not updated in window %d)" % (s["active7d"], s["active24h"], s["newFindings"], s["repeat10"], s["snapshot"], s["snapshotOnly"]))
    print("wrote: guardduty_resource_report.html, guardduty_resource_report_interactive.html, findings.csv, types.csv, resources.csv, daily.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, finds, snap, arc, notes):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    def row(x):
        return {"id": x["id"], "type": x["type"], "category": x["category"], "severity": x["severity"], "band": x["band"], "title": x["title"], "account": x["account"],
                "region": x["region"], "resourceType": x["resourceType"], "resource": x["resource"], "principal": x["principal"], "created": x["created"], "first": x["first"],
                "last": x["last"], "updates": x["updates"], "eventCount": x["eventCount"], "archived": x["archived"], "inSnapshot": x["inSnapshot"], "score": x["score"],
                "state": x["state"], "reasons": x["reasons"]}
    srcs = [{"source": r.get("source"), "status": r.get("status"), "detail": str(r.get("detail") or "")[:160]} for r in arc["tables"].get("sources", [])]
    method = [
        "Source: the archived daily run of the scheduled report %s; findings are counted on the day they were created and added across the archived days; the current list is the latest day (%s)." % (REPORT, f["asOf"]),
        "GuardDuty re-sends a finding each time it sees more of the same activity. A finding is counted once, by its id, at its latest update. Updates is the number of times it was sent in the window (%d days)." % f["summary"]["windowDays"],
        "Severity: 7 or more High, 4 up to 7 Medium, below 4 Low.",
        "Attention rating: High 3, Medium 2, Low 1, plus 1 when the finding was updated in the last 7 days of the window; archived findings score 0. 3 or more Needs action, 2 Watch, 1 Low priority.",
        "Resource: the instance, EKS cluster, S3 bucket or access key owner the finding is about.",
        "GuardDuty count is how many times GuardDuty saw the activity; it is not the number of updates in the window.",
        "Current list: the GuardDuty resource table as at the run. Findings that were not updated in the window appear there only.",
    ]
    data = {"title": "AWS GuardDuty Resource Report", "account": args.account, "customer": args.customer, "snapshot": f["asOf"], "summary": f["summary"], "status": f["status"],
            "categories": f["categories"], "types": f["types"], "accounts": f["accounts"], "resources": f["resources"], "daily": f["daily"], "repeat": f["repeat"],
            "findings": [row(x) for x in finds], "current": [dict(row(x), inWindow=x.get("inWindow", "")) for x in snap], "sources": srcs, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " GuardDuty Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r = sub.add_parser("render"); r.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--max-listed", type=int, default=20)
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
