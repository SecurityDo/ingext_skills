---
name: billing-csv
version: 1.0.0
description: Generate a billing CSV for all clients by querying the Ingext datalake / resource tables directly (no System_Usage_Report or System_Billing_Report). Trigger whenever the user asks to "generate a billing CSV", "run the billing report", "export billing data", "create a billing file", "billing for [month/period]", or any phrasing that implies producing a per-client usage summary for invoicing or accounting. The skill discovers the available data tables, counts each client's billable users (Office365 paid Member users + Google Workspace users), and writes a ready-to-use CSV file.
---

# Billing CSV Generator

Produce a per-client billing CSV by querying the tenant's data tables directly.

> **Approach:** this skill builds billable figures from queries run directly
> against the datalake stream tables and the Office365 resource (snapshot)
> tables — it does **not** use `System_Usage_Report` / `System_Billing_Report`.
> Queries are kept as bundled assets so they can be reviewed and refined over
> time.

## Bundled assets

| Path | Purpose |
|---|---|
| `assets/Microsoft365_LicenseTable.csv` | Reference list of **paid** Microsoft 365 license SKUs (`Product name, SKUID, String ID`). All free/trial/developer SKUs have already been removed — **every row is a paid license**. Used to decide which Office365 users are billable, and to map a `skuId` to a readable product name. |
| `assets/queries/office365_licensed_users.kql` | Validated KQL — Office365 licensed **Member** users (one row per `userPrincipalName`, `skuId`). |
| `assets/queries/googleworkspace_users.kql` | ⚠️ Placeholder / unvalidated — no Google Workspace table exists in the tenant yet. Refine when one is connected. |

## Step 1 — Discover the available data tables

**Always start here.** Call `list_data_tables`. It returns two kinds of tables:

- **`streamTables`** — append-only event logs in the datalake (e.g.
  `AzureSigninLogs`, `Office365`). Query with `kql_search`; time-bound them.
- **`resourceTables`** — entity *snapshots* synced from a vendor API (e.g.
  `office365User`). Each holds one current row per entity, so query them
  **directly with `kql_search` — no time filter, no dedup**.

Use this to confirm which user sources exist for the client (Office365 resource
tables, and — if present — a Google Workspace user table).

## Step 2 — Count billable users

A client's billable user count is **Office365 paid users + Google Workspace
users**.

### Office365 paid users

Run `assets/queries/office365_licensed_users.kql` via `kql_search`:

```
office365User
| where userType == "Member"
| mv-expand assignedLicenses
| extend skuId = tostring(assignedLicenses.skuId)
| where isnotempty(skuId)
| distinct userPrincipalName, skuId
```

This returns one row per `(user, skuId)` for **Member** users who hold at least
one assigned license. Guests (`userType == "Guest"`) are excluded.

Then, **after** the query returns (do **not** try to do this in KQL — see the
engine note below):

1. Drop any row whose `skuId` is **not** present in
   `assets/Microsoft365_LicenseTable.csv` (those are free/trial SKUs).
2. Count **distinct** `userPrincipalName` among the remaining rows → the
   Office365 paid-user count.
3. (Optional) map each surviving `skuId` to its product name via the CSV for a
   readable per-user license breakdown.

### Google Workspace users

No Google Workspace table is currently exposed by `list_data_tables`, and the
KQL schema knowledge base has no Google schema, so this count is **0** unless a
Google Workspace user table is present. If one appears, mirror the Office365
pattern — see `assets/queries/googleworkspace_users.kql` (placeholder). Google
seats are licensed per active account, so there is no per-SKU paid filter to
apply on that side.

**Total billable users = Office365 paid users + Google Workspace users.**

## Engine note — do the paid match downstream, not in KQL

