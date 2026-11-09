# Shadow AI scoring

Source: original Shadow AI skill (ciso-rpt-1) scoring table. Cut-offs marked proposal are Fluency proposals; the original
text says only "many hosts" and "broad use". All values live in `assets/rating_rules.json`.

| Path | High | Medium | Low | None |
|---|---|---|---|---|
| 1 SaaS AI (Entra) | AI app with a content-read scope plus offline_access and no verified publisher | non-first-party AI apps with user grants, an unverified third-party AI publisher, or a Tier 1 service | only first-party, enterprise-tier or verified apps | no AI apps |
| 2 Network egress | not assessed (no archived source) | | | |
| 3 Endpoint | local model runners on 5 or more hosts (proposal) | runners on 1 to 4 hosts, or non-Microsoft AI desktop apps on 10% or more of inventoried hosts (proposal) | smaller desktop footprint | nothing found |
| 4 Data exposure (DLP_Activity_Report) | Microsoft 365 Copilot DLP policy hits that were not enforced (adapted from the original: DLP hits coinciding with AI use) | Copilot hits that were enforced, or not all DLP rules enforce | matches, all enforced, none on the Copilot policy | not assessed when no matches |
| 5 Detection | | no enabled AI-specific EventWatch rule (original: no AI coverage is Medium) | at least one | |

Posture = highest assessed path risk (None or Low: Low; Medium: Moderate; High: Elevated), raised one level when three or
more paths are Medium or worse. The original sample file shows Elevated with five Medium-or-worse paths, which the literal
rule would raise to High; this skill applies the literal rule. A path with no data is "not assessed", never clean.

Known limits: granted permission names are not in the application dump for most apps (only ids), so the persistent-access
check covers apps whose permissions are named; the user dump lists granted app names, not scopes; approval status is
"unverified" unless a sanctioned list is supplied; Microsoft Copilot is first-party and never raises risk.
