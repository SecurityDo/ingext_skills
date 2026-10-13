# Adding or changing a source

Each entry in `sources.json` describes one inventory. To add a source, add an entry, download its
dump, and run `check`. Nothing else needs to change: matching, statuses, panels, method text, device
list and CSV all adapt.

## Fields

| field | required | meaning |
|---|---|---|
| `name` | yes | Identifier used internally and in CSV columns. Letters, digits and `_`, starting with a letter. |
| `label` | no | Display name in the report; defaults to `name`. Keep it short, because it becomes a column header. |
| `scope` | no | One phrase describing what is counted. Shown under "How this report is built". |
| `resource` | yes | Resource type as `list_resource_dumps` shows it, e.g. `msDefenderMachine`. |
| `filter` | no | Which records count as devices for this source (syntax below). |
| `host` | yes | Field path holding the hostname. It is normalized: lowercased, DNS suffix and trailing `$` removed. |
| `deviceId` | no | Field path holding the **Entra device ID**. Only that identifier may go here. |
| `idAuthority` | no | `true` on the one source whose hostname wins when device IDs match. Normally Entra ID. |
| `os` | yes | Field path holding the OS name. The first source in list order that has one wins. |
| `lastSeen` | yes | Field path holding the last-seen timestamp: ISO 8601, or epoch milliseconds. |
| `required` | no | `true` if a device missing from this source is a deployment gap. `false` (the default) makes it reference-only. Set it explicitly. |
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

- Comparisons are exact and case-sensitive. The one exception is a JSON boolean, which also matches
  the strings `"true"` / `"false"`.
- A field missing from the record counts as `null`.

Anything more complex, such as date ranges or partial string matches, needs a small change in
`in_scope()` in the script.

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

Hostnames in `DOMAIN\name` form, or anything else plain normalization doesn't handle, need an
extra rule in `norm_host()`.

## Required or reference?

- **Required:** an agent that must be on every active device, such as an EDR or AV agent. A device
  missing it counts as a gap.
- **Reference:** an inventory that describes the estate but doesn't protect it, such as Entra ID,
  Intune, AD or a CMDB. It helps with matching and appears as a column, but never creates a gap. A
  server that isn't in Entra ID is not a problem in itself.
- **Watch reference scopes.** A reference source still adds devices found nowhere else. If its
  filter is broader than the estate you mean to report on, those extra devices show up as "missing
  all agents". Example: personally registered devices in an Intune source.

At least one source must be required. With two required sources, the KPI note reads "one or both
agents"; with three or more, "one or more agents". The report creates a separate issue for each
combination of missing or stale required sources.

## Layout limits

- **Up to 3 sources:** the compact layout. Page 1 holds every panel and the next steps.
- **4 sources:** the presence matrix and device-type panels go full width, and the next steps may move
  to page 2.
- **5 or more sources:** the device-list columns get narrow. Drop the sources that add little, or
  split the report.

## Removing a source

Delete its entry. If it was the `idAuthority`, device-ID matching is off and every match uses the
hostname. Set `idAuthority` on another source that has a `deviceId` field to turn it back on.
