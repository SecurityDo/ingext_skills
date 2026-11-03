# Methodology

## Data

The scheduled report `SentinelOne_Resource_Report` queries the three SentinelOne resource tables (`sentinelOneAgent`,
`sentinelOneApplication`, `sentinelOneThreat`) once a day and archives the result. Each archived day is a **snapshot** of
the console when the run took it; the tables have no time column. The script reads the latest completed day and lists
the other days in a change table. It never adds days together.

Tables used: `s1res_summary` (one row of totals, `asOf` is the end of the run window), `s1res_endpoints` (one row per
endpoint, with the score, status and reasons the report computed), `s1res_agent_versions`, `s1res_apps_risk`,
`s1res_apps_top` (the 25 applications on the most endpoints), `s1res_threats_class`, `s1res_threats_daily`,
`s1res_threats_open`, and `sources` (which query ran and whether it succeeded). See the header of
`Scripts/fplProcessors/code/SentinelOne_Resource_Report.js`.

## Joins

The join of applications and threats to agents (on `agentUuid`) is done by the scheduled report, in KQL, and arrives as
columns of `s1res_endpoints` (`riskyApps`, `openThreats`, `activeThreats`). The skill does no join of its own. A threat
whose endpoint is no longer in the agent list is counted in the totals but cannot be attributed to an endpoint.

## Endpoints in scope

Agents that are decommissioned or uninstalled are left out of `endpoints` (they are counted separately in the summary).

## Reporting

`isActive` is SentinelOne's own flag. Silent endpoints are bucketed by `daysSinceActive`: under 1, 1 to 7, 8 to 30,
over 30. More than 7 days silent counts as stale. When the archive has no usable `daysSinceActive` (a tenant whose
`lastActiveDate` cannot be parsed returns null), the endpoint is shown as "not reporting, last active unknown" and is not
counted as stale; the report says so under Data notes.

## Newest agent build

The highest `agentVersion` in the fleet, compared part by part as numbers (the row flagged `isNewest` in
`s1res_agent_versions`). It is not the latest SentinelOne release, so a fleet that never upgrades reports 100% on the
newest build. Say so if the figure looks too good.

## Endpoint score

Computed by the scheduled report and read as is. Points per endpoint, summed:

| Condition | Points |
|---|---|
| Infected, or active threats on the agent | 3 |
| One or more open threats | 3 |
| Not reporting for more than 7 days | 3 |
| Not reporting, 7 days or less | 2 |
| Mitigation mode is not `protect` | 2 |
| Medium, high or critical risk application installed | 1 |
| `appsVulnerabilityStatus` is `patch_required` | 1 |
| Agent older than the newest build | 1 |
| Reboot required | 1 |

3 or more is **Needs action**, 1 or 2 is **Watch**, 0 is **Healthy**. The weights live in the scheduled report. Scan age
is not scored: many fleets never repeat the full disk scan SentinelOne runs at install, and scoring it made nearly every
endpoint "Watch". Because the report works in whole calendar days to the end of the run window, an endpoint that went
quiet late on the 7th day can score Watch in the archive.

## Open threat

A threat is open when its mitigation status is not `mitigated`, or its incident status is not `resolved`. A threat can be
mitigated and still show an unresolved incident, so both are checked. `s1res_threats_open` lists each open threat;
`s1res_threats_class` gives the history by classification and status; `s1res_threats_daily` gives threats per day, which
the report rolls up to weeks.

## What the archive does not carry

Scan status and scan age, the confidence and verdict mix of the full threat history, application publishers beyond the
top 25, a per-application endpoint list, versions per application, last logged-in user, site and domain, duplicate-name
detail beyond the endpoint names, the reboot-required flag, and pending-uninstall agents. These were in the earlier
dump-based version of this skill. Extending `SentinelOne_Resource_Report` is the way to bring one back.

## Known data pitfalls

- **Threat names can be file hashes.** Some detections are named with a SHA-1 and an extension. The page shortens long
  names; `open_threats.csv` keeps them whole.
- **Application counts are installs, not applications.** One application on 57 endpoints is 57 installs and one distinct
  application. The report shows both. The distinct count is by name and publisher.
- **Snapshots, not events.** A later archived day replaces an earlier one. Compare days to see change; never sum them.
- **A tenant without SentinelOne** has no archive entries or a `sources` table that says "not available". Treat that as
  "no SentinelOne import", not as an error.
