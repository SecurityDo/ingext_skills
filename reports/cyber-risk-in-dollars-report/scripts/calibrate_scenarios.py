#!/usr/bin/env python3
"""Turn the ransomware-readiness evidence into FAIR scenarios for the Cyber Risk in Dollars report.

  calibrate_scenarios.py --resource resource_evidence.json [--windows windows_evidence.json] [--entra entra_evidence.json]
                         [--dlp dlp_evidence.json]
                         --rating draft_findings.json --tenant NAME [--business business_inputs.json] [--out scenarios.json]

--resource/--windows/--entra are the outputs of the ransomware-readiness scripts; --rating is the draft that
rate_evidence.py wrote (its `_review.rules_fired` says which readiness rules fired). Nothing here queries a tenant.
Frequency ranges come from baseline x (1 + the weights of the evidence factors that apply), widened for every input
the telemetry cannot measure. Loss ranges are a reference organization scaled by size (or built from revenue when it is
supplied). Every weight is in assets/calibration_rules.json and listed in references/calibration_rules.md.
"""
import argparse, datetime, html, json, math, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def get(ev, path):
    cur = ev
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def test(ev, t):
    v = get(ev, t["path"])
    if v is None:
        return False
    ref = t["value"]
    if "ratio_of" in t:
        base = get(ev, t["ratio_of"])
        if base in (None, 0):
            return False
        ref = t["value"] * base
    try:
        return OPS[t["op"]](v, ref)
    except TypeError:
        return False


def holds(ev, fired, node):
    """A factor, tier or treatment trigger: every condition present must hold."""
    if node.get("always"):
        return True
    if node.get("fired_any") and not (set(node["fired_any"]) & fired):
        return False
    if node.get("when") and not all(test(ev, t) for t in node["when"]):
        return False
    return bool(node.get("fired_any") or node.get("when"))


def fill(text, ev):
    miss = []

    def sub(m):
        v = get(ev, m.group(1))
        if v is None:
            miss.append(m.group(1))
            return "?"
        if isinstance(v, int) and not isinstance(v, bool) and v >= 1000:
            return f"{v:,}"
        return html.escape(str(v), quote=False)
    out = re.sub(r"\{([rwnd]\.[\w.]+)\}", sub, text)
    return out, miss


