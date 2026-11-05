---
name: mssp-coverage-map
version: 1.0.0
description: >-
  Build a fleet-wide IDENTITY-versus-ENDPOINT coverage map across the tenants a provider can act on:
  for each customer, licensed Microsoft 365 seats against the endpoints and users that its EDR
  dumps show (CrowdStrike Falcon, SentinelOne, Microsoft Defender), with the gap flagged and tenants
  sorted into EDR under-coverage, aligned, identity-blind, endpoint-blind and not assessable.
  USE THIS SKILL for "which customers have EDR coverage gaps", "fleet coverage map", "identity vs
  endpoint across all tenants", "which tenants have users without endpoints", "where is
  CrowdStrike (or SentinelOne) under-deployed", "rank my customers by coverage gap". Reads one
  list_resource_dumps per account and downloads the office365User and EDR dumps of the accounts
  that have them, computes every figure locally and writes an HTML map and a CSV. Read-only. DO NOT
  use it for one tenant's endpoint operating systems (endpoint-os-currency) or its agent
  deployment status (security-agent-deployment-status-report).
---

# Identity versus endpoint coverage map (fleet view)

Gives a provider the portfolio view of **which customers' endpoint protection actually covers their
people.** For every tenant it compares the licensed Microsoft 365 population with the endpoints and
users in its EDR dumps, flags the gap, and ranks customers so the provider knows where to push agent
deployment, or where identity data is missing. It is read-only and never changes a tenant.

## What it uses

| Side | Dump (`list_resource_dumps` resource) | Counted as |
|---|---|---|
| Identity | `office365User` | **licensed seat**: an enabled Member account with at least one assigned license (not the raw user count, which includes guests, disabled and unlicensed accounts) |
| Endpoint | `falconAgent` | every record is a host; the `last_login_user` is the host's user |
| Endpoint | `sentinelOneAgent` | hosts that are not decommissioned or uninstalled; `lastLoggedInUserName` is the user |
| Endpoint | `msDefenderMachine` | hosts whose `onboardingStatus` is `Onboarded`; no user field |

EDR users are the distinct last-login users, lower-cased with any `DOMAIN\` prefix and `@domain` suffix
removed, joined across Falcon and SentinelOne. **gap = licensed seats minus EDR users.**

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names (for example Develop). |
| Scope | Every account from `list_accounts`, or a subset the user names. State exactly which accounts were and were not assessed; never imply fleet-wide coverage from a sample. |

## Step 1 — Roster and what each tenant has

1. `list_accounts` for the roster. Save it as `WORKDIR/accounts.json` and confirm the count to the user. For
   a subset, save only those accounts.
2. For each account call `list_resource_dumps(account)` and save the result as
   `WORKDIR/<account>/resources.json`. It lists each resource, its customer, record count and dump time, and
   decides what to download. Run these in parallel.
3. `python3 scripts/plan_downloads.py --evidence-dir WORKDIR` prints the dumps to fetch and tells which
   accounts have nothing (neither identity nor EDR).

Tell the user the sizes before downloading: how many tenants have both sides, only identity, only EDR or
neither. Offer to scope to a subset (for example only the tenants with both) when the fleet is large.

## Step 2 — Download the dumps

For each line `plan_downloads.py` printed, call `get_resource_dump_url(account, resource, customer)` and
download the link straight to disk, never into the conversation (the link expires in 15 minutes):

```bash
curl -sf -o WORKDIR/<account>/<file> "<url>"
```

The file names matter: `users*`, `falcon*`, `sentinelone*` and `defender*` are summed per account, which
handles an account with more than one customer for a resource. Run the downloads in parallel. A dump
is a gzipped snapshot; the largest (a tenant with tens of thousands of users) is tens of megabytes
compressed. The script compares each file's record count with `list_resource_dumps` and warns on a mismatch.

## Step 3 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --out WORKDIR/coverage.html --csv WORKDIR/coverage.csv --site Develop
```

An account whose resources.json lists a dump that was not downloaded is shown as not collected, never as
zero.

## Reading the result

Each tenant lands in one bucket and, where it has both sides, one pattern:

| Result | Meaning |
|---|---|
| **EDR under-coverage** | seats exceed EDR users by more than 10% of the seats: licensed people without a managed endpoint. Ranked by gap |
| **Aligned** | EDR users within 10% of the seats |
| **EDR users exceed seats** | more EDR users than seats by over 10%: shared or service logins, stale agents or another license model |
| **Identity blind** | EDR dumps but no Microsoft 365 user dump: endpoints with no owners |
| **Endpoint blind** | a user dump but no EDR dump: the tenant may use an EDR that is not collected |
| **Identity and Defender only** | hosts exist but Defender has no user, so no gap can be computed |
| **Not assessable** | neither side |

The 10% thresholds are constants in the script. Lead with the work queue: the largest gaps and what share of
the seats they are.

## Honesty rules

- **The gap is directional, not exact.** The EDR user is the last login: shared machines undercount, users
  with several hosts overcount, and service accounts add users that are not seats.
- **A clean row is not full coverage.** Only managed endpoints appear; the point is the people and machines
  that do not.
- Say which seat definition was used (licensed Members, not raw users).
- The figures are snapshots as of each dump's time, not a period. A dump more than two days old is named.
- Only Falcon, SentinelOne and Defender are read. A tenant with another EDR or identity provider shows as
  blind on that side; say so rather than calling it uncovered.
- Never add tenant names to the skill, a note or a commit. The report names customers because it is the
  provider's own deliverable, so keep it out of the repository.

## Delivering

Sending or posting the report needs the operator's approval of the HTML first. Do not post automatically.

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
