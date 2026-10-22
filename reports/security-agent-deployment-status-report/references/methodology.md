# Methodology

## Data: resource dumps

Every resource table in Fluency is backed by a **resource dump**. A dump is a full inventory
snapshot for one resource type and one customer (integration), written about hourly as gzipped
JSONL. Each line is one vendor record wrapped in an envelope:

```json
{"@resource_type": "sentinelOneAgent", "@customer": "SentinelOne-default-resource",
 "@dayIndex": "20260101-08", "@timestamp": 1767255000000, "@key": "...",
 "@sentinelOneAgent": { "computerName": "...", "osName": "...", "lastActiveDate": "...", ... }}
```

- **Vendor fields.** The vendor fields sit under `@<resource>` and keep the vendor API's own names.
  These are the same names a search on the resource table uses.
- **Snapshot hour.** `@dayIndex` (`YYYYMMDD-HH`) is the snapshot hour and is the same for every line
  in a dump.
- **`@timestamp` varies per record.** It is not the snapshot time.

A search on a resource table reads the latest dump: the record counts and byte sizes are identical.
A report built from dumps therefore sees exactly the same data.

The script uses the following inputs:

- **Field paths** are dotted paths into the vendor record, e.g. `activeDirectory.computerDistinguishedName`.
- **Timestamps** may be ISO 8601 strings with any fraction length and an optional offset, or epoch
  milliseconds. Anything else counts as "no timestamp", so the record is stale.
- **Several dumps for one resource** (several integrations) are combined.

## Per-device model

**Scope.** Each source keeps only the records matching its `filter`. Each kept record gives a host,
an optional device ID, an OS and a last-seen time.

**Hostname normalization.** The host is:
1. lowercased;
2. cut at the first `.`, which drops the DNS suffix: `WS-0142.corp.example` becomes `ws-0142`;
3. stripped of a trailing `$`, because Entra and AD list computer accounts as `NAME$`.

Records with an empty host are skipped.

**Device-ID matching.** One source can be the `idAuthority`; by default that is Entra ID.
- When a record from any source carries a `deviceId` that the authority also holds, the record is
  filed under the authority's hostname. This lines up machines renamed in one inventory but not in
  another.
- IDs are compared case-insensitively.
- Defender's `aadDeviceId` is the Entra `deviceId`.
- A vendor's own agent or device ID must not go in `deviceId`.
- Records without a matching ID fall back to the normalized hostname.

**State per source.** For each device, every source is in one of three states:

| state | meaning |
|---|---|
| `active` | the source has a record seen within `staleDays` |
| `stale` | the source has records, but all are older |
| `missing` | the source has no record for the device |

Duplicate records collapse into one device. A source counts as active if any of its records for the
host is active, which covers re-onboarded agents.

**Status.** The first matching rule wins:

| status | rule |
|---|---|
| Inactive | not active in any source; excluded from every total |
| Missing agent | at least one **required** source is missing |
| Agent not reporting | every required source is present, and at least one is stale |
| Compliant | every required source is active |

Reference sources such as Entra ID never make a device non-compliant. They help with matching and
appear as context columns.

**Compliance %** is `Compliant / (all devices − Inactive)`. Per-source coverage % is the share of
active devices that the source sees as active.

**Device class.** The OS comes from the first source, in list order, that has one. The class is
chosen by keyword:

| class | OS contains |
|---|---|
| Server | `server` |
| Linux | linux, ubuntu, centos, red hat, rhel, debian, suse, rocky or alma |
| Workstation | anything else |

The keyword list lives in `CLASS_KEYWORDS` in the script.

## Health check

`check`, and `render` before it does anything else, flag a source when any of these is true:
- no dump was downloaded;
- the dump is empty;
- no record matches the filter;
- no record was seen within `staleDays`;
- the host field is empty on every record;
- the snapshot is more than 48 hours old.

Each of these points to a broken integration or a wrong filter, not to missing agents. `render`
refuses to continue while a required source is flagged, unless you pass `--allow-unhealthy`.

## Outputs

| file | contents |
|---|---|
| `facts.json` | totals, per-source coverage, issues (with device-class split and reference absence), presence patterns, inactive breakdown, device-class breakdown, source health, default narrative |
| `devices.csv` | every device: host, OS, class, status, issue, active-in, and per source the state and latest last-seen |
| `<stem>.html` | the report, which prints to A4 |

## Data pitfalls in the default sources

- **Defender** (`msDefenderMachine`) lists discovered but unmanaged devices next to onboarded ones.
  On some tenants the discovered-only devices outnumber the onboarded ones. The filter keeps
  `onboardingStatus: "Onboarded"` and `isExcluded: false`.
- **Entra ID** (`office365Device`) includes phones, tablets, printers and personally registered
  devices. The filter keeps enabled devices that:
  - run Windows or macOS;
  - are Entra-joined (`AzureAd`) or hybrid-joined (`ServerAd`).

  Registered devices (`Workplace`) are excluded. Check `fields` output for the `operatingSystem`
  values a tenant actually uses.
- **SentinelOne** (`sentinelOneAgent`) keeps decommissioned agents; the filter excludes them.
  Re-imaged machines can leave several agent records under one hostname, and these collapse into one
  device.
- **Shared hostnames.** Two different machines with the same short hostname merge into one device.
  Hostname reuse after a rebuild is the usual cause.
- **Integrations without dumps.** An integration can exist with no dumps behind it.
  `list_resource_dumps` won't show it, and the health check catches it if it is the only source for a
  resource.

## Relationship to the FPL report

The script follows `Security_Deployment_Status.fpl.js` rule for rule, including the trailing-`$`
normalization. It was checked on one tenant against the same snapshot:
- Totals and per-issue counts match the FPL report once the trailing-`$` fix is applied.
- Every device in the attention list matches a search-based implementation of the same rules: same
  host, same OS and same state in every source.
