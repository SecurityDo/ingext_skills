# Methodology

## Data: resource dumps

Every resource table in Fluency is backed by a **resource dump**. A dump is a full inventory
snapshot for one resource type and one customer (integration), written as gzipped JSONL: about
hourly for agent inventories, and when the pentest list changes (at least daily) for Horizon3. Each
line is one vendor record wrapped in an envelope:

```json
{"@resource_type": "sentinelOneAgent", "@customer": "SentinelOne-default-resource",
 "@dayIndex": "20260101-08", "@timestamp": 1767255000000, "@key": "...",
 "@sentinelOneAgent": { "computerName": "...", "osName": "...", "lastActiveDate": "...", ... }}
```

- **Vendor fields.** The vendor fields sit under `@<resource>` and keep the vendor API's own names.
  These are the same names a search on the resource table uses.
- **Snapshot hour.** `@dayIndex` (`YYYYMMDD-HH`) is the snapshot hour and is the same for every line
  in a dump.
- **`@timestamp` varies per record** on some resources. It is not the snapshot time.

A search on a resource table reads the latest dump: the record counts and byte sizes are identical.
A report built from dumps therefore sees exactly the same data.

The script uses the following inputs:

- **Field paths** are dotted paths into the vendor record, e.g. `activeDirectory.computerDistinguishedName`.
- **Timestamps** may be ISO 8601 strings with any fraction length and an optional offset, or epoch
  milliseconds. Anything else counts as "no timestamp", so the record is stale.
- **Several dumps for one resource** (several integrations) are combined, except a dump whose
  snapshot is more than 48 hours older than the newest one for that resource. That dump comes from a
  replaced or removed integration, which keeps its last dump. It is left out, with a warning.
- **Files** may be `.jsonl.gz` or plain `.jsonl`. A file that can't be read through (truncated or
  corrupt download) is left out with a warning. A line that isn't a JSON object is skipped and
  counted.

## Per-device model

**Scope.** Each source keeps only the records matching its `filter`. Each kept record gives a host,
an optional device ID, IP, OS, device type and weakness counts, and a last-seen time.

**Hostname normalization.** The host is:
1. lowercased;
2. cut at the first `.`, which drops the DNS suffix: `WS-0142.corp.example` becomes `ws-0142`.
   An IP address is kept whole;
3. stripped of a trailing `$`, because Entra and AD list computer accounts as `NAME$`.

Records with an empty host are skipped, unless the source has a `key` or matches by IP.

**Units.** A source's records first collapse into units, one per device as that source sees it:
- the `key` value when the source sets one (for Horizon3, the IP across every pentest in the
  window);
- otherwise the device-ID-mapped or normalized hostname.

A unit keeps every candidate name, its IPs and the latest last-seen time. OS, device type and
weakness counts come from its most recent record.

**Device-ID matching.** One source can be the `idAuthority`; by default that is Entra ID.
- When a record from any source carries a `deviceId` that the authority also holds, the record is
  filed under the authority's hostname. This lines up machines renamed in one inventory but not in
  another.
- IDs are compared case-insensitively.
- Defender's `aadDeviceId` is the Entra `deviceId`.
- A vendor's own agent or device ID must not go in `deviceId`.
- Records without a matching ID fall back to the normalized hostname.

**Name and IP matching for discovery sources** (`matchIp`). A unit of such a source is filed under
the first of these that applies:

| rule | how |
|---|---|
| 1 | the authority hostname for a known device ID |
| 2 | its **consistent name**, if another source knows that name |
| 3 | the one hostname that another source lists at the same IP (every address the sources' `ip` paths give, e.g. all of a Defender machine's interfaces; loopback and link-local addresses are ignored; an IP held by several devices matches nothing) |
| 4 | its consistent name, unknown elsewhere |
| 5 | its IP address |

A consistent name comes from the first `host` path that gives the same name in every record of the
unit. A name that changes between pentests is not trusted for matching. The names a unit was
reported under still appear in the device list and in the CSV `otherNames` column, as hints for the
client. The render output and `facts.matching` count how each unit was matched.

