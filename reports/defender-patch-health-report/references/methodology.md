# Methodology

## Sources

| Data | Source | Notes |
|---|---|---|
| Devices, enrolment, health | `msDefenderMachine` dump | Snapshot. Includes devices Defender only *discovered* (`CanBeOnboarded`, `InsufficientInfo`, `Unsupported`). |
| Vulnerabilities | `msDefenderVulnerability` dump | One row per CVE × device, PascalCase fields. Mostly enrolled devices, but Defender also scans some discovered devices (the report lists them separately). |
| Configuration | `msDefenderSecureConfig` dump | Only `isApplicable == true` counts. `scid-20000` (onboard devices) is excluded from failure lists. Only enrolled devices with 20 or more applicable checks are the baseline population. |
| Antivirus and full OS build | `msDefenderAvHealth` dump | `avMode` "0" = active. Up-to-date flags are the strings "True"/"False". `osVersion` carries the full build, for example 10.0.17763.9487. |
| Alerts | `MSDefender` stream, `MSDefenderAlert` | One `kql_search` over a 180-day window, reduced to the latest state of each alert id, with age buckets from the creation time. |
| Connector coverage | `list_integrations`, dump customers | Each `MSDefenderEndpoint` integration must match the customer of a downloaded dump. |

The dumps are processed in full. There are no row limits, so nothing is cut at a top-N.

## Patch gap

Defender reports, per device, the `RecommendedSecurityUpdate` that fixes each CVE. For the Windows OS itself these are monthly
cumulative updates named "`<Month> <Year> Security Updates`". The script collects the distinct months missing on each server (OS software
only: `windows_server_*`, `windows_10`, `windows_11`) and:

1. sorts them and walks back from the newest month while consecutive months are at most 2 apart (Defender lists only months that fix a CVE
   present on the device, so one month can be absent from an otherwise unbroken run);
2. takes the start of that run as the **first missing update**; the month before is **last patched**;
3. **months behind** = months from the first missing update to the latest Patch Tuesday on or before the snapshot date, inclusive;
4. older isolated months are kept as `outlierMonths` (usually a component such as an old .NET or servicing-stack item, not the OS
   cumulative update) and are not counted.

**Status.** *Behind*: at least one missing monthly update. *Current*: Defender holds scan results for the server and lists no missing monthly
update. *No data*: no scan results for the server, or no data from it for 30 days; its patch state is unknown and it is never counted as
current.

**Validation.** The report shows the full OS build of every server (from the antivirus dump). The script flags a Current server whose build is
older than a Behind server of the same OS, and a Current server whose build has no revision, so cannot be checked. A Current server last seen
more than 7 days ago is marked as such. For a server with a gap, the oldest exploitable finding is normally first seen on Patch Tuesday of the
first missing month. None of these checks needs a build-to-month table.

## Exploitable

`ExploitabilityLevel` in `ExploitIsVerified`, `ExploitIsInKit` or `ExploitIsPublic`. Defender carries no CVSS attack vector, so the report
cannot say "remotely exploitable"; it says "known exploit".

Age buckets use calendar days from `FirstSeenTimestamp` (when Defender first saw the finding on the device) to the snapshot date, not the CVE
publication date. A finding on the boundary of a bucket can land one bucket either side of a query that truncates to elapsed days.

## Servers outside Defender

`msDefenderMachine` rows not `Onboarded` whose OS is Windows Server (or the generic `Windows` / `Server` fingerprint), or whose host name matches
a server pattern (`srv`, `sql`, `dc<n>`, `hv<n>`, `app<n>`, `web<n>`, `mst<n>`) and a role pattern or Windows Server OS. GUID-named devices are
dropped. A row whose short host name matches an enrolled device is a **re-registered copy**: the machine came back under a new Defender id and
the enrolled record went silent. It is not counted as an extra server.

## Devices scanned but not enrolled

Any device in `msDefenderVulnerability` that is not an enrolled device. The report lists them with their enrolment status, findings and
maximum CVSS, because they are not in the server tables and can carry more critical findings than an enrolled server.

## Priority order

P1 patch actions are ranked by exploitable Critical/High findings, then months behind, then name. The role is shown but is not a ranking input.
A critical-role server (domain controller, backup, Hyper-V) that is not enrolled gets its own P1 action: active ones to onboard, and ones last
seen within 90 days that are no longer active to onboard or confirm retired.

## Roles

Inferred from host name only, with anchored patterns: `dc`/`ads<n>` at the end → domain controller, `backup`/`bkp` → backup server,
`hv`/`hyperv` → Hyper-V host, `sql` → SQL server, `print` → print server, `mst<n>`/`mgmt`/`jump` → management host, `srv` at the end → server.
Always presented as "likely role".

## Configuration baseline

A setting failing on every enrolled server that reports configuration is a **baseline gap** (policy never deployed), not drift. ASR rules are the
`Security controls` settings whose name starts with "Block " plus "Use advanced protection against ransomware", the one ASR rule without that prefix. The report lists ASR rules off everywhere, the highest-impact other settings failing
everywhere (with the total), and settings with impact 8 or more failing on some servers (with the total).

## Alerts

The same alert id is written to the stream every time its state changes, so counting rows overstates the number of alerts and leaves alerts that
were later resolved looking open. The query keeps the latest state of each id. The stream timestamp is the last emission, not the creation time,
so age is measured from `createdDateTime`; "created in the last 30 days" and "open now" are separate counts. Open alerts older than 30 days are
listed separately, because an alert nobody has handled for a month is a process finding in its own right. Only alerts emitted inside the query
window (180 days) are seen. The stream carries every Defender product (email, identity, cloud
apps, endpoint); this report's endpoint alerts are the `microsoftDefenderForEndpoint` source and the rest are shown as context.

## Known data-quality issues

- `SecurityUpdateAvailable` can be `true` on every finding. The script tests for this and, when true, says the flag was not relied on.
- Operating systems of discovered (unmanaged) devices are network fingerprints and are often wrong.
- Re-registered servers appear twice: an `Onboarded` record that went silent and a `CanBeOnboarded` record that is active.
- An `MSDefenderEndpoint` integration can be installed and `inUse` while delivering no dumps.
- `fullScanTime` is empty for a server that has never run a full scan; the report counts that as "never run a full scan".
- Unique-CVE counts here are exact. An earlier version used KQL `dcount`, which is approximate and read about 1% high on the large groups.
- Defender's antivirus table and its configuration check can disagree (for example signatures current in one, definitions failing in the other).
  The report shows both.
