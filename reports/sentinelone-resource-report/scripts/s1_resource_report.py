#!/usr/bin/env python3
"""SentinelOne resource report: agents, applications and threats in one page.

Reads the three SentinelOne resource dumps (sentinelOneAgent, sentinelOneApplication,
sentinelOneThreat) for one Fluency / Ingext account, joins them on the agent UUID and writes
facts.json, three CSVs and a Fluency-branded HTML page. Standard library only.

  s1_resource_report.py check  --dumps DIR
  s1_resource_report.py render --dumps DIR --work DIR --account NAME [--customer TEXT]

Dumps live at DIR/<resource>/<customer>.jsonl.gz.
"""
import argparse, collections, csv, datetime as dt, glob, gzip, html, json, os, shutil, sys

RES = {"agent": "sentinelOneAgent", "application": "sentinelOneApplication", "threat": "sentinelOneThreat"}
INACTIVE_STALE_DAYS = 7     # not reporting for longer than this is "stale"
SCAN_STALE_DAYS = 30        # last full disk scan older than this is flagged
NEW_APP_DAYS = 30           # "recently installed" window
TREND_WEEKS = 12
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")


# ---------------------------------------------------------------- loading
def load(dumps, key):
    """Return (rows, customers, snapshot_hours, files) for one resource type."""
    rows, customers, hours, files = [], set(), set(), []
    for path in sorted(glob.glob(os.path.join(dumps, RES[key], "*.jsonl.gz"))):
        files.append(os.path.basename(path))
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                body = rec.get("@" + RES[key])
                if not isinstance(body, dict):
                    continue
                body["_customer"] = rec.get("@customer", "")
                body["_ts"] = rec.get("@timestamp")
                rows.append(body)
                customers.add(rec.get("@customer", ""))
                if rec.get("@dayIndex"):
                    hours.add(rec["@dayIndex"])
    return rows, sorted(customers), sorted(hours), files


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


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def day(d):
    return d.strftime("%Y-%m-%d") if d else ""


# ---------------------------------------------------------------- check
def cmd_check(args):
    now = dt.datetime.now(dt.timezone.utc)
    problems = 0
    agents = []
    for key in RES:
        rows, customers, hours, files = load(args.dumps, key)
        newest = max((r["_ts"] for r in rows if r.get("_ts")), default=None)
        age_h = (now.timestamp() - newest / 1000.0) / 3600.0 if newest else None
        level = "ok"
        note = ""
        if not rows:
            level = "PROBLEM" if key == "agent" else "warning"
            note = "no records" + (": the report cannot run" if key == "agent" else ": that section will be left out")
        elif age_h is not None and age_h > 48:
            level = "PROBLEM" if key == "agent" else "warning"
            note = "snapshot is %.0f hours old" % age_h
        if level == "PROBLEM":
            problems += 1
        print("%-8s %-24s records=%-7d customers=%-2d snapshot=%s files=%s %s"
              % (level, RES[key], len(rows), len(customers), ",".join(hours) or "-", len(files), note))
        if key == "agent":
            agents = rows
    if agents:
        in_scope = [a for a in agents if not a.get("isDecommissioned") and not a.get("isUninstalled")]
        print("agents: %d records, %d in scope, %d active, %d distinct hosts"
              % (len(agents), len(in_scope), sum(1 for a in in_scope if a.get("isActive")),
                 len({(a.get("computerName") or "").lower() for a in in_scope})))
    return 1 if problems else 0


