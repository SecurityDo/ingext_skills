#!/usr/bin/env python3
"""Write references/calibration_rules.md from assets/calibration_rules.json (run after every change to the rules)."""
import html, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "..", "assets", "calibration_rules.json"), encoding="utf-8"))
OUT = os.path.join(HERE, "..", "references", "calibration_rules.md")
LABEL = {
    "r.unprotected.not_in_edr_agent_list": "active devices with no EDR agent", "r.endpoint.agents": "agents",
    "r.remote_other_endpoints": "endpoints with a non-sanctioned remote-access tool",
    "n.signins.single_factor_share_pct": "single-factor share of successful sign-ins (%)", "n.signins.legacyAuth": "legacy-authentication sign-ins",
    "n.signins.risky": "risky sign-ins", "n.signins.failed": "failed sign-ins", "n.signins.events": "sign-in attempts",
    "r.conditional_access.mfa_all_users": "enforced policies requiring MFA for all users on all apps", "r.identity.global_admins": "Global Administrators",
}
OPW = {">=": "at least", ">": "more than", "<=": "at most", "<": "fewer than", "==": "exactly", "!=": "not"}
plain = lambda s: html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"\{[^}]+\}", "N", s)))


def cond(node):
    parts = []
    if node.get("always"):
        return "always"
    if node.get("fired_any"):
        parts.append("readiness rule " + " or ".join(node["fired_any"]) + " fired")
    for t in node.get("when", []):
        lab = LABEL.get(t["path"], t["path"])
        if "ratio_of" in t:
            parts.append(f"{lab}: {OPW[t['op']]} {round(t['value'] * 100)}% of {LABEL.get(t['ratio_of'], t['ratio_of'])}")
        else:
            parts.append(f"{lab}: {OPW[t['op']]} {t['value']}")
    return " and ".join(parts)


m = lambda x: "${:,.0f}".format(x)
L = ["# Calibration rules", "", "Generated from `assets/calibration_rules.json` by `scripts/make_calibration_doc.py`. Do not edit by hand: change the rules file, then regenerate.", "",
     "Frequency (events a year) is `baseline x (1 + sum of the weights of the factors that apply)`, with the sum capped per scenario. Minimum is the most likely value divided by "
     f"{R['lef_min_divisor']}; maximum is the most likely value times {R['lef_max_multiplier']}, widened by {round(R['widen_per_gap'] * 100)}% for every input the telemetry cannot measure (capped at {round((R['widen_cap'] - 1) * 100)}%). "
     "Missing data widens the range and is never treated as zero risk. All weights and loss figures are Fluency proposals for a mid-market organization, not measurements.", "",
     f"Loss per event is a reference organization of {R['reference_users']:,} accounts, scaled by (accounts / {R['reference_users']:,}) to the power {R['scale_exponent']}, limited to "
     f"{R['scale_clamp'][0]} to {R['scale_clamp'][1]} times. When revenue or a daily downtime cost is supplied, business interruption is days of disruption "
     f"({R['downtime']['days']['min']}, {R['downtime']['days']['ml']}, {R['downtime']['days']['max']}) times the daily cost (times {R['downtime']['daily_factor']['min']}, {R['downtime']['daily_factor']['ml']}, {R['downtime']['daily_factor']['max']}), "
     f"with the daily cost taken as {round(R['downtime']['daily_from_revenue'] * 100)}% of daily revenue when only revenue is given, and the extortion maximum is {round(R['ransom']['revenue_share'] * 100)}% of revenue between {m(R['ransom']['floor'])} and {m(R['ransom']['cap'])}.", ""]
for sid, sc in R["scenarios"].items():
    L += [f"## {html.unescape(sc['name'])}", "", f"Baseline {sc['baseline_lef']} events a year; weight cap {sc['weight_cap']}.", "", "| Evidence factor | Adds | When |", "|---|---|---|"]
    for f in sc["factors"]:
        if f.get("tiers"):
            for t in f["tiers"]:
                L.append(f"| {f['label']} | +{t['weight']} | {cond(t)} |")
        else:
            L.append(f"| {f['label']} | +{f['weight']} | {cond(f)} |")
    L += ["", "Not measurable (each widens the maximum): " + "; ".join(g["text"] for g in sc["gaps"]) + ".", "",
          "| Loss component (reference size) | Min | Likely | Max | Scaling |", "|---|---|---|---|---|"]
    for c in sc["loss"]:
        L.append(f"| {html.unescape(c['name'])} | {m(c['ref']['min'])} | {m(c['ref']['ml'])} | {m(c['ref']['max'])} | {c['scale']} |")
    L += ["", sc["anchor"], ""]
L += ["## Recommended actions and their modelled effect", "", "An effect multiplies the frequency (lef) or the cost per event (lm); 0.5 halves it. These are expert estimates.", "",
      "| Action | Included when | Effect |", "|---|---|---|"]
for t in R["treatments"]:
    eff = "; ".join(f"{k}: " + ", ".join(f"{a} x{b}" for a, b in v.items()) for k, v in t["effects"].items())
    L.append(f"| {t['name']} | {cond(t)} | {eff} |")
L += ["", "## Not modelled", ""] + [f"- {n['text']}" for n in R["not_modelled"]] + ["", "## Benchmarks", "", R["benchmarks"]["text"], ""]
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("wrote", OUT)
