#!/usr/bin/env python3
"""CrowdStrike Falcon resource report: sensor health, versions, policies and detections in one page.

Archive only. Reads the archived daily runs of the scheduled FPL report CrowdStrike_Resource_Report (the
download_report_archive output for one Fluency / Ingext account), takes the latest completed day and writes
facts.json, three CSVs, a Fluency-branded print HTML page and a self-contained interactive HTML file.
Standard library only. It never queries the tenant.

  falcon_resource_report.py check  --archive FILE [FILE ...]
  falcon_resource_report.py render --archive FILE [FILE ...] --work DIR --account NAME [--customer TEXT]
"""
import argparse, collections, csv, datetime as dt, html, json, os, shutil, sys

REPORT = "CrowdStrike_Resource_Report"
STALE_DAYS = 7              # no check-in for longer than this is "stale"
LONG_STALE_DAYS = 30        # no check-in for longer than this is "silent"
SENSOR_WINDOW = 3           # the newest N major.minor sensor releases in the fleet are "current" (N, N-1, N-2)
TREND_WEEKS = 12
MAX_AGE_DAYS = 3            # an archived day older than this is flagged as out of date
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")


# ---------------------------------------------------------------- loading
def load_archive(paths):
    """Read download_report_archive output (one or more files). Returns
    {"asOf", "days", "lastDay", "firstDay", "tables": {name: [row dicts]}} for the latest completed day, or None."""
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
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]))
    rng, _, res = cands[-1]
    tables = {}
    for o in res.get("objects") or []:
        tb = o.get("table") or {}
        tables[o.get("name")] = tb.get("rows") or []
    if not tables.get("falres_summary"):
        return None
    summ = tables["falres_summary"][0]
    return {"asOf": str(summ.get("asOf") or rng)[:10], "days": len(cands), "firstDay": cands[0][0], "lastDay": cands[-1][0], "tables": tables}


def ts(value):
    """Parse an ISO-8601 timestamp (fractions and Z allowed) to an aware datetime, or None."""
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


def minor(version):
    k = vkey(version)
    return (k[0], k[1]) if len(k) >= 2 else None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def day(d):
    return d.strftime("%Y-%m-%d") if d else ""


def plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")




# ---------------------------------------------------------------- check
def cmd_check(args):
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM  no completed day with a falres_summary table in the archive file(s): the report cannot run")
        return 1
    now = dt.datetime.now(dt.timezone.utc)
    s = arc["tables"]["falres_summary"][0]
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    level, note = "ok", ""
    if not int(s.get("hostCount") or 0):
        level, note = "PROBLEM", "the latest day has no hosts (no Falcon resource import on the tenant)"
    elif age > MAX_AGE_DAYS:
        level, note = "PROBLEM", "latest archived day is %d days old" % age
    srcs = [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]
    print("%-8s %-28s asOf=%s days_in_file=%d hosts=%s %s" % (level, REPORT, arc["asOf"], arc["days"], s.get("hostCount"), note))
    for r in srcs:
        print("         query not available: %s %s" % (r.get("source"), str(r.get("detail") or "")[:100]))
    missing = [t for t in ("falres_seen", "falres_versions", "falres_platforms", "falres_policies", "falres_weekly") if not arc["tables"].get(t)]
    if missing:
        print("         tables empty or absent (an older script version?): %s" % ", ".join(missing))
    return 1 if level == "PROBLEM" else 0


