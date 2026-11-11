#!/usr/bin/env python3
"""Smoke test: sample evidence -> evidence -> rating -> HTML. Run: python3 tests/test_pipeline.py"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts"); A = os.path.join(ROOT, "assets", "sample_evidence")


def run(*args):
    return subprocess.run([sys.executable, "-I"] + list(args), check=True, capture_output=True, text=True).stdout


def main():
    t = tempfile.mkdtemp(); f = lambda n: "%s/%s.sample.json" % (A, n)
    run(os.path.join(S, "drift_evidence.py"), "--roles", f("roles"), "--accounts", f("accounts"), "--signins", f("signins"), "--role-drift", f("role_drift"), "--role-activity", f("role_activity"),
        "--app-grants", f("app_grants"), "--app-events", f("app_events"), "--ca", f("ca_changes"), "--windows-archive", "%s/windows_archive.sample.json" % A, "--apps", f("apps"), "--tables", f("tables"), "--asof", "2026-11-10", "-o", t + "/ev.json")
    run(os.path.join(S, "rate_evidence.py"), "--evidence", t + "/ev.json", "--tenant", "Sample Co", "--date", "2026-11-10", "--out", t + "/draft.json")
    ev = json.load(open(t + "/ev.json")); d = json.load(open(t + "/draft.json"))
    dr = ev["drift"]
    assert dr["outside_pim_events"] == 258 and dr["outside_pim_by_initiator"][0]["timeboxed"] is True, dr["outside_pim_by_initiator"]   # 313 removals / 361 additions
    assert dr["pim_permanent_added"] == 8 and dr["pim_permanent_removed"] == 11 and dr["pim_alerts"] == 1 and dr["pim_alerts_resolved"] == 0, dr
    assert ev["signins"]["single_factor_pct"] == 48.4 and ev["global_admins"]["holders"] == 6, ev["signins"]
    tiers = {x["identity"]: x["tier"] for x in ev["non_human"]}
    assert tiers["Backup Connector"] == 0 and tiers["Policy Portal App"] == 1 and tiers["Upload App"] == 2, tiers
    pubs = {x["identity"]: x["publisher"] for x in ev["non_human"]}
    assert pubs["Backup Connector"].startswith("verified") and pubs["Upload App"] == "not verified" and pubs["Policy Portal App"] == "not checked", pubs
    assert ev["onprem"]["group_change_events"] == 24 and ev["onprem"]["days"] == 2 and ev["onprem"]["dc_activity"], ev["onprem"]
    assert d["drift_rating"] == "High"                                           # tier-0 grant and an unresolved PIM alert
    sev = [x["severity"] for x in d["findings"]]
    assert sev[0] == "critical" and "high" in sev, sev
    assert any(x["title"] == "A PIM alert has no recorded resolution" for x in d["findings"])
    assert not any(x["title"].startswith("On-premises privilege") for x in d["findings"])   # group events are present
    assert any("2 of 30 days" in g for g in d["coverage_gaps"]), d["coverage_gaps"]            # a short archive is stated, not hidden
    # a tenant with no role-management events at all
    z = json.load(open(t + "/ev.json")); z["drift"].update({"role_events_total": 0, "outside_pim_events": 0, "outside_pim_by_initiator": [], "pim_permanent_added": 0, "pim_alerts": 0, "pim_activations": 0, "pim_seen": False})
    z["non_human"] = []; json.dump(z, open(t + "/ev0.json", "w"))
    run(os.path.join(S, "rate_evidence.py"), "--evidence", t + "/ev0.json", "--tenant", "Quiet Co", "--date", "2026-11-10", "--out", t + "/draft0.json")
    q = json.load(open(t + "/draft0.json"))
    assert any(x["title"] == "Role assignment changes cannot be observed" for x in q["findings"]) and q["drift_rating"] == "Elevated", q["drift_rating"]   # 6 Global Administrators
    try:
        run(os.path.join(S, "render_report.py"), t + "/draft.json", t, "--no-pdf")
        assert any(x.startswith("Privileged_Access_Drift_SampleCo_") and x.endswith(".html") for x in os.listdir(t))
    except subprocess.CalledProcessError as e:
        if "brand kit was not found" not in (e.stderr or "") + (e.stdout or ""):
            raise
        print("render skipped: fluency-report brand kit not found")
    # snapshot dump -> evidence (synthetic dump; the real one is a gzipped JSONL of the office365User and office365InstalledApp records)
    import gzip
    users = [{"userPrincipalName": "a_adm@x.test", "roles": ["Global Administrator", "SharePoint Administrator"], "accountEnabled": True, "assignedLicenses": [{"skuId": "1"}], "createdDateTime": "2026-10-01T00:00:00Z", "userRegistration": {"isMfaRegistered": True, "isPasswordlessCapable": True}},
             {"userPrincipalName": "helpdesk@x.test", "roles": ["User Administrator", "Exchange Administrator", "SharePoint Administrator", "Teams Administrator", "Helpdesk Administrator", "Global Administrator"], "accountEnabled": False, "assignedLicenses": [], "createdDateTime": "2020-01-01T00:00:00Z", "userRegistration": {"isMfaRegistered": False}},
             {"value": {"userPrincipalName": "b@x.test", "roles": [], "accountEnabled": True}},
             {"userPrincipalName": "g@x.test", "roles": ["Global Reader"], "userType": "Guest", "accountEnabled": True, "userRegistration.isMfaRegistered": True}]
    with gzip.open(t + "/u.jsonl.gz", "wt") as fh:
        fh.write("\n".join(json.dumps(x) for x in users) + "\n")
    with gzip.open(t + "/a.jsonl.gz", "wt") as fh:
        fh.write(json.dumps({"displayName": "Backup Connector", "verifiedPublisher": {"displayName": "Backup Vendor Inc."}}) + "\n" + json.dumps({"displayName": "Upload App", "verifiedPublisher": None}) + "\n")
    run(os.path.join(S, "dump_evidence.py"), "--users", t + "/u.jsonl.gz", "--apps", t + "/a.jsonl.gz", "--asof", "2026-11-10", "--batch", "2", "-o", t + "/dump")
    acc = json.load(open(t + "/dump/accounts.json"))["data"]["Tables"][0]; ac = dict(zip([x["ColumnName"] for x in acc["Columns"]], acc["Rows"][0]))
    assert ac["accounts"] == 3 and ac["enabled"] == 2 and ac["disabled"] == 1 and ac["licensed"] == 1 and ac["multi6"] == 1 and ac["shared"] == 1 and ac["noMfa"] == 1 and ac["passwordless"] == 1 and ac["guests"] == 1 and ac["new90"] == 1, ac
    rl = {r[0]: r for r in json.load(open(t + "/dump/roles.json"))["data"]["Tables"][0]["Rows"]}
    assert rl["Global Administrator"][1:] == [2, 1, 1, 0] and rl["Global Reader"][4] == 1
    assert len([x for x in os.listdir(t + "/dump") if x.startswith("signins_query_")]) == 2 and "x.test" in open(t + "/dump/signins_query_1.kql").read()
    run(os.path.join(S, "drift_evidence.py"), "--roles", t + "/dump/roles.json", "--accounts", t + "/dump/accounts.json", "--signins", f("signins"), f("signins"), "--apps", t + "/dump/apps.json", "--asof", "2026-11-10", "-o", t + "/ev_dump.json")
    dv = json.load(open(t + "/ev_dump.json")); assert dv["signins"]["successful"] == 2 * 27844 and dv["accounts"]["accounts"] == 3, dv["signins"]   # two batches are summed
    print("ok")


if __name__ == "__main__":
    main()
