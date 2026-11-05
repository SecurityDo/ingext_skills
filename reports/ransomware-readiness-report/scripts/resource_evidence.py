#!/usr/bin/env python3
"""Compute ransomware-readiness evidence from locally downloaded resource dumps.

Usage: resource_evidence.py <dump_dir> [out.json]

<dump_dir> holds the files from get_resource_dump_url, named <resource>.jsonl.gz or
<resource>.parquet (sentinelOneAgent, sentinelOneApplication, sentinelOneThreat, msDefenderMachine,
msDefenderSecureConfig, msDefenderSecureScore, msDefenderVulnerability, office365User,
office365ConditionalAccessPolicy). Any missing file becomes a visibility gap, never a guess.
Counts only: no host, user or IP names are written to the output.
Needs pandas + pyarrow only for the parquet files.
"""
import gzip, json, os, re, sys
from collections import Counter
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)
BACKUP = re.compile(r"veeam|backup exec|rubrik|cohesity|commvault|acronis|datto|unitrends|arcserve|nakivo|altaro|druva|veritas|networker|avamar", re.I)
REMOTE = re.compile(r"teamviewer|anydesk|splashtop|screenconnect|connectwise control|logmein|gotomypc|goto resolve|rustdesk|ultraviewer|ammyy|supremo|dameware|bomgar|beyondtrust remote|remotepc|pdq|manageengine|desktop central|endpoint central|bigfix|atera|ninjarmm|ninjaone|n-able|kaseya|action1|level\.io|meshcentral|radmin|vnc|dwservice|zoho assist|chrome remote desktop", re.I)
SCANNER = re.compile(r"advanced ip scanner|advanced port scanner|angry ip|nmap|zenmap|masscan|netscan|softperfect|ip scanner|port scanner|network scanner", re.I)
EOL_PLATFORM = re.compile(r"windows ?(xp|vista|7|8)|server ?(2003|2008|2012)", re.I)
EOL_OS = re.compile(r"windows (xp|vista|7|8|8\.1)\b|server 2003|server 2008|server 2012|windows 10", re.I)


def path(d, n):
    for ext in (".jsonl.gz", ".parquet"):
        p = os.path.join(d, n + ext)
        if os.path.exists(p):
            return p
    return None


def rows(d, n):
    """Yield one dict per resource record, or None when the dump is absent."""
    p = path(d, n)
    if not p:
        return None
    out = []
    if p.endswith(".gz"):
        with gzip.open(p, "rt") as f:
            for line in f:
                r = json.loads(line)
                out.append(r.get("@" + n, r))
    else:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(p)
        for b in pf.iter_batches(columns=["doc"], batch_size=50000):
            out.extend(json.loads(s) for s in b.column("doc").to_pylist())
    return out


def vuln_frame(d):
    p = path(d, "msDefenderVulnerability")
    if not p:
        return None
    import pandas as pd
    import pyarrow.parquet as pq
    cols = ["DeviceId", "CveId", "VulnerabilitySeverityLevel", "ExploitabilityLevel", "FirstSeenTimestamp",
            "OSPlatform", "SoftwareName", "SecurityUpdateAvailable", "CvssScore"]
    parts = []
    for b in pq.ParquetFile(p).iter_batches(columns=["doc"], batch_size=100000):
        parts.append(pd.DataFrame([{c: (json.loads(s)).get(c) for c in cols} for s in b.column("doc").to_pylist()]))
    return pd.concat(parts, ignore_index=True)


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def load_advisories():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "backup_advisories.json")
    try:
        return json.load(open(p)).get("advisories", [])
    except Exception:
        return []


def advisory_status(product, version, advisories):
    for a in advisories:
        if re.search(a["product_regex"], product or "", re.I):
            if vkey(version) <= vkey(a["vulnerable_through"]):
                return "VULNERABLE", a["id"] + ": " + ", ".join(a["cves"]) + " (fixed in " + a["fixed_in"] + ")", bool(a.get("requires_domain_joined"))
            return "fixed or newer", a["id"], False
    return "CVE status not verified", "", False


def load_allowlist():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "remote_access_allowlist.json")
    try:
        return [x.lower() for x in json.load(open(p)).get("sanctioned", [])]
    except Exception:
        return []


