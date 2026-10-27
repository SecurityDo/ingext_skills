---
name: mssp-ops-sitrep
version: 1.0.0
description: >-
  Generate an MSSP Operations SitRep (shift handoff) across the accounts of one Fluency / Ingext
  connector as a single HTML page: a summary, product posture for Office365, CrowdStrike Falcon and
  SentinelOne, and four lanes (SOC Manager, Administrator, Operator, Investigator) listing what needs
  doing now. USE THIS SKILL for "operations sitrep", "situation report", "SOC status", "shift
  handoff", "what needs to be done", "what is escalated or unworked across my customers". Reads each
  account's behavior summaries (tickets scored 3,000 or more) through the connector, plus the optional
  health-status-report and mssp-coverage-map results; computes every figure locally and shows what was
  not collected as "not collected". Read-only; stores nothing. DO NOT use it for one incident
  (incident-investigation) or a monthly customer report (CISO_monthly_report).
---

# MSSP Operations SitRep

> **Prerequisites (optional but recommended):** install `health-status-report` for the Administrator
> lane and product posture, and `mssp-coverage-map` for identity-versus-endpoint coverage. Without them
> those parts show "not collected".

A shift-handoff page for the people running a portfolio of tenants: what is in the queue, what is
escalated, what is broken, and what each lane should do next. It is read-only and keeps no state;
the companion app's investigation-gap ledger has no equivalent here.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names. Use its tools directly. |
| Accounts | `list_accounts`; default all accounts of the connector, or the ones the user names. |
| Window | Last N days (default 7). Use epoch milliseconds for `rangeFrom` and `rangeTo`. |

## Step 1 — Collect

Make a work folder **outside the repository** (results name real hosts, users and customers).

| File | Tool |
|---|---|
| `accounts.json` | `list_accounts` |
| `<account>/cases.json` | `behavior_summary_search(account, rangeFrom, rangeTo, searchStr="riskScore:[3000 TO *]", limit=100, sortField="to")`. If `total` exceeds 100, page with `offset` and merge the pages into one JSON array. Large results are saved by the harness; copy that file to the name |
| `<account>/health.json` | optional: health-status-report for the account (its evaluation step only) |
| `coverage.csv` | optional: mssp-coverage-map output for the same accounts |

Run the accounts in parallel. An account whose search fails is left out and shows as not collected.

## Step 2 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --out WORKDIR/sitrep.html \
  --json WORKDIR/sitrep.json --site Conekt --days 7 --as-of 2026-10-27T00:00:00Z
```

`--as-of` is the end of the window; it fixes ticket ages. The script prints the totals and warns when an
account reported more tickets than were saved.

## Reading it

- **Ticket:** a behavior summary scored 3,000 or more; smaller ones are not counted.
- **Unworked:** status `new` and no comment: the AI assistant has not run on it. Flagged when older than 24 hours.
- **Escalated:** status `new` after the AI assistant commented: needs an analyst. This is the Investigator's queue.
- **Age:** from `incidentDetectionTime`; a ticket without it has no age (no fallback).
- **Product posture:** installed application instances per product and how many are in error, attention
  or disabled, from `health.json`. Coverage buckets come from `coverage.csv`.

## Honesty rules

- Never type a number into the HTML. Missing evidence is "not collected", never zero or healthy.
- A quiet window is a true result: say so, do not pad it.
- State what the SitRep cannot see: log flow (unless health-status-report ran in full mode), Falcon and
  SentinelOne agent health, unresolved threats and mitigation issues.
- The output names customers, hosts and users. Keep it out of the repository and out of release notes.
- Posting or sending the SitRep needs the operator's approval of the HTML first.
