#!/usr/bin/env python3
"""Smoke test: archive-shaped sample inputs -> evidence -> rating -> HTML. Run: python3 tests/test_pipeline.py"""
import gzip, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts"); A = os.path.join(ROOT, "assets", "sample_evidence")


def run(*args):
    return subprocess.run([sys.executable, "-I"] + list(args), check=True, capture_output=True, text=True).stdout


def evidence(t, name, **over):
    a = {"inventory": "inventory_archive", "pad": "pad_archive", "entra": "entra_archive", "windows-archive": "windows_archive", "apps": "apps"}
    a.update(over)
    cmd = [os.path.join(S, "drift_evidence.py")]
    for k, v in a.items():
        if v:
            cmd += ["--" + k, "%s/%s.sample.json" % (A, v) if not v.startswith("/") else v]
    run(*cmd, "--asof", "2026-11-12", "-o", "%s/%s.json" % (t, name))
    return json.load(open("%s/%s.json" % (t, name)))


def rate(t, name, tenant="Sample Co"):
    run(os.path.join(S, "rate_evidence.py"), "--evidence", "%s/%s.json" % (t, name), "--tenant", tenant, "--date", "2026-11-12", "--out", "%s/%s_draft.json" % (t, name))
    return json.load(open("%s/%s_draft.json" % (t, name)))


