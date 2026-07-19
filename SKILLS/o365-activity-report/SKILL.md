---
name: o365-activity-report
version: 1.0.0
description: >-
  Produce an **account-wide** (whole-tenant, NOT a single user) Microsoft 365 /
  Office 365 activity report by querying the Ingext/Fluency **Office365 datalake
  table directly with KQL** and rendering a self-contained HTML report of
  **tables + a timechart**. Three focuses: `all` (every workload), `exchange`
  (Exchange mailbox activity), and `mailitemsaccessed` (a drill-down into the
  MailItemsAccessed operation — who accessed which mailboxes, external vs owner,
  from where). USE THIS SKILL when the user wants an O365/Exchange **activity
  report for a whole account/tenant over a time window** — e.g. "report on
  Office365 Exchange activity in the last 24 hours", "MailItemsAccessed activity
  report", "what O365 operations spiked today", "timechart of Exchange events" —
  and explicitly wants KQL (a table / timechart), NOT an FPL report. This is the
  KQL, account-wide counterpart of the FPL-based `fluency-report`. DO NOT use it
  when the focus is a single named mailbox/user (use `office-user-investigation`)
  or when the user asked to run a saved FPL report (use `fluency-report`).
  Triggers: "office365 exchange activity report", "o365 activity last 24h",
  "MailItemsAccessed report", "account-wide mailbox activity", "timechart of
  O365 events by workload/operation".
---

# O365 Activity Report (KQL, account-wide)

Produce a single-page, self-contained HTML report of **Microsoft 365 activity
for a whole account/tenant** — a KPI strip, a **timechart** of events over the
window, and ranked breakdown **tables** — by querying the **Office365 audit
table** in the Ingext/Fluency datalake with KQL and rendering the *real* query
output deterministically.

This is **distinct** from its siblings:

| Skill | Scope | Source |
|---|---|---|
| `office-user-investigation` | ONE named mailbox/user, GeoIP + BEC focus | KQL |
| `fluency-report` | Runs a saved report from the FPL catalog | FPL |
| **`o365-activity-report`** (this) | **Whole account/tenant, activity over time** | **KQL** |

Use this when the user wants account-wide O365/Exchange activity from KQL and
specifically did **not** want an FPL report.

## Data integrity (non-negotiable)

Every number, row, timestamp, IP, mailbox and chart point in the report is
rendered **by the build script directly from the KQL results you saved** — you
never hand-write figures into HTML. If a query returns zero rows or errors, the
corresponding panel renders an explicit **"no data in this window"** state.
**Never** invent, estimate, or copy example values to fill a panel; an empty or
partial-but-true report is the correct outcome. This is exactly why the renderer
is a script and not free-form HTML authoring.

## Required inputs

| Argument | Meaning | Example |
|---|---|---|
| `focus` | `all` \| `exchange` \| `mailitemsaccessed` | `exchange` |
| `from` / `to` | Window as **epoch milliseconds** | `1773862340254` |
| connector | Which Ingext/Fluency MCP connector (tenant) | the connected tenant |

Infer `focus` from the request ("Exchange activity" → `exchange`;
"MailItemsAccessed" → `mailitemsaccessed`; otherwise `all`). If the time window
is missing, use `AskUserQuestion` or default to **last 24h**. Convert presets to
ms yourself relative to the authoritative "now" you were given: 24h =
`now-86_400_000`, 7d = `now-604_800_000`, 30d = `now-2_592_000_000`.
Pick the timechart bin from the window: **≤2d → 1h**, ≤14d → `6h` or `1d`,
otherwise `1d`.

---

## Pipeline

```
1. Confirm the Office365 index exists   (list_indexes -> datalakeIndex "Office365")
   └─ absent -> stop, tell the user this tenant has no Office365 datalake table
2. Resolve focus + from/to (ms) + bin   (AskUserQuestion / default 24h if missing)
3. Run the KQL set for the focus via kql_search (rangeFrom=from, rangeTo=to)
   Save each raw tool result to <workdir>/<name>.json  (raw output is fine)
4. Run scripts/build_report.py          -> self-contained HTML (+ optional PDF)
5. Deliver the HTML/PDF (publish_artifact) + a one-line data-derived summary
```

Use a scratch working dir, e.g. `mkdir -p /tmp/o365_act`.

---

## Step 1 — Confirm the Office365 index

Call `list_indexes` on the connector; confirm an entry whose `datalakeIndex` is
`Office365`. If absent, stop and report that this tenant doesn't ingest Office365
audit data. All the useful fields (`timestamp`, `Operation`, `Workload`,
`UserId`, `ResultStatus`, `ClientIPAddress`, `MailboxOwnerUPN`, `ExternalAccess`,
`LogonType`) are queryable directly.

---

## Step 2–3 — Run the KQL set (via `kql_search`, passing the window)

Run **each** query with `kql_search`, passing `rangeFrom`=`<from_ms>` and
`rangeTo`=`<to_ms>` (the connector applies the time window — do **not** also add
an `ago()`/`timestamp between` filter). Save each raw tool result JSON to the
exact filename shown; the build script parses the raw `data.Tables[0]` shape and
tolerates the full tool envelope. Replace `{BIN}` with the bin you chose (e.g.
`1h`). For `focus=exchange`, every query already includes `| where Workload ==
"Exchange"`; for `focus=all`, **delete that line** from each query; for
`focus=mailitemsaccessed`, use the MailItemsAccessed set at the bottom.

> If a result says "Output too large" and is saved to a path, read that path and
> save its `data` object as `<name>.json` instead. Saving the whole raw result
> is fine — the parser is tolerant. If a query legitimately returns nothing,
> still save the (empty) result; the report will show a truthful "no data" panel.