# ---------------------------------------------------------------- analysis
def top(counter, n=10):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def n_of(r, k):
    try:
        return int(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0


def analyse(arc, now):
    tb = arc["tables"]
    s = tb["falres_summary"][0]
    total = n_of(s, "hostCount")
    cur_rel = [x.strip() for x in str(s.get("currentReleases") or "").split(",") if x.strip()]
    vers = tb.get("falres_versions", [])
    current_ver = {v.get("agentVersion"): bool(v.get("isCurrent")) for v in vers}
    latest = str(s.get("newestVersion") or "")

    eps = []
    for r in tb.get("falres_hosts", []):
        ver = r.get("agentVersion") or ""
        d = r.get("daysSinceSeen")
        d = None if d in (None, "") or int(d) >= 99999 else int(d)
        e = {
            "id": r.get("device_id", ""), "host": r.get("hostname", ""), "platform": r.get("platform") or "Unknown", "type": r.get("role") or "Unknown",
            "os": r.get("os") or "", "version": ver, "behind": bool(ver) and current_ver.get(ver) is False, "lastSeenDays": d,
            "score": n_of(r, "score"), "state": r.get("status") or ("Needs action" if n_of(r, "score") >= 3 else "Watch"), "reasons": r.get("reasons") or "",
            "alerts": n_of(r, "alerts"), "openAlerts": n_of(r, "openAlerts"), "highOpen": n_of(r, "highOpen"), "lastAlert": "", "topAlert": "",
        }
        eps.append(e)
    by_id = {e["id"]: e for e in eps}
    for r in tb.get("falres_alert_hosts", []):
        e = by_id.get(r.get("device_id"))
        if e:
            e["lastAlert"] = str(r.get("lastAlert") or "")[:10]
            e["topAlert"] = r.get("topDetection") or ""

    seen_order = ["< 1 day", "1-7 days", "8-30 days", "31-90 days", "> 90 days", "unknown"]
    seen = {r.get("bucket"): n_of(r, "hosts") for r in tb.get("falres_seen", [])}
    buckets = collections.OrderedDict((k, seen.get(k, 0)) for k in seen_order)

    plat = collections.Counter(); types = collections.Counter(); mix = []
    for r in tb.get("falres_platforms", []):
        plat[r.get("platform") or "Unknown"] += n_of(r, "hosts")
        types[r.get("role") or "Unknown"] += n_of(r, "hosts")
        mix.append({"platform": r.get("platform") or "Unknown", "type": r.get("role") or "Unknown", "count": n_of(r, "hosts")})

    weeks = []
    wk = {}
    for r in tb.get("falres_weekly", []):
        try:
            d0 = dt.date.fromisoformat(str(r.get("week"))[:10])
        except ValueError:
            continue
        wk[d0] = wk.get(d0, 0) + n_of(r, "hosts")
    if wk:
        last, first = max(wk), min(wk)
        cur = first
        while cur <= last:
            weeks.append({"week": cur.isoformat(), "count": wk.get(cur, 0)})
            cur += dt.timedelta(days=7)
        weeks = weeks[-TREND_WEEKS:]

    cover = [{"policy": r.get("policy"), "assigned": n_of(r, "assigned"), "missing": n_of(r, "missing"), "notApplied": n_of(r, "notApplied")}
             for r in tb.get("falres_policies", [])]
    listed_cap = 500
    facts = {
        "account": "", "generated": now.isoformat(), "asOf": arc["asOf"], "archive": {"days": arc["days"], "firstDay": arc["firstDay"], "lastDay": arc["lastDay"]},
        "latestVersion": latest, "currentReleases": cur_rel,
        "hosts": {
            "total": total, "listed": len(eps), "listedCap": listed_cap, "truncated": len(eps) >= listed_cap and (n_of(s, "needsAction") + n_of(s, "watch")) > len(eps),
            "stale": n_of(s, "stale7d"), "silent": n_of(s, "silent30d"), "seenBuckets": dict(buckets),
            "rfm": n_of(s, "rfm"), "contained": n_of(s, "contained"), "notProvisioned": n_of(s, "notProvisioned"), "noPrevention": n_of(s, "noPrevention"),
            "preventionNotApplied": n_of(s, "preventionNotApplied"), "uninstallOff": n_of(s, "uninstallOff"), "uninstallMaintenance": n_of(s, "uninstallMaintenance"),
            "safeMode": n_of(s, "safeMode"), "behind": n_of(s, "behind"), "onCurrent": n_of(s, "onCurrent"), "rebootOld": n_of(s, "rebootOld"),
            "versions": [{"name": v.get("agentVersion") or "unknown", "count": n_of(v, "hosts")} for v in vers[:12]], "versionCount": len(vers),
            "platforms": top(plat), "types": top(types), "mix": mix, "weekly": weeks,
        },
        "policies": {"coverage": cover},
        "endpoints": {"needsAction": n_of(s, "needsAction"), "watch": n_of(s, "watch"), "healthy": n_of(s, "healthy")},
    }
    facts["alerts"] = alert_facts(arc, eps)
    return facts, eps


def alert_facts(arc, eps):
    """Detection facts from the falres_alert_* tables of the archived day."""
    tb = arc["tables"]
    summ = tb["falres_summary"][0]
    if not (tb.get("falres_alert_sev") or n_of(summ, "alerts") or tb.get("falres_alert_hosts")):
        return None
    ORDER = ["Critical", "High", "Medium", "Low", "Lead"]
    sev, status = collections.Counter(), collections.Counter()
    for r in tb.get("falres_alert_sev", []):
        sev[r.get("severity") or "unknown"] += n_of(r, "alerts")
    for r in tb.get("falres_alert_status", []):
        status[r.get("status") or "unknown"] += n_of(r, "alerts")
    tactic = collections.Counter({(r.get("tactic") or "unknown"): n_of(r, "alerts") for r in tb.get("falres_alert_tactics", [])})
    names = collections.Counter({(r.get("name") or "unknown"): n_of(r, "alerts") for r in tb.get("falres_alert_names", [])})
    hosts = sorted(tb.get("falres_alert_hosts", []), key=lambda r: (-n_of(r, "highOpen"), -n_of(r, "openAlerts"), str(r.get("hostname") or "").lower()))
    return {
        "windowDays": n_of(summ, "windowDays") or 30, "total": n_of(summ, "alerts") or sum(sev.values()), "open": n_of(summ, "alertsOpen"),
        "openHigh": n_of(summ, "alertsOpenHigh"), "leads": sev.get("Lead", 0), "leadsOpen": n_of(summ, "leadsOpen"),
        "hostsWithAlerts": n_of(summ, "hostsWithAlerts"), "hostsOpenHigh": n_of(summ, "hostsOpenHigh"), "hostsOpen": n_of(summ, "hostsOpen"),
        "severity": [{"name": k, "count": v} for k, v in sorted(sev.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else 9)],
        "status": top(status), "tactics": top(tactic, 8), "detections": top(names, 8),
        "topHosts": [{"host": r.get("hostname") or "", "id": r.get("device_id") or "", "type": r.get("role") or "", "alerts": n_of(r, "alerts"), "open": n_of(r, "openAlerts"),
                      "highOpen": n_of(r, "highOpen"), "last": str(r.get("lastAlert") or "")[:10], "top": r.get("topDetection") or ""} for r in hosts[:25]],
        "other": [{"product": o.get("product") or "", "type": o.get("type") or "", "alerts": n_of(o, "alerts"), "hosts": n_of(o, "hosts"), "open": n_of(o, "open")}
                  for o in tb.get("falres_alert_other", [])],
    }


# ---------------------------------------------------------------- narrative
def default_narrative(f):
    h, e = f["hosts"], f["endpoints"]
    n = h["total"]
    s1 = ("<p>Falcon manages <strong>%d hosts</strong> (as of %s). <strong>%d (%s%%) checked in within the last %d days</strong>; <strong>%d have been silent "
          "for longer</strong>, %d of them for over %d days. <strong>%d hosts (%s%%) run one of the newest %d sensor releases</strong> (%s); %d are older. "
          "<strong>%d hosts need action</strong> and %d more are worth watching.</p>"
          % (n, esc(f["asOf"]), n - h["stale"], pct(n - h["stale"], n), STALE_DAYS, h["stale"], h["silent"], LONG_STALE_DAYS, h["onCurrent"], pct(h["onCurrent"], n),
             SENSOR_WINDOW, esc(", ".join(f["currentReleases"])), h["behind"], e["needsAction"], e["watch"]))
    gaps = h["rfm"] + h["notProvisioned"] + h["noPrevention"] + h["preventionNotApplied"]
    bits = []
    if gaps:
        bits.append("<strong>%d hosts have a protection gap</strong>: %d in reduced functionality mode, %d not provisioned, %d without a prevention policy and %d with a prevention policy not yet applied."
                    % (gaps, h["rfm"], h["notProvisioned"], h["noPrevention"], h["preventionNotApplied"]))
    else:
        bits.append("Every host has a provisioned sensor with an applied prevention policy and none is in reduced functionality mode.")
    if h["contained"]:
        bits.append("<strong>%d %s currently contained</strong> (network isolation)." % (h["contained"], plural(h["contained"], "host is", "hosts are")))
    if h["uninstallOff"]:
        bits.append("Uninstall protection is not enabled on <strong>%d</strong> Windows or Mac hosts." % h["uninstallOff"])
    al = f.get("alerts")
    out = [s1, "<p>" + " ".join(bits) + "</p>"]
    if al:
        out.append("<p>In the %d-day window Falcon raised <strong>%d endpoint detections and leads</strong> on %d hosts. <strong>%d are still open</strong>, %d of them high or critical on %d hosts.</p>"
                   % (al["windowDays"], al["total"], al["hostsWithAlerts"], al["open"], al["openHigh"], al["hostsOpenHigh"]))
    return out


def default_steps(f):
    h = f["hosts"]
    s = []
    al = f.get("alerts")
    if al and al["hostsOpenHigh"]:
        s.append({"when": "Today", "tone": "urgent", "text": "Triage the %d open high or critical detections on %d hosts in the Falcon console, starting with %s." % (al["openHigh"], al["hostsOpenHigh"], ", ".join(x["host"] for x in al["topHosts"][:3] if x["highOpen"]) or "the hosts listed below")})
    if h["rfm"] or h["notProvisioned"] or h["noPrevention"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Fix the %d hosts with a protection gap: restore full functionality, provision the sensor or assign a prevention policy." % (h["rfm"] + h["notProvisioned"] + h["noPrevention"])})
    if h["contained"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Confirm the %d contained %s still need isolation, and lift containment where the investigation is closed." % (h["contained"], plural(h["contained"], "host"))})
    if h["silent"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Find out why %d hosts have been silent for over %d days: retired, powered off, or the sensor is damaged. Remove retired hosts from Falcon." % (h["silent"], LONG_STALE_DAYS)})
    if h["uninstallOff"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Turn uninstall protection on for the %d Windows and Mac hosts where it is off or in maintenance mode." % h["uninstallOff"]})
    if h["behind"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Move the %d hosts on older sensor releases to a current one through the sensor update policy." % h["behind"]})
    s.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare check-in, sensor and policy counts with the previous quarter."})
    return s[:6]


# ---------------------------------------------------------------- html helpers
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


def trend_svg(weeks):
    if not weeks or not any(x["count"] for x in weeks):
        return '<p class="panel-subtitle">No hosts enrolled in this period.</p>'
    w, h, pad = 520, 170, 26
    mx = max(x["count"] for x in weeks) or 1
    bw = (w - 2 * pad) / len(weeks)
    out = ['<svg class="svg-chart" viewBox="0 0 %d %d" role="img" aria-label="New hosts per week">' % (w, h)]
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
def coverage_notes(arc, f, now):
    notes = []
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    notes.append("Built from the archived %s for %s (latest completed day in the file; the file holds %d day%s, %s to %s). Each archived day is a snapshot of the console, so days are never added together."
                 % (REPORT, arc["asOf"], arc["days"], "" if arc["days"] == 1 else "s", arc["firstDay"] or "?", arc["lastDay"] or "?"))
    if age > MAX_AGE_DAYS:
        notes.append("The latest archived day is %d days old, so these figures are not current. Check the scheduled report." % age)
    if f["hosts"]["truncated"]:
        notes.append("The archive lists the %d highest-scoring hosts; %d hosts need action or watch, so the host table and hosts.csv are cut at %d. The counts above cover every host."
                     % (f["hosts"]["listed"], f["endpoints"]["needsAction"] + f["endpoints"]["watch"], f["hosts"]["listedCap"]))
    bad = [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]
    if bad:
        notes.append("These queries did not run on the archived day and their panels are empty: %s." % ", ".join(str(r.get("source")) for r in bad))
    notes.append("Not in the archive, so not shown: operating system and domain breakdowns, criticality, tags, last logged-in user, duplicate host names and per-policy ids.")
    return notes


def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM: no completed archived day with a falres_summary table; nothing to report", file=sys.stderr)
        return 1
    f, eps = analyse(arc, now)
    if not f["hosts"]["total"]:
        print("PROBLEM: the archived day has no Falcon hosts; nothing to report", file=sys.stderr)
        return 1
    f["account"] = args.account
    h, e, pol = f["hosts"], f["endpoints"], f["policies"]
    n = h["total"]
    notes = coverage_notes(arc, f, now)
    f["notes"] = notes
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}
    gaps = h["rfm"] + h["notProvisioned"] + h["noPrevention"]

    kp = [
        kpi("Hosts", "{:,}".format(n), "navy", "%s platforms" % len(h["platforms"])),
        kpi("Silent over %d days" % STALE_DAYS, "{:,}".format(h["stale"]), "red" if h["silent"] else "amber" if h["stale"] else "green", "%d over %d days" % (h["silent"], LONG_STALE_DAYS)),
        kpi("On a current sensor", "%s%%" % pct(h["onCurrent"], n), "green" if not h["behind"] else "amber", "newest %d releases" % SENSOR_WINDOW),
        kpi("Need action", "{:,}".format(e["needsAction"]), "red" if e["needsAction"] else "green", "%d more on watch" % e["watch"]),
        kpi("Protection gaps", gaps, "red" if gaps else "green", "RFM, unprovisioned, no policy"),
        kpi("Contained", h["contained"], "amber" if h["contained"] else "green", "network isolation"),
    ]
    al = f.get("alerts")
    if al:
        kp[5] = kpi("Open detections", "{:,}".format(al["open"]), "red" if al["openHigh"] else "amber" if al["open"] else "green",
                    "%d high or critical, last %dd" % (al["openHigh"], al["windowDays"]))

    g = []
    colors = ["#15803D", "#1D4ED8", "#B45309", "#B91C1C", "#7f1d1d", "#64748B"]
    segs = [(k, v, c) for (k, v), c in zip(h["seenBuckets"].items(), colors) if v]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * v / n, c, esc(k), v) for k, v, c in segs)
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %s</span>' % (c, esc(k), "{:,}".format(v)) for k, v, c in segs)
    g.append(panel("Last check-in", stack + legend + bars(h["platforms"], n, "var(--navy)"), 6, "%s hosts" % "{:,}".format(n)))
    vrows = [{"name": v["name"] + ("  (newest)" if v["name"] == f["latestVersion"] else ""), "count": v["count"]} for v in h["versions"]]
    g.append(panel("Sensor versions", bars(vrows, n), 6, "%d versions; current releases %s" % (h["versionCount"], ", ".join(f["currentReleases"]))))
    mixrows = [{"name": "%s / %s" % (m["platform"], m["type"]), "count": m["count"]} for m in h["mix"]]
    g.append(panel("Platforms and host roles", bars(mixrows, n, "var(--navy)"), 6, "hosts"))
    prot = [("Reduced functionality mode", h["rfm"]), ("Sensor not provisioned", h["notProvisioned"]), ("No prevention policy assigned", h["noPrevention"]),
            ("Prevention policy not applied", h["preventionNotApplied"]), ("Contained (network isolation)", h["contained"]),
            ("Uninstall protection off (Windows, Mac)", h["uninstallOff"]), ("  of which maintenance mode", h["uninstallMaintenance"]),
            ("Running in safe mode", h["safeMode"]), ("Last reboot over 90 days ago (info only)", h["rebootOld"])]
    g.append(panel("Protection health", table(["Check", "Hosts"], [[td(k), '<td class="num">%d</td>' % v] for k, v in prot], ["75%", "25%"]), 6, "hosts affected"))
    rows = [[td(c["policy"]), '<td class="num">%s</td>' % "{:,}".format(c["assigned"]), '<td class="num">%s</td>' % "{:,}".format(c["missing"]), '<td class="num">%d</td>' % c["notApplied"]] for c in pol["coverage"]]
    g.append(panel("Policy coverage", table(["Policy type", "Assigned", "Missing", "Not applied"], rows, ["40%", "20%", "18%", "22%"]), 6, "policy types, hosts"))
    g.append(panel("New hosts per week", trend_svg(h["weekly"]), 6, "first seen by Falcon, last %d weeks" % TREND_WEEKS))

    if al:
        g.append(panel("Detections by severity", bars(al["severity"], al["total"] or 1, "var(--red)", "No detections in the window.") +
                       '<div style="height:12px"></div>' + bars(al["status"], al["total"] or 1, "var(--amber)"), 6,
                       "%d-day window; leads count as their own row" % al["windowDays"]))
        g.append(panel("Top tactics and detections", bars(al["tactics"], max(1, sum(t["count"] for t in al["tactics"])), "var(--navy)", "No endpoint detections.") +
                       '<div style="height:12px"></div>' + bars(al["detections"], max(1, sum(t["count"] for t in al["detections"])), "var(--blue)"), 6, "endpoint detections"))
        trs = [[('<td class="host">%s</td>' % esc(x["host"])), td(x["type"]), '<td class="num">%d</td>' % x["alerts"], '<td class="num">%d</td>' % x["open"],
                '<td class="num">%d</td>' % x["highOpen"], td(x["top"], True)] for x in al["topHosts"][:10]]
        g.append(panel("Hosts with open detections", table(["Host", "Role", "Alerts", "Open", "High open", "Most common"], trs, ["20%", "11%", "10%", "9%", "12%", "38%"])
                       if trs else '<p class="panel-subtitle">No host has an open detection.</p>', 12, "%d hosts; top 10 by open high or critical" % al["hostsOpen"]))
        if al["other"]:
            orow = [[td(o["product"]), td(o["type"]), '<td class="num">%s</td>' % "{:,}".format(o["alerts"]), '<td class="num">%s</td>' % "{:,}".format(o["hosts"]),
                     '<td class="num">%s</td>' % "{:,}".format(o["open"])] for o in al["other"]]
            g.append(panel("Other Falcon alert products", table(["Product", "Type", "Alerts", "Hosts", "Open"], orow, ["26%", "34%", "13%", "13%", "14%"]), 12,
                           "identity, data protection and cloud alerts; context only, not in host scores"))

    attn = sorted(eps, key=lambda x: (-x["score"], x["host"].lower()))
    cap = args.max_listed
    rows = [([('<td class="host">%s</td>' % esc(x["host"])), td(x["type"]), td(x["os"]), td(x["version"]),
              '<td>%s</td>' % chip(x["state"], STATUS_COLOR.get(x["state"], "#64748B")), td(x["reasons"], True)], "") for x in attn[:cap]]
    note = "" if len(attn) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(attn))
    app = [panel("Hosts needing attention", table(["Host", "Role", "OS", "Sensor", "Status", "Why"], rows, ["16%", "10%", "17%", "11%", "13%", "33%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No host has an open issue.</p>', 12, "%d of %s%s" % (len(attn), "{:,}".format(e["needsAction"] + e["watch"]), note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Source.</b> The archived daily run of the scheduled report %s for %s. Each day is a snapshot of the Falcon console at that run, and the latest completed day is used.</div>'
              '<div><b>Last check-in.</b> Days from the host\'s last_seen to the end of the run window. More than %d days is stale; more than %d days is silent.</div>'
              '<div><b>Current sensor.</b> A host is current when its sensor major.minor release is one of the newest %d releases found in this fleet (N, N-1, N-2), not the latest Falcon release.</div>'
              '<div><b>Needs action.</b> Score of 3 or more: reduced functionality mode, not provisioned or no prevention policy (3 each), silent over %d days (3), prevention not applied, silent %d to %d days, contained or uninstall protection in maintenance mode (2 each). Watch is 1 to 2: uninstall protection off, older sensor, safe mode.</div>'
              '<div><b>Detections.</b> FalconAlert rows created in the %d-day window. Endpoint detections (product epp) and automated leads count; identity, data protection and cloud alerts are listed for context only. An open high or critical detection scores 3; any other open detection or lead scores 1.</div>'
              '<div><b>Not scored.</b> Last reboot age is shown for context.</div></div>'
              % (REPORT, esc(f["asOf"]), STALE_DAYS, LONG_STALE_DAYS, SENSOR_WINDOW, LONG_STALE_DAYS, STALE_DAYS + 1, LONG_STALE_DAYS, al["windowDays"] if al else 30))
    app.append(panel("How to read this report", method, 12))
    app.append(panel("Data notes", '<div class="method">%s</div>' % "".join("<div>%s</div>" % esc(x) for x in notes), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(s.get("tone"), "var(--navy)"), i + 1, esc(s.get("when", "")), esc(s.get("text", ""))) for i, s in enumerate(steps))

    subtitle = args.customer or args.account
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "CrowdStrike Falcon Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong> · as of <strong>%s</strong>" % (esc(args.account), esc(f["asOf"])),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "Falcon resource report · %s" % esc(subtitle), "footer_data_date": esc(f["asOf"]),
    }
    for k, v in page.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    with open(os.path.join(args.work, "falcon_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    with open(os.path.join(args.work, "hosts.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hostname", "device_id", "platform", "role", "os", "sensor_version", "behind_current_releases", "days_since_seen",
                    "alerts_%dd" % (al["windowDays"] if al else 30), "open_alerts", "open_high_or_critical", "score", "state", "reasons", "as_of"])
        for x in attn:
            w.writerow([x["host"], x["id"], x["platform"], x["type"], x["os"], x["version"], x["behind"], "" if x["lastSeenDays"] is None else x["lastSeenDays"],
                        x["alerts"], x["openAlerts"], x["highOpen"], x["score"], x["state"], x["reasons"], f["asOf"]])
    if al:
        with open(os.path.join(args.work, "alerts.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["hostname", "device_id", "role", "alerts", "open_alerts", "open_high_or_critical", "last_alert", "most_common_detection", "as_of"])
            for x in al["topHosts"]:
                w.writerow([x["host"], x["id"], x["type"], x["alerts"], x["open"], x["highOpen"], x["last"], x["top"], f["asOf"]])
    with open(os.path.join(args.work, "policies.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["policy_type", "hosts_assigned", "hosts_not_assigned", "hosts_not_applied", "as_of"])
        for c in pol["coverage"]:
            w.writerow([c["policy"], c["assigned"], c["missing"], c["notApplied"], f["asOf"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "falcon_resource_report_interactive.html"), args, f, eps, arc, notes, now)

    print("as of %s | hosts %d | silent over %d days: %d (over %d: %d) | current sensor %d, older %d" % (f["asOf"], n, STALE_DAYS, h["stale"], LONG_STALE_DAYS, h["silent"], h["onCurrent"], h["behind"]))
    print("needs action %d, watch %d, healthy %d (host table lists %d)" % (e["needsAction"], e["watch"], e["healthy"], len(eps)))
    print("protection gaps: rfm %d, not provisioned %d, no prevention %d, prevention not applied %d, contained %d" % (h["rfm"], h["notProvisioned"], h["noPrevention"], h["preventionNotApplied"], h["contained"]))
    if al:
        print("detections (%dd): %d, open %d (high or critical %d) on %d hosts" % (al["windowDays"], al["total"], al["open"], al["openHigh"], al["hostsOpen"]))
    print("wrote: falcon_resource_report.html, falcon_resource_report_interactive.html, hosts.csv, alerts.csv, policies.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, eps, arc, notes, now):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    hosts = []
    for x in eps:
        hosts.append({
            "name": x["host"], "platform": x["platform"], "role": x["type"], "os": x["os"],
            "sensor": x["version"], "release": ("current" if not x["behind"] else "older") if x["version"] else "",
            "seenDays": x["lastSeenDays"] if x["lastSeenDays"] is not None else "", "checkin": "Silent" if (x["lastSeenDays"] or 0) > STALE_DAYS else "Checking in",
            "alerts": x["alerts"], "openAlerts": x["openAlerts"], "highOpen": x["highOpen"], "lastAlert": x["lastAlert"], "topAlert": x["topAlert"],
            "score": x["score"], "state": x["state"], "reasons": x["reasons"]})
    srcs = [{"source": r.get("source"), "status": r.get("status"), "detail": str(r.get("detail") or "")[:160]} for r in arc["tables"].get("sources", [])]
    method = [
        "Source: the archived daily run of the scheduled report %s; the latest completed day (%s) is used. Each day is a snapshot of the Falcon console." % (REPORT, f["asOf"]),
        "Last check-in: days from last_seen to the end of the run window. More than %d days is stale; more than %d days is silent." % (STALE_DAYS, LONG_STALE_DAYS),
        "Current sensor: the host's major.minor release is one of the newest %d releases found in this fleet (N, N-1, N-2), not the latest Falcon release." % SENSOR_WINDOW,
        "Needs action is a score of 3 or more: reduced functionality mode, not provisioned or no prevention policy (3 each), silent over %d days (3), prevention not applied, silent %d to %d days, contained or uninstall protection in maintenance mode (2 each)." % (LONG_STALE_DAYS, STALE_DAYS + 1, LONG_STALE_DAYS),
        "Watch is 1 to 2: uninstall protection off on Windows or Mac, older sensor, safe mode. Last reboot age is shown for context only.",
        "Detections: FalconAlert rows created in the %d-day window. Endpoint detections and automated leads count; an open high or critical detection scores 3, any other open detection or lead scores 1. Identity, data protection and cloud alerts are context only." % ((f.get("alerts") or {}).get("windowDays", 30)),
    ]
    data = {"title": "CrowdStrike Falcon Resource Report", "account": args.account, "customer": args.customer, "snapshot": f["asOf"],
            "staleDays": STALE_DAYS, "silentDays": LONG_STALE_DAYS, "window": SENSOR_WINDOW, "latestVersion": f["latestVersion"], "currentReleases": f["currentReleases"],
            "hosts": f["hosts"], "policies": f["policies"], "summary": f["endpoints"], "alerts": f.get("alerts"), "rows": hosts,
            "sources": srcs, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " Falcon Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r = sub.add_parser("render"); r.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--max-listed", type=int, default=40)
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
