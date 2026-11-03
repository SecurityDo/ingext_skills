#!/usr/bin/env python3
"""CrowdStrike Falcon resource report: sensor health, versions, policies and posture in one page.

Reads the falconAgent resource dump (Falcon Hosts API snapshot) for one Fluency / Ingext account and
writes facts.json, two CSVs, a Fluency-branded print HTML page and a self-contained interactive HTML
file. Standard library only.

  falcon_resource_report.py check  --dumps DIR
  falcon_resource_report.py render --dumps DIR --work DIR --account NAME [--customer TEXT]

The dump lives at DIR/falconAgent/<customer>.jsonl.gz.
"""
import argparse, collections, csv, datetime as dt, glob, gzip, html, json, os, shutil, sys

RES = "falconAgent"
STALE_DAYS = 7              # no check-in for longer than this is "stale"
LONG_STALE_DAYS = 30        # no check-in for longer than this is "silent"
REBOOT_DAYS = 90            # last reboot older than this is shown (info only, not scored)
SENSOR_WINDOW = 3           # the newest N major.minor sensor releases in the fleet are "current" (N, N-1, N-2)
NEW_HOST_DAYS = 30
TREND_WEEKS = 12
CORE_POLICIES = ["prevention", "sensor_update", "firewall", "device_control", "remote_response", "content-update",
                 "global_config", "host-retention", "exposure-management", "sca", "it-automation", "logscale-collector"]
ALERT_DAYS = 30             # alert window; the alert extract is built over this many days
HIGH_SEV = ("High", "Critical")
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")


# ---------------------------------------------------------------- loading
def load(dumps):
    """Return (rows, customers, snapshot_hours, files)."""
    rows, customers, hours, files = [], set(), set(), []
    for path in sorted(glob.glob(os.path.join(dumps, RES, "*.jsonl.gz"))):
        files.append(os.path.basename(path))
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                body = rec.get("@" + RES)
                if not isinstance(body, dict):
                    continue
                body["_customer"] = rec.get("@customer", "")
                body["_ts"] = rec.get("@timestamp")
                rows.append(body)
                customers.add(rec.get("@customer", ""))
                if rec.get("@dayIndex"):
                    hours.add(rec["@dayIndex"])
    return rows, sorted(customers), sorted(hours), files


def _tables(path):
    """Tables of a kql_search result saved as JSON: {name: [row dicts]} (raw response, a Tables list, or a list of row objects)."""
    if not path or not os.path.exists(path):
        return {}
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, dict):
        data = data.get("Tables") or data.get("tables") or []
    if isinstance(data, list) and data and isinstance(data[0], dict) and "Columns" not in data[0] and "columns" not in data[0]:
        return {"PrimaryResult": [r for r in data if isinstance(r, dict)]}
    out = {}
    for tb in data:
        cols = [c.get("ColumnName") or c.get("name") for c in tb.get("Columns") or tb.get("columns") or []]
        out[tb.get("TableName") or tb.get("name") or "PrimaryResult"] = [dict(zip(cols, row)) for row in tb.get("Rows") or tb.get("rows") or []]
    return out


def load_search(hosts_path, facets_path, other_path, window_days):
    """Build the same tables the archived report carries from the three kql_search queries in SKILL.md step 2b."""
    hosts = _tables(hosts_path).get("PrimaryResult", [])
    facets = _tables(facets_path)
    other = _tables(other_path).get("PrimaryResult", [])
    if not hosts and not facets:
        return None

    def facet(col, key, name):
        rows = facets.get("Facet_" + col, [])
        return [{name: r.get(col), "alerts": int(r.get("count_") or 0)} for r in rows if r.get(col) not in (None, "")]
    n = lambda r, k: int(r.get(k) or 0)
    tbl = {
        "falres_summary": [{"windowDays": window_days, "alertsOpen": sum(n(r, "openAlerts") for r in hosts),
                            "alertsOpenHigh": sum(n(r, "highOpen") for r in hosts), "leadsOpen": sum(n(r, "leadsOpen") for r in hosts),
                            "hostsWithAlerts": len(hosts), "hostsOpenHigh": sum(1 for r in hosts if n(r, "highOpen")),
                            "hostsOpen": sum(1 for r in hosts if n(r, "openAlerts")), "asOf": ""}],
        "falres_hosts": [{"device_id": r.get("agent_id"), "alerts": n(r, "alerts"), "openAlerts": n(r, "openAlerts"), "highOpen": n(r, "highOpen")} for r in hosts],
        "falres_alert_hosts": [{"device_id": r.get("agent_id"), "lastAlert": r.get("lastAlert") or "", "topDetection": r.get("topDetection") or ""} for r in hosts],
        "falres_alert_sev": facet("severity", "severity", "severity"),
        "falres_alert_status": facet("status", "status", "status"),
        "falres_alert_tactics": facet("tacticName", "tactic", "tactic"),
        "falres_alert_names": facet("detection", "name", "name")[:10],
        "falres_alert_other": other,
    }
    return {"asOf": "", "days": 0, "tables": tbl, "search": True}


