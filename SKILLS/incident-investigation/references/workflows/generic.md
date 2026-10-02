# Generic workflow (incident-investigation, step 3)

Run this when no dedicated workflow matches the ticket's type (see the routing table in
SKILL.md step 3) — an EDR alert, a firewall event, a Google Workspace login, a vendor
alert Fluency relays, anything new. It is not a query list. It is the order of questions
a dedicated workflow answers, with the tools that answer them on any data source.

> **Guidance, not a script.** These are the questions that settled past tickets with no
> dedicated workflow, in a sensible order. Add, reorder or skip any of them when the evidence
> points elsewhere, and say in the closure what you skipped and why. The non-negotiables
> in SKILL.md still apply.

Label every check in the closure **"generic workflow — improvised"** with the index or
table it came from, so a reader knows no vetted query set stood behind it. Everything
below runs on `ACCOUNT` only.

## G1 — Find and read the raw events behind the ticket

The summary tells you what fired; the raw event tells you what happened.

- **On an `asset_…` ticket, prove the host is one machine first.** The key is a host
  name, and a cloned or restored VM reports the original's name until it is renamed.
  Facet `@sender` on the host (SKILL.md step 4, "A hostname is not a machine"); with
  more than one sender, attribute every event to its sender before reading anything
  else, and name each address with `host_ip_owner.kql`. One ticket on the production
  name and a second ticket on a fresh `WIN-…` name the same day is the pattern.
- **Find where the source lands.** `lake_search_list_index` lists the raw indexes;
  `list_data_tables` lists the KQL tables and inventories. The ticket's attributes
  (`_customer`, the rule prefix, `detectionSourceVendor`) say which one.
- **Search by stable identifiers first** — agent id/uuid, alert id or `externalId`,
  object id, storyline id, hash. They are exact tokens. A product or process name
  (`ScreenConnect`) sits inside long strings and a bare-word search for it can return
  0 across hundreds of thousands of rows: that is the step-4 predicate trap, not an
  absence.
- **Read the whole event**, not the summary's attribute list: the actor (user, process,
  service account), its parent, its start time, signer, command line, source and
  destination, and what the product did about it (blocked, killed, excluded, failed).
- **A vendor's own rule is not a Fluency rule.** If `eventwatch_rule_list` has nothing
  under the rule's name, the logic lives in the vendor console and Fluency only relays
  the alert. The tuning in step 5 then goes to the vendor.
- **Microsoft Defender alerts list each file twice. Read `fileEvidence`.** The alert's
  `evidence[]` has a `fileEvidence` entry per file, with its path, hashes and verdict.
  It also has a `malwareEvidence` entry whose `files[]` repeats the files, but there
  the hashes can be null and the verdict `unknown` for all but one. Reading only
  `malwareEvidence` makes it look as though the scanner processed one file of several.
- **Defender for Cloud agentless alerts always carry placeholder fields.**
  `VM.Agentless_MalwareWasDetected` / `AgentlessAMThreatDetections` alerts come from a
  scan of a disk snapshot. They arrive with `detectionSource: unknownFutureValue`,
  `investigationState: unsupportedAlertType` and remediation `none` on every alert.
  Those values are not contradictions or signs of tampering. Show it by finding the
  same values on another agentless alert on the account. An agentless hit means a
  **file at rest**: it says nothing about execution, and real-time protection on the
  host did not act on that copy.

## G1b — How did the file get there?

When the ticket is about a file (a detection in `Downloads`, `Temp`, a mail cache or a
user folder), find how it arrived before judging the host. The arrival route is often
the real finding: a delivery path that bypasses mail filtering produces the same
ticket again on every host it reaches. On a Microsoft 365 tenant, two bundled queries
answer it:

- `assets/queries/file_mail_by_hash.kql` finds every message in the last 30 days that
  carried an attachment with this SHA256 (`TIMailData`, `AttachmentData`). It returns
  one row per message × recipient with Microsoft's `Verdict` and `DeliveryAction`.
  - **Read the outcome per recipient.** One message is often `Blocked` for some
    recipients, `DeliveredAsSpam` for others and `Delivered` for a third.
  - **Read the `Outbound` rows.** A forward, journal or copy to an outside system (a
    helpdesk or ticketing address, a shared-inbox tool) can be `Delivered` while every
    inbound copy was blocked. That system then hands the file to its users, outside
    the mail client's protection.
  - `P1Sender` `<>` with `P2Sender` set to an internal address is a spoofed internal
    sender.
