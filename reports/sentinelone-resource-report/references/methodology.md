# Methodology

## Data

Three resource snapshots, each the full inventory at the snapshot hour (`dayIndex`, for example `20261103-04`):

- `sentinelOneAgent`: body under `@sentinelOneAgent`. Key fields: `uuid`, `computerName`, `machineType`, `osName`,
  `agentVersion`, `isActive`, `lastActiveDate`, `mitigationMode`, `scanFinishedAt`, `appsVulnerabilityStatus`,
  `infected`, `activeThreats`, `isDecommissioned`, `isUninstalled`.
- `sentinelOneApplication`: body under `@sentinelOneApplication`. Key fields: `agentUuid`, `name`, `publisher`,
  `version`, `riskLevel`, `installedAt`, `osType`.
- `sentinelOneThreat`: body under `@sentinelOneThreat`. Key fields: `threatInfo.*` (name, classification,
  confidence, analyst verdict, mitigation status, incident status, createdAt) and `agentRealtimeInfo.*` (endpoint
  name and UUID).

## Joins

Applications join to agents on `agentUuid`; threats on `agentRealtimeInfo.agentUuid`, falling back to
`agentDetectionInfo.agentUuid`. Records that point at an agent that is not in the agent snapshot are counted but not
attributed. They appear under "Data notes". A threat history that names removed endpoints is normal: the threat list
keeps history, the agent list does not.

## Endpoints in scope

Agents with `isDecommissioned` or `isUninstalled` set are left out. `isPendingUninstall` agents stay in and are
counted in Protection health.

## Reporting

`isActive` is SentinelOne's own flag. Silent endpoints are bucketed by days since `lastActiveDate`: under 1, 1 to 7,
8 to 30, over 30. More than 7 days silent counts as stale.

## Newest agent build

The highest `agentVersion` in the fleet, compared part by part as numbers. It is not the latest SentinelOne release,
so a fleet that never upgrades reports 100% on the newest build. Say so if the figure looks too good.

## Endpoint score

Points per endpoint, summed:

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

3 or more is **Needs action**, 1 or 2 is **Watch**, 0 is **Healthy**. The weights are in `analyse()` in the script.

Last full scan age is shown in Protection health but is not scored. In the first tenant tested, 52 of 58 endpoints
had a full scan older than 30 days, because SentinelOne runs a full disk scan at install and many fleets never
repeat it. Scoring it made nearly every endpoint "Watch".

## Open threat

A threat is open when `threatInfo.mitigationStatus` is not `mitigated`, or `threatInfo.incidentStatus` is not
`resolved`. A threat can be mitigated and still show an unresolved incident, so check both.

## Known data pitfalls

- **Threat names can be file hashes.** Some detections are named with a SHA-1 and an extension. The chart shortens
  long names; `threats.csv` keeps them whole.
- **`signed` is almost always false** in the application inventory (2,458 of 2,462 in the test tenant). It is not
  used in the report.
- **Duplicate host names.** Two agent records with the same `computerName` are usually a re-imaged or cloned
  machine. Both are listed; the report flags the name.
- **`windows_legacy` application records** come from old Windows installs and are counted in `facts.json`
  (`applications.windowsLegacy`) but not charted.
- **A tenant without SentinelOne** answers `resource type not found` to `list_resource_dumps` rather than returning
  an empty list.
- **Application counts are installs, not applications.** One application on 57 endpoints is 57 installs and one
  distinct application. The report shows both.
