# Evidence files

Each file is the raw result of one MSOC (fluency-mssp) tool call, saved as JSON. The script reads
only the fields below; other fields are ignored.

| File | Fields read |
|---|---|
| `metrics.json`, `metrics_prev.json` | `capped`, `reported_total`, `case_count`, `unacked_count`, `closed_count`, `metrics.mttr` and `metrics.mttc` (`p50_seconds`, `p90_seconds`, `sample_n`), `effective_classifications.counts` |
| `fingerprints.json` | `fingerprints[]`: `hash`, `rules_str`, `case_count_in_window_live`, `mitre_attack.mapped_case_count`, `mitre_attack.techniques[]` (`tactic`, `technique_id`, `technique_name`, `case_count`) |
| `repeat.json`, `repeat_prev.json` | `admin_lookup_ok`, `cohorts.admin_watch`, `cohorts.repeat_offenders`, `cohorts.unclassified` (each `key`, `case_count`) |
| `cases.json`, `cases_prev.json` | `reported_total`, `cases[]`: `key`, `dayIndex`, `riskScore`, `status`, `classification`, `behaviorRules` |
| `sources.json` | `tenants.<grid>`: `configured_source_count`, `by_health`, `configured_integrations`, `verdict`, `findings[]` (`kind`, `integration`, `resource_type`, `probe_age_human`), `resource_freshness[]` |
| `compliance.json` | `assessment_type`, `counts`, `live_collection.counts`, `live_collection.collection_log[]`, `findings_toon` (rows with `not_observed`) |

Notes

- MTTD is structurally zero on this platform (a case is created at its first event), so the report
  says it is not meaningful.
- The time to first response comes from the earliest comment on a case. A case still in status new
  can carry one (an automated assistant comment), so the report flags the figure as possibly
  shorter than the true analyst response.
- A compliance result that is a skeleton (`assessment_skeleton_no_fluency_calls`) or that collected
  no sources is never rendered; the section is marked GAP.
- Rolling-trend categories come from keywords in `behaviorRules` (the `CATEGORIES` table at the top
  of `build_report.py`). A case counts once, in the first matching category; unmatched cases are
  shown as Other. Adjust the table for a tenant's rule names if too many fall into Other.