def main():
    t = tempfile.mkdtemp()
    ev = evidence(t, "ev"); d = rate(t, "ev"); dr = ev["drift"]
    # events are added across the three PAD days; per-day distinct counts use the busiest day
    x = dr["outside_pim_by_initiator"][0]
    assert dr["outside_pim_events"] == 24 and x["removals"] == 15 and x["removal_ratio"] == 0.625 and x["timeboxed"] is False, dr["outside_pim_by_initiator"]
    assert dr["pim_permanent_added"] == 8 and dr["pim_permanent_removed"] == 11 and dr["pim_alerts"] == 1 and dr["pim_alerts_resolved"] == 0 and dr["pim_activations"] == 40, dr
    sg = ev["signins"]
    assert sg["successful"] == 1599 and sg["single_factor"] == 824 and sg["single_factor_pct"] == 51.5, sg
    assert sg["admins_signed_in"] == 52 and sg["admins_with_single_factor"] == 33 and sg["admins_all_single_factor"] == 9, sg
    # directory state: latest inventory day; the GA count changed between snapshots
    assert ev["global_admins"]["holders"] == 5 and ev["accounts"]["accounts"] == 66 and ev["accounts"]["licensed"] == 20 and ev["accounts"]["noMfa"] == 4 and ev["accounts_detail"], ev["accounts"]
    assert [x["global_admins"] for x in ev["admin_trend"]] == [None, 4, 5] or [x["global_admins"] for x in ev["admin_trend"]] == [0, 4, 5], ev["admin_trend"]
    assert ev["archive"]["pad"]["days"] == 3 and ev["archive"]["inventory"]["role_history_days"] == 2 and ev["archive"]["entra"]["days"] == 1, ev["archive"]
    # applications: the publisher is mapped from the apps map by application id
    nh = {x["identity"]: x for x in ev["non_human"]}
    assert nh["Backup Connector"]["tier"] == 0 and nh["Backup Connector"]["publisher"] == "verified: Backup Vendor Inc.", nh
    assert nh["Policy Portal App"]["tier"] == 1 and nh["Policy Portal App"]["publisher"] == "not verified", nh
    assert ev["app_events"] == {"Consent to application": 3, "Add service principal credentials": 5}, ev["app_events"]
    assert ev["conditional_access"]["added"] == 1 and ev["conditional_access"]["updated"] == 3, ev["conditional_access"]
    assert ev["onprem"]["group_change_events"] == 24 and ev["onprem"]["days"] == 2 and ev["onprem"]["dc_activity"], ev["onprem"]
    # rating
    assert d["drift_rating"] == "High"
    sev = [f["severity"] for f in d["findings"]]; titles = [f["title"] for f in d["findings"]]
    assert sev[0] == "critical" and "A PIM alert has no recorded resolution" in titles and "Roles are assigned outside PIM" in titles, titles
    sf = next(f for f in d["findings"] if f["title"].startswith("Administrator sign-ins")); assert "busiest day 33 of 52" in sf["finding"], sf["finding"]
    assert any("Global Administrators rose from 4 to 5" in x["event"] for x in d["timeline"]), d["timeline"]
    gaps = " | ".join(d["coverage_gaps"])
    assert "holds 3 of 60 days" in gaps and "Dormant administrators are not measured" in gaps, gaps
    assert not any(x.startswith("The Office365_Resource_Inventory_Report archive holds no day") for x in d["coverage_gaps"])
    assert any(e["source"].startswith("Privileged_Access_Drift_Report") for e in d["evidence"])
    # time-boxed tooling: removals at least 80% of additions is reported, not rated high
    tbx = json.load(open(t + "/ev.json")); tbx["drift"]["outside_pim_by_initiator"][0].update({"removals": 22, "removal_ratio": 0.92, "timeboxed": True})
    tbx["non_human"] = [x for x in tbx["non_human"] if x["tier"] > 0]; tbx["drift"]["pim_alerts"] = 0; tbx["signins"]["single_factor_pct"] = 5.0
    json.dump(tbx, open(t + "/tb.json", "w")); q = rate(t, "tb")
    assert next(f for f in q["findings"] if f["title"] == "Roles are assigned outside PIM")["severity"] == "medium", q["findings"]
    # a tenant with no archived PAD day: nothing is invented, the gap is stated
    json.dump({"days": []}, open(t + "/pad_empty.json", "w")); emp = evidence(t, "nopad", pad=t + "/pad_empty.json"); e = rate(t, "nopad")
    assert emp["drift"] is None and emp["non_human"] is None and emp["signins"]["single_factor_pct"] is None
    assert any("Privileged_Access_Drift_Report archive holds no day" in g for g in e["coverage_gaps"]), e["coverage_gaps"]
    # a PAD scan that was not available on every day (no Entra audit table)
    na = json.load(open(A + "/pad_archive.sample.json"))
    for dy in na["days"]:
        for o in dy["result"]["objects"]:
            if o["name"] == "sources":
                for r in o["table"]["rows"]:
                    if r["source"].startswith("AzureAuditLogs"):
                        r["status"] = "not available"
    json.dump(na, open(t + "/pad_na.json", "w"))
    nv = evidence(t, "na", pad=t + "/pad_na.json"); nd = rate(t, "na")
    assert nv["drift"] is None and nv["tables_present"]["AzureAuditLogs"] is False and any("directory audit logs" in g for g in nd["coverage_gaps"]), nd["coverage_gaps"]
    # a tenant with a quiet role log
    z = json.load(open(t + "/ev.json")); z["drift"].update({"role_events_total": 0, "outside_pim_events": 0, "outside_pim_by_initiator": [], "pim_permanent_added": 0, "pim_alerts": 0, "pim_activations": 0, "pim_seen": False})
    z["non_human"] = []; z["signins"]["single_factor_pct"] = None; z["global_admins"]["holders"] = 6; json.dump(z, open(t + "/ev0.json", "w"))
    qd = rate(t, "ev0", "Quiet Co")
    assert any(f["title"] == "Role assignment changes cannot be observed" for f in qd["findings"]) and qd["drift_rating"] == "Elevated", qd["drift_rating"]
    try:
        run(os.path.join(S, "render_report.py"), t + "/ev_draft.json", t, "--no-pdf")
        assert any(f.startswith("Privileged_Access_Drift_SampleCo_") and f.endswith(".html") for f in os.listdir(t))
    except subprocess.CalledProcessError as ex:
        if "brand kit was not found" not in (ex.stderr or "") + (ex.stdout or ""):
            raise
        print("render skipped: fluency-report brand kit not found")
    # application dump -> apps map (synthetic dump; the real one is a gzipped JSONL of office365InstalledApp records)
    with gzip.open(t + "/a.jsonl.gz", "wt") as fh:
        fh.write(json.dumps({"appId": "x1", "displayName": "Backup Connector", "verifiedPublisher": {"displayName": "Backup Vendor Inc."}}) + "\n"
                 + json.dumps({"value": {"appId": "x2", "displayName": "Upload App", "verifiedPublisher": None}}) + "\n" + json.dumps({"appId": "x1", "displayName": "dup"}) + "\n")
    run(os.path.join(S, "dump_evidence.py"), "--apps", t + "/a.jsonl.gz", "-o", t + "/apps.json")
    m = {r["appId"]: r for r in json.load(open(t + "/apps.json"))}
    assert m["x1"]["verified"] == "Backup Vendor Inc." and m["x2"]["verified"] == "" and len(m) == 2, m
    print("ok")


if __name__ == "__main__":
    main()