**State per source.** For each device, every source is in one of three states:

| state | meaning |
|---|---|
| `active` | the source has a record seen within its `staleDays` |
| `stale` | the source has records, but all are older |
| `missing` | the source has no record for the device |

Duplicate records collapse into one device. A source counts as active if any of its records for the
host is active, which covers re-onboarded agents.

**Device class.** The OS and device type come from the first source, in list order, that has
either. The class is chosen in this order:

| class | rule |
|---|---|
| Network device | the device type is not a computer type, or the OS or device type names a network product (firewall, switch, UPS, PDU, printer, iDRAC, FortiOS, APC, Cisco, ... as whole words) |
| Server | OS contains `server` |
| Linux | OS contains linux, ubuntu, centos, red hat, rhel, debian, suse, rocky or alma |
| Workstation | any other OS |
| Unknown | no OS and no device type from any source |

The keyword lists live in `NETWORK_WORDS` and `CLASS_KEYWORDS` in the script.

**Status.** The first matching rule wins:

| status | rule |
|---|---|
| Inactive | not active in any source; excluded from every total |
| No agent expected | no required source has the device, and it is a network device |
| Unidentified | no required source has the device, and no source reports an OS (in practice a host only a scanner found) |
| Not assessed | no required source is usable in this run |
| Missing agent | at least one **required** source is missing |
| Agent not reporting | every required source is present, and at least one is stale |
| Compliant | every required source is active |

Reference sources such as Entra ID and Horizon3 never make a device non-compliant. They help with
matching and appear as context columns.

**Totals.** "Active devices" counts the agent-assessment scope: Compliant, Missing agent, Agent not
reporting and Not assessed. Unidentified hosts and network devices are reported separately and are
not part of any percentage.
- **Compliance %** is `Compliant / active devices`, or `null` when no required source is usable.
- **Per-source coverage %** is the share of active devices that the source sees as active.
- **"Devices requiring attention"** lists Missing agent, Agent not reporting and Unidentified.

## Health check and partial data

`check`, and `render` before it does anything else, leave a source out of the run when any of these
is true:
- no dump was downloaded;
- no dump could be read;
- the dump is empty;
- no record matches the filter;
- no record was seen within the source's `staleDays`;
- the host (or key) field is empty on every record.

Each of these points to a missing or broken integration or a wrong filter, not to missing agents.
Counting such a source would mark every device as missing that agent, so it is left out instead.

These keep the source but are warnings:
- a snapshot more than 48 hours old;
- a superseded or unreadable dump left out;
- skipped lines.

What is left out:
- **A required source.** The report shows a "Data coverage" note on page 1 and measures the
  remaining required agents only.
- **Any source.** It is named under "Not included" in the method section and listed in
  `facts.unavailableSources` with the reason.
- **Every required source.** The report still renders. It lists the inventories, shows the
  compliance KPIs as not assessed, and recommends connecting an agent inventory.

The script exits 0 in all these cases. Only an invalid sources file stops it.

## Outputs

| file | contents |
|---|---|
| `facts.json` | totals, per-source coverage, issues (with device-class split, reference absence and weakness counts), presence patterns, inactive breakdown, device-class breakdown, discovery breakdown, matching counts, source health, sources left out, default narrative |
| `devices.csv` | every device: host, OS, class, status, issue, active-in, per source the state and latest last-seen, then IPs, other names seen, weaknesses and confirmed weaknesses |
| `<stem>.html` | the report, which prints to US Letter |

## Data pitfalls in the default sources

