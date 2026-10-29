---
name: security-agent-deployment-status-report
version: 1.0.1
description: >-
  Build a client-ready security agent deployment status report (HTML + A4 PDF + device CSV) for
  a Fluency / Ingext account from its resource dumps, processed locally in Python. No FPL report,
  processor or search queries are needed. Compares endpoint agent inventories (by default
  SentinelOne, Microsoft Defender for Endpoint and Entra ID) per device and shows coverage, devices
  missing an agent, agents that stopped reporting, and next steps. Sources are set in
  sources.json, so adding an inventory (Intune, CrowdStrike, ...) is a config change. Triggers:
  "agent deployment status for account X", "EDR coverage report", "which devices are missing
  SentinelOne / Defender", "deployment gap report for the Fluency account". Do NOT use to run an
  existing FPL report (use fluency-report) or for a one-off datalake query (use ingext-kql).
---

# Security Agent Deployment Status

Produces the same report as the `Security_Deployment_Status` FPL report, without saving anything
in Fluency and without running searches. A run has three parts:

- **Download.** The connector issues a download link for each inventory's resource dump. A dump is
  the full hourly snapshot behind each resource table. You fetch the links with `curl`.
- **Process locally.** `scripts/deployment_status.py` reads the dumps and applies the sources file,
  then writes `facts.json`, `devices.csv` and a Fluency-branded HTML page. It uses only the Python
  standard library.
- **Narrative.** You write the summary and next steps from `facts.json`.

A run makes one `list_resource_dumps` call plus one `get_resource_dump_url` call per dump. The dump
data never passes through the conversation.

`<skill-dir>` below means this skill's base directory.

## Inputs

- **Account.** The Fluency tenant account name. Use whichever Fluency MCP server exposes
  `list_resource_dumps` and `get_resource_dump_url` for it. If the account is unclear, run
  `list_accounts` and ask.
- **Customer name** (optional). Shown in the subtitle.
- **Sources.** By default, `<skill-dir>/sources.json`. Don't edit the bundled file for a one-off run:
  copy it into the work directory and edit the copy.

Work in a fresh directory, e.g. `./deployment_status_<account>_<yyyymmdd>/`. Dumps go in
`<work>/dumps/<resource>/<customer>.jsonl.gz`.

## Steps

### 1. Find the dumps

Call `list_resource_dumps` with the account. For each source's `resource`:

- Note every entry. A resource with several integrations (customers) has one dump per customer, and
  you need all of them.
- If a **reference** source (`"required": false`) has no dump, drop it from your copy and mention it
  in your reply.
- If a **required** source has no dump, stop and ask the user. Otherwise the report would show every
  device as missing that agent.

### 2. Download

For each (resource, customer) pair, call `get_resource_dump_url` with the account, resource,
customer and `format: "jsonl"`. Then download it immediately:

```bash
mkdir -p <work>/dumps/<resource>
curl -sSf -o "<work>/dumps/<resource>/<customer>.jsonl.gz" "<url>"
```

Rules for this step:

- **Order.** Links expire after 15 minutes, so request one link, download it, then move on to the
  next.
- **Don't read the dumps.** Only the script opens them: no `zcat`, `head` or Read tool on a dump.
  Invoking this skill is the user's request to download the dumps into the work directory.
- **Reuse.** If a matching dump is already in `<work>/dumps` from the same snapshot (`dayIndex` /
  `createdOn` in the listing), skip the download.
- **Blocked downloads.** A 403, or a refused proxy or CONNECT, means this environment's egress
  allowlist blocks the tenant host (`<account>.app.ingext.io`). Stop. Tell the user that host must
  be added to their organization's allowed domains, or that the skill can run from a local Claude
  Code session. Don't retry, and don't try to fetch the data any other way.

### 3. Health check

```bash
python3 <skill-dir>/scripts/deployment_status.py check --dumps <work>/dumps --sources <sources file>
```

The output shows, per source:
- records, records in scope, records active, and distinct hosts;
- the snapshot hour and the dumps it read.

A `PROBLEM` line on a required source (exit code 1) means a data problem, not missing agents. Typical
causes:
- an empty dump;
- nothing in scope after filtering;
- nothing seen within `staleDays`;
- an empty host field;
- a snapshot more than 48 hours old.

Stop and tell the user. A `warning` on a reference source can go ahead, but mention it.

### 4. Render

```bash
python3 <skill-dir>/scripts/deployment_status.py render --dumps <work>/dumps --work <work> \
  --sources <sources file> --account <account> --customer "<Customer>"
```

This prints the health table, totals and issue counts. It writes:
- `<work>/facts.json`: every number on the page, the source health and the default narrative;
- `<work>/devices.csv`: every device with its status and per-source state and last-seen time;
- `<work>/security_deployment_status.html`, with `assets/logo2.png` copied next to it.

The report lists every device that needs attention. For a very long list, `--max-listed N` caps it
in the report; `devices.csv` always has every device.

### 5. Write the narrative

The default narrative is generic. Read `facts.json`, filter `devices.csv` for specifics, then write
`<work>/narrative.json`:

```json
{
  "summary": ["<p> HTML for paragraph 1 (may use <strong>)", "paragraph 2"],
  "nextSteps": [
    {"when": "This week", "tone": "urgent", "text": "Install SentinelOne on the 11 servers that run Defender only."},
    {"when": "Within 14 days", "tone": "normal", "text": "..."},
    {"when": "Quarterly", "tone": "routine", "text": "..."}
  ]
}
```

Run step 4 again; it picks up `narrative.json` automatically. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in `devices.csv`. Compute
  it; don't estimate.
- **Summary.** Two paragraphs: the coverage, then where the gaps are. Each is at most about 90 words.
- **Next steps.** At most 6, ordered by urgency.
  - `when` is one of: This week, Within 14 days, Within 30 days, Quarterly.
  - `tone` sets the colour: `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client:
  - Use no internal terms (dump, FPL, connector).
  - Hedge causes the data can't show, e.g. "some may be renamed or spare machines".
- **Reference hint.** `listedNotInReference` counts the gap devices that are absent from a
  reference inventory such as Entra ID. These are often unmanaged or off-domain machines, which is a
  useful hint for the steps.

### 6. PDF and review

For PDF output, use the browser's "Save as PDF" with A4 paper, 12 mm margins, background graphics
enabled and no scaling. If browser printing is unavailable, deliver the HTML with these print
settings for the user.

Page 1 holds the KPIs, summary, panels and next steps. Page 2 onwards holds the method and the device
list. If you can rasterise the pages, look at them before handing over:
- no clipped labels;
- page 1 ends with the next steps.

### 7. Deliver

Give the HTML, PDF and `devices.csv` paths, plus two or three sentences:
- the compliance %;
- the largest gap;
- anything from step 3.

Keep internal findings out of the PDF and put them in your reply instead. Examples: a stale
integration, a dropped source, duplicate agent records.

## Changing what the report covers

Each of these is an edit to the sources file:
- adding a source;
- changing a scope filter;
- marking a source required or reference-only;
- changing `staleDays`.

`references/adding_sources.md` covers the fields and the filter syntax. It also explains how to
explore a new dump with the `fields` command. `references/methodology.md` covers:
- the matching and status rules;
- how dumps are read;
- known data pitfalls in the default sources.
