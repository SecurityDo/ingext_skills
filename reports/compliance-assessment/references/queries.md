# Queries for compliance-assessment

All run against one tenant account through the connector's `kql_search` (or the named tool).
Set `rangeFrom` / `rangeTo` to the month in epoch milliseconds for the event queries.

| File | Query |
|---|---|
| `windows.json` | `WindowsAudit \| summarize events=count()` |

## Extra sources (only for tables that `list_data_tables` lists)

CloudTrail, Office 365 and Entra are not here: they are never queried. CloudTrail comes from the archive of the scheduled report `CloudTrail_Activity_Report` (`ct_archive.json`), and Office365, AzureSigninLogs, AzureAuditLogs, AADServicePrincipalSignInLogs and AADNonInteractiveUserSignInLogs from the archive of `Office365_Entra_Activity_Report` (`m365_archive.json`). See SKILL.md.

| File | Query |
|---|---|
| `src_<Table>.json` | `<Table> \| summarize events=count()` |

The class of a `src_` table comes from its name (first class with a matching word wins):

| Class | Name contains | Feeds |
|---|---|---|
| network | fortigate, meraki, netskope, zscaler, zpa, f5, palo, firewall, cisco | SC-7, AU-2 |
| endpoint | sentinelone, falcon, defender, cortex, crowdstrike | SI-3, AU-2 |
| cloud | cloudtrail, guardduty | AU-2 |
| identity | duo, gsuite, okta, googleworkspace | AU-2 |

Notes for these queries:
- **Large tables time out.** On a table with millions of events a single query that aggregates several
  nested fields was closed by the proxy. One narrow `where` per file worked (a few seconds each); a
  combined `summarize` with several `countif` over nested fields did not. Retry once, then leave the file
  out; the figure renders as not collected.
- The `total` in a result is the rows scanned and can differ from the `events` count; use `events`.
- A table that is listed but matches no class is not queried.

## History depth (optional, AU-4 / AU-11)

| File | Query |
|---|---|
| `history_<Table>.json` | `<Table> \| summarize oldest=min(TimeGenerated), newest=max(TimeGenerated)` (tables other than the archived ones) |

Use a `rangeFrom` a year or more before the period and `rangeTo` the end of the period. The result is the
history that exists, not a retention setting. CloudTrail, Office365 and the Entra tables are never searched, so no
history is measured for them; very large tables time out or return a null time column, leave them out. If the oldest record sits at the start of your query window it is reported
as "at least".

Resource tables are not queried. Each is a resource dump (`list_resource_dumps`, then
`get_resource_dump_url`, jsonl format) saved as:

