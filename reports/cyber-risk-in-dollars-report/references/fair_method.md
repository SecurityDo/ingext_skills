# FAIR method (Cyber Risk in Dollars)

Risk = Loss Event Frequency (LEF, events a year) x Loss Magnitude (LM, dollars an event). Each input is a calibrated
range (minimum, most likely, maximum). The renderer samples PERT distributions, draws a Poisson number of events for
each of 20,000 simulated years, sums the per-event losses and repeats. It reports the mean (expected annual loss), the
90th percentile (the "1-in-10 bad year") and the 95th ("1-in-20"), a loss exceedance curve, and the same numbers after
the recommended actions.

## Scenarios

| id | Scenario | Evidence (all from the ransomware-readiness evidence) |
|---|---|---|
| ransomware | Ransomware and operational extortion | backup server exposure, unprotected devices, EDR blocking, ASR and LAPS hardening, exploitable CVEs, log clearing, active threats, admin MFA, remote-tool sprawl |
| bec | Business email compromise and payment fraud | sign-in archive: single-factor share, failed-sign-in pressure, risky and legacy sign-ins, admin MFA, all-users MFA |
| breach | Credential-driven cloud data breach | sign-in archive: single-factor share, risky sign-ins, MFA policy gaps and role exclusions, number of Global Administrators |

The older version of this report also modelled accidental and insider exposure (including shadow AI) from DLP matches and
generative-AI egress. Neither source exists in the archives or resource dumps, so it is not modelled; it returns when a
source is available. A scenario the data cannot support is dropped, never guessed.

## Rules, not judgment

Frequency and loss ranges come from `assets/calibration_rules.json` (listed in `calibration_rules.md`). The analyst does not
type numbers into the scenarios file; to change a figure, change the rules file and regenerate the document. Evidence counts
never become frequencies directly (1,000 failed logins is not 1,000 losses): they move the most likely value up from a
baseline by a fixed weight. Missing data widens the range and is never treated as lower risk.

## Inputs to request (ask once; proceed with stated defaults if unknown)

Annual revenue or daily downtime cost, cyber insurance limit and deductible, the largest 1-in-10-year loss the board will
tolerate, and the annual cost of each recommended action. Without revenue, loss is scaled from a reference organization of
1,700 accounts and the assumption is stated in the report.

## Treatments

Each recommended action multiplies the frequency and/or cost of the scenarios it affects (0.5 halves it). An action is
included only when the readiness rules that justify it fired. Effects are expert estimates, never measurements. If the annual
cost of an action is supplied the report shows the return (loss avoided divided by cost); otherwise "cost to be supplied".

## Benchmarks

IBM Cost of a Data Breach 2025: global average breach $4.44M, US average $10.22M, ransomware or extortion incident $5.08M,
shadow AI adds about $670K. FBI IC3: BEC loss per complaint roughly $130K. Check these with a web search when they are more
than a year old and update `assets/calibration_rules.json` before running.
