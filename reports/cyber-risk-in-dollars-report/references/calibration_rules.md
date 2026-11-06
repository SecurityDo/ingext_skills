# Calibration rules

Generated from `assets/calibration_rules.json` by `scripts/make_calibration_doc.py`. Do not edit by hand: change the rules file, then regenerate.

Frequency (events a year) is `baseline x (1 + sum of the weights of the factors that apply)`, with the sum capped per scenario. Minimum is the most likely value divided by 3; maximum is the most likely value times 3, widened by 10% for every input the telemetry cannot measure (capped at 60%). Missing data widens the range and is never treated as zero risk. All weights and loss figures are Fluency proposals for a mid-market organization, not measurements.

Loss per event is a reference organization of 1,700 accounts, scaled by (accounts / 1,700) to the power 0.5, limited to 0.3 to 3.0 times. When revenue or a daily downtime cost is supplied, business interruption is days of disruption (2, 7, 21) times the daily cost (times 0.6, 1.0, 1.6), with the daily cost taken as 50% of daily revenue when only revenue is given, and the extortion maximum is 2% of revenue between $250,000 and $5,000,000. As in the Fluency footprint tools, loss per event is limited to 5% of revenue (most likely) and 15% (maximum) when revenue is supplied.

## Ransomware & operational extortion

Baseline 0.08 events a year; weight cap 1.5.

| Evidence factor | Adds | When |
|---|---|---|
| exposed backup servers | +0.25 | readiness rule B1 fired |
| devices without endpoint protection | +0.15 | active devices with no EDR agent: at least 5% of agents |
| anti-ransomware hardening not confirmed | +0.15 | readiness rule P1 fired |
| EDR agents not in Protect mode | +0.1 | readiness rule D1 fired |
| CrowdStrike sensors with reduced protection | +0.1 | readiness rule E4 or E5 fired |
| aging exploitable vulnerabilities | +0.05 | readiness rule V1 fired |
| log clearing | +0.05 | readiness rule L1 fired |
| suspicious persistence | +0.05 | readiness rule L2 fired |
| active threats | +0.25 | readiness rule T1 or T3 or T4 fired |
| administrators without enforced MFA | +0.1 | readiness rule I3 fired |
| extra remote-access tools | +0.05 | readiness rule P2 fired and endpoints with a non-sanctioned remote-access tool: at least 1 |

Not measurable (each widens the maximum): Backup success, age, immutability and restore tests cannot be measured, so recovery ability is unproven; No endpoint application inventory, so backup software exposure is unknown; No EDR threat inventory; No Windows audit archive, so log clearing and persistence are unknown.

| Loss component (reference size) | Min | Likely | Max | Scaling |
|---|---|---|---|---|
| Business interruption | $1,000,000 | $2,500,000 | $8,000,000 | downtime |
| Response, recovery & rebuild | $500,000 | $1,500,000 | $4,000,000 | size |
| Extortion payment | $0 | $0 | $3,000,000 | ransom |
| Legal, notification & regulatory | $100,000 | $500,000 | $2,500,000 | size |

Per-event cost is anchored to the IBM 2025 average cost of a ransomware or extortion incident ($5.08M) and scaled to organization size.

## Business email compromise & payment fraud

Baseline 0.5 events a year; weight cap 1.0.

| Evidence factor | Adds | When |
|---|---|---|
| single-factor sign-ins | +0.25 | single-factor share of successful sign-ins (%): at least 25 |
| single-factor sign-ins | +0.1 | single-factor share of successful sign-ins (%): at least 5 |
| administrators without enforced MFA | +0.2 | readiness rule I3 fired |
| no all-users MFA | +0.1 | enforced policies requiring MFA for all users on all apps: exactly 0 |
| legacy authentication in use | +0.15 | readiness rule I5 fired and legacy-authentication sign-ins: at least 1 |
| legacy authentication in use | +0.1 | legacy-authentication sign-ins: at least 1 |
| risky sign-ins | +0.1 | risky sign-ins: at least 1 |
| high failed sign-in share | +0.1 | failed sign-ins: at least 25% of sign-in attempts |
| inbox-rule activity | +0.15 | n.o365.inboxRuleChanges: at least 0% of n.o365.events |
| inbox-rule activity | +0.08 | n.o365.inboxRuleChanges: at least 0% of n.o365.events |
| mailbox-permission changes | +0.05 | n.o365.mailboxPermissionChanges: at least 0% of n.o365.events |

