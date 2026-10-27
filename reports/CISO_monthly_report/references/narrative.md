# narrative.json

Strings may contain HTML (`<strong>`) and `{{placeholders}}`.

| Key | Content |
|---|---|
| `rag` | `Green`, `Amber` or `Red` |
| `trend` | `improving`, `stable` or `declining` |
| `exec_summary` | list of paragraphs, no raw metrics |
| `decisions` | one or two leadership decisions |
| `caveat` | optional single caveat |
| `chapters` | `"2"` to `"7"`, each `{ "intro": str, "analysis": [paragraphs, at least 150 words in total], "callouts": [1 to 3 findings] }` |
| `trend_notes` | `{ category: text }` for the five rolling-trend categories |
| `repeat_why` | `{ identifier: reason }` for the repeat-actor tables |
| `root_causes` | rows `[theme, cases, linked users and assets, evidence, confidence]`, three to five |
| `exposure` | optional `o365_hygiene`, `environment_changes`, `vulnerability_highlights`, each `{evidence, limit}`; an omitted one uses the text built from `compliance_summary.json` facts, or a GAP without them |
| `blind_spots` | rows `[category, source, what cannot be detected, remediation, risk id]`, six fixed categories: missing log sources, partial coverage, protocol limits, architectural gaps, identity gaps, third-party access |
| `pathways` | three to five breach-pathway paragraphs, narrative not a MITRE table |
| `risks` | objects `{id, category, name, description, business_impact, likelihood, impact, mitigation}`; the script computes score and band |
| `remediation` | five to ten `{action, owner, due (YYYY-MM-DD), priority High/Medium/Low, risk, evidence}` |
| `client_actions` | `{action, owner, due, why, risk}` |
| `improvements` | list of paragraphs, only from a real change source; otherwise leave empty |
| `placeholders` | optional extra `{name: text}` values |

Placeholders computed from the evidence: `cases`, `cases_prev`, `closed`, `closed_prev`, `unacked`,
`unacked_prev`, `tp`, `tp_prev`, `fp`, `fp_prev`, `bp`, `bp_prev`, `mttr_samples`, `human_n`,
`closed_by_ai`, `no_human` (each also `_prev`), `mttr_p50`, `mttr_p90`, `mttc_p50`, `mttc_p90`,
`human_p50` (each also `_prev`), which print as `3h 27m` or `n/a` when there is no sample; add `_h`
for hours, such as `{{mttr_p50_h}}`. Category counts are `cat_identity_access`,
`cat_threat_attack`, `cat_endpoint`, `cat_network_perimeter`, `cat_vulnerability` and `cat_other`,
each also `cat_prev_…`. An unknown placeholder, including one whose value is `n/a`, raises a warning.
