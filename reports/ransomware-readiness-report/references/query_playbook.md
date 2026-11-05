# Ransomware Readiness — Query Playbook

Proven on the Acme connector (30 Sep 2026). Tool names are `mcp__<Connector>__<tool>`
(e.g. `mcp__Acme__kql_search`); load them first if your client defers tools. Always `validate_kql`
before `kql_search`. Skip any pillar whose table is absent from `list_data_tables` and
record it as a visibility gap instead of guessing.

## Engine quirks learned the hard way

- **Resource tables** (sentinelOneAgent, msDefender*, office365User, sentinelOneThreat,
  sentinelOneApplication) are snapshots: no time filter, no dedup.
- **AzureSigninLogs** uses `TimeGenerated`.
- **WindowsAudit** time column is `timestamp`, NOT `TimeGenerated` (a `TimeGenerated`
  filter silently returns 0 rows). The default window is 24h — pass `rangeFrom` /
  `rangeTo` (epoch ms) for 30 days. Queries over 30 days take 20–90s; keep them narrow
  (filter EventID first) and use 7 days for 4624 logon analysis.
- **Always pass BOTH `rangeFrom` and `rangeTo`.** On some tenants (Globex) `rangeFrom` alone returns 0 rows.
- **`TimeGenerated` is not populated on every tenant** (Globex Office365 / WindowsAudit). Check the time span first with
  `summarize n=count(), first=min(timestamp), last=max(timestamp)` and filter on `timestamp` via rangeFrom/rangeTo.
  A table with rows but a tiny span (e.g. under one day) is a logging/retention finding.
- When Defender tables are absent, hardening and CVE exposure become visibility gaps; use
  sentinelOneAgent `appsVulnerabilityStatus` for patch status and FortiGate for perimeter (inbound
  WAN allow to 3389/445/22; SSL-VPN `ssl-login-fail` vs `ssl-new-con` in NetworkFortigateEvent).
- Multiple ScreenConnect instance IDs (the hex in the app name) = multiple remote-access owners; report it.
- EDR noise: group sentinelOneThreat by file-path prefix and publisher before judging (e.g. Dell
  SupportAssist remediation copies generated ~95% of Globex detections).
- `summarize by a, b` with **no aggregate fails** to parse — add `n=count()`.
- The tenant's table is `sentinelOneThreat` (lower-case s); the KB schema is under
  `SentinelOneThreat`. Nested fields need `tostring(threatInfo.x)`.
- `office365User.userRegistration.*` and `authMethodCount` may be entirely null
  (auth-method permission not granted). Check with `countif(isnotempty(...))`; if null,
  report "MFA registration not collected" as a visibility gap and use sign-in logs.
- `leftanti` joins across tables work (used for unprotected-device matching).

## Pillar 1 — Endpoint coverage (sentinelOneAgent, msDefenderMachine)

```
sentinelOneAgent | where isDecommissioned == false
| summarize total=count(), connected=countif(networkStatus=="connected"),
  outOfDate=countif(isUpToDate==false), detectMode=countif(mitigationMode=="detect"),
  suspDetect=countif(mitigationModeSuspicious=="detect"), infected=countif(infected==true),
  servers=countif(machineType=="server") by osType
```
Silent agents (networkStatus stays "connected" even when stale — trust lastActiveDate):
```
sentinelOneAgent | where isDecommissioned == false
| extend daysOff = datetime_diff('day', now(), todatetime(lastActiveDate))
| summarize stale7=countif(daysOff > 7), stale30=countif(daysOff > 30), maxD=max(daysOff) by machineType
```
Unprotected active devices (seen by Defender discovery, no Defender, no S1 agent):
```
msDefenderMachine | where isExcluded == false and onboardingStatus == "CanBeOnboarded"
  and healthStatus == "Active" and osPlatform startswith "Windows"
| extend host = tolower(tostring(split(computerDnsName, ".")[0]))
| join kind=leftanti (sentinelOneAgent | where isDecommissioned == false
  | extend host = tolower(computerName)) on host
| summarize n=count() by osPlatform
```
Caveat: hostname match — say so in methodology. Flag servers and EOL OS
(Windows 7, Server 2008 R2, 2012 R2, Windows 10) separately.

