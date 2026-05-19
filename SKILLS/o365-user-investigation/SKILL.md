---
name: o365-user-investigation
description: Investigate an Office365 / Azure AD user on Fluency by running all three required reports (GetDirectoryChangesInitiatedByUser, GetDirectoryChangesTargetingUser, GetUserSigninHistory) and producing a single-page HTML investigation report with an activity timeline, executive summary, per-report data tables, and security recommendations. Trigger whenever the user asks to investigate a specific O365 or Azure AD / Entra user — e.g. "investigate O365 user john@contoso.com", "look into what user X did in Office365", "pull a Fluency user investigation for jane@corp.com", "check this Azure AD account on Fluency", "run an O365 user investigation", "what did user X do in Office 365 last week?", or any phrasing implying a focused review of a specific user's sign-in or directory activity in Microsoft 365.
---

# O365 User Investigation

Produce a comprehensive, single-page HTML investigation report for a specific Microsoft 365 / Azure AD user by running three Fluency reports and combining the results into one readable document.

## Required reports

This skill depends on exactly these three FPL reports being present in the user's Fluency catalog:

| Report name | What it covers |
|---|---|
| `GetDirectoryChangesInitiatedByUser` | Azure AD / Entra directory changes the subject user *made* (e.g. adding group members, modifying accounts) |
| `GetDirectoryChangesTargetingUser` | Directory changes made *to* the subject user's account (e.g. password resets, role assignments) |
| `GetUserSigninHistory` | Sign-in events for the subject user (IPs, apps, success/failure, location) |

If **any** of the three reports is missing from the catalog, stop immediately and tell the user which report(s) are absent. Do not substitute another report or proceed with partial data.

## Required arguments

Every run needs three values. If the user's message does not include all three, use `AskUserQuestion` to collect the missing ones before doing anything else.

| Argument | Description | Example |
|---|---|---|
| `username` | The UPN or display name of the user to investigate | `john@contoso.com` |
| `from` | Investigation window start — Unix timestamp **in milliseconds** | `1746057600000` |
| `to` | Investigation window end — Unix timestamp **in milliseconds** | `1746316800000` |

When asking for the time range, offer human-friendly options (e.g. "Last 24 hours", "Last 7 days", "Last 30 days", "Custom range") and convert the chosen option to milliseconds yourself using the current time.

---

## Pipeline

```
1. list_reports              → verify all 3 required reports exist
   └─ any missing → stop, tell user which are absent

2. Collect from / to / username  (AskUserQuestion if not all provided)

3. Run in parallel (same turn):
   ├─ run_report: GetDirectoryChangesInitiatedByUser  (syncMode: false)
   ├─ run_report: GetDirectoryChangesTargetingUser    (syncMode: false)
   ├─ run_report: GetUserSigninHistory                (syncMode: false)
   └─ get_azure_user_record: username=<username>      (call immediately, no polling needed)

4. Poll the 3 report tasks; call get_report_result for each when completed

5. Save each result to /tmp/ as JSON (reports → 3 files; user record → 1 file)

6. Run scripts/build_report.py to produce the HTML

7. Write output HTML and share a computer:// link
```

---

### Step 1 — Verify the three reports exist

Call `list_reports` on the FPL MCP connector. Scan the returned names using **case-insensitive** matching for each of the three required names. If even one is absent, respond with:

> **Investigation cannot proceed** — the following required report(s) are not available in your Fluency catalog:
> - `MissingReportName`
>
> Please ensure these reports are deployed to your Fluency instance before running this investigation.

Then stop. Do not proceed with any remaining steps.

---

### Step 2 — Collect arguments

If the user already supplied `username`, `from`, and `to` in their message, use those values directly.

Otherwise, use `AskUserQuestion` to ask. Offer preset time-range options and convert them to milliseconds:

- **Last 24 h**: `from = now_ms - 86_400_000`
- **Last 7 days**: `from = now_ms - 604_800_000`
- **Last 30 days**: `from = now_ms - 2_592_000_000`

---

### Step 3 — Run reports and fetch user record in parallel

In a **single turn**, fire all four calls at once:

**Three FPL reports** (async):
```
tool:   mcp__…__run_report
args:   name=<report-name>, syncMode=false,
        arguments=[
          { "name": "from",     "value": "<from_ms_as_string>" },
          { "name": "to",       "value": "<to_ms_as_string>" },
          { "name": "username", "value": "<username>" }
        ]
```

> **Important:** Pass `from` and `to` as **strings** (no `"type": "integer"`). The FPL reports internally call `timeConvert()` which expects the raw millisecond string. Do **not** pass a custom `fpl` parameter — use the saved report scripts unchanged.

