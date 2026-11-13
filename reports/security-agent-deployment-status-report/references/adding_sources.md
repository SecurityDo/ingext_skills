# Adding or changing a source

Each entry in `sources.json` describes one inventory. To add a source, add an entry, download its
dump, and run `check`. Nothing else needs to change: matching, statuses, panels, method text, device
list and CSV all adapt. A source that is configured but has no dump on an account is left out of
that account's run, so one sources file serves accounts with different inventories.

## Fields

| field | required | meaning |
|---|---|---|
| `name` | yes | Identifier used internally and in CSV columns. Letters, digits and `_`, starting with a letter. |
| `label` | no | Display name in the report; defaults to `name`. Keep it short, because it becomes a column header. |
| `scope` | no | One phrase describing what is counted. Shown under "How this report is built". |
| `resource` | yes | Resource type as `list_resource_dumps` shows it, e.g. `msDefenderMachine`. |
| `filter` | no | Which records count as devices for this source (syntax below). |
| `host` | yes | Field path holding the hostname, or a list of paths tried in order. It is normalized: lowercased, DNS suffix and trailing `$` removed; an IP address is kept whole. A list value, or a list serialized in a string (`"['a.corp', 'b.corp']"`), gives its first element. |
| `deviceId` | no | Field path holding the **Entra device ID**. Only that identifier may go here. |
| `idAuthority` | no | `true` on the one source whose hostname wins when device IDs match. Normally Entra ID. |
| `os` | yes | Field path holding the OS name. The first source in list order that has one wins. |
| `deviceType` | no | Field path holding a device type such as `Firewall` or `UPS`. Any value that is not a computer type makes the device a network device. |
| `lastSeen` | yes | Field path holding the last-seen timestamp: ISO 8601, or epoch milliseconds. |
| `staleDays` | no | Activity window for this source; defaults to the top-level `staleDays`. Use it for a source that sees devices periodically, like a pentest. |
| `ip` | no | Field path holding the device's internal IP address, or a list of paths. A path through a list takes every element: `ipAddresses.ipAddress` is each interface's address. On an agent source it builds the IP index that discovery hosts match against. Loopback, link-local and multicast addresses are ignored. |
| `key` | no | Field path that identifies one device within this source, when the hostname can't. Records with the same key are one device, e.g. one IP across several pentests. |
| `matchIp` | no | `true` for a source whose hosts may lack a usable name, typically a network scanner. Its devices are matched by name first, then by IP against the other sources' `ip`. |
| `discovery` | no | `true` for a source that finds devices by scanning the network. It gets its own panel, and devices found only by it are counted as "in no other inventory". |
| `weaknesses` | no | Field path holding a per-host count of weaknesses or vulnerabilities. Shown in the device list and used to rank gaps. |
| `confirmedWeaknesses` | no | Field path holding the per-host count of weaknesses the scanner confirmed or exploited. |
| `required` | no | `true` if a device missing from this source is a deployment gap. `false` (the default) makes it reference-only. Set it explicitly. |
| `activeLabel` | no | Text for "active" cells in the device list; defaults to `"Active"`. `"Seen"` reads better for a scanner. |
| `missingLabel` | no | Text for "absent" cells of a reference source, e.g. `"Not joined"` for Entra ID. Defaults to `"Not listed"`. |

Top level: `staleDays` (default 30) sets the activity window.

Field paths are dotted paths into the vendor record, e.g. `agent.lastCheckIn`. Two sources may read
the same resource with different filters. For example, Entra ID and Intune-managed devices can both
come from `office365Device`.

## Filter syntax

`filter` is an object. A record is in scope when **every** key matches.

| form | meaning | example |
|---|---|---|
| `"field": value` | equal | `"onboardingStatus": "Onboarded"`, `"isExcluded": false` |
| `"field": [v1, v2]` | any of | `"trustType": ["AzureAd", "ServerAd"]` |
| `"field": {"not": value or [...]}` | not equal to / none of | `"status": {"not": ["retired", "deleted"]}` |
| `"field": {"match": "<regex>"}` | regex search, case-insensitive | `"computerDnsName": {"not": {"match": "^worker-[0-9a-f]{8}-"}}` |

- Comparisons are exact and case-sensitive. A JSON boolean also matches the strings `"true"` /
  `"false"`, and `match` ignores case.
- A field missing from the record counts as `null`; `match` never matches it.
- A bad regex, or any other operator object, makes the sources file invalid.

Anything more complex, such as date ranges, needs a small change in `in_scope()` in the script.

**Excluding a tenant's throwaway machines.** Some tenants auto-onboard short-lived VMs, such as
backup or build workers created and deleted every day. Left in, they appear as hundreds of devices
missing an agent. Exclude them with a `match` filter in the work-directory copy of the sources file,
not the bundled one. Say so in that source's `scope` text, which the report prints under "How this
report is built".

