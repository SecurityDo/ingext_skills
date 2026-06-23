---
name: azure-user-signin-investigation
version: 1.0.3
description: >-
  Investigate a user's Azure AD / Entra ID sign-in and directory-change activity by querying
  the AzureSigninLogs / AzureAuditLogs datalake tables directly with KQL, and combining the
  results into one HTML report (sign-in timeline, summary, per-section tables, recommendations).
  Use when the focus is Azure AD sign-ins (IPs, apps, success/failure, location) and directory
  changes (role/group/password changes the user made or received). The only dependency is the
  AzureSigninLogs / AzureAuditLogs tables — no saved FPL reports are required. Triggers:
  "investigate Azure AD/Entra user X", "pull X's sign-in history", "what directory changes did
  X make/receive", "run the Azure sign-in investigation for jane@corp.com". Do NOT use for
  mailbox/Exchange content (inbox rules, sends, OAuth consents) or when AzureSigninLogs is
  absent — use the office-user-investigation skill, which queries the Office365 table instead.
---

# Azure AD User Sign-in & Directory-Change Investigation

Produce a comprehensive, single-page HTML investigation report for a specific Microsoft 365 /
Azure AD user by running three **KQL queries directly** against the Azure datalake tables and
combining the results into one readable document.

## Required data tables

This skill queries these datalake tables directly — **no saved FPL reports are needed**:

| Table | Used by | Covers |
|---|---|---|
| `AzureSigninLogs` | sign-in query | Sign-in events for the user (IPs, apps, success/failure, location, device) |
| `AzureAuditLogs` | both directory-change queries | Azure AD / Entra directory changes the user *made* and changes *targeting* the user |

If `AzureSigninLogs` (or `AzureAuditLogs`) is not present on the tenant, stop and tell the user
this tenant doesn't ingest Azure AD sign-in / audit data, so this skill can't run.

## Bundled queries

The three KQL queries live in `assets/queries/` (extracted from the original
`GetUserSigninHistory`, `GetDirectoryChangesInitiatedByUser`, and
`GetDirectoryChangesTargetingUser` FPL reports). Each uses three placeholders you substitute
before running:

- `{USER}` → the **lower-cased** UPN
- `{FROM}` / `{TO}` → the window bounds as **epoch milliseconds**

| File | Saves to | Section |
|---|---|---|
| `assets/queries/signin.kql` | `signin.json` | Sign-in history |
| `assets/queries/dir_changes_initiated.kql` | `dir_init.json` | Directory changes initiated by user |
| `assets/queries/dir_changes_targeting.kql` | `dir_target.json` | Directory changes targeting user |

> **Directory-change coverage (v1.0.2):** the two directory queries match group / role /
> app-role membership changes **plus** identity-security events — password resets / changes,
> MFA / security-info (authentication method) registration & changes, device registration, and
> session-token / account-disable events. These are high-signal account-takeover indicators and
> are flagged distinctly in the report's Diagnostic Findings.

## Required arguments

Every run needs these values. Only `username` is mandatory — if it's missing, use
`AskUserQuestion` to collect it before doing anything else. **If no time range is supplied,
default to the last 7 days and proceed without asking** (`to = now_ms`,
`from = now_ms - 604_800_000`); the other presets are still offered on request.

| Argument | Description | Example |
|---|---|---|
| `username` | The UPN or display name of the user to investigate (**required**) | `john@contoso.com` |
| `from` | Investigation window start — Unix timestamp **in milliseconds** (default: `now_ms - 604_800_000`, i.e. 7 days ago) | `1746057600000` |
| `to` | Investigation window end — Unix timestamp **in milliseconds** (default: `now_ms`) | `1746316800000` |

When asking for the time range, offer human-friendly options (e.g. "Last 24 hours", "Last 7 days", "Last 30 days", "Custom range"). To convert the chosen option to milliseconds, use the authoritative `now` epoch given in the CURRENT TIME block of your system prompt and **subtract** — never compute the current epoch from memory. The human-readable date you show the user MUST correspond to the epoch you actually pass (a common bug is showing this year's date but passing last year's epoch).

---

## Pipeline

```
1. list_data_tables          → confirm AzureSigninLogs + AzureAuditLogs exist
   └─ either missing → stop, tell the user this tenant has no Azure sign-in/audit data

2. Collect username (AskUserQuestion if missing); default from/to to last 7 days if not supplied

3. Run in parallel (same turn):
   ├─ kql_search: assets/queries/signin.kql                (-> signin.json)
   ├─ kql_search: assets/queries/dir_changes_initiated.kql (-> dir_init.json)
   ├─ kql_search: assets/queries/dir_changes_targeting.kql (-> dir_target.json)
   └─ get_azure_user_record: username=<username>           (-> user.json)

4. Save each kql_search result to <workdir> as JSON

5. Run scripts/build_report.py to produce the HTML

6. Write output HTML and share a computer:// link
```

Use a scratch working dir, e.g. `mkdir -p /tmp/azinv`.

---

### Step 1 — Confirm the Azure tables exist

Call `list_data_tables`. Confirm both `AzureSigninLogs` and `AzureAuditLogs` appear (as
streamTables). If either is absent, respond:

> **Investigation cannot proceed** — this tenant does not ingest the required Azure table(s):
> `AzureSigninLogs` / `AzureAuditLogs`. Deploy the Azure Directory Audit connector before
> running this investigation.

Then stop.

---

### Step 2 — Collect arguments

