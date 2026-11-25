#!/usr/bin/env python3
"""Tests for defender_patch_health.py on a synthetic tenant (no customer data). Run: python3 tests/test_defender_patch_health.py"""
import contextlib, datetime as dt, gzip, importlib.util, io, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "defender_patch_health.py")
spec = importlib.util.spec_from_file_location("dph", SCRIPT)
dph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dph)

ASOF = dt.date(2026, 11, 25)           # newest Patch Tuesday on or before this date: 10 Nov 2026
NOW = "2026-11-25T01:00:00Z"
MONTHS = dph.MONTHS


def upd(y, m):
    return "%s %d Security Updates" % (MONTHS[m - 1], y)


def months(y1, m1, y2, m2):
    out, y, m = [], y1, m1
    while (y, m) <= (y2, m2):
        out.append(upd(y, m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def write_dump(work, resource, rows, customer="C1"):
    d = os.path.join(work, "dumps", resource)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, customer + ".jsonl.gz"), "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"@" + resource: r, "@dayIndex": "20261125-12"}) + "\n")


def machine(i, name, os_="WindowsServer2019", status="Onboarded", health="Active", seen=NOW, ver="1809"):
    return {"id": i, "computerDnsName": name, "osPlatform": os_, "version": ver, "osBuild": 17763, "onboardingStatus": status,
            "healthStatus": health, "lastSeen": seen, "exposureLevel": "Low", "lastIpAddress": "10.0.0.1"}


def vuln(dev, name, cve, sev="Low", ex="NoExploit", first="2026-11-01 00:00:00", sw="chrome", upd_="CVE-fix", cvss=5.0):
    return {"CveId": cve, "DeviceId": dev, "DeviceName": name, "VulnerabilitySeverityLevel": sev, "ExploitabilityLevel": ex,
            "FirstSeenTimestamp": first, "SoftwareName": sw, "SoftwareVendor": "v", "RecommendedSecurityUpdate": upd_,
            "SecurityUpdateAvailable": True, "CvssScore": cvss, "OSVersion": "10.0.17763.1"}


def os_rows(dev, name, month_list, verified_first=1, prefix="C"):
    """One OS finding per missing monthly update; the first N carry a verified exploit (High)."""
    out = []
    for k, mo in enumerate(month_list):
        yy = int(mo.split()[1])
        mm = MONTHS.index(mo.split()[0]) + 1
        ex = "ExploitIsVerified" if k < verified_first else "NoExploit"
        out.append(vuln(dev, name, "%s-%s-%d" % (prefix, dev, k), "High", ex, "%d-%02d-12 00:00:00" % (yy, mm), "windows_server_2019", mo, 7.8))
    return out


def config_rows(dev, name, secure_boot_fails=False):
    rows = [{"deviceId": dev, "deviceName": name, "isApplicable": True, "isCompliant": True, "configurationId": "scid-%d" % k,
             "configurationName": "Generic %d" % k, "configurationCategory": "OS", "configurationImpact": 1} for k in range(20)]
    spec = [("Block credential stealing from the Windows local security authority subsystem (lsass.exe)", "Security controls", 9, False),
            ("Use advanced protection against ransomware", "Security controls", 9, False),
            ("Ensure LAPS is enabled on every endpoint and server", "OS", 8, False),
            ("Enable UEFI Secure Boot mode", "Firmware", 9, not secure_boot_fails)]
    for k, (nm, cat, imp, ok) in enumerate(spec):
        rows.append({"deviceId": dev, "deviceName": name, "isApplicable": True, "isCompliant": ok, "configurationId": "scid-9%d" % k,
                     "configurationName": nm, "configurationCategory": cat, "configurationImpact": imp})
    rows.append({"deviceId": dev, "deviceName": name, "isApplicable": False, "isCompliant": False, "configurationId": "scid-777",
                 "configurationName": "Not applicable here", "configurationCategory": "OS", "configurationImpact": 9})
    rows.append({"deviceId": dev, "deviceName": name, "isApplicable": True, "isCompliant": False, "configurationId": "scid-20000",
                 "configurationName": "Onboard devices", "configurationCategory": "Security controls", "configurationImpact": 9})
    return rows


def av_row(dev, name, osv, full="2026-10-01T00:00:00Z"):
    return {"machineId": dev, "computerDnsName": name, "avMode": "0", "avIsSignatureUpToDate": "True", "avIsEngineUpToDate": "True",
            "avIsPlatformUpToDate": "True", "fullScanTime": full, "osVersion": osv}


def make_tenant(work):
    dc, web = months(2025, 6, 2026, 11), months(2026, 4, 2026, 11)
    machines = [
        machine("dc", "site-dc01.x.local"), machine("web", "web01.x.local"), machine("app", "app01.x.local"),
        machine("old", "old01.x.local"), machine("stale", "stale01.x.local", seen="2026-11-10T01:00:00Z"),
        machine("silent", "silent01.x.local", "WindowsServer2022", health="Inactive", seen="2026-06-26T09:00:00Z"),
        machine("noscan", "noscan01.x.local", "WindowsServer2022"),
        machine("laptop", "NB-LAP", "Windows11", "CanBeOnboarded", ver="24H2"),
        machine("u1", "SAGE-SRV", "Windows", "InsufficientInfo", ver="Server"),
        machine("u2", "4si-backup", "WindowsServer2019", "CanBeOnboarded", "Inactive", "2026-10-22T01:00:00Z"),
        machine("u3", "dc9-old", "WindowsServer2019", "CanBeOnboarded", "Inactive", "2026-01-01T01:00:00Z"),
        machine("u4", "0b3f2cd9-33d1-4c22-8e57-55a3ec8c8a77", "Windows10", "CanBeOnboarded"),
        machine("u5", "APP01", "WindowsServer2019", "CanBeOnboarded"),          # re-registered copy of app01
        machine("u6", "NB-USER1", "Windows11", "CanBeOnboarded", ver="24H2"),
    ]
    vulns = (os_rows("dc", "site-dc01.x.local", dc, 1) + os_rows("web", "web01.x.local", web, 5, "W")
             + [vuln("app", "app01.x.local", "X-1", "High", "ExploitIsVerified", "2023-08-09 00:00:00", "winrar", cvss=8.4),
                vuln("old", "old01.x.local", "X-2"), vuln("stale", "stale01.x.local", "X-3"),
                vuln("laptop", "NB-LAP", "X-4", "Critical"), vuln("laptop", "NB-LAP", "X-5", "Critical")])
    cfg = []
    for i, n_ in (("dc", "site-dc01.x.local"), ("app", "app01.x.local"), ("old", "old01.x.local")):
        cfg += config_rows(i, n_, secure_boot_fails=(i == "dc"))
    avs = [av_row("dc", "site-dc01.x.local", "10.0.17763.5000", None), av_row("web", "web01.x.local", "10.0.17763.6000"),
           av_row("app", "app01.x.local", "10.0.17763.9487"), av_row("old", "old01.x.local", "10.0.17763.4000"),
           av_row("stale", "stale01.x.local", "10.0.17763.9487")]
    write_dump(work, "msDefenderMachine", machines); write_dump(work, "msDefenderVulnerability", vulns)
    write_dump(work, "msDefenderSecureConfig", cfg); write_dump(work, "msDefenderAvHealth", avs)
    with open(os.path.join(work, "scope.json"), "w") as f:
        json.dump({"endpointIntegrations": ["C1", "C2"], "dumpCounts": {"msDefenderMachine": len(machines), "msDefenderVulnerability": len(vulns),
                                                                          "msDefenderSecureConfig": len(cfg), "msDefenderAvHealth": len(avs)}}, f)
    return machines, vulns


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def alert_file(work, rows):
    cols = ["serviceSource", "severity", "status", "bucket", "t", "alerts", "oldestDays"]
    with open(os.path.join(work, "a_alerts.json"), "w") as f:
        json.dump({"data": {"Tables": [{"Columns": [{"ColumnName": c} for c in cols], "Rows": rows}]}}, f)


ALERT_ROWS = [["microsoftDefenderForOffice365", "medium", "new", "0-30", "", 5, 20],
              ["microsoftDefenderForOffice365", "medium", "new", "31+", "", 2, 70],
              ["azureAdIdentityProtection", "high", "resolved", "0-30", "Unfamiliar sign-in", 10, 15],
              ["unknownFutureValue", "high", "new", "31+", "Stale high", 1, 90],
              ["microsoftDefenderForEndpoint", "informational", "new", "0-30", "FileZilla", 1, 4]]


class PatchGap(unittest.TestCase):
    def gap(self, *ms, asof=ASOF):
        return dph.patch_gap([upd(*m) for m in ms], asof)

    def test_contiguous_run_counts_to_latest_patch_tuesday(self):
        start, behind, out = self.gap((2026, 10), (2026, 11))
        self.assertEqual((dph.fmt_month(start), behind, out), ("Oct 2026", 2, []))

    def test_only_the_newest_month(self):
        self.assertEqual(self.gap((2026, 11))[1], 1)

    def test_one_skipped_month_is_tolerated(self):
        start, behind, _ = self.gap((2026, 6), (2026, 8), (2026, 10), (2026, 11))
        self.assertEqual((dph.fmt_month(start), behind), ("Jun 2026", 6))

    def test_isolated_old_month_is_an_outlier_not_the_gap(self):
        start, behind, out = self.gap((2026, 5), (2026, 8), (2026, 9), (2026, 10), (2026, 11))
        self.assertEqual((dph.fmt_month(start), behind, [dph.fmt_month(o) for o in out]), ("Aug 2026", 4, ["May 2026"]))

    def test_single_old_month_alone_counts_its_full_age(self):
        self.assertEqual(self.gap((2024, 6))[1], 30)

    def test_before_patch_tuesday_the_current_month_is_not_yet_due(self):
        self.assertEqual(dph.patch_gap([upd(2026, 10)], dt.date(2026, 11, 5))[1], 1)

    def test_unrecognised_labels_give_no_gap(self):
        self.assertEqual(dph.patch_gap(["2026-10 Cumulative Update", None, ""], ASOF), (None, 0, []))

    def test_second_tuesday(self):
        self.assertEqual(dph.second_tuesday(2026, 11), dt.date(2026, 11, 10))
        self.assertEqual(dph.second_tuesday(2026, 12), dt.date(2026, 12, 8))


class Roles(unittest.TestCase):
    def test_roles(self):
        for name, role in [("4si-az-dc01.acctech.biz", "Domain controller"), ("atoazads01", "Domain controller"), ("dc9-old", "Domain controller"),
                           ("4si-Backupsrv", "Backup server"), ("bkp01", "Backup server"), ("4Si-HV02", "Hyper-V host"), ("hypervarc", "Hyper-V host"),
                           ("lrfsqlserver01", "SQL server"), ("4sh-printsrv", "Print server"), ("acctechmst01", "Management host"),
                           ("SAGECRMDEMO-SRV", "Server")]:
            self.assertEqual(dph.role_of(name), role, name)

    def test_names_that_only_contain_the_letters_are_not_roles(self):
        for name in ("reads-fileserver", "headsets01", "mstar-app", "NB-ADS-USER", "crmdev", "4sh-ot-az-pme01"):
            self.assertNotEqual(dph.role_of(name), "Domain controller", name)
        self.assertEqual(dph.role_of("mstar-app"), "")
        self.assertEqual(dph.role_of("crmdev"), "")

    def test_asr_rules(self):
        s = lambda n, c="Security controls": {"name": n, "category": c}
        self.assertTrue(dph.is_asr(s("Block credential stealing from lsass")))
        self.assertTrue(dph.is_asr(s("Use advanced protection against ransomware")))
        self.assertFalse(dph.is_asr(s("Enable Microsoft Defender Antivirus email scanning")))
        self.assertFalse(dph.is_asr(s("Block file transfer over RDP", "OS")))


class BuildCheck(unittest.TestCase):
    def srv(self, name, status, build):
        return {"name": name, "status": status, "build": build}

    def test_revision_parsing(self):
        self.assertEqual(dph.build_rev("10.0.17763.9487"), (17763, 9487))
        self.assertIsNone(dph.build_rev("17763"))
        self.assertIsNone(dph.build_rev(None))

    def test_current_older_than_behind_is_flagged(self):
        f = dph.build_flags([self.srv("a", "Behind", "10.0.17763.5000"), self.srv("b", "Current", "10.0.17763.4000")])
        self.assertEqual(len(f), 1)
        self.assertIn("b is marked Current", f[0])

    def test_consistent_builds_and_other_os_are_not_flagged(self):
        self.assertEqual(dph.build_flags([self.srv("a", "Behind", "10.0.17763.5000"), self.srv("b", "Current", "10.0.17763.9487"),
                                          self.srv("c", "Current", "10.0.20348.100")]), [])

    def test_current_without_revision_cannot_be_cross_checked(self):
        f = dph.build_flags([self.srv("a", "Current", "17763")])
        self.assertIn("no revision", f[0])

    def test_no_data_servers_are_ignored(self):
        self.assertEqual(dph.build_flags([self.srv("a", "No data", "20348"), self.srv("b", "Behind", "10.0.17763.5000")]), [])


class Alerts(unittest.TestCase):
    def rows(self):
        cols = ["serviceSource", "severity", "status", "bucket", "t", "alerts", "oldestDays"]
        return [dict(zip(cols, r)) for r in ALERT_ROWS]

    def test_window_counts_use_the_30_day_bucket_only(self):
        a = dph.alerts_facts(self.rows())
        self.assertEqual(a["distinct"], 16)               # 5 + 10 + 1
        self.assertEqual(a["high"], 10)
        self.assertEqual((a["endpoint"], a["endpointOpen"]), (1, 1))

    def test_open_alerts_are_counted_at_any_age(self):
        a = dph.alerts_facts(self.rows())
        self.assertEqual(a["highOpen"], 1)                # the stale high alert, created 90 days ago
        self.assertEqual(a["highOpenTitles"], [("Stale high", 1)])

    def test_alerts_open_longer_than_30_days(self):
        a = dph.alerts_facts(self.rows())
        self.assertEqual((a["openAged"], a["openAgedActionable"], a["openAgedOldestDays"]), (3, 3, 90))
        self.assertEqual(a["openAgedBySeverity"], {"high": 1, "medium": 2})
        self.assertEqual(a["openAgedRows"][0]["severity"], "high")      # high severity listed first

    def test_informational_aged_alerts_are_not_actionable(self):
        rows = [{"serviceSource": "x", "severity": "informational", "status": "new", "bucket": "31+", "t": "", "alerts": 4, "oldestDays": 40}]
        a = dph.alerts_facts(rows)
        self.assertEqual((a["openAged"], a["openAgedActionable"]), (4, 0))

    def test_rows_without_a_bucket_are_treated_as_recent(self):
        a = dph.alerts_facts([{"serviceSource": "x", "severity": "high", "status": "new", "t": "T", "alerts": 2}])
        self.assertEqual((a["distinct"], a["openAged"], a["highOpen"]), (2, 0, 2))


class Facts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp()
        make_tenant(cls.work)
        alert_file(cls.work, ALERT_ROWS)
        cls.F = dph.build_facts(cls.work, ASOF, "acct", "Customer")
        cls.srv = {d["name"]: d for d in cls.F["servers"]}

    def test_server_status(self):
        s = self.srv
        self.assertEqual(s["site-dc01.x.local"]["status"], "Behind")
        self.assertEqual((s["site-dc01.x.local"]["monthsBehind"], s["site-dc01.x.local"]["lastPatched"]), (18, "May 2025"))
        self.assertEqual((s["web01.x.local"]["status"], s["web01.x.local"]["monthsBehind"]), ("Behind", 8))
        self.assertEqual(s["app01.x.local"]["status"], "Current")
        self.assertEqual(s["silent01.x.local"]["status"], "No data")         # silent 152 days
        self.assertEqual(s["noscan01.x.local"]["status"], "No data")         # enrolled, active, but no scan results
        self.assertEqual(len(self.F["serversNoData"]), 2)
        self.assertEqual(self.F["serversReporting"], 5)

    def test_no_data_is_never_counted_as_current(self):
        self.assertNotIn("silent01.x.local", [d["name"] for d in self.F["serversCurrent"]])
        self.assertNotIn("noscan01.x.local", [d["name"] for d in self.F["serversCurrent"]])

    def test_current_server_last_seen_over_a_week_ago_is_marked_stale(self):
        self.assertTrue(self.srv["stale01.x.local"]["stale"])
        self.assertFalse(self.srv["app01.x.local"]["stale"])

    def test_build_comes_from_the_antivirus_dump_and_is_cross_checked(self):
        self.assertEqual(self.srv["app01.x.local"]["build"], "10.0.17763.9487")
        self.assertEqual(len(self.F["buildFlags"]), 1)
        self.assertIn("old01.x.local is marked Current", self.F["buildFlags"][0])

    def test_oldest_exploitable_is_patch_tuesday_of_first_missing_month(self):
        self.assertEqual(self.srv["site-dc01.x.local"]["oldestExploitable"], "2025-06-12")

    def test_unmanaged_servers(self):
        names = {u["name"] for u in self.F["unmanagedServers"]}
        self.assertIn("SAGE-SRV", names)                                       # generic "Windows Server" fingerprint
        self.assertIn("4si-backup", names)
        self.assertNotIn("0b3f2cd9-33d1-4c22-8e57-55a3ec8c8a77", names)        # GUID-named
        self.assertNotIn("NB-USER1", names)                                    # a laptop
        self.assertEqual([u["name"] for u in self.F["unmanagedActive"]], ["SAGE-SRV"])
        dup = [u for u in self.F["reRegisteredActive"]]
        self.assertEqual([(u["name"], u["duplicateOf"]) for u in dup], [("APP01", "app01.x.local")])

    def test_quiet_critical_servers_are_kept_while_recent(self):
        self.assertEqual([u["name"] for u in self.F["unmanagedCriticalQuiet"]], ["4si-backup"])   # dc9-old: quiet 328 days

    def test_scanned_devices_that_are_not_enrolled_are_listed(self):
        self.assertEqual([(x["name"], x["critical"]) for x in self.F["unenrolledScanned"]], [("NB-LAP", 2)])
        self.assertEqual(self.F["vulnDevices"], 6)

    def test_configuration_baseline_uses_enrolled_servers_only(self):
        F = self.F
        self.assertEqual(F["configDevices"], 3)
        self.assertEqual(sorted(F["asrOffAll"]), sorted(["Block credential stealing from the Windows local security authority subsystem (lsass.exe)",
                                                         "Use advanced protection against ransomware"]))
        self.assertEqual([x["name"] for x in F["baselineFailAll"]], ["Ensure LAPS is enabled on every endpoint and server"])
        self.assertEqual([(x["name"], x["devices"]) for x in F["partialFailAll"]], [("Enable UEFI Secure Boot mode", 1)])
        self.assertEqual(F["configFailingSettings"], 4)                          # n/a and scid-20000 rows are ignored

    def test_antivirus_counts_enrolled_servers_without_data(self):
        av = self.F["av"]
        self.assertEqual((av["devices"], av["enrolledServers"], av["healthy"], av["neverFullScan"]), (5, 7, 5, 1))

    def test_connector_without_a_dump_is_reported(self):
        self.assertEqual(self.F["endpointIntegrationsNoData"], ["C2"])

    def test_age_buckets_and_exploitable_totals(self):
        F = self.F
        self.assertEqual(F["exploitableCritHigh"], 7)                            # dc 1 + web 5 + app 1
        self.assertEqual(F["exploitableOver180"], 4)                             # dc, app, and web01's April and May exploits
        self.assertEqual(F["exploitableAgeTotal"], 7)
        self.assertEqual(len(F["cves"]), 7)

    def test_actions_are_ranked_by_risk_not_by_role(self):
        acts = dph.actions(self.F)
        p1 = [a for a in acts if a[0] == "P1"]
        self.assertIn("web01.x.local", p1[0][1])                                 # 5 exploitable beats the domain controller's 1
        self.assertIn("site-dc01.x.local", p1[1][1])
        self.assertIn("(domain controller)", p1[1][1])
        text = " ".join(a[1] for a in acts)
        self.assertIn("4si-backup", text)                                        # quiet critical server still gets an action
        self.assertIn("Enrol the 1 devices", text)

    def test_render_smoke(self):
        try:
            fb = dph.find_brand()
        except SystemExit:
            self.skipTest("fluency-report skill not installed")
        page = dph.render(self.F, fb)
        for needle in ("Build check", "No data", "Scanned devices that are not enrolled", "Open for more than 30 days"):
            self.assertIn(needle, page)


class Check(unittest.TestCase):
    def run_check(self, work):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dph.check(work, ASOF)
        return rc, buf.getvalue()

    def fresh(self):
        w = tempfile.mkdtemp()
        make_tenant(w); alert_file(w, ALERT_ROWS)
        return w

    def test_complete_tenant_is_ok(self):
        rc, out = self.run_check(self.fresh())
        self.assertEqual(rc, 0, out)
        self.assertIn("OK 4 dumps", out)

    def test_missing_dump_is_a_problem(self):
        w = self.fresh()
        os.remove(os.path.join(w, "dumps", "msDefenderMachine", "C1.jsonl.gz"))
        rc, out = self.run_check(w)
        self.assertEqual(rc, 1)
        self.assertIn("no dump for msDefenderMachine", out)

    def test_truncated_download_is_a_problem(self):
        w = self.fresh()
        p = os.path.join(w, "dumps", "msDefenderVulnerability", "C1.jsonl.gz")
        with open(p, "rb") as f:
            data = f.read()
        with open(p, "wb") as f:
            f.write(data[: len(data) // 2])
        rc, out = self.run_check(w)
        self.assertEqual(rc, 1)
        self.assertIn("unreadable or truncated", out)

    def test_row_count_differing_from_the_listing_is_a_problem(self):
        w = self.fresh()
        s = read_json(os.path.join(w, "scope.json"))
        s["dumpCounts"]["msDefenderSecureConfig"] += 1
        write_json(os.path.join(w, "scope.json"), s)
        rc, out = self.run_check(w)
        self.assertEqual(rc, 1)
        self.assertIn("partial download", out)

    def test_empty_vulnerability_dump_is_a_problem_but_empty_config_is_a_warning(self):
        w = self.fresh()
        write_dump(w, "msDefenderVulnerability", [])
        rc, out = self.run_check(w)
        self.assertEqual(rc, 1)
        w2 = self.fresh()
        write_dump(w2, "msDefenderSecureConfig", [])
        s = read_json(os.path.join(w2, "scope.json")); s["dumpCounts"]["msDefenderSecureConfig"] = 0
        write_json(os.path.join(w2, "scope.json"), s)
        rc2, out2 = self.run_check(w2)
        self.assertEqual(rc2, 0, out2)
        self.assertIn("WARN msDefenderSecureConfig dump is empty", out2)

    def test_missing_update_label_warns(self):
        w = self.fresh()
        write_dump(w, "msDefenderVulnerability", [vuln("dc", "x", "A")])
        s = read_json(os.path.join(w, "scope.json")); s["dumpCounts"]["msDefenderVulnerability"] = 1
        write_json(os.path.join(w, "scope.json"), s)
        rc, out = self.run_check(w)
        self.assertEqual(rc, 0, out)
        self.assertIn("Security Updates", out)

    def test_stale_snapshot_warns(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dph.check(self.fresh(), dt.date(2026, 12, 5))
        self.assertIn("older than the as-of date", buf.getvalue())


class Window(unittest.TestCase):
    def test_window_command(self):
        import subprocess
        out = subprocess.run([sys.executable, "-I", SCRIPT, "window", "--asof", "2026-11-25", "--days", "30"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "rangeFrom=1793059199000 rangeTo=1795651199000")


if __name__ == "__main__":
    unittest.main(verbosity=1)
