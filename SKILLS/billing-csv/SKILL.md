---
name: billing-csv
version: 1.2.0
description: "Generate a billing CSV for all clients from the tenant's own immutable daily usage ledger (usage_daily), with billable-user counts from the Office365 user resource dump. Trigger whenever the user asks to \"generate a billing CSV\", \"run the billing report\", \"export billing data\", \"create a billing file\", \"billing for [month/period]\", \"usage for the whole provider\", or any phrasing that implies producing a per-client usage summary for invoicing or accounting. The skill enumerates every tenant, reads each tenant's closed daily billing ledger for the period, writes one CSV row per client with a column per meter, adds a provider-wide TOTAL row, and counts billable users (Office365 paid Member users + Google Workspace users) locally."
---

# Billing CSV Generator

Produce a per-client billing CSV from the tenant's **immutable daily usage
ledger** plus a locally-counted billable-user figure, and add a provider-wide
total row.

> **Approach:** data-volume figures come from `usage_daily` — the per-tenant
> daily billing ledger that each tenant measures once a day and stores
> immutably. These are the **closed, billable record**; prefer them over
> `prom_query`, which only re-derives an approximation of the same numbers. The
> billable-user count is still taken by **downloading the Office365 user resource
> dump and counting it locally** (exact, and it sidesteps the datalake query
> engine). This skill does **not** use `System_Usage_Report` /
> `System_Billing_Report`.

## Bundled assets

| Path | Purpose |
|---|---|
| `assets/Microsoft365_LicenseTable.csv` | Reference list of **paid** Microsoft 365 license SKUs (`Product name, SKUID, String ID`). All free/trial/developer SKUs have already been removed — **every row is a paid license**. Used to decide which Office365 users are billable, and to map a `skuId` to a readable product name. |
| `assets/queries/office365_licensed_users.kql` | **Legacy / reference only.** The user count is done on the downloaded dump, not via `kql_search`. Kept to document the field logic (Member filter, `assignedLicenses` expansion). |
| `assets/queries/googleworkspace_users.kql` | Placeholder / unvalidated — refine when a Google Workspace source is connected. |
| `assets/queries/egress_bytes_by_dest.promql`, `assets/queries/data_dropped_bytes.promql` | **Legacy / fallback only.** The ledger (`usage_daily`) is the source of record for volume. Use these PromQL queries only when the ledger is unreachable for a tenant (`storeAvailable:false`) and an approximate figure is explicitly acceptable — see the fallback note in Step 3. |

## Step 1 — Enumerate the tenants to bill

Call `list_accounts` first. A provider has no usage of its own, so billing is
always **per tenant, then summed**. Each entry carries the account `name` (the
`account` argument for every other tool) and a human-readable `displayName`
(use for the `Client` column).

To bill the whole provider, bill every account returned here and add a TOTAL
row (Step 5).

## Step 2 — Billable user count per tenant

A client's billable user count is **Office365 paid users + Google Workspace
users**, counted locally from the resource dump.

1. `list_resource_dumps` for the account (optionally `resource="office365User"`).
   It lists the vendor dumps, each a full inventory snapshot for one resource
   type and one customer. If there is **no `office365User` dump**, the client has
   no Office365 source → Office365 paid count = 0. A resource may have a dump per
   `customer`; note each one.
2. `get_resource_dump_url` with `resource="office365User"` (and `customer=...` when
   Step 1 showed more than one). Pass `format="parquet"` (columnar; best for
   pandas/DuckDB); fall back to `format="jsonl"` only if parquet is not in the
   dump's `formats`. The URL is time-limited (~15 min) and carries its own
   credential; request a fresh one rather than reusing an expired link.
3. Download with `curl`/python (no extra header). Do **not** read the whole file
   into the conversation — for large tenants it far exceeds the context window.
4. Count locally:
   1. Keep only `userType == "Member"` (drop Guests).
   2. Expand `assignedLicenses`, take each `skuId`.
   3. Keep rows whose `skuId` is in `assets/Microsoft365_LicenseTable.csv` (the
      paid SKUs; everything else is free/trial).
   4. Count **distinct** `userPrincipalName` among survivors → the Office365
      paid-user count.