def load_archive(path):
    """Read the archived CrowdStrike_Resource_Report (download_report_archive output, or a run_report result).
    Returns {"asOf", "days", "tables": {name: [row dicts]}} for the latest completed day, or None."""
    if not path or not os.path.exists(path):
        return None
    data = json.load(open(path, encoding="utf-8"))
    cands = []
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
    if "falres_summary" not in tables or not tables["falres_summary"]:
        return None
    summ = tables["falres_summary"][0]
    return {"asOf": str(summ.get("asOf") or rng)[:10], "days": len(cands), "tables": tables}


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
    now = dt.datetime.now(dt.timezone.utc)
    rows, customers, hours, files = load(args.dumps)
    newest = max((r["_ts"] for r in rows if r.get("_ts")), default=None)
    age_h = (now.timestamp() - newest / 1000.0) / 3600.0 if newest else None
    level, note = "ok", ""
    if not rows:
        level, note = "PROBLEM", "no records: the report cannot run"
    elif age_h is not None and age_h > 48:
        level, note = "PROBLEM", "snapshot is %.0f hours old" % age_h
    print("%-8s %-12s records=%-7d customers=%-2d snapshot=%s files=%s %s"
          % (level, RES, len(rows), len(customers), ",".join(hours) or "-", len(files), note))
    if rows:
        ids = [r.get("device_id") for r in rows]
        print("hosts: %d records, %d distinct device ids, %d with a last_seen, %d with a prevention policy"
              % (len(rows), len(set(ids)), sum(1 for r in rows if ts(r.get("last_seen"))),
                 sum(1 for r in rows if (r.get("device_policies") or {}).get("prevention"))))
    return 1 if level == "PROBLEM" else 0


# ---------------------------------------------------------------- analysis
def top(counter, n=10):
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def policy_of(r, name):
    p = (r.get("device_policies") or {}).get(name)
    return p if isinstance(p, dict) else None


