---
name: security-agent-deployment-status-report
version: 1.1.0
description: >-
  Build a client-ready security agent deployment status report (HTML + PDF + device CSV) for a
  Fluency / Ingext account from its resource dumps, processed locally in Python. No FPL report,
  processor or search queries are needed. Compares endpoint agent inventories (by default
  SentinelOne, Microsoft Defender for Endpoint and Entra ID) per device, and adds hosts that
  Horizon3.ai NodeZero pentests found on the network. Shows coverage, devices missing an agent,
  agents that stopped reporting, unidentified hosts and next steps. Runs with whatever inventories
  the account has: a missing one is left out and the report says so. Sources are set in
  sources.json, so adding an inventory (Intune, CrowdStrike, a network scanner) is a config change.
  Triggers: "agent deployment status for account X", "EDR coverage report", "which devices are
  missing SentinelOne / Defender", "deployment gap report". Do NOT use to run an existing FPL report
  (use fluency-report) or for a one-off datalake query (use ingext-kql).
---

# Security Agent Deployment Status

Produces the same report as the `Security_Deployment_Status` FPL report, without saving anything
in Fluency and without running searches. A run has three parts:

- **Download.** The connector issues a download link for each inventory's resource dump. A dump is
  the full snapshot behind each resource table. You fetch the links with `curl`.
- **Process locally.** `scripts/deployment_status.py` reads the dumps and applies the sources file,
  then writes `facts.json`, `devices.csv` and a Fluency-branded HTML page. It uses only the Python
  standard library.
- **Narrative.** You write the summary and next steps from `facts.json`.

A run makes one `list_resource_dumps` call plus one `get_resource_dump_url` call per dump. The dump
data never passes through the conversation.

**Partial data is normal.** Not every account has every inventory connected. The script leaves out
any source whose dump is missing, unreadable, empty or unusable, prints why, and builds the report
from the sources that remain. The report names what it left out. Never stop a run because an
inventory is missing, and never invent data for it.

`<skill-dir>` below means this skill's base directory.

## Inputs

- **Account.** The Fluency tenant account name. Use whichever Fluency MCP server exposes
  `list_resource_dumps` and `get_resource_dump_url` for it. If the account is unclear, run
  `list_accounts` and ask. The account's `displayName` there is a good default customer name.
- **Customer name** (optional). Shown in the subtitle.
- **Sources.** By default, `<skill-dir>/sources.json`. Don't edit the bundled file for a one-off run:
  copy it into the work directory and edit the copy.

Work in a fresh directory, e.g. `./deployment_status_<account>_<yyyymmdd>/`. Dumps go in
`<work>/dumps/<resource>/<customer>.jsonl.gz`.

## Default sources

| source | resource | role |
|---|---|---|
| SentinelOne | `sentinelOneAgent` | required agent |
| Defender | `msDefenderMachine` | required agent |
| Entra ID | `office365Device` | reference inventory; its device ID lines up renamed machines |
| Horizon3 | `horizon3Host` | reference, **discovery**: hosts NodeZero internal pentests found on the network |

Horizon3 needs only `horizon3Host`. Its weaknesses, pentests and action logs are not used.

## Steps

### 1. Find the dumps

Call `list_resource_dumps` with the account. For each source's `resource`:

- Note every entry. A resource with several integrations (customers) has one dump per customer.
  Download all of them, except a dump whose `dayIndex` is more than 48 hours older than the newest
  dump of the same resource. That one comes from a replaced or removed integration, and the script
  would leave it out anyway.
- A source with no dump at all is simply not downloaded. Note it for your reply. This applies to a
  required source too. The script leaves it out and the report says it wasn't available.

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
- **A failed download** (a non-zero `curl` exit, or a 404) for one dump: retry once with a fresh
  link, then carry on without it.
- **Blocked downloads.** A 403, or a refused proxy or CONNECT, means this environment's egress
  allowlist blocks the tenant host (`<account>.app.ingext.io`). Stop. Tell the user that host must
  be added to their organization's allowed domains, or that the skill can run from a local Claude
  Code session. Don't retry, and don't try to fetch the data any other way.

### 3. Health check

```bash
python3 <skill-dir>/scripts/deployment_status.py check --dumps <work>/dumps --sources <sources file>
```

The output shows, per source:
- its status: `ok`, `warning`, or `left out`;
- records, records in scope, records active, and distinct hosts;
- the snapshot hour and the dumps it read.

A source is **left out** (a `LEFT OUT` line) when:
- no dump was downloaded;
- no dump could be read;
- the dump is empty;
- nothing is in scope after filtering;
- nothing was seen within its `staleDays`;
- the host field is empty on every record.

These are data problems, not missing agents, so the script never counts them against devices. A
**warning** keeps the source and should be mentioned in your reply. Examples:
- a snapshot older than 48 hours;
- a superseded or unreadable dump left out;
- skipped lines.

The last line says what the report covers. If no required source is usable, the report still
renders but only lists the inventories; it does not assess agent coverage. Tell the user.

### 4. Render