# ---------------------------------------------------------------- analysis
def top(counter, n=10):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def analyse(dumps, now):
    agents_all, a_cust, a_hours, _ = load(dumps, "agent")
    apps, p_cust, p_hours, _ = load(dumps, "application")
    threats, t_cust, t_hours, _ = load(dumps, "threat")

    ag = [a for a in agents_all if not a.get("isDecommissioned") and not a.get("isUninstalled")]
    by_uuid = {a.get("uuid"): a for a in ag}
    latest = max((a.get("agentVersion") for a in ag if a.get("agentVersion")), key=vkey, default="")

    # per-endpoint accumulators
    ep = {}
    for a in ag:
        last = ts(a.get("lastActiveDate"))
        scan = ts(a.get("scanFinishedAt"))
        ep[a["uuid"]] = {
            "customer": a.get("_customer", ""), "computerName": a.get("computerName", ""),
            "machineType": a.get("machineType", ""), "os": a.get("osName", ""),
            "osRevision": a.get("osRevision", ""), "group": a.get("groupName", ""),
            "site": a.get("siteName", ""), "domain": a.get("domain", ""),
            "user": a.get("lastLoggedInUserName", ""), "agentVersion": a.get("agentVersion", ""),
            "behindLatest": bool(a.get("agentVersion")) and vkey(a["agentVersion"]) < vkey(latest),
            "active": bool(a.get("isActive")), "lastActive": last,
            "lastActiveDays": (now - last).days if last else None,
            "scanDays": (now - scan).days if scan else None,
            "scanStatus": a.get("scanStatus", ""), "mitigationMode": a.get("mitigationMode", ""),
            "networkStatus": a.get("networkStatus", ""),
            "appsVuln": a.get("appsVulnerabilityStatus", ""),
            "infected": bool(a.get("infected")), "activeThreats": a.get("activeThreats") or 0,
            "rebootRequired": bool(a.get("threatRebootRequired")),
            "apps": 0, "highRiskApps": 0, "threats": 0, "openThreats": 0, "recentThreats": 0,
        }

    # applications
    app_idx = collections.OrderedDict()
    risk = collections.Counter(); os_type = collections.Counter(); publishers = collections.Counter()
    new_apps = 0; orphan_app_agents = set()
    for p in apps:
        u = p.get("agentUuid")
        e = ep.get(u)
        if e is None:
            orphan_app_agents.add(u)
            continue
        e["apps"] += 1
        lvl = (p.get("riskLevel") or "none").lower()
        risk[lvl] += 1
        os_type[p.get("osType") or "unknown"] += 1
        publishers[p.get("publisher") or "(unknown)"] += 1
        if lvl in ("high", "medium", "critical"):
            e["highRiskApps"] += 1
        inst = ts(p.get("installedAt"))
        if inst and (now - inst).days <= NEW_APP_DAYS:
            new_apps += 1
        k = (p.get("name") or "(unnamed)", p.get("publisher") or "")
        row = app_idx.setdefault(k, {"name": k[0], "publisher": k[1], "installs": 0, "hosts": set(),
                                     "versions": set(), "risk": "none", "windowsLegacy": 0})
        row["installs"] += 1
        row["hosts"].add(e["computerName"])
        row["versions"].add(p.get("version") or "")
        if p.get("osType") == "windows_legacy":
            row["windowsLegacy"] += 1
        order = ["none", "low", "medium", "high", "critical"]
        if lvl in order and order.index(lvl) > order.index(row["risk"] if row["risk"] in order else "none"):
            row["risk"] = lvl

    # threats
    classification = collections.Counter(); confidence = collections.Counter(); verdict = collections.Counter()
    mitig = collections.Counter(); incident = collections.Counter(); tnames = collections.Counter()
    fverify = collections.Counter(); per_ep = collections.Counter(); weekly = collections.Counter()
    open_threats = []; orphan_threat_agents = {}
    first = last = None
    for t in threats:
        ti = t.get("threatInfo") or {}
        rt = t.get("agentRealtimeInfo") or {}
        det = t.get("agentDetectionInfo") or {}
        u = rt.get("agentUuid") or det.get("agentUuid")
        name = rt.get("agentComputerName") or det.get("agentComputerName") or ""
        created = ts(ti.get("createdAt"))
        if created:
            first = created if not first or created < first else first
            last = created if not last or created > last else last
            monday = (created - dt.timedelta(days=created.weekday())).date()
            weekly[monday] += 1
        cls = ti.get("classification") or "Unclassified"
        classification[cls] += 1
        confidence[(ti.get("confidenceLevel") or "unknown").title()] += 1
        verdict[ti.get("analystVerdictDescription") or ti.get("analystVerdict") or "Undefined"] += 1
        ms = ti.get("mitigationStatus") or "unknown"
        mitig[ms] += 1
        inc = ti.get("incidentStatus") or "unknown"
        incident[inc] += 1
        tnames[ti.get("threatName") or "(unnamed)"] += 1
        fverify[ti.get("fileVerificationType") or "unknown"] += 1
        per_ep[name or u or "(unknown)"] += 1
        is_open = ms != "mitigated" or inc != "resolved"
        e = ep.get(u)
        if e is not None:
            e["threats"] += 1
            if is_open:
                e["openThreats"] += 1
            if created and (now - created).days <= 30:
                e["recentThreats"] += 1
        else:
            orphan_threat_agents[u] = name
        if is_open:
            open_threats.append({"created": created, "endpoint": name, "threat": ti.get("threatName") or "",
                                 "classification": cls, "verdict": verdict_label(ti), "mitigation": ms,
                                 "incident": inc})

    # endpoint scoring
    for e in ep.values():
        why, total = [], [0]

        def add(n, text):
            total[0] += n
            why.append(text)
        if e["infected"] or e["activeThreats"]:
            add(3, "infected / active threats")
        if e["openThreats"]:
            add(3, "%d open threat%s" % (e["openThreats"], "" if e["openThreats"] == 1 else "s"))
        if not e["active"]:
            stale = e["lastActiveDays"] is not None and e["lastActiveDays"] > INACTIVE_STALE_DAYS
            add(3 if stale else 2, "not reporting" + ("" if e["lastActiveDays"] is None else " for less than a day" if e["lastActiveDays"] < 1 else " for %d day%s" % (e["lastActiveDays"], "" if e["lastActiveDays"] == 1 else "s")))
        if e["mitigationMode"] and e["mitigationMode"] != "protect":
            add(2, "mitigation mode %s" % e["mitigationMode"])
        if e["highRiskApps"]:
            add(1, "%d high/medium-risk app%s" % (e["highRiskApps"], "" if e["highRiskApps"] == 1 else "s"))
        if e["appsVuln"] == "patch_required":
            add(1, "apps need patching")
        if e["behindLatest"]:
            add(1, "agent %s behind %s" % (e["agentVersion"], latest))
        if e["rebootRequired"]:
            add(1, "reboot required")
        e["score"] = total[0]
        e["reasons"] = "; ".join(why)
        e["status"] = "Needs action" if e["score"] >= 3 else ("Watch" if e["score"] else "Healthy")

    eps = list(ep.values())
    n = len(eps)
    active = sum(1 for e in eps if e["active"])
    seen = collections.Counter((e["computerName"] or "").lower() for e in eps)
    dup_names = sorted({e["computerName"] for e in eps if e["computerName"] and seen[e["computerName"].lower()] > 1})
    buckets = collections.Counter()
    for e in eps:
        if e["active"]:
            continue
        d = e["lastActiveDays"]
        buckets["< 1 day" if d is not None and d < 1 else "1-7 days" if d is not None and d <= 7
                else "8-30 days" if d is not None and d <= 30 else "> 30 days" if d is not None else "unknown"] += 1
    weeks = []
    if weekly:
        n_weeks = min(TREND_WEEKS, max(6, (max(weekly) - min(weekly)).days // 7 + 1))
        start = max(weekly) - dt.timedelta(weeks=n_weeks - 1)
        for i in range(n_weeks):
            w = start + dt.timedelta(weeks=i)
            weeks.append({"week": w.isoformat(), "count": weekly.get(w, 0)})

    app_rows = sorted(app_idx.values(), key=lambda r: (-{"critical": 4, "high": 3, "medium": 2, "low": 1}.get(r["risk"], 0), -len(r["hosts"]), r["name"].lower()))
    facts = {
        "account": "", "generated": now.isoformat(), "latestVersion": latest,
        "snapshot": {"agent": a_hours, "application": p_hours, "threat": t_hours},
        "customers": sorted(set(a_cust) | set(p_cust) | set(t_cust)),
        "present": {"agent": bool(agents_all), "application": bool(apps), "threat": bool(threats)},
        "agents": {
            "records": len(agents_all), "inScope": n, "decommissioned": sum(1 for a in agents_all if a.get("isDecommissioned")),
            "uninstalled": sum(1 for a in agents_all if a.get("isUninstalled")),
            "pendingUninstall": sum(1 for a in ag if a.get("isPendingUninstall")),
            "active": active, "inactive": n - active,
            "inactiveStale": sum(1 for e in eps if not e["active"] and (e["lastActiveDays"] or 0) > INACTIVE_STALE_DAYS),
            "inactiveBuckets": dict(buckets),
            "onLatest": sum(1 for e in eps if e["agentVersion"] and not e["behindLatest"]),
            "behindLatest": sum(1 for e in eps if e["behindLatest"]),
            "versions": top(collections.Counter(e["agentVersion"] or "unknown" for e in eps), 12),
            "machineTypes": top(collections.Counter(e["machineType"] or "unknown" for e in eps)),
            "os": top(collections.Counter(e["os"] or "unknown" for e in eps), 10),
            "groups": top(collections.Counter(e["group"] or "unknown" for e in eps), 10),
            "mitigationModes": top(collections.Counter(e["mitigationMode"] or "unknown" for e in eps)),
            "notProtect": sum(1 for e in eps if e["mitigationMode"] and e["mitigationMode"] != "protect"),
            "scanStatus": top(collections.Counter(e["scanStatus"] or "unknown" for e in eps)),
            "scanStale": sum(1 for e in eps if e["scanDays"] is not None and e["scanDays"] > SCAN_STALE_DAYS),
            "appsVulnerability": top(collections.Counter(e["appsVuln"] or "unknown" for e in eps)),
            "patchRequired": sum(1 for e in eps if e["appsVuln"] == "patch_required"),
            "infected": sum(1 for e in eps if e["infected"]), "withActiveThreats": sum(1 for e in eps if e["activeThreats"]),
            "rebootRequired": sum(1 for e in eps if e["rebootRequired"]),
            "duplicateNames": sorted(dup_names),
        },
        "applications": {
            "instances": sum(risk.values()), "distinct": len(app_idx), "risk": dict(risk), "osType": dict(os_type),
            "highRiskInstances": sum(v for k, v in risk.items() if k in ("high", "medium", "critical")),
            "highRiskDistinct": sum(1 for r in app_rows if r["risk"] in ("high", "medium", "critical")),
            "highRiskEndpoints": sum(1 for e in eps if e["highRiskApps"]),
            "newInWindow": new_apps, "newWindowDays": NEW_APP_DAYS,
            "windowsLegacy": os_type.get("windows_legacy", 0),
            "topPublishers": top(publishers, 8),
            "topApps": [{"name": r["name"], "publisher": r["publisher"], "endpoints": len(r["hosts"])}
                        for r in sorted(app_rows, key=lambda r: -len(r["hosts"]))[:8]],
            "orphanAgents": len(orphan_app_agents),
        },
        "threats": {
            "total": len(threats), "first": day(first), "last": day(last), "open": len(open_threats),
            "classification": top(classification), "confidence": top(confidence), "verdict": top(verdict),
            "mitigation": dict(mitig), "incident": dict(incident), "topNames": top(tnames, 10),
            "topEndpoints": top(per_ep, 10), "fileVerification": top(fverify), "weekly": weeks,
            "endpointsAffected": len({k for k in per_ep}), "orphanEndpoints": sorted(v or "(unknown)" for v in orphan_threat_agents.values()),
            "malicious": confidence.get("Malicious", 0),
        },
        "endpoints": {"needsAction": sum(1 for e in eps if e["status"] == "Needs action"),
                      "watch": sum(1 for e in eps if e["status"] == "Watch"),
                      "healthy": sum(1 for e in eps if e["status"] == "Healthy")},
    }
    return facts, eps, app_rows, threats, open_threats


def verdict_label(ti):
    return ti.get("analystVerdictDescription") or ti.get("analystVerdict") or ""


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
        parts.append("<strong>%d threats</strong> were recorded between %s and %s; <strong>%d are still open</strong> "
                     "(not mitigated or not resolved)." % (t["total"], esc(t["first"]), esc(t["last"]), t["open"]))
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
        s.append({"when": "This week" if a["inactiveStale"] else "Within 14 days", "tone": "urgent" if a["inactiveStale"] else "normal",
                  "text": "Find out why %d endpoints are not reporting (%d for over %d days): powered off, retired, or the agent is damaged." % (a["inactive"], a["inactiveStale"], INACTIVE_STALE_DAYS)})
    if a["notProtect"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Move the %d endpoints that are not in protect mode back to protect." % a["notProtect"]})
    if p["highRiskInstances"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Review the %d medium and high-risk applications installed on %d endpoints and remove or approve each." % (p["highRiskDistinct"], p["highRiskEndpoints"])})
    if a["behindLatest"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Upgrade the %d endpoints on older agent builds to %s." % (a["behindLatest"], f["latestVersion"])})
    if a["patchRequired"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Patch the applications flagged on %d endpoints." % a["patchRequired"]})
    if a["duplicateNames"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Check the %d host name%s that appear%s more than once: cloned machines or stale records." % (len(a["duplicateNames"]), "" if len(a["duplicateNames"]) == 1 else "s", "s" if len(a["duplicateNames"]) == 1 else "")})
    s.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare agent, application and threat counts with the previous quarter."})
    return s[:6]


# ---------------------------------------------------------------- html helpers
PALETTE = ["#1D4ED8", "#14213d", "#B45309", "#15803D", "#64748B", "#B91C1C", "#7C3AED", "#0E7490"]


def panel(title, body, cols=6, sub="", cls=""):
    return ('<div class="panel col-%d %s"><div class="panel-header"><h3 class="panel-title">%s</h3>%s</div>%s</div>'
            % (cols, cls, esc(title), '<span class="panel-subtitle">%s</span>' % esc(sub) if sub else "", body))


def bars(items, total=None, color="var(--blue)", empty="No data."):
    items = [i for i in items if i["count"]]
    if not items:
        return '<p class="panel-subtitle">%s</p>' % esc(empty)
    mx = max(i["count"] for i in items)
    out = ['<div class="ibars">']
    for i in items:
        w = max(2.0, 100.0 * i["count"] / mx)
        sub = '<span class="ibar-sub">%s%%</span>' % pct(i["count"], total) if total else ""
        label = i["name"] if len(str(i["name"])) <= 44 else str(i["name"])[:41] + "..."
        out.append('<div class="ibar"><div class="ibar-label" title="%s">%s%s</div><div class="bar-track"><div class="bar-fill" style="width:%.1f%%;background:%s"></div></div>'
                   '<div class="ibar-val">%s</div></div>' % (esc(i["name"]), esc(label), sub, w, color, i["count"]))
    out.append("</div>")
    return "".join(out)


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
    if not weeks:
        return '<p class="panel-subtitle">No threats recorded.</p>'
    w, h, pad = 520, 170, 26
    mx = max(x["count"] for x in weeks) or 1
    bw = (w - 2 * pad) / len(weeks)
    out = ['<svg class="svg-chart" viewBox="0 0 %d %d" role="img" aria-label="Threats per week">' % (w, h)]
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e2e8f0"/>' % (pad, h - 24, w - pad, h - 24))
    for i, x in enumerate(weeks):
        bh = (h - 56) * x["count"] / mx
        bx = pad + i * bw + 4
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#1D4ED8"><title>Week of %s: %d</title></rect>'
                   % (bx, h - 24 - bh, bw - 8, bh, x["week"], x["count"]))
        if x["count"]:
            out.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" fill="#475569">%d</text>' % (bx + (bw - 8) / 2, h - 28 - bh, x["count"]))
        if i % 2 == 0 or len(weeks) < 7:
            out.append('<text x="%.1f" y="%d" font-size="9" text-anchor="middle" fill="#64748B">%s</text>' % (bx + (bw - 8) / 2, h - 8, x["week"][5:]))
    out.append("</svg>")
    return "".join(out)


STATUS_COLOR = {"Needs action": "#B91C1C", "Watch": "#B45309", "Healthy": "#15803D"}


def kpi(label, value, color, note=""):
    return ('<div class="kpi"><div class="kpi-value %s">%s</div><div class="kpi-label">%s</div>%s</div>'
            % (color, esc(value), esc(label), '<div class="kpi-note">%s</div>' % esc(note) if note else ""))


# ---------------------------------------------------------------- render
def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    f, eps, app_rows, threats, open_threats = analyse(args.dumps, now)
    if not f["present"]["agent"]:
        print("PROBLEM: no sentinelOneAgent records; nothing to report", file=sys.stderr)
        return 1
    f["account"] = args.account
    a, p, t, e = f["agents"], f["applications"], f["threats"], f["endpoints"]
    n = a["inScope"]
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}

    # KPIs
    kp = [
        kpi("Endpoints", n, "navy", "%d reporting" % a["active"]),
        kpi("Not reporting", a["inactive"], "red" if a["inactive"] else "green", "%d for over %d days" % (a["inactiveStale"], INACTIVE_STALE_DAYS)),
        kpi("On newest agent", "%s%%" % pct(a["onLatest"], n), "green" if a["behindLatest"] == 0 else "amber", f["latestVersion"]),
        kpi("Need action", e["needsAction"], "red" if e["needsAction"] else "green", "%d more on watch" % e["watch"]),
    ]
    if f["present"]["threat"]:
        kp.append(kpi("Open threats", t["open"], "red" if t["open"] else "green", "%d recorded" % t["total"]))
    if f["present"]["application"]:
        kp.append(kpi("Risky app installs", p["highRiskInstances"], "amber" if p["highRiskInstances"] else "green", "%d distinct apps" % p["highRiskDistinct"]))

    g = []
    # --- 1 fleet status
    segs = [("Reporting", a["active"], "#15803D")] + [(k, v, c) for (k, v), c in zip(
        sorted(a["inactiveBuckets"].items(), key=lambda kv: ["< 1 day", "1-7 days", "8-30 days", "> 30 days", "unknown"].index(kv[0])), ["#B45309", "#B91C1C", "#7f1d1d", "#64748B"])]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * v / n, c, esc(k), v) for k, v, c in segs if v)
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %d</span>' % (c, esc(k if k == "Reporting" else "Silent " + k), v) for k, v, c in segs if v)
    g.append(panel("Agent reporting status", stack + legend + bars(a["machineTypes"], n, "var(--navy)"), 6, "%d endpoints" % n))
    # --- 2 versions
    vrows = [{"name": v["name"] + ("  (newest)" if v["name"] == f["latestVersion"] else ""), "count": v["count"]} for v in a["versions"]]
    g.append(panel("Agent versions", bars(vrows, n), 6, "newest build in the fleet: %s" % f["latestVersion"]))
    # --- 3 OS, protection settings
    g.append(panel("Operating systems", bars(a["os"], n, "var(--navy)"), 6))
    prot = [
        ("Mitigation mode not 'protect'", a["notProtect"]), ("Reboot required", a["rebootRequired"]),
        ("Apps need patching", a["patchRequired"]), ("Infected / active threats", max(a["infected"], a["withActiveThreats"])),
        ("Last full scan older than %d days (info only)" % SCAN_STALE_DAYS, a["scanStale"]), ("Pending uninstall", a["pendingUninstall"]),
    ]
    g.append(panel("Protection health", table(["Check", "Endpoints"], [[td(k), '<td class="num">%d</td>' % v] for k, v in prot], ["75%", "25%"]), 6, "endpoints affected"))
    # --- applications
    if f["present"]["application"]:
        order = ["critical", "high", "medium", "low"]
        risk_items = [{"name": k.title(), "count": p["risk"][k]} for k in order if p["risk"].get(k)]
        unrated = p["instances"] - sum(i["count"] for i in risk_items)
        g.append(panel("Application risk", bars(risk_items, p["instances"], "var(--amber)", "No application is rated above none.") +
                       '<p class="panel-subtitle" style="margin-top:10px">%d installs across %d distinct applications. %d have no risk rating. %d were installed in the last %d days.</p>'
                       % (p["instances"], p["distinct"], unrated, p["newInWindow"], p["newWindowDays"]), 4, "install records"))
        g.append(panel("Top publishers", bars(p["topPublishers"], p["instances"], "var(--navy)"), 4, "by installs"))
        g.append(panel("Most widespread applications", bars([{"name": x["name"], "count": x["endpoints"]} for x in p["topApps"]], n, "var(--blue)"), 4, "endpoints"))
        risky = [r for r in app_rows if r["risk"] in ("critical", "high", "medium")][:15]
        if risky:
            rows = [[td(r["name"]), td(r["publisher"]), td(", ".join(sorted(v for v in r["versions"] if v)[:3]) + (" +" if len(r["versions"]) > 3 else "")),
                     '<td>%s</td>' % pill(r["risk"].title(), "high" if r["risk"] in ("high", "critical") else "med"), '<td class="num">%d</td>' % len(r["hosts"])] for r in risky]
            g.append(panel("Medium and high-risk applications", table(["Application", "Publisher", "Versions", "Risk", "Endpoints"], rows, ["28%", "26%", "20%", "10%", "16%"]), 12, "top %d of %d" % (len(risky), p["highRiskDistinct"])))
    # --- threats
    if f["present"]["threat"]:
        g.append(panel("Threats per week", trend_svg(t["weekly"]), 6, "%s to %s" % (t["first"], t["last"])))
        g.append(panel("Classification and confidence", bars(t["classification"], t["total"], "var(--red)") + '<div style="height:12px"></div>' + bars(t["confidence"], t["total"], "var(--amber)"), 6))
        g.append(panel("Top threat names", bars(t["topNames"], t["total"], "var(--red)"), 6))
        g.append(panel("Endpoints with the most threats", bars(t["topEndpoints"], t["total"], "var(--navy)"), 6))
        mt = " · ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(t["mitigation"].items()))
        it = " · ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(t["incident"].items()))
        if open_threats:
            ot = sorted(open_threats, key=lambda x: x["created"] or now, reverse=True)[:15]
            rows = [[td(day(x["created"])), td(x["endpoint"]), td(x["threat"]), td(x["classification"]), td(x["verdict"]),
                     '<td>%s</td>' % pill(x["mitigation"].replace("_", " "), "high" if x["mitigation"] != "mitigated" else "info"), td(x["incident"].replace("_", " "))] for x in ot]
            g.append(panel("Open threats", '<p class="panel-subtitle">Mitigation: %s. Incident: %s.</p>' % (esc(mt), esc(it)) +
                           table(["Created", "Endpoint", "Threat", "Class", "Verdict", "Mitigation", "Incident"], rows, ["11%", "17%", "20%", "11%", "13%", "16%", "12%"]), 12, "newest %d of %d" % (len(ot), t["open"])))
        else:
            g.append(panel("Open threats", '<p class="panel-subtitle">All %d threats are mitigated and resolved. Mitigation: %s. Incident: %s.</p>' % (t["total"], esc(mt), esc(it)), 12))

    # --- appendix: endpoints needing attention + method
    attn = sorted([x for x in eps if x["score"]], key=lambda x: (-x["score"], x["computerName"].lower()))
    cap = args.max_listed
    rows = []
    for x in attn[:cap]:
        rows.append(([('<td class="host">%s</td>' % esc(x["computerName"])), td(x["machineType"]), td(x["os"]), td(x["agentVersion"]),
                      '<td>%s</td>' % chip(x["status"], STATUS_COLOR[x["status"]]), td(x["reasons"], True)], ""))
    note = "" if len(attn) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(attn))
    app = [panel("Endpoints needing attention", table(["Endpoint", "Type", "OS", "Agent", "Status", "Why"], rows, ["17%", "8%", "16%", "11%", "15%", "33%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No endpoint has an open issue.</p>', 12, "%d of %d%s" % (len(attn), n, note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Sources.</b> Three SentinelOne resource snapshots (agents, applications, threats), joined on the agent UUID.</div>'
              '<div><b>Endpoints.</b> Agents that are decommissioned or uninstalled are left out (%d).</div>'
              '<div><b>Reporting.</b> An agent counts as reporting when SentinelOne marks it active. Not-reporting agents are grouped by days since last active.</div>'
              '<div><b>Newest build.</b> Taken as the highest agent version seen in this fleet, not the latest SentinelOne release.</div>'
              '<div><b>Needs action.</b> Score of 3 or more: infection or open threat (3 each), not reporting (2 to 3), not in protect mode (2). Watch is 1 to 2: medium/high-risk app, patching, older agent, reboot. Scan age is shown but not scored, because many fleets never rerun full scans.</div>'
              '<div><b>Open threat.</b> Not mitigated, or the incident is not resolved. Threat history covers %s to %s.</div></div>'
              % (a["decommissioned"] + a["uninstalled"], esc(t["first"] or "n/a"), esc(t["last"] or "n/a")))
    app.append(panel("How to read this report", method, 12))
    if t["orphanEndpoints"] or a["duplicateNames"] or p["orphanAgents"]:
        bits = []
        if t["orphanEndpoints"]:
            bits.append("%d endpoint%s in the threat history %s no longer in the agent list: %s." % (len(t["orphanEndpoints"]), "" if len(t["orphanEndpoints"]) == 1 else "s", "is" if len(t["orphanEndpoints"]) == 1 else "are", esc(", ".join(t["orphanEndpoints"][:8]))))
        if a["duplicateNames"]:
            bits.append("%d host name%s appear%s more than once: %s." % (len(a["duplicateNames"]), "" if len(a["duplicateNames"]) == 1 else "s", "s" if len(a["duplicateNames"]) == 1 else "", esc(", ".join(a["duplicateNames"][:8]))))
        if p["orphanAgents"]:
            bits.append("%d agents in the application list are not in the agent list." % p["orphanAgents"])
        app.append(panel("Data notes", '<div class="method"><div>%s</div></div>' % " ".join(bits), 12))

    # --- steps
    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(s.get("tone"), "var(--navy)"), i + 1, esc(s.get("when", "")), esc(s.get("text", ""))) for i, s in enumerate(steps))

    subtitle = args.customer or ", ".join(c for c in f["customers"] if c) or args.account
    snap = (f["snapshot"]["agent"] or [""])[-1]
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "SentinelOne Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong>" % esc(args.account),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "SentinelOne resource report · %s" % esc(subtitle), "footer_data_date": esc(snap),
    }
    for k, v in page.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    with open(os.path.join(args.work, "sentinelone_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    # --- CSVs
    with open(os.path.join(args.work, "endpoints.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["customer", "computer_name", "machine_type", "os", "os_revision", "group", "site", "domain", "last_user", "agent_version",
                    "behind_newest", "reporting", "last_active", "last_active_days", "last_scan_days", "mitigation_mode", "scan_status",
                    "apps_vulnerability", "infected", "active_threats", "reboot_required", "app_installs", "risky_app_installs",
                    "threats", "open_threats", "threats_30d", "score", "status", "reasons"])
        for x in sorted(eps, key=lambda x: (-x["score"], x["computerName"].lower())):
            w.writerow([x["customer"], x["computerName"], x["machineType"], x["os"], x["osRevision"], x["group"], x["site"], x["domain"], "" if args.no_actors else x["user"],
                        x["agentVersion"], x["behindLatest"], x["active"], day(x["lastActive"]), x["lastActiveDays"], x["scanDays"], x["mitigationMode"],
                        x["scanStatus"], x["appsVuln"], x["infected"], x["activeThreats"], x["rebootRequired"], x["apps"], x["highRiskApps"],
                        x["threats"], x["openThreats"], x["recentThreats"], x["score"], x["status"], x["reasons"]])
    with open(os.path.join(args.work, "applications.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["application", "publisher", "risk", "installs", "endpoints", "versions", "windows_legacy_installs"])
        for r in app_rows:
            w.writerow([r["name"], r["publisher"], r["risk"], r["installs"], len(r["hosts"]), "; ".join(sorted(v for v in r["versions"] if v)), r["windowsLegacy"]])
    with open(os.path.join(args.work, "threats.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["created", "endpoint", "threat_name", "classification", "confidence", "analyst_verdict", "mitigation_status", "incident_status", "publisher", "file_verification", "file_path"])
        for tr in sorted(threats, key=lambda x: (x.get("threatInfo") or {}).get("createdAt") or "", reverse=True):
            ti, rt = tr.get("threatInfo") or {}, tr.get("agentRealtimeInfo") or {}
            w.writerow([ti.get("createdAt", ""), rt.get("agentComputerName", ""), ti.get("threatName", ""), ti.get("classification", ""), ti.get("confidenceLevel", ""),
                        verdict_label(ti), ti.get("mitigationStatus", ""), ti.get("incidentStatus", ""), ti.get("publisherName", ""), ti.get("fileVerificationType", ""), ti.get("filePath", "")])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "sentinelone_resource_report_interactive.html"), args, f, eps, app_rows, threats, now)

    print("endpoints %d (reporting %d, not reporting %d) | newest build %s, behind %d" % (n, a["active"], a["inactive"], f["latestVersion"], a["behindLatest"]))
    print("needs action %d, watch %d, healthy %d" % (e["needsAction"], e["watch"], e["healthy"]))
    if f["present"]["application"]:
        print("applications: %d installs, %d distinct, %d risky installs on %d endpoints" % (p["instances"], p["distinct"], p["highRiskInstances"], p["highRiskEndpoints"]))
    else:
        print("applications: no dump, section left out")
    if f["present"]["threat"]:
        print("threats: %d total, %d open (%s to %s)" % (t["total"], t["open"], t["first"], t["last"]))
    else:
        print("threats: no dump, section left out")
    print("wrote: sentinelone_resource_report.html, sentinelone_resource_report_interactive.html, endpoints.csv, applications.csv, threats.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, eps, app_rows, threats, now):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    a, p, t = f["agents"], f["applications"], f["threats"]
    order = ["< 1 day", "1-7 days", "8-30 days", "> 30 days", "unknown"]
    a = dict(a, inactiveBuckets={k: a["inactiveBuckets"][k] for k in order if k in a["inactiveBuckets"]})
    endpoints = []
    for x in eps:
        endpoints.append({
            "name": x["computerName"], "user": "" if args.no_actors else x["user"], "type": x["machineType"], "os": x["os"],
            "agent": x["agentVersion"], "reporting": "Reporting" if x["active"] else "Not reporting",
            "lastActiveDays": x["lastActiveDays"] if not x["active"] and x["lastActiveDays"] is not None else "",
            "mitigation": x["mitigationMode"], "apps": x["apps"], "riskyApps": x["highRiskApps"], "threats": x["threats"],
            "openThreats": x["openThreats"], "score": x["score"], "status": x["status"], "reasons": x["reasons"],
            "patch": "Patch required" if x["appsVuln"] == "patch_required" else "Up to date"})
    apps = []
    for r in app_rows:
        risky = r["risk"] in ("medium", "high", "critical")
        vers = sorted(v for v in r["versions"] if v)
        apps.append({"name": r["name"], "publisher": r["publisher"], "risk": r["risk"].title(), "installs": r["installs"],
                     "endpoints": len(r["hosts"]), "versions": ", ".join(vers[:3]) + (" +%d more" % (len(vers) - 3) if len(vers) > 3 else ""),
                     "hosts": ", ".join(sorted(r["hosts"])[:40]) + (" ..." if len(r["hosts"]) > 40 else "") if risky else ""})
    trows = []
    for tr in threats:
        ti, rt = tr.get("threatInfo") or {}, tr.get("agentRealtimeInfo") or {}
        ms, inc = ti.get("mitigationStatus") or "unknown", ti.get("incidentStatus") or "unknown"
        trows.append({"created": (ti.get("createdAt") or "")[:16].replace("T", " "), "endpoint": rt.get("agentComputerName", ""),
                      "name": ti.get("threatName", ""), "cls": ti.get("classification") or "Unclassified",
                      "confidence": (ti.get("confidenceLevel") or "unknown").title(), "verdict": verdict_label(ti),
                      "mitigation": ms.replace("_", " "), "incident": inc.replace("_", " "), "publisher": ti.get("publisherName", ""),
                      "verification": ti.get("fileVerificationType", ""), "open": "Open" if (ms != "mitigated" or inc != "resolved") else "Closed"})
    sources = []
    for key in RES:
        rows, customers, hours, _ = load(args.dumps, key)
        sources.append({"resource": RES[key], "records": len(rows), "snapshot": ", ".join(hours), "customers": ", ".join(c for c in customers if c)})
    notes = []
    if t["orphanEndpoints"]:
        notes.append("%d endpoint(s) in the threat history are no longer in the agent list: %s." % (len(t["orphanEndpoints"]), ", ".join(t["orphanEndpoints"][:8])))
    if a["duplicateNames"]:
        notes.append("%d host name(s) appear more than once: %s." % (len(a["duplicateNames"]), ", ".join(a["duplicateNames"][:8])))
    if p["orphanAgents"]:
        notes.append("%d agent(s) in the application list are not in the agent list." % p["orphanAgents"])
    if not f["present"]["application"]:
        notes.append("No application dump: the Applications tab is empty.")
    if not f["present"]["threat"]:
        notes.append("No threat dump: the Threats tab is empty.")
    method = [
        "Sources: three SentinelOne resource snapshots, joined on the agent UUID. Decommissioned and uninstalled agents are left out of the endpoint count.",
        "Reporting: an agent is reporting when SentinelOne marks it active. Silent endpoints are bucketed by days since last active; more than %d days is stale." % INACTIVE_STALE_DAYS,
        "Newest build: the highest agent version in this fleet, not the latest SentinelOne release.",
        "Needs action is a score of 3 or more: infection or open threat (3 each), not reporting (2 to 3), not in protect mode (2). Watch is 1 to 2: medium/high-risk app, patching, older agent, reboot.",
        "Open threat: not mitigated, or the incident is not resolved. Scan age is shown but not scored, because many fleets never rerun full scans.",
        "Application counts are installs; one application on 57 endpoints is 57 installs and one distinct application.",
    ]
    if not args.no_actors:
        method.append("This file embeds endpoint names and last logged-in users. Share it only with the tenant's owner, or rebuild with --no-actors.")
    data = {"title": "SentinelOne Resource Report", "account": args.account, "customer": args.customer, "snapshot": (f["snapshot"]["agent"] or [""])[-1],
            "staleDays": INACTIVE_STALE_DAYS, "scanStaleDays": SCAN_STALE_DAYS, "latestVersion": f["latestVersion"], "noActors": args.no_actors,
            "present": f["present"], "agents": a, "applications": p, "threats": t, "endpointSummary": f["endpoints"],
            "endpoints": endpoints, "apps": apps, "threatRows": trows, "sources": sources, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " SentinelOne Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--dumps", required=True)
    r = sub.add_parser("render"); r.add_argument("--dumps", required=True); r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--max-listed", type=int, default=40)
    r.add_argument("--no-actors", action="store_true", help="leave last logged-in user names out of the CSV and the interactive file")
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
