#!/usr/bin/env python3
"""Build the Acronis Cyber Protect data review from the scheduled-report ARCHIVE only (HTML + summary JSON).

  build_report.py --archive a.json [b.json ...] --from YYYY-MM-DD --to YYYY-MM-DD --tenant NAME --client "Customer Ltd" \
                  --out report.html [--summary-json s.json]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}); several files and
several days per file are merged. This script never queries a tenant. Daily results are combined the only safe way:
  * event counters (acr_trend, acr_activities, acr_backup) are summed;
  * keyed tables (acr_alerts, acr_incidents, acr_edr_triggers, acr_update_failures) are merged by the vendor's own key
    and take their state from the latest day that mentions the key;
  * snapshot tables (agent inventory) are read from ONE day, the latest, never added;
  * a day that was not archived is a GAP, never zero.
The Fluency brand kit comes from the `fluency-report` skill (FLUENCY_BRAND_DIR or a sibling skill folder).
"""
import argparse, collections, datetime, glob, json, os, re, sys


def _find_brand_kit():
    here = os.path.dirname(os.path.abspath(__file__)); home = os.path.expanduser("~")
    cands = [os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = os.path.dirname(up)
        cands += [os.path.join(up, "fluency-report", "scripts"), os.path.join(up, "SKILLS", "fluency-report", "scripts")]
    cands += [os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += glob.glob(os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and os.path.exists(os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")


sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s)")
ap.add_argument("--from", dest="dfrom", required=True, help="first day, YYYY-MM-DD (UTC)")
ap.add_argument("--to", dest="dto", required=True, help="last day, YYYY-MM-DD (UTC), included")
ap.add_argument("--tenant", required=True)
ap.add_argument("--client", required=True)
ap.add_argument("--out", required=True, help="report HTML (static, Fluency brand); render_pdf.mjs turns it into the PDF")
ap.add_argument("--summary-json")
a = ap.parse_args()

EVENT_TABLES = ["acr_trend", "acr_alerts", "acr_incidents", "acr_edr_triggers", "acr_activities", "acr_update_failures", "acr_backup"]
SNAP_TABLES = ["acr_agent_summary", "acr_defs_age", "acr_versions", "acr_units", "acr_stale_agents", "acr_duplicates",
               "acr_no_active_protection", "acr_tenants"]


def parse_day(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)


def parse_ts(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)


# ---- load: one completed run per UTC day (latest completedOn), the rest are gaps ------------------------------------------
done, other, hashes = {}, {}, set()
files = []
for p in a.archive:
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
        h = (en.get("env") or {}).get("scriptHash")
        if h:
            hashes.add(h)

d0, d1 = parse_day(a.dfrom), parse_day(a.dto)
if d1 < d0:
    sys.exit("--to is before --from")
expected = []
x = d0
while x <= d1:
    expected.append(x.strftime("%Y-%m-%d")); x += datetime.timedelta(days=1)
have = [k for k in expected if k in done]
gaps = [(k, other.get(k, "not archived")) for k in expected if k not in done]
if not have:
    sys.exit("no completed archived day between %s and %s: nothing to report. Run list_report_archive, then backfill_report_archive." % (a.dfrom, a.dto))
for k in have:
    bad = [r["source"] for r in done[k]["T"].get("sources", []) if r.get("status") != "ok"]
    if bad:
        sys.exit("archived day %s has source(s) not available (%s): backfill it with force=true or leave it out" % (k, bad))


# ---- merge ----------------------------------------------------------------------------------------------------------------
def keyed(table, keyfn, fold):
    """Merge the daily rows of one keyed table, oldest day first, so fold() sees the latest day last."""
    out = {}
    for k in have:
        for r in done[k]["T"].get(table, []):
            kk = keyfn(r)
            if kk in out:
                out[kk] = fold(out[kk], r)
            else:
                out[kk] = dict(r)
    return list(out.values())


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def mx(p, q):
    return max(p or "", q or "")


def mn(p, q):
    return min([v for v in (p, q) if v] or [""])


def f_alert(o, r):
    o["events"] = num(o.get("events")) + num(r.get("events"))
    o["resolved"] = num(o.get("resolved")) + num(r.get("resolved"))
    o["firstSeen"] = mn(o.get("firstSeen"), r.get("firstSeen"))
    o["lastSeen"] = mx(o.get("lastSeen"), r.get("lastSeen"))
    for f in ("category", "alertType", "severity", "device", "planName"):
        o[f] = r.get(f) or o.get(f)
    for f in ("domain", "process"):
        o[f] = o.get(f) or r.get(f)
    return o


def f_inc(o, r):
    o["events"] = num(o.get("events")) + num(r.get("events"))
    o["lastUpdate"] = mx(o.get("lastUpdate"), r.get("lastUpdate"))
    for f in ("lastState", "lastMitigation", "severity"):
        o[f] = r.get(f) or o.get(f)
    o["created"] = o.get("created") or r.get("created")
    o["transferredTo"] = r.get("transferredTo") or o.get("transferredTo")
    return o


def f_trig(o, r):
    o["lastSeen"] = mx(o.get("lastSeen"), r.get("lastSeen"))
    o["mitigation"] = r.get("mitigation") or o.get("mitigation")
    o["detection"] = mn(o.get("detection"), r.get("detection"))
    o["trigger"] = r.get("trigger") or o.get("trigger")
    return o


def f_act(o, r):
    for f in ("runs", "ok", "notOk"):
        o[f] = num(o.get(f)) + num(r.get(f))
    o["title"] = o.get("title") or r.get("title")
    return o


def f_uf(o, r):
    o["failed"] = num(o.get("failed")) + num(r.get("failed"))
    o["lastFailure"] = mx(o.get("lastFailure"), r.get("lastFailure"))
    o["errorCode"] = r.get("errorCode") or o.get("errorCode")
    return o


def f_bk(o, r):
    for f in ("runs", "ok", "failed", "gbProcessed"):
        o[f] = num(o.get(f)) + num(r.get(f))
    o["lastRun"] = mx(o.get("lastRun"), r.get("lastRun"))
    def codes(v):
        try:
            return json.loads(v) if isinstance(v, str) else (v or [])
        except ValueError:
            return []
    o["errors"] = json.dumps(sorted(set(codes(o.get("errors"))) | set(codes(r.get("errors"))))[:5])
    return o


def f_trend(o, r):
    for f in ("events", "alertEvents", "activityEvents", "incidentEvents"):
        o[f] = num(o.get(f)) + num(r.get(f))
    return o


T = {}
T["acr_trend"] = sorted(keyed("acr_trend", lambda r: r["Date"][:10], f_trend), key=lambda r: r["Date"])
T["acr_alerts"] = keyed("acr_alerts", lambda r: r["alertId"], f_alert)
T["acr_incidents"] = keyed("acr_incidents", lambda r: (r["shortId"], (r["host"] or "").lower()), f_inc)
T["acr_edr_triggers"] = keyed("acr_edr_triggers", lambda r: (r["incident"], (r["device"] or "").lower()), f_trig)
T["acr_activities"] = keyed("acr_activities", lambda r: r["activityType"], f_act)
T["acr_update_failures"] = keyed("acr_update_failures", lambda r: (r["agentId"], r["unit"], r["activityType"]), f_uf)
T["acr_backup"] = keyed("acr_backup", lambda r: (r["device"], r["plan"]), f_bk)

# Snapshot: ONE day. Prefer the latest day that was archived by the schedule itself (created within 8 hours of the day's
# end: the schedule runs at 04:00 UTC); a backfilled day reads the inventory as it is at backfill time, so it is a fallback and the report says so.
def lag_hours(k):
    en = done[k]["entry"]
    try:
        return (parse_ts(en["createdOn"]) - parse_ts(en["rangeTo"])).total_seconds() / 3600.0
    except (KeyError, ValueError):
        return 0.0


scheduled = [k for k in have if lag_hours(k) <= 8]
snap_day = (scheduled or have)[-1]
snap_backfilled = snap_day not in scheduled
for t in SNAP_TABLES:
    T[t] = done[snap_day]["T"].get(t, [])
if not T["acr_agent_summary"]:
    sys.exit("snapshot day %s has no acr_agent_summary row" % snap_day)

frm = d0
to = d1 + datetime.timedelta(days=1)
last_day = d1
days = len(expected)
d = lambda x: x.strftime("%-d %b %Y")
win = "%s – %s" % (frm.strftime("%-d %b"), d(last_day))
asof_dt = parse_ts(T["acr_agent_summary"][0]["asOf"])
asof = d(asof_dt) + " 00:00 UTC"
S = T["acr_agent_summary"][0]
nf = lambda n: "{:,}".format(int(n))
pct = lambda a_, b_: ("%.1f" % (100.0 * a_ / b_)) if b_ else "0.0"
unit = lambda u: re.sub(r"\s*\(.*\)\s*$", "", u or "") or "(none)"
fdate = lambda s: (s or "")[:16].replace("T", " ") + " UTC" if s else ""
n_have = len(have)

# ---- events -----------------------------------------------------------------
trend = T["acr_trend"]
ev_total = sum(r["events"] for r in trend)
alert_ev = sum(r["alertEvents"] for r in trend)
act_ev = sum(r["activityEvents"] for r in trend)
inc_ev = sum(r["incidentEvents"] for r in trend)
alerts = T["acr_alerts"]
uniq_alerts = len(alerts)
alert_devices = len({r["device"] for r in alerts if r["device"]})
resend = alert_ev / float(uniq_alerts) if uniq_alerts else 0

# ---- EDR --------------------------------------------------------------------
inc = T["acr_incidents"]
trig = T["acr_edr_triggers"]
inc_by = {(r["shortId"], r["host"].lower()): r for r in inc}
open_inc = [r for r in inc if r["lastState"] != "CLOSED" or r["lastMitigation"] == "NOT_MITIGATED"]
open_ids = sorted({r["shortId"] for r in open_inc})
open_hosts = sorted({r["host"] for r in open_inc})
trig_open = [r for r in trig if r["mitigation"] == "NOT_MITIGATED"]
merged_ids = {r["shortId"] for r in inc if r["transferredTo"]}
open_cases = sorted(({r["incident"] for r in trig_open} | set(open_ids)) - merged_ids)
node_trig = [r for r in trig if r["trigger"].lower().endswith(".node")]
merged = [r for r in inc if r["transferredTo"]]

# ---- agents -----------------------------------------------------------------
stale = T["acr_stale_agents"]
no_ap = T["acr_no_active_protection"]
dups = T["acr_duplicates"]
vers = T["acr_versions"]
units = T["acr_units"]
ages = T["acr_defs_age"]
latest = S["latestInstaller"]
on_latest = S["onLatest"]
stale_online = [r for r in stale if r["online"]]
stale_off = [r for r in stale if not r["online"]]

# ---- update failures --------------------------------------------------------
uf = T["acr_update_failures"]
UTYPE = {"UpdateVapm": "Vulnerability-assessment definition update", "AutoUpdateStandby": "Auto-update standby",
         "DownloadInstaller": "Installer download", "Download": "Component download", "UpdateAgent": "Agent update"}
acts = {r["activityType"]: r for r in T["acr_activities"]}
vapm_fail_agents = len({r["agentId"] for r in uf if r["activityType"] == "UpdateVapm"})
fail_runs = sum(acts[t]["notOk"] for t in UTYPE if t in acts)
fail_agents = len({r["agentId"] for r in uf})
err_codes = collections.Counter()
for r in uf:
    err_codes[r["errorCode"] or "(no code)"] += r["failed"]

# ---- backup -----------------------------------------------------------------
bk = T["acr_backup"]
bk_runs = sum(r["runs"] for r in bk); bk_ok = sum(r["ok"] for r in bk); bk_fail = sum(r["failed"] for r in bk)
bk_gb = sum((r["gbProcessed"] if isinstance(r["gbProcessed"], (int, float)) else 0) for r in bk)

# ---- alert mix --------------------------------------------------------------
TYPE = {"TotalProtectDeniedCategoryURLDetected": "URL category blocked", "MachineOffline30": "Machine offline 30+ days",
        "MaliciousUrlBlocked": "Malicious URL blocked", "MachineOffline20": "Machine offline 20+ days",
        "MiMonitoringMetricGatheringFailed": "Monitoring metrics failed", "EDRIncidentDetected": "EDR incident detected",
        "ProtectionServiceNotWorking": "Protection service not working"}
nice = lambda t: TYPE.get(t) or re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", t or "(none)")
by_type = collections.Counter(r["alertType"] for r in alerts)
by_dev_events = collections.Counter()
for r in alerts:
    by_dev_events[r["device"] or "(none)"] += r["events"]
url_block = [r for r in alerts if r["alertType"] == "MaliciousUrlBlocked"]
url_cat = [r for r in alerts if r["alertType"] == "TotalProtectDeniedCategoryURLDetected"]
amazon = lambda dmn: bool(re.search(r"(amazon\.com|amazon\.co\.za|amazonaws\.com)$", dmn or ""))
url_block_amazon = sum(1 for r in url_block if amazon(r["domain"]))
url_block_resolved = sum(1 for r in url_block if r["resolved"] > 0)
url_cat_resolved = sum(1 for r in url_cat if r["resolved"] > 0)
url_cat_devices = len({r["device"] for r in url_cat if r["device"]})
macos_plan = [r for r in alerts if "macos" in (r["planName"] or "").lower()]
macos_plan_devs = sorted({r["device"] for r in macos_plan if r["device"]})

# ---- components -------------------------------------------------------------
def sev(ok):
    return fb.tag("Critical", "red") if ok == "c" else fb.tag("High", "amber") if ok == "h" else fb.tag("Medium", "gray") if ok == "m" else fb.tag("Low", "o-blue")

kpis = [
    fb.kpi("Events collected", nf(ev_total), note=("%d days" % days) if not gaps else ("%d of %d days archived" % (n_have, days))),
    fb.kpi("Unique alerts", nf(uniq_alerts), note="%s devices · %s alert events" % (nf(alert_devices), nf(alert_ev))),
    fb.kpi("Open EDR cases", nf(len(open_cases)), color="red" if open_cases else "", tag=fb.tag("Not mitigated", "red") if open_cases else fb.tag("None open", "o-blue")),
    fb.kpi("Agents with stale definitions", nf(S["defsStale"]), color="amber", note="30+ days · %s online" % nf(S["defsStaleOnline"])),
    fb.kpi("On latest installer", pct(on_latest, S["agents"]) + "%", note="%s of %s agents on %s" % (nf(on_latest), nf(S["agents"]), latest)),
]

band = [
    ("01 — What is exposed",
     "<p>%s EDR case%s on %s device%s remain not mitigated and untriaged%s. %s online agent%s report no Active Protection component, and %s online agent%s have not updated protection definitions in 30 days or more.</p>"
     % (nf(len(open_cases)), "" if len(open_cases) == 1 else "s", nf(len(open_hosts)), "" if len(open_hosts) == 1 else "s",
        " (" + ", ".join(open_hosts[:3]) + ")" if open_hosts else "", nf(S["noActiveProtection"]), "" if S["noActiveProtection"] == 1 else "s",
        nf(S["defsStaleOnline"]), "" if S["defsStaleOnline"] == 1 else "s")),
    ("02 — What is already right",
     "<p>%s of %s Acronis agents (%s%%) run the current installer, %s of %s agents have fresh definitions, %s EDR incident%s were closed automatically, and %s of %s backup jobs (%s%%) succeeded.</p>"
     % (nf(on_latest), nf(S["agents"]), pct(on_latest, S["agents"]), nf(S["defsFresh"]), nf(S["agents"]),
        nf(len(inc) - len(open_inc)), "" if len(inc) - len(open_inc) == 1 else "s", nf(bk_ok), nf(bk_runs), pct(bk_ok, bk_runs))),
    ("03 — What to fix first",
     "<p>Triage the open EDR cases in the Acronis console, restore protection on the online agents with stale definitions or no Active Protection, then retire the %s offline stale and %s duplicate agent records.</p>"
     % (nf(S["defsStaleOffline"]), nf(S["duplicateHosts"]))),
]

# F1 table
f1_rows = []
for r in trig:
    st = inc_by.get((r["incident"], r["device"].lower()))
    state = ("Open, not mitigated" if (r["mitigation"] == "NOT_MITIGATED") else "Closed, auto-mitigated" if r["mitigation"] == "AUTO_MITIGATED" else r["mitigation"].replace("_", " ").title())
    if st and st["transferredTo"]:
        state += " · merged into another incident"
    f1_rows.append([r["incident"], r["device"], r["trigger"], fdate(r["detection"]), fb.tag("Open", "red") if r["mitigation"] == "NOT_MITIGATED" else fb.tag("Closed", "o-blue"), state])
f1 = fb.table(["Incident", "Host", "Trigger file", "Detected", "State", "Detail"], f1_rows,
              widths=["8%", "20%", "26%", "16%", "8%", "22%"], raw_cols=(4,))
f1_text = ("<p>The Acronis feed raised %s EDR alert%s on %s incident%s in the window. %s remain <b>not mitigated</b>: nobody has worked them in the Acronis console and the files were not removed. "
           "%s of the %s trigger files are native Node.js add-on modules (<code>.node</code>), which are typically bundled with code editors and JavaScript build tools, so a false positive from developer tooling is likely, but it has not been confirmed "
           "(the file hash, signer and parent process are not in this feed).</p>"
           % (nf(len(trig)), "" if len(trig) == 1 else "s", nf(len({r["incident"] for r in trig})), "" if len({r["incident"] for r in trig}) == 1 else "s",
              nf(len(open_cases)) + " case" + ("" if len(open_cases) == 1 else "s") + " (" + ", ".join(open_cases) + ")",
              nf(len(node_trig)), nf(len(trig))))
if merged:
    f1_text += "<p class=\"fn\">Incident %s was merged into another incident (transferred), so its devices appear only in the trigger rows.</p>" % ", ".join(sorted({r["shortId"] for r in merged}))

# F2 definitions / agents
age_chart = fb.column_chart([r["bucket"] for r in ages], [r["agents"] for r in ages], height=170)
ver_items = [("%s%s" % (r["version"], " (current)" if r["isLatest"] else ""), r["agents"]) for r in sorted(vers, key=lambda x: [int(p) if p.isdigit() else 0 for p in re.split(r"\.", x["version"])], reverse=True)]
stale_rows = [[r["host"], unit(r["unit"]), "Online" if r["online"] else "Offline", r["days"], r["installer"]] for r in stale_online + stale_off[:12]]
stale_tbl = fb.table(["Agent", "Unit", "State", "Age (days)", "Installer"], stale_rows,
                     widths=["28%", "26%", "12%", "18%", "16%"], num_cols=(3,),
                     foot="All %s agents with definitions 30 days or more old: the %s online ones first, then the oldest %s of %s offline." % (nf(len(stale)), nf(len(stale_online)), nf(min(12, len(stale_off))), nf(len(stale_off))))
noap_tbl = fb.table(["Agent", "Unit", "Installer", "Age (days)"],
                    [[r["host"], unit(r["unit"]), r["installer"], r.get("days", "no component data")] for r in no_ap],
                    widths=["32%", "30%", "16%", "22%"], num_cols=(3,))
dup_tbl = fb.table(["Host", "Records", "Units", "States"], [[r["host"], r["records"], " / ".join(unit(u) for u in re.split(r"(?<=\)) / ", r["units"])), r["states"]] for r in dups],
                   widths=["28%", "10%", "42%", "20%"], num_cols=(1,))
unit_tbl = fb.table(["Unit", "Agents", "Online", "Stale definitions"], [[unit(r["unit"]), r["agents"], r["online"], r["stale"]] for r in units],
                    widths=["46%", "18%", "18%", "18%"], num_cols=(1, 2, 3))
upd_rows = []
for t in ["UpdateVapm", "AutoUpdateStandby", "DownloadInstaller", "Download", "UpdateAgent"]:
    r = acts.get(t)
    if r:
        ag = len({x["agentId"] for x in uf if x["activityType"] == t})
        upd_rows.append([UTYPE[t], r["runs"], r["notOk"], ag])
upd_tbl = fb.table(["Activity", "Runs", "Not OK", "Agents with a failure"], upd_rows, widths=["46%", "16%", "16%", "22%"], num_cols=(1, 2, 3))

# F3 backup
bk_tbl = fb.table(["Device", "Plan", "Runs", "OK", "Failed", "Errors", "GB read"],
                  [[r["device"], r["plan"], r["runs"], r["ok"], r["failed"], ", ".join(json.loads(r["errors"])) if isinstance(r["errors"], str) and r["errors"].startswith("[") else (r["errors"] or ""),
                    ("%.0f" % r["gbProcessed"]) if isinstance(r["gbProcessed"], (int, float)) and r["gbProcessed"] else "-"] for r in bk],
                  widths=["22%", "18%", "7%", "7%", "8%", "26%", "12%"], num_cols=(2, 3, 4, 6))

# F4 alert quality
type_items = [(nice(t), n) for t, n in by_type.most_common(10)]
noisy = by_dev_events.most_common(5)
noisy_tbl = fb.table(["Device", "Alert events", "Share of all alert events"], [[dv, n, pct(n, alert_ev) + "%"] for dv, n in noisy],
                     widths=["50%", "24%", "26%"], num_cols=(1, 2))
dom = collections.Counter(r["domain"] for r in url_block if r["domain"])

# actions
steps = []
if open_cases:
    steps.append(("Today", "Triage the open EDR incident%s %s in the Acronis console%s. Retrieve the hash, path and parent process of the trigger file on %s; confirm with the users whether it came from installed developer tooling, then add a narrow exclusion or isolate and clean the device%s." % ("" if len(open_cases) == 1 else "s", ", ".join(open_cases), (" (incident %s was merged into another)" % ", ".join(sorted(merged_ids))) if merged_ids else "", ", ".join(open_hosts) or "the affected devices", "" if len(open_hosts) == 1 else "s"), "P1"))
if S["noActiveProtection"] or S["defsStaleOnline"]:
    names = [r["host"] for r in no_ap] + [r["host"] for r in stale_online if r["host"] not in {x["host"] for x in no_ap}]
    steps.append(("This week", "Restore protection on the online agents that are not updating or report no Active Protection (%s): update the agent, force a definition update and confirm Active Protection reports healthy." % ", ".join(names), "P1"))
steps.append(("Within 14 days", "Retire the %s stale agent records once confirmed (%s of them offline), and merge the %s duplicate hosts into the correct unit. Fix definition updates on the %s agents with a failed update and upgrade the %s agents behind %s." % (nf(S["defsStale"]), nf(S["defsStaleOffline"]), nf(S["duplicateHosts"]), nf(vapm_fail_agents), nf(S["behind"]), latest), "P2"))
if bk_fail:
    steps.append(("Within 30 days", "Look at the %s failed backup job%s (%s) and consider scheduling backups when laptops are less likely to be shut down. Confirm how servers are backed up: no server backup appears in this feed." % (nf(bk_fail), "" if bk_fail == 1 else "s", ", ".join(c for c, _ in collections.Counter(c for r in bk for c in (json.loads(r["errors"]) if isinstance(r["errors"], str) and r["errors"].startswith("[") else [])).most_common(3))), "P2"))
if url_block_amazon:
    steps.append(("Within 30 days", "Report the Amazon false positives (%s of %s malicious-URL blocks) to Acronis or add a narrow allow rule, and refer repeat acceptable-use breaches to HR." % (nf(url_block_amazon), nf(len(url_block))), "P3"))
steps.append(("Within 30 days", "Count distinct alert IDs, not events, in any dashboard built on Acronis data: alerts are re-sent %.1f times on average here." % resend, "P3"))

snap_note = ("The inventory snapshot is the %s run, taken by the schedule at the end of that day." % d(parse_day(snap_day))
             if not snap_backfilled else
             "No schedule-written day is in the period, so the inventory snapshot is the %s run, which was backfilled: it shows the inventory as it was when the backfill ran, not on that day." % d(parse_day(snap_day)))
gap_note = ("" if not gaps else " %d day%s %s not archived (%s) and %s counted as a gap, not as zero." % (len(gaps), "" if len(gaps) == 1 else "s", "was" if len(gaps) == 1 else "were", ", ".join(g for g, _ in gaps[:10]) + (" …" if len(gaps) > 10 else ""), "is" if len(gaps) == 1 else "are"))
method = ("<p><b>Data.</b> The report is built only from the archive of the scheduled report Acronis_Protection_Report for tenant %s: %d of %d days (%s) were archived.%s "
          "Event tables come from the Acronis index (alerts, activities and EDR incidents pulled by the AcronisCP connector) and are merged across days: counters are summed, keyed tables are merged by the vendor's own id. %s</p>"
          "<p><b>Counting rules.</b> Alerts are counted by Acronis alert ID at their latest event, because Acronis re-sends an alert each time it changes. Activities are counted by activity UUID, so an activity re-sent across a day boundary is counted on both days and run totals are slightly overstated. Incidents are counted by incident short ID at the latest state. "
          "Definition age is the days from the end of the snapshot day to the most recent update time of any protection component on the agent. The Acronis inventory has no last check-in time, so an agent that is online but not updating is a broken updater; an agent with no component data is counted as \"no data\", not stale. "
          "Unit names are shown without e-mail addresses.</p>"
          "<p><b>Limits.</b> Acronis history only goes back as far as the connector's first import, so days before that read as zero events and the trend is not comparable with earlier months. The coverage cross-check against Microsoft Defender and Microsoft Entra ID devices (workstations with no agent, unknown devices on the network) is not part of this report. "
          "The false-positive reading of the EDR cases rests on file names only and is not confirmed. Backup jobs are identified by the activity title \"Backing up\"; servers may be backed up by another product.</p>"
          % (a.tenant, n_have, days, win, gap_note, snap_note))

body = ""
body += fb.section(1, "Summary of findings", fb.table(["", "Finding", "Area", "Severity"], [
    ["F1", "%s EDR case%s unmitigated on %s device%s" % (nf(len(open_cases)), "" if len(open_cases) == 1 else "s", nf(len(open_hosts)), "" if len(open_hosts) == 1 else "s"), "EDR", sev("c" if open_cases else "l")],
    ["F2", "%s online agent%s with stale definitions or no Active Protection" % (nf(len({r["host"] for r in no_ap} | {r["host"] for r in stale_online})), "" if len({r["host"] for r in no_ap} | {r["host"] for r in stale_online}) == 1 else "s"), "Agent protection", sev("h")],
    ["F3", "%s stale and %s duplicate agent records; %s agents behind %s; %s failed definition updates" % (nf(S["defsStale"]), nf(S["duplicateHosts"]), nf(S["behind"]), latest, nf(acts.get("UpdateVapm", {}).get("notOk", 0))), "Agent hygiene", sev("m")],
    ["F4", "Backup covers %s device%s; %s of %s runs failed" % (nf(len(bk)), "" if len(bk) == 1 else "s", nf(bk_fail), nf(bk_runs)), "Backup", sev("m")],
    ["F5", "Alert volume inflated %.1fx by re-sends; web filtering false positives and acceptable-use breaches" % resend, "Alert quality", sev("l")],
], widths=["7%", "58%", "20%", "15%"], raw_cols=(3,)))

body += fb.section(2, "Scope and data", "<p>%s events in the window: %s alert events, %s activity events and %s EDR incident events.</p>" % (nf(ev_total), nf(alert_ev), nf(act_ev), nf(inc_ev))
                   + fb.column_chart([r["Date"][5:10] for r in trend], [("Activities", [r["activityEvents"] for r in trend]), ("Alerts", [r["alertEvents"] for r in trend]), ("EDR incidents", [r["incidentEvents"] for r in trend])], mode="stack", height=190, y_label="Events")
                   + '<p class="fn">Events per day (UTC). Agent inventory: %s agents in %s Acronis units, as at %s.</p>' % (nf(S["agents"]), nf(S["units"]), asof)
                   + ('' if not gaps else '<p class="fn"><b>Gaps:</b> %s. A gap is not zero activity.</p>' % "; ".join("%s (%s)" % g for g in gaps[:12])))

body += fb.section(3, "F1 · EDR cases", f1_text + f1)
body += fb.section(4, "F2 · Online agents with stale protection", "<p>%s online agent%s report no Active Protection component and %s online agent%s have definitions 30 days or more old. An online agent that does not update usually points to a broken update component rather than a powered-off machine.</p>" % (nf(S["noActiveProtection"]), "" if S["noActiveProtection"] == 1 else "s", nf(S["defsStaleOnline"]), "" if S["defsStaleOnline"] == 1 else "s")
                   + fb.table(["Agent", "Unit", "Installer", "Age (days)"], [[r["host"], unit(r["unit"]), r["installer"], r.get("days", "no component data")] for r in no_ap], widths=["32%", "30%", "16%", "22%"], num_cols=(3,)) if no_ap else "")
body += fb.section(5, "F3 · Agent hygiene",
                   "<p>%s agents have definitions 30 days or more old (%s offline, %s online), %s hosts have more than one agent record (%s records), and %s agents run an installer older than %s.</p>" % (nf(S["defsStale"]), nf(S["defsStaleOffline"]), nf(S["defsStaleOnline"]), nf(S["duplicateHosts"]), nf(S["duplicateRecords"]), nf(S["behind"]), latest)
                   + '<p class="cap">Age of each agent\'s most recent protection-definition update</p>' + age_chart
                   + '<p class="cap">Agents by installer version</p>' + fb.bar_rows(ver_items)
                   + stale_tbl + '<p class="cap">Agents by Acronis unit</p>' + unit_tbl
                   + '<p class="cap">Hosts with more than one agent record</p>' + dup_tbl
                   + '<p class="cap">Update activity outcomes in the window</p>' + upd_tbl
                   + "<p class=\"fn\">%s update activities failed across %s agents; the most common error codes are %s.</p>" % (nf(fail_runs), nf(fail_agents), ", ".join("%s (%s)" % (c, nf(n)) for c, n in err_codes.most_common(3))))
body += fb.section(6, "F4 · Backup", "<p>%s device%s ran Acronis backup jobs: %s of %s runs succeeded (%s%%), %s GB read. No server backup job appears in the feed.</p>" % (nf(len(bk)), "" if len(bk) == 1 else "s", nf(bk_ok), nf(bk_runs), pct(bk_ok, bk_runs), nf(round(bk_gb))) + bk_tbl)
body += fb.section(7, "F5 · Alert quality and web filtering",
                   "<p>The %s alert events describe only %s distinct alerts on %s devices (%.1f events per alert), because Acronis re-sends an alert each time it changes.</p>" % (nf(alert_ev), nf(uniq_alerts), nf(alert_devices), resend)
                   + '<p class="cap">Unique alerts by type</p>' + fb.bar_rows(type_items)
                   + "<p>%s malicious-URL blocks: %s of them are Amazon domains and %s were auto-resolved by Acronis. %s URL-category blocks on %s devices, of which %s were resolved. Blocks of this kind are acceptable-use matters for HR rather than security incidents.</p>" % (nf(len(url_block)), nf(url_block_amazon), nf(url_block_resolved), nf(len(url_cat)), nf(url_cat_devices), nf(url_cat_resolved))
                   + '<p class="cap">Devices producing the most alert events</p>' + noisy_tbl
                   + ("<p class=\"fn\">%s device%s carry%s a plan whose name contains \"macOS\"; the operating system of these devices was not part of this run and should be checked against the agent inventory.</p>" % (nf(len(macos_plan_devs)), "" if len(macos_plan_devs) == 1 else "s", "s" if len(macos_plan_devs) == 1 else "") if macos_plan_devs else ""))

html = fb.page(
    title="%s — Acronis Cyber Protect data review" % a.client,
    eyebrow="Acronis Cyber Protect data review",
    subtitle="EDR cases, agent protection, backup and alert quality from the Acronis Cyber Protect Cloud feed for %s." % a.client,
    meta="%s · Tenant %s · %s (%d days, %d archived) · Agents as at %s · Archive only" % (a.client, a.tenant, win, days, n_have, asof),
    kpis=kpis, band=band, body=body, steps=steps, method=method,
    footer_left="Acronis Cyber Protect data review · %s" % a.client, data_date=d(last_day))
open(a.out, "w").write(html)
print("wrote", a.out, len(html))

if a.summary_json:
    json.dump({"tenant": a.tenant, "from": a.dfrom, "to": a.dto, "daysExpected": days, "daysArchived": n_have, "gaps": gaps,
               "snapshotDay": snap_day, "snapshotBackfilled": snap_backfilled, "scriptHashes": sorted(hashes),
               "events": ev_total, "alertEvents": alert_ev, "uniqueAlerts": uniq_alerts, "alertDevices": alert_devices,
               "openEdrCases": open_cases, "agents": S["agents"], "online": S["online"], "staleDefinitions": S["defsStale"],
               "staleOnline": S["defsStaleOnline"], "noActiveProtection": S["noActiveProtection"], "onLatestInstaller": on_latest,
               "duplicateHosts": S["duplicateHosts"], "backupRuns": bk_runs, "backupFailed": bk_fail}, open(a.summary_json, "w"), indent=2, default=str)
    print("wrote", a.summary_json)
if len(hashes) > 1:
    print("note: %d script versions in the period (%s): days may not be comparable" % (len(hashes), ", ".join(sorted(hashes))))