```bash
python3 <skill-dir>/scripts/deployment_status.py render --dumps <work>/dumps --work <work> \
  --sources <sources file> --account <account> --customer "<Customer>"
```

This prints the health table, totals, issue counts, how the discovery hosts were matched, and the
sources it left out. It always writes:
- `<work>/facts.json`: every number on the page, the source health, the sources left out
  (`unavailableSources`), the discovery breakdown and the default narrative;
- `<work>/devices.csv`: every device with its status, per-source state and last-seen time, IPs,
  other names seen and weakness counts;
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

Run step 4 again; it picks up `narrative.json` automatically. A malformed file is reported and the
default narrative is kept. Rules:

- **Numbers.** Every number comes from `facts.json` or from counting rows in `devices.csv`. Compute
  it; don't estimate.
- **Summary.** Two paragraphs: the coverage, then where the gaps are. Each is at most about 90 words.
- **Next steps.** At most 6, ordered by urgency. Together they should account for every device in
  the attention list.
  - `when` is one of: This week, Within 14 days, Within 30 days, Quarterly.
  - `tone` sets the colour: `urgent` (red), `normal` (blue) or `routine` (navy).
- **Audience.** This page goes to the client:
  - Use no internal terms (dump, FPL, connector, integration).
  - Hedge causes the data can't show, e.g. "some may be renamed or spare machines".
- **Reference hint.** `listedNotInReference` counts the gap devices that are absent from a
  reference inventory such as Entra ID. These are often unmanaged or off-domain machines, which is a
  useful hint for the steps.
- **Discovery (Horizon3).** `facts.discovery` breaks down the hosts NodeZero found:
  - `byStatus` shows how many run the agents, could run one but have none, are unidentified, or are
    network devices;
  - `notInInventories` counts hosts that appear in no other inventory;
  - `attentionWithWeaknesses` / `attentionWithConfirmed` count gap devices with NodeZero weaknesses.

  Gaps with confirmed weaknesses, domain controllers, hypervisors and backup servers come first.
  Hedge what the data can't prove:
  - a host listed only by IP address may be a second network interface of a server that already
    has an agent;
  - the device class comes from the OS string, and NodeZero often reports just "Microsoft Windows";
  - a name in "names seen" is what NodeZero reported, not a verified hostname.
- **Unidentified hosts** (no OS detected) and **network devices** (firewalls, switches, power
  units) are outside the percentages. Ask the client to identify the former. Don't call the latter
  gaps.

### 6. PDF and review

Render the PDF with `node <fluency-report>/scripts/render_pdf.mjs --input <report.html> --output <report.pdf>`.
It produces US Letter with the same CSS as the HTML, so the two match. If Playwright is missing, run
`npm install playwright-core` in a scratch directory and run the command from there; it finds an
installed Chrome by itself. If that is not possible, deliver the HTML.

Layout:
- The first pages hold the KPIs, summary, panels, next steps and the discovery panel.
- The method and device list start on a new page.

If you can rasterise the pages, look at them before handing over:
- no clipped labels;
- no next steps cut off.

### 7. Deliver

Give the HTML, PDF and `devices.csv` paths, plus two or three sentences:
- the compliance %;
- the largest gap;
- anything from step 3, above all every source that was left out.

Keep internal findings out of the PDF and put them in your reply instead. Examples:
- why a source was left out (an integration with no inventory, a superseded integration, an old
  snapshot);
- duplicate agent records.

The report itself only says that an inventory was not available.

## Changing what the report covers

Each of these is an edit to the sources file:
- adding a source, including a network scanner as a discovery source;
- changing a scope filter;
- marking a source required or reference-only;
- changing `staleDays`, globally or per source.

`references/adding_sources.md` covers the fields and the filter syntax. It also explains how to
explore a new dump with the `fields` command. `references/methodology.md` covers:
- the matching and status rules, including IP matching for discovery sources;
- how dumps are read and when a source is left out;
- known data pitfalls in the default sources.

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own
copy: the build scripts here that style a report find the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and
import `fluency_brand` from it, and stop with a clear message if it is not installed. Install `fluency-report` alongside this skill. In the steps below, `<fluency-report>` means
that skill's folder.

- The HTML report is one self-contained file (mark, fonts and CSS inlined). The PDF is rendered from that same HTML with the same
  CSS, so the two match: `node <fluency-report>/scripts/render_pdf.mjs --input report.html --output report.pdf`.
  US Letter, same editorial styling as the HTML (brandline, closing footer line; no paged footer). It needs Playwright
  (`npm install playwright`) and a Chromium or Chrome binary; it finds a Chrome install automatically.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore
  the brand CSS (grid, fonts, page rules), so the PDF would not match the HTML.
- Do not hand-write report styling. The look is the Fluency editorial style (white paper, IBM Plex, black rules, one blue / red / amber, no cards or gradients). A new page is `fluency_brand.page(...)`; markup from an older script goes
  through `fluency_brand.apply_brand(html)`. Design and component reference: the `fluency-report` skill (`references/widget_recipes.md`).