def analyse(dumps, now, archive=None):
    rows, customers, hours, _ = load(dumps)
    # a host appears once per device_id; keep the newest record if a snapshot repeats one
    by_id = {}
    for r in rows:
        k = r.get("device_id") or r.get("hostname")
        if k not in by_id or (r.get("_ts") or 0) >= (by_id[k].get("_ts") or 0):
            by_id[k] = r
    hosts = list(by_id.values())
    minors = sorted({minor(h.get("agent_version")) for h in hosts if minor(h.get("agent_version"))}, reverse=True)
    rank = {m: i for i, m in enumerate(minors)}
    latest = max((h.get("agent_version") for h in hosts if h.get("agent_version")), key=vkey, default="")

    eps = []
    for h in hosts:
        last = ts(h.get("last_seen")); first = ts(h.get("first_seen")); boot = ts(h.get("last_reboot"))
        prev = policy_of(h, "prevention"); su = policy_of(h, "sensor_update")
        plat = h.get("platform_name") or "Unknown"
        uninstall = (su or {}).get("uninstall_protection") or ""
        m = minor(h.get("agent_version"))
        e = {
            "customer": h.get("_customer", ""), "id": h.get("device_id", ""), "host": h.get("hostname", ""),
            "platform": plat, "type": h.get("product_type_desc") or "Unknown", "os": h.get("os_product_name") or h.get("os_version") or "",
            "build": h.get("os_build") or "", "domain": h.get("machine_domain") or "", "site": h.get("site_name") or "",
            "user": h.get("last_login_user") or "", "version": h.get("agent_version") or "",
            "behind": m is not None and rank.get(m, 0) >= SENSOR_WINDOW, "versionRank": rank.get(m) if m else None,
            "status": h.get("status") or "", "provision": h.get("provision_status") or "",
            "rfm": (h.get("reduced_functionality_mode") or "").lower() == "yes",
            "safeMode": (h.get("safe_mode") or "").lower() in ("yes", "true"),
            "rtr": h.get("rtr_state") or "", "criticality": h.get("criticality") or "unassigned",
            "tags": len(h.get("tags") or []), "groups": len(h.get("groups") or []),
            "lastSeen": last, "lastSeenDays": (now - last).days if last else None,
            "firstSeen": first, "lastReboot": boot, "rebootDays": (now - boot).days if boot else None,
            "prevention": bool(prev), "preventionApplied": bool(prev and prev.get("applied") is not False),
            "preventionPolicy": (prev or {}).get("policy_id", ""), "uninstall": uninstall,
            "policies": sorted((h.get("device_policies") or {}).keys()),
            "notApplied": sorted(k for k, v in (h.get("device_policies") or {}).items() if isinstance(v, dict) and v.get("applied") is False),
        }
        e["contained"] = e["status"] not in ("", "normal")
        e["notProvisioned"] = e["provision"] == "NotProvisioned"
        e["uninstallOff"] = plat in ("Windows", "Mac") and bool(su) and uninstall != "ENABLED"
        eps.append(e)

    ids = {e["id"] for e in eps}
    per = collections.defaultdict(lambda: {"n": 0, "open": 0, "highOpen": 0, "leadsOpen": 0, "last": "", "names": collections.Counter()})
    unmatched = 0
    if archive:
        # per-host counts come from the archived day: falres_hosts (scored hosts) and falres_alert_hosts (last alert, top detection)
        tb = archive["tables"]
        for r in tb.get("falres_hosts", []):
            aid = r.get("device_id") or ""
            if not (int(r.get("alerts") or 0) or int(r.get("openAlerts") or 0)):
                continue
            if aid not in ids:
                unmatched += int(r.get("alerts") or 0)
                continue
            d = per[aid]
            d["n"], d["open"], d["highOpen"] = int(r.get("alerts") or 0), int(r.get("openAlerts") or 0), int(r.get("highOpen") or 0)
        for r in tb.get("falres_alert_hosts", []):
            aid = r.get("device_id") or ""
            if aid in per:
                d = per[aid]
                d["last"] = str(r.get("lastAlert") or "")
                if r.get("topDetection"):
                    d["names"][r["topDetection"]] += max(1, d["n"])
    for e in eps:
        d = per.get(e["id"])
        e["alerts"] = d["n"] if d else 0
        e["openAlerts"] = d["open"] if d else 0
        e["highOpen"] = d["highOpen"] if d else 0
        e["leadsOpen"] = d["leadsOpen"] if d else 0
        e["lastAlert"] = (d["last"][:10] if d else "")
        e["topAlert"] = d["names"].most_common(1)[0][0] if d and d["names"] else ""

    for e in eps:
        why, total = [], [0]

        def add(n, text):
            total[0] += n
            why.append(text)
        d = e["lastSeenDays"]
        if e["rfm"]:
            add(3, "reduced functionality mode")
        if e["notProvisioned"]:
            add(3, "sensor not provisioned")
        if not e["prevention"]:
            add(3, "no prevention policy assigned")
        elif not e["preventionApplied"]:
            add(2, "prevention policy not applied")
        if d is not None and d > LONG_STALE_DAYS:
            add(3, "no check-in for %d days" % d)
        elif d is not None and d > STALE_DAYS:
            add(2, "no check-in for %d days" % d)
        elif d is None:
            add(2, "never checked in")
        if e["contained"]:
            add(2, "host is contained (%s)" % e["status"].replace("_", " "))
        if e["uninstall"] == "MAINTENANCE_MODE":
            add(2, "uninstall protection in maintenance mode")
        elif e["uninstallOff"]:
            add(1, "uninstall protection not enabled")
        if e["behind"]:
            add(1, "sensor %s is older than the newest %d releases" % (e["version"], SENSOR_WINDOW))
        if e["safeMode"]:
            add(1, "running in safe mode")
        if e["highOpen"]:
            add(3, "%d open high or critical detection%s" % (e["highOpen"], "" if e["highOpen"] == 1 else "s"))
        elif e["openAlerts"]:
            add(1, "%d open detection%s or lead%s" % (e["openAlerts"], "" if e["openAlerts"] == 1 else "s", "" if e["openAlerts"] == 1 else "s"))
        e["score"] = total[0]
        e["reasons"] = "; ".join(why)
        e["state"] = "Needs action" if e["score"] >= 3 else ("Watch" if e["score"] else "Healthy")

    n = len(eps)
    buckets = collections.OrderedDict((k, 0) for k in ["< 1 day", "1-7 days", "8-30 days", "31-90 days", "> 90 days", "unknown"])
    for e in eps:
        d = e["lastSeenDays"]
        buckets["unknown" if d is None else "< 1 day" if d < 1 else "1-7 days" if d <= 7 else "8-30 days" if d <= 30 else "31-90 days" if d <= 90 else "> 90 days"] += 1

    weekly = collections.Counter()
    for e in eps:
        if e["firstSeen"]:
            weekly[(e["firstSeen"] - dt.timedelta(days=e["firstSeen"].weekday())).date()] += 1
    weeks = []
    if weekly:
        end = (now - dt.timedelta(days=now.weekday())).date()
        for i in range(TREND_WEEKS):
            w = end - dt.timedelta(weeks=TREND_WEEKS - 1 - i)
            weeks.append({"week": w.isoformat(), "count": weekly.get(w, 0)})

    cover = []
    for name in CORE_POLICIES:
        have = sum(1 for e in eps if name in e["policies"])
        cover.append({"policy": name, "assigned": have, "missing": n - have, "notApplied": sum(1 for e in eps if name in e["notApplied"])})
    prev_ids = collections.Counter(e["preventionPolicy"] for e in eps if e["preventionPolicy"])
    seen = collections.Counter((e["host"] or "").lower() for e in eps)
    dup = sorted({e["host"] for e in eps if e["host"] and seen[e["host"].lower()] > 1})
    crit = [e for e in eps if e["criticality"] in ("critical", "high")]
    mix = collections.Counter((e["platform"], e["type"]) for e in eps)

    facts = {
        "account": "", "generated": now.isoformat(), "snapshot": hours, "customers": customers,
        "latestVersion": latest, "currentReleases": ["%d.%d" % m for m in minors[:SENSOR_WINDOW]],
        "hosts": {
            "records": len(rows), "total": n, "duplicateIds": len(rows) - n, "duplicateNames": dup,
            "stale": sum(1 for e in eps if e["lastSeenDays"] is not None and e["lastSeenDays"] > STALE_DAYS),
            "silent": sum(1 for e in eps if e["lastSeenDays"] is not None and e["lastSeenDays"] > LONG_STALE_DAYS),
            "seenBuckets": dict(buckets),
            "rfm": sum(1 for e in eps if e["rfm"]), "contained": sum(1 for e in eps if e["contained"]),
            "notProvisioned": sum(1 for e in eps if e["notProvisioned"]), "noPrevention": sum(1 for e in eps if not e["prevention"]),
            "preventionNotApplied": sum(1 for e in eps if e["prevention"] and not e["preventionApplied"]),
            "uninstallOff": sum(1 for e in eps if e["uninstallOff"]),
            "uninstallMaintenance": sum(1 for e in eps if e["uninstall"] == "MAINTENANCE_MODE"),
            "safeMode": sum(1 for e in eps if e["safeMode"]), "behind": sum(1 for e in eps if e["behind"]),
            "onCurrent": sum(1 for e in eps if e["version"] and not e["behind"]),
            "rebootOld": sum(1 for e in eps if e["rebootDays"] is not None and e["rebootDays"] > REBOOT_DAYS),
            "newHosts": sum(1 for e in eps if e["firstSeen"] and (now - e["firstSeen"]).days <= NEW_HOST_DAYS),
            "versions": top(collections.Counter(e["version"] or "unknown" for e in eps), 12),
            "versionCount": len({e["version"] for e in eps}),
            "platforms": top(collections.Counter(e["platform"] for e in eps)),
            "types": top(collections.Counter(e["type"] for e in eps)),
            "mix": [{"platform": k[0], "type": k[1], "count": v} for k, v in mix.most_common()],
            "os": top(collections.Counter(e["os"] or "unknown" for e in eps), 10),
            "criticality": top(collections.Counter(e["criticality"] for e in eps)),
            "domains": top(collections.Counter(e["domain"] or "(none)" for e in eps), 8),
            "sites": top(collections.Counter(e["site"] or "(none)" for e in eps), 8),
            "uninstall": top(collections.Counter(e["uninstall"] or "(none)" for e in eps)),
            "tagged": sum(1 for e in eps if e["tags"]), "weekly": weeks,
            "criticalNeedsAction": sum(1 for e in crit if e["state"] == "Needs action"),
            "criticalTotal": len(crit),
        },
        "policies": {"coverage": cover, "preventionPolicies": len(prev_ids), "preventionTop": top(prev_ids, 8)},
        "endpoints": {"needsAction": sum(1 for e in eps if e["state"] == "Needs action"),
                      "watch": sum(1 for e in eps if e["state"] == "Watch"),
                      "healthy": sum(1 for e in eps if e["state"] == "Healthy")},
    }
    facts["alerts"] = alert_facts(archive, eps, unmatched)
    return facts, eps