def rnd(v):
    if v >= 1_000_000:
        return round(v, -4)
    if v >= 10_000:
        return round(v, -3)
    return round(v, -2) if v >= 1000 else round(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resource", required=True)
    ap.add_argument("--windows")
    ap.add_argument("--entra")
    ap.add_argument("--dlp", help="dlp_evidence.json from the DLP report (enables the accidental and insider exposure scenario)")
    ap.add_argument("--rating", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--business")
    ap.add_argument("--date", help="assessment date YYYY-MM-DD (default: the rating draft's date)")
    ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "calibration_rules.json"))
    ap.add_argument("--out", default="scenarios.json")
    a = ap.parse_args()
    load = lambda p: json.load(open(p, encoding="utf-8")) if p and os.path.exists(p) else None
    R = json.load(open(a.rules, encoding="utf-8"))
    r, w, n = load(a.resource) or {}, load(a.windows), load(a.entra)
    rating = load(a.rating) or {}
    biz = load(a.business) or {}
    ev = {"r": r, "w": w or {}, "n": n or {}, "d": load(a.dlp) or {}}
    fired = set((rating.get("_review") or {}).get("rules_fired") or [])
    review = {"factors": {}, "gaps": {}, "defaults_used": [], "unresolved_placeholders": []}

    # ---- size
    ref_users = R["reference_users"]
    users = get(ev, "r.identity.enabled") or get(ev, "r.endpoint.agents")
    if users:
        scale = min(max((users / ref_users) ** R["scale_exponent"], R["scale_clamp"][0]), R["scale_clamp"][1])
        basis = "enabled accounts" if get(ev, "r.identity.enabled") else "endpoint agents"
    else:
        users, scale, basis = None, 1.0, "none"
        review["defaults_used"].append("No identity or endpoint count: loss figures use the reference organization unscaled")
    revenue = biz.get("annual_revenue")
    daily = biz.get("daily_downtime_cost") or (revenue / 365.0 * R["downtime"]["daily_from_revenue"] if revenue else None)
    if daily is None:
        review["defaults_used"].append("No revenue or downtime cost supplied: business interruption is scaled from the reference organization")

    # ---- scenarios
    scenarios = []
    for sid, sc in R["scenarios"].items():
        if sc.get("requires") and get(ev, sc["requires"]) is None:
            continue
        applied, weight, bullets = [], 0.0, []
        for f in sc["factors"]:
            node = None
            if f.get("tiers"):
                node = next((t for t in f["tiers"] if holds(ev, fired, t)), None)
            elif holds(ev, fired, f):
                node = f
            if node is None:
                continue
            wt = node["weight"]
            weight += wt
            applied.append({"id": f["id"], "label": f["label"], "weight": wt})
            text, miss = fill(node.get("text") or f["text"], ev)
            if miss:
                text = f["label"][:1].upper() + f["label"][1:]
            bullets.append(text)
        weight = min(weight, sc["weight_cap"])
        ml = sc["baseline_lef"] * (1 + weight)
        gaps = []
        for g in sc["gaps"]:
            if g.get("always") or (g.get("missing") and get(ev, g["missing"]) is None):
                gaps.append(g["text"])
        widen = min(1 + R["widen_per_gap"] * len(gaps), R["widen_cap"])
        lef = {"min": round(ml / R["lef_min_divisor"], 3), "ml": round(ml, 3), "max": round(ml * R["lef_max_multiplier"] * widen, 3)}
        review["factors"][sid] = applied
        review["gaps"][sid] = gaps
        bullets += ["Not measurable: " + (g[:1].lower() + g[1:] if g[1:2].islower() else g) for g in gaps]

        loss = []
        for c in sc["loss"]:
            ref = c["ref"]
            kind = c["scale"]
            if kind == "downtime" and daily:
                d, f_ = R["downtime"]["days"], R["downtime"]["daily_factor"]
                vals = {k: d[k] * f_[k] * daily for k in ("min", "ml", "max")}
            elif kind == "ransom" and revenue:
                cap = min(max(revenue * R["ransom"]["revenue_share"], R["ransom"]["floor"]), R["ransom"]["cap"])
                vals = {"min": 0, "ml": 0, "max": cap}
            elif kind == "none":
                vals = dict(ref)
            else:
                vals = {k: ref[k] * scale for k in ("min", "ml", "max")}
            loss.append({"name": c["name"], **{k: rnd(v) for k, v in vals.items()}})
        if revenue and R.get("revenue_cap"):
            rc = R["revenue_cap"]
            for key, share in (("ml", rc["ml_share"]), ("max", rc["max_share"])):
                tot = sum(c[key] for c in loss)
                lim = revenue * share
                if tot > lim and tot > 0:
                    for c in loss:
                        c[key] = rnd(c[key] * lim / tot)
                    review["defaults_used"].append(f"{sc['name']}: {key} loss per event limited to {int(share*100)}% of revenue")
            for c in loss:
                c["ml"] = min(c["ml"], c["max"]); c["min"] = min(c["min"], c["ml"])
        top = sorted(applied, key=lambda x: -x["weight"])[:3]
        why = ("the most likely value rises above the baseline because of " + ", ".join(x["label"] for x in top)) if top else "no evidence raises it above the baseline"
        cal = (f"Baseline frequency for a mid-market organization is {sc['baseline_lef']} events a year; {why}. "
               f"The range is widened by {round((widen - 1) * 100)}% at the top end because {len(gaps)} input{'s' if len(gaps) != 1 else ''} cannot be measured. {sc['anchor']}")
        scenarios.append({"id": sid, "name": sc["name"], "description": sc["description"], "lef": lef, "loss": loss, "evidence": bullets, "calibration": cal})

    modelled = {s["id"] for s in scenarios}
    # ---- treatments
    treatments = []
    for t in R["treatments"]:
        if not holds(ev, fired, t):
            continue
        eff = {k: v for k, v in t["effects"].items() if k in modelled}
        if not eff:
            continue
        detail, miss = fill(t["detail"], ev)
        if miss:
            detail = re.sub(r"\s*[^.]*\?[^.]*\.", "", detail) or t["name"]
        item = {"id": t["id"], "name": t["name"], "detail": detail, "owner": t["owner"], "timeframe": t["timeframe"], "effects": eff}
        cost = (biz.get("control_costs") or {}).get(t["id"])
        if cost is not None:
            item["annual_cost"] = cost
        treatments.append(item)

    # ---- text
    when = a.date or rating.get("assessment_date") or datetime.date.today().isoformat()
    tenant = html.escape(a.tenant, quote=False)
    window = rating.get("evidence_window", "")
    assumptions = []
    if daily:
        assumptions.append("Business interruption is built from " + ("the downtime cost supplied" if biz.get("daily_downtime_cost") else "annual revenue at about half of daily revenue lost") +
                           ", over 2 to 21 days of disruption (most likely 7), with the daily cost varying between 60% and 160%.")
    else:
        assumptions.append("No revenue or downtime cost was supplied, so business interruption is scaled from a reference organization of 1,700 accounts. Replace with the organization&rsquo;s own figures to sharpen the estimate.")
    if users:
        assumptions.append(f"Loss per event is scaled to about {users:,} {basis} using the square root of size against a 1,700-account reference organization, limited to between 0.3 and 3 times the reference.")
    if biz.get("insurance_limit"):
        assumptions.append("Cyber insurance recoveries and deductibles are not netted off; losses are gross. The insurance limit supplied is used only to show how often a year exceeds it.")
    else:
        assumptions.append("Cyber insurance recoveries and deductibles are not netted off; losses are gross.")
    assumptions.append("Extortion payment is modelled as usually not paid (most likely $0), consistent with IBM 2025 reporting that most victims refuse to pay.")
    if any("annual_cost" in t for t in treatments):
        assumptions.append("Return on investment is shown only for actions whose annual cost was supplied; the other costs are to be supplied.")
    else:
        assumptions.append("Annual control costs were not supplied, so return on investment is not calculated: cost to be supplied.")
    assumptions.append("Treatment effects are expert estimates of how much each control reduces frequency or cost, not measurements.")
    for nm in R["not_modelled"]:
        if nm.get("unless") and get(ev, nm["unless"]) is not None:
            continue
        assumptions.append(nm["text"])
    assumptions.append("Frequency and cost ranges come from fixed calibration rules (references/calibration_rules.md), applied to the ransomware-readiness evidence" + (f" ({html.escape(window, quote=False)})" if window else "") + ".")
    sources = ["IBM Cost of a Data Breach Report 2025: global average breach $4.44M; US average $10.22M; ransomware or extortion incident $5.08M; shadow AI adds about $670K",
               "FBI IC3 Internet Crime Report (BEC loss per complaint, approximate)",
               "The Open Group Risk Taxonomy (O-RT) and Risk Analysis (O-RA) standards (FAIR)",
               "Fluency / Ingext telemetry and the ransomware readiness assessment of " + when]
    if get(ev, "r.backup_vulnerable.cves"):
        sources.insert(2, "Vendor advisory for " + html.escape(str(get(ev, "r.backup_vulnerable.cves")), quote=False))
    out = {
        "tenant": tenant, "assessment_date": when, "evidence_window": window,
        "headline": "{TENANT} faces about {ALE} of expected cyber loss a year, and a bad year could exceed {P90}",
        "summary": ("Using FAIR-style analysis calibrated with {TENANT}&rsquo;s own security telemetry, we estimate expected annual cyber loss at {ALE}, with a 1-in-10-year loss of {P90} and a 1-in-20-year loss of {P95}. "
                    "{TOP_NAME} is the largest exposure, about {TOP_SHARE} of expected loss. {FREQ_NAME} is the most likely to occur in any year. "
                    "The recommended actions cut expected loss to {TALE}, an avoided loss of about {SAVED} a year. Where the telemetry cannot measure a control, the ranges are widened, never reduced."),
        "board_ask": ("accept this quantified view as the basis for cyber investment decisions, approve the highest-return actions first, " +
                      ("and confirm whether a 1-in-10-year loss of {P90} is within the organization&rsquo;s tolerance." if not biz.get("risk_appetite_p90") else "and note that the stated tolerance for a 1-in-10-year loss is {APPETITE}.")),
        "risk_appetite": biz.get("risk_appetite_p90"), "insurance_limit": biz.get("insurance_limit"),
        "scenarios": scenarios, "treatments": treatments, "assumptions": assumptions, "sources": sources,
        "_review": {**review, "rules_fired_from_readiness": sorted(fired),
                    "note": "Frequencies and losses are rule-based. Check the evidence bullets and assumptions before rendering; numbers in the text are filled in from the simulation."},
    }
    json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({s["id"]: {"lef": s["lef"], "per_event_ml": sum(c["ml"] for c in s["loss"]), "factors": [f["id"] for f in review["factors"][s["id"]]]} for s in scenarios}, indent=1))
    print("treatments:", [t["id"] for t in treatments])
    print("defaults used:", review["defaults_used"])


if __name__ == "__main__":
    main()