> **Dump schema note:** each parquet/JSONL row wraps the user record in a `doc`
> field (a JSON string), with labels (`customer`, `dayIndex`, `resourceType`)
> alongside. Parse `doc` to reach `userType`, `assignedLicenses`,
> `userPrincipalName` — they are not top-level columns.

```python
import pandas as pd, csv, json

paid = set()
with open('assets/Microsoft365_LicenseTable.csv') as f:
    for r in csv.DictReader(f):
        s = r['SKUID'].strip().lower()
        if s: paid.add(s)

df = pd.read_parquet('office365User.parquet', columns=['doc'])
upns = set()
for raw in df['doc']:
    u = json.loads(raw) if isinstance(raw, str) else raw
    if u.get('userType') != 'Member':
        continue
    for a in (u.get('assignedLicenses') or []):
        if isinstance(a, dict) and (a.get('skuId') or '').lower() in paid:
            upn = (u.get('userPrincipalName') or '').lower()
            if upn: upns.add(upn)
            break
office365_paid_users = len(upns)
```

### Google Workspace users

No Google Workspace resource dump is currently exposed, so this count is **0**
unless one appears in `list_resource_dumps`. If one does, mirror the Office365
pattern — download and count distinct active accounts (Google seats are licensed
per active account, so there is no per-SKU paid filter).

**Total billable users = Office365 paid users + Google Workspace users.**

### Why download instead of query

Counting on the downloaded snapshot is **exact**. `summarize
dcount(userPrincipalName)` is approximate at tenant scale, and a raw `distinct
user, skuId` can hit the engine's per-table row cap on large tenants. The dump
is the whole snapshot, so a local `nunique()` over the paid-filtered rows is
ground truth.

## Step 3 — Data volume per tenant from the usage ledger

For each tenant, call `usage_daily` with `account="<name>"` and
`month="YYYY-MM"` (a month still in progress ends at yesterday; for a partial
current month omit nothing — the tool handles it). This returns a per-day ledger
plus a precomputed `summary.totals`, one entry per meter.

**Use `summary.totals[*].bytes`** — the whole-month total per meter — for the CSV
columns. The meters are:

| Ledger meter | Meaning |
|---|---|
| `input_bytes` | Total raw bytes ingested |
| `platform_datalake_bytes` | Bytes stored to the datalake |
| `lake_ingress_bytes` | Datalake ingress |
| `eventwatch_bytes` | Eventwatch volume |
| `lake_search_bytes` | Datalake search volume |
| `lake_realtime_search_bytes` | Real-time search volume |
| `deleted_bytes` | Deleted / dropped volume |
| `processed_bytes` | Usually 0; include only if non-zero |

> **BILLING CALCULATION — which bytes to charge.** When calculating billing, use
> these two volumes (not the raw meters one-for-one):
> - **Eventwatch usage = `eventwatch_bytes`.**
> - **Datalake usage = `lake_ingress_bytes − eventwatch_bytes`.**
>
> `eventwatch_bytes` is a subset of `lake_ingress_bytes` (eventwatch is always ≤
> lake ingress), so subtracting it nets the two buckets and ensures no byte is
> billed twice. Do **not** bill datalake on `platform_datalake_bytes` — that meter
> is bytes stored after dedup/compression and is often *lower* than eventwatch,
> which breaks the "datalake ≥ eventwatch" relationship. The subtraction is always
> ≥ 0; if a tenant ever shows `eventwatch_bytes > lake_ingress_bytes`, clamp the
> datalake figure to 0 and flag it as a data anomaly.

**READ THE FLAGS before trusting a number:**

- `storeAvailable:false` → the ledger was unreachable for that tenant. Do **not**
  record zero. Mark the tenant's volume columns as unavailable, and say so.
  (Only if the user explicitly accepts an approximation may you fall back to the
  legacy PromQL queries for that one tenant — label those cells as estimates.)
- A day with `state:"missing"` had no collection; `summary.missingDays > 0` (or any
  `summary.totals[*].lowerBound == true`) means the month total is a **lower
  bound**, not a smaller bill. Carry that into the row's `Note` and into the TOTAL
  row's note.
- Only days with `billable:true` count toward a charge; `summary.billableDays` is
  the number used — put it in the `Billed Days` column.
- `paidUsers` in the ledger is the daily observed M365 seat count; it is a useful
  cross-check against the Step-2 count but the billable figure comes from Step 2.

