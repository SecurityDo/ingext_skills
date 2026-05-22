---
name: ingext-health-monitor
description: Check the health of an Ingext / Fluency site and produce a clear status report. Trigger whenever the user asks about site health, whether data is flowing, if Ingext is working, if the site is healthy, whether ingestion is active, or any phrasing like "check the health", "is data coming in?", "is the site healthy?", "run a health check", "monitor site health", "check Ingext status", "is ingestion working?". Always use this skill for any question about whether the Ingext platform is ingesting data correctly or whether users are logging in — even if the user doesn't say "health check" explicitly.
---

# Ingext Site Health Monitor

Assess whether an Ingext site is healthy by running up to two diagnostic checks and reporting a clear pass/fail status for each.

## When to use

Trigger whenever the user asks about site health, data ingestion status, or whether the platform is working — e.g.:

- "Check the health of the site"
- "Is data flowing into Ingext?"
- "Run a health check"
- "Is the site healthy?"
- "Is ingestion working?"
- "What's the status of our Ingext instance?"

## Overview

A site is considered **healthy** when it has active non-internal user logins **or** is actively ingesting data. The skill runs two independent checks and aggregates them into a single status report (HTML).

## Step 1 — Check for a list_accounts tool

Look through the tools available in your current session for anything matching `list_accounts` (exact or near match — e.g. `list_accounts`, `get_accounts`, `listAccounts`).

- **Found**: Call it to get the list of all accounts. Present the accounts in the report's summary section and note that account enumeration succeeded. Skip to Step 4 (since listing accounts is itself a positive health signal).
- **Not found** (the common case today): Proceed to Step 2. Do not mention this to the user — just move on quietly.

## Step 2 — Login activity check (audit_search)

This check answers: *Are real (non-internal) users logging in?*

**Call `audit_search`** with:
- `query`: `"action:login"`
- `rangeFrom`: epoch milliseconds for 7 days ago (now − 7 × 86400 × 1000)
- `rangeTo`: epoch milliseconds for now
- `limit`: 100

**Evaluate the result:**

Scan the returned events. First filter to **successful logins only** — an event is successful if it has **no `error` field** (or `error` is null/absent). Discard any event where `error` is present and non-null, as these are failed login attempts.

From the successful logins, classify each by the `email` field (or `username` if `email` is absent) as **internal** or **external**. The following are all considered internal domains:
- `@fluencysecurity.com`
- `@ingext.io`
- `@security.do`

Any email not ending in one of those three domains is **external**.

