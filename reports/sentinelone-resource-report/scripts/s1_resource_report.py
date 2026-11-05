#!/usr/bin/env python3
"""SentinelOne resource report: agents, applications and threats in one page, from the archive.

Reads the archive of the scheduled report SentinelOne_Resource_Report (download_report_archive output)
for one Fluency / Ingext account, takes the latest completed day and writes facts.json, three CSVs,
a Fluency-branded HTML page and an interactive HTML file. Standard library plus the fluency-report brand kit (charts and PDF). It never searches
the tenant and never reads a resource dump.

  s1_resource_report.py check  --archive FILE [FILE ...]
  s1_resource_report.py render --archive FILE [FILE ...] --work DIR --account NAME [--customer TEXT]

Each archived day is a snapshot of the SentinelOne console (agents, applications, threats), so the
report uses the latest day and lists the other days as a change table. Days are never added together.
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

INACTIVE_STALE_DAYS = 7     # not reporting for longer than this is "stale"
TREND_WEEKS = 12
MAX_AGE_DAYS = 2            # an archive whose latest day ends more than this many days ago is stale
REPORT = "SentinelOne_Resource_Report"
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
NEEDED = ["s1res_summary", "s1res_endpoints"]
OPTIONAL = ["s1res_agent_versions", "s1res_apps_risk", "s1res_apps_top", "s1res_threats_class", "s1res_threats_daily", "s1res_threats_open"]


# ---------------------------------------------------------------- loading
def _num(v, default=0):
    try:
        if v is None or v == "" or str(v).lower() == "null":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def ts(value):
    """Parse an ISO-8601 timestamp (microseconds and Z allowed) to an aware datetime, or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def vkey(version):
    out = []
    for part in str(version or "").split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


def _days_in(path):
    """Yield (rangeTo, completedOn, result) for each completed day in one file: a download_report_archive
    result ({"days": [...]}), or a single run_report result ({"result": {...}} or the result itself)."""
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("days"), list):
        for d in data["days"]:
            res = d.get("result")
            ent = d.get("entry") or {}
            if res and ent.get("state") in (None, "completed", "Completed", "complete", "done"):
                yield str(ent.get("rangeTo") or ""), str(ent.get("completedOn") or ""), res
    elif isinstance(data, dict):
        res = data.get("result") if isinstance(data.get("result"), dict) else data
        if res.get("objects"):
            yield "", "", res


def load_archive(paths):
    """Return {"asOf", "days", "tables": {name: [row dicts]}, "history": [...]} for the latest completed day, or None."""
    cands = []
    for p in paths:
        cands.extend(_days_in(p))
    out = []
    for rng, done, res in cands:
        tables = {o.get("name"): (o.get("table") or {}).get("rows") or [] for o in res.get("objects") or []}
        if tables.get("s1res_summary"):
            s = tables["s1res_summary"][0]
            out.append({"asOf": str(s.get("asOf") or rng)[:10], "completed": done, "tables": tables, "summary": s})
    if not out:
        return None
    out.sort(key=lambda c: (c["asOf"], c["completed"]))
    seen = {}
    for c in out:                      # one entry per day: a later file replaces an earlier copy of the same day
        seen[c["asOf"]] = c
    days = [seen[k] for k in sorted(seen)]
    latest = days[-1]
    history = [{"asOf": d["asOf"], "endpoints": _num(d["summary"].get("endpoints")), "inactive": _num(d["summary"].get("inactive")),
                "needsAction": _num(d["summary"].get("needsAction")), "watch": _num(d["summary"].get("watch")),
                "openThreats": _num(d["summary"].get("openThreats")), "riskyEndpoints": _num(d["summary"].get("riskyEndpoints"))} for d in days]
    return {"asOf": latest["asOf"], "days": len(days), "tables": latest["tables"], "history": history}


def day(d):
    return d.strftime("%Y-%m-%d") if d else ""


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