`username` is required — if it's missing, use `AskUserQuestion` to collect it. For the time
range: if the user supplied `from`/`to`, use those directly; **if they supplied no time range,
default to the last 7 days and proceed without asking** (`from = now_ms - 604_800_000`,
`to = now_ms`). Only ask about the window if the user wants to choose one or asks for a
different range. `now_ms` is the authoritative millisecond epoch from the CURRENT TIME block of
your system prompt — use it verbatim, do not recompute it. `to = now_ms`, and:
  - **Last 24 h**: `from = now_ms - 86_400_000`
  - **Last 7 days** (default): `from = now_ms - 604_800_000`
  - **Last 30 days**: `from = now_ms - 2_592_000_000`  

Sanity check before calling `run_report`: the year in the human-readable label you showed the user must equal the year of the epoch you pass. If they differ, you computed the epoch wrong — recompute from `now_ms`.  

---

### Step 3 — Run the three queries and fetch the user record

For each query file, read it, substitute `{USER}` (lower-cased UPN), `{FROM}` and `{TO}`
(epoch-ms), and run it with `kql_search`. Fire all four calls in a **single turn**:

```
tool: mcp__…__kql_search   kql=<substituted signin.kql>
tool: mcp__…__kql_search   kql=<substituted dir_changes_initiated.kql>
tool: mcp__…__kql_search   kql=<substituted dir_changes_targeting.kql>
tool: mcp__…__get_azure_user_record   username=<username>
```

> The queries carry their own `TimeGenerated between (...)` bounds, so passing `rangeFrom`/
> `rangeTo` is optional.

Save each `kql_search` result **as returned** (the build script reads the raw
`data.Tables[0]` shape directly):

```python
import json
json.dump(signin_result,     open("/tmp/azinv/signin.json","w"))
json.dump(dir_init_result,   open("/tmp/azinv/dir_init.json","w"))
json.dump(dir_target_result, open("/tmp/azinv/dir_target.json","w"))
# user record:
json.dump(user_record if isinstance(user_record, dict) else {"raw": user_record},
          open("/tmp/azinv/user.json","w"))
```

If `get_azure_user_record` errors, log a warning and continue — the report renders without the
profile card.

If a `kql_search` returns an **"Output too large"** error, it is saved to a file path — read
that file with the `Read` tool and save its `data` object to the matching `<name>.json` (the
parser is tolerant of the full raw tool result too). An empty result (`Rows: []`) is fine — that
panel renders a "No events found" notice.

---

### Step 4 — Build the HTML report

`scripts/build_report.py` reads the three result files (it accepts the `kql_search`
`data.Tables` shape as well as the legacy report shape) and fills `assets/report_template.html`.

```bash
SKILL_DIR="<absolute-path-to-this-skill-directory>"
OUTPUT_DIR="/tmp/azinv_out"; mkdir -p "${OUTPUT_DIR}/assets"

python3 "${SKILL_DIR}/scripts/build_report.py" \
  --username    "<username>" \
  --from-ms     <from_ms> \
  --to-ms       <to_ms> \
  --signin      /tmp/azinv/signin.json \
  --dir-init    /tmp/azinv/dir_init.json \
  --dir-target  /tmp/azinv/dir_target.json \
  --user-record /tmp/azinv/user.json \
  --template    "${SKILL_DIR}/assets/report_template.html" \
  --output      "${OUTPUT_DIR}/azure_investigation.html"
```

The script prints the output path and exits 0. If it exits non-zero, surface stderr and stop.
`--user-record` is optional.

---

### Step 5 — Copy logo asset

```bash
cp "${SKILL_DIR}/assets/logo2.png" "${OUTPUT_DIR}/assets/"
```

If the copy fails, continue — the report renders correctly without the logo.

---

### Step 6 — Copy to final location and share

Copy the completed HTML to the user's workspace output directory and provide a `computer://`
link. Add a one-sentence chat summary of the most significant finding (e.g. "3 sign-ins from a
new country detected; the user's admin role was modified twice during the window.").

---

## Output description

The HTML report contains:

- **Header**: username investigated, time window, date generated, Fluency logo
- **KPI strip** (4 cards): Total sign-ins · Unique source IPs · Directory changes initiated · Directory changes targeting user
- **Activity timeline**: SVG chart plotting all events across the window, colour-coded by source (sign-ins = blue, changes initiated = amber, changes targeting = red)
- **Executive summary**: 2–4 sentences naming the highest-signal findings
- **Three data panels** (one per query): concise table of key columns, rows capped at 50
- **Recommendations**: 4–6 prioritised next steps drawn from the actual findings

---

## Failure modes

| Situation | Response |
|---|---|
| `AzureSigninLogs` / `AzureAuditLogs` table missing | Stop; tell the user this tenant has no Azure sign-in/audit data |
| `kql_search` errors | Surface the error; do not render a partial page |
| A query returns empty data | Render that panel with a "No events found in this window" notice; continue |
| `build_report.py` exits non-zero | Show stderr output and stop |
| Logo not found | Continue without it — the report is still fully usable |
| `get_azure_user_record` returns error | Log warning, omit profile card, continue — report is complete without it |

---

## Layout

```
azure-user-signin-investigation/
├── SKILL.md
├── assets/
│   ├── report_template.html    ← Fluency-branded HTML scaffold with named placeholders
│   └── queries/                ← the three KQL queries (extracted from the FPL reports)
│       ├── signin.kql
│       ├── dir_changes_initiated.kql
│       └── dir_changes_targeting.kql
├── evals/
│   └── evals.json
└── scripts/
    └── build_report.py         ← Reads 3 result JSONs (kql_search or report shape), builds timeline SVG + tables, fills template
```
