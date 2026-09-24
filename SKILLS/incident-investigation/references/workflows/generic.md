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
(`NetworkFortigateTraffic` — session counts and distinct sources, never summed bytes
without the `fortigate-bandwidth` rules), and the platform `asset_search` inventory,
which on some accounts holds only log-derived hosts.

## G4 — Build the timeline from raw time

- **Raw timestamps only** — the event's own `createdAt` / `eventtime`, never the
  summary's 2-minute buckets (step 4).
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