# ---------------------------------------------------------------- check
def cmd_check(args):
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM   no completed day with s1res_summary in %s: the report cannot run" % ", ".join(args.archive))
        return 1
    problems = 0
    asof = dt.datetime.strptime(arc["asOf"], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - asof).days
    level, note = "ok", ""
    if age > MAX_AGE_DAYS:
        level, note, problems = "PROBLEM", "latest archived day is %d days old" % age, problems + 1
    print("%-8s archive: %d day(s), latest as of %s %s" % (level, arc["days"], arc["asOf"], note))
    for name in NEEDED + OPTIONAL:
        rows = arc["tables"].get(name, [])
        lvl = "ok"
        if not rows:
            lvl = "PROBLEM" if name in NEEDED else "warning"
            problems += lvl == "PROBLEM"
        print("%-8s %-22s rows=%d%s" % (lvl, name, len(rows), "" if rows else ("  (the report cannot run)" if name in NEEDED else "  (that panel will be left out or empty)")))
    bad = [s for s in arc["tables"].get("sources", []) if s.get("status") != "ok"]
    for s in bad:
        print("warning  source not available: %s %s" % (s.get("source"), s.get("detail", "")))
    s = arc["tables"]["s1res_summary"][0]
    print("endpoints %s, active %s, needs action %s, open threats %s" % (s.get("endpoints"), s.get("active"), s.get("needsAction"), s.get("openThreats")))
    return 1 if problems else 0


