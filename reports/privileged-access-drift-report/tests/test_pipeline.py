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
        "--app-grants", f("app_grants"), "--app-events", f("app_events"), "--ca", f("ca_changes"), "--onprem", f("onprem"), "--apps", f("apps"), "--tables", f("tables"), "--asof", "2026-11-10", "-o", t + "/ev.json")
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
    assert ev["onprem"]["group_change_events"] == 24
    assert d["drift_rating"] == "High"                                           # tier-0 grant and an unresolved PIM alert
    sev = [x["severity"] for x in d["findings"]]
    assert sev[0] == "critical" and "high" in sev, sev
    assert any(x["title"] == "A PIM alert has no recorded resolution" for x in d["findings"])
    assert not any(x["title"].startswith("On-premises privilege") for x in d["findings"])   # group events are present
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
    print("ok")


if __name__ == "__main__":
    main()
