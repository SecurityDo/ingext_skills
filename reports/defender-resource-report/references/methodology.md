# Methodology

## Data

The report reads the archive of the scheduled FPL report `Defender_Resource_Report`, one UTC day per archived run, and uses the latest
completed day. Each day carries the tables below, all computed in the tenant from the Defender resource tables (`msDefenderMachine`,
`msDefenderAvHealth`, `msDefenderVulnerability`, `msDefenderSecureConfig`, `msDefenderRecommendation`, `msDefenderSecureScore`; snapshots
of the console, no history) and the `MSDefenderAlert` and `MSDefenderIncident` streams (the 30 days before the run). `asOf` is the end of
the run window. Days are never added together.

| Table | Holds |
|---|---|
| `mderes_summary` | one row: devices, onboarding counts, last seen, exposure and risk, antivirus, vulnerability, needs action / watch / healthy, Secure Score, recommendations, alert and incident totals |
| `mderes_hosts` | onboarded devices with a score above 0, highest first, at most 500: name, id, OS, last seen days, health, exposure, risk, antivirus mode, CVE counts, open alerts, score, status, reasons |
| `mderes_onboarding`, `mderes_seen`, `mderes_os`, `mderes_groups`, `mderes_av` | enrolment by status and OS, last seen buckets, OS and version, device groups, antivirus mode and up-to-date flags |
| `mderes_vuln_sev`, `mderes_vuln_cves`, `mderes_vuln_software` | severity by exploit level, the top 10 exploitable CVEs by devices, the 10 software products with the most critical CVEs |
| `mderes_config`, `mderes_config_top`, `mderes_recs` | secure configuration by category, the 10 most common failing settings, the top 10 recommendations by exposed devices |
| `mderes_alerts`, `mderes_alert_titles`, `mderes_incidents`, `mderes_alert_hosts` | alert cross-tab (product, severity, status, category), the top endpoint alert titles, incidents by severity and status, devices with open alerts |
| `sources` | one row per query with `ok` or `not available` and the error |

Fleet figures come from the summary and the fleet tables, which cover every onboarded device. The device table lists only scored devices,
so a healthy device is counted but not named, and a long list is cut at 500 (the report says so). Installed software, per-CVE device
lists, last logged-in user and tags are not in the archive and are not shown.

## Last seen

Days from the device's `lastSeen` to `asOf`, the end of the run window (whole calendar days). Buckets: under 1, 1 to 7, 8 to 30, 31 to 90,
over 90 days. More than 7 days is stale; more than 30 days is silent. Defender marks a device `Inactive` after a short silence, so the
sensor-inactive count can be higher than the stale count.

## Device score

Points per onboarded device, summed:

| Condition | Points |
|---|---|
| Not seen for more than 30 days | 3 |
| Sensor inactive, or not seen for 8 to 30 days | 2 |
| Risk score High / Medium / Low | 3 / 2 / 1 |
| Exposure level High | 1 |
| Antivirus mode Disabled or EDR blocked | 2 |
| Antivirus signatures not up to date | 2 |
| Antivirus engine or platform not up to date | 1 |
| 10 or more distinct High or Critical CVEs with a verified exploit or exploit kit | 2 |
| 100 or more distinct critical CVEs | 1 |
| Open alert of high severity | 3 |
| Other open alert (new or in progress) above informational severity | 1 |

3 or more is **Needs action**, 1 or 2 is **Watch**, 0 is **Healthy**. The weights are in the FPL report, so the skill and the archive agree.
Informational alerts are deliberately not scored: a single noisy informational alert (for example a custom network indicator) can
otherwise put hundreds of devices on the list. The vulnerability points are capped for the same reason: on a typical fleet most devices
carry some exploitable CVE.

## Vulnerabilities

Counted per device and distinct CVE. Exploitable means the exploitability level is `ExploitIsVerified` or `ExploitIsInKit` and the severity
is High or Critical. The severity table shows every severity and exploit level; the CVE table shows the ten that reach the most devices.

## Secure configuration

Only checks where `isApplicable` is true count. Compliance is compliant checks divided by applicable checks, by category. The failing
settings are ranked by devices failing multiplied by the setting's impact.

## Alerts and incidents

Alert rows are snapshots, so each alert is reduced to its latest state. Open means status `new` or `inProgress`. The cross-tab keeps all
products (endpoint, Office 365, data loss prevention); only Defender for Endpoint alerts map to devices. Incidents are listed by severity and
status.
