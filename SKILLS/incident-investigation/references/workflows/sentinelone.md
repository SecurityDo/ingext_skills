# SentinelOne workflow (incident-investigation, step 3)

Run this when the ticket is a **SentinelOne** alert — its `behaviorRules` start with
`SentinelOne:` (see the routing table in SKILL.md step 3). It replaces the generic
workflow for this type. Seven parts, in order; each result goes into the step-5 closure
with the index or tool it came from.

Sources used: the `investigate_sentinelone_alert` tool, the raw **SentinelOne** index
through `lake_search`, and the `sentinelOneAgent` / `sentinelOneApplication` inventories.
Everything runs on `ACCOUNT` only.

**Search the raw index with `lake_search`, not KQL.** The SentinelOne documents are
nested (`@sentinelOneThreat.threatInfo.*`, `@sentinelOneActivity.data.*`); a KQL query on
the `SentinelOne` table that names `externalId`, `threatId` or `sha1` returns 0 rows
without an error. Search on **stable ids** — a quoted SHA-1, agent uuid, agent id or
`externalId` — and read the rest from facets. A bare product or file name inside a path
can return 0 across hundreds of thousands of rows.

## S1 — Pull every alert whole

The summary lists what fired; the alert investigation says what it was. For each
distinct `externalId` on the ticket (the summary's `attributeSummaries`), call:

```json
investigate_sentinelone_alert {
  "alertId": "<externalId>",
  "options": { "activityWindowMinutes": 180, "maxActivities": 300,
               "includeRelatedAlerts": true }
}
```

- One call returns the alert, the correlated threats, the agent's activities in the
  window and the **live endpoint record**. Alerts on the same agent share activities and
  the endpoint: one call with `includeRelatedAlerts` usually covers the host; call again
  only for an alert whose threat you still need.
- `externalId` is the numeric id; for SentinelOne EDR alerts it equals the threat id.
  The alert's own UUID also works. The result's `alertMatchedField` says which matched.
- Read `associations.confidence`: `high` is an id match, `medium` a shared storyline,
  `low` only the same host in the window. `none` is an answer, not an error.

## S2 — Was it running, or was it found on disk?

These fields decide most SentinelOne tickets. Read them off each threat (S1 result, or
`@sentinelOneThreat.threatInfo.*` in the index):

| Field | Reading |
|---|---|
| `initiatedBy` | `full_disk_scan` — a file at rest, found by a scan. `agent_policy` — on-execution or on-write, in real time. `on_demand_scan` — someone asked for it. |
| `engines` / `detectionType` | `User-Defined Blocklist`, `Reputation`, `SentinelOne Cloud` are **static hash hits** (`static`). `DBT - Executables` (Behavioral AI) is **dynamic**: something ran and behaved. |
| `originatorProcess`, `processUser`, `maliciousProcessArguments` | Who launched it and how. `explorer.exe` run by a named user is a person double-clicking; `services.exe` as SYSTEM is a service. Empty on scan hits. |
| `mitigationStatus` next to the agent's `mitigationMode` | "Not mitigated" under `detect` mode is the policy working as configured, not a failed response. |
| `analystVerdict`, `mitigationStatus: marked_as_benign` | An earlier human decision on the same hash. |
| `cloudFilesHashVerdict`, `fileVerificationType`, `publisherName` | SentinelOne's cloud rating of the hash; whether the file is signed, and by whom. |

A ticket where every threat is `full_disk_scan` + a static engine is **a file at rest**.
It can still be real malware — but the question becomes "did it ever run?", not "is it
running?", and containment is quarantine, not isolation.

## S3 — Place the agent in time and ownership

From the live endpoint record (S1):

- **`registeredAt` against the detection time.** Minutes apart means this is the agent's
  **first full disk scan** after a new install or a site move (activity types `17`
  "joined group", `71` "system initiated a full disk scan", `90`/`92` scan start/end).
  Everything the scan finds predates the agent, and nothing before `registeredAt` is
  visible.
- **`lastLoggedInUserName` against the user folder in the file path.** A file under
  `Users\<a>\` on a laptop whose last user is `<b>` means the device changed hands; the
  file belongs to the previous user.
- **`siteName` / `groupName` and `mitigationMode`** for the tuning section.
- **The live record wins over the inventory.** `sentinelOneAgent` is a snapshot and lags
  new installs: a host registered today returns 0 rows there while the live record shows
  an active agent. Run `ingext-get-profile` for the device as usual, and when the
  snapshot misses, cite its readability probe and use the live record — never write
  "unmanaged" from an empty snapshot.

## S4 — How common is the hash here, and where did it start?

One search per distinct SHA-1 on the ticket (or several OR'ed when you only need the
spread), over the full window, oldest first:

```json
lake_search {
  "index": "SentinelOne",
  "searchStr": "\"<sha1>\"",
  "mustFilters": [{ "field": "@eventType", "terms": ["SentinelOneThreat"] }],
  "rangeFrom": <ms − 30 days>, "rangeTo": <ms>,
  "sortOrder": "asc", "limit": 1,
  "facets": ["@sentinelOneThreat.agentRealtimeInfo.agentComputerName",
             "@sentinelOneThreat.threatInfo.threatName",
             "@sentinelOneThreat.threatInfo.initiatedBy",
             "@sentinelOneThreat.threatInfo.engines",
             "@sentinelOneThreat.threatInfo.analystVerdict",
             "@sentinelOneThreat.threatInfo.mitigationStatus",
             "@sentinelOneThreat.agentRealtimeInfo.siteName"],
  "facetSize": 50
}
```

Read four things:

- **Spread** — the computer-name facet. Many hosts first seen the same day as a wave of
  new agents is a rollout's first scans surfacing old files, not an outbreak.
- **Origin** — the one document returned is the **oldest** threat. Its `filePath` often
  names the delivery route: `...\Microsoft\Olk\Attachments\...` or
  `...\Content.Outlook\...` is an email attachment, `Downloads` a browser download,
  a removable-drive letter a USB stick.
- **Prior execution anywhere** — rerun with a second filter
  `{ "field": "@sentinelOneThreat.threatInfo.initiatedBy", "terms": ["agent_policy"] }`
  and `limit: 2`. Any hit with a named `processUser` is someone running the file on
  another host; it is a side finding (S7) and a strong hint for this host.
- **Earlier verdicts** — an `analystVerdict: false_positive` on a hash that now fires
  through `User-Defined Blocklist` means the hash was blocklisted after being judged
  benign. That is a tuning finding, not an incident.

When the detection is a **named application** rather than a dropped file (a remote-access
tool, an updater), also count its installs in `sentinelOneApplication` by name, version
and publisher — hundreds of hosts is deployed software, one is the finding. Probe the
table first: on some tenants it returns only a `timestamp` column, which is a gap.

## S5 — Prove what did not run, with a control

- **On this agent:** search the agent uuid and agent id, facet on `@eventType`,
  `threatInfo.initiatedBy`, `threatInfo.engines`, `threatInfo.threatName` and
  `@sentinelOneActivity.activityType`:

  ```json
  lake_search {
    "index": "SentinelOne",
    "searchStr": "\"<agentUuid>\" OR \"<agentId>\"",
    "rangeFrom": <ms − 30 days>, "rangeTo": <ms>, "limit": 1,
    "facets": ["@eventType", "@sentinelOneThreat.threatInfo.initiatedBy",
               "@sentinelOneThreat.threatInfo.engines",
               "@sentinelOneThreat.threatInfo.threatName",
               "@sentinelOneActivity.activityType"],
    "facetSize": 50
  }
  ```

  `agent_policy` = 0 is the negative. **Its control** is the S4 `agent_policy` search on
  the same hashes elsewhere on the tenant returning hits — it shows the query can find a
  runtime detection when there is one. If S4 found none either, the control is any
  `agent_policy` threat on the tenant.
- **After the event:** the last detection time and the scan-completed activity (`92`),
  against the agent's `lastActiveDate`. Nothing new since the scan finished is a
  negative only while the agent was active.
- **Before `registeredAt`:** always a gap, stated as one. Read the paths for what they
  imply: `AppData\Local\Temp\<guid>_<archive>.zip.<n>\<file>.exe` is the folder Windows
  creates when someone opens an executable from inside a zip in Explorer — each distinct
  `<guid>` is one opening. That is evidence of interaction, not of execution, and it
  makes prior execution likely rather than ruled out.
- **Other sources on the host:** Defender, Windows audit or firewall data mapped to the
  host, if the tenant has them; otherwise "not checked — no <source> for this host".

## S6 — Reconcile the counts

Three numbers should agree and often do not: SentinelOne **threats** on the agent,
SentinelOne **alerts** in the index (`@eventType: SentinelOneAlert`), and the rules on the
Fluency **summary**. A threat with no alert never reaches a ticket (seen: 11 threats,
10 alerts — the missing one was the blocklisted-false-positive hash); an alert with no
summary is a relay gap. Name each mismatch in the closure as a collection gap.

## S7 — Read the score, route the tuning, keep side findings apart

- **Relayed rule names embed the file name.** `SentinelOne:EDR_<threat name>_detected_as_<class>`
  means a browser-renamed duplicate — `report (1).zip`, `report (2).zip` — is a **new
  rule** and a new `ML_NEW_ALERT` first-seen hit each time. Decompose the score (step 1)
  before reading it as severity: on one ticket four such duplicates were 17,600 of an
  18,800 score.
- **The detection logic lives in the SentinelOne console.** `eventwatch_rule_list` has
  nothing under these names; Fluency only relays them. Blocklist entries, exclusions and
  detect/protect mode are vendor-side levers. The Fluency-side lever is how SentinelOne
  alerts are grouped — by hash rather than by alert name stops duplicates inflating
  the score.
- **Side findings** from S4 — another host that ran the file, the delivery host, a hash
  blocklisted after an analyst cleared it — go in the closure as separate items with a
  recommendation to open their own tickets, and do not change this ticket's verdict.

## Verdict shapes seen so far

| What S2–S5 show | Verdict |
|---|---|
| Static hits from a first scan, malicious hash, no runtime detection, no sign of opening | Escalate for remediation (quarantine); no isolation |
| Same, plus Temp extraction folders or a runtime hit elsewhere by the same user | Escalate for remediation and a pre-install execution check on the host and the user's account |
| `agent_policy` + dynamic engine with a user process, not mitigated | Escalate for containment — this is the live case |
| Blocklist hit on a hash an analyst marked false positive | Benign for the host; tuning to the SentinelOne console |