def alert_facts(arc, eps, unmatched):
    """Detection facts from the falres_alert_* tables (the archived report, or the same queries run by kql_search)."""
    if not arc:
        return None
    tb = arc["tables"]
    summ = (tb.get("falres_summary") or [{}])[0]
    ORDER = ["Critical", "High", "Medium", "Low", "Lead"]
    sev, status = collections.Counter(), collections.Counter()
    open_high = leads = 0
    for r in tb.get("falres_alert_sev", []):
        n = int(r.get("alerts") or 0)
        s = r.get("severity") or "unknown"
        sev[s] += n
        if "status" in r:                      # rows of an older archive carry severity and status together
            status[r.get("status") or "unknown"] += n
        if s == "Lead":
            leads += n
    for r in tb.get("falres_alert_status", []):
        status[r.get("status") or "unknown"] += int(r.get("alerts") or 0)
    tactic = collections.Counter({(r.get("tactic") or "unknown"): int(r.get("alerts") or 0) for r in tb.get("falres_alert_tactics", [])})
    names = collections.Counter({(r.get("name") or "unknown"): int(r.get("alerts") or 0) for r in tb.get("falres_alert_names", [])})
    risky = sorted([e for e in eps if e["highOpen"] or e["openAlerts"]], key=lambda e: (-e["highOpen"], -e["openAlerts"], e["host"].lower()))
    total = sum(sev.values())
    return {
        "windowDays": int(summ.get("windowDays") or ALERT_DAYS), "total": total, "open": int(summ.get("alertsOpen") or 0),
        "openHigh": int(summ.get("alertsOpenHigh") or 0), "leads": leads, "leadsOpen": int(summ.get("leadsOpen") or 0),
        "hostsWithAlerts": int(summ.get("hostsWithAlerts") or 0), "hostsOpenHigh": int(summ.get("hostsOpenHigh") or 0),
        "hostsOpen": int(summ.get("hostsOpen") or 0), "unmatched": unmatched, "fromArchive": "" if arc.get("search") else arc["asOf"],
        "severity": [{"name": k, "count": v} for k, v in sorted(sev.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else 9)],
        "status": top(status), "tactics": top(tactic, 8), "detections": top(names, 8), "openHighDetections": [],
        "noPreventionWithOpen": sum(1 for e in eps if e["openAlerts"] and (not e["prevention"] or not e["preventionApplied"])),
        "silentWithOpen": sum(1 for e in eps if e["openAlerts"] and (e["lastSeenDays"] or 0) > STALE_DAYS),
        "topHosts": [{"host": e["host"], "id": e["id"], "type": e["type"], "alerts": e["alerts"], "open": e["openAlerts"], "highOpen": e["highOpen"],
                      "last": e["lastAlert"], "top": e["topAlert"]} for e in risky[:15]],
        "other": [{"product": o.get("product") or "", "type": o.get("type") or "", "alerts": int(o.get("alerts") or 0), "hosts": int(o.get("hosts") or 0),
                   "open": int(o.get("open") or 0)} for o in tb.get("falres_alert_other", [])],
    }


