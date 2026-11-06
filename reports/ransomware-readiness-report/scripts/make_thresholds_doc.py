#!/usr/bin/env python3
"""Regenerate references/rating_thresholds.md from assets/rating_rules.json.

Usage: make_thresholds_doc.py [rules.json] [out.md]
Run it after every change to the rules so the document never drifts from them.
"""
import html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "assets", "rating_rules.json")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "references", "rating_thresholds.md")
LABEL = {
    "r.backup_vulnerable.exploitable_now": "vulnerable backup servers that are domain-joined",
    "r.backup_vulnerable.endpoints": "backup servers with a known critical flaw",
    "r.unprotected.not_in_edr_agent_list": "active devices with no EDR agent",
    "r.unprotected.of_which_servers": "unprotected servers",
    "r.endpoint.stale_7d": "agents silent for over 7 days",
    "r.endpoint.detect_only": "agents fully in detect-only mode",
    "r.endpoint.suspicious_detect_only": "agents with the suspicious policy in detect-only",
    "r.hardening_rules_failing_everywhere": "hardening rules failing on every device",
    "r.eol_total": "end-of-life devices",
    "r.remote_other_endpoints": "endpoints with a non-sanctioned remote-access tool",
    "r.vulnerabilities.exploitable_older_than_30d_devices": "devices with an exploitable CVE older than 30 days",
    "r.vulnerabilities.exploit_available_devices": "devices with an exploitable CVE",
    "n.signins.single_factor_share_pct": "single-factor share of successful sign-ins (%)",
    "r.conditional_access.mfa_all_users": "conditional-access policies requiring MFA for all users",
    "n.signins.legacyAuth": "legacy-authentication sign-ins",
    "w.log_clearing.events": "security-log-cleared events",
    "w.persistence.suspect_count": "services or tasks with attacker-tool names",
    "r.threats.unmitigated_malicious": "malicious threats not mitigated",
    "r.threats.unresolved": "unresolved threats",
    "r.endpoint.agents": "agents",
    "r.endpoint.connected": "connected agents",
    "r.endpoint.mitigation_modes.protect": "agents in Protect mode",
    "r.threats.total": "threats in the last 90 days",
    "r.strong_controls_count": "protective settings compliant on 95% or more of devices",
    "r.identity.global_admins": "Global Administrators",
    "r.identity.global_admins_cloud_only": "cloud-only Global Administrators",
}
OPW = {">=": "at least", ">": "more than", "<=": "at most", "<": "fewer than", "==": "exactly", "!=": "not"}


def phrase(t):
    lab = LABEL.get(t["path"], t["path"])
    if "ratio_of" in t:
        return f"{lab}: {OPW[t['op']]} {round(t['value'] * 100)}% of {LABEL.get(t['ratio_of'], t['ratio_of'])}"
    return f"{lab}: {OPW[t['op']]} {t['value']}"


rules = json.load(open(RULES))
names = {p["key"]: html.unescape(p["name"]) for p in rules["pillars"]}
L = ["# Rating thresholds", "",
     "Generated from `assets/rating_rules.json` by `scripts/make_thresholds_doc.py`. Do not edit by hand: change the rules file, then regenerate.", "",
     "A pillar is **red** if any of its issues is Critical or a rule marks it red, **amber** if it has any High or Medium issue, partial evidence or a missing source, and **green** otherwise. "
     "The overall rating is Elevated Risk when Backup, Endpoint coverage or Prevention is red; High Risk with two or more red pillars; Resilient with no red or amber; otherwise Moderate Risk.", "",
     "| Rule | Pillar | Severity | Fires when | Owner | Target | Pillar colour |", "|---|---|---|---|---|---|---|"]
for r in rules["rules"]:
    all_ = " and ".join(phrase(t) for t in r.get("when", []))
    any_ = " or ".join(phrase(t) for t in r.get("when_any", []))
    cond = all_ + ((" and " if all_ else "") + "(" + any_ + ")" if any_ else "")
    if r.get("suppress_if"):
        cond += f" (not when {', '.join(r['suppress_if'])} fired)"
    L.append(f"| {r['id']} | {names[r['pillar']]} | {r['severity']} | {cond} | {html.unescape(r['owner'])} | {r['target']} | "
             f"{'red regardless of severity' if r.get('pillar_status') == 'red' else ('red' if r['severity'] == 'Critical' else 'amber')} |")
L += ["", "## Strengths", "", "A strength is listed when its test is true:", ""]
for s in rules["strengths"]:
    L.append("- " + " and ".join(phrase(t) for t in s["when"]) + " → " + re.sub(r"\{[^}]+\}", "N", html.unescape(s["text"])))
open(OUT, "w").write("\n".join(L) + "\n")
print("wrote", OUT)
