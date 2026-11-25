#!/usr/bin/env python3
"""Defender patch & hardening health report for ONE Fluency / Ingext tenant.

Reads the resource dumps of the msDefender* resource tables (gzipped JSONL issued by get_resource_dump_url) and two small
files written from tool output (alerts, scope), and writes a CISO-level report: where patching stopped (per server, from the
monthly updates Defender lists as missing), which exploitable CVEs to clear first, which servers are not in Defender at all,
which hardening controls are off fleet-wide, and the 30-day endpoint alert picture.

    python3 defender_patch_health.py check  --work <dir>
    python3 defender_patch_health.py render --work <dir> --account <acct> --customer "<Name>" [--asof yyyy-mm-dd] [--pdf]

<dir>/dumps/<resource>/<customer>.jsonl.gz   msDefenderMachine, msDefenderVulnerability, msDefenderSecureConfig, msDefenderAvHealth
<dir>/a_alerts.json                          kql_search response, de-duplicated alerts (see references/inputs.md)
<dir>/scope.json                             {"endpointIntegrations": [...], "dumpCounts": {resource: count}}

Every figure on the page is computed here from those files. The dumps never pass through the conversation.
"""
import argparse, csv, datetime as dt, glob, gzip, html, json, os, re, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = ["msDefenderMachine", "msDefenderVulnerability", "msDefenderSecureConfig", "msDefenderAvHealth"]
EXPLOIT = {"ExploitIsVerified", "ExploitIsInKit", "ExploitIsPublic"}
CRITHIGH = ("Critical", "High")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
# software that has no business on a server and carries exploited CVEs: remove rather than patch
REMOVE_ON_SERVERS = {"winrar": "WinRAR", "notepad++": "Notepad++", "teams_classic": "classic Teams (retired)",
                     "7-zip": "7-Zip", "wireshark": "Wireshark", "thunderbird": "Thunderbird"}
# anchored on purpose: "reads-fileserver" and "headsets01" are not domain controllers
ROLE_PATTERNS = [(r"(^|[-_.])dc\d*([-_.]|$)|ads\d+$", "Domain controller"), (r"backup|(^|[-_.])bkp", "Backup server"),
                 (r"(^|[-_.])hv\d*|hyperv|hyper-v", "Hyper-V host"), (r"sql", "SQL server"),
                 (r"print", "Print server"), (r"(^|[-_.]|[a-z])mst\d+$|(^|[-_.])(mgmt|jump)", "Management host"),
                 (r"srv\d*$", "Server")]
SERVER_NAME = re.compile(r"(srv|sql|dc[0-9]|hv[0-9]|app[0-9]|web[0-9]|mst[0-9])", re.I)
SILENT_DAYS = 30
STALE_DAYS = 7                # an enrolled server last seen longer ago than this is flagged next to its status
QUIET_DAYS = 90               # an unmanaged critical server last seen within this many days still needs an answer
CRITICAL_ROLES = ("Domain controller", "Backup server", "Hyper-V host")
OPEN_STATES = ("new", "inProgress")
# every Attack Surface Reduction rule is named "Block ..." except ransomware protection
ASR_EXTRA = {"Use advanced protection against ransomware"}


# -- loading -------------------------------------------------------------------------------------
def dump_files(work, resource):
    d = os.path.join(work, "dumps", resource)
    return sorted(glob.glob(d + "/*.jsonl.gz") + glob.glob(d + "/*.jsonl"))


