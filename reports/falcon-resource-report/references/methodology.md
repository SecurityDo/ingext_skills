# Methodology

## Data

The report reads the archive of the scheduled FPL report `CrowdStrike_Resource_Report`, one UTC day per archived run, and merges the archived days: the host tables from the latest day, the detections added across all days. Each day carries the tables below, all computed in the tenant from the `falconAgent` host table (a snapshot of
the console, no history) and the `FalconAlert` stream (the detections created in the one-day run window). `asOf` is the end of the run window. The host tables are never added across days; the detection tables are (see Merging archived days).

| Table | Holds |
|---|---|
| `falres_summary` | one row: host count, stale and silent counts, current and older sensor counts, newest version, current releases, protection-gap counts, needs action / watch / healthy, detection totals, window days |
| `falres_hosts` | hosts with a score above 0, highest first, at most 500: name, id, platform, role, OS, sensor, days since seen, score, status, reasons, detection counts |
| `falres_seen`, `falres_versions`, `falres_platforms`, `falres_policies`, `falres_weekly` | check-in buckets, sensor versions (top 25), platform and role, policy coverage, new hosts per week |
| `falres_alert_sev`, `_status`, `_tactics`, `_names`, `_hosts`, `_other` | detection counts by severity, status, tactic and name; the top 25 hosts with open detections; other alert products |
| `sources` | one row per query with `ok` or `not available` and the error |

The fleet figures come from the summary and the fleet tables, which cover every host. The host table lists only scored hosts, so a
healthy host is counted but not named, and a long list is cut at 500 (the report says so). Operating-system, domain, site,
criticality, tag and last-user data are not in the archive and are not shown.

## Last check-in

Days from `last_seen` to `asOf`, the end of the run window (whole calendar days). Buckets: under 1, 1 to 7, 8 to 30, 31 to 90, over 90 days. More than 7
days is stale; more than 30 days is silent. Laptops are often offline for a week, so stale hosts score lower than silent ones.

## Sensor releases

The sensor version is `major.minor.build.patch`. The report ranks the distinct major.minor releases in the fleet from newest
down. A host is current when its release is one of the newest three (N, N-1, N-2). It is not the latest Falcon release: a fleet
that never upgrades reports 100% current. Ranking by release rather than by exact version avoids flagging 4,500 hosts because
a handful of pilot hosts run a newer build.

## Host score

Points per host, summed:

| Condition | Points |
|---|---|
| Reduced functionality mode is `yes` | 3 |
| `provision_status` is `NotProvisioned` | 3 |
| No prevention policy assigned | 3 |
| No check-in for more than 30 days | 3 |
| Prevention policy assigned but not applied | 2 |
| No check-in for 8 to 30 days | 2 |
| Never checked in | 2 |
| Host is contained (`status` is not `normal`) | 2 |
| Uninstall protection in `MAINTENANCE_MODE` | 2 |
| Uninstall protection not `ENABLED` on Windows or Mac | 1 |
| Sensor release older than the newest three | 1 |
| Safe mode | 1 |

3 or more is **Needs action**, 1 or 2 is **Watch**, 0 is **Healthy**. The weights are in `analyse()` in the script.

Not scored: last reboot age, host criticality, tags and groups. They are shown for context. The report counts how many critical
or high-rated hosts need action, so a reader can start there.

## Policies

`device_policies` lists every policy type assigned to the host. The Policy coverage table counts, for 12 core policy types, the
hosts with the policy assigned, the hosts without it, and the hosts where it is assigned but `applied` is false. 

## Known data pitfalls

- **`provision_status` can be empty.** An empty value is not scored; only `NotProvisioned` is.
- **Uninstall protection** is `IGNORE` on Linux, where it does not apply. It is only scored on Windows and Mac.
- **A tenant without Falcon** has no host rows: the archived summary is empty or has zero hosts and `check` reports PROBLEM.
- **`last_seen` is the sensor check-in**, not a user login.
- **A stale archive.** The host figures are as of the latest archived day; `check` flags a day older than 3 days. A missing day is
  never filled by searching; `backfill_report_archive` records today's state under the past date.
- **Archived query failures** appear in `sources` and the Data notes; the panel for a failed query is empty.

## Detections (FalconAlert)

FalconAlert is an event stream. The same alert is emitted again each time its status changes, so the report filters on
`created_timestamp` (the alert's creation time) rather than the emit time, and aggregates per host, severity, status and tactic.
The archived run joins them to hosts on `agent_id` = `device_id` (the open-alert host ids are written into the host query, because a join against the alert stream does not work on the engine).

Counted per host: product `epp` (endpoint detections) and `automated-lead` (leads). Open means status `new`, `in_progress` or
`reopened`. Scoring: an open High or Critical detection adds 3 (Needs action on its own); any other open detection or open lead adds 1.
Closed alerts do not score. Product `idp`, `data-protection`, `fcs`, `ngsiem` and `thirdparty` alerts are summarised as fleet
totals (alerts, hosts, open) and never affect a host score: IdP and DLP alerts are tied to a user or a data rule, not to the
health of the sensor, and on a busy tenant they outnumber endpoint detections by more than 40 to 1.

Pitfall: a single noisy host can hold most of the volume (one test host had 922 PUP detections in 30 days). The report shows
counts per host so that one host does not read as a fleet problem.

## Merging archived days

Each archived run covers one UTC day (`windowDays` 1, ending the day before `asOf`). The script merges them as follows.

- **Added across days:** `alerts`, `alertsOpen`, `alertsOpenHigh`, `leads` and `leadsOpen` in `falres_summary`, and the counts in
  `falres_alert_sev`, `falres_alert_status`, `falres_alert_tactics`, `falres_alert_names`, `falres_alert_hosts` (by device id) and
  `falres_alert_other`. Each detection is counted on the day it was created.
- **Busiest day:** `hostsWithAlerts`, `hostsOpenHigh`, `hostsOpen` and `alertScored`, because the same host can have detections on several days.
- **Lists are lower bounds:** the daily top lists (detection names, tactics, hosts) are cut per day, so a merged list can miss an item that was
  never in a day's top list.
- **Latest day:** every host, sensor, policy and score table.
- **Open means open when last seen:** a detection's status is its state at the end of the day it was created. One closed afterwards still counts
  as open, and the host scores include only the latest day's detections.
- **Gaps and repeats:** a day archived twice keeps the latest run; a missing day is listed as a gap and is not counted as zero.
- **Old archives:** runs from before the daily schedule have a 30-day window and overlap each other. They are used alone when no daily run
  exists, and are left out (with a note) when daily runs do.
