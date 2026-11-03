---
name: sentinelone-resource-report
version: 1.0.0
description: >-
  Produce a SentinelOne resource report for ONE Ingext/Fluency tenant as HTML (print-style and interactive), PDF and CSVs, combining the three
  SentinelOne resource dumps in one page: agents (reporting status, agent versions, operating systems, protection
  mode), applications (installed software, risk levels, publishers, risky applications) and threats (history,
  classification, open threats, trend). The three are joined per endpoint to rank which endpoints need action.
  Processed locally in Python from resource dumps; no searches or saved reports are needed. USE THIS SKILL for
  "SentinelOne resource report", "SentinelOne inventory", "SentinelOne agent, application and threat summary for
  tenant X", "which SentinelOne endpoints are not reporting or need attention". DO NOT use it for agent coverage
  against other products (security-agent-deployment-status-report), OS support dates (endpoint-os-currency) or a
  single host (ingext-get-profile).
---

# SentinelOne Resource Report

One report for the three SentinelOne resource types a tenant imports:

| Resource | What it holds |
|---|---|
| `sentinelOneAgent` | One record per managed endpoint: version, OS, reporting state, protection mode, scan state |
| `sentinelOneApplication` | One record per application installed on an endpoint, with a risk level |
| `sentinelOneThreat` | One record per detected threat, with classification, verdict and mitigation |

The script joins applications and threats to agents on the agent UUID, so the report can say which endpoints
carry the risk, not only how much risk there is.

A run has three parts:

- **Download.** The connector issues a download link for each dump. You fetch the links with `curl`.
- **Process locally.** `scripts/s1_resource_report.py` reads the dumps and writes `facts.json`, three CSVs, a
  Fluency-branded print-style HTML page and a self-contained interactive HTML file. It uses only the Python
  standard library.
- **Narrative.** You write the summary and next steps from `facts.json`.

A run makes one `list_resource_dumps` call per resource plus one `get_resource_dump_url` call per dump. The dump data
never passes through the conversation.

`<skill-dir>` below means this skill's base directory.

## Inputs

- **Account.** The Fluency tenant account name. Use whichever Fluency MCP server exposes `list_resource_dumps` and
  `get_resource_dump_url` for it. If the account is unclear, run `list_accounts` and ask.
- **Customer name** (optional). Shown in the subtitle.

Work in a fresh directory, e.g. `./sentinelone_resources_<account>_<yyyymmdd>/`. Dumps go in
`<work>/dumps/<resource>/<customer>.jsonl.gz`, using the exact resource names above.

## Steps

### 1. Find the dumps

Call `list_resource_dumps` with the account and `resource` set to each of the three names, one call each.

- **Not installed.** A tenant without SentinelOne answers `resource type not found` for the resource. Treat that as
  "no dump", not as a failure of the tool.
- **No agent dump.** Stop and tell the user the tenant has no SentinelOne resource import. The report has nothing to
  anchor to. Applications and threats alone are not enough.
- **No application or threat dump.** Carry on. The report leaves that section out and says so in your reply.
- **Several integrations.** A resource with several customers (integrations) has one dump per customer. Fetch all of
  them. The script reads every file in the resource folder.

### 2. Download

For each (resource, customer) pair, call `get_resource_dump_url` with the account, resource, customer and
`format: "jsonl"`. Then download it immediately:

```bash
mkdir -p <work>/dumps/<resource>
curl -sSf -o "<work>/dumps/<resource>/<customer>.jsonl.gz" "<url>"
```

Rules for this step:

- **Order.** Links expire after 15 minutes, so request one link, download it, then move on.
- **Don't read the dumps.** Only the script opens them: no `zcat`, `head` or Read tool on a dump. They hold hostnames,
  user names and file paths. Invoking this skill is the user's request to download them into the work directory.
- **Reuse.** If a matching dump is already in `<work>/dumps` from the same snapshot (`dayIndex` / `createdOn` in the
  listing), skip the download.
- **Large dumps.** A tenant with tens of thousands of application records still downloads in seconds. Only stop for
  size if the listing shows more than about 5 million records in one dump.
- **Blocked downloads.** A 403, or a refused proxy or CONNECT, means this environment's egress allowlist blocks the
  tenant host (`<account>.app.ingext.io`). Stop. Tell the user that host must be added to their organization's
  allowed domains, or that the skill can run from a local Claude Code session. Don't retry, and don't try to fetch
  the data any other way.