Not measurable (each widens the maximum): Forwarding targets, who changed inbox rules and payment-verification controls cannot be measured (the archive counts rule and permission changes, not their content); No sign-in archive, so credential-attack pressure is unmeasured; No Office 365 workload archive, so inbox-rule and mailbox-permission activity is unmeasured.

| Loss component (reference size) | Min | Likely | Max | Scaling |
|---|---|---|---|---|
| Fraudulent transfer | $20,000 | $130,000 | $1,200,000 | none |
| Investigation & remediation | $15,000 | $40,000 | $150,000 | size |

Per-event loss uses the FBI IC3 average BEC loss (about $130K) with a long tail for large wires.

## Credential-driven data breach (cloud)

Baseline 0.1 events a year; weight cap 1.0.

| Evidence factor | Adds | When |
|---|---|---|
| single-factor sign-ins | +0.25 | single-factor share of successful sign-ins (%): at least 15 |
| single-factor sign-ins | +0.1 | single-factor share of successful sign-ins (%): at least 5 |
| no all-users MFA | +0.15 | enforced policies requiring MFA for all users on all apps: exactly 0 |
| privileged roles exempt from MFA | +0.15 | readiness rule I4 fired |
| risky sign-ins | +0.1 | risky sign-ins: at least 1 |
| many standing Global Administrators | +0.05 | Global Administrators: at least 5 |

Not measurable (each widens the maximum): MFA registration, OAuth consents and file-download volumes cannot be measured; No sign-in archive.

| Loss component (reference size) | Min | Likely | Max | Scaling |
|---|---|---|---|---|
| Response & notification | $300,000 | $1,000,000 | $3,000,000 | size |
| Legal & regulatory | $50,000 | $400,000 | $2,500,000 | size |
| Lost business & reputation | $200,000 | $1,000,000 | $5,000,000 | size |

Per-event cost sits below the IBM 2025 global average breach ($4.44M) at mid-market scale, with a tail toward the US average ($10.22M).

## Recommended actions and their modelled effect

An effect multiplies the frequency (lef) or the cost per event (lm); 0.5 halves it. These are expert estimates.

| Action | Included when | Effect |
|---|---|---|
| Patch and isolate backup servers; immutable copies | readiness rule B1 or B2 fired | ransomware: lm x0.55 |
| Prove recovery: restore test and backup monitoring | always | ransomware: lm x0.85 |
| Close endpoint gaps and turn on anti-ransomware hardening | readiness rule E1 or E2 or E3 or E4 or E5 or E6 or D1 or P1 fired | ransomware: lef x0.55; breach: lef x0.9 |
| Contain active threats now | readiness rule T1 or T3 or T4 fired | ransomware: lef x0.7 |
| Patch exploitable vulnerabilities, oldest first | readiness rule V1 or V2 fired | ransomware: lef x0.85 |
| Enforce MFA and Conditional Access | readiness rule I1 or I2 or I3 or I4 fired | bec: lef x0.6; breach: lef x0.6; ransomware: lef x0.85 |
| Block legacy authentication | readiness rule I5 fired | bec: lef x0.9; breach: lef x0.95 |
| Payment verification and inbox-rule alerting | always | bec: lef x0.8, lm x0.5 |
| Stop log clearing; keep 90-day log retention | readiness rule L1 or L2 fired | ransomware: lm x0.9; breach: lm x0.85 |

## Not modelled

- Accidental and insider data exposure, including shadow AI, is not modelled: the Office 365 archive counts sharing and external-access events but shows zero DLP matches, which cannot separate "no DLP policy" from "no matches", and there is no generative-AI egress source.
- Third-party and remote-tool compromise is not modelled separately to avoid double counting; extra remote-access tools already raise the ransomware frequency.

## Benchmarks

IBM Cost of a Data Breach 2025: global average breach $4.44M, US average $10.22M, ransomware or extortion incident $5.08M, shadow AI adds about $670K. FBI IC3: BEC loss per complaint roughly $130K. Verify with a web search when more than a year old.
