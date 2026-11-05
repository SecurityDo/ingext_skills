#!/usr/bin/env python3
"""Microsoft Defender resource report: enrolment, device health, antivirus, vulnerabilities, configuration and alerts in one page.

Archive only. Reads the archived daily runs of the scheduled FPL report Defender_Resource_Report (the
download_report_archive output for one Fluency / Ingext account), takes the latest completed day and writes
facts.json, four CSVs, a Fluency-branded print HTML page and a self-contained interactive HTML file.
Standard library plus the fluency-report brand kit (charts and PDF). It never queries the tenant.

  defender_resource_report.py check  --archive FILE [FILE ...]
  defender_resource_report.py render --archive FILE [FILE ...] --work DIR --account NAME [--customer TEXT]
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

REPORT = "Defender_Resource_Report"
STALE_DAYS = 7              # not seen for longer than this is "stale"
LONG_STALE_DAYS = 30        # not seen for longer than this is "silent"
MAX_AGE_DAYS = 3            # an archived day older than this is flagged as out of date
LISTED_CAP = 500            # the archive lists at most this many scored hosts
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
AV_MODE = {"0": "Active", "1": "Passive", "2": "Disabled", "3": "Other", "4": "EDR blocked", "5": "Passive audit", "": "No data"}
SEV_ORDER = ["high", "medium", "low", "informational"]
OPEN_STATUS = ("new", "inProgress")
TABLES = ["mderes_summary", "mderes_hosts", "mderes_onboarding", "mderes_seen", "mderes_os", "mderes_groups", "mderes_av", "mderes_vuln_sev",
          "mderes_vuln_cves", "mderes_vuln_software", "mderes_config", "mderes_config_top", "mderes_recs", "mderes_alerts",
          "mderes_alert_titles", "mderes_incidents", "mderes_alert_hosts"]


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
    if not tables.get("mderes_summary"):
        return None
    summ = tables["mderes_summary"][0]
    return {"asOf": str(summ.get("asOf") or rng)[:10], "days": len(cands), "firstDay": cands[0][0], "lastDay": cands[-1][0], "tables": tables}


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


def n_of(r, k):
    try:
        return int(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0


def f_of(r, k):
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def num(n):
    return "{:,}".format(int(n))


# ---------------------------------------------------------------- check
def cmd_check(args):
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM  no completed day with a mderes_summary table in the archive file(s): the report cannot run")
        return 1
    now = dt.datetime.now(dt.timezone.utc)
    s = arc["tables"]["mderes_summary"][0]
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    level, note = "ok", ""
    if not n_of(s, "devices"):
        level, note = "PROBLEM", "the latest day has no devices (no Defender for Endpoint import on the tenant)"
    elif age > MAX_AGE_DAYS:
        level, note = "PROBLEM", "latest archived day is %d days old" % age
    print("%-8s %-28s asOf=%s days_in_file=%d devices=%s onboarded=%s %s" % (level, REPORT, arc["asOf"], arc["days"], s.get("devices"), s.get("onboarded"), note))
    for r in [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]:
        print("         query not available: %s %s" % (r.get("source"), str(r.get("detail") or "")[:100]))
    missing = [t for t in TABLES if t not in arc["tables"]]
    if missing:
        print("         tables absent (an older script version?): %s" % ", ".join(missing))
    return 1 if level == "PROBLEM" else 0


# ---------------------------------------------------------------- analysis
def top(counter, n=10):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def analyse(arc, now):
    tb = arc["tables"]
    s = tb["mderes_summary"][0]
    onboarded = n_of(s, "onboarded")

    eps = []
    for r in tb.get("mderes_hosts", []):
        d = r.get("daysSinceSeen")
        d = None if d in (None, "") or int(d) >= 99999 else int(d)
        eps.append({
            "id": r.get("device_id", ""), "host": r.get("hostname", ""), "os": r.get("os") or "", "osVersion": r.get("osVersion") or "",
            "health": r.get("health") or "", "exposure": r.get("exposure") or "", "risk": r.get("risk") or "", "avMode": r.get("avMode") or "",
            "seenDays": d, "vulnCritical": n_of(r, "vulnCritical"), "vulnHigh": n_of(r, "vulnHigh"), "vulnExploit": n_of(r, "vulnExploit"),
            "openAlerts": n_of(r, "openAlerts"), "highOpen": n_of(r, "highOpen"), "score": n_of(r, "score"),
            "state": r.get("status") or ("Needs action" if n_of(r, "score") >= 3 else "Watch"), "reasons": r.get("reasons") or "",
        })

    seen_order = ["< 1 day", "1-7 days", "8-30 days", "31-90 days", "> 90 days", "unknown"]
    seen = {r.get("bucket"): n_of(r, "devices") for r in tb.get("mderes_seen", [])}
    buckets = collections.OrderedDict((k, seen.get(k, 0)) for k in seen_order)

    enrol = collections.Counter()
    by_status_os = []
    for r in tb.get("mderes_onboarding", []):
        enrol[r.get("onboardingStatus") or "Unknown"] += n_of(r, "devices")
        by_status_os.append({"status": r.get("onboardingStatus") or "Unknown", "os": r.get("osPlatform") or "Unknown", "count": n_of(r, "devices")})

    os_rows = [{"name": ("%s %s" % (r.get("osPlatform") or "Unknown", r.get("version") or "")).strip(), "count": n_of(r, "devices")} for r in tb.get("mderes_os", [])]
    groups = [{"name": r.get("deviceGroup") or "(none)", "count": n_of(r, "devices")} for r in tb.get("mderes_groups", [])]

    av_mode, av_sig, av_eng, av_plat = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for r in tb.get("mderes_av", []):
        c = n_of(r, "devices")
        av_mode[AV_MODE.get(str(r.get("avMode") or ""), "Other")] += c
        av_sig[r.get("signatureUpToDate") or "Unknown"] += c
        av_eng[r.get("engineUpToDate") or "Unknown"] += c
        av_plat[r.get("platformUpToDate") or "Unknown"] += c

    vsev = [{"severity": r.get("severity") or "", "exploit": r.get("exploit") or "", "devices": n_of(r, "devices"), "cves": n_of(r, "cves")} for r in tb.get("mderes_vuln_sev", [])]
    cves = [{"cve": r.get("cveId") or "", "severity": r.get("severity") or "", "exploit": r.get("exploit") or "", "devices": n_of(r, "devices"),
             "cvss": f_of(r, "cvss"), "software": r.get("software") or ""} for r in tb.get("mderes_vuln_cves", [])]
    soft = [{"vendor": r.get("vendor") or "", "software": r.get("software") or "", "cves": n_of(r, "cves"), "devices": n_of(r, "devices")} for r in tb.get("mderes_vuln_software", [])]

    cfg = []
    for r in tb.get("mderes_config", []):
        a, c = n_of(r, "applicable"), n_of(r, "compliant")
        cfg.append({"category": r.get("category") or "", "applicable": a, "compliant": c, "pct": pct(c, a), "devices": n_of(r, "devices")})
    cfg_top = [{"configuration": r.get("configuration") or "", "category": r.get("category") or "", "impact": n_of(r, "impact"), "devices": n_of(r, "devices")} for r in tb.get("mderes_config_top", [])]
    recs = [{"recommendation": r.get("recommendation") or "", "category": r.get("category") or "", "severity": n_of(r, "severity"), "exposed": n_of(r, "exposed"),
             "total": n_of(r, "total"), "publicExploit": bool(r.get("publicExploit")), "remediation": r.get("remediation") or ""} for r in tb.get("mderes_recs", [])]

    # alerts: cross-tab of source, severity, status, category
    a_src, a_sev, a_stat = collections.Counter(), collections.Counter(), collections.Counter()
    mde_total = mde_info_open = mde_open_real = 0
    matrix = []
    for r in tb.get("mderes_alerts", []):
        c = n_of(r, "alerts")
        src, sev, st = r.get("serviceSource") or "unknown", r.get("severity") or "unknown", r.get("status") or "unknown"
        a_src[src] += c; a_sev[sev] += c; a_stat[st] += c
        matrix.append({"source": src, "severity": sev, "status": st, "category": r.get("category") or "", "count": c})
        if src == "microsoftDefenderForEndpoint":
            mde_total += c
            if st in OPEN_STATUS:
                if sev == "informational":
                    mde_info_open += c
                else:
                    mde_open_real += c
    titles = [{"title": r.get("title") or "", "alerts": n_of(r, "alerts"), "open": n_of(r, "open")} for r in tb.get("mderes_alert_titles", [])]
    inc = [{"severity": r.get("severity") or "", "status": r.get("status") or "", "count": n_of(r, "incidents")} for r in tb.get("mderes_incidents", [])]
    inc_total = sum(i["count"] for i in inc)
    inc_open = sum(i["count"] for i in inc if i["status"] in ("active", "inProgress", "new"))
    ahosts = sorted(tb.get("mderes_alert_hosts", []), key=lambda r: (-n_of(r, "highOpen"), -n_of(r, "openAlerts"), str(r.get("hostname") or "").lower()))
    alert_hosts = [{"host": r.get("hostname") or "", "id": r.get("device_id") or "", "os": r.get("os") or "", "alerts": n_of(r, "alerts"), "open": n_of(r, "openAlerts"),
                    "highOpen": n_of(r, "highOpen"), "last": str(r.get("lastAlert") or "")[:10], "top": r.get("topAlert") or ""} for r in ahosts]

    needs, watch, healthy = n_of(s, "needsAction"), n_of(s, "watch"), n_of(s, "healthy")
    facts = {
        "account": "", "generated": now.isoformat(), "asOf": arc["asOf"], "archive": {"days": arc["days"], "firstDay": arc["firstDay"], "lastDay": arc["lastDay"]},
        "fleet": {"devices": n_of(s, "devices"), "onboarded": onboarded, "canBeOnboarded": n_of(s, "canBeOnboarded"), "insufficientInfo": n_of(s, "insufficientInfo"),
                  "unsupported": n_of(s, "unsupported"), "enrolment": top(enrol, 6), "byStatusOs": by_status_os},
        "hosts": {"listed": len(eps), "listedCap": LISTED_CAP, "truncated": len(eps) >= LISTED_CAP and (needs + watch) > len(eps),
                  "sensorInactive": n_of(s, "sensorInactive"), "stale": n_of(s, "stale7d"), "silent": n_of(s, "silent30d"), "seenBuckets": dict(buckets),
                  "exposureHigh": n_of(s, "exposureHigh"), "exposureMedium": n_of(s, "exposureMedium"), "riskHigh": n_of(s, "riskHigh"), "riskMedium": n_of(s, "riskMedium"),
                  "os": os_rows, "groups": groups},
        "av": {"devices": n_of(s, "avDevices"), "active": n_of(s, "avActive"), "passive": n_of(s, "avPassive"), "notActive": n_of(s, "avNotActive"),
               "sigOutdated": n_of(s, "sigOutdated"), "platformOutdated": n_of(s, "platformOutdated"), "mode": top(av_mode), "signature": top(av_sig), "engine": top(av_eng), "platform": top(av_plat)},
        "vuln": {"devices": n_of(s, "vulnDevices"), "criticalDevices": n_of(s, "vulnCriticalDevices"), "exploitDevices": n_of(s, "vulnExploitDevices"), "severity": vsev, "cves": cves, "software": soft},
        "config": {"categories": cfg, "top": cfg_top, "applicable": sum(c["applicable"] for c in cfg), "compliant": sum(c["compliant"] for c in cfg)},
        "recs": {"count": n_of(s, "recommendations"), "publicExploit": n_of(s, "recsPublicExploit"), "top": recs},
        "secureScore": {"score": n_of(s, "secureScore"), "time": str(s.get("secureScoreTime") or "")[:10]},
        "alerts": {"windowDays": n_of(s, "windowDays") or 30, "total": sum(a_src.values()), "bySource": top(a_src), "bySeverity": [{"name": k, "count": a_sev[k]} for k in SEV_ORDER if a_sev.get(k)] +
                  [{"name": k, "count": v} for k, v in a_sev.items() if k not in SEV_ORDER], "byStatus": top(a_stat), "matrix": matrix, "titles": titles,
                  "mdeTotal": mde_total, "mdeInformationalOpen": mde_info_open, "mdeOpenScored": n_of(s, "alertsOpen"), "openHigh": n_of(s, "alertsOpenHigh"),
                  "devicesWithAlerts": n_of(s, "alertDevices"), "devicesOpen": n_of(s, "devicesOpen"), "devicesOpenHigh": n_of(s, "devicesOpenHigh"),
                  "hosts": alert_hosts, "incidents": inc, "incidentsTotal": inc_total, "incidentsOpen": inc_open},
        "endpoints": {"needsAction": needs, "watch": watch, "healthy": healthy},
    }
    return facts, eps


# ---------------------------------------------------------------- narrative
def default_narrative(f):
    fl, h, e, a, v, av = f["fleet"], f["hosts"], f["endpoints"], f["alerts"], f["vuln"], f["av"]
    n = fl["onboarded"]
    s1 = ("<p>Defender for Endpoint knows of <strong>%s devices</strong> (as of %s). <strong>%s are onboarded</strong>; %s more can be onboarded, %s have insufficient information and %s are on an unsupported platform. "
          "Of the onboarded devices, <strong>%s (%s%%) were seen in the last %d days</strong> and <strong>%s have been silent for over %d days</strong>. "
          "<strong>%s devices need action</strong> and %s more are worth watching.</p>"
          % (num(fl["devices"]), esc(f["asOf"]), num(n), num(fl["canBeOnboarded"]), num(fl["insufficientInfo"]), num(fl["unsupported"]),
             num(n - h["stale"]), pct(n - h["stale"], n), STALE_DAYS, num(h["silent"]), LONG_STALE_DAYS, num(e["needsAction"]), num(e["watch"])))
    cfgpct = pct(f["config"]["compliant"], f["config"]["applicable"])
    s2 = ("<p>Antivirus is active on <strong>%s of %s</strong> devices that report its health; %s are disabled or blocked by EDR. "
          "<strong>%s devices carry known vulnerabilities</strong> and <strong>%s of them have a High or Critical CVE with a verified exploit</strong>. "
          "Secure configuration checks are <strong>%s%% compliant</strong>, and Secure Score is %s points.</p>"
          % (num(av["active"]), num(av["devices"]), num(av["notActive"]), num(v["devices"]), num(v["exploitDevices"]), cfgpct, num(f["secureScore"]["score"])))
    s3 = ("<p>In the %d-day window Defender raised <strong>%s alerts</strong>; <strong>%s open endpoint alert%s</strong> above informational severity, %s high. "
          "%s incidents are open.</p>" % (a["windowDays"], num(a["total"]), num(a["mdeOpenScored"]), "" if a["mdeOpenScored"] == 1 else "s", num(a["openHigh"]), num(a["incidentsOpen"])))
    return [s1, s2, s3]


def default_steps(f):
    h, a, v, av, fl = f["hosts"], f["alerts"], f["vuln"], f["av"], f["fleet"]
    s = []
    if a["devicesOpenHigh"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Triage the %d open high severity endpoint alerts on %d devices in the Defender portal." % (a["openHigh"], a["devicesOpenHigh"])})
    elif a["mdeOpenScored"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Review the %d open endpoint alerts above informational severity (%s)." % (a["mdeOpenScored"], ", ".join(x["host"] for x in a["hosts"][:3]) or "see the table")})
    if av["notActive"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Find out why %d devices have antivirus disabled or EDR-blocked, and restore active protection where it is not intended." % av["notActive"]})
    if v["exploitDevices"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Patch the browsers and operating systems behind the exploitable CVEs first (%s) and start with the devices that carry the most." % (", ".join(c["software"] for c in v["cves"][:3]) or "see the table")})
    if h["silent"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Find out why %d onboarded devices have been silent for over %d days: retired, powered off, or the sensor is damaged. Offboard retired devices." % (h["silent"], LONG_STALE_DAYS)})
    if fl["canBeOnboarded"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Onboard the %s devices that Defender can see but that are not onboarded." % num(fl["canBeOnboarded"])})
    cfgtop = f["config"]["top"]
    if cfgtop:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Enable the most common failing settings, for example \"%s\" (%s devices)." % (cfgtop[0]["configuration"], num(cfgtop[0]["devices"]))})
    s.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare onboarding, exposure and Secure Score with the previous quarter."})
    return s[:6]


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
    body = "".join("<tr%s>%s</tr>" % (' class="%s"' % r[1] if isinstance(r, tuple) else "", "".join(r[0] if isinstance(r, tuple) else r)) for r in rows)
    return '<table class="%s">%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, cg, th, body)


def td(x, wrap=False):
    return '<td%s>%s</td>' % (' class="wrap"' if wrap else "", esc(x))


def tdn(x):
    return '<td class="num">%s</td>' % (num(x) if isinstance(x, int) else esc(x))


def chip(text, color):
    return '<span class="st"><i style="background:%s"></i>%s</span>' % (color, esc(text))


EXPLOIT = {"ExploitIsVerified": "Verified exploit", "ExploitIsInKit": "In exploit kit", "ExploitIsPublic": "Public exploit", "NoExploit": "No known exploit"}
STATUS_COLOR = {"Needs action": "#b3242e", "Watch": "#a06c00", "Healthy": "#175d9a"}


def kpi(label, value, color, note=""):
    return ('<div class="kpi"><div class="kpi-value %s">%s</div><div class="kpi-label">%s</div>%s</div>'
            % (color, esc(value), esc(label), '<div class="kpi-note">%s</div>' % esc(note) if note else ""))


# ---------------------------------------------------------------- render
def coverage_notes(arc, f, now):
    notes = []
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    notes.append("Built from the archived %s for %s (latest completed day in the file; the file holds %d day%s, %s to %s). Each archived day is a snapshot of the Defender console, so days are never added together."
                 % (REPORT, arc["asOf"], arc["days"], "" if arc["days"] == 1 else "s", arc["firstDay"] or "?", arc["lastDay"] or "?"))
    if age > MAX_AGE_DAYS:
        notes.append("The latest archived day is %d days old, so these figures are not current. Check the scheduled report." % age)
    if f["hosts"]["truncated"]:
        notes.append("The archive lists the %d highest-scoring devices; %d devices need action or watch, so the device table and hosts.csv are cut at %d. The counts above cover every onboarded device."
                     % (f["hosts"]["listed"], f["endpoints"]["needsAction"] + f["endpoints"]["watch"], f["hosts"]["listedCap"]))
    a = f["alerts"]
    if a["mdeInformationalOpen"]:
        t = max(a["titles"], key=lambda x: x["open"], default=None)
        one = (" %s of them are one alert, \"%s\"." % (num(t["open"]), t["title"])) if t and t["open"] >= 0.5 * a["mdeInformationalOpen"] else ""
        notes.append("%s of the %s endpoint alerts in the window are informational and still open.%s Informational alerts do not count toward device scores or the open-alert figures." % (num(a["mdeInformationalOpen"]), num(a["mdeTotal"]), one))
    bad = [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]
    if bad:
        notes.append("These queries did not run on the archived day and their panels are empty: %s." % ", ".join(str(r.get("source")) for r in bad))
    notes.append("Vulnerability counts are per device and CVE (a CVE on many devices is counted once per device). Secure configuration compliance counts only checks that apply to the device.")
    notes.append("Not in the archive, so not shown: installed software lists, per-CVE device lists, last logged-in user and tags.")
    return notes


def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM: no completed archived day with a mderes_summary table; nothing to report", file=sys.stderr)
        return 1
    f, eps = analyse(arc, now)
    if not f["fleet"]["devices"]:
        print("PROBLEM: the archived day has no Defender devices; nothing to report", file=sys.stderr)
        return 1
    f["account"] = args.account
    fl, h, e, av, v, cfg, al = f["fleet"], f["hosts"], f["endpoints"], f["av"], f["vuln"], f["config"], f["alerts"]
    n = fl["onboarded"]
    notes = coverage_notes(arc, f, now)
    f["notes"] = notes
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}

    kp = [
        kpi("Onboarded devices", num(n), "navy", "of %s known to Defender" % num(fl["devices"])),
        kpi("Need action", num(e["needsAction"]), "red" if e["needsAction"] else "green", "%s more on watch" % num(e["watch"])),
        kpi("Secure Score", num(f["secureScore"]["score"]), "blue", "points, %s" % f["secureScore"]["time"]),
        kpi("High exposure", num(h["exposureHigh"]), "amber" if h["exposureHigh"] else "green", "%s%% of onboarded" % pct(h["exposureHigh"], n)),
        kpi("Exploitable CVEs", num(v["exploitDevices"]), "red" if v["exploitDevices"] else "green", "devices with a verified exploit"),
        kpi("Open alerts", num(al["mdeOpenScored"]), "red" if al["openHigh"] else "amber" if al["mdeOpenScored"] else "green", "%d high, informational excluded" % al["openHigh"]),
    ]

    g = []
    colors = ["#111111", "#175d9a", "#a06c00", "#b3242e", "#6b6b6b", "#bdbdbd"]
    # enrolment
    enr = [("Onboarded", n, "#175d9a"), ("Can be onboarded", fl["canBeOnboarded"], "#175d9a"), ("Insufficient information", fl["insufficientInfo"], "#a06c00"), ("Unsupported", fl["unsupported"], "#8a8a8a")]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * c / fl["devices"], col, esc(k), c) for k, c, col in enr if c)
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %s</span>' % (col, esc(k), num(c)) for k, c, col in enr if c)
    mix = [{"name": "%s / %s" % (x["status"], x["os"]), "count": x["count"]} for x in fl["byStatusOs"][:6]]
    g.append(panel("Enrolment coverage", stack + legend + '<div style="height:8px"></div>' + bars(mix, fl["devices"], "var(--navy)"), 6, "%s devices known to Defender" % num(fl["devices"])))
    segs = [(k, c, col) for (k, c), col in zip(h["seenBuckets"].items(), colors) if c]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * c / n, col, esc(k), c) for k, c, col in segs)
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %s</span>' % (col, esc(k), num(c)) for k, c, col in segs)
    g.append(panel("Last seen", stack + legend + '<div style="height:8px"></div>' + bars(h["os"][:6], n, "var(--navy)"), 6, "onboarded devices, with operating systems"))
    # antivirus
    avrows = [[td("Antivirus mode: " + x["name"]), tdn(x["count"])] for x in av["mode"]]
    avrows += [[td("Signatures out of date"), tdn(av["sigOutdated"])], [td("Engine or platform out of date"), tdn(av["platformOutdated"])]]
    g.append(panel("Antivirus health", table(["Check", "Devices"], avrows, ["75%", "25%"]), 6, "devices reporting antivirus health"))
    expo = [{"name": "High exposure", "count": h["exposureHigh"]}, {"name": "Medium exposure", "count": h["exposureMedium"]},
            {"name": "High risk score", "count": h["riskHigh"]}, {"name": "Medium risk score", "count": h["riskMedium"]}, {"name": "Sensor inactive", "count": h["sensorInactive"]}]
    g.append(panel("Exposure and risk", bars(expo, n, "var(--amber)"), 6, "onboarded devices"))
    # vulnerabilities
    sev_rows = [[td(x["severity"] if x["severity"] not in ("", "null", "None") else "Unknown"), td(EXPLOIT.get(x["exploit"], x["exploit"]), True), tdn(x["cves"]), tdn(x["devices"])] for x in sorted(v["severity"], key=lambda x: -x["devices"])][:8]
    g.append(panel("Vulnerabilities by severity and exploit", table(["Severity", "Exploit", "CVEs", "Devices"], sev_rows, ["22%", "34%", "20%", "24%"]), 6,
                   "%s devices carry CVEs, %s with a critical one" % (num(v["devices"]), num(v["criticalDevices"]))))
    sw = [[td(x["vendor"], True), td(x["software"], True), tdn(x["cves"]), tdn(x["devices"])] for x in v["software"][:8]]
    g.append(panel("Software with the most critical CVEs", table(["Vendor", "Software", "CVEs", "Devices"], sw, ["26%", "34%", "18%", "22%"]) if sw else '<p class="panel-subtitle">None.</p>', 6, "top 8"))
    cv = [[td(c["cve"], True), td(c["severity"]), tdn(c["devices"]), td("%.1f" % c["cvss"]), td(c["software"], True)] for c in v["cves"][:8]]
    g.append(panel("Top exploitable CVEs", table(["CVE", "Severity", "Devices", "CVSS", "Software"], cv, ["20%", "12%", "12%", "10%", "46%"]) if cv else '<p class="panel-subtitle">No exploitable CVEs.</p>', 12, "High or Critical with a verified exploit"))
    # config
    cb = [{"name": "%s  (%s%%)" % (c["category"], c["pct"]), "count": c["compliant"]} for c in cfg["categories"]]
    crow = [[td(c["category"], True), tdn(c["applicable"]), tdn(c["compliant"]), td("%s%%" % c["pct"])] for c in cfg["categories"]]
    g.append(panel("Secure configuration by category", table(["Category", "Checks", "Compliant", "Rate"], crow, ["30%", "22%", "28%", "20%"]), 6,
                   "%s%% of applicable checks compliant overall" % pct(cfg["compliant"], cfg["applicable"])))
    ft = [[td(c["configuration"], True), tdn(c["devices"]), tdn(c["impact"])] for c in cfg["top"][:6]]
    g.append(panel("Most common failing settings", table(["Setting", "Devices", "Impact"], ft, ["58%", "22%", "20%"]) if ft else '<p class="panel-subtitle">None.</p>', 6, "weighted by devices and impact"))
    rr = [[td(r["recommendation"], True), td(r["severity"]), tdn(r["exposed"]), td("yes" if r["publicExploit"] else "no")] for r in f["recs"]["top"][:6]]
    g.append(panel("Top security recommendations", table(["Recommendation", "Severity", "Exposed", "Public exploit"], rr, ["56%", "12%", "16%", "16%"]) if rr else '<p class="panel-subtitle">None.</p>', 12,
                   "%s active, %s with a public exploit" % (num(f["recs"]["count"]), num(f["recs"]["publicExploit"]))))
    # alerts
    g.append(panel("Alerts by severity and status", bars(al["bySeverity"], al["total"] or 1, "var(--red)", "No alerts in the window.") + '<div style="height:12px"></div>' + bars(al["byStatus"], al["total"] or 1, "var(--amber)"), 6,
                   "%d-day window, all Defender products" % al["windowDays"]))
    src_names = {"microsoftDefenderForEndpoint": "Defender for Endpoint", "microsoftDefenderForOffice365": "Defender for Office 365", "dataLossPrevention": "Data loss prevention"}
    srcb = [{"name": src_names.get(x["name"], x["name"]), "count": x["count"]} for x in al["bySource"]]
    inc = [{"name": "%s, %s" % (x["severity"], x["status"]), "count": x["count"]} for x in al["incidents"][:5]]
    g.append(panel("Alerts by product and incidents", bars(srcb, al["total"] or 1, "var(--navy)") + '<div style="height:12px"></div>' + bars(inc, al["incidentsTotal"] or 1, "var(--blue)"), 6,
                   "%s incidents, %s open" % (num(al["incidentsTotal"]), num(al["incidentsOpen"]))))
    tt = [[td(x["title"], True), tdn(x["alerts"]), tdn(x["open"])] for x in al["titles"][:6]]
    g.append(panel("Most common endpoint alerts", table(["Alert", "Alerts", "Open"], tt, ["62%", "19%", "19%"]) if tt else '<p class="panel-subtitle">None.</p>', 6, "Defender for Endpoint, informational included"))
    ah = [[td(x["host"], True), tdn(x["open"]), td(x["top"], True)] for x in al["hosts"][:10]]
    g.append(panel("Devices with open alerts", table(["Device", "Open", "Most common"], ah, ["38%", "16%", "46%"]) if ah else '<p class="panel-subtitle">No device has an open alert above informational severity.</p>', 6,
                   "%s devices; informational alerts excluded" % num(al["devicesOpen"])))

    attn = sorted(eps, key=lambda x: (-x["score"], x["host"].lower()))
    cap = args.max_listed
    rows = [([('<td class="host wrap">%s</td>' % esc(x["host"])), td(x["os"]), td("" if x["seenDays"] is None else x["seenDays"]),
              '<td>%s</td>' % chip(x["state"], STATUS_COLOR.get(x["state"], "#8a8a8a")), td(x["reasons"], True)], "") for x in attn[:cap]]
    note = "" if len(attn) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(attn))
    app = [panel("Devices needing attention", table(["Device", "OS", "Days", "Status", "Why"], rows, ["26%", "12%", "6%", "17%", "39%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No device has an open issue.</p>', 12, "%d of %s%s" % (len(attn), num(e["needsAction"] + e["watch"]), note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Source.</b> The archived daily run of the scheduled report %s for %s. Each day is a snapshot of the Defender console at that run, and the latest completed day is used. Scores cover onboarded devices only.</div>'
              '<div><b>Last seen.</b> Days from the device\'s last seen time to the end of the run window. More than %d days is stale; more than %d days is silent.</div>'
              '<div><b>Needs action.</b> Score of 3 or more. Points: not seen for over 30 days 3 (inactive sensor or over 7 days 2); risk score High 3, Medium 2, Low 1; exposure level High 1; antivirus disabled or EDR-blocked 2; antivirus signatures out of date 2; engine or platform out of date 1; 10 or more exploitable High or Critical CVEs 2; 100 or more critical CVEs 1; an open high severity alert 3 and any other open alert above informational 1. Watch is 1 to 2.</div>'
              '<div><b>Vulnerabilities.</b> Per device, distinct CVEs. Exploitable means a High or Critical CVE with a verified exploit or an exploit kit.</div>'
              '<div><b>Secure configuration.</b> Only checks that apply to the device count. Compliance is compliant checks divided by applicable checks.</div>'
              '<div><b>Alerts.</b> Defender alerts created in the %d-day window, each counted once at its latest state. Informational alerts are listed but are not scored or counted as open.</div></div>'
              % (REPORT, esc(f["asOf"]), STALE_DAYS, LONG_STALE_DAYS, al["windowDays"]))
    app.append(panel("How to read this report", method, 12))
    app.append(panel("Data notes", '<div class="method">%s</div>' % "".join("<div>%s</div>" % esc(x) for x in notes), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(s.get("tone"), "var(--navy)"), i + 1, esc(s.get("when", "")), esc(s.get("text", ""))) for i, s in enumerate(steps))

    subtitle = args.customer or args.account
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "Microsoft Defender Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong> · as of <strong>%s</strong>" % (esc(args.account), esc(f["asOf"])),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "Defender resource report · %s" % esc(subtitle), "footer_data_date": esc(f["asOf"]),
    }
    for k, val in page.items():
        tpl = tpl.replace("{{%s}}" % k, val)
    with open(os.path.join(args.work, "defender_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    def out_csv(name, header, rows_):
        with open(os.path.join(args.work, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header + ["as_of"])
            for r in rows_:
                w.writerow(list(r) + [f["asOf"]])

    out_csv("hosts.csv", ["hostname", "device_id", "os", "os_version", "days_since_seen", "health", "exposure", "risk_score", "antivirus_mode", "critical_cves", "high_cves",
                          "exploitable_cves", "open_alerts", "open_high_alerts", "score", "state", "reasons"],
            [[x["host"], x["id"], x["os"], x["osVersion"], "" if x["seenDays"] is None else x["seenDays"], x["health"], x["exposure"], x["risk"], x["avMode"], x["vulnCritical"], x["vulnHigh"],
              x["vulnExploit"], x["openAlerts"], x["highOpen"], x["score"], x["state"], x["reasons"]] for x in attn])
    out_csv("alerts.csv", ["kind", "name", "device_id", "severity", "status", "category", "alerts", "open", "high_open", "last_alert"],
            [["device", x["host"], x["id"], "", "", "", x["alerts"], x["open"], x["highOpen"], x["last"]] for x in al["hosts"]] +
            [["title", x["title"], "", "", "", "", x["alerts"], x["open"], "", ""] for x in al["titles"]] +
            [["matrix", m["source"], "", m["severity"], m["status"], m["category"], m["count"], "", "", ""] for m in al["matrix"]] +
            [["incident", "", "", x["severity"], x["status"], "", x["count"], "", "", ""] for x in al["incidents"]])
    out_csv("vulnerabilities.csv", ["kind", "name", "severity", "exploit", "devices", "cves", "cvss", "software"],
            [["severity", "", x["severity"], x["exploit"], x["devices"], x["cves"], "", ""] for x in v["severity"]] +
            [["cve", c["cve"], c["severity"], c["exploit"], c["devices"], "", c["cvss"], c["software"]] for c in v["cves"]] +
            [["software", x["vendor"], "Critical", "", x["devices"], x["cves"], "", x["software"]] for x in v["software"]])
    out_csv("config.csv", ["kind", "name", "category", "applicable", "compliant", "compliance_pct", "devices", "impact"],
            [["category", c["category"], c["category"], c["applicable"], c["compliant"], c["pct"], c["devices"], ""] for c in cfg["categories"]] +
            [["failing", c["configuration"], c["category"], "", "", "", c["devices"], c["impact"]] for c in cfg["top"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "defender_resource_report_interactive.html"), args, f, eps, arc, notes)

    print("as of %s | devices %s, onboarded %s (can be onboarded %s, insufficient info %s, unsupported %s)" % (f["asOf"], num(fl["devices"]), num(n), num(fl["canBeOnboarded"]), num(fl["insufficientInfo"]), num(fl["unsupported"])))
    print("needs action %d, watch %d, healthy %d (device table lists %d)" % (e["needsAction"], e["watch"], e["healthy"], len(eps)))
    print("silent over %d days: %d (over %d: %d) | antivirus active %d of %d, not active %d" % (STALE_DAYS, h["stale"], LONG_STALE_DAYS, h["silent"], av["active"], av["devices"], av["notActive"]))
    print("vulnerable devices %d, exploitable %d | secure score %d | open scored alerts %d (high %d)" % (v["devices"], v["exploitDevices"], f["secureScore"]["score"], al["mdeOpenScored"], al["openHigh"]))
    print("wrote: defender_resource_report.html, defender_resource_report_interactive.html, hosts.csv, alerts.csv, vulnerabilities.csv, config.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, eps, arc, notes):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    rows = []
    for x in eps:
        rows.append({"name": x["host"], "os": x["os"], "osVersion": x["osVersion"], "health": x["health"], "exposure": x["exposure"] or "None", "risk": x["risk"] or "None",
                     "av": x["avMode"], "seenDays": x["seenDays"] if x["seenDays"] is not None else "", "checkin": "Silent" if (x["seenDays"] or 0) > STALE_DAYS else "Seen",
                     "exploit": x["vulnExploit"], "critical": x["vulnCritical"], "openAlerts": x["openAlerts"], "highOpen": x["highOpen"],
                     "score": x["score"], "state": x["state"], "reasons": x["reasons"]})
    srcs = [{"source": r.get("source"), "status": r.get("status"), "detail": str(r.get("detail") or "")[:160]} for r in arc["tables"].get("sources", [])]
    method = [
        "Source: the archived daily run of the scheduled report %s; the latest completed day (%s) is used. Each day is a snapshot of the Defender console. Scores cover onboarded devices only." % (REPORT, f["asOf"]),
        "Last seen: days from the last seen time to the end of the run window. More than %d days is stale; more than %d days is silent." % (STALE_DAYS, LONG_STALE_DAYS),
        "Needs action is a score of 3 or more. Points: not seen over 30 days 3 (inactive sensor or over 7 days 2); risk score High 3, Medium 2, Low 1; exposure High 1; antivirus disabled or EDR-blocked 2; signatures out of date 2; engine or platform out of date 1; 10 or more exploitable CVEs 2; 100 or more critical CVEs 1; open high alert 3, other open alert above informational 1.",
        "Watch is 1 to 2. Healthy (0) devices are counted but not listed.",
        "Vulnerabilities are distinct CVEs per device. Exploitable means High or Critical with a verified exploit or exploit kit.",
        "Secure configuration compliance is compliant checks divided by applicable checks.",
        "Alerts are counted once at their latest state. Informational alerts are shown but are not scored or counted as open.",
    ]
    data = {"title": "Microsoft Defender Resource Report", "account": args.account, "customer": args.customer, "snapshot": f["asOf"], "staleDays": STALE_DAYS, "silentDays": LONG_STALE_DAYS,
            "fleet": f["fleet"], "hosts": f["hosts"], "av": f["av"], "vuln": f["vuln"], "config": f["config"], "recs": f["recs"], "secureScore": f["secureScore"], "alerts": f["alerts"],
            "summary": f["endpoints"], "rows": rows, "sources": srcs, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " Defender Resource Report")).replace("{{data}}", blob)
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
