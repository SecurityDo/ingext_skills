# Scoring: Regulatory Disclosure Readiness

All thresholds are in `assets/rating_rules.json`. Items marked proposal were not stated in the original Board Rpt 3 skill.

## Capabilities (ready / partial / not ready / confirm)

| Capability | Ready | Partial | Not ready |
|---|---|---|---|
| Detection and automated triage | AI verdict on 80%+ of cases examined and median 60 min or less (proposal) | AI verdicts exist but slower or sparser, or none exist so triage time cannot be measured | n/a |
| Human escalation and ownership | No open serious cases | Open cases exist | Any AI-escalated case without a human status change beyond 24 h, or a quarter or more of open cases older than 14 days (proposal) |
| Reportability classification | A reportability or materiality marker on case classifications or actions | Counsel states determinations are recorded outside the SIEM | No marker found |
| Timeline reconstruction | Always: 12-month retention is a platform guarantee (proposal to revisit if tenants can shorten it) | n/a | n/a |
| Scope of data and systems | Identity, collaboration, endpoint and network sources all present | Two or three of those present | One or none |
| Evidence integrity | No log-clearing events in the archived WindowsSrv_Activity_Report days | n/a | Any log-clearing event; no archive = Confirm |
| Third-party awareness; board, legal and customer workflow | n/a | n/a | always Confirm (documents) |

## Regimes

Readiness is the worst of the measured capabilities its clock depends on (see `regimes` in the rules file). When counsel's applicability
answer is "unknown" the regime shows Confirm and the computed readiness is quoted in its gap text; "no" shows Not applicable. DORA
defaults to "no", customer notice to "yes".

## Overall rating (original playbook, plus the open-age test)

- **Not ready:** an escalated case has no human decision beyond the tightest deadline (24 h), or a quarter or more of open cases are older than 14 days (proposal), or no reportability determination exists.
- **Partially ready:** decisions exist but evidence or scope gaps remain.
- **Ready:** none of the above.

## Notes on measurement

- Escalation: an AI-Assistant comment whose content has `"actionable": true`, a decision starting "Escalate", or the word ESCALATE (the original rule).
- Human decision: a comment by a non AI-Assistant user whose `actions` change status or classification.
- Triage time: case `incidentDetectionTime` (else `from`) to the first AI-Assistant comment.
