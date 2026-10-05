# SentinelOne workflow (incident-investigation, step 3)

Run this when the ticket is a **SentinelOne** alert — its `behaviorRules` start with
`SentinelOne:` (see the routing table in SKILL.md step 3). It replaces the generic
workflow for this type. Seven parts, usually run in this order; each result goes into the
step-5 closure with the index or tool it came from.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled past tickets of this type, in a sensible order. Add checks or reorder them
> when the evidence points elsewhere. Skip one only when it cannot apply to this ticket
> (say which and why in the closure); a check that applies runs its bundled queries
> before any of your own (non-negotiable 4). Accuracy comes before speed and cost.

Sources used: the `investigate_sentinelone_alert` tool, the raw **SentinelOne** index
through `lake_search`, and the `sentinelOneAgent` / `sentinelOneApplication` inventories.
Everything runs on `ACCOUNT` only.

**Search the raw index with `lake_search`, not KQL.** The SentinelOne documents are
nested (`@sentinelOneThreat.threatInfo.*`, `@sentinelOneActivity.data.*`); a KQL query on
the `SentinelOne` table that names `externalId`, `threatId` or `sha1` returns 0 rows
without an error. Search on **stable ids** — a quoted SHA-1, agent uuid, agent id or
`externalId` — and read the rest from facets. A bare product or file name inside a path
can return 0 across hundreds of thousands of rows.

**A rule or alert name is not a stable id either.** A free-text search for a word in a STAR
rule's name has returned 0 across the whole index while that rule's alert was in it. Count
alerts by name with a filter on the exact value, never a free-text search:

```json
lake_search {
  "index": "SentinelOne", "searchStr": "",
  "mustFilters": [{ "field": "@sentinelOneAlert.name", "terms": ["<exact alert name>"] }],
  "rangeFrom": <ms − 30 days>, "rangeTo": <ms>, "sortOrder": "asc", "limit": 1,
  "facets": ["@sentinelOneAlert.asset.name", "@sentinelOneAlert.status",
             "@sentinelOneAlert.analystVerdict"],
  "facetSize": 50
}
```

**Leave `searchStr` empty.** An empty string matches everything, the same as `"*"` or
leaving the field out. `searchStr` and the filters are ANDed, so adding the name, or a word
from it, as a free-text term brings the false zero back even with the exact-name filter in
place. The filter alone does the selecting.

The activity side carries the same name in `@sentinelOneActivity.data.rulename`. The control
is the ticket's own alert: a census that does not find it is broken, not empty.

**The index can hold two feeds. Census both, and check how far back each one reaches.**

| `@eventType` | Comes from | Carries | Fields |
|---|---|---|---|
| `SentinelOneThreat`, `SentinelOneActivity`, `SentinelOneAlert` | the SentinelOneEvents integration | whole threat records (`threatInfo`, `agentDetectionInfo`), activities, Unified Alerts | `@sentinelOneThreat.*`, `@sentinelOneActivity.data.*`, `@sentinelOneAlert.*` |
| `SentinelOneAPI` | the older API connector | **activities only**, no threat record | `@s1.activityType`, `@s1.computerName`, `@s1.fileContentHash`, `@s1.fileDisplayName`, `@s1.threatId` |

- **A site moving from the older connector to SentinelOneEvents has a short new feed.** The
  new feed starts at whatever the integration backfilled, often a day or less. A 30-day
  census on `SentinelOneThreat` alone then reports "the only threats on the tenant are this
  ticket's" while other hosts had detections the week before. Before trusting a tenant-wide
  zero from one feed, read its oldest document (`sortOrder: asc`, `limit: 1`).
- **The older feed has no `threatInfo`.** Facets on `@s1.threatInfo.*` come back empty
  because the field does not exist, not because nothing matched. Count detections there
  by activity type: `4003` suspicious detected, `19` malicious detected, `2001` killed,
  `2004` quarantined, `4008` mitigation status changed, `2037` cloud changed the confidence
  level, `2` added to the blocklist.
- **A tenant-wide negative cites both feeds**, or names the one it could not use and says
  how far back the other reaches.

