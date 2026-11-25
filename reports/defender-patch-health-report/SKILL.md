---
name: defender-patch-health-report
version: 1.0.0
description: >-
  Produce a CISO-level Microsoft Defender for Endpoint PATCH AND HARDENING health report for ONE Fluency / Ingext tenant (HTML, PDF, CSVs) from the
  msDefender* resource dumps, with no scheduled report or archive needed. It shows where server patching stopped (months behind and last patched
  month per server), which exploitable CVEs to clear first and how long they have been open, which servers (domain controllers, backup, Hyper-V)
  are on the network but outside Defender, which enrolled servers have gone silent, which hardening controls (ASR rules, LAPS, BitLocker,
  ransomware protection) are off on every server, antivirus health, 30 days of de-duplicated alerts, and endpoint connections that deliver no
  data. USE THIS SKILL for "Defender health report", "patching health", "which servers need patching", "CISO view of Defender vulnerabilities",
  "exploitable CVEs and hardening for tenant X". DO NOT use it for the archive-based device-scoring report (defender-resource-report), one host
  (ingext-get-profile) or alert triage (incident-investigation).
---

# Defender Patch & Hardening Health Report

Answers the questions a CISO asks of Defender data: **are we patching, and if not where did it stop; what is exploitable because of it;
what is on the network that Defender does not protect; and are the controls that would contain an attack switched on.** It is read-only:
it calls `list_data_tables`, `list_resource_dumps`, `get_resource_dump_url`, `list_integrations` and one `kql_search` for alerts, nothing that writes.

It complements `defender-resource-report` (archive-based device scoring). This skill needs no scheduled report, works the day a tenant is
connected, and adds what the archive does not carry: per-server patch gap, silent and unmanaged servers, exploit age, fleet-wide baseline failures
and connector coverage.

**The resource tables come from resource dumps, not from `kql_search`.** The device, vulnerability, configuration and antivirus tables are
snapshots; the dump holds every row, so nothing is capped, sampled or retyped, and the data never passes through the conversation. Only the
alerts (an event stream, not a resource table) are read with a query, and that response is small.

`<skill-dir>` below means this skill's base directory.

## Inputs

| Input | Rule |
|---|---|
| Connector | The tenant MCP connector the user names. Use its tools directly. |
| Tenant | One account. `list_accounts`, match the user's name, stop if ambiguous. Never merge tenants. |
| Snapshot date | Today (UTC), `yyyy-mm-dd`. Used as `--asof` and for the alert window. |
| Customer name | Display name for the title. |

Work in a fresh directory, e.g. `./defender_patch_<account>_<yyyymmdd>/`. Dumps go in `<work>/dumps/<resource>/<customer>.jsonl.gz`.

## Steps

### 1. Confirm the tenant has Defender for Endpoint data

`list_data_tables(account)` must list `msDefenderMachine` and `msDefenderVulnerability` under `resourceTables`. If not, stop.

### 2. List the dumps

`list_resource_dumps(account)`. Note, for `msDefenderMachine`, `msDefenderVulnerability`, `msDefenderSecureConfig` and `msDefenderAvHealth`, the
customer name(s) and the `count`. The customer is the name of an `MSDefenderEndpoint` integration. If an `MSDefenderEndpoint` integration has no
dump, that is a coverage gap the report states.

### 3. Download the four dumps

For each (resource, customer), call `get_resource_dump_url(account, resource, customer, format="jsonl")`, then download it immediately (links
expire after 15 minutes, so one link at a time):

```bash
mkdir -p <work>/dumps/<resource>
curl -sSf -o "<work>/dumps/<resource>/<customer>.jsonl.gz" "<url>"
```

Do not read the dumps: no `zcat`, `head` or Read tool. Only the script opens them. If the download is refused by a proxy (403 or a denied
CONNECT), the sandbox blocks the tenant host: tell the user it must be allowed, or that the files can be downloaded from their own shell.

### 4. Write the two small inputs

`references/inputs.md` gives the exact content:

- `<work>/scope.json` from `list_integrations` and `list_resource_dumps`: the `MSDefenderEndpoint` integration names and the dump row counts.
- `<work>/a_alerts.json`: the response of the de-duplicated alert query. Run `python3 <skill-dir>/scripts/defender_patch_health.py window --asof <yyyy-mm-dd>`
  for the `rangeFrom` / `rangeTo` values (180 days, so alerts still open after 30 days are seen).

### 5. Check

```bash
python3 <skill-dir>/scripts/defender_patch_health.py check --work <work> --asof <yyyy-mm-dd>
```

`PROBLEM` (exit 1): a dump is missing, unreadable, truncated, empty, or its row count differs from `list_resource_dumps` (download it again).
`WARN`: the alert file or scope file is missing, the device snapshot is more than 2 days old, or no finding carries a
"`<Month> <Year> Security Updates`" name (every server would read as Current: the label changed).

### 6. Render

```bash
python3 <skill-dir>/scripts/defender_patch_health.py render --work <work> --account <account> \
  --customer "<Customer>" --asof <yyyy-mm-dd> --pdf
```

Writes to `<work>`: `defender_patch_health.html` (self-contained, Fluency brand), `defender_patch_health.pdf` with `--pdf` (needs node +
Playwright through the fluency-report renderer; if missing the script prints the command to run), `facts.json` (every number on the page), and
`servers.csv`, `unmanaged_servers.csv`, `exploitable_cves.csv`, `unenrolled_scanned_devices.csv`.

The structure is fixed by the script: KPI strip, three-column band, summary, scope note, then §1 Priority actions, §2 Patching, §3 Servers outside
Defender, §4 Coverage, §5 Vulnerabilities, §6 Configuration and hardening, §7 Alerts, Methodology. Do not hand-edit the HTML.

### 7. Review before delivering

Read §1 and §2 against `facts.json`. Check in particular:

- **Patch gap vs build.** The table shows the full OS build of every server. A server marked Behind should have a lower revision than a Current
  server of the same OS. The script runs this cross-check itself and prints the result under the server table (a Current server
  with an older build than a Behind server of the same OS is flagged, as is a Current server whose build has no revision). Where a server has
  a gap, its "oldest exploitable open" date normally falls on Patch Tuesday of its first missing month; if not, look at `outlierMonths` in
  `facts.json` and say so in your reply.
- **No data is not Current.** A server with no scan rows or silent for 30+ days is shown as No data. Say which servers, and that their patch
  state is unknown.
- **Priority order is by risk.** P1 patch actions are ranked by exploitable Critical/High findings, then months behind. The role (domain
  controller and so on) is shown but does not move a server up. Critical servers that are not enrolled and have been quiet for up to 90 days
  still get a P1 action.
- **Roles are inferred from host names** (dc, backup, hv, sql, print, mst). Tell the user to confirm any role that drives a P1 action.
- **Discovered-device operating systems are guesses.** Defender fingerprints unmanaged devices from network traffic; "Windows XP" on a
  laptop-named device is usually a misidentified modern laptop, and "Windows 10 1809" on a Hyper-V host is probably Windows Server. Do not
  repeat those counts as fact.
- **A connector with no data** means the totals may cover part of the estate. Say so first.

### 8. Deliver

Give the HTML, PDF and CSV paths and three sentences: the worst patch gap (server, months, last patched), the number of active servers
outside Defender, and whether ASR is off fleet-wide. Customer hostnames and vulnerabilities are sensitive: deliver as files and do not
publish a link unless the user asks.

## Tests

`python3 <skill-dir>/tests/test_defender_patch_health.py` runs the unit tests on a synthetic tenant (patch gap, roles, build cross-check, alert
aging, unmanaged and re-registered servers, configuration baseline, `check` failures). Run it after any change to the script.

## Method

`references/methodology.md` explains the patch-gap rule, exploitability, role inference, the unmanaged-server and duplicate-record logic,
the configuration baseline test and the known data-quality issues.

## Branding prerequisite

Requires the `fluency-report` skill (its `scripts/fluency_brand.py`, CSS, fonts and `render_pdf.mjs`). The script finds it next to this
skill (`../fluency-report/scripts`), in the repo layout (`../../SKILLS/fluency-report/scripts`), or at `FLUENCY_BRAND_DIR`, and stops with
a clear message otherwise. Do not hand-write report styling.
