# Rating thresholds

Generated from `assets/rating_rules.json` by `scripts/make_thresholds_doc.py`. Do not edit by hand: change the rules file, then regenerate.

A pillar is **red** if any of its issues is Critical or a rule marks it red, **amber** if it has any High or Medium issue, partial evidence or a missing source, and **green** otherwise. The overall rating is Elevated Risk when Backup, Endpoint coverage or Prevention is red; High Risk with two or more red pillars; Resilient with no red or amber; otherwise Moderate Risk.

| Rule | Pillar | Severity | Fires when | Owner | Target | Pillar colour |
|---|---|---|---|---|---|---|
| B1 | Backup & Recovery | Critical | vulnerable backup servers that are domain-joined: at least 1 | Infrastructure | 7 days | red |
| B2 | Backup & Recovery | High | backup servers with a known critical flaw: at least 1 (not when B1 fired) | Infrastructure | 14 days | amber |
| E1 | Endpoint Coverage | Critical | (active devices with no EDR agent: at least 50 or unprotected servers: at least 1) | IT Operations | 30 days | red |
| E2 | Endpoint Coverage | High | active devices with no EDR agent: at least 1 (not when E1 fired) | IT Operations | 30 days | amber |
| E3 | Endpoint Coverage | Critical | agents silent past the vendor cutoff (7 days SentinelOne, 14 days CrowdStrike): at least 10% of agents | IT Operations | 30 days | red |
| E6 | Endpoint Coverage | High | agents silent past the vendor cutoff (7 days SentinelOne, 14 days CrowdStrike): at least 1 (not when E3 fired) | IT Operations | 30 days | amber |
| E7 | Endpoint Coverage | High | CrowdStrike agents with Real-Time Response off: at least 1 | Security Operations | 14 days | amber |
| E8 | Endpoint Coverage | High | network-contained CrowdStrike hosts: at least 1 | Security Operations | 14 days | amber |
| E9 | Endpoint Coverage | High | CrowdStrike agents with no firewall policy applied: at least 1 | Security Operations | 14 days | amber |
| E10 | Endpoint Coverage | High | CrowdStrike agents not provisioned: at least 1 | Security Operations | 14 days | amber |
| E11 | Endpoint Coverage | Medium | CrowdStrike agents with no sensor-update policy: at least 1 | Security Operations | 14 days | amber |
| E4 | Endpoint Coverage | Critical | CrowdStrike agents in reduced functionality mode: at least 1 | Security Operations | 14 days | red |
| E5 | Endpoint Coverage | Critical | CrowdStrike agents with no prevention policy applied: at least 1 | Security Operations | 14 days | red |
| P1 | Prevention & Hardening | High | hardening rules failing on every device: at least 5 | Endpoint Engineering | 60 days | red regardless of severity |
| P2 | Prevention & Hardening | Medium | (end-of-life devices: at least 1 or endpoints with a non-sanctioned remote-access tool: at least 1) | IT Operations | 90 days | amber |
| V1 | Vulnerability Exposure | High | devices with an exploitable CVE older than 30 days: at least 25 | IT Operations | 30 days | amber |
| V2 | Vulnerability Exposure | Medium | devices with an exploitable CVE: at least 1 (not when V1 fired) | IT Operations | 30 days | amber |
| D1 | Detection & Response | High | SentinelOne agents with either mitigation mode not in Protect: at least 1 | Security Operations | 14 days | amber |
| I1 | Identity & Access | Medium | (single-factor share of successful sign-ins (%): at least 5 or conditional-access policies requiring MFA for all users: exactly 0 or legacy-authentication sign-ins: at least 1) | Identity & Access | 30 days | amber |
| I2 | Identity & Access | High | single-factor share of successful sign-ins (%): at least 50 | Identity & Access | 30 days | amber |
| L1 | Logging & Forensics | High | security-log-cleared events: at least 1 | Security Operations | 14 days | amber |
| L2 | Logging & Forensics | High | services or tasks with attacker-tool names: at least 1 | Security Operations | 7 days | amber |
| T3 | Threat Activity | Critical | agents reporting an active infection: at least 1 | Security Operations | 24 hours | red |
| T4 | Threat Activity | Critical | unresolved threats with credential access, lateral movement, obfuscation or several on one host: at least 1 | Security Operations | 24 hours | red |
| T1 | Threat Activity | High | malicious threats not mitigated: at least 1 | Security Operations | 7 days | amber |
| T2 | Threat Activity | High | unresolved threats: at least 1 (not when T4 fired) | Security Operations | 14 days | amber |

## Strengths

A strength is listed when its test is true:

- connected agents: at least 95% of agents → N of N N agents are connected.
- agents in Protect mode: at least 95% of agents → Confirmed threats are blocked automatically on N of N agents (Protect mode).
- threats in the last 90 days: at least 1 and unresolved threats: exactly 0 → All N threats in the last N days are resolved.
- protective settings compliant on 95% or more of devices: at least 3 → N protective settings, for example N, are compliant on 95% or more of devices.
- Global Administrators: at least 1 and Global Administrators: at most 6 and cloud-only Global Administrators: at least 100% of Global Administrators → Global Administrator accounts are few (N) and cloud-only.