**Do not call `list_integrations` to find out whether SentinelOneEvents is installed.** Its
output can carry connector credentials, and the investigation trace stores whatever a tool
returns. `investigate_sentinelone_alert` already answers the question: it fails with "no
SentinelOneEvents integration is configured" when the integration is missing.

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
- **If the tool fails** ("no SentinelOneEvents integration", or "alert not found" for the
  ticket's threat id), pull each threat from the
  index instead: `lake_search` on the quoted threat id, with `@eventType` set to
  `SentinelOneThreat`. When that returns nothing too, the site has only the older feed: read
  the threat's activities from `@s1.*` (by `@s1.threatId`), and record the live endpoint
  record and the threat's `threatInfo` as gaps. Say in the closure which path you used.
- **A STAR (custom rule) alert has no threat record.** Its `externalId` is STAR's own id,
  the tool skips the threat lookup, and the alert record's `process` is null. What the rule
  matched is in the alert's `3608` activity in the index. Run `lake_search` on the quoted
  `externalId` and read `@sentinelOneActivity.data.*`:
  - `dveventtype`: `FILESCAN` means a file at rest found by a scan. A process or
    registry event type means something live.
  - `tgtfilepath`, `tgtfilehashsha1` and `tgtfilehashsha256`: the file.
  - `sourceprocess*` and `sourceparentprocess*`: the actor, which is empty on a scan.
  - `ruleid`, `rulename`, `ruledescription` and `rulescopelevel`: the rule.

  S2 to S5 then work on that file. "Alert created for  from Custom Rule" (an empty name)
  in the activity text is the sign of a file-scan match.

### A network STAR alert: find what made the connection, then what followed

When the `3608` activity's `dveventtype` is `DNS`, `IP` or another network event, there is
no file to follow through S2 to S5. The rule matched one lookup or one connection. The
destination is in `dnsrequest` / `dnsresponse` (or `dstip` / `dstport`), and the actor is in
`sourceprocess*`. Two questions decide the ticket, and the SentinelOne index answers neither:
what made the request, and what happened after it.

- **A browser's network-service process stands in for every tab.** In Chromium browsers
  (Edge, Chrome), every page's DNS lookups and connections are made by one utility process
  (`--type=utility --utility-sub-type=network.mojom.NetworkService`). That process name
  cannot rule out a page, an ad or an extension, and it cannot prove the lookup was the
  browser's own housekeeping. Never write "not a tab" or "a routine lookup by the
  browser itself" from it.
- **Answer both with the firewall, following `references/fortigate.md`.** On an account
  with FortiGate tables, run its three bundled queries in order, one at a time:
  `fw_trigger_hosts.kql` (F1, the sites the host reached in the minute around the lookup's
  raw `eventtime`, from `agentipv4`), `fw_aftermath_sessions.kql` (F2, every flow to the
  addresses in `dnsresponse` for the next hour, one row per flow) and
  `fw_host_sessions_control.kql` (F3, the host's largest flows in the same window, the
  control). A domain fetched within the same second as a burst of a page's ad, analytics
  and CDN hosts is a script embedded in a page the user opened. A domain reached on its
  own, at a steady interval, or by a non-browser process is a different case.
- **`hostname` is on `NetworkFortigateEvent` only.** `NetworkFortigateTraffic` has no such
  column, so projecting it there returns null on every row. That is not "no web-filter
  visibility". Names come from the Event table and sessions from the Traffic table.
- **Count flows, not rows or session ids, and never sum the byte columns.** Several
  FortiGates can log the same flow under different session ids, and `sentbyte` /
  `rcvdbyte` are cumulative. The bundled queries handle both; a hand-written one that
  does not is wrong by a multiple.
- **A recurring lookup gets more than one anchor.** When the same domain alerts on several
  days, run F1 on the first occurrence, the ticket's own and one in between, and say how
  many of the total were checked.
- **A shared CDN address is not an indicator.** Cloudflare-, Akamai- or CDN77-fronted
  domains share addresses with unrelated sites, so attribute a flow to the domain only
  near the lookup.
- **Keep the window narrow.** Firewall tables are among the largest on an account: a
  30-day domain search can fail outright (the lake search pool runs out of capacity) and
  return no rows. That is a gap, not a negative. The bundled queries use ±1 minute and
  +60 minutes.
- **HTTPS logs name hosts, not pages.** A web filter that sees only the TLS server name
  logs `https://<host>/`, so the page's own domain is often not separable from its
  third-party scripts, and a domain can be absent from the web filter by name while its
  flows are in Traffic. Say so in the closure as a gap.

If the account has no firewall, proxy or DNS logs for the host, the trigger and what
followed are gaps. Write them as gaps, and do not fill them with what the process name
suggests.

- **"Alert not found" is common, not an error in the ticket.** The tool reads
  SentinelOne's Unified Alerts, and a site can have far fewer of those than threats: one
  account held 40 threat records and 5 alert records in 30 days. The threat record is still
  in the index. Read it there (`lake_search` on the quoted threat id, `@eventType`
  `SentinelOneThreat`, newest first, since each update is a new copy) and carry on with S2.
  The live endpoint record is then the threat's own `agentRealtimeInfo`, as of the
  threat's `updatedAt`.

## S2 — Was it running, or was it found on disk?

These fields decide most SentinelOne tickets. Read them off each threat (S1 result, or
`@sentinelOneThreat.threatInfo.*` in the index):

| Field | Reading |
|---|---|
| `initiatedBy` | `full_disk_scan` — a file at rest, found by a scan. `agent_policy` — on-execution or on-write, in real time. `on_demand_scan` — someone asked for it. |
| `engines` / `detectionEngines` | `User-Defined Blocklist`, `Reputation`, `SentinelOne Cloud` are **static hash hits**. `On-Write Static AI` / `On-Write DFI` (`detectionEngines.key: pre_execution_*`) is a **static model verdict on the file** — static whatever `detectionType` says (see below). `DBT - Executables` (Behavioral AI) is **dynamic**: something ran and behaved. |
| `originatorProcess`, `processUser`, `maliciousProcessArguments` | Who launched it and how. `explorer.exe` run by a named user is a person double-clicking; `services.exe` as SYSTEM is a service. Empty on scan hits. |
| `mitigationStatus` next to `agentDetectionInfo.agentMitigationMode` | "Not mitigated" under `detect` mode is the policy working as configured, not a failed response. Read the mode on the **threat's own detection record**, never the live endpoint record (see below). |
| `analystVerdict`, `mitigationStatus: marked_as_benign` | An earlier human decision on the same hash. |
| `cloudFilesHashVerdict` | SentinelOne's cloud rating of the hash. |
| `publisherName`, `certificateId`, `fileVerificationType`, `isValidCertificate` | **Who signed it, and whether the signature holds.** Required in every closure, quoted as read, including when empty. See "Who signed it" below. |
| `mitigationStatus[]` (per action) and `agentRealtimeInfo.rebootRequired` | Whether the response actually finished. See "Is the mitigation finished?" below. |

**Who signed it.** Read the four signer fields before judging what the file did, and
quote them in the closure whatever they say.

- **`SignedVerified` with `isValidCertificate: true` and a vendor in `publisherName`** means
  the file is that vendor's build, unless its certificate was stolen, which is rare and
  needs its own evidence. The question changes from "is this malware?" to "which product is
  this, is it allowed here, and did the installer do anything an installer wouldn't?". Go
  to "Is it an installed product?" in S4 and run the census on the publisher's product
  **before** writing a verdict.
- **Unsigned, `NotSigned`, or a signature that fails** is a fact about the file, not a
  verdict. Many in-house tools are unsigned. Say so and carry it to the verdict shapes.
- **A behavioural "Ransomware" label on a signed installer** is the common false positive:
  an office suite or similar installer writes tens of thousands of files, registers shell
  extensions, file associations, COM objects and scheduled tasks, which reads as mass file
  modification plus persistence. One such installer showed `remediate` 35,421 actions and
  `quarantine` 1,928. Those counts are the installer's own writes being reversed, not
  encrypted user files. Never call a signed vendor installer "confirmed ransomware" from
  the label and the counters alone.

**Behavioural indicators belong to the storyline, not the file.** Under a behavioural
engine (`DBT - Executables`) the threat's `indicators[]` are collected across its whole
`storyline`: the file, its parent, its children, and processes it touched. One installer's
record listed "User logged on", "Suspicious Kerberoasting attack. Too many SPN tickets
requests", "Detected attempt to query the SAM" and "illegitimate access to … Edge's
private memory" next to persistence and shell-extension indicators. An installer explains
the second group. It does not obviously explain the first.

- **Before citing an indicator against the file, attribute it to a process.** The record
  does not say which process raised each indicator. The storyline does (the SentinelOne
  console's storyline view, or Deep Visibility on the `storyline` id).
- **If the index cannot attribute it, the unexplained indicators are the escalation
  question.** Name them, name the storyline id, and say what would settle it. They are
  neither proof against the file nor noise to drop.
- **Group the indicators** in the closure: the ones the product's own install explains
  (shell extension, file association, COM, scheduled task, registry), and the ones it does
  not (credential access, injection into unrelated processes). The second group decides
  the verdict.

**Indicators say what a file *can* do, not what it did.** A threat's `indicators[]` come
from the engine that judged it. Under a static engine every entry is a **capability read
from the binary** — its imports, sections and strings: "File can delete files", "File can
create processes", "File can delay its execution", "high entropy, a sign of obfuscation or
packing". None of them is an observed action, and a long list of them is not a behavioural
profile. A packaged Python app (PyInstaller and similar) carries most of them by
construction: "This is a compiled Python executable", high-entropy sections, ZLIB, debugger
and kernel-exception imports, process create and terminate. An unsigned in-house tool built
that way reads, indicator by indicator, exactly like a dropper.

- **Decide static or dynamic on the engine, not on `detectionType` or
  `classificationSource`.** The same hash on the same `On-Write Static AI` engine has been
  stamped `detectionType: dynamic` on one record and `static` on the next, with
  `classificationSource: Behavioral` on both. Neither field showed that anything happened
  beyond the launch.
- **What counts as behaviour:** a dynamic engine (`DBT - Executables`); an indicator that
  reports an observed action rather than a capability; a child file or process whose
  `originatorProcess` is this file; activity in S1's window attributed to it. A launch by a
  named user (`originatorProcess: explorer.exe`, the "process started from shortcut"
  indicator) proves the file **ran** — not that it did anything harmful.
- **A capability list never supports `confirmed` on its own.** Quote it as "static
  indicators" in the closure, never as "a dropper/stealer behavioral profile". With no
  behaviour evidence, a suspicious static detection on a file the organisation might own is
  an escalation with one question — does the organisation recognise this file? — and
  remediation follows a no.

A ticket where every threat is `full_disk_scan` + a static engine is **a file at rest**.
It can still be real malware — but the question becomes "did it ever run?", not "is it
running?", and containment is quarantine, not isolation.

**The mitigation mode is set per confidence level, not per agent.** A SentinelOne policy
has one mode for *suspicious* threats and another for *malicious* ones, and the common
setting is detect for suspicious, protect for malicious. Three consequences:

- **The live endpoint record's `mitigationMode` is the malicious-threat mode.** On the same
  agent a suspicious threat can be stamped `detect` in `agentDetectionInfo` while the live
  record says `protect`. Neither record is wrong. A ticket or AI-assist that says "protect,
  so it auto-remediated" from the live record is wrong for a suspicious threat.
- **"Detect" on a suspicious threat is not a misconfigured host.** Before recommending a
  policy check, facet `agentDetectionInfo.agentMitigationMode` against
  `threatInfo.confidenceLevel` over the tenant's threats. If suspicious detections read
  detect and malicious ones read protect, that is the policy as configured. The finding is
  then the policy choice itself (suspicious threats wait for an analyst), not one host.
- **Compare only threats at the same confidence level.** Another host that auto-quarantined
  a *malicious* detection does not show that this host's *suspicious* detection should have
  been mitigated. Both follow the same policy.

**A detection's confidence can change after the ticket.** SentinelOne's cloud can raise a
suspicious threat to malicious hours later (activity `2037`), add its hash to the blocklist
(`2`), and remediate it automatically. A file not mitigated at the time of investigation may
be quarantined an hour later, and a new detection may follow from the same installer.
Before writing the verdict, re-read each threat's `confidenceLevel`, `mitigationStatus` and
`updatedAt`, and list every detection on the agent since the ticket's first one. State in the
closure the time your evidence runs to, and say that a later SentinelOne action can change
the verdict.

**Is the mitigation finished?** The top-level `threatInfo.mitigationStatus: mitigated` is
set as soon as the first action succeeds. Each entry of `mitigationStatus[]` has its own
`status` and `actionsCounters` (`success`, `failed`, `pendingReboot`, `notFound`):

- `status: pending-reboot`, any `pendingReboot > 0`, or `agentRealtimeInfo.rebootRequired:
  true` means the remediation or rollback is **not complete** until the host restarts.
  Activities `2032` / `2033` ("A reboot is required … to complete the remediate / rollback")
  say the same thing.
- `failed > 0` on `rollback` means some of the changes were not reversed. Name the count,
  and recommend checking those items after the reboot.
- Never write "kill, quarantine, remediate and rollback all completed" without these
  fields, and never explain the counters (for example as a group-wide broadcast) without
  evidence. Quote them as read.

**An analyst verdict from the customer's MDR is a relayed claim.** `analystVerdict:
true_positive` set by a managed-detection provider's user usually means "a valid
detection, now handled", not "proven malicious". The same provider marked a comparable
detection on the same account `false_positive` two days earlier. Quote it with who set it
and when, and weigh it as one party's disposition, never as independent confirmation of
your verdict (SKILL.md, "A relayed claim inherits none of the original's confidence").

**"Killed" does not prove it was running.** Activity `2001` "successfully killed the threat"
is reported as part of every remediation, even when no process existed. Evidence of
execution is the threat's `originatorProcess` and `processUser`, a child written by the
file (the child's `originatorProcess` names it), or a dynamic engine.

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
- **Origin** — the one document returned is the **oldest** threat. Only the earliest
  copy can say how the file arrived, and the order of the copies matters more than their
  folders. See "Arrival or departure" below.
- **Both feeds** — on the older feed the same hashes are `@s1.fileContentHash`; search
  the quoted SHA-1 without the `@eventType` filter and facet `@eventType` and
  `@s1.computerName` as well. The spread is the union of the two computer-name facets.
- **Prior execution anywhere** — rerun with a second filter
  `{ "field": "@sentinelOneThreat.threatInfo.initiatedBy", "terms": ["agent_policy"] }`
  and `limit: 2`. Any hit with a named `processUser` is someone running the file on
  another host; it is a side finding (S7) and a strong hint for this host.
- **Earlier verdicts** — an `analystVerdict: false_positive` on a hash that now fires
  through `User-Defined Blocklist` means the hash was blocklisted after being judged
  benign. That is a tuning finding, not an incident.

**Arrival or departure — order the copies before naming a delivery route.** One file
detected in several places on a host is a sequence, not a set. Put every copy on the host
in order of `identifiedAt` (facet `threatInfo.filePath` with `threatInfo.identifiedAt`,
or read the records) and mark the first launch (`originatorProcess` a shell such as
`explorer.exe` and a named `processUser`, or a "started from shortcut" indicator).

- **Only the earliest copy on a host is a candidate for the arrival route.** Its folder
  says which application last wrote it: an Outlook or mail-client attachment cache
  (`...\Content.Outlook\...`, `...\Olk\...`, a WebView2 `IndexedDB` blob under a mail
  origin), `Downloads`, a removable-drive letter, a `Temp\<guid>_<archive>.zip.<n>`
  extraction folder.
- **A copy that appears after a launch on the same host is the file being passed on, not
  arriving.** Mail-client cache copies minutes after the user ran the file mean the file
  was being attached and sent, or re-opened from a sent message. That changes the
  question from "who sent it to this user" to "who did this user send it to", and
  recipients are what a mail check should then look for.
- **`Downloads` does not name a source.** A browser download and an attachment saved
  from a mail client both land there. When the earliest copy is in `Downloads`, the route
  is "not established", not "browser download".
- **The earliest record is often not the arrival.** When it is a launch rather than an
  on-write detection, the file was already on disk when the agent first saw it. If its
  time is close to `registeredAt` (S3), or the static engine flags only on launch, the
  file may predate the agent. State the arrival as a gap.
- **Across hosts**, compare each host's earliest copy with the other hosts' launches. A
  host whose first copy sits in a mail cache shortly after another host's user ran and
  sent the file is a recipient. That is the internal spread path, and it is a different
  finding from external delivery.

Folder names are hints about which application touched the file. Never let one stand
alone as "consistent with email delivery". Say which copy, at what time, relative to which
launch.

### Is it an installed product?

When the detection is a **named application** rather than a dropped file (a remote-access
tool, an updater), count its installs with `assets/queries/s1_app_census.kql`. Treat it as
named when **any** of these name a product: the rule, the threat's `publisherName` (S2), or
the file name itself (a vendor's web installer often carries the product in its name, with a
download token appended). Use the product or the publisher as `{APP}`. On one ticket the
census found the same vendor's suite already on four other hosts at four different versions,
which pointed to users installing it themselves. An investigation that skipped the census
called that installer "confirmed ransomware". Hundreds of
hosts means deployed software; one host is the finding.

**A hash hit can be a named application that does not look like one.** Two signs:

- **The rule names a product.** A STAR hash rule's name or description cites a vendor
  campaign or a tool, while the file it hit has a meaningless name.
- **The file is in the Windows Installer cache.** That is `C:\Windows\Installer\<hex>.msi`
  (or `.msp`). Windows Installer keeps a renamed copy of every package it installs there,
  so it can repair, modify or uninstall the product later. A file there was **installed**,
  not downloaded or dropped by hand, and it is dormant. A scan finding it means the product
  is or was installed. It does not mean something ran, and the arrival-route analysis
  above does not apply.

Either sign changes the question to: **which product and version is this, and how many
hosts run it?**

**Run the three bundled queries; don't write your own first** (non-negotiable 4). They
already carry the column names, and the inventory's names are not the ones you would guess:

- **The host column is `agentComputerName`.** `computerName`, `hostName` and `assetName`
  are not columns.
- **`validate_kql` does not check column names.** A query on a column that doesn't exist
  passes validation, then returns no columns and no rows. That reads as "nothing installed",
  and it isn't.

Substitute the placeholders and run the queries as written. Your own queries come after
them, for anything they don't answer.

1. **Probe the inventory** with `assets/queries/s1_app_probe.kql`. `withName > 0` makes
   the table readable. A `take 1` with no `project` returns only `timestamp`, because the
   engine returns just the columns a query names. That is not an unreadable table, so never
   write a gap from it.
2. **Name the package** with `assets/queries/s1_host_apps.kql` on the subject host. Look for
   the product the rule names, or for an entry whose publisher fits the file's signer.
   Where the run has an external hash lookup, match the hash too. Where it has none, the
   identification rests on the inventory alone. Say so in the verdict sentence and in the
   closure's gaps, for example "named from the application inventory; the hash was not
   checked against external threat intelligence". A version range quoted from memory of a
   public advisory is not a hash check. Name it as background knowledge, not as a measured
   finding.
3. **Census it** with `assets/queries/s1_app_census.kql`, using a fragment of the product
   name.
4. **Compare the installed version with the range the rule targets.** A hash rule for a
   supply-chain campaign targets specific builds:
   - Installed versions **inside** that range: every host running them is in scope. That is
     a fleet exposure finding, not a single-host one.
   - Versions **outside** it, especially later than the vendor's fixed release: the rule's
     hash list is the suspect. The tuning goes to the SentinelOne console.

**One alerting host among many with the product is not a contradiction.** A STAR file-scan
rule fires when each agent's scan reaches the cached file. Scans run at different times,
and a new agent's first full disk scan can take weeks on a laptop that is often off. Unless
you measured why the other hosts are silent, write it down as a gap. It is not evidence
that the product is absent elsewhere.

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
  `agent_policy` threat on the tenant, or on the older feed any detection activity
  (`4003`/`19`) on another host. If the only detections on the tenant are this ticket's
  own, check the feed's oldest document first (see the two feeds above).
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

Examples from past tickets, not a lookup table: reason from what S2–S5 actually showed,
and expect tickets that fit none of these rows.

| What S2–S5 show | Verdict |
|---|---|
| Static hits from a first scan, malicious hash, no runtime detection, no sign of opening | Escalate for remediation (quarantine); no isolation |
| Same, plus Temp extraction folders or a runtime hit elsewhere by the same user | Escalate for remediation and a pre-install execution check on the host and the user's account |
| `agent_policy` + dynamic engine with a user process, not mitigated | Escalate for containment — this is the live case |
| Blocklist hit on a hash an analyst marked false positive | Benign for the host; tuning to the SentinelOne console |
| On-write or on-execution detections at suspicious confidence, a named user, not mitigated because suspicious threats are in detect mode | Escalate for remediation (quarantine), with the policy choice as a finding, not a host fault; re-check confidence before closing, since the cloud may upgrade it |
| An unsigned executable launched by named users on one or a few hosts over days, static on-write engine only (capability indicators, nothing observed), suspicious confidence | Escalate with one question: does the organisation recognise the file (an in-house or vendor tool)? Yes → benign, exclusion in the SentinelOne console; no → quarantine everywhere it is and trace where it came from. Not containment on the indicators alone |
| A STAR hash rule matched a cached installer (`C:\Windows\Installer\<hex>.msi`) during a full disk scan, with no threat record and no process. The inventory names the product at a version outside the range the rule targets, installed across the account | Benign for the host. The finding is the rule's hash list, tuned in the SentinelOne console. If the hash was identified from the inventory alone, say so. Inside the range: escalate as a fleet exposure covering every host with that version |
| A network STAR rule matched one browser DNS lookup to an uncommon-TLD domain. The firewall log shows it fetched in the same burst as a page's ad and analytics hosts, with a few minutes of small transfers and nothing after. The rule fires on many hosts and its earlier copies were closed | Benign, citing the page-load burst and the traffic that followed, not the process name. Tuning (a threshold, distinct domains, or excluding ad-serving lookups) goes to the SentinelOne console. Repeating connections or a non-browser actor: escalate |
| The same network STAR rule on one host on several working days, one domain. Each anchored lookup (first, latest, one between) sits inside the same site's page load or its ad-slot refreshes, with a few small flows after each | Benign: a site the user keeps open serves the domain through its ads. Tuning is an exclusion for that domain in the SentinelOne console; the recurrence is the user's habit, not persistence. A lookup with no page load around it: escalate |
| A vendor-signed (`SignedVerified`) installer the user launched from the browser, behavioural engine labels it "Ransomware" at suspicious confidence, auto-killed with mass remediation counts, the product already installed on other hosts. All indicators are explained by the install | Benign for the host: an unapproved application, not an attack. Recommend the customer decide whether the product is allowed, finish the pending reboot, and check failed rollback items. Not containment |
| The same, but the storyline also carries indicators the install does not explain (credential access, SAM or Kerberos activity, injection into unrelated processes) | Escalate with one question: which process in storyline `<id>` raised those indicators? From the installer: benign as above. From anything else: contain |
| A signed installer from a browser download writing further executables under the user's profile, single host, no spread | Usually an unwanted application the user installed; confirmed once the parent ran, contained when every child is quarantined; recommend checking persistence (Run keys, scheduled tasks, services) |

**Every verdict is as of a time.** A SentinelOne ticket keeps moving after it is raised:
cloud upgrades, automatic and analyst quarantines, new detections from the same installer.
Write the time your evidence runs to into the verdict.