def load(work, resource):
    """All records of a resource dump (inner object of the '@<resource>' envelope); [] if absent."""
    out = []
    for p in dump_files(work, resource):
        with (gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    out.append(r.get("@" + resource) or r)
    return out


def day_index(work, resource):
    for p in dump_files(work, resource):
        with (gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")) as f:
            line = f.readline()
            if line.strip():
                return json.loads(line).get("@dayIndex")
    return None


def load_json(work, name):
    p = os.path.join(work, name + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def kql_rows(work, name):
    raw = load_json(work, name)
    if raw is None:
        return []
    t = ((raw.get("data") or {}).get("Tables") or [{}])[0]
    cols = [c["ColumnName"] if isinstance(c, dict) else c for c in t.get("Columns", [])]
    return [dict(zip(cols, r)) for r in t.get("Rows", [])]


# -- helpers -------------------------------------------------------------------------------------
def short(name):
    return (name or "").split(".")[0].lower()


def role_of(name):
    n = short(name)
    for pat, role in ROLE_PATTERNS:
        if re.search(pat, n, re.I):
            return role
    return ""


def parse_day(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T")[:19]).date()
    except ValueError:
        return None


def month_index(y, m):
    return y * 12 + (m - 1)


def second_tuesday(y, m):
    d = dt.date(y, m, 1)
    first_tue = d + dt.timedelta(days=(1 - d.weekday()) % 7)
    return first_tue + dt.timedelta(days=7)


def latest_released(asof):
    """Month index of the newest Patch Tuesday on or before asof."""
    if asof >= second_tuesday(asof.year, asof.month):
        return month_index(asof.year, asof.month)
    return month_index(asof.year, asof.month) - 1


def fmt_month(idx):
    return "%s %d" % (MONTHS[idx % 12][:3], idx // 12)


def patch_gap(months, asof):
    """months: ['October 2026 Security Updates', ...] = monthly updates Defender says are missing.
    Returns (first_missing_idx, months_behind, outliers): the contiguous run that ends at the newest missing month
    (one skipped month allowed, since Defender lists only months that fix a CVE present on the device);
    older isolated months are outliers (usually a component, not the OS cumulative update)."""
    idx = sorted({month_index(int(m.group(2)), MONTHS.index(m.group(1)) + 1)
                  for s in months for m in [re.match(r"(\w+) (\d{4}) Security Updates", s or "")] if m and m.group(1) in MONTHS})
    if not idx:
        return None, 0, []
    start = idx[-1]
    for i in range(len(idx) - 1, 0, -1):
        if idx[i] - idx[i - 1] <= 2:
            start = idx[i - 1]
        else:
            break
    outliers = [i for i in idx if i < start]
    behind = latest_released(asof) - start + 1
    return start, max(behind, 0), outliers


def is_asr(setting):
    return setting["category"] == "Security controls" and (setting["name"].startswith("Block ") or setting["name"] in ASR_EXTRA)


def build_rev(build):
    """'10.0.17763.9487' -> (17763, 9487); None when the build has no revision (for example '17763')."""
    m = re.match(r"\d+\.\d+\.(\d+)\.(\d+)", str(build or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def build_flags(servers):
    """Cross-check each server's patch status against its OS build. Within one OS (same build number) a server that is
    Current must not run an older revision than a server that is Behind. Returns a list of plain-language findings."""
    flags = []
    for c in servers:
        rc = build_rev(c["build"])
        if c["status"] == "Current" and rc is None:
            flags.append("%s is marked Current but its build (%s) has no revision, so it cannot be cross-checked." % (c["name"], c["build"] or "unknown"))
            continue
        if c["status"] != "Current":
            continue
        for b in servers:
            rb = build_rev(b["build"])
            if b["status"] == "Behind" and rb and rb[0] == rc[0] and rc[1] < rb[1]:
                flags.append("%s is marked Current but runs build %s, older than %s (Behind, build %s)." % (c["name"], c["build"], b["name"], b["build"]))
                break
    return flags


def e(v):
    return html.escape("" if v is None else str(v))


def n(v):
    return "{:,}".format(int(v or 0))


def is_os_update_row(r):
    sw = str(r.get("SoftwareName") or "")
    return (sw.startswith("windows_server") or sw in ("windows_10", "windows_11")) and \
        str(r.get("RecommendedSecurityUpdate") or "").endswith("Security Updates")


# -- facts ---------------------------------------------------------------------------------------
def build_facts(work, asof, account, customer):
    F = {"account": account, "customer": customer or account, "asOf": asof.isoformat(), "notes": []}
    mach = load(work, "msDefenderMachine")
    vuln = load(work, "msDefenderVulnerability")
    cfgrows = load(work, "msDefenderSecureConfig")
    avrows = load(work, "msDefenderAvHealth")
    scope = load_json(work, "scope") or {}
    di = day_index(work, "msDefenderMachine")
    F["snapshot"] = di

    # coverage
    by_status = defaultdict(lambda: [0, 0])
    for m in mach:
        by_status[m.get("onboardingStatus")][0] += 1
        by_status[m.get("onboardingStatus")][1] += 1 if m.get("healthStatus") == "Active" else 0
    F["coverage"] = {k: {"devices": v[0], "active": v[1]} for k, v in sorted(by_status.items(), key=lambda kv: -kv[1][0])}
    F["devicesTotal"] = len(mach)
    onb = [m for m in mach if m.get("onboardingStatus") == "Onboarded"]
    F["onboarded"] = len(onb)
    F["eligibleActiveEndpoints"] = sum(1 for m in mach if m.get("onboardingStatus") == "CanBeOnboarded" and
                                       m.get("healthStatus") == "Active" and m.get("osPlatform") in ("Windows10", "Windows11"))
    by_id = {m["id"]: m for m in mach}
    onb_ids = {m["id"] for m in onb}
    for m in onb:
        d = parse_day(m.get("lastSeen"))
        m["_silent"] = (asof - d).days if d else None
    servers = [m for m in onb if str(m.get("osPlatform")).startswith("WindowsServer")]
    F["onboardedServers"] = len(servers)
    F["silentServers"] = [{"name": m["computerDnsName"], "os": m["osPlatform"], "lastSeen": str(m["lastSeen"])[:10],
                           "days": m["_silent"]} for m in servers if (m["_silent"] or 0) > SILENT_DAYS]
    F["silentOtherEnrolled"] = [{"name": m["computerDnsName"], "os": m["osPlatform"], "lastSeen": str(m["lastSeen"])[:10]}
                                for m in onb if m not in servers and (m["_silent"] or 0) > SILENT_DAYS]

    # servers Defender sees but does not manage
    onb_short = {short(m["computerDnsName"]): m for m in onb}
    um = []
    for m in mach:
        if m.get("onboardingStatus") == "Onboarded":
            continue
        name = m.get("computerDnsName") or ""
        if re.fullmatch(r"[0-9a-f-]{36}", name):
            continue                                    # GUID-named endpoints are not servers
        oss = str(m.get("osPlatform"))
        generic_server = oss == "Windows" and m.get("version") == "Server"
        if not (oss.startswith("WindowsServer") or generic_server or SERVER_NAME.search(name)):
            continue
        if not (oss.startswith("WindowsServer") or generic_server or role_of(name)):
            continue
        dup = onb_short.get(short(name))
        um.append({"name": name, "os": oss, "version": m.get("version"), "health": m.get("healthStatus"),
                   "lastSeen": str(m.get("lastSeen"))[:10], "ip": m.get("lastIpAddress"), "role": role_of(name),
                   "daysQuiet": (asof - parse_day(m.get("lastSeen"))).days if parse_day(m.get("lastSeen")) else None,
                   "duplicateOf": dup["computerDnsName"] if dup else None,
                   "duplicateLastSeen": str(dup["lastSeen"])[:10] if dup else None})
    order = {"Domain controller": 0, "Backup server": 1, "Hyper-V host": 2, "SQL server": 3}
    um.sort(key=lambda x: (x["health"] != "Active", order.get(x["role"], 9), x["name"].lower()))
    F["unmanagedServers"] = um
    F["unmanagedActive"] = [u for u in um if u["health"] == "Active" and not u["duplicateOf"]]
    F["reRegisteredActive"] = [u for u in um if u["health"] == "Active" and u["duplicateOf"]]
    F["unmanagedCriticalQuiet"] = [u for u in um if u["health"] != "Active" and not u["duplicateOf"] and u["role"] in CRITICAL_ROLES
                                   and u["daysQuiet"] is not None and u["daysQuiet"] <= QUIET_DAYS]

    legacy = defaultdict(lambda: {"n": 0, "active": 0, "sample": []})
    for m in mach:
        if m.get("onboardingStatus") == "Onboarded":
            continue
        oss, ver = str(m.get("osPlatform")), str(m.get("version"))
        if oss in ("WindowsXp", "Windows7", "Windows8", "Windows8Blue", "WindowsServer2008R2", "WindowsServer2012R2") or \
                (oss == "Windows10" and ver in ("1507", "1511", "1607", "1703", "1709", "1803", "1809", "1903", "1909", "2004", "20H2", "21H1")):
            g = legacy[(oss, ver)]
            g["n"] += 1
            g["active"] += 1 if m.get("healthStatus") == "Active" else 0
            nm = m.get("computerDnsName") or ""
            if len(g["sample"]) < 4 and nm and not re.fullmatch(r"[0-9a-f-]{36}", nm):    # GUID names say nothing about the device
                g["sample"].append(nm)
    F["legacyDiscovered"] = [{"os": k[0], "version": k[1], "devices": g["n"], "active": g["active"], "sample": g["sample"]}
                             for k, g in sorted(legacy.items(), key=lambda kv: -kv[1]["n"])]

    # vulnerabilities
    F["vulnTotal"] = len(vuln)
    matrix = defaultdict(lambda: {"findings": 0, "cves": set(), "devices": set(), "flag": 0})
    age = defaultdict(lambda: [0, 0])
    dev = defaultdict(lambda: {"total": 0, "critical": 0, "high": 0, "exploitable": 0, "oldest": None, "cvss": 0, "name": None})
    cves = {}
    sw = defaultdict(lambda: {"findings": 0, "critical": 0, "exploitable": 0, "devices": set()})
    patch = defaultdict(lambda: {"months": set(), "osVersion": None, "os": None})
    for r in vuln:
        sev, ex = r.get("VulnerabilitySeverityLevel") or "Unrated", r.get("ExploitabilityLevel")
        did = r.get("DeviceId")
        g = matrix[(sev, ex)]
        g["findings"] += 1; g["cves"].add(r.get("CveId")); g["devices"].add(did)
        g["flag"] += 1 if r.get("SecurityUpdateAvailable") is True else 0
        expl = ex in EXPLOIT
        d = dev[did]
        d["name"] = r.get("DeviceName"); d["total"] += 1
        d["critical"] += 1 if sev == "Critical" else 0
        d["high"] += 1 if sev == "High" else 0
        d["cvss"] = max(d["cvss"], r.get("CvssScore") or 0)
        if sev in CRITHIGH:
            fs = parse_day(r.get("FirstSeenTimestamp"))
            a = (asof - fs).days if fs else 0
            b = "0-15" if a <= 15 else "16-30" if a <= 30 else "31-90" if a <= 90 else "91-180" if a <= 180 else "180+"
            age[b][0] += 1; age[b][1] += 1 if expl else 0
            if expl:
                d["exploitable"] += 1
                fsd = str(r.get("FirstSeenTimestamp") or "")[:10]
                if fsd and (d["oldest"] is None or fsd < d["oldest"]):
                    d["oldest"] = fsd
                c = cves.setdefault(r.get("CveId"), {"cve": r.get("CveId"), "severity": sev, "exploit": ex, "devices": set(),
                                                     "cvss": 0, "software": []})
                c["devices"].add(did); c["cvss"] = max(c["cvss"], r.get("CvssScore") or 0)
                s = r.get("SoftwareName")
                if s and s not in c["software"] and len(c["software"]) < 4:
                    c["software"].append(s)
        s = sw[(r.get("SoftwareVendor"), r.get("SoftwareName"))]
        s["findings"] += 1; s["critical"] += 1 if sev == "Critical" else 0; s["exploitable"] += 1 if expl else 0
        s["devices"].add(did)
        if is_os_update_row(r):
            p = patch[did]
            p["months"].add(r["RecommendedSecurityUpdate"])
            p["osVersion"] = p["osVersion"] or r.get("OSVersion") or r.get("SoftwareVersion")

    F["vulnDevices"] = len(dev)
    F["vulnMatrix"] = [{"severity": k[0], "exploit": k[1], "findings": g["findings"], "cves": len(g["cves"]),
                        "devices": len(g["devices"])} for k, g in matrix.items()]
    F["exploitableCritHigh"] = sum(g["findings"] for k, g in matrix.items() if k[1] in EXPLOIT and k[0] in CRITHIGH)
    F["exploitableAny"] = sum(g["findings"] for k, g in matrix.items() if k[1] in EXPLOIT)
    F["securityUpdateFlagUnreliable"] = bool(vuln) and sum(g["flag"] for g in matrix.values()) == len(vuln)
    if F["securityUpdateFlagUnreliable"]:
        F["notes"].append("Defender's SecurityUpdateAvailable flag reads true on every finding; it was not relied on.")
    F["age"] = [{"bucket": b, "findings": age[b][0], "exploitable": age[b][1]} for b in ("0-15", "16-30", "31-90", "91-180", "180+")]
    F["exploitableOver180"] = age["180+"][1]
    F["exploitableAgeTotal"] = sum(v[1] for v in age.values())
    F["cves"] = sorted(({**c, "devices": len(c["devices"])} for c in cves.values()), key=lambda c: (-c["devices"], -c["cvss"]))
    F["software"] = sorted(({"SoftwareVendor": k[0], "SoftwareName": k[1], "findings": s["findings"], "critical": s["critical"],
                             "exploitable": s["exploitable"], "devices": len(s["devices"])} for k, s in sw.items()),
                           key=lambda s: -s["findings"])[:20]
    sw_names = {x for c in F["cves"] for x in c["software"]}
    F["removeOnServers"] = [REMOVE_ON_SERVERS[k] for k in REMOVE_ON_SERVERS if k in sw_names]
    F["patchRowsMatched"] = len(patch)

    # per-server join
    avm = {r.get("machineId"): r for r in avrows}
    cfg_by_dev = defaultdict(lambda: [0, 0])
    for r in cfgrows:
        if r.get("isApplicable") is True:
            c = cfg_by_dev[r.get("deviceId")]
            c[0] += 1; c[1] += 1 if r.get("isCompliant") is False else 0
    rows_ = []
    for m in servers:
        i = m["id"]; v = dev.get(i); p = patch.get(i); c = cfg_by_dev.get(i)
        start, behind, outl = patch_gap((p or {}).get("months") or [], asof)
        silent = (m["_silent"] or 0) > SILENT_DAYS
        build = (avm.get(i) or {}).get("osVersion") or (p or {}).get("osVersion") or str(m.get("osBuild") or "")
        if silent or v is None:
            status = "No data"
        elif behind >= 1:
            status = "Behind"
        else:
            status = "Current"
        oldest = (v or {}).get("oldest")
        rows_.append({"name": m["computerDnsName"], "role": role_of(m["computerDnsName"]), "os": m["osPlatform"], "build": build,
                      "health": m["healthStatus"], "lastSeen": str(m["lastSeen"])[:10], "silentDays": m["_silent"],
                      "exposure": m.get("exposureLevel"), "status": status, "stale": status == "Current" and (m["_silent"] or 0) > STALE_DAYS,
                      "total": (v or {}).get("total", 0), "critical": (v or {}).get("critical", 0),
                      "exploitable": (v or {}).get("exploitable", 0), "oldestExploitable": oldest,
                      "firstMissingUpdate": fmt_month(start) if start is not None else None,
                      "lastPatched": fmt_month(start - 1) if start is not None else None,
                      "monthsBehind": behind if status == "Behind" else 0, "outlierMonths": [fmt_month(o) for o in outl],
                      "configChecks": c[0] if c else None, "configFailing": c[1] if c else None})
    rows_.sort(key=lambda d: ({"Behind": 0, "Current": 1, "No data": 2}[d["status"]], -(d["monthsBehind"] or 0),
                              -(d["exploitable"] or 0), -(d["critical"] or 0)))
    F["servers"] = rows_
    F["buildFlags"] = build_flags(rows_)
    F["maxMonthsBehind"] = max([d["monthsBehind"] for d in rows_] + [0])
    F["serversBehind6"] = [d for d in rows_ if d["monthsBehind"] >= 6]
    F["serversBehind"] = [d for d in rows_ if d["status"] == "Behind"]
    F["serversCurrent"] = [d for d in rows_ if d["status"] == "Current"]
    F["serversNoData"] = [d for d in rows_ if d["status"] == "No data"]
    F["serversReporting"] = len(rows_) - len(F["serversNoData"])

    # devices Defender scanned that are not enrolled
    F["unenrolledScanned"] = sorted(
        [{"name": d["name"], "os": (by_id.get(i) or {}).get("osPlatform"), "version": (by_id.get(i) or {}).get("version"),
          "status": (by_id.get(i) or {}).get("onboardingStatus") or "not in device list",
          "health": (by_id.get(i) or {}).get("healthStatus"), "total": d["total"], "critical": d["critical"],
          "exploitable": d["exploitable"], "cvss": d["cvss"]} for i, d in dev.items() if i not in onb_ids],
        key=lambda x: (-x["critical"], -x["total"]))

    # configuration: only enrolled devices that report a full check set
    full = {i for i in onb_ids if (cfg_by_dev.get(i) or [0])[0] >= 20}
    ncfg = len(full) or 1
    fail = {}
    for r in cfgrows:
        if r.get("deviceId") in full and r.get("isApplicable") is True and r.get("isCompliant") is False \
                and r.get("configurationId") != "scid-20000":
            k = (r.get("configurationName"), r.get("configurationCategory"))
            f = fail.setdefault(k, {"devices": set(), "impact": 0})
            f["devices"].add(r["deviceId"]); f["impact"] = max(f["impact"], r.get("configurationImpact") or 0)
    cf = sorted(({"name": k[0], "category": k[1], "devices": len(f["devices"]), "impact": f["impact"]} for k, f in fail.items()),
                key=lambda x: (-x["impact"], -x["devices"], x["name"]))
    asr = [x for x in cf if is_asr(x)]
    F["configDevices"] = len(full)
    F["configFailingSettings"] = len(cf)
    F["asrOffAll"] = [x["name"] for x in asr if x["devices"] >= ncfg]
    F["baselineFailAll"] = [x for x in cf if x["devices"] >= ncfg and x not in asr]
    F["partialFailAll"] = [x for x in cf if x["devices"] < ncfg and x["impact"] >= 8]
    pct = [round(100.0 * c[1] / c[0]) for i, c in cfg_by_dev.items() if i in full and c[0]]
    F["configFailPct"] = [min(pct), max(pct)] if pct else None
    av_def_fail = next((x["devices"] for x in cf if x["name"] == "Update Microsoft Defender Antivirus definitions"), 0)

    # antivirus
    F["av"] = {"devices": len(avrows), "enrolledServers": len(servers),
               "active": sum(1 for r in avrows if str(r.get("avMode")) == "0"),
               "signaturesCurrent": sum(1 for r in avrows if str(r.get("avIsSignatureUpToDate")).lower() == "true"),
               "engineCurrent": sum(1 for r in avrows if str(r.get("avIsEngineUpToDate")).lower() == "true"),
               "platformCurrent": sum(1 for r in avrows if str(r.get("avIsPlatformUpToDate")).lower() == "true"),
               "neverFullScan": sum(1 for r in avrows if not r.get("fullScanTime")),
               "definitionsCheckFailing": av_def_fail}
    F["av"]["healthy"] = sum(1 for r in avrows if str(r.get("avMode")) == "0" and
                             str(r.get("avIsSignatureUpToDate")).lower() == "true" and
                             str(r.get("avIsEngineUpToDate")).lower() == "true" and
                             str(r.get("avIsPlatformUpToDate")).lower() == "true")

    # alerts: de-duplicated by alert id upstream (see references/inputs.md)
    ar = kql_rows(work, "a_alerts")
    F["alerts"] = alerts_facts(ar)

    # connector coverage
    ints = scope.get("endpointIntegrations") or []
    custs = sorted({os.path.basename(p).split(".jsonl")[0] for p in dump_files(work, "msDefenderMachine")})
    F["endpointIntegrations"] = ints
    F["scopeCustomers"] = custs
    F["endpointIntegrationsNoData"] = [x for x in ints if x not in custs]
    return F


def alerts_facts(ar):
    """ar: rows of the de-duplicated alert query (one row per source, severity, status, age bucket, title).
    Counts for the last 30 days use the 0-30 bucket; open alerts are counted at any age, and those older than 30 days are
    reported separately. Rows without a bucket (older files) are treated as 0-30."""
    for r in ar:
        r.setdefault("bucket", "0-30"); r.setdefault("oldestDays", 0); r["t"] = r.get("t") or ""
    tot = lambda rs: sum(r["alerts"] for r in rs)
    by = lambda rs, k: sorted(Counter({v: tot([r for r in rs if r[k] == v]) for v in {r[k] for r in rs}}).items(), key=lambda kv: -kv[1])
    titles = lambda rs: sorted(Counter({t: tot([r for r in rs if r["t"] == t]) for t in {r["t"] for r in rs if r["t"]}}).items(),
                               key=lambda kv: -kv[1])
    win = [r for r in ar if r["bucket"] == "0-30"]
    opn = [r for r in ar if r["status"] in OPEN_STATES]
    aged = [r for r in opn if r["bucket"] != "0-30"]
    high_open = [r for r in opn if r["severity"] == "high"]
    ep = [r for r in win if r["serviceSource"] == "microsoftDefenderForEndpoint"]
    ep_open = [r for r in opn if r["serviceSource"] == "microsoftDefenderForEndpoint"]
    agg = {}
    for r in aged:
        k = (r["serviceSource"], r["severity"]); g = agg.setdefault(k, {"alerts": 0, "oldestDays": 0})
        g["alerts"] += r["alerts"]; g["oldestDays"] = max(g["oldestDays"], r["oldestDays"] or 0)
    order = {"high": 0, "medium": 1, "low": 2, "informational": 3}
    aged_rows = sorted(({"source": k[0], "severity": k[1], **g} for k, g in agg.items()), key=lambda x: (order.get(x["severity"], 9), -x["alerts"]))
    sev = Counter()
    for x in aged_rows:
        sev[x["severity"]] += x["alerts"]
    return {"distinct": tot(win), "bySource": by(win, "serviceSource"), "bySeverity": by(win, "severity"), "byStatus": by(win, "status"),
            "high": tot([r for r in win if r["severity"] == "high"]), "highOpen": tot(high_open), "highOpenTitles": titles(high_open),
            "highOpenBySource": by(high_open, "serviceSource"),
            "endpoint": tot(ep), "endpointOpen": tot(ep_open), "endpointTitles": titles(ep),
            "openAged": tot(aged), "openAgedBySeverity": dict(sev), "openAgedRows": aged_rows,
            "openAgedOldestDays": max([x["oldestDays"] for x in aged_rows] + [0]),
            "openAgedActionable": tot([r for r in aged if r["severity"] != "informational"])}


# -- narrative and actions ---------------------------------------------------------------------
def actions(F):
    out = []
    # ranked by risk: exploitable crit/high findings, then months behind; the role is shown, not ranked
    stalled = sorted(F["serversBehind6"], key=lambda d: (-(d["exploitable"] or 0), -d["monthsBehind"], d["name"]))
    for d in stalled[:3]:
        role = (" (%s)" % d["role"].lower()) if d["role"] else ""
        out.append(("P1", "Patch <code>%s</code>%s to the current cumulative update" % (e(d["name"]), role),
                    "%d monthly updates behind (last patched %s); %d exploitable crit/high findings" % (d["monthsBehind"], d["lastPatched"], d["exploitable"]),
                    "One update + reboot"))
    if len(stalled) > 3:
        out.append(("P1", "Patch the other %d servers stalled more than 6 months: " % (len(stalled) - 3) + ", ".join("<code>%s</code>" % e(d["name"]) for d in stalled[3:7]),
                    "; ".join("%s %d months behind" % (e(short(d["name"])), d["monthsBehind"]) for d in stalled[3:7]), "One cumulative update each"))
    crit_um = [u for u in F["unmanagedServers"] if u["health"] == "Active" and not u["duplicateOf"] and u["role"] in CRITICAL_ROLES]
    if crit_um:
        out.append(("P1", "Onboard the unmanaged critical servers: " + ", ".join("<code>%s</code>" % e(u["name"]) for u in crit_um[:5]),
                    "Active on the network with no EDR and no configuration check", "Onboarding package"))
    quiet = F["unmanagedCriticalQuiet"]
    if quiet:
        out.append(("P1", "Onboard, or confirm retired, the critical servers that have gone quiet: " + ", ".join("<code>%s</code>" % e(u["name"]) for u in quiet[:5]),
                    "; ".join("%s (%s) last seen %s" % (e(short(u["name"])), e(u["role"].lower()), e(u["lastSeen"])) for u in quiet[:5]) + "; never enrolled, so no EDR or scan",
                    "Onboarding package or decommission"))
    if F["asrOffAll"]:
        out.append(("P2", "Turn on Attack Surface Reduction rules (audit mode first), ransomware protection and LAPS",
                    "%d ASR rules off on all %d servers that report configuration" % (len(F["asrOffAll"]), F["configDevices"]),
                    "Policy change, no patching"))
    if F["serversNoData"] or F["reRegisteredActive"]:
        names = [d["name"] for d in F["serversNoData"]] or [u["duplicateOf"] for u in F["reRegisteredActive"]]
        out.append(("P2", "Repair or retire the enrolled servers that stopped reporting: " + ", ".join("<code>%s</code>" % e(x) for x in names[:4]),
                    "No scan data, so their patch state is unknown%s" % ("; the same machines are active again under a new Defender record" if F["reRegisteredActive"] else ""),
                    "Re-onboard or decommission"))
    if F["unenrolledScanned"]:
        top = F["unenrolledScanned"][0]
        out.append(("P2", "Enrol the %d devices Defender has scanned but does not manage" % len(F["unenrolledScanned"]),
                    "%s carries %d critical findings; %s findings in all across these devices" % (e(top["name"]), top["critical"], n(sum(x["total"] for x in F["unenrolledScanned"]))),
                    "Onboarding package / Intune"))
    if F["eligibleActiveEndpoints"]:
        out.append(("P2", "Enrol workstations in Defender",
                    "%s active Windows 10/11 devices are eligible but not enrolled" % n(F["eligibleActiveEndpoints"]), "Onboarding package / Intune"))
    a = F["alerts"]
    if a["openAgedActionable"]:
        sv = a["openAgedBySeverity"]
        out.append(("P2", "Close out the %d alerts that have been open more than 30 days" % a["openAgedActionable"],
                    "Oldest %d days; %s" % (a["openAgedOldestDays"], ", ".join("%s %d" % (k, sv[k]) for k in ("high", "medium", "low") if sv.get(k))),
                    "SOC triage"))
    if a["highOpen"]:
        titles = ", ".join("%s (%d)" % (t, c) for t, c in a["highOpenTitles"][:3])
        out.append(("P2", "Triage the %d high-severity Defender alerts still open (all products, not only endpoint)" % a["highOpen"], e(titles), "SOC triage"))
    if F["endpointIntegrationsNoData"]:
        out.append(("P3", "Fix the Defender endpoint connection(s) with no data: " + ", ".join("<code>%s</code>" % e(x) for x in F["endpointIntegrationsNoData"]),
                    "Installed and in use, but no device, vulnerability or configuration data delivered", "App permissions / licence check"))
    if F["removeOnServers"]:
        out.append(("P3", "Review and remove " + ", ".join(F["removeOnServers"]) + " from servers",
                    "Exploited CVEs in software that is rarely needed on a server", "Uninstall"))
    return out


def summary_html(F):
    p = []
    worst = F["serversBehind6"][:2]
    if worst:
        w = "; ".join("<code>%s</code>%s is %d monthly updates behind (last patched %s)" % (
            e(d["name"]), " (domain controller)" if d["role"] == "Domain controller" else "", d["monthsBehind"], d["lastPatched"]) for d in worst)
        p.append("Windows security updates have stopped on %d of the %d enrolled servers that report: %s. %d of %d exploitable Critical/High findings "
                 "have been open more than 180 days, so the remedy is to restart server patching, not to chase individual CVEs."
                 % (len(F["serversBehind6"]), F["serversReporting"], w, F["exploitableOver180"], F["exploitableAgeTotal"]))
    if F["serversNoData"]:
        p.append("%d enrolled servers have sent nothing for more than %d days (%s), so their patch state is unknown, not current."
                 % (len(F["serversNoData"]), SILENT_DAYS, ", ".join("<code>%s</code>" % e(d["name"]) for d in F["serversNoData"][:4])))
    um = F["unmanagedActive"]
    if um:
        roles = sorted({u["role"] for u in um if u["role"] and u["role"] != "Server"})
        p.append("%d active server-class devices are on the network but not enrolled in Defender%s, so nothing on them is protected by EDR."
                 % (len(um), (" (" + ", ".join(r.lower() + "s" for r in roles) + ")") if roles else ""))
    if F["unenrolledScanned"]:
        top = F["unenrolledScanned"][0]
        p.append("Defender has also scanned %d devices it does not manage; they carry %s findings, led by <code>%s</code> with %d critical."
                 % (len(F["unenrolledScanned"]), n(sum(x["total"] for x in F["unenrolledScanned"])), e(top["name"]), top["critical"]))
    if F["asrOffAll"]:
        p.append("Hardening that would blunt an attack in the meantime is off on every server: all %d Attack Surface Reduction rules, "
                 "including the LSASS credential-theft block%s." % (len(F["asrOffAll"]),
                 ", plus " + ", ".join(x["name"].split(" (")[0] for x in F["baselineFailAll"][:3]) if F["baselineFailAll"] else ""))
    a = F["av"]
    if a["devices"]:
        p.append("Antivirus: %d of %d enrolled servers run Defender Antivirus in active mode with current signatures, engine and platform; "
                 "%d have never run a full scan%s."
                 % (a["healthy"], a["enrolledServers"], a["neverFullScan"],
                    ("; Defender's own configuration check says definitions are out of date on %d" % a["definitionsCheckFailing"]) if a["definitionsCheckFailing"] else ""))
    return "".join("<p>%s</p>" % x for x in p)


# -- render --------------------------------------------------------------------------------------
def find_brand():
    cands = [os.environ.get("FLUENCY_BRAND_DIR"), os.path.join(HERE, "..", "..", "fluency-report", "scripts"),
             os.path.join(HERE, "..", "..", "..", "SKILLS", "fluency-report", "scripts")]
    for c in cands:
        if c and os.path.exists(os.path.join(c, "fluency_brand.py")):
            sys.path.insert(0, os.path.abspath(c))
            import fluency_brand
            return fluency_brand
    sys.exit("fluency-report skill not found: install it next to this skill or set FLUENCY_BRAND_DIR to its scripts/ folder.")


def render(F, brand):
    _table = brand.table

    class _FB:                                      # every cell below is escaped with e() already
        def __getattr__(self, k):
            return getattr(brand, k)

        def table(self, headers, rows, **kw):
            kw["raw_cols"] = tuple(range(len(headers)))
            return _table(headers, rows, **kw)
    fb = _FB()
    acts = actions(F)
    a = F["alerts"]; av = F["av"]
    um_active = len(F["unmanagedActive"])
    kpis = [fb.kpi("Devices enrolled in Defender", "%d / %d" % (F["onboarded"], F["devicesTotal"]), color="red" if F["onboarded"] < F["devicesTotal"] / 4 else ""),
            fb.kpi("Longest server patch gap", "%d mo" % F["maxMonthsBehind"], color="red" if F["maxMonthsBehind"] >= 6 else ""),
            fb.kpi("Exploitable crit/high findings > 180 days", "%d of %d" % (F["exploitableOver180"], F["exploitableAgeTotal"]), color="red" if F["exploitableOver180"] else ""),
            fb.kpi("Unmanaged active servers", str(um_active), color="amber"),
            fb.kpi("ASR rules off on every server", str(len(F["asrOffAll"])), color="amber" if F["asrOffAll"] else ""),
            fb.kpi("Enrolled servers with healthy AV", "%d / %d" % (av["healthy"], av["enrolledServers"]))]
    band = [("01 — What is exposed", "<p>%d servers stalled on patching; %d servers outside Defender; %d enrolled servers silent; %s workstations not enrolled.</p>"
             % (len(F["serversBehind6"]), um_active, len(F["serversNoData"]), n(F["eligibleActiveEndpoints"]))),
            ("02 — What is already right", "<p>Defender Antivirus healthy on %d of %d enrolled servers; %d servers fully current on Windows updates.</p>"
             % (av["healthy"], av["enrolledServers"], len(F["serversCurrent"]))),
            ("03 — What to fix first", "<p>%s</p>" % (acts[0][1] if acts else "Nothing urgent."))]

    body = []
    scope = ("This report covers the devices Defender manages in %s. " % ", ".join("<code>%s</code>" % e(c) for c in F["scopeCustomers"]))
    if F["endpointIntegrationsNoData"]:
        scope += ("<strong>The endpoint connection(s) %s are installed but have delivered no Defender data, so their devices are absent from every figure; "
                  "the totals below may cover only part of the estate.</strong> " % ", ".join("<code>%s</code>" % e(x) for x in F["endpointIntegrationsNoData"]))
    scope += ("Defender's data has no attack-vector (remotely exploitable) field: exploitable below means a public, verified or "
              "kit-packaged exploit exists.")
    body.append(fb.note(scope, "amber" if F["endpointIntegrationsNoData"] else ""))

    body.append(fb.section(1, "Priority actions", fb.table(["", "Action", "Why", "Effort"],
                [[fb.priority(p), act, why, e(eff)] for p, act, why, eff in acts], widths=["7%", "38%", "38%", "17%"])))

    rows_ = []
    for d in F["servers"]:
        nm = "<code>%s</code>%s" % (e(d["name"]), (" " + fb.tag(d["role"], "gray")) if d["role"] else "")
        if d["status"] == "Behind":
            gap = e("%d months · last patched %s" % (d["monthsBehind"], d["lastPatched"]))
        elif d["status"] == "Current":
            gap = e("Current · last seen %s days ago" % d["silentDays"]) if d["stale"] else "Current"
        else:
            gap = e("No data · silent %s days" % d["silentDays"]) if (d["silentDays"] or 0) > SILENT_DAYS else "No data · no scan results"
        rows_.append([nm, "%s · %s" % (e(d["os"].replace("WindowsServer", "Server ")), e(d["build"])), gap, n(d["exploitable"]), n(d["critical"]),
                      e(d["oldestExploitable"] or "—"), ("%s / %s" % (d["configFailing"], d["configChecks"])) if d["configChecks"] else "—"])
    sec = ("<p>Patch level comes from the monthly cumulative updates Defender lists as missing on each server: the first missing month "
           "marks where patching stopped. Current means Defender scanned the server and lists no missing monthly update; No data means it did not.</p>")
    sec += fb.table(["Server", "OS · build", "Windows update gap", "Exploitable crit/high", "Critical", "Oldest exploitable open", "Config failing"],
                    rows_, num_cols=(3, 4),
                    row_class=lambda r: "sev-high" if "months" in r[2] and int(r[2].split()[0]) >= 6 else "")
    if F["buildFlags"]:
        sec += fb.note("Build check: " + " ".join(e(x) for x in F["buildFlags"]), "amber")
    else:
        sec += fb.note("Build check: every server marked Current runs a build at least as new as every Behind server of the same operating system.")
    if F["silentOtherEnrolled"]:
        sec += fb.note("Other enrolled devices silent for more than %d days: %s." % (SILENT_DAYS, ", ".join(
            "<code>%s</code> (%s, last seen %s)" % (e(s["name"]), e(s["os"]), e(s["lastSeen"])) for s in F["silentOtherEnrolled"])), "amber")
    body.append(fb.section(2, "Patching: where it stopped", sec))

    if F["unmanagedServers"]:
        ur = [["<code>%s</code>" % e(u["name"]), e(u["role"] or "—"), e("%s %s" % (u["os"], u["version"])), e(u["health"]), e(u["lastSeen"]),
               ("Re-registered copy of enrolled server <code>%s</code> (enrolled record silent since %s)" % (e(u["duplicateOf"]), e(u["duplicateLastSeen"]))) if u["duplicateOf"] else ""]
              for u in F["unmanagedServers"]]
        body.append(fb.section(3, "Servers outside Defender", "<p>Server-class devices Defender has discovered on the network but does not manage: no EDR "
                               "and no configuration check. Re-registered copies are the same machine as an enrolled server, not an extra server. "
                               "Roles are inferred from host names; confirm them.</p>" +
                               fb.table(["Device", "Likely role", "OS (as discovered)", "Health", "Last seen", "Note"], ur)))

    cr = [[e(k), n(v["devices"]), n(v["active"])] for k, v in F["coverage"].items()]
    cov = ("<p>Defender has discovered %s devices and manages %d. Vulnerability and configuration data come mainly from managed devices; "
           "a few unmanaged devices are scanned too (section 5).</p>" % (n(F["devicesTotal"]), F["onboarded"]))
    cov += fb.table(["Enrolment status", "Devices", "Active"], cr, num_cols=(1, 2))
    if F["legacyDiscovered"]:
        lr = [[e("%s %s" % (x["os"], x["version"])), n(x["devices"]), n(x["active"]), e(", ".join(x["sample"]))] for x in F["legacyDiscovered"]]
        cov += fb.callout("watch", "Data quality", "Unsupported operating systems on discovered devices are unconfirmed",
                          "Defender guesses the OS of devices it does not manage from network traffic. Workstation-named devices reported as "
                          "Windows XP or early Windows 10 are more likely current laptops that are simply not enrolled; confirm by onboarding them.")
        cov += fb.table(["OS as discovered", "Devices", "Active", "Examples"], lr, num_cols=(1, 2))
    body.append(fb.section(4, "Coverage", cov))

    order_sev = ["Critical", "High", "Medium", "Low", "Unrated"]
    vr = [[e(x["severity"]), e(x["exploit"].replace("ExploitIs", "").replace("NoExploit", "None known")), n(x["findings"]), n(x["cves"]), n(x["devices"])]
          for x in sorted(F["vulnMatrix"], key=lambda x: (x["exploit"] == "NoExploit", order_sev.index(x["severity"]) if x["severity"] in order_sev else 9))]
    v = "<p>%s open findings (CVE × device) across %d devices; %s have a known exploit.</p>" % (n(F["vulnTotal"]), F["vulnDevices"], n(F["exploitableAny"]))
    v += fb.table(["Severity", "Exploit", "Findings", "Unique CVEs", "Devices"], vr, num_cols=(2, 3, 4),
                  row_class=lambda r: "sev-high" if r[1] != "None known" and r[0] in ("Critical", "High") else "")
    v += "<h3>Age of Critical and High findings</h3>" + fb.column_chart(
        ["0–15 d", "16–30 d", "31–90 d", "91–180 d", ">180 d"],
        [("All crit/high", [x["findings"] for x in F["age"]]), ("Exploitable", [x["exploitable"] for x in F["age"]])], y_label="Findings")
    v += "<h3>Exploitable CVEs to clear first (top 15 of %d)</h3>" % len(F["cves"]) + fb.table(
        ["CVE", "Severity", "Exploit", "CVSS", "Software", "Devices"],
        [[e(c["cve"]), e(c["severity"]), e(c["exploit"].replace("ExploitIs", "")), e(c["cvss"]), e(", ".join(s.replace("windows_server_", "Server ") for s in c["software"])), n(c["devices"])]
         for c in F["cves"][:15]], num_cols=(3, 5))
    v += "<h3>Where the findings come from</h3>" + fb.table(
        ["Software", "Findings", "Critical", "Exploitable", "Devices"],
        [[e(s["SoftwareName"]), n(s["findings"]), n(s["critical"]), n(s["exploitable"]), n(s["devices"])] for s in F["software"][:12]], num_cols=(1, 2, 3, 4))
    if F["unenrolledScanned"]:
        v += "<h3>Scanned devices that are not enrolled</h3><p>Defender holds vulnerability findings for these devices although it does not manage them. They are not in the server tables above.</p>" + fb.table(
            ["Device", "OS (as discovered)", "Enrolment", "Health", "Findings", "Critical", "Exploitable crit/high", "Max CVSS"],
            [["<code>%s</code>" % e(x["name"]), e("%s %s" % (x["os"], x["version"])), e(x["status"]), e(x["health"] or "—"), n(x["total"]), n(x["critical"]),
              n(x["exploitable"]), e(x["cvss"])] for x in F["unenrolledScanned"]], num_cols=(4, 5, 6, 7))
    body.append(fb.section(5, "Vulnerabilities", v))

    c = ""
    if F["configFailPct"]:
        c += "<p>Each server fails %d%%–%d%% of the Defender security checks that apply to it (%d distinct failing settings in all). " % (
            F["configFailPct"][0], F["configFailPct"][1], F["configFailingSettings"])
        c += "Failures that are identical on every server point to a missing baseline policy rather than drift.</p>"
    if F["asrOffAll"]:
        c += fb.callout("act", "Off on all %d servers" % F["configDevices"], "%d Attack Surface Reduction rules" % len(F["asrOffAll"]),
                        e("; ".join(F["asrOffAll"])))
    if F["baselineFailAll"]:
        c += "<h3>Other settings failing on every server (top 12 of %d, by impact)</h3>" % len(F["baselineFailAll"]) + fb.table(
            ["Setting", "Category", "Impact"], [[e(x["name"]), e(x["category"]), e(x["impact"])] for x in F["baselineFailAll"][:12]], num_cols=(2,))
    if F["partialFailAll"]:
        c += "<h3>Failing on some servers (top 12 of %d with impact 8 or more)</h3>" % len(F["partialFailAll"]) + fb.table(
            ["Setting", "Servers", "Impact"], [[e(x["name"]), n(x["devices"]), e(x["impact"])] for x in F["partialFailAll"][:12]], num_cols=(1, 2))
    c += fb.note("Antivirus: %d of %d reporting servers in active mode; signatures current on %d, engine on %d, platform on %d; %d have never run a full scan. "
                 "%d enrolled servers are not in the antivirus data."
                 % (av["active"], av["devices"], av["signaturesCurrent"], av["engineCurrent"], av["platformCurrent"], av["neverFullScan"],
                    av["enrolledServers"] - av["devices"]))
    body.append(fb.section(6, "Configuration and hardening", c))

    al = "<p>Alerts created in the last 30 days, counted once per alert (the latest state of each): %s distinct across all Defender products.</p>" % n(a["distinct"])
    al += fb.table(["Product (service source)", "Alerts"], [[e(s), n(k)] for s, k in a["bySource"]], num_cols=(1,))
    al += "<p><strong>Endpoint:</strong> %d alert(s), %d still open%s.</p>" % (
        a["endpoint"], a["endpointOpen"], (" (" + e(", ".join("%s (%d)" % (t, k) for t, k in a["endpointTitles"][:3])) + ")") if a["endpointTitles"] else "")
    al += "<p><strong>High severity, all products:</strong> %d alerts in the last 30 days; %d high-severity alerts are open now%s. Most alerts here are email and identity, not endpoint.</p>" % (
        a["high"], a["highOpen"], (": " + e(", ".join("%s (%d)" % (t, k) for t, k in a["highOpenTitles"][:5]))) if a["highOpenTitles"] else "")
    if a["openAgedRows"]:
        al += "<h3>Open for more than 30 days</h3><p>%d alerts created more than 30 days ago have not been closed (oldest %d days).</p>" % (a["openAged"], a["openAgedOldestDays"])
        al += fb.table(["Product (service source)", "Severity", "Open alerts", "Oldest (days)"],
                       [[e(x["source"]), e(x["severity"]), n(x["alerts"]), n(x["oldestDays"])] for x in a["openAgedRows"]], num_cols=(2, 3),
                       row_class=lambda r: "sev-high" if r[1] == "high" else "")
    body.append(fb.section(7, "Alerts", al))

    method = ("<p>Microsoft Defender for Endpoint resource dumps Fluency syncs for the tenant (msDefenderMachine, msDefenderVulnerability, "
              "msDefenderSecureConfig, msDefenderAvHealth), snapshot %s, processed in full with no row limits; Defender alerts from the "
              "MSDefender stream (the last 180 days, reduced to the latest state of each alert, so alerts open for longer than 30 days are counted); and the tenant's integration list. Patch gap = months from the first "
              "missing monthly cumulative update Defender reports for the server to the latest Patch Tuesday. Exploitable = verified, in-kit or "
              "public exploit. Roles are inferred from host names.%s</p>"
              % (e(F["snapshot"] or F["asOf"]), (" " + " ".join(e(x) for x in F["notes"])) if F["notes"] else ""))
    return fb.page(title="%s — Defender Patch & Hardening Health" % F["customer"], eyebrow="Endpoint health report",
                   subtitle="Where server patching stopped, what is exposed because of it, and the controls that would contain an attack in the meantime.",
                   meta="Tenant %s · Microsoft Defender for Endpoint · Read-only" % F["account"], kpis=kpis, band=band,
                   summary=summary_html(F), body="".join(body), method=method, data_date=F["asOf"],
                   footer_left="%s · Defender patch & hardening health" % F["customer"])


def write_csvs(F, work):
    def w(name, keys, rows):
        with open(os.path.join(work, name), "w", newline="") as f:
            cw = csv.writer(f); cw.writerow(keys)
            for r in rows:
                cw.writerow([r.get(k) if not isinstance(r.get(k), list) else ";".join(map(str, r[k])) for k in keys])
    w("servers.csv", ["name", "role", "os", "build", "health", "lastSeen", "status", "monthsBehind", "lastPatched", "firstMissingUpdate",
                      "exploitable", "critical", "total", "oldestExploitable", "configFailing", "configChecks"], F["servers"])
    w("unmanaged_servers.csv", ["name", "role", "os", "version", "health", "lastSeen", "ip", "duplicateOf"], F["unmanagedServers"])
    w("exploitable_cves.csv", ["cve", "severity", "exploit", "cvss", "devices", "software"], F["cves"])
    w("unenrolled_scanned_devices.csv", ["name", "os", "version", "status", "health", "total", "critical", "exploitable", "cvss"], F["unenrolledScanned"])


# -- check ---------------------------------------------------------------------------------------
def check(work, asof=None):
    problems, warns = [], []
    scope = load_json(work, "scope") or {}
    counts = scope.get("dumpCounts") or {}
    if not scope:
        warns.append("scope.json missing: connector coverage cannot be checked")
    for res in RESOURCES:
        files = dump_files(work, res)
        if not files:
            problems.append("no dump for %s under dumps/%s/" % (res, res)); continue
        try:
            rs = load(work, res)
        except (EOFError, OSError, ValueError) as ex:
            problems.append("%s dump is unreadable or truncated (%s): download it again" % (res, ex)); continue
        if res in counts and counts[res] != len(rs):
            problems.append("%s has %d rows, list_resource_dumps says %d: partial download" % (res, len(rs), counts[res]))
        if not rs and res in ("msDefenderMachine", "msDefenderVulnerability"):
            problems.append("%s dump is empty: does the tenant import Defender for Endpoint?" % res)
        elif not rs:
            warns.append("%s dump is empty: its section of the report will be empty" % res)
        elif res == "msDefenderMachine" and not any(r.get("onboardingStatus") == "Onboarded" for r in rs):
            problems.append("msDefenderMachine lists no onboarded device")
    if not os.path.exists(os.path.join(work, "a_alerts.json")):
        warns.append("a_alerts.json missing: the alerts section will be empty")
    di = day_index(work, "msDefenderMachine")
    if di and asof:
        d = parse_day("%s-%s-%s" % (di[:4], di[4:6], di[6:8]))
        if d and (asof - d).days > 2:
            warns.append("device snapshot is %d days older than the as-of date (%s)" % ((asof - d).days, di))
    if not problems:
        # the Windows update label is what the patch gap is built from: no match anywhere means the label changed
        vuln = load(work, "msDefenderVulnerability")
        if vuln and not any(is_os_update_row(r) for r in vuln):
            warns.append("no finding carries a '<Month> <Year> Security Updates' update name: every server would read as Current. Check the field.")
    for p in problems:
        print("PROBLEM", p)
    for w_ in warns:
        print("WARN", w_)
    if not problems:
        print("OK %d dumps" % len(RESOURCES))
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "render", "window"])
    ap.add_argument("--work", default=".")
    ap.add_argument("--account", default="")
    ap.add_argument("--customer", default="")
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    asof = dt.date.fromisoformat(a.asof)
    if a.cmd == "window":                      # rangeFrom / rangeTo for the alert query, epoch milliseconds
        end = dt.datetime(asof.year, asof.month, asof.day, 23, 59, 59, tzinfo=dt.timezone.utc)
        print("rangeFrom=%d rangeTo=%d" % (int((end - dt.timedelta(days=a.days)).timestamp() * 1000), int(end.timestamp() * 1000)))
        return
    if a.cmd == "check":
        sys.exit(check(a.work, asof))
    if check(a.work, asof):
        sys.exit(1)
    F = build_facts(a.work, asof, a.account, a.customer)
    fb = find_brand()
    out = os.path.join(a.work, "defender_patch_health.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(F, fb))
    with open(os.path.join(a.work, "facts.json"), "w") as f:
        json.dump(F, f, indent=1, default=str)
    write_csvs(F, a.work)
    print("as of %s · %d/%d enrolled · %d servers ≥6 months behind (max %d) · %d no data · %d unmanaged active servers · %d ASR rules off everywhere"
          % (F["asOf"], F["onboarded"], F["devicesTotal"], len(F["serversBehind6"]), F["maxMonthsBehind"], len(F["serversNoData"]),
             len(F["unmanagedActive"]), len(F["asrOffAll"])))
    print("wrote", out)
    if a.pdf:
        pdf = out[:-5] + ".pdf"
        try:
            fb.to_pdf(out, pdf)
            print("wrote", pdf)
        except Exception as ex:   # node/playwright missing
            print("PDF not written (%s). Run: node <fluency-report>/scripts/render_pdf.mjs --input %s --output %s" % (ex, out, pdf))


if __name__ == "__main__":
    main()