Count all groups:
- `successful_count` — events with no error field
- `failed_count` — events with an error field (track but don't use for pass/fail)
- `internal_count` — successful logins from internal domains
- `external_count` — successful logins from all other domains

Determine the result:
- If `external_count > 0` → **LOGIN CHECK: PASS** — real external users are actively logging in.
- If `external_count == 0` and `internal_count > 0` → **LOGIN CHECK: FAIL** — successful logins exist but only internal users.
- If `successful_count == 0` → **LOGIN CHECK: FAIL** — no successful logins at all.

Save: `total_count`, `successful_count`, `failed_count`, `internal_count`, `external_count`, and a sample of up to 3 external email addresses (redacted to `u***@domain.com` for display) to use in the report.

## Step 3 — Data ingress check (run_report)

This check answers: *Is data flowing into the platform?*

**Call `run_report`** with:
- `name`: `"System_DataIngress"`
- `syncMode`: `true`
- `arguments`:
  - `{ "name": "from", "value": "-7d@m" }`
  - `{ "name": "to",   "value": "@m" }`

**Evaluate the result:**

The report returns `objects[]`. Find the object whose data represents the ingress volume (look for a numeric column like `count`, `total`, `events`, `value`, or similar). Sum all numeric values across all rows.

- If the sum is **> 0** → **INGRESS CHECK: PASS** — data is flowing.
- If the sum is **0** or the report returns no rows / no numeric data → **INGRESS CHECK: FAIL** — no data ingested in the last 7 days.

If `run_report` returns an error or the report `System_DataIngress` doesn't exist in the catalog (verify with `list_reports` if needed), mark this check as **UNKNOWN** rather than FAIL, and note the error in the report.

Save: the total ingress count and the report's data shape for the report.

## Step 4 — Determine overall health

| Login Check | Ingress Check | Overall |
|-------------|---------------|---------|
| PASS        | PASS          | ✅ HEALTHY |
| PASS        | FAIL/UNKNOWN  | ⚠️ DEGRADED — logins active but ingestion may be down |
| FAIL        | PASS          | ⚠️ DEGRADED — data flowing but no external logins detected |
| FAIL        | FAIL          | ❌ UNHEALTHY |
| FAIL        | UNKNOWN       | ⚠️ UNCERTAIN — could not fully assess |
| UNKNOWN     | PASS          | ⚠️ DEGRADED |
| UNKNOWN     | UNKNOWN       | ⚠️ UNCERTAIN |

## Step 5 — Write the HTML report

Produce a self-contained single-file HTML report and save it to the output directory as `ingext_health_<YYYYMMDD>.html`.

**Time period:** Before writing the report, compute the human-readable window. The check covers the last 7 days, so format it as `"DD MMM YYYY – DD MMM YYYY"` (e.g. `"15 May 2026 – 22 May 2026"`). Display this prominently in the header as the reporting period.

### Report structure

```
Header bar          — "Ingext Site Health Report" + date + overall badge
                      Reporting period: "DD MMM YYYY – DD MMM YYYY"
──────────────────────────────────────────────────────
KPI strip (4 cards) — Overall Status | Internal Logins (7d) | External Logins (7d) | Data Ingressed (7d)
──────────────────────────────────────────────────────
Check panels (2)    — One card per check:

  Login Activity panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Login breakdown table:
        Successful logins  │  <successful_count>  │ (no error)
          – Internal       │  <internal_count>    │ fluencysecurity.com / ingext.io / security.do
          – External       │  <external_count>    │ customer / external users
        Failed logins      │  <failed_count>      │ (error present)
        ────────────────────────────────────────────
        Total attempts     │  <total_count>
    • If external logins > 0: sample of up to 3 redacted external addresses
    • What the result means

  Data Ingress panel:
    • Check name & description
    • Result badge (PASS / FAIL / UNKNOWN)
    • Key evidence (total bytes/events ingested)
    • What the result means

──────────────────────────────────────────────────────
Interpretation      — 2–3 sentence plain-English summary of findings
Next steps          — 2–4 action items if anything is degraded/unhealthy
                      (omit or shorten if everything is healthy)
──────────────────────────────────────────────────────
Footer              — "Powered by Ingext · <date>"
```

### Styling guidelines

- Use inline CSS only — no external dependencies.
- Color scheme:
  - HEALTHY / PASS: `#22c55e` (green)
  - DEGRADED / UNKNOWN: `#f59e0b` (amber)
  - UNHEALTHY / FAIL: `#ef4444` (red)
  - Background: `#0f172a` (dark navy), card background: `#1e293b`
  - Body text: `#e2e8f0`, muted text: `#94a3b8`
- Max width `780px`, centered, responsive.
- The overall status badge should be prominent — large font, full-width banner color.

## Step 6 — Share

Link to the HTML file with a `computer://` path. Add one sentence in chat summarizing the overall status (e.g., "The site looks healthy — external logins detected and 1.2 M events ingested over the last 7 days.").

## Failure modes

- **`audit_search` errors**: Mark the login check as UNKNOWN, note the error in the report, continue to the ingress check.
- **`System_DataIngress` not found**: Call `list_reports` to verify the catalog. If missing, mark ingress check as UNKNOWN with a note.
- **Both checks UNKNOWN**: Report can't determine health. Tell the user to check connector configuration.
- **No output directory**: Write to `/tmp/` and share the path.