| File | Resource | Customer (from `list_resource_dumps`) | Counted by the script |
|---|---|---|---|
| `users.jsonl.gz` | `office365User` | Office365ResourceWatch-<TENANT> | records; `accountEnabled == true` |
| `devices.jsonl.gz` | `office365Device` | Office365ResourceWatch-<TENANT> | records; `isManaged == true` |
| `ca_policies.jsonl.gz` | `office365ConditionalAccessPolicy` | Office365ResourceWatch-<TENANT> | records by `state` |
| `qualys.jsonl.gz` | `qualysHost` | Qualys-<TENANT> | records |
| `guardduty.jsonl.gz` | `GuarddutyFinding` | AmazonGuardDuty-<name> | latest record per finding id; open and high-severity (7.0 and above) counts |
| `gsuite_users.jsonl.gz` | `gsuiteUser` | GoogleWorkspaceResource-<name> | users, administrators, 2-Step Verification enrolment |
| `apps.jsonl.gz` | `office365Application` | Office365ResourceWatch-<name> | app registrations: client secret count, expired and long-lived secrets, apps requesting app-only permissions |
| `enterprise_apps.jsonl.gz` | `office365InstalledApp` | Office365ResourceWatch-<name> | enterprise applications (service principals): total, disabled, Microsoft-owned versus other tenants |
| `groups.jsonl.gz` | `office365Group` | Office365ResourceWatch-<name> | groups: security-enabled, public, role-assignable, empty |
| `gsuite_groups.jsonl.gz` | `gsuiteGroup` | GoogleWorkspaceResource-<name> | groups with external members or no owner |
| `mde_machine.jsonl.gz` | `msDefenderMachine` | MSDefenderEndpoint-default | device inventory: onboarded, can be onboarded, inactive sensors, exposure rating |
| `mde_avhealth.jsonl.gz` | `msDefenderAvHealth` | MSDefenderEndpoint-default | antivirus signature, engine and platform currency, last scan result |
| `mde_vulnerability.jsonl.gz` | `msDefenderVulnerability` | MSDefenderEndpoint-default | findings by severity, with known exploits, aged critical findings (the largest dump, tens to hundreds of MB compressed; streamed) |
| `mde_secureconfig.jsonl.gz` | `msDefenderSecureConfig` | MSDefenderEndpoint-default | applicable versus failing configuration checks, by category |
| `mde_recommendation.jsonl.gz` | `msDefenderRecommendation` | MSDefenderEndpoint-default | active recommendations, with public exploit |
| `mde_securescore.jsonl.gz` | `msDefenderSecureScore` | MSDefenderEndpoint-default | device secure score |
| `tenable_asset.jsonl.gz` | `tenableAsset` | Tenable | assets: scanned in the last 30 days, authenticated scans, agent present (deleted and terminated assets skipped) |
| `tenable_agent.jsonl.gz` | `tenableAgent` | Tenable | agents online versus offline |
| `tenable_plugin.jsonl.gz` | `tenablePlugin` | Tenable | plugin hit counts by risk factor (critical, high) |
| `sentinelone_agent.jsonl.gz` | `sentinelOneAgent` | SentinelOne | agents: inactive, out of date, infected, not in protect mode |
| `sentinelone_threat.jsonl.gz` | `sentinelOneThreat` | SentinelOne | threats: unresolved, not mitigated, rated malicious |
| `falcon_agent.jsonl.gz` | `falconAgent` | CrowdStrike Falcon | sensors: contained, reduced functionality, no prevention policy, not seen in 30 days |

`behavior.json`: `behavior_summary_search` with `limit: 0` and `facets: ["status", "classification",
"scoreLevel"]`. The facets count incident-flagged summaries, so `status` totals are the incident
count, which is smaller than `total` (all behavior summaries).

Notes:
- `list_data_tables` runs first (SKILL.md Step 1). If a table is absent (no `WindowsAudit`, no
  `qualysHost`), do not run its query: the control it feeds is not observed on that tenant.
- Control mapping used by the script: AU-2/AU-12 (event volumes), SI-4 (behavior summaries),
  AU-6 and IR-4/IR-5 (incident dispositions), AC-2 (users, directory audit), AC-7 (failed
  sign-ins), IA-2/IA-5 (Conditional Access), CM-8 (devices, Qualys hosts), RA-5 (Qualys).
  AU-4/AU-11 is partial when a history depth was measured and not observed otherwise (configured retention is never collected); SC-7 and SI-3 are not observed until a network or endpoint source is
  present, then partial; AC-1, IA-1 and IR-1 are always manual review. IA-2/IA-5 is partial from Conditional
  Access policies or from MFA registration in the user dump; AC-2 and AC-7 also use CloudTrail IAM changes
  and failed console logins when present.

## Retention probe (archived sources)

One `kql_search` per table and age (90, 180, 270, 365 days before the period end): `<Table> | take 1`, `rangeFrom`/`rangeTo` a 1 to 24 hour window ending that many days before the period end (window = 100000 / avg daily events x 24 h, clamped). Save as `retention_<Table>_<age>.json`. `take 1` is not cheap on a dense window, so keep it short. The result shows records exist at that depth, not the configured retention.
