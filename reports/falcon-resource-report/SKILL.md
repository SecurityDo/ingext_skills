---
name: falcon-resource-report
version: 1.0.0
description: >-
  Produce a CrowdStrike Falcon resource report for ONE Ingext/Fluency tenant as HTML (print-style and interactive), PDF and CSVs from the
  falconAgent resource dump joined to 30 days of FalconAlert detections: host check-in health, sensor versions, operating systems,
  protection gaps (reduced functionality mode, unprovisioned sensors, missing prevention policy, containment, uninstall protection),
  policy coverage and open endpoint detections per host, with a score that ranks which hosts need action. USE THIS SKILL for
  "CrowdStrike resource report", "Falcon host inventory", "Falcon sensor health for tenant X", "which Falcon hosts have protection gaps
  or open detections". DO NOT use it for agent coverage against other products (security-agent-deployment-status-report), OS support
  dates (endpoint-os-currency), alert triage or a single host (ingext-get-profile).
---

# CrowdStrike Falcon Resource Report

One report for the Falcon resource type a tenant imports:

| Resource | What it holds |
|---|---|
| `falconAgent` | One record per host with a Falcon sensor: identity, OS, sensor version, check-in times, containment and reduced functionality state, assigned policies |

| `FalconAlert` | An event stream, not a resource dump. The report reads a 30-day view of it from the archive of `CrowdStrike_Resource_Report` (or, without an archive, two `kql_search` calls; see step 2b) and joins it to hosts on `agent_id` = `device_id` |

A run has three parts:

- **Download.** The connector issues a download link for the dump. You fetch it with `curl`.
- **Process locally.** `scripts/falcon_resource_report.py` reads the dump and writes `facts.json`, two CSVs, a Fluency-branded
  print-style HTML page and a self-contained interactive HTML file. It uses only the Python standard library.
- **Narrative.** You write the summary and next steps from `facts.json`.

A run makes one `list_resource_dumps` call plus one `get_resource_dump_url` call per dump. The dump data never passes through
the conversation.

`<skill-dir>` below means this skill's base directory.

## Inputs

- **Account.** The Fluency tenant account name. Use whichever Fluency MCP server exposes `list_resource_dumps` and
  `get_resource_dump_url` for it. If the account is unclear, run `list_accounts` and ask.
- **Customer name** (optional). Shown in the subtitle.

Work in a fresh directory, e.g. `./falcon_resources_<account>_<yyyymmdd>/`. The dump goes in
`<work>/dumps/falconAgent/<customer>.jsonl.gz`.

## Steps

### 1. Find the dump

Call `list_resource_dumps` with the account and `resource` set to `falconAgent`.

- **Not installed.** A tenant without Falcon answers `resource type not found`. Treat that as "no dump", not as a failure of
  the tool. Tell the user the tenant has no Falcon host import and stop.
- **Several integrations.** A resource with several customers (integrations) has one dump per customer. Fetch all of them.
  The script reads every file in the folder and keeps one row per device id.

### 2. Download

For each customer, call `get_resource_dump_url` with the account, resource, customer and `format: "jsonl"`. Download it
immediately:

```bash
mkdir -p <work>/dumps/falconAgent
curl -sSf -o "<work>/dumps/falconAgent/<customer>.jsonl.gz" "<url>"
```

Rules for this step:

- **Order.** Links expire after 15 minutes, so request one link, download it, then move on.
- **Don't read the dump.** Only the script opens it: no `zcat`, `head` or Read tool on it. It holds host names and last logged-in
  user names. Invoking this skill is the user's request to download it into the work directory.
- **Reuse.** If a matching dump is already in `<work>/dumps` from the same snapshot (`dayIndex` / `createdOn` in the listing),
  skip the download.
- **Large dumps.** A tenant with a few thousand hosts downloads in seconds (about 3 MB for 5,000 hosts). Only stop for size if
  the listing shows more than about 2 million records.
- **Blocked downloads.** A 403, or a refused proxy or CONNECT, means this environment's egress allowlist blocks the tenant host
  (`<account>.app.ingext.io`). Stop. Tell the user that host must be added to their organization's allowed domains, or that the
  skill can run from a local Claude Code session. Don't retry, and don't try to fetch the data any other way.