- `assets/queries/file_download_origin.kql` reads the endpoint download records
  (`FileDownloadedFromBrowser`). They give when the file was saved, by whom, in which
  browser, and the **`OriginatingDomain`** it came from: a mail web client, a
  helpdesk's attachment host, a file-sharing site.
  - It matches the hash anywhere on the account, and the file name only on the
    subject host. Lures are often named after the company, and the company name
    appears in every OneDrive path.
  - Not every saved copy is logged. One row for three copies on disk is normal.
  - Rows from other users on the same host or the same originating domain show who
    else the route reaches. They are G6 side findings.

Run both before calling the route "not established". A zero from the mail query on a
tenant with `TIMailData` rows means the file did not arrive as an attachment in 30 days
(a link, a download or removable media remain possible). A zero from the download
query needs a control: any `FileDownloadedFromBrowser` row on the account.

**Use the download time as the anchor for everything after.** An agentless or
scheduled scan finds the file days after it arrived. The credential, sign-in and
activity checks start from the download time, not from the alert time. A ±24h window
around the alert can miss the whole period in which a phishing lure would have been
used.

## G2 — What is the thing that fired, and how common is it here?

Step 2 counted entities that fired the rule. This counts the **artifact** the rule fired
on — the process, application, file, app registration, domain — across the whole
account, whether or not it alerted.

- **Use the inventory tables.** Installed applications (`sentinelOneApplication`,
  `office365InstalledApp`, `office365Application`), device inventories
  (`msDefenderMachine`, `sentinelOneAgent`, `falconAgent`), vulnerability tables —
  whatever `list_data_tables` shows. Count hosts or users that carry the artifact, by
  version, publisher and signer.
- **Hundreds of hosts is deployed software; one is the finding.** Look at the tail of the
  same query as hard as the head: a second instance, a different signer or a copy
  installed yesterday is where the real incident usually hides.

## G3 — Resolve every indicator against the tenant

The Office365 workflow does this for sign-in IPs; do the same for whatever the ticket
carries — destination IPs and ports, domains, hashes, device or account ids.

| Shape | Reading |
|---|---|
| Hundreds of sources / hosts, every day | Company infrastructure or deployed software |
| Many first seen on the same day | A change — rollout, new rule, network move |
| A handful, recent | A site or project; corroborate in G5 |
| Exactly one | Keep going — check its neighbours (same /24, same publisher, same parent) first |

Good sources: agent inventories (`externalIp`, `lastIpToMgmt`), firewall traffic
(`NetworkFortigateTraffic` — flows and distinct sources, never summed bytes; for one
host follow `references/fortigate.md`, for volume the `fortigate-bandwidth` rules), and the platform `asset_search` inventory,
which on some accounts holds only log-derived hosts.

## G4 — Build the timeline from raw time

- **Raw timestamps only** — the event's own `createdAt` / `eventtime`, never the
  summary's 2-minute buckets (step 4). On a forwarded Windows feed that means
  `EventTime` (host-local, convert the zone) and `RecordNumber` for order: the
  `timestamp` column there is arrival time, and a backlog arrives in one second.
- **Include when the artifact started, not just when it alerted.** A process that has
  run for a month and alerts today points at the detection, not the process.
- **Include when the rule itself appeared.** A rule created minutes before a wave of
  identical alerts means the wave is the rule. Vendor ids are often time-ordered; if you
  derive a time from one, calibrate it on events with known times and label it
  *derived*.

## G5 — Prove what did not happen

Pick negatives by what the subject is (the step-1 profile says), and pair each zero with
a control.

- **A device:** other alerts or threats on the host in the same source and in every other
  endpoint source (Defender, EDR); what the product did (killed, quarantined, excluded,
  failed); the device's other activity that day; outbound connections after the event.
- **A user:** the Office365 workflow's 3c negatives if the account has Microsoft 365
  data; otherwise the identity provider's own sign-in and admin events, and any sharing,
  forwarding or app authorisation the user did afterwards.
- **Any zero needs a control.** Before writing "no alerts", run the same search for an
  entity that does have hits, or an empty search on the index. A control of 0 means the
  index is empty or unreadable — a **gap**, not a negative (e.g. "WindowsAudit holds no
  events in the window").

## G6 — Keep side findings separate

The artifact census and the indicator checks often surface something on a *different*
entity — another host with a foreign install, an infected machine the rule missed.
Record it as a separate item in the closure with its own evidence and a recommendation
to open its own ticket. Do not let it change this ticket's verdict, and do not
investigate it further inside this run.

## When the generic workflow keeps being used

If the same incident type goes through this workflow twice, the checks that settled it
are the draft of a dedicated workflow: write them into
`references/workflows/<type>.md` with tested queries and add a row to the step-3 table.
