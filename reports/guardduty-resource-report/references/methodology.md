# Methodology

## Data

The report reads the archive of the scheduled FPL report `GuardDuty_Resource_Report`, one UTC day per archived run, and merges the archived
days: findings are counted on the day they were created and added up, and the current list is the latest day. Each day carries the tables below, computed in the tenant from two sources: the `GuardDuty` stream table (one row every
time GuardDuty sends or updates a finding) over the one-day run window, and the `GuarddutyFinding` resource table (GuardDuty's own
current list of recently updated findings, a snapshot with no history). `asOf` is the end of the run window. The current list is never added across days; the finding tables are (see Merging archived days).

| Table | Holds |
|---|---|
| `gdres_summary` | one row: findings, updates, high / medium / low, archived, active 24 hours and 7 days, new findings, repeat-heavy, accounts, regions, resource types, resources, first and last update, current-list counts, window days |
| `gdres_findings` | one row per finding id in the window, at most 200, highest severity first: type, category, severity, title, account, region, resource, created, first and last update, updates, GuardDuty count, archived, whether it is in the current list |
| `gdres_types` | finding types: findings, updates, resources, accounts, worst severity, first and last update |
| `gdres_accounts` | accounts by region: findings by severity, updates, resources, last update |
| `gdres_resources` | the top 100 resources: findings, types, updates, worst severity, most common type |
| `gdres_daily`, `gdres_created` | per day: updates, findings by severity; findings first raised that day |
| `gdres_repeat` | findings updated 10 or more times |
| `gdres_snapshot` | up to 200 rows of the current list, with a flag for whether each is in the window |
| `sources` | one row per query with `ok` or `not available` and the error |

## Counting

GuardDuty re-sends a finding each time it sees more of the same activity, so the stream holds many rows per finding. The processor
groups them by finding id: a finding is counted once, at its latest update, and `updates` is how many rows it had in the window.
`eventCount` is GuardDuty's own count of how often it saw the activity, which is a different number. Findings first raised in the
window (`created` inside it) are counted as new.

A finding that was not updated in the window does not appear in the findings table, even if GuardDuty still lists it. The
current-list table shows those, and the Data notes give the count.

## Severity

GuardDuty severity is a number from 0.1 to 8.9. High is 7 or more, Medium 4 up to 7, Low below 4.

## Attention score

Computed by the skill, not by the processor. Per finding:

| Condition | Points |
|---|---|
| Severity High / Medium / Low | 3 / 2 / 1 |
| Updated within the last 7 days (168 hours) before the end of the window | +1 |
| Archived in GuardDuty | score is 0 |

3 or more is Needs action, 2 is Watch, 1 is Low priority, 0 is Archived. A high severity finding is therefore always Needs action;
a medium one reaches it only when it is also recent, and a low one never does.

## Categories and resources

Category is the part of the finding type before the first colon (for example `Recon`, `UnauthorizedAccess`, `Exfiltration`). The resource
of a finding is its instance, else its EKS cluster, else its S3 bucket, else the access key owner.

## Merging archived days

Each archived run covers one UTC day (`windowDays` 1, ending the day before `asOf`). The script merges them as follows.

- **Added across days:** `events`, `newFindings`, `newHigh`, `newMedium` and `newLow` in `gdres_summary`, the counts in `gdres_types`,
  `gdres_accounts` and `gdres_resources` (a finding is in the tables of the day it was created), and one row per day in `gdres_daily` and
  `gdres_created`. The headline `findings`, `high`, `medium` and `low` are the findings created in the period, the same basis as the tables.
- **Not added:** the summary counts of findings updated in a run (`active24h`, `active7d`, `repeat10`) count a finding on every day it changes.
  `active24h` is the latest day, `active7d` is at least the busiest of the last 7 days, and `repeat10` is the busiest day.
- **Distinct counts:** accounts, regions, resource types and resources are counted from the merged tables, so the resource count is a lower bound
  (the daily tables are cut to the top rows).
- **Latest day:** `gdres_snapshot` and the `snapshot*` counts.
- **Gaps and repeats:** a day archived twice keeps the latest run; a missing day is listed as a gap and is not counted as zero.
- **Old archives:** runs from before the daily schedule have a 30-day window and overlap each other. They are used alone when no daily run
  exists, and are left out (with a note) when daily runs do.