## Pillar 2 — Prevention & hardening (msDefenderSecureConfig, msDefenderSecureScore)

```
msDefenderSecureConfig | where isApplicable == true
| where configurationSubcategory == "Attack Surface Reduction" or configurationName contains "ransomware"
  or configurationName contains "LAPS" or configurationName contains "Credential Guard"
  or configurationName contains "SMB" or configurationName contains "Controlled Folder"
  or configurationName contains "tamper" or configurationName contains "WDigest"
  or configurationName contains "LSASS" or configurationName contains "PSExec"
| summarize total=count(), noncomp=countif(isCompliant==false) by configurationName, configurationImpact
| order by noncomp desc
```
`msDefenderSecureScore | project score, time` (device score, max 1000).
Compliant items (tamper protection, SMBv1 off, WDigest off) go into Strengths.

## Pillar 3 — Vulnerability exposure (msDefenderVulnerability)

```
msDefenderVulnerability | where VulnerabilitySeverityLevel in ("Critical","High")
  and ExploitabilityLevel in ("ExploitIsPublic","ExploitIsVerified","ExploitIsInKit")
| extend age = datetime_diff('day', now(), todatetime(FirstSeenTimestamp))
| extend isServer = OSPlatform startswith "WindowsServer"
| summarize devices=dcount(DeviceId), dev30=dcountif(DeviceId, age > 30),
  dev90=dcountif(DeviceId, age > 90), critDev=dcountif(DeviceId, VulnerabilitySeverityLevel=="Critical") by isServer
```
Top drivers: same filter, `summarize devices=dcount(DeviceId), firstSeen=min(FirstSeenTimestamp) by CveId, SoftwareName | top 20 by devices desc`.
Compare server count here vs sentinelOneAgent servers — a large gap is a server
vulnerability blind spot.

## Pillar 4 — Backup & recovery (sentinelOneApplication)

```
sentinelOneApplication | extend ln = tolower(name)
| where ln contains "veeam" or ln contains "backup" or ln contains "rubrik" or ln contains "cohesity"
  or ln contains "commvault" or ln contains "datto" or ln contains "acronis"
| summarize endpoints=dcount(agentComputerName) by name, version, agentDomain
```
Each backup product and version is compared with `assets/backup_advisories.json` by `scripts/resource_evidence.py`
(Veeam B&R up to 12.3.2.3617 is VULNERABLE to CVE-2025-48983/48984, fixed in 12.3.2.4165; Veeam KB4771, 14 Oct 2025).
Update the JSON, not the code, when advisories change. Not on the list means "CVE status not verified", never safe.
Backup servers joined to the production domain are a finding on their own.

## Pillar 5 — Detection & response (sentinelOneThreat)

```
sentinelOneThreat | extend created = todatetime(threatInfo.createdAt) | where created > ago(90d)
| summarize n=count(), unmitigated=countif(tostring(threatInfo.mitigationStatus)=="not_mitigated"),
  unresolved=countif(tostring(threatInfo.incidentStatus)!="resolved"),
  detectOnly=countif(tostring(agentDetectionInfo.agentMitigationMode)=="detect")
  by classification=tostring(threatInfo.classification), confidence=tostring(threatInfo.confidenceLevel)
```
Then project detail for `classification == "Ransomware"` and for suspicious not-mitigated
items. Look especially for discovery tools (Angry IP / Advanced IP Scanner, nmap) run
under admin accounts. Never name the user or host in the board report.

## Pillar 6 — Identity (AzureSigninLogs, office365User)