# ---------------------------------------------------------------- analysis
def top(counter, n=10):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def analyse(arc):
    T = arc["tables"]
    S = T["s1res_summary"][0]
    as_of = dt.datetime.strptime(arc["asOf"], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    vers = T.get("s1res_agent_versions", [])
    latest = next((v["agentVersion"] for v in vers if v.get("isNewest")), "") or max((v.get("agentVersion") or "" for v in vers), key=vkey, default="")

    open_rows = T.get("s1res_threats_open", [])
    open_by_name = collections.Counter(r.get("computerName") for r in open_rows)
    ep = []
    for r in T["s1res_endpoints"]:
        days = _num(r.get("daysSinceActive"), None)
        active = bool(r.get("isActive"))
        v = r.get("agentVersion") or ""
        ep.append({
            "computerName": r.get("computerName") or "", "machineType": r.get("machineType") or "", "os": r.get("osName") or "",
            "group": r.get("groupName") or "", "agentVersion": v, "behindLatest": bool(v) and bool(latest) and vkey(v) < vkey(latest),
            "active": active, "lastActiveDays": days if not active else None, "mitigationMode": r.get("mitigationMode") or "",
            "appsVuln": r.get("appsVulnerabilityStatus") or "", "activeThreats": _num(r.get("activeThreats")),
            "apps": 0, "highRiskApps": _num(r.get("riskyApps")),
            "openThreats": _num(r.get("openThreats"), open_by_name.get(r.get("computerName"), 0)),
            "score": _num(r.get("score")), "status": r.get("status") or "Healthy", "reasons": r.get("reasons") or ""})
    n = _num(S.get("endpoints"), len(ep))
    active = _num(S.get("active"))
    inactive = _num(S.get("inactive"), n - active)
    buckets = collections.Counter()
    for e in ep:
        if e["active"]:
            continue
        d = e["lastActiveDays"]
        buckets["< 1 day" if d is not None and d < 1 else "1-7 days" if d is not None and d <= 7 else "8-30 days" if d is not None and d <= 30
                else "> 30 days" if d is not None else "unknown"] += 1
    seen = collections.Counter((e["computerName"] or "").lower() for e in ep)
    dup_names = sorted({e["computerName"] for e in ep if e["computerName"] and seen[e["computerName"].lower()] > 1})

    # applications
    risk_rows = T.get("s1res_apps_risk", [])
    risk = {(r.get("riskLevel") or "none").lower(): _num(r.get("installs")) for r in risk_rows}
    app_rows = []
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for r in T.get("s1res_apps_top", []):
        app_rows.append({"name": r.get("name") or "(unnamed)", "publisher": r.get("publisher") or "", "risk": (r.get("riskLevel") or "none").lower(), "endpoints": _num(r.get("endpoints"))})
    app_rows.sort(key=lambda r: (-r["endpoints"], r["name"].lower()))

    # threats
    classification = collections.Counter(); mitig = collections.Counter(); incident = collections.Counter()
    for r in T.get("s1res_threats_class", []):
        c = _num(r.get("threats"))
        classification[r.get("classification") or "Unclassified"] += c
        mitig[r.get("mitigationStatus") or "unknown"] += c
        incident[r.get("incidentStatus") or "unknown"] += c
    weekly = collections.Counter(); first = last = None
    for r in T.get("s1res_threats_daily", []):
        d = ts(str(r.get("day") or ""))
        if not d:
            continue
        first = d if not first or d < first else first
        last = d if not last or d > last else last
        weekly[(d - dt.timedelta(days=d.weekday())).date()] += _num(r.get("threats"))
    weeks = []
    if weekly:
        n_weeks = min(TREND_WEEKS, max(6, (max(weekly) - min(weekly)).days // 7 + 1))
        start = max(weekly) - dt.timedelta(weeks=n_weeks - 1)
        weeks = [{"week": (start + dt.timedelta(weeks=i)).isoformat(), "count": weekly.get(start + dt.timedelta(weeks=i), 0)} for i in range(n_weeks)]
    open_threats = [{"created": ts(r.get("createdAt")), "endpoint": r.get("computerName") or "", "threat": r.get("threatName") or "",
                     "classification": r.get("classification") or "Unclassified", "confidence": (r.get("confidence") or "unknown").title(),
                     "verdict": r.get("verdict") or "", "mitigation": r.get("mitigationStatus") or "unknown", "incident": r.get("incidentStatus") or "unknown"}
                    for r in open_rows]

    inst = _num(S.get("installs"), sum(risk.values()))
    facts = {
        "account": "", "asOf": arc["asOf"], "archiveDays": arc["days"], "latestVersion": latest,
        "present": {"agent": bool(ep), "application": inst > 0 or bool(app_rows), "threat": _num(S.get("threats")) > 0 or bool(classification)},
        "agents": {
            "records": n + _num(S.get("decommissioned")) + _num(S.get("uninstalled")), "inScope": n,
            "decommissioned": _num(S.get("decommissioned")), "uninstalled": _num(S.get("uninstalled")),
            "active": active, "inactive": inactive, "inactiveStale": _num(S.get("notReporting7d")),
            "inactiveBuckets": dict(buckets),
            "onLatest": n - _num(S.get("behindNewest")), "behindLatest": _num(S.get("behindNewest")),
            "versions": [{"name": v.get("agentVersion") or "unknown", "count": _num(v.get("endpoints"))} for v in vers][:12],
            "machineTypes": top(collections.Counter(e["machineType"] or "unknown" for e in ep)),
            "os": top(collections.Counter(e["os"] or "unknown" for e in ep), 10),
            "groups": top(collections.Counter(e["group"] or "unknown" for e in ep), 10),
            "mitigationModes": top(collections.Counter(e["mitigationMode"] or "unknown" for e in ep)),
            "notProtect": _num(S.get("notProtect")), "patchRequired": _num(S.get("patchRequired")),
            "infected": _num(S.get("infected")), "withActiveThreats": sum(1 for e in ep if e["activeThreats"]),
            "duplicateNames": dup_names,
        },
        "applications": {
            "instances": inst, "distinct": _num(S.get("distinctApps")), "risk": risk,
            "highRiskInstances": _num(S.get("riskyInstalls")), "highRiskEndpoints": _num(S.get("riskyEndpoints")),
            "newInWindow": sum(_num(r.get("newApps")) for r in risk_rows), "newWindowDays": 30,
            "topApps": [{"name": r["name"], "publisher": r["publisher"], "risk": r["risk"], "endpoints": r["endpoints"]} for r in app_rows[:8]],
        },
        "threats": {
            "total": _num(S.get("threats")), "first": day(first), "last": day(last), "open": _num(S.get("openThreats")),
            "classification": top(classification), "mitigation": dict(mitig), "incident": dict(incident), "weekly": weeks,
            "openListed": len(open_threats),
        },
        "endpoints": {"needsAction": _num(S.get("needsAction")), "watch": _num(S.get("watch")), "healthy": _num(S.get("healthy"))},
        "history": arc["history"],
        "sources": arc["tables"].get("sources", []),
    }
    return facts, ep, app_rows, open_threats


# ---------------------------------------------------------------- narrative
def default_narrative(f):
    a, p, t, e = f["agents"], f["applications"], f["threats"], f["endpoints"]
    s1 = ("<p>SentinelOne manages <strong>%d endpoints</strong>, of which <strong>%d (%s%%) are reporting</strong> and "
          "<strong>%d are not</strong>. <strong>%d endpoints (%s%%) run the newest agent build in the fleet</strong> (%s); "
          "%d are behind. <strong>%d endpoints need action</strong> and %d more are worth watching.</p>"
          % (a["inScope"], a["active"], pct(a["active"], a["inScope"]), a["inactive"], a["onLatest"],
             pct(a["onLatest"], a["inScope"]), esc(f["latestVersion"]), a["behindLatest"], e["needsAction"], e["watch"]))
    parts = []
    if f["present"]["threat"]:
        parts.append("<strong>%d threats</strong> have been recorded%s; <strong>%d are still open</strong> "
                     "(not mitigated or not resolved)." % (t["total"], " between %s and %s" % (esc(t["first"]), esc(t["last"])) if t["first"] else "", t["open"]))
    if f["present"]["application"]:
        parts.append("The inventory lists <strong>%d application installs</strong> across <strong>%d distinct applications</strong>; "
                     "<strong>%d installs on %d endpoints</strong> are rated medium or high risk, and <strong>%d endpoints</strong> "
                     "report applications that need patching." % (p["instances"], p["distinct"], p["highRiskInstances"], p["highRiskEndpoints"], a["patchRequired"]))
    return [s1] + (["<p>" + " ".join(parts) + "</p>"] if parts else [])


def default_steps(f):
    a, p, t = f["agents"], f["applications"], f["threats"]
    s = []
    if t["open"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Review the %d open threats and confirm each is mitigated and resolved in the SentinelOne console." % t["open"]})
    if a["infected"] or a["withActiveThreats"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Isolate and clean the %d endpoints reporting an infection or active threats." % max(a["infected"], a["withActiveThreats"])})
    if a["inactive"]:
        stale = a["inactiveStale"]
        s.append({"when": "This week" if stale else "Within 14 days", "tone": "urgent" if stale else "normal",
                  "text": "Find out why %d endpoints are not reporting%s: powered off, retired, or the agent is damaged." % (a["inactive"], " (%d for over %d days)" % (stale, INACTIVE_STALE_DAYS) if stale else "")})
    if a["notProtect"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Move the %d endpoints that are not in protect mode back to protect." % a["notProtect"]})
    if p["highRiskInstances"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Review the %d medium and high-risk application installs on %d endpoints and remove or approve each." % (p["highRiskInstances"], p["highRiskEndpoints"])})
    if a["behindLatest"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Upgrade the %d endpoints on older agent builds to %s." % (a["behindLatest"], f["latestVersion"])})
    if a["patchRequired"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Patch the applications flagged on %d endpoints." % a["patchRequired"]})
    if a["duplicateNames"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Check the %d host name%s that appear%s more than once: cloned machines or stale records." % (len(a["duplicateNames"]), "" if len(a["duplicateNames"]) == 1 else "s", "s" if len(a["duplicateNames"]) == 1 else "")})
    s.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare agent, application and threat counts with the previous quarter."})
    return s[:6]


# ---------------------------------------------------------------- html helpers
PALETTE = ["#175d9a", "#111111", "#a06c00", "#175d9a", "#8a8a8a", "#b3242e", "#8a8a8a", "#0E7490"]


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
    body = "".join("<tr%s>%s</tr>" % (' class="%s"' % r[1] if isinstance(r, tuple) else "", "".join(r[0] if isinstance(r, tuple) else r)) for r in rows)
    return '<table class="%s">%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, cg, th, body)


def td(x, wrap=False):
    return '<td%s>%s</td>' % (' class="wrap"' if wrap else "", esc(x))


def chip(text, color):
    return '<span class="st"><i style="background:%s"></i>%s</span>' % (color, esc(text))


def pill(text, kind):
    return '<span class="pill %s">%s</span>' % (kind, esc(text))


def trend_svg(weeks):
    """New hosts per week as columns (shared chart helper)."""
    if not weeks or not any(x["count"] for x in weeks):
        return '<p class="panel-subtitle">No threats recorded.</p>'
    return fb.column_chart([x["week"][5:] for x in weeks], [("New hosts", [x["count"] for x in weeks])], height=170, y_label="New hosts per week")


STATUS_COLOR = {"Needs action": "#b3242e", "Watch": "#a06c00", "Healthy": "#175d9a"}


def kpi(label, value, color, note=""):
    return ('<div class="kpi"><div class="kpi-value %s">%s</div><div class="kpi-label">%s</div>%s</div>'
            % (color, esc(value), esc(label), '<div class="kpi-note">%s</div>' % esc(note) if note else ""))




# ---------------------------------------------------------------- render
def cmd_render(args):
    arc = load_archive(args.archive)
    if not arc or not arc["tables"].get("s1res_endpoints"):
        print("PROBLEM: no archived day with SentinelOne endpoints; nothing to report", file=sys.stderr)
        return 1
    f, eps, app_rows, open_threats = analyse(arc)
    f["account"] = args.account
    a, p, t, e = f["agents"], f["applications"], f["threats"], f["endpoints"]
    n = a["inScope"]
    as_of = f["asOf"]
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}

    kp = [
        kpi("Endpoints", n, "navy", "%d reporting" % a["active"]),
        kpi("Not reporting", a["inactive"], "red" if a["inactive"] else "green", "%d for over %d days" % (a["inactiveStale"], INACTIVE_STALE_DAYS)),
        kpi("On newest agent", "%s%%" % pct(a["onLatest"], n), "green" if a["behindLatest"] == 0 else "amber", f["latestVersion"]),
        kpi("Need action", e["needsAction"], "red" if e["needsAction"] else "green", "%d more on watch" % e["watch"]),
    ]
    if f["present"]["threat"]:
        kp.append(kpi("Open threats", t["open"], "red" if t["open"] else "green", "%d recorded" % t["total"]))
    if f["present"]["application"]:
        kp.append(kpi("Risky app installs", p["highRiskInstances"], "amber" if p["highRiskInstances"] else "green", "%d endpoints" % p["highRiskEndpoints"]))

    g = []
    segs = [("Reporting", a["active"], "#175d9a")] + [(k, v, c) for (k, v), c in zip(
        sorted(a["inactiveBuckets"].items(), key=lambda kv: ["< 1 day", "1-7 days", "8-30 days", "> 30 days", "unknown"].index(kv[0])), ["#a06c00", "#b3242e", "#b3242e", "#8a8a8a"])]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * v / max(n, 1), c, esc(k), v) for k, v, c in segs if v)
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join(
        '<span class="lg"><i style="background:%s"></i>%s: %d</span>' % (c, esc("Reporting" if k == "Reporting" else ("Not reporting, last active unknown" if k == "unknown" else "Silent " + k)), v) for k, v, c in segs if v)
    g.append(panel("Agent reporting status", stack + legend + bars(a["machineTypes"], n, "var(--navy)"), 6, "%d endpoints" % n))
    vrows = [{"name": v["name"] + ("  (newest)" if v["name"] == f["latestVersion"] else ""), "count": v["count"]} for v in a["versions"]]
    g.append(panel("Agent versions", bars(vrows, n), 6, "newest build in the fleet: %s" % f["latestVersion"]))
    g.append(panel("Operating systems", bars(a["os"], n, "var(--navy)"), 6))
    prot = [("Mitigation mode not 'protect'", a["notProtect"]), ("Behind the newest agent build", a["behindLatest"]),
            ("Apps need patching", a["patchRequired"]), ("Infected / active threats", max(a["infected"], a["withActiveThreats"])),
            ("Endpoints with medium or high-risk apps", p["highRiskEndpoints"])]
    g.append(panel("Protection health", table(["Check", "Endpoints"], [[td(k), '<td class="num">%d</td>' % v] for k, v in prot], ["75%", "25%"]), 6, "endpoints affected"))
    if f["present"]["application"]:
        order = ["critical", "high", "medium", "low"]
        risk_items = [{"name": k.title(), "count": p["risk"][k]} for k in order if p["risk"].get(k)]
        unrated = p["instances"] - sum(i["count"] for i in risk_items)
        g.append(panel("Application risk", bars(risk_items, p["instances"], "var(--amber)", "No application is rated above none.") +
                       '<p class="panel-subtitle" style="margin-top:10px">%d installs across %d distinct applications. %d have no risk rating. %d were installed in the last %d days.</p>'
                       % (p["instances"], p["distinct"], unrated, p["newInWindow"], p["newWindowDays"]), 4, "install records"))
        if app_rows:
            rows = [[td(r["name"]), td(r["publisher"]), '<td>%s</td>' % pill(r["risk"].title(), "high" if r["risk"] in ("high", "critical") else "med" if r["risk"] == "medium" else "info"),
                     '<td class="num">%d</td>' % r["endpoints"]] for r in app_rows[:12]]
            g.append(panel("Most widespread applications", table(["Application", "Publisher", "Risk", "Endpoints"], rows, ["42%", "30%", "13%", "15%"]), 8, "top %d by endpoints" % len(rows)))
    if f["present"]["threat"]:
        g.append(panel("Threats per week", trend_svg(t["weekly"]), 6, "%s to %s" % (t["first"], t["last"]) if t["first"] else ""))
        g.append(panel("Classification", bars(t["classification"], t["total"], "var(--red)"), 6))
        g.append(panel("Mitigation status", bars([{"name": k.replace("_", " "), "count": v} for k, v in sorted(t["mitigation"].items(), key=lambda kv: -kv[1])], t["total"], "var(--navy)"), 6))
        g.append(panel("Incident status", bars([{"name": k.replace("_", " "), "count": v} for k, v in sorted(t["incident"].items(), key=lambda kv: -kv[1])], t["total"], "var(--amber)"), 6))
        mt = " · ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(t["mitigation"].items()))
        it = " · ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(t["incident"].items()))
        if open_threats:
            ot = sorted(open_threats, key=lambda x: x["created"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)[:15]
            rows = [[td(day(x["created"])), td(x["endpoint"]), td(x["threat"]), td(x["classification"]), td(x["verdict"]),
                     '<td>%s</td>' % pill(x["mitigation"].replace("_", " "), "high" if x["mitigation"] != "mitigated" else "info"), td(x["incident"].replace("_", " "))] for x in ot]
            g.append(panel("Open threats", '<p class="panel-subtitle">Mitigation: %s. Incident: %s.</p>' % (esc(mt), esc(it)) +
                           table(["Created", "Endpoint", "Threat", "Class", "Verdict", "Mitigation", "Incident"], rows, ["11%", "17%", "20%", "11%", "13%", "16%", "12%"]), 12, "newest %d of %d" % (len(ot), t["open"])))
        else:
            g.append(panel("Open threats", '<p class="panel-subtitle">All %d threats are mitigated and resolved. Mitigation: %s. Incident: %s.</p>' % (t["total"], esc(mt), esc(it)), 12))

    attn = sorted([x for x in eps if x["score"]], key=lambda x: (-x["score"], x["computerName"].lower()))
    cap = args.max_listed
    rows = [([('<td class="host">%s</td>' % esc(x["computerName"])), td(x["machineType"]), td(x["os"]), td(x["agentVersion"]),
              '<td>%s</td>' % chip(x["status"], STATUS_COLOR.get(x["status"], "#8a8a8a")), td(x["reasons"], True)], "") for x in attn[:cap]]
    note = "" if len(attn) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(attn))
    app = [panel("Endpoints needing attention", table(["Endpoint", "Type", "OS", "Agent", "Status", "Why"], rows, ["17%", "8%", "16%", "11%", "15%", "33%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No endpoint has an open issue.</p>', 12, "%d of %d%s" % (len(attn), n, note), "page-break")]
    hist = f["history"][-8:]
    if len(hist) > 1:
        hrows = [[td(h["asOf"]), '<td class="num">%d</td>' % h["endpoints"], '<td class="num">%d</td>' % h["inactive"], '<td class="num">%d</td>' % h["needsAction"],
                  '<td class="num">%d</td>' % h["watch"], '<td class="num">%d</td>' % h["openThreats"], '<td class="num">%d</td>' % h["riskyEndpoints"]] for h in reversed(hist)]
        app.append(panel("Change over the archived days", table(["As of", "Endpoints", "Not reporting", "Need action", "Watch", "Open threats", "Endpoints with risky apps"], hrows, ["16%", "14%", "15%", "14%", "11%", "14%", "16%"]), 12, "each day is a snapshot, not an event count"))
    method = ('<div class="method">'
              '<div><b>Source.</b> The archived daily SentinelOne resource report (agents, applications, threats), as of %s. Each archived day is a snapshot of the console; the latest day is used and days are never added together.</div>'
              '<div><b>Endpoints.</b> Agents that are decommissioned or uninstalled are left out (%d).</div>'
              '<div><b>Reporting.</b> An agent counts as reporting when SentinelOne marks it active. Not-reporting agents are grouped by days since last active.</div>'
              '<div><b>Newest build.</b> Taken as the highest agent version seen in this fleet, not the latest SentinelOne release.</div>'
              '<div><b>Needs action.</b> Score of 3 or more: infection or open threat (3 each), not reporting (2 to 3), not in protect mode (2). Watch is 1 to 2: medium/high-risk app, patching, older agent.</div>'
              '<div><b>Open threat.</b> Not mitigated, or the incident is not resolved. Threat history covers %s to %s. Applications are counted as installs; the application list shows the 25 most widespread.</div></div>'
              % (esc(as_of), a["decommissioned"] + a["uninstalled"], esc(t["first"] or "n/a"), esc(t["last"] or "n/a")))
    app.append(panel("How to read this report", method, 12))
    bits = []
    if a["duplicateNames"]:
        bits.append("%d host name%s appear%s more than once: %s." % (len(a["duplicateNames"]), "" if len(a["duplicateNames"]) == 1 else "s", "s" if len(a["duplicateNames"]) == 1 else "", esc(", ".join(a["duplicateNames"][:8]))))
    bad = [s["source"] for s in f["sources"] if s.get("status") != "ok"]
    if bad:
        bits.append("Not available in the archived run: %s." % esc(", ".join(bad)))
    if a["inactive"] and not any(x["lastActiveDays"] is not None for x in eps if not x["active"]):
        bits.append("The archive does not say how long the %d silent endpoints have been silent." % a["inactive"])
    if bits:
        app.append(panel("Data notes", '<div class="method"><div>%s</div></div>' % " ".join(bits), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(s.get("tone"), "var(--navy)"), i + 1, esc(s.get("when", "")), esc(s.get("text", ""))) for i, s in enumerate(steps))

    subtitle = args.customer or args.account
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "SentinelOne Resource Report", "report_subtitle": subtitle,
        "report_date": as_of, "report_meta": " · account <strong>%s</strong> · as of %s" % (esc(args.account), esc(as_of)),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "SentinelOne resource report · %s" % esc(subtitle), "footer_data_date": esc(as_of),
    }
    for k, v in page.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    with open(os.path.join(args.work, "sentinelone_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    with open(os.path.join(args.work, "endpoints.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["as_of", "computer_name", "machine_type", "os", "group", "agent_version", "behind_newest", "reporting", "silent_days",
                    "mitigation_mode", "apps_vulnerability", "active_threats", "risky_app_installs", "open_threats", "score", "status", "reasons"])
        for x in sorted(eps, key=lambda x: (-x["score"], x["computerName"].lower())):
            w.writerow([as_of, x["computerName"], x["machineType"], x["os"], x["group"], x["agentVersion"], x["behindLatest"], x["active"],
                        "" if x["lastActiveDays"] is None else x["lastActiveDays"], x["mitigationMode"], x["appsVuln"], x["activeThreats"],
                        x["highRiskApps"], x["openThreats"], x["score"], x["status"], x["reasons"]])
    with open(os.path.join(args.work, "applications_top.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["as_of", "application", "publisher", "risk", "endpoints"])
        for r in app_rows:
            w.writerow([as_of, r["name"], r["publisher"], r["risk"], r["endpoints"]])
    with open(os.path.join(args.work, "open_threats.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["as_of", "created", "endpoint", "threat_name", "classification", "confidence", "analyst_verdict", "mitigation_status", "incident_status"])
        for x in sorted(open_threats, key=lambda x: x["created"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True):
            w.writerow([as_of, day(x["created"]), x["endpoint"], x["threat"], x["classification"], x["confidence"], x["verdict"], x["mitigation"], x["incident"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "sentinelone_resource_report_interactive.html"), args, f, eps, app_rows, open_threats)

    print("as of %s (%d archived day%s)" % (as_of, f["archiveDays"], "" if f["archiveDays"] == 1 else "s"))
    print("endpoints %d (reporting %d, not reporting %d) | newest build %s, behind %d" % (n, a["active"], a["inactive"], f["latestVersion"], a["behindLatest"]))
    print("needs action %d, watch %d, healthy %d" % (e["needsAction"], e["watch"], e["healthy"]))
    print("applications: %d installs, %d distinct, %d risky installs on %d endpoints" % (p["instances"], p["distinct"], p["highRiskInstances"], p["highRiskEndpoints"]))
    print("threats: %d total, %d open (%s to %s)" % (t["total"], t["open"], t["first"], t["last"]))
    print("wrote: sentinelone_resource_report.html, sentinelone_resource_report_interactive.html, endpoints.csv, applications_top.csv, open_threats.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, eps, app_rows, open_threats):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    a, p, t = f["agents"], f["applications"], f["threats"]
    order = ["< 1 day", "1-7 days", "8-30 days", "> 30 days", "unknown"]
    a = dict(a, inactiveBuckets={k: a["inactiveBuckets"][k] for k in order if k in a["inactiveBuckets"]})
    endpoints = [{
        "name": x["computerName"], "type": x["machineType"], "os": x["os"], "agent": x["agentVersion"],
        "reporting": "Reporting" if x["active"] else "Not reporting",
        "lastActiveDays": x["lastActiveDays"] if x["lastActiveDays"] is not None else "",
        "mitigation": x["mitigationMode"], "riskyApps": x["highRiskApps"], "openThreats": x["openThreats"], "score": x["score"],
        "status": x["status"], "reasons": x["reasons"], "patch": "Patch required" if x["appsVuln"] == "patch_required" else "Up to date"} for x in eps]
    apps = [{"name": r["name"], "publisher": r["publisher"], "risk": r["risk"].title(), "endpoints": r["endpoints"]} for r in app_rows]
    trows = [{"created": (day(x["created"])), "endpoint": x["endpoint"], "name": x["threat"], "cls": x["classification"], "confidence": x["confidence"],
              "verdict": x["verdict"], "mitigation": x["mitigation"].replace("_", " "), "incident": x["incident"].replace("_", " ")} for x in open_threats]
    notes = []
    if a["duplicateNames"]:
        notes.append("%d host name(s) appear more than once: %s." % (len(a["duplicateNames"]), ", ".join(a["duplicateNames"][:8])))
    bad = [s["source"] for s in f["sources"] if s.get("status") != "ok"]
    if bad:
        notes.append("Not available in the archived run: %s." % ", ".join(bad))
    if t["open"] > len(trows):
        notes.append("The archive lists %d of the %d open threats." % (len(trows), t["open"]))
    method = [
        "Source: the archived daily SentinelOne resource report, as of %s. Each archived day is a snapshot; the latest day is shown and days are never added together." % f["asOf"],
        "Reporting: an agent is reporting when SentinelOne marks it active. Silent endpoints are bucketed by days since last active; more than %d days is stale." % INACTIVE_STALE_DAYS,
        "Newest build: the highest agent version in this fleet, not the latest SentinelOne release.",
        "Needs action is a score of 3 or more: infection or open threat (3 each), not reporting (2 to 3), not in protect mode (2). Watch is 1 to 2: medium/high-risk app, patching, older agent.",
        "Open threat: not mitigated, or the incident is not resolved. The Threats tab lists the open threats; history is summarised by class, status and week.",
        "Application counts are installs; one application on 57 endpoints is 57 installs and one distinct application. The Applications tab lists the 25 most widespread.",
    ]
    data = {"title": "SentinelOne Resource Report", "account": args.account, "customer": args.customer, "snapshot": f["asOf"],
            "staleDays": INACTIVE_STALE_DAYS, "latestVersion": f["latestVersion"],
            "present": f["present"], "agents": a, "applications": p, "threats": t, "endpointSummary": f["endpoints"],
            "endpoints": endpoints, "apps": apps, "threatRows": trows, "sources": f["sources"], "history": f["history"], "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " SentinelOne Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--archive", nargs="+", required=True)
    r = sub.add_parser("render"); r.add_argument("--archive", nargs="+", required=True); r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--max-listed", type=int, default=40)
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
