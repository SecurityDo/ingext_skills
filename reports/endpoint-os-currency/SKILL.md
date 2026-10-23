---
name: endpoint-os-currency
version: 1.0.0
description: >-
  Produce an endpoint operating-system currency report for ONE Ingext/Fluency tenant: which OSes
  are running, which hosts are on an unsupported (end-of-support) Windows release, which are about
  to be, and which are on an older build than the rest of the fleet. Reads one resource dump
  through the tenant's MCP connector (CrowdStrike falconAgent, else sentinelOneAgent, else Entra
  office365Device), evaluates it locally, and renders a self-contained HTML, a PDF and a per-host
  CSV. USE THIS SKILL for "what OS versions do we have", "which machines are on an old Windows
  build", "are our endpoints up to date", "any end-of-life or unsupported OS", "old Windows 7 or
  Server 2012 boxes", "OS currency report". DO NOT use it for endpoint protection coverage gaps
  or for a single host (ingext-get-profile).
---

# Endpoint OS Currency & End-of-Support Report

Answers: what OSes are the endpoints on, which are past or near the end of vendor support, and
which lag the rest of the fleet on build. It is read-only and never changes the tenant.

Two separate axes, never merged:

1. **Support status.** The OS release's vendor support end date, from the curated Windows table in
   `scripts/build_report.py` (dated `TABLE_AS_OF`). The fix is an OS upgrade or replacement, not
   a patch. A fleet where every host runs Windows 7 shows as current on the second axis, so this
   axis must not be skipped.
2. **Build currency.** Behind the newest build seen in this fleet for the same OS line. The fix is
   to patch. "Newest" is the fleet maximum, not the vendor's latest.

## Data integrity (non-negotiable)

Every figure comes from the downloaded dump, computed by `scripts/build_report.py`. Never type a
number into the HTML. If the dump cannot be read or is empty, the script stops; do not report an
empty fleet as healthy. Hosts with no build number or an unlisted build show as "Unknown build",
never as supported.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. |
| Source | One of the three below. Do not combine sources: a host in two inventories would be counted twice. |

## Step 1 — Pick the source

Call `list_data_tables` for the tenant, then `list_resource_dumps` (a resource that is not
listed is absent). Use the first one present:

| Order | Resource | `--source` | What it carries |
|---|---|---|---|
| 1 | `falconAgent` | `falcon` | OS name, edition, full build and patch revision, server vs workstation, last seen |
| 2 | `sentinelOneAgent` | `sentinelone` | OS name and build number, no patch revision |
| 3 | `office365Device` | `office365` | OS and version only: no edition, no server/client, and it lists stale and personal devices; the weakest source |

If none is present, stop and say the tenant has no endpoint inventory to assess. Say which source
you used and why in the hand-off.

## Step 2 — Download the dump

`get_resource_dump_url` with `resource`, the `customer` from `list_resource_dumps`, and the
default `jsonl` format. Download the URL straight to disk with `curl -o WORKDIR/dump.jsonl.gz`
(it expires in 15 minutes; never read it into the conversation). Check that the file's line count
equals the `count` that `list_resource_dumps` reported; a mismatch is a truncated download.

## Step 3 — Build

```bash
python3 scripts/build_report.py --source falcon --dump WORKDIR/dump.jsonl.gz \
  --tenant acme --tenant-name "Example Corp" --site Develop \
  --out WORKDIR/report.html --csv WORKDIR/hosts.csv
```

`--as-of` defaults to today. `--stale-days` defaults to 30 for the EDR sources and 90 for Entra.

## Step 4 — Render and QA

```bash
node scripts/render-html-pdf.mjs --input WORKDIR/report.html --output WORKDIR/report.pdf \
  --title "Example Corp Endpoint OS Currency Report"
```

The renderer needs Playwright and a Chrome or Chromium binary. It looks for Chrome in the usual
macOS, Linux and Windows paths (override with `--chrome` or `CHROME_PATH`) and for Playwright in
the current folder, the input's folder and the global npm root.

QA before delivering: if `pdftoppm` exists, look at every page (footer on every page, no clipped
text, tables inside the page); otherwise check in print media that each table has
`scrollWidth <= clientWidth`. If you cannot look at the pages, say so in the hand-off.

## Reading the result

- **End of support:** the release no longer gets security updates. Act first; upgrade or replace.
- **Ending soon:** support ends within 180 days. Plan the upgrade.
- **Verify SKU/edition:** the build is shared by a client and a server release (14393, 17763,
  26100) and the source cannot tell which. Confirm before calling it unsupported.
- **Unknown build:** no build number, or a build not in the table. Not a pass.
- **Not assessed:** macOS at or above 14, Linux and mobile get inventory only. macOS below 14
  is flagged end of support.
- A host that was not seen recently may simply have missed updates; the report counts these as
  stale and the CSV marks them.

## Accuracy discipline

- Support dates are curated and dated. Verify them against Microsoft's lifecycle pages before
  quoting one to a customer. Extended Security Updates (ESU) and LTSC channels are not visible in
  this data; an LTSC host shows as "verify".
- Enterprise, Education and LTSC editions use the Enterprise/Education date; everything else uses
  the Home/Pro date. Windows 11 Pro on 24H2 reached the end of its updates on 13 Oct 2026, while
  Enterprise on the same build runs to 12 Oct 2027.
- A build newer than the table (for example a pre-release build) is treated as supported and as
  current, and is labelled as newer than the table, so it cannot set the fleet's "newest".
- Builds are compared only within one OS line.
- Only hosts in the chosen inventory appear. Machines without the sensor are not covered; absence
  is not coverage.

## Updating the table

When Microsoft publishes new dates or a new feature release, edit `CLIENT` and `SERVER` in
`scripts/build_report.py`, set `TABLE_AS_OF`, and rebuild `cowork/endpoint-os-currency.skill`.

## Delivering to the customer

Delivering or posting the report is a separate step that needs the operator's approval of the
HTML and PDF first. Do not post automatically. The CSV lists every host by name; share it only
where that is appropriate.