### Exchange / all set

**overview.json** (single-row KPIs — drives the KPI strip):
```kql
Office365
| where Workload == "Exchange"
| summarize TotalEvents=count(),
            UniqueUsers=dcount(UserId),
            UniqueMailboxes=dcount(MailboxOwnerUPN),
            UniqueClientIPs=dcount(ClientIPAddress),
            FailedOps=countif(ResultStatus == "Failed"),
            ExternalAccess=countif(ExternalAccess == true)
```

**timechart.json** (the timechart — events per bin, split by Workload):
```kql
Office365
| where Workload == "Exchange"
| summarize events=count() by bin(timestamp, {BIN}), Workload
| sort by timestamp asc
```
> For `focus=all`, drop the `Workload ==` filter but KEEP `by ..., Workload` so
> the chart shows one line per workload.

**operations.json** (top operations table + bars):
```kql
Office365
| where Workload == "Exchange"
| summarize events=count(), users=dcount(UserId), lastSeen=max(timestamp) by Operation
| sort by events desc | take 40
```

**top_users.json**:
```kql
Office365
| where Workload == "Exchange"
| summarize events=count(), operations=dcount(Operation), lastSeen=max(timestamp) by UserId
| sort by events desc | take 25
```

**top_ips.json**:
```kql
Office365
| where Workload == "Exchange"
| where isnotempty(ClientIPAddress)
| summarize events=count(), users=dcount(UserId),
            external=countif(ExternalAccess == true), lastSeen=max(timestamp)
  by ClientIPAddress
| sort by events desc | take 25
```

**workload.json** (only for `focus=all` — workload split table):
```kql
Office365
| summarize events=count(), users=dcount(UserId) by Workload
| sort by events desc
```

### MailItemsAccessed set (`focus=mailitemsaccessed`)

**overview.json**:
```kql
Office365
| where Operation == "MailItemsAccessed"
| summarize TotalAccesses=count(),
            UniqueMailboxes=dcount(MailboxOwnerUPN),
            UniqueActors=dcount(UserId),
            UniqueClientIPs=dcount(ClientIPAddress),
            ExternalAccess=countif(ExternalAccess == true)
```

**timechart.json** (accesses per bin, split by external vs internal):
```kql
Office365
| where Operation == "MailItemsAccessed"
| extend Access = iff(ExternalAccess == true, "External", "Internal")
| summarize events=count() by bin(timestamp, {BIN}), Access
| sort by timestamp asc
```

**top_mailboxes.json** (which mailboxes were accessed most):
```kql
Office365
| where Operation == "MailItemsAccessed"
| summarize accesses=count(), actors=dcount(UserId), ips=dcount(ClientIPAddress),
            external=countif(ExternalAccess == true), lastSeen=max(timestamp)
  by MailboxOwnerUPN
| sort by accesses desc | take 25
```

**top_ips.json** (source IPs doing the accessing):
```kql
Office365
| where Operation == "MailItemsAccessed"
| where isnotempty(ClientIPAddress)
| summarize accesses=count(), mailboxes=dcount(MailboxOwnerUPN),
            external=countif(ExternalAccess == true), lastSeen=max(timestamp)
  by ClientIPAddress
| sort by accesses desc | take 25
```

**logontype.json** (owner=0 / admin=1 / delegate=2 access split):
```kql
Office365
| where Operation == "MailItemsAccessed"
| summarize accesses=count() by LogonType
| sort by accesses desc
```

---

## Step 4 — Build the report

First run only — WeasyPrint is only needed if you want a PDF:
```bash
pip install weasyprint --break-system-packages -q   # optional, PDF only
```

Then:
```bash
python3 <SKILL_DIR>/scripts/build_report.py \
  --workdir /tmp/o365_act \
  --focus   exchange \
  --tenant  "hanoverresearch" \
  --from-ms <from_ms> \
  --to-ms   <to_ms> \
  --bin     1h \
  --output  /tmp/o365_act/o365_activity.html \
  [--pdf    /tmp/o365_act/o365_activity.pdf]
```

The script reads whatever `<name>.json` files are present in `--workdir`,
renders each as its panel, and shows a truthful "no data" state for any that are
missing or empty. It never fabricates. A "Data sources" appendix lists each file
and its row count so every figure is traceable.

Notes:
- HTML has **no external assets** (inline CSS, inline SVG chart) so it renders in
  the Cowork/artifact sandbox.
- PDF via WeasyPrint is optional; if its libs are missing, drop `--pdf` and use
  the `html-to-pdf` skill on the HTML instead.

---

## Step 5 — Deliver

Deliver the HTML (and PDF) with `publish_artifact` (or `present_files`). Add a
one-line chat summary **derived only from the data** — e.g. "Exchange: 48,210
events in 24h across 63 mailboxes; MailItemsAccessed is the top operation (31%),
busiest hour 14:00 UTC." If a window returned nothing, say exactly that.

## Layout

```
o365-activity-report/
├── SKILL.md
└── scripts/
    └── build_report.py     # KQL JSON -> KPIs + timechart + tables -> HTML (+PDF)
```

## Failure modes

| Situation | Response |
|---|---|
| No `Office365` index on the tenant | Stop; tell the user this skill needs Office365 datalake data |
| `overview.json` empty / missing | Report renders KPIs as "no data"; say the window had no matching events |
| A single query errored | That panel shows "no data"; the rest of the report still builds |
| WeasyPrint libs missing | Build HTML only; convert via the `html-to-pdf` skill |
| User named ONE mailbox | Wrong skill — use `office-user-investigation` |
| User asked for a saved/FPL report | Wrong skill — use `fluency-report` |