# ---------------------------------------------------------------- narrative
def default_narrative(f):
    h, e = f["hosts"], f["endpoints"]
    n = h["total"]
    s1 = ("<p>Falcon manages <strong>%d hosts</strong>. <strong>%d (%s%%) checked in within the last %d days</strong>; <strong>%d have been silent "
          "for longer</strong>, %d of them for over %d days. <strong>%d hosts (%s%%) run one of the newest %d sensor releases</strong> (%s); %d are older. "
          "<strong>%d hosts need action</strong> and %d more are worth watching.</p>"
          % (n, n - h["stale"], pct(n - h["stale"], n), STALE_DAYS, h["stale"], h["silent"], LONG_STALE_DAYS, h["onCurrent"], pct(h["onCurrent"], n),
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
    if h["criticalTotal"]:
        bits.append("<strong>%d of the %d hosts rated critical or high need action</strong>." % (h["criticalNeedsAction"], h["criticalTotal"]))
    al = f.get("alerts")
    out = [s1, "<p>" + " ".join(bits) + "</p>"]
    if al:
        out.append("<p>In the %d-day window Falcon raised <strong>%d endpoint detections and leads</strong> on %d hosts. <strong>%d are still open</strong>, %d of them high or critical on %d hosts. %s</p>"
                   % (al["windowDays"], al["total"], al["hostsWithAlerts"], al["open"], al["openHigh"], al["hostsOpenHigh"],
                      ("%d hosts with open detections are also silent or lack an applied prevention policy." % (al["silentWithOpen"] + al["noPreventionWithOpen"])) if (al["silentWithOpen"] or al["noPreventionWithOpen"]) else ""))
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
    if h["criticalNeedsAction"]:
        s.append({"when": "This week", "tone": "urgent", "text": "Start with the %d critical or high-rated hosts that need action." % h["criticalNeedsAction"]})
    if h["silent"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Find out why %d hosts have been silent for over %d days: retired, powered off, or the sensor is damaged. Remove retired hosts from Falcon." % (h["silent"], LONG_STALE_DAYS)})
    if h["uninstallOff"]:
        s.append({"when": "Within 14 days", "tone": "normal", "text": "Turn uninstall protection on for the %d Windows and Mac hosts where it is off or in maintenance mode." % h["uninstallOff"]})
    if h["behind"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Move the %d hosts on older sensor releases to a current one through the sensor update policy." % h["behind"]})
    if h["duplicateNames"]:
        s.append({"when": "Within 30 days", "tone": "normal", "text": "Check the %d host %s that appear more than once: cloned images or stale records." % (len(h["duplicateNames"]), plural(len(h["duplicateNames"]), "name"))})
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
def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    global ALERT_DAYS
    ALERT_DAYS = args.alerts_days
    archive = load_archive(args.alerts_archive) or load_search(args.alerts_hosts, args.alerts_facets, args.alerts_other, args.alerts_days)
    if archive:
        ALERT_DAYS = int((archive["tables"]["falres_summary"][0].get("windowDays")) or ALERT_DAYS)
    f, eps = analyse(args.dumps, now, archive)
    if not f["hosts"]["total"]:
        print("PROBLEM: no falconAgent records; nothing to report", file=sys.stderr)
        return 1
    f["account"] = args.account
    h, e, pol = f["hosts"], f["endpoints"], f["policies"]
    n = h["total"]
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
    g.append(panel("Operating systems", bars(h["os"], n, "var(--navy)"), 6))
    g.append(panel("Host roles and criticality", bars(h["types"], n, "var(--blue)") + '<div style="height:12px"></div>' + bars(h["criticality"], n, "var(--amber)"), 6))
    prot = [("Reduced functionality mode", h["rfm"]), ("Sensor not provisioned", h["notProvisioned"]), ("No prevention policy assigned", h["noPrevention"]),
            ("Prevention policy not applied", h["preventionNotApplied"]), ("Contained (network isolation)", h["contained"]),
            ("Uninstall protection off (Windows, Mac)", h["uninstallOff"]), ("  of which maintenance mode", h["uninstallMaintenance"]),
            ("Running in safe mode", h["safeMode"]), ("Last reboot over %d days ago (info only)" % REBOOT_DAYS, h["rebootOld"])]
    g.append(panel("Protection health", table(["Check", "Hosts"], [[td(k), '<td class="num">%d</td>' % v] for k, v in prot], ["75%", "25%"]), 6, "hosts affected"))
    rows = [[td(c["policy"]), '<td class="num">%s</td>' % "{:,}".format(c["assigned"]), '<td class="num">%s</td>' % "{:,}".format(c["missing"]), '<td class="num">%d</td>' % c["notApplied"]] for c in pol["coverage"]]
    g.append(panel("Policy coverage", table(["Policy type", "Assigned", "Missing", "Not applied"], rows, ["40%", "20%", "18%", "22%"]), 6,
                   "%d prevention %s in use" % (pol["preventionPolicies"], plural(pol["preventionPolicies"], "policy", "policies"))))
    g.append(panel("New hosts per week", trend_svg(h["weekly"]), 6, "first seen by Falcon, last %d weeks" % TREND_WEEKS))
    g.append(panel("Active Directory domains", bars(h["domains"], n, "var(--navy)"), 6, "by hosts"))

    if al:
        sevc = {"Critical": "#7f1d1d", "High": "#B91C1C", "Medium": "#B45309", "Low": "#64748B", "Lead": "#1D4ED8"}
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

    attn = sorted([x for x in eps if x["score"]], key=lambda x: (-x["score"], x["host"].lower()))
    cap = args.max_listed
    rows = [([('<td class="host">%s</td>' % esc(x["host"])), td(x["type"]), td(x["os"]), td(x["version"]),
              '<td>%s</td>' % chip(x["state"], STATUS_COLOR[x["state"]]), td(x["reasons"], True)], "") for x in attn[:cap]]
    note = "" if len(attn) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(attn))
    app = [panel("Hosts needing attention", table(["Host", "Role", "OS", "Sensor", "Status", "Why"], rows, ["16%", "10%", "17%", "11%", "13%", "33%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No host has an open issue.</p>', 12, "%d of %s%s" % (len(attn), "{:,}".format(n), note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Source.</b> One Falcon Hosts snapshot (falconAgent): the current state of each host with a Falcon sensor. One row per device id.</div>'
              '<div><b>Last check-in.</b> Days from the host\'s last_seen to the time this report was built. More than %d days is stale; more than %d days is silent.</div>'
              '<div><b>Current sensor.</b> A host is current when its sensor major.minor release is one of the newest %d releases found in this fleet (N, N-1, N-2), not the latest Falcon release.</div>'
              '<div><b>Needs action.</b> Score of 3 or more: reduced functionality mode, not provisioned or no prevention policy (3 each), silent over %d days (3), prevention not applied, silent %d to %d days, contained or uninstall protection in maintenance mode (2 each). Watch is 1 to 2: uninstall protection off, older sensor, safe mode.</div>'
              '<div><b>Detections.</b> FalconAlert rows created in the %d-day window, joined to hosts on agent_id = device_id. Endpoint detections (product epp) and automated leads count; identity, data protection and cloud alerts are listed for context only. An open high or critical detection scores 3; any other open detection or lead scores 1.</div>'
              '<div><b>Not scored.</b> Last reboot age, host criticality and tags are shown for context.</div></div>'
              % (STALE_DAYS, LONG_STALE_DAYS, SENSOR_WINDOW, LONG_STALE_DAYS, STALE_DAYS + 1, LONG_STALE_DAYS, ALERT_DAYS))
    app.append(panel("How to read this report", method, 12))
    if al and al["unmatched"]:
        app.append(panel("Data notes", '<div class="method"><div>%d alert rows belong to device ids that are not in the host snapshot (retired or deleted hosts) and are left out of the host table.</div></div>' % al["unmatched"], 12))
    if al and al.get("fromArchive"):
        app.append(panel("Data notes", '<div class="method"><div>Detections come from the archived CrowdStrike_Resource_Report for %s (%d-day window). Per-host detection counts cover the scored hosts the archive lists, so a host with only closed detections may show none.</div></div>' % (esc(al["fromArchive"]), al["windowDays"]), 12))
    if not al:
        app.append(panel("Data notes", '<div class="method"><div>No alert extract was supplied, so detections are not part of this run.</div></div>', 12))
    if h["duplicateNames"] or h["duplicateIds"]:
        bits = []
        if h["duplicateIds"]:
            bits.append("%d repeated device ids were collapsed to the newest record." % h["duplicateIds"])
        if h["duplicateNames"]:
            bits.append("%d host %s appear more than once: %s." % (len(h["duplicateNames"]), plural(len(h["duplicateNames"]), "name"), esc(", ".join(h["duplicateNames"][:8]))))
        app.append(panel("Data notes", '<div class="method"><div>%s</div></div>' % " ".join(bits), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(s.get("tone"), "var(--navy)"), i + 1, esc(s.get("when", "")), esc(s.get("text", ""))) for i, s in enumerate(steps))

    subtitle = args.customer or ", ".join(c for c in f["customers"] if c) or args.account
    snap = (f["snapshot"] or [""])[-1]
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "CrowdStrike Falcon Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong>" % esc(args.account),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "Falcon resource report · %s" % esc(subtitle), "footer_data_date": esc(snap),
    }
    for k, v in page.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    with open(os.path.join(args.work, "falcon_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    with open(os.path.join(args.work, "hosts.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["customer", "hostname", "device_id", "platform", "role", "os", "os_build", "domain", "site", "last_login_user", "sensor_version",
                    "behind_current_releases", "last_seen", "last_seen_days", "first_seen", "last_reboot_days", "status", "provision_status",
                    "reduced_functionality", "safe_mode", "rtr_state", "criticality", "tags", "groups", "prevention_policy", "prevention_applied",
                    "uninstall_protection", "policies_assigned", "policies_not_applied", "alerts_%dd" % ALERT_DAYS, "open_alerts", "open_high_or_critical", "last_alert", "most_common_detection", "score", "state", "reasons"])
        for x in sorted(eps, key=lambda x: (-x["score"], x["host"].lower())):
            w.writerow([x["customer"], x["host"], x["id"], x["platform"], x["type"], x["os"], x["build"], x["domain"], x["site"], "" if args.no_actors else x["user"],
                        x["version"], x["behind"], day(x["lastSeen"]), x["lastSeenDays"], day(x["firstSeen"]), x["rebootDays"], x["status"], x["provision"],
                        x["rfm"], x["safeMode"], x["rtr"], x["criticality"], x["tags"], x["groups"], x["preventionPolicy"], x["preventionApplied"],
                        x["uninstall"], len(x["policies"]), "; ".join(x["notApplied"]), x["alerts"], x["openAlerts"], x["highOpen"], x["lastAlert"], x["topAlert"], x["score"], x["state"], x["reasons"]])
    if f.get("alerts"):
        with open(os.path.join(args.work, "alerts.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["hostname", "device_id", "role", "alerts", "open_alerts", "open_high_or_critical", "last_alert", "most_common_detection"])
            for x in sorted([x for x in eps if x["alerts"]], key=lambda x: (-x["highOpen"], -x["openAlerts"], -x["alerts"], x["host"].lower())):
                w.writerow([x["host"], x["id"], x["type"], x["alerts"], x["openAlerts"], x["highOpen"], x["lastAlert"], x["topAlert"]])
    with open(os.path.join(args.work, "policies.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["policy_type", "hosts_assigned", "hosts_not_assigned", "hosts_not_applied"])
        for c in pol["coverage"]:
            w.writerow([c["policy"], c["assigned"], c["missing"], c["notApplied"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "falcon_resource_report_interactive.html"), args, f, eps, now)

    print("hosts %d | silent over %d days: %d (over %d: %d) | current sensor %d, older %d" % (n, STALE_DAYS, h["stale"], LONG_STALE_DAYS, h["silent"], h["onCurrent"], h["behind"]))
    print("needs action %d, watch %d, healthy %d" % (e["needsAction"], e["watch"], e["healthy"]))
    print("protection gaps: rfm %d, not provisioned %d, no prevention %d, prevention not applied %d, contained %d" % (h["rfm"], h["notProvisioned"], h["noPrevention"], h["preventionNotApplied"], h["contained"]))
    print("wrote: falcon_resource_report.html, falcon_resource_report_interactive.html, hosts.csv, policies.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, eps, now):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    h = f["hosts"]
    hosts = []
    for x in eps:
        hosts.append({
            "name": x["host"], "user": "" if args.no_actors else x["user"], "platform": x["platform"], "role": x["type"], "os": x["os"],
            "sensor": x["version"], "release": ("current" if not x["behind"] else "older") if x["version"] else "",
            "seenDays": x["lastSeenDays"] if x["lastSeenDays"] is not None else "", "checkin": "Silent" if (x["lastSeenDays"] or 0) > STALE_DAYS else "Checking in",
            "mode": "Reduced" if x["rfm"] else "Full", "prov": x["provision"] or "unknown", "contained": "Contained" if x["contained"] else "No",
            "prevention": "Applied" if x["preventionApplied"] else "Not applied" if x["prevention"] else "None",
            "uninstall": x["uninstall"] or "none", "crit": x["criticality"], "domain": x["domain"], "policies": len(x["policies"]),
            "alerts": x["alerts"], "openAlerts": x["openAlerts"], "highOpen": x["highOpen"], "lastAlert": x["lastAlert"], "topAlert": x["topAlert"],
            "score": x["score"], "state": x["state"], "reasons": x["reasons"]})
    sources = [{"resource": RES, "records": f["hosts"]["records"], "snapshot": ", ".join(f["snapshot"]), "customers": ", ".join(c for c in f["customers"] if c)}]
    notes = []
    if h["duplicateIds"]:
        notes.append("%d repeated device ids were collapsed to the newest record." % h["duplicateIds"])
    if h["duplicateNames"]:
        notes.append("%d host name(s) appear more than once: %s." % (len(h["duplicateNames"]), ", ".join(h["duplicateNames"][:8])))
    method = [
        "Source: one Falcon Hosts snapshot (falconAgent), one row per device id.",
        "Last check-in: days from last_seen to the time this file was built. More than %d days is stale; more than %d days is silent." % (STALE_DAYS, LONG_STALE_DAYS),
        "Current sensor: the host's major.minor release is one of the newest %d releases found in this fleet (N, N-1, N-2), not the latest Falcon release." % SENSOR_WINDOW,
        "Needs action is a score of 3 or more: reduced functionality mode, not provisioned or no prevention policy (3 each), silent over %d days (3), prevention not applied, silent %d to %d days, contained or uninstall protection in maintenance mode (2 each)." % (LONG_STALE_DAYS, STALE_DAYS + 1, LONG_STALE_DAYS),
        "Watch is 1 to 2: uninstall protection off on Windows or Mac, older sensor, safe mode. Last reboot age, criticality and tags are shown for context only.",
    ]
    method.append("Detections: FalconAlert rows created in the %d-day window, joined to hosts on agent_id = device_id. Endpoint detections and automated leads count; an open high or critical detection scores 3, any other open detection or lead scores 1. Identity, data protection and cloud alerts are context only." % ALERT_DAYS)
    if not args.no_actors:
        method.append("This file embeds host names and last logged-in users. Share it only with the tenant's owner, or rebuild with --no-actors.")
    data = {"title": "CrowdStrike Falcon Resource Report", "account": args.account, "customer": args.customer, "snapshot": (f["snapshot"] or [""])[-1],
            "staleDays": STALE_DAYS, "silentDays": LONG_STALE_DAYS, "window": SENSOR_WINDOW, "latestVersion": f["latestVersion"], "currentReleases": f["currentReleases"],
            "noActors": args.no_actors, "hosts": h, "policies": f["policies"], "summary": f["endpoints"], "alerts": f.get("alerts"), "rows": hosts,
            "sources": sources, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " Falcon Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--dumps", required=True)
    r = sub.add_parser("render"); r.add_argument("--dumps", required=True); r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--alerts-archive", default="", help="download_report_archive JSON of CrowdStrike_Resource_Report (preferred)")
    r.add_argument("--alerts-hosts", default="", help="fallback: kql_search result of the per-host alert query (SKILL.md step 2b)")
    r.add_argument("--alerts-facets", default="", help="fallback: kql_search result of the facet query")
    r.add_argument("--alerts-days", type=int, default=30, help="window of the alert data in days (default 30)")
    r.add_argument("--alerts-other", default="", help="fallback: kql_search result of the other-products query")
    r.add_argument("--max-listed", type=int, default=40)
    r.add_argument("--no-actors", action="store_true", help="leave last logged-in user names out of the CSV and the interactive file")
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