**Azure AD user record** (synchronous, returns immediately):
```
tool:   get_azure_user_record
args:   username=<username>
```

The user record call returns immediately — no polling needed. Save its result to `/tmp/o365inv_user.json`:

```python
import json
# result = get_azure_user_record response (dict or string)
with open("/tmp/o365inv_user.json", "w") as f:
    json.dump(result if isinstance(result, dict) else {"raw": result}, f)
```

If `get_azure_user_record` returns an error (user not found, no integration configured), log a warning and continue — the report renders without the profile card.

Poll the three FPL tasks with `get_report_task` until each is `completed` or `aborted`, then call `get_report_result` for each.

If a report returns `aborted`, render that panel as "Report aborted — no data available" and continue with the other two.

The `get_report_result` response has shape:
```
result.objects[0].table.columns  →  array of {name, isVariable, ...}  ← dict format
result.objects[0].table.rows     →  array of dicts  (keyed by column name)  ← dict format
```

**No manual normalisation needed.** `build_report.py`'s `extract_rows()` function automatically handles both dict-format columns and dict-format rows.

If `get_report_result` returns an **"Output too large"** error, it includes a file path where the result was persisted. Read that file using the `Read` tool (macOS host path) and parse it with:

```python
import json
data = json.loads(open(path).read())
result_objects = data["result"]["objects"]
```

Save each result to a temp file:

```python
import json
# result_objects = get_report_result_response["result"]["objects"]
with open("/tmp/o365inv_signin.json", "w") as f:
    json.dump({"objects": result_objects}, f)
# repeat for dir_init → /tmp/o365inv_dir_init.json
# repeat for dir_target → /tmp/o365inv_dir_target.json
```

---

### Step 4 — Build the HTML report

The bundled script `scripts/build_report.py` reads the three result files and the HTML template, then writes a fully-populated HTML file.

```bash
SKILL_DIR="<absolute-path-to-this-skill-directory>"
OUTPUT_DIR="/tmp/o365inv_out"
mkdir -p "${OUTPUT_DIR}/assets"

python3 "${SKILL_DIR}/scripts/build_report.py" \
  --username    "<username>" \
  --from-ms     <from_ms> \
  --to-ms       <to_ms> \
  --signin      /tmp/o365inv_signin.json \
  --dir-init    /tmp/o365inv_dir_init.json \
  --dir-target  /tmp/o365inv_dir_target.json \
  --user-record /tmp/o365inv_user.json \
  --template    "${SKILL_DIR}/assets/report_template.html" \
  --output      "${OUTPUT_DIR}/o365_investigation.html"

# --user-record is optional. If the file is absent or the tool returned an error,
# the script renders the report without the profile card and exits 0.
```

The script prints the output path on success and exits 0. If it exits non-zero, surface stderr and stop.

---

### Step 5 — Copy logo asset

The Fluency logo is bundled with this skill in `assets/logo2.png`. Copy it to the output directory:

```bash
cp "${SKILL_DIR}/assets/logo2.png" "${OUTPUT_DIR}/assets/"
```

If the copy fails for any reason, continue — the report renders correctly without the logo.

---

### Step 6 — Copy to final location and share

Copy the completed HTML to the user's workspace output directory, then provide a `computer://` link.

Add a one-sentence chat summary of the most significant finding (e.g. "3 sign-ins from a new country detected; the user's admin role was modified twice during the investigation window.").

---

## Output description

The HTML report contains:

- **Header**: username investigated, time window, date generated, Fluency logo
- **KPI strip** (4 cards): Total sign-ins · Unique source IPs · Directory changes initiated · Directory changes targeting user
- **Activity timeline**: SVG chart plotting all events across the investigation window, colour-coded by source (sign-ins = blue, changes initiated = amber, changes targeting = red)
- **Executive summary**: 2–4 sentences naming the highest-signal findings
- **Three data panels** (one per report): concise table of key columns, rows capped at 50
- **Recommendations**: 4–6 prioritised next steps drawn from the actual findings

---

## Failure modes

| Situation | Response |
|---|---|
| One or more required reports missing | Stop; list the missing report names; ask user to deploy them |
| `run_report` errors | Surface the error; do not render a partial page |
| A report returns empty data | Render that panel with a "No events found in this window" notice; continue |
| `build_report.py` exits non-zero | Show stderr output and stop |
| Logo not found | Continue without it — the report is still fully usable |
| `get_azure_user_record` returns error | Log warning, omit profile card, continue — report is complete without it |

---

## Layout

```
o365-user-investigation/
├── SKILL.md
├── assets/
│   └── report_template.html    ← Fluency-branded HTML scaffold with named placeholders
└── scripts/
    └── build_report.py         ← Reads 3 report JSONs, builds timeline SVG + tables, fills template
```
