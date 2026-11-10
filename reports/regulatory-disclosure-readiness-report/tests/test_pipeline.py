#!/usr/bin/env python3
"""Smoke test: sample evidence -> case/platform evidence -> rating -> HTML. Run: python3 tests/test_pipeline.py"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts"); A = os.path.join(ROOT, "assets", "sample_evidence")


def run(*args):
    return subprocess.run([sys.executable, "-I"] + list(args), check=True, capture_output=True, text=True).stdout


def main():
    t = tempfile.mkdtemp()
    run(os.path.join(S, "case_evidence.py"), "--facets", A + "/facets.sample.json", "--open", A + "/open.sample.json", "--closed", A + "/closed.sample.json", "--asof", "2026-11-10", "-o", t + "/case.json")
    run(os.path.join(S, "platform_evidence.py"), "--tables", A + "/tables.sample.json", "--windows-archive", A + "/windows_archive.sample.json", "--asof", "2026-11-10", "-o", t + "/plat.json")
    run(os.path.join(S, "rate_evidence.py"), "--cases", t + "/case.json", "--platform", t + "/plat.json", "--tenant", "Sample Co", "--date", "2026-11-10", "--applicability", A + "/applicability.sample.json", "--out", t + "/draft.json")
    c = json.load(open(t + "/case.json")); d = json.load(open(t + "/draft.json"))
    assert c["open"]["escalated"] == 1 and c["open"]["escalated_no_human"] == 1, c["open"]
    assert c["open"]["personal_data"] == 1 and c["triage"]["with_ai_verdict"] == 3, c["triage"]
    assert c["closed_sample"]["closed_by_human"] == 1 and c["closed_sample"]["median_hours_to_close"] == 2.0, c["closed_sample"]
    assert d["readiness_rating"] == "Not ready"                      # escalated case waiting beyond 24 h, no reportability marker
    reg = {r["id"]: r["readiness"] for r in d["regimes"]}
    assert reg["sec"] == "confirm" and reg["dora"] == "n/a" and reg["nis2"] == "not ready", reg
    cap = {x["id"]: x["status"] for x in d["capabilities"]}
    assert cap["timeline"] == "ready" and cap["scope"] == "partial" and cap["integrity"] == "not ready", cap   # sample archive has 3 log-clearing events
    try:
        run(os.path.join(S, "render_report.py"), t + "/draft.json", t, "--no-pdf")
        assert any(f.startswith("Regulatory_Disclosure_Readiness_SampleCo_") and f.endswith(".html") for f in os.listdir(t))
    except subprocess.CalledProcessError as e:
        if "brand kit was not found" not in (e.stderr or "") + (e.stdout or ""):
            raise
        print("render skipped: fluency-report brand kit not found")
    print("ok")


if __name__ == "__main__":
    main()