### 3. Health check

```bash
python3 <skill-dir>/scripts/s1_resource_report.py check --dumps <work>/dumps
```

It prints one line per resource with the records, customers and snapshot hour, then the agent totals.

- `PROBLEM` on the agent line (exit code 1) is an empty dump or a snapshot older than 48 hours. Stop and tell the
  user. Do not render a report from stale or empty agent data.
- `warning` on applications or threats means that section will be left out or is stale. Carry on and mention it.

### 4. Render

```bash
python3 <skill-dir>/scripts/s1_resource_report.py render --dumps <work>/dumps --work <work> \
  --account <account> --customer "<Customer>"
```

This prints the totals and writes to `<work>`:

- `sentinelone_resource_report.html`, the print-style page for the PDF, with `assets/logo2.png` copied next to it;
- `sentinelone_resource_report_interactive.html`, the file to open in a browser (see below);
- `facts.json`: every number on the page and the default narrative;
- `endpoints.csv`: every endpoint with its score, status and reasons;
- `applications.csv`: every distinct application with publisher, risk, installs, endpoints and versions;
- `threats.csv`: every threat, newest first.

`--max-listed N` caps the "Endpoints needing attention" table in the print-style report (default 40). The CSV and the
interactive file always have every endpoint.

**Interactive file.** One HTML file with no server and no internet needed. Tabs: Overview, Endpoints, Applications,
Threats and Coverage. Every table has search, sortable columns, filters, paging and an Export CSV button that
exports the filtered view. Tiles and bars on the Overview open the matching table already filtered. It follows the
browser's dark mode. Offer it for working through the endpoint, application and threat lists, and the PDF for a
document to send.

**Personal data.** The interactive file and `endpoints.csv` carry endpoint names and each endpoint's last logged-in
user. Add `--no-actors` to leave the user names out of both when the files will leave the tenant's owner.

### 5. Write the narrative

The default narrative is generic. Read `facts.json`, filter the CSVs for specifics, then write
`<work>/narrative.json`:

```json
{
  "summary": ["<p>HTML for paragraph 1 (may use <strong>)</p>", "<p>paragraph 2</p>"],
  "nextSteps": [
    {"when": "This week", "tone": "urgent", "text": "Confirm the 4 unmitigated threats on FT-22-DISPATCH2 and REM-MART-1."},
    {"when": "Within 14 days", "tone": "normal", "text": "..."},
    {"when": "Quarterly", "tone": "routine", "text": "..."}
  ]
}
```

Run step 4 again; it picks up `narrative.json` automatically. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in the CSVs. Compute it; don't estimate.
- **Summary.** Two paragraphs: the fleet and its reporting health, then the threat and application picture. Each is at
  most about 90 words.
- **Next steps.** At most 6, ordered by urgency. `when` is one of: This week, Within 14 days, Within 30 days,
  Quarterly. `tone` is `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client:
  - Use no internal terms (dump, FPL, connector).
  - Hedge causes the data cannot show. A silent endpoint may be powered off, retired or renamed.
  - Say "open threat" only as defined on the page: not mitigated, or the incident is not resolved.

### 6. PDF and review

Open the interactive file in a browser (or Playwright) once. Every tab should render with no console error, and the
Endpoints search, filters and sort should change the row count.

Print `sentinelone_resource_report.html` (not the interactive file) to PDF on A4 with 12 mm margins, background graphics on and no scaling. With headless Chrome:

```bash
chromium --headless --no-pdf-header-footer --print-to-pdf=<work>/sentinelone_resource_report.pdf \
  file://<work>/sentinelone_resource_report.html
```

The report runs about six to seven pages. If you can rasterise the pages, check that:
- no labels are clipped;
- the KPI strip and summary sit together on page 1.

### 7. Deliver

Give the interactive HTML, print-style HTML, PDF and the three CSV paths, plus two or three sentences: how many endpoints are not reporting, how
many threats are open, and the biggest application risk. Keep internal findings out of the PDF and put them in your
reply. Examples: a duplicate host name, a threat history that names endpoints no longer in the agent list, a snapshot
that is several hours old.

## What the report does not cover

- Windows end-of-support dates: use `endpoint-os-currency`.
- Comparing SentinelOne with Defender or Entra: use `security-agent-deployment-status-report`.
- Live detections and alerts as they happen: use the SentinelOne alert investigation tools.

`references/methodology.md` covers the join, the scoring and the data pitfalls found in real dumps.