### 2b. Alert data (archive first)

Detections are read from the **archive of the scheduled report `CrowdStrike_Resource_Report`** (an FPL report, one UTC day per
run, 30-day alert window, daily 04:35 UTC; source in the Scripts repo, `fplProcessors/code/CrowdStrike_Resource_Report.js`).
Search only when there is no archive.

1. `list_report_archive(account, name="CrowdStrike_Resource_Report")`. If the report is listed with a completed day within the
   last 2 days, use the archive. State the day used. A missing last day is a gap: offer `backfill_report_archive`, never fill it
   by searching.
2. `download_report_archive(account, name="CrowdStrike_Resource_Report", from=<last day>, to=<last day>)` and save the result as
   `<work>/alerts_archive.json`. The script takes the latest completed day. The file holds detection counts and up to 500 host
   names with scores, and no user names.
3. Render with `--alerts-archive <work>/alerts_archive.json`.

What the archive carries: the fleet totals, severity by status, tactics, top 10 detection names, other alert products, the top 25
hosts with open detections, and per-host detection counts for every scored host. A host whose detections are all closed has a score
of 0 and is not listed per host, so its count is missing from `hosts.csv`; the fleet totals still include it.

**Fallback, only when the tenant has no `CrowdStrike_Resource_Report` archive (or the last archived day is more than 2 days old and
the user wants today's state).** Say so, then run the three queries below with `kql_search` on the tenant account. The epp and automated-lead rows the report uses
are a small part of the table (about 1,600 of 51,000 rows over three months on a 5,000-host tenant) and the queries aggregate, so a
30-day search is fine. `rangeFrom` is 30 days ago at 00:00 UTC (epoch
milliseconds), `rangeTo` is now. The `created_timestamp` filter keeps re-emitted alert updates from older alerts out of the window.
Render with the default `--alerts-days 30`. If `truncated` is true, shorten the window and pass the matching `--alerts-days`, and say so.

These are the same three queries the scheduled report runs (`GetAlertsByHost`, `GetAlertFacets`, `GetAlertOther` in the FPL source), so a
search and an archive give the same numbers. Save each result to a file:

`alerts_hosts.json`, one row per host:

```
FalconAlert | where product in ("epp","automated-lead") | where created_timestamp > ago(30d)
| extend open = iff(status in ("new","in_progress","reopened"), 1, 0), sev = iff(product == "automated-lead", "Lead", severity_name)
| summarize alerts = count(), openAlerts = countif(open == 1), highOpen = countif(open == 1 and sev in ("High", "Critical")),
            leadsOpen = countif(open == 1 and product == "automated-lead"), lastAlert = max(created_timestamp), topDetection = min(name) by agent_id
```

`alerts_facets.json`, one facet query (one result table per column; the blank tactic and detection rows belong to leads and are skipped):

```
FalconAlert | where product in ("epp","automated-lead") | where created_timestamp > ago(30d)
| extend severity = iff(product == "automated-lead", "Lead", severity_name), tacticName = iff(product == "epp", tactic, ""), detection = iff(product == "epp", name, "")
| facet by severity, status, tacticName, detection
```

`alerts_other.json`, the other alert products:

```
FalconAlert | where not(product in ("epp","automated-lead")) | where created_timestamp > ago(30d)
| summarize alerts = count(), hosts = dcount(agent_id), open = countif(status in ("new","in_progress","reopened")) by product, type
| sort by alerts desc
```

Unlike the archive, the search gives per-host detail (last alert, top detection) for every host with detections. If a result has
`truncated` true, say so rather than presenting a partial result. If the tenant has neither an archive nor a FalconAlert table, skip
this step: the report renders hosts only and says so under Data notes. The alert files hold host ids and detection names but no user names.

### 3. Health check

```bash
python3 <skill-dir>/scripts/falcon_resource_report.py check --dumps <work>/dumps
```

It prints the records, customers and snapshot hour, then the host totals. `PROBLEM` (exit code 1) is an empty dump or a
snapshot older than 48 hours. Stop and tell the user. Do not render a report from stale or empty data.

### 4. Render

```bash
python3 <skill-dir>/scripts/falcon_resource_report.py render --dumps <work>/dumps --work <work> \
  --account <account> --customer "<Customer>" \
  --alerts-archive <work>/alerts_archive.json
```

(With the search fallback use `--alerts-hosts <work>/alerts_hosts.json --alerts-facets <work>/alerts_facets.json --alerts-other <work>/alerts_other.json` instead; leave the alert flags out when there is no alert data.) This prints the totals and writes to `<work>`:

- `falcon_resource_report.html`, the print-style page for the PDF, with `assets/logo2.png` copied next to it;
- `falcon_resource_report_interactive.html`, the file to open in a browser (see below);
- `facts.json`: every number on the page and the default narrative;
- `hosts.csv`: every host with its score, state and reasons;
- `alerts.csv`: hosts with detections in the window, with open and high-severity counts and the most common detection;
- `policies.csv`: for each policy type, hosts assigned, not assigned and not applied.

`--max-listed N` caps the "Hosts needing attention" table in the print-style report (default 40). The CSV and the interactive
file always have every host.

**Interactive file.** One HTML file with no server and no internet needed. Tabs: Overview, Hosts, Detections, Policies and Coverage. The
Hosts table has search, sortable columns, 13 filters, paging and an Export CSV button that exports the filtered view. Tiles and
bars on the Overview open the matching table already filtered. It follows the browser's dark mode. Offer it for working through
the host list, and the PDF for a document to send.

**Personal data.** The interactive file and `hosts.csv` carry host names and each host's last logged-in user. Add `--no-actors`
to leave the user names out of both when the files will leave the tenant's owner.

### 5. Write the narrative

The default narrative is generic. Read `facts.json`, filter `hosts.csv` for specifics, then write `<work>/narrative.json`:

```json
{
  "summary": ["<p>HTML for paragraph 1 (may use <strong>)</p>", "<p>paragraph 2</p>"],
  "nextSteps": [
    {"when": "This week", "tone": "urgent", "text": "Restore full functionality on the 3 hosts in reduced functionality mode."},
    {"when": "Within 14 days", "tone": "normal", "text": "..."},
    {"when": "Quarterly", "tone": "routine", "text": "..."}
  ]
}
```

Run step 4 again; it picks up `narrative.json` automatically. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in the CSV. Compute it; don't estimate.
- **Summary.** Two paragraphs: the fleet and its check-in and sensor health, then the protection gaps and policy picture. Each
  is at most about 90 words.
- **Next steps.** At most 6, ordered by urgency. `when` is one of: This week, Within 14 days, Within 30 days, Quarterly. `tone`
  is `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client:
  - Use no internal terms (dump, FPL, connector).
  - Hedge causes the data cannot show. A silent host may be powered off, retired or renamed.
  - Containment is often deliberate. Say a host "is contained", not that it is compromised.

### 6. PDF and review

Open the interactive file in a browser (or Playwright) once. Every tab should render with no console error, and the Hosts
search, filters and sort should change the row count.

Print `falcon_resource_report.html` (not the interactive file) to PDF on A4 with 12 mm margins, background graphics on and no
scaling. With headless Chrome:

```bash
chromium --headless --no-pdf-header-footer --print-to-pdf=<work>/falcon_resource_report.pdf \
  file://<work>/falcon_resource_report.html
```

The report runs about five to six pages. If you can rasterise the pages, check that no labels are clipped and the KPI strip and
summary sit together on page 1.

### 7. Deliver

Give the interactive HTML, print-style HTML, PDF and the two CSV paths, plus two or three sentences: how many hosts are silent,
how many have a protection gap, and how many need action. Keep internal findings out of the PDF and put them in your reply.
Examples: duplicate host names, a snapshot that is several hours old, hosts with an empty provisioning status.

## What the report does not cover

- Alert triage and investigation: the report counts and ranks detections per host; use the Falcon console or the alert tools to work them. Identity (IdP), data-protection and cloud alerts are shown as fleet totals only and do not affect host scores.
- Windows end-of-support dates: use `endpoint-os-currency`.
- Comparing Falcon with Defender or SentinelOne: use `security-agent-deployment-status-report`.

`references/methodology.md` covers the scoring and the data pitfalls found in real dumps.