- **Defender** (`msDefenderMachine`) lists discovered but unmanaged devices next to onboarded ones.
  On some tenants the discovered-only devices outnumber the onboarded ones. The filter keeps
  `onboardingStatus: "Onboarded"` and `isExcluded: false`. An account can have a Defender
  integration that collects alerts but no machine inventory; then there is no dump and Defender is
  left out.
  - **Short-lived VMs.** Defender keeps a record for every VM it ever onboarded. A tenant that runs
    throwaway VMs (backup or build workers created per job) can have hundreds of them in the 30-day
    window, often outnumbering the real machines, each named `<prefix>-<random id>`. After `check`,
    look at the active Defender hosts for one name pattern that dominates. Exclude it with a `match`
    filter in the run's copy of the sources file, and say so in the scope text (see
    adding_sources.md).
  - **Several records per name.** Pooled or re-imaged session hosts get a new record each time they
    are rebuilt. They collapse into one device by hostname.
  - **Interfaces.** `ipAddresses` lists every interface. The default `ip` uses it, so a hypervisor's
    second network card, which NodeZero sees as a separate host, lines up with the hypervisor.
    `lastIpAddress` alone would leave it as a false gap. Container bridge addresses such as
    `172.17.0.1` repeat across hosts and so never match.
- **Entra ID** (`office365Device`) includes phones, tablets, printers and personally registered
  devices. The filter keeps enabled devices that:
  - run Windows or macOS;
  - are Entra-joined (`AzureAd`) or hybrid-joined (`ServerAd`).

  Registered devices (`Workplace`) are excluded. Check `fields` output for the `operatingSystem`
  values a tenant actually uses. Entra reports Windows servers as plain `Windows`, so a server known
  only to Entra is classed as a workstation.
- **SentinelOne** (`sentinelOneAgent`) keeps decommissioned agents; the filter excludes them.
  Re-imaged machines can leave several agent records under one hostname, and these collapse into one
  device. `lastIpToMgmt` is the address the agent last used to reach the console. A multi-homed
  server (a hypervisor, say) is matched on that address only, so a scanner that saw its other
  interface lists that interface as a separate host.
- **Horizon3** (`horizon3Host`) holds one record per host per pentest, for every finished pentest in
  the plugin's window (90 days by default):
  - Hosts often carry no name. Server management cards and power units are reported under a
    different name in each pentest, and one name can appear on several IPs. That is why the source
    is keyed on `IP` and only a consistent DNS name or hostname is trusted.
  - `OS` is often generic (`Microsoft Windows`), so such hosts are classed as workstations.
  - Hosts NodeZero could not fingerprint have no OS at all and become unidentified.
  - `DNSHostnames` arrives as a list serialized in a string; its first entry is the host's name.
  - `pentest.opType` keeps internal-network pentests (`NodeZero`, `NetworkEnumeration`, insider
    threat and similar) and drops `ExternalAttack`, `AWSPentest`, `AzurePentest`, `K8sPentest`,
    `Phishing` and `WebApp`.
  - Weakness counts come from the host's most recent pentest.
- **Shared hostnames.** Two different machines with the same short hostname merge into one device.
  Hostname reuse after a rebuild is the usual cause.
- **Integrations without dumps.** An integration can exist with no dumps behind it.
  `list_resource_dumps` won't show it. Its source is left out, and the health check says so.

## Relationship to the FPL report

The script follows `Security_Deployment_Status.fpl.js` rule for rule, including the trailing-`$`
normalization. It was checked on one tenant against the same snapshot:
- Totals and per-issue counts match the FPL report once the trailing-`$` fix is applied.
- Every device in the attention list matches a search-based implementation of the same rules: same
  host, same OS and same state in every source.

The discovery-source rules (keyed units, IP matching, network-device and unidentified statuses), the
per-source windows and the partial-data handling are additions the FPL report does not have. On one
tenant, the original three-source configuration gave the same results as the previous version: the
device rows, totals, issues, presence patterns and device-class split were all identical. The
deliberate differences are these:
- a superseded dump (more than 48 hours older than the newest for its resource) is left out;
- a hostname that is an IP address is kept whole instead of being cut at the first dot;
- "data as at" is the oldest snapshot among the required sources, not among all sources. Each
  source's snapshot time is listed in the method section.