def days_since(ts):
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (NOW - t).days
    except Exception:
        return None


def host(name):
    return (name or "").split(".")[0].strip().lower()


def main(d, out):
    ev = {"generated": NOW.strftime("%Y-%m-%d"), "gaps": []}
    gap = ev["gaps"].append
    s1 = rows(d, "sentinelOneAgent")
    apps = rows(d, "sentinelOneApplication")
    thr = rows(d, "sentinelOneThreat")
    mac = rows(d, "msDefenderMachine")
    cfg = rows(d, "msDefenderSecureConfig")
    score = rows(d, "msDefenderSecureScore")
    usr = rows(d, "office365User")
    cap = rows(d, "office365ConditionalAccessPolicy")
    vul = vuln_frame(d)
    for n, v in [("sentinelOneAgent", s1), ("sentinelOneApplication", apps), ("sentinelOneThreat", thr),
                 ("msDefenderMachine", mac), ("msDefenderSecureConfig", cfg), ("msDefenderSecureScore", score),
                 ("msDefenderVulnerability", vul), ("office365User", usr), ("office365ConditionalAccessPolicy", cap)]:
        if v is None:
            gap(f"{n} dump not available")

    ev["sources"] = {n: (None if v is None else len(v)) for n, v in [
        ("sentinelOneAgent", s1), ("sentinelOneApplication", apps), ("sentinelOneThreat", thr), ("msDefenderMachine", mac),
        ("msDefenderSecureConfig", cfg), ("office365User", usr), ("office365ConditionalAccessPolicy", cap), ("msDefenderVulnerability", vul)]}
    # ---- Endpoint coverage + detect-only EDR + EOL OS
    if s1 is not None:
        live = [a for a in s1 if not a.get("isDecommissioned")]
        off = [days_since(a.get("lastActiveDate")) for a in live]
        ev["endpoint"] = {
            "agents": len(live),
            "connected": sum(a.get("networkStatus") == "connected" for a in live),
            "by_type": dict(Counter(a.get("machineType") for a in live)),
            "stale_7d": sum(1 for x in off if x is not None and x > 7),
            "stale_30d": sum(1 for x in off if x is not None and x > 30),
            "stale_7d_by_type": dict(Counter(a.get("machineType") for a, x in zip(live, off) if x is not None and x > 7)),
            "not_up_to_date": sum(a.get("isUpToDate") is False for a in live),
            "pending_uninstall": sum(bool(a.get("isPendingUninstall")) for a in live),
            "detect_only": sum(a.get("mitigationMode") != "protect" for a in live),
            "suspicious_detect_only": sum(a.get("mitigationModeSuspicious") != "protect" for a in live),
            "mitigation_modes": dict(Counter(a.get("mitigationMode") for a in live)),
            "suspicious_modes": dict(Counter(a.get("mitigationModeSuspicious") for a in live)),
            "os": dict(Counter(a.get("osName") for a in live).most_common(15)),
            "eol_os": {k: v for k, v in Counter(a.get("osName") for a in live if EOL_OS.search(a.get("osName") or "")).items()},
            "eol_approaching": {"Windows Server 2016 (extended support ends 12 Jan 2027)": sum("server 2016" in (a.get("osName") or "").lower() for a in live)},
        }
        names = {host(a.get("computerName")) for a in live}
    else:
        names = set()
    if mac is not None:
        ENDPOINT_OS = re.compile(r"^(windows|linux|ubuntu|debian|redhat|centos|suse|fedora|oracle|macos)", re.I)
        cand = [m for m in mac if not m.get("isExcluded") and m.get("onboardingStatus") == "CanBeOnboarded"
                and not m.get("mergedIntoMachineId") and not m.get("isPotentialDuplication")]
        ep = [m for m in cand if ENDPOINT_OS.match(m.get("osPlatform") or "")]
        act = [m for m in ep if m.get("healthStatus") == "Active"]
        miss = [m for m in act if host(m.get("computerDnsName")) not in names] if s1 is not None else None
        ev["unprotected"] = {
            "defender_onboarded": sum(m.get("onboardingStatus") == "Onboarded" for m in mac),
            "can_be_onboarded_raw": len(cand),
            "excluded_not_an_endpoint_platform": len(cand) - len(ep),
            "excluded_inactive": len(ep) - len(act),
            "not_in_edr_agent_list": None if miss is None else len(miss),
            "of_which_servers": None if miss is None else sum("server" in (m.get("osPlatform") or "").lower() for m in miss),
            "of_which_end_of_life": None if miss is None else sum(bool(EOL_PLATFORM.search(m.get("osPlatform") or "")) for m in miss),
            "by_os": None if miss is None else dict(Counter(m.get("osPlatform") for m in miss)),
            "note": "Active Windows, Linux and Mac devices Defender can see with no matching EDR agent; phones, embedded and unknown platforms, duplicates and inactive devices are excluded. Matched by short hostname, so a rename can mis-match.",
        }

    # ---- Backup + remote tools
    if apps is not None:
        b = Counter(); r = Counter(); bdom = Counter()
        bh, rh, rsrv, scan = {}, {}, {}, {}
        for a in apps:
            nm = a.get("name") or ""
            if BACKUP.search(nm):
                b[(nm, a.get("version"))] += 0
                bh.setdefault((nm, a.get("version")), set()).add(a.get("agentComputerName"))
                bdom[(a.get("agentDomain") or "").upper()] += 0
            if REMOTE.search(nm):
                rh.setdefault(nm, set()).add(a.get("agentComputerName"))
                if a.get("agentMachineType") == "server":
                    rsrv.setdefault(nm, set()).add(a.get("agentComputerName"))
            if SCANNER.search(nm):
                scan.setdefault(nm, set()).add(a.get("agentComputerName"))
        adv = load_advisories()
        ev["backup"] = sorted(({"product": k[0], "version": k[1], "endpoints": len(v),
                                "advisory": advisory_status(k[0], k[1], adv)[0],
                                "detail": advisory_status(k[0], k[1], adv)[1]} for k, v in bh.items()),
                              key=lambda x: (x["advisory"] != "VULNERABLE", -x["endpoints"]))
        vul_hosts, needs_domain = {}, False
        for a in apps:
            nm = a.get("name") or ""
            if BACKUP.search(nm):
                st = advisory_status(nm, a.get("version"), adv)
                if st[0] == "VULNERABLE":
                    vul_hosts[a.get("agentComputerName")] = (a.get("agentDomain") or "").upper()
                    needs_domain = needs_domain or st[2]
        joined = [h for h, d in vul_hosts.items() if d not in ("", "WORKGROUP")]
        ev["backup_vulnerable"] = {"endpoints": len(vul_hosts), "domain_joined": len(joined),
                                   "workgroup_or_unknown": len(vul_hosts) - len(joined),
                                   "exploitable_now": len(joined) if needs_domain else len(vul_hosts),
                                   "note": "The advisory applies only to domain-joined servers." if needs_domain else ""}
        ev["backup_domains"] = sorted({(a.get("agentDomain") or "").upper() for a in apps
                                      if BACKUP.search(a.get("name") or "") and a.get("agentDomain")})
        fam, fam_srv = {}, {}
        for nm, hs in rh.items():
            m = REMOTE.search(nm)
            key = (m.group(0) if m else nm).lower()
            fam.setdefault(key, set()).update(hs)
            fam_srv.setdefault(key, set()).update(rsrv.get(nm, set()))
        ev["scanner_tools"] = sorted(({"tool": k, "endpoints": len(v)} for k, v in scan.items()), key=lambda x: -x["endpoints"])
        allow = load_allowlist()
        live_n = len([x for x in s1 if not x.get("isDecommissioned")]) if s1 is not None else 0
        top = max(fam, key=lambda f: len(fam[f])) if fam else None
        inferred = [f for f in fam if not allow and live_n and len(fam[f]) >= 0.4 * live_n]
        sanctioned = set(allow) | set(inferred)
        other = set().union(*[h for f, h in fam.items() if f not in sanctioned]) if fam else set()
        ev["remote_tools"] = sorted(({"family": f, "endpoints": len(h), "servers": len(fam_srv.get(f, ())), "status": "sanctioned" if f in sanctioned else "other"}
                                     for f, h in fam.items()), key=lambda x: -x["endpoints"])
        ev["remote_other_families"] = sum(1 for f in fam if f not in sanctioned)
        ev["remote_other_endpoints"] = len(other)
        ev["remote_sanctioned_basis"] = "allow-list" if allow else ("inferred: tools on 40% or more of agents are treated as the organisation's own" if inferred else "none identified")
    # ---- Hardening
    if cfg is not None:
        import pandas as pd
        df = pd.DataFrame(cfg)
        df = df[df["isApplicable"] == True]
        key = df["configurationName"].str.contains(r"ransomware|attack surface|credential guard|laps|local admin|tamper|real-?time|cloud-delivered|network protection|controlled folder", case=False, regex=True) | \
              (df["configurationSubcategory"] == "Attack Surface Reduction")
        g = df[key].groupby(["configurationName", "configurationImpact"]).agg(
            devices=("deviceId", "nunique"), noncompliant=("isCompliant", lambda s: int((s == False).sum()))).reset_index()
        g["pct"] = (100 * g["noncompliant"] / g["devices"]).round(1)
        g["possible_reporting_gap"] = ((g["pct"] >= 99.9) & (g["devices"] >= 50)).astype(bool)
        ev["hardening"] = g.sort_values("noncompliant", ascending=False).head(25).to_dict("records")
        ev["hardening_devices"] = int(df["deviceId"].nunique())
        sk = df[df["configurationName"].str.contains(r"tamper protection|smbv1|smb v1|wdigest|controlled folder|real-?time protection|cloud-delivered|potentially unwanted|network protection|bitlocker|firewall|smartscreen", case=False, regex=True)]
        sg = sk.groupby("configurationName").agg(devices=("deviceId", "nunique"), compliant=("isCompliant", lambda x: int((x == True).sum()))).reset_index()
        sg["pct_compliant"] = (100 * sg["compliant"] / sg["devices"]).round(1)
        ev["strong_controls"] = sg[(sg["devices"] >= 50) & (sg["pct_compliant"] >= 95)].sort_values("pct_compliant", ascending=False).head(10).to_dict("records")
        ev["hardening_rules_failing_everywhere"] = int(g["possible_reporting_gap"].sum())
        if ev["hardening_rules_failing_everywhere"] >= 10:
            ev["gaps"].append("10 or more hardening rules fail on every applicable device: the tenant may not report them. Word the finding as 'not confirmed' unless the policy state is verified.")
    if score:
        ev["secure_score"] = score[0].get("score")
    # ---- Vulnerabilities
    if vul is not None:
        import pandas as pd
        v = vul[vul["VulnerabilitySeverityLevel"].isin(["Critical", "High"])].copy()
        v["age"] = (pd.Timestamp.now(tz="UTC") - pd.to_datetime(v["FirstSeenTimestamp"], utc=True, errors="coerce")).dt.days
        v["server"] = v["OSPlatform"].astype(str).str.startswith("WindowsServer")
        exp = v[v["ExploitabilityLevel"].astype(str).str.contains("Exploit", na=False) & ~v["ExploitabilityLevel"].astype(str).str.contains("NoExploit", na=False)]
        ev["vulnerabilities"] = {
            "rows_total": int(len(vul)),
            "critical_high_devices": int(v["DeviceId"].nunique()),
            "critical_devices": int(v[v["VulnerabilitySeverityLevel"] == "Critical"]["DeviceId"].nunique()),
            "older_than_30d_devices": int(v[v["age"] > 30]["DeviceId"].nunique()),
            "server_devices": int(v[v["server"]]["DeviceId"].nunique()),
            "exploit_available_cves": int(exp["CveId"].nunique()),
            "exploit_available_devices": int(exp["DeviceId"].nunique()),
            "exploit_levels": {str(k): int(x) for k, x in v["ExploitabilityLevel"].value_counts().items()},
            "exploitable_older_than_30d_devices": int(exp[exp["age"] > 30]["DeviceId"].nunique()),
            "exploitable_older_than_90d_devices": int(exp[exp["age"] > 90]["DeviceId"].nunique()),
            "exploitable_critical_devices": int(exp[exp["VulnerabilitySeverityLevel"] == "Critical"]["DeviceId"].nunique()),
            "top_software": [{"software": k, "devices": int(x)} for k, x in exp.groupby("SoftwareName")["DeviceId"].nunique().sort_values(ascending=False).head(8).items()],
            "servers_in_vulnerability_data": int(vul[vul["OSPlatform"].astype(str).str.startswith("WindowsServer")]["DeviceId"].nunique()),
            "servers_in_edr": (ev.get("endpoint") or {}).get("by_type", {}).get("server"),
            "servers_onboarded_to_defender": sum(m.get("onboardingStatus") == "Onboarded" and str(m.get("osPlatform")).startswith("WindowsServer") for m in (mac or [])),
            "top_cves": [{"cve": k, "devices": int(x)} for k, x in exp.groupby("CveId")["DeviceId"].nunique().sort_values(ascending=False).head(10).items()],
        }
    # ---- Threats
    if thr is not None:
        ti = lambda t, k: (t.get("threatInfo") or {}).get(k)
        all_thr = thr
        thr = [t for t in all_thr if days_since(ti(t, "createdAt")) is not None and days_since(ti(t, "createdAt")) <= 90]
        ev["threats"] = {
            "in_dump": len(all_thr), "window_days": 90,
            "total": len(thr),
            "by_classification": dict(Counter(ti(t, "classification") for t in thr)),
            "by_verdict": dict(Counter(ti(t, "analystVerdict") for t in thr)),
            "by_incident_status": dict(Counter(ti(t, "incidentStatus") for t in thr)),
            "on_detect_only_agent": sum((t.get("agentDetectionInfo") or {}).get("agentMitigationMode") != "protect" for t in thr),
            "ransomware_class": sum(ti(t, "classification") == "Ransomware" for t in thr),
            "by_mitigation": dict(Counter(ti(t, "mitigationStatus") for t in thr)),
            "by_confidence": dict(Counter(ti(t, "confidenceLevel") for t in thr)),
            "scanner_named": sum(bool(SCANNER.search(str(ti(t, "threatName") or ""))) for t in thr),
            "top_names": dict(Counter(str(ti(t, "threatName")) for t in thr).most_common(6)),
        }
    # ---- Identity (resource side)
    if usr is not None:
        ev["identity"] = {
            "users": len(usr), "enabled": sum(bool(u.get("accountEnabled")) for u in usr),
            "guests": sum(u.get("userType") == "Guest" for u in usr),
            "synced_from_ad": sum(bool(u.get("onPremisesSyncEnabled")) for u in usr),
            "password_never_expires": sum("DisablePasswordExpiration" in (u.get("passwordPolicies") or "") for u in usr),
        }
        ga = [u for u in usr if "Global Administrator" in (u.get("roles") or [])]
        adm = [u for u in usr if any("Administrator" in r for r in (u.get("roles") or []))]
        ev["identity"].update({
            "global_admins": len(ga),
            "global_admins_enabled": sum(bool(u.get("accountEnabled")) for u in ga),
            "global_admins_cloud_only": sum(not u.get("onPremisesSyncEnabled") for u in ga),
            "admin_role_holders": len(adm),
            "admin_roles": dict(Counter(r for u in usr for r in (u.get("roles") or []) if "Administrator" in r).most_common(12)),
        })
    if cap is not None:
        def mfa(p): return "mfa" in json.dumps((p.get("grantControls") or {})).lower()
        def alluser(p): return "All" in ((p.get("conditions") or {}).get("users") or {}).get("includeUsers", [])
        def legacy(p): return any(x in ("exchangeActiveSync", "other") for x in (p.get("conditions") or {}).get("clientAppTypes", []))
        en = [p for p in cap if p.get("state") == "enabled"]
        ev["conditional_access"] = {
            "policies": len(cap), "enabled": len(en),
            "mfa_all_users": sum(mfa(p) and alluser(p) for p in en),
            "mfa_policies": sum(mfa(p) for p in en),
            "legacy_auth_block": sum(legacy(p) and "block" in json.dumps(p.get("grantControls") or {}).lower() for p in en),
            "report_only": sum(p.get("state") == "enabledForReportingButNotEnforced" for p in cap),
        }
    gap("Per-user MFA registration is not in the resource dumps (admin MFA comes from the sign-in events)")
    gap("Log clearing, new services and account changes are event data: see windows_evidence.json (archived WindowsSrv_Activity_Report)")
    json.dump(ev, open(out, "w"), indent=2, default=str)
    print(json.dumps(ev, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "resource_evidence.json")