## Exploring a new dump

1. Call `list_resource_dumps` and find the resource type and its customers.
2. Download the dump into `<work>/dumps/<resource>/<customer>.jsonl.gz`, as in SKILL.md step 2.
3. List its fields:

   ```bash
   python3 <skill-dir>/scripts/deployment_status.py fields --dumps <work>/dumps --resource <resource>
   ```

   Each field path is printed with:
   - how often it is filled;
   - its type;
   - its number of distinct values;
   - either the values with their counts (for 8 or fewer distinct values), or one example.

   Low-cardinality fields such as status, type and enabled flags are your filter candidates. Pick
   `host`, `os` and `lastSeen` from the rest.
4. Add the entry and run `check`. The new source should show plausible in-scope, active and host
   counts. Compare the in-scope host count with the vendor console's device count.

Typical vendor field names to look for (always confirm with `fields`):

| inventory | host | last seen | OS | Entra device ID |
|---|---|---|---|---|
| Intune managed devices (Graph `managedDevice`) | `deviceName` | `lastSyncDateTime` | `operatingSystem` | `azureADDeviceId` (usable as `deviceId`) |
| CrowdStrike Falcon hosts | `hostname` | `last_seen` | `os_version` / `platform_name` | none: Falcon's `device_id` is its own ID, so leave `deviceId` out |
| Active Directory computers | `name` / `dNSHostName` | `lastLogonTimestamp` | `operatingSystem` | none |
| Defender machines, every interface IP | `computerDnsName` | `lastSeen` | `osPlatform` | `aadDeviceId`; `ip`: `["lastIpAddress", "ipAddresses.ipAddress"]` |
| Horizon3 NodeZero hosts (`horizon3Host`) | `["DNSHostnames", "Hostname"]`, `key: "IP"` | `pentest.completedAt` | `OS` | none |

Hostnames in `DOMAIN\name` form, or anything else plain normalization doesn't handle, need an
extra rule in `norm_host()`.

## Required or reference?

- **Required:** an agent that must be on every active device, such as an EDR or AV agent. A device
  missing it counts as a gap.
- **Reference:** an inventory that describes the estate but doesn't protect it, such as Entra ID,
  Intune, AD, a CMDB or a network scanner. It helps with matching and appears as a column, but never
  creates a gap. A server that isn't in Entra ID is not a problem in itself.
- **Watch reference scopes.** A reference source still adds devices found nowhere else. If its
  filter is broader than the estate you mean to report on, those extra devices show up as "missing
  all agents". Example: personally registered devices in an Intune source.

At least one source must be configured as required. With two required sources, the KPI note reads
"one or both agents"; with three or more, "one or more agents". The report creates a separate issue
for each combination of missing or stale required sources. If no required source has usable data
on an account, the report lists the inventories and says agent coverage was not assessed.

## Discovery sources (network scanners)

A scanner such as Horizon3 NodeZero, Tenable, Qualys or Rapid7 sees what is on the network, whatever
inventory it is in. That makes it the best way to find machines no agent console knows about. It
also brings three problems, and each one has a setting:

- **Hosts without a usable name.** Many scanned hosts have only an IP, and some scanners report a
  different name for the same IP from scan to scan. Set `key` to the IP so one IP is one device. Set
  `host` to the name fields in order of trust, DNS first. A name is used only when it is the same in
  every record for that IP.
- **Matching to agents.** Set `matchIp: true` here, and `ip` on the agent sources. A host whose name
  no other source knows is then matched to the one device that an agent source lists at the same
  IP. If several devices hold that IP, there is no match. A host that matches nothing is listed by
  its IP address. Give an agent source every interface address where it has them: a scanner often
  sees a server's second network card.
- **Things that can't run an agent.** Firewalls, switches, power units, printers and server
  management cards are classed as network devices (from `deviceType` or the OS string) and counted
  as "no agent expected". Hosts with no detectable OS are "unidentified": they are listed for the
  client to identify, but kept out of the percentages.

Also set `staleDays` to the scan cadence (the Horizon3 default is 90, the plugin's window), so a
host seen in the last scan is not inactive. Filter out scan types that don't describe the internal
network: Horizon3's external, cloud, phishing and web-app pentests are excluded by
`pentest.opType`.

## Layout limits

- **Up to 3 sources:** the compact layout. The panels sit two per row.
- **4 sources:** the presence matrix and device-type panels go full width.
- **5 or more sources:** the device-list columns get narrow. Drop the sources that add little, or
  split the report.

The counts are of the sources used in the run, so a configured source that an account doesn't have
doesn't count.

## Removing a source

Delete its entry. If it was the `idAuthority`, device-ID matching is off and every match uses the
hostname. Set `idAuthority` on another source that has a `deviceId` field to turn it back on.