This KQL engine **silently drops** any column derived from a dynamic array via
`set_intersect`, `array_length`, or `set_has_element` when that column is
computed *after* a `summarize make_set(...)`. So do **not** try to compute a
"has a paid license" flag inside the query by intersecting a `make_set` of SKUs
against the paid list. Return the raw `(user, skuId)` rows and match each
`skuId` against the CSV in the downstream step. (Scalar `extend`s after a
`summarize` are fine — it is specifically dynamic-array operations on a
`make_set` column that don't survive.)

## Step 3 — Determine the billing window

The PromQL byte counters are accumulated over the billing cycle, so first turn
the requested period into a window the metrics tools accept.

**Critical tool constraint:** `prom_query` / `prom_query_range` accept **only
relative offsets** (`-31d`, `-1617600s`, `now`/`-0h`) for `time` / `from` / `to`.
Epoch milliseconds and RFC3339 timestamps are **rejected** (`invalid time`). So an
absolute calendar month must be expressed as an offset from *now*.

Compute, at run time:

1. `cycleStart` = first day of the billing month, 00:00:00 UTC.
2. `cycleEnd`   = first day of the **next** month, 00:00:00 UTC (exclusive end).
3. `periodDays` = whole days in the cycle = `(cycleEnd - cycleStart) / 1 day`
   (28/29/30/31). This is the PromQL window, e.g. `31d`.
4. `offsetSeconds` = `now_epoch_seconds − cycleEnd_epoch_seconds` (a positive
   integer for any already-closed month). The evaluation instant is the string
   `-<offsetSeconds>s`.

Then every Step-4 query is `increase(<counter>[<periodDays>d])` evaluated at
`time = "-<offsetSeconds>s"`. A few seconds of drift (between computing the
offset and the query running) is negligible over a multi-week window.

```python
from datetime import datetime, timezone
import calendar, time

def billing_window(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    em, ey = (month % 12 + 1), (year + (1 if month == 12 else 0))
    end   = datetime(ey, em, 1, tzinfo=timezone.utc)
    period_days   = (end - start).days
    offset_seconds = int(time.time() - end.timestamp())   # > 0 for a closed month
    last_day = datetime(year, month, calendar.monthrange(year, month)[1], tzinfo=timezone.utc)
    return {
        "period_window": f"{period_days}d",
        "time_offset":   f"-{offset_seconds}s",
        "billing_from":  start.strftime("%Y-%m-%d"),
        "billing_to":    last_day.strftime("%Y-%m-%d"),
    }
```

Notes:
- **Current (partial) month:** `cycleEnd` is in the future, so `offsetSeconds`
  would be negative — you can't query the future. Instead evaluate at `time =
  "-0h"` (now) with the window set to the days elapsed since `cycleStart`.
- **Old months beyond metrics retention** return partial or empty series — see
  failure modes.

## Step 4 — Data volume (stored + dropped) via PromQL

These come from the platform metrics store (VictoriaMetrics), **not** from a
report. All three are monotonic counters, so they are wrapped in `increase(...)`
over the `periodDays` window from Step 3 and run with `prom_query` at
`time = "-<offsetSeconds>s"`. Substitute the `period_window` value for
`<PERIOD>` below.

### Data stored — datalake & eventwatch

Run `assets/queries/egress_bytes_by_dest.promql`:

```
sum by (dest) (increase(platform_egress_bytes[<PERIOD>]))
```

Splits stored volume by destination:
- `dest="datalake"` → **Ingress Datalake (Bytes)**
- `dest="eventwatch"` → **Ingress Eventwatch (Bytes)**

### Data dropped

Run `assets/queries/data_dropped_bytes.promql`:

```
sum(increase(platform_component_bytes{component=~"router|datasink", action="drop"}[<PERIOD>]))
```

→ **Data Dropped (Bytes)**.

**Avoid double-counting:** a `pipe` sits inside a `router` and the platform
records the same drop at both granularities (identical byte counts), so summing
across *all* components double-counts. Scoping to `component=~"router|datasink"`
(pipe excluded) gives the true dropped total.

> All three queries were verified against the live tenant over a 24h window:
> datalake ≈ 385.2 MB, eventwatch ≈ 15.5 MB, dropped ≈ 73 KB.

## Step 5 — Write the CSV

Current agreed columns:

```
Client,Billing From,Billing To,Billable Users,Ingress Datalake (Bytes),Ingress Eventwatch (Bytes),Data Dropped (Bytes)
```

- `Billable Users` = Office365 paid users + Google Workspace users (Step 2).
- The three byte columns are raw integers from Step 3 (no unit conversion).
- `Billing From` / `Billing To` = first / last day of the billing cycle (UTC, `YYYY-MM-DD`).
- Sort rows alphabetically by `Client`.
- UTF-8 encoding, Unix line endings.
- Write to the workspace folder: `<workspace>/billing_<YYYY-MM>_<YYYYMMDD_HHMMSS>.csv`.

## Failure modes

| Situation | Action |
|---|---|
| `list_data_tables` shows no `office365User` | Note the client has no Office365 source; Office365 paid count = 0 |
| A returned `skuId` is not in the license CSV | Treat as free/trial — exclude from the billable count |
| No Google Workspace table present | Google count = 0; total = Office365 paid users only |
| `kql_search` errors | Surface the error; note the affected client and continue |
| A PromQL metric returns no series | Treat that byte total as 0 for the client |
| Tempted to sum drop bytes across all components | Don't — scope to `router\|datasink` to avoid the pipe/router double-count |
| `prom_query` rejects the time (`invalid time`) | You passed epoch/RFC3339 — only relative offsets work; use `time = "-<offsetSeconds>s"` (Step 3) |
| Billing month predates metrics retention | `increase()` returns partial/empty — flag the client's byte totals as incomplete rather than billing a low number |
