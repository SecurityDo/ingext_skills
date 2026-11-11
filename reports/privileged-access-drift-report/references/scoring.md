# Scoring

All cut-offs live in `assets/rating_rules.json`. The original CISO Rpt 2 rating rule is kept; items marked proposal were not in the original.

| Rating | When |
|---|---|
| High | any tier-0 application permission granted in the window; a role assigned outside PIM by a person or by an application that does not reverse its grants; a PIM alert with no resolution; administrator single-factor sign-ins above 50% of successful administrator sign-ins |
| Elevated | permanent role grants added in PIM or outside PIM (time-boxed tooling counts); more than 4 Global Administrators; administrators with no registered MFA (proposal); single-factor share above 10% (proposal) |
| Moderate | any other finding (hygiene only) |
| Low | no finding |

- **Time-boxed tooling (proposal).** An application initiator whose "Remove member from role" events are at least 80% of its additions (the larger of "Add member to role" and the outside-PIM events) is treated as reversing its grants. The finding stays, with the net additions stated, and is rated medium instead of high.
- **Finding severities.** Critical: tier-0 application grants. High: single-factor above 50%, AI or tier-1 application grants with an AI connector among them, outside-PIM by a non-reversing initiator, 10+ permanent PIM grants, an unresolved PIM alert, administrators without MFA registration. Medium: the rest.
- **Single-factor** counts successful sign-ins whose `AuthenticationRequirement` is `singleFactorAuthentication` over successful sign-ins by accounts holding a directory role.
- **Dormant** is an enabled privileged account with no interactive sign-in in the window; it includes service accounts that sign in non-interactively.
- **Not observed** (no RoleManagement events, no on-premises group events) is never scored as "no drift".