```
AzureSigninLogs | where TimeGenerated > ago(30d) and ResultType == "0"
| summarize total=count(), users=dcount(UserPrincipalName),
  sfa=countif(AuthenticationRequirement=="singleFactorAuthentication"),
  sfaUsers=dcountif(UserPrincipalName, AuthenticationRequirement=="singleFactorAuthentication"),
  legacyUsers=dcountif(UserPrincipalName, ClientAppUsed in ("IMAP","POP","SMTP","Exchange ActiveSync","Other clients","Authenticated SMTP","IMAP4","POP3")),
  riskyUsers=dcountif(UserPrincipalName, RiskLevelDuringSignIn in ("medium","high"))
```
Admin-tool single-factor sign-ins (the board-relevant number):
```
AzureSigninLogs | where TimeGenerated > ago(30d) and ResultType == "0"
  and AuthenticationRequirement=="singleFactorAuthentication"
  and AppDisplayName in ("Azure Portal","Microsoft Azure CLI","Microsoft 365 Admin portal","Graph Explorer","Microsoft Azure PowerShell")
| summarize n=count() by UserPrincipalName
```
Privileged holders: `office365User | where accountEnabled == true | extend r=tostring(roles) | summarize globalAdmins=countif(r contains "Global Administrator"), anyRole=countif(array_length(roles) > 0)`.

## Pillar 7 — Logging & forensics / pre-encryption signals (WindowsAudit, 30d via rangeFrom)

```
WindowsAudit | where EventID in (1102, 104, 4720, 4728, 4732, 4756, 7045, 4697, 4698, 4625)
| summarize n=count(), hosts=dcount(Hostname) by EventID
```
Log clearing detail: `where EventID in (1102,104) | summarize n=count(), days=dcount(bin(timestamp,1d)) by EventID, Hostname`.
Daily clearing on domain controllers = finding (T1070.001). Review 7045/4697 service
names for PsExec, remote-access or unknown binaries. Note: `ANONYMOUS LOGON` NTLM V1
events are normally benign — do not headline them.

## Pillar 8 — Remote-access tools & EOL (sentinelOneApplication, sentinelOneAgent)

RMM search terms: anydesk, teamviewer, screenconnect, connectwise, splashtop, rustdesk,
atera, logmein, pdq, manageengine. Count endpoints and servers. EOL from
`sentinelOneAgent | summarize n=count() by machineType, osName`.

## Scoring guidance

- Pillar **red / At Risk**: any Critical issue in the pillar, or a control absent fleet-wide.
- **amber / Needs Work**: High/Medium issues, or partial coverage.
- **green / Healthy**: no material issues.
- Overall rating: any red pillar in Backup, Endpoint Coverage or Prevention → "Elevated Risk";
  2+ red → "High Risk"; no red and ≤2 amber → "Moderate Risk"; otherwise "Resilient".

## Resource data is parsed locally (v1.1.0)

Pillars 1 to 5 and 8 no longer use KQL on resource tables. `scripts/resource_evidence.py` computes the same
measures from the downloaded dumps (see SKILL.md step 3). The KQL above remains the fallback when a dump cannot be
downloaded and is a cross-check for small tables. Only pillars 6 and 7 (sign-in and Windows audit events) always run as queries.

## Windows audit and sign-ins come from archives (v1.2.0)

Pillar 7 is read from the archive of `WindowsSrv_Activity_Report` by `scripts/windows_evidence.py`; the `WindowsAudit`
query above is not run. A tenant without that archive gets "not measurable, visibility gap" for the pillar. Pillar 6 reads
`Office365_Entra_Activity_Report` first. Verified on gramfg for 2026-11-04: 24 log-clear events (12 each of 1102 and 104,
none with a recorded actor), 7,232 audit-policy changes by the domain controllers' own accounts, 47 services and 4 tasks
installed (Sentinel and Windows components, nothing suspect), 57 failed logons and 19 probe-pattern failed-logon sources.