Also capture, per tenant, the M365 seat count the ledger observed on the final
billable day (handy as a sanity check, and the basis for the `Paid Users (M365)`
column when no resource dump exists — then it is 0 / "no M365 user source").

> No manual billing-window math and no relative-offset PromQL gymnastics are
> needed here — `usage_daily` takes a plain `month` (or `from`/`to`) and returns
> closed, immutable totals. The PromQL window logic is retained only in the
> legacy fallback assets.

## Step 4 — (legacy) PromQL fallback

Only when `usage_daily` reports `storeAvailable:false` for a tenant **and** an
approximate figure is explicitly acceptable: run the bundled PromQL queries
(`assets/queries/egress_bytes_by_dest.promql`,
`assets/queries/data_dropped_bytes.promql`) over the period. These re-derive an
approximation of the ledger and must be labelled as estimates. `prom_query`
accepts **only relative offsets** (`-31d`, `-<seconds>s`, `now`/`-0h`), never
epoch or RFC3339. Compute the period length and an offset-from-now for the
closed month and evaluate `increase(<counter>[<Nd>])` at `time="-<offset>s"`.
Scope dropped bytes to `component=~"router|datasink"` (pipe excluded) to avoid
the pipe/router double-count.

## Step 5 — Write the CSV

**Standard columns** (one row per tenant, then a provider TOTAL row):

```
Client,Billing From,Billing To,Billed Days,Paid Users (M365),input_bytes,platform_datalake_bytes,lake_ingress_bytes,eventwatch_bytes,lake_search_bytes,lake_realtime_search_bytes,deleted_bytes,Note
```

- `Client` = the account's `displayName` from Step 1.
- `Billing From` / `Billing To` = first / last day of the billing cycle (UTC, `YYYY-MM-DD`).
- `Billed Days` = `summary.billableDays` from the ledger.
- `Paid Users (M365)` = Step-2 billable users (0 with a `Note` when the tenant has no Office365 user source).
- The seven meter columns are **raw integers** from `summary.totals[*].bytes` (no unit conversion). A meter absent for a tenant is 0; an unavailable ledger is left blank with a `Note`.
- `Note` = per-row flags: `LOWER BOUND: N missing days`, `ledger unavailable`, `no M365 user source`, `M365 users observed = 0`, etc.
- **TOTAL row** `Client = "TOTAL (whole of {provider})"`: sum each meter column across all tenants; sum `Paid Users (M365)`; leave `Billed Days` blank. If **any** tenant was a lower bound or had an unavailable ledger, the TOTAL is a lower bound — say so in its `Note` and name the affected tenant(s).
- Sort client rows alphabetically by `Client`; the TOTAL row goes last.
- UTF-8 encoding, Unix line endings.
- Write to the workspace outputs folder as `billing_{YYYY-MM}_{provider-or-timestamp}.csv`.

> **Do not bake prices or SKUs into this CSV.** The ledger holds quantities only.
> If the user wants a single "usage" column or a dollar figure, ask which meter
> they bill on and (for money) the rate, then add that column — do not infer it.

## Failure modes

| Situation | Action |
|---|---|
| `usage_daily` `storeAvailable:false` for a tenant | Ledger unreachable — report it, leave that tenant's volume blank with a `Note`; the provider TOTAL becomes a lower bound. Fall back to legacy PromQL only if the user accepts an estimate. |
| `summary.missingDays > 0` / any `lowerBound:true` | The month total is a lower bound — flag the row and the TOTAL row; never present it as the full bill. |
| Billing month predates ledger retention | Partial/empty ledger — flag as incomplete rather than billing a low number. |
| `list_resource_dumps` shows no `office365User` dump | Client has no Office365 source; Office365 paid count = 0, `Note = "no M365 user source"`. |
| `office365User` dump lists several `customer`s | Download each customer's dump and sum the paid-user counts, deduping `userPrincipalName` across them. |
| Ledger `paidUsers` disagrees with the dump count | The billable figure is the dump count (Step 2); mention the ledger's observed count only as a cross-check. |
| `get_resource_dump_url` link expired | Request a fresh one; the link is not a stored location. |
| Dump is very large | Fetch `format="parquet"`, process with pandas/DuckDB; never read the whole file into the conversation. |
| A `skuId` is not in the license CSV | Treat as free/trial — exclude from the billable count. |
