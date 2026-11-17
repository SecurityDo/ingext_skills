#!/usr/bin/env python3
"""Path 2 smoke test: synthetic FortiGate archive -> egress_evidence -> ai_evidence -> rate_evidence. Run: python3 tests/test_egress.py"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); S = os.path.join(ROOT, "scripts")


def run(*a):
    return subprocess.run([sys.executable, "-I"] + list(a), check=True, capture_output=True, text=True).stdout


def dims(day, nsrc, named=True):
    r = lambda dim, val, outcome, ev, out=0: {"dim": dim, "val": val, "outcome": outcome, "events": ev, "bytesOut": out, "bytesIn": 0}
    app = lambda n: n if named else "(not recorded)"
    rows = [r("device", "fw1 | " + day, "allowed", 9000), r("device", "fw1 | " + day, "blocked", 1000),
            r("app", app("HTTPS.BROWSER") + " | Web.Client", "allowed", 6000), r("app", app("DNS") + " | Network.Service", "allowed", 3000),
            r("app", "(not recorded) | (not recorded)", "allowed", 1000)]
    if named:
        rows += [r("genaiApp", "ChatGPT | AI", "allowed", 40, 5000), r("genaiApp", "ChatGPT | AI", "blocked", 10, 0), r("genaiApp", "Claude.AI | AI", "allowed", 20, 900),
                 r("genaiApp", "Microsoft.Copilot | AI", "allowed", 15, 100), r("genaiPolicy", "7 | ChatGPT", "allowed", 50), r("genaiPolicy", "9 | Claude.AI", "allowed", 20)]
        rows += [r("genaiSource", "10.0.0.%d | host%d | ChatGPT" % (i, i), "allowed", 1) for i in range(nsrc)]
        rows += [r("genaiDestination", "203.0.113.5 | United States | ChatGPT", "allowed", 40), r("genaiDestination", "198.51.100.9 | Ireland | Claude.AI", "allowed", 20)]
    return {"entry": {"rangeFrom": day + "T00:00:00Z"}, "result": {"objects": [
        {"name": "traffic_dims", "table": {"rows": rows}}, {"name": "traffic_talkers", "table": {"rows": [{"source": "must-not-be-read", "host": "x", "events": 1}]}},
        {"name": "sources", "table": {"rows": [{"source": "NetworkFortigateTraffic dimensions", "status": "ok"}, {"source": "NetworkFortigateTraffic talkers", "status": "ok"}]}}]}}


def main():
    t = tempfile.mkdtemp(); w = lambda n, d: (json.dump(d, open(t + "/" + n, "w")), t + "/" + n)[1]
    f = w("fg.json", {"days": [dims("2026-11-10", 30), dims("2026-11-11", 20)]})
    run(os.path.join(S, "egress_evidence.py"), f, "-o", t + "/eg.json"); eg = json.load(open(t + "/eg.json"))
    assert eg["status"] == "assessed" and eg["days"] == 2 and eg["total_events"] == 20000 and eg["named_share"] == 0.9, eg
    assert eg["genai_events"] == 170 and eg["genai_blocked"] == 20 and eg["sources_peak_day"] == 30 and eg["countries"] == ["Ireland", "United States"] and eg["policies"] == 2, eg
    sv = {x["service"]: x for x in eg["services"]}
    assert sv["ChatGPT / OpenAI"]["events"] == 100 and sv["Microsoft Copilot"]["first_party"] and eg["non_first_party_allowed"] == 120, sv
    blob = json.dumps(eg); assert "10.0.0." not in blob and "host1" not in blob and "must-not-be-read" not in blob and "203.0.113" not in blob   # no host, address or talker
    d0 = t + "/dumps"; os.mkdir(d0)
    run(os.path.join(S, "ai_evidence.py"), d0, "-o", t + "/ev.json", "--egress", t + "/eg.json")
    run(os.path.join(S, "rate_evidence.py"), t + "/ev.json", "--tenant", "Sample Co", "--date", "2026-11-12", "--out", t + "/draft.json")
    d = json.load(open(t + "/draft.json")); p = next(x for x in d["paths"] if x["id"] == "network")
    assert p["status"] == "assessed" and p["risk"] == "high", p                     # 120 allowed events, 30 sources on the busiest day (25 or more)
    assert any(x["path"] == "network" and x["severity"] == "high" for x in d["findings"]), d["findings"]
    assert any(r["service"].startswith("Claude") and "network" in r["seen_in"] for r in d["services"]), d["services"]
    assert not any("is not assessed: no Fortigate" in g for g in d["coverage_gaps"]) and any("FortiGate only" in g for g in d["coverage_gaps"])
    # few sources: medium; everything blocked: low
    g2 = json.load(open(t + "/eg.json")); g2["sources_peak_day"] = 5; json.dump(g2, open(t + "/eg2.json", "w"))
    run(os.path.join(S, "ai_evidence.py"), d0, "-o", t + "/ev2.json", "--egress", t + "/eg2.json"); run(os.path.join(S, "rate_evidence.py"), t + "/ev2.json", "--tenant", "S", "--date", "2026-11-12", "--out", t + "/d2.json")
    assert next(x for x in json.load(open(t + "/d2.json"))["paths"] if x["id"] == "network")["risk"] == "medium"
    # no application names (Application Control off): not assessed, never clean
    run(os.path.join(S, "egress_evidence.py"), w("fg3.json", {"days": [dims("2026-11-10", 0, named=False)]}), "-o", t + "/eg3.json"); e3 = json.load(open(t + "/eg3.json"))
    assert e3["status"] == "no_app_control" and any("not clean" in g for g in e3["gaps"]), e3
    # no archive and no egress file: not assessed
    run(os.path.join(S, "egress_evidence.py"), w("fg4.json", {"days": []}), "-o", t + "/eg4.json"); assert json.load(open(t + "/eg4.json"))["status"] == "no_data"
    run(os.path.join(S, "ai_evidence.py"), d0, "-o", t + "/ev5.json"); run(os.path.join(S, "rate_evidence.py"), t + "/ev5.json", "--tenant", "S", "--date", "2026-11-12", "--out", t + "/d5.json")
    q = next(x for x in json.load(open(t + "/d5.json"))["paths"] if x["id"] == "network"); assert q["status"] == "no_data", q
    print("ok")


if __name__ == "__main__":
    main()
