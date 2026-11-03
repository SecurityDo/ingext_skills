# Methodology

## Data

One resource snapshot, the full host inventory at the snapshot hour (`dayIndex`, for example `20261103-15`). The body is under
`@falconAgent`. Key fields: `device_id`, `hostname`, `platform_name`, `product_type_desc`, `os_product_name`, `agent_version`,
`last_seen`, `first_seen`, `last_reboot`, `status`, `provision_status`, `reduced_functionality_mode`, `safe_mode`, `rtr_state`,
`criticality`, `machine_domain`, `site_name`, `last_login_user`, `device_policies` (an object keyed by policy type, each with
`policy_id`, `applied`, `assigned_date`, `applied_date`; `sensor_update` adds `uninstall_protection`).

## Hosts

One row per `device_id`. If a repeated id appears, the newest record wins and the count is shown under Data notes.

## Last check-in

Days from `last_seen` to the time the report is built. Buckets: under 1, 1 to 7, 8 to 30, 31 to 90, over 90 days. More than 7
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
hosts with the policy assigned, the hosts without it, and the hosts where it is assigned but `applied` is false. Hosts per
prevention policy id is listed on the interactive Policies tab. Policy ids are not names; the resource does not carry names.

## Known data pitfalls

- **`provision_status` can be empty** (33 of 5,307 hosts in the first tenant tested). An empty value is shown as unknown and is
  not scored; only `NotProvisioned` is.
- **Uninstall protection** is `IGNORE` on Linux, where it does not apply. It is only scored on Windows and Mac.
- **Duplicate host names.** Two hosts with the same `hostname` are usually a re-imaged or cloned machine. Both are listed and the
  name is flagged.
- **`criticality` is usually `unassigned`.** Tenants that rate their assets use `critical` and `high`.
- **A tenant without Falcon** answers `resource type not found` to `list_resource_dumps` rather than returning an empty list.
- **`last_seen` is the sensor check-in**, not a user login. `last_login_user` is the last interactive login and can be old on
  servers.

## Detections (FalconAlert)

FalconAlert is an event stream. The same alert is emitted again each time its status changes, so the report filters on
`created_timestamp` (the alert's creation time) rather than the emit time, and aggregates per host, severity, status and tactic.
Alerts join to hosts on `agent_id` = `device_id`; rows whose id is not in the host snapshot are counted under Data notes.

Counted per host: product `epp` (endpoint detections) and `automated-lead` (leads). Open means status `new`, `in_progress` or
`reopened`. Scoring: an open High or Critical detection adds 3 (Needs action on its own); any other open detection or open lead adds 1.
Closed alerts do not score. Product `idp`, `data-protection`, `fcs`, `ngsiem` and `thirdparty` alerts are summarised as fleet
totals (alerts, hosts, open) and never affect a host score: IdP and DLP alerts are tied to a user or a data rule, not to the
health of the sensor, and on a busy tenant they outnumber endpoint detections by more than 40 to 1.

Pitfall: a single noisy host can hold most of the volume (one test host had 922 PUP detections in 30 days). The report shows
counts per host so that one host does not read as a fleet problem.
