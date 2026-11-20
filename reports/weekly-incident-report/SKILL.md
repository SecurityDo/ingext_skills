---
name: weekly-incident-report
version: 1.0.0
description: >-
  Produce a Weekly Incident Report for ONE Agent Portal account (a tenant on a provider MCP) in the Fluency brand, as one interactive HTML file,
  that opens with a prioritised checklist of what the analyst must do (open tickets waiting on an answer, closed incidents that ask
  someone to confirm a change by type, benign tickets still marked Escalate, process fixes), then the evidence behind each. Incidents
  still waiting for an investigation are left out. Built from agentportal_list_incidents plus agentportal_get_incident for every incident
  that is not closed; read-only. USE THIS SKILL for "weekly incident report", "incidents this week", "what needs action on the incidents",
  "weekly SOC report for account X". DO NOT use it for one incident (incident-investigation), a month-end executive report
  (ciso-monthly-report) or a provider-wide roll-up across accounts.
---

# Weekly Incident Report (one account)

The report answers one question: **what does the analyst have to do about this week's incidents.** It opens with that checklist (P1, P2, P3 with due dates,
one short line per action); the sections after it are the evidence. **Keep it short:** each row shows the ask only; the full detail sits behind a collapsed *Details* toggle.
It is meant to run **every week**. Read-only. The look is the Fluency report brand (`fluency-report` skill: IBM Plex, lock-mark brandline, black rule).

**Prerequisite: the `fluency-report` skill** (brand kit in its `scripts/`; the renderer finds it or uses `FLUENCY_BRAND_DIR`).

## Steps

0. **Provider or tenant server?** A *provider* MCP server hosts many accounts: it has `list_accounts` and every tool takes an `account` argument. A *tenant* MCP server is
   bound to one account: no `list_accounts`, no `account` argument (check the tool schema). On a tenant server skip step 1, leave `account` out of every call, pass
   `--mcp tenant`, and give `--account` the tenant's own short name (used for the report title and the saved-ticks key only).
1. **Find the account and its connector** (provider server only). Each provider connector lists its own accounts: call `list_accounts` on the connector the user names.
   The account name goes in every call as `account`. If the user gave an account but no
   connector, try `list_accounts` on each connector until the name appears; do not guess.
2. **Pick the week.** Default: the last 7 days ending today (UTC), first-seen date. Ask only if the user's wording is ambiguous (calendar week or rolling).
3. **Pull the incidents.** `agentportal_list_incidents` with `limit: 200`, newest first, paging with `offset` until the oldest incident is **older than the
   start of the week before** (the comparison needs it). Every reply is large and is saved to a file; do not paste it. Merge nothing by hand: pass each saved
   file to `--lists` (a bare list or `{"incidents":[...]}` both work).
4. **Read every incident that is not closed in full.** From the merged list take the incidents whose `status` is not `closed` and whose `first_seen_at` is in the
   week; call `agentportal_get_incident` for each (the id is the portal UUID) and save the replies in one folder (`--details`). Two reasons: the list's
   `latest_investigation` is not always the latest run (a ticket can show an older, higher rating than its last run), and the full record carries the live status
   and the reason a run was skipped. Closed incidents are not re-read; their action is the one in the list reply (say so in the report; it does).
5. **Optional analyst notes** (`--notes notes.json`): what the data cannot say by itself. Use sparingly, from what the investigations themselves reported:
   ```json
   {"tuning": [{"title": "…", "text": "…", "tickets": ["SOC-…"]}], "extra_gaps": ["…"]}
   ```
   `tuning` entries become the report's §5 list (keep each `text` to one sentence); `extra_gaps` are added to the method notes.
6. **Render:**
   ```
   python3 scripts/build_weekly_report.py --lists p1.json p2.json p3.json --details details/ --notes notes.json \
       --account <account> --display "<Tenant display name>" --start YYYY-MM-DD --end YYYY-MM-DD [--report-date YYYY-MM-DD] \
       --site-url https://<connector>.app.ingext.io [--mcp tenant] --out <dir>
   ```
   Writes one file, `Weekly_Incident_Report_<Account>_<DDMonYY>.html`. No PDF or CSV is produced; printing the HTML from a browser gives a clean page if one is needed.
   `--report-date` is the day the report is issued (default `--end`). Due dates are calendar dates from it: **P1 the same day, P2 seven days later, P3 fourteen days
   later** (constants `DUE_DAYS` in the script). The report never says "today" or "this week", because it is read after the day it was written.
   `--site-url` is the Fluency site of the MCP connector the account was listed on: the connector's own host, `https://<connector>.app.ingext.io`. Take it from the connector's endpoint, not from the tenant. Every entity then links (opens in a new tab, marked ↗) to its behavior-summary page:
   `<site>/v2/behavior-summary?dayIndex=<YYYYMMDD>&id=%22<entity key>%22&gridaccount=<account>` on a **provider** server (the default). On a **tenant** server (`--mcp tenant`) the
   link has no `gridaccount`: `<site>/v2/behavior-summary?dayIndex=<YYYYMMDD>&id=%22<entity key>%22`. The key and day come from the incident id (`<keyType>_<key>_<day>`), the account
   from the incident. This was checked against a real link copied from the page. `--link-template` overrides the whole URL (placeholders `{key} {day} {account} {key_type} {incident_id} {id}`,
   all URL-encoded) if the page ever moves. Without either option no links are shown. If the connector's host is not known (`open_companion` with a `server_name` returns the Fluency MCP's own local address, not a provider's), infer `https://<connector>.app.ingext.io` from the connector's name, say in the reply that it was inferred, and check that it answers (a plain GET returns 200). Do not invent a host that does not answer.
7. **Check the buckets** printed by the script add up (`open + confirm + settled = reported`) and read the §1 checklist once for sense. The script also prints how many
   incidents it left out for having no finished investigation yet; mention that count in your reply, not in the report.
8. **Reply briefly:** the headline, the P1 actions, the file names and the gaps.

## The checklist is interactive

The checklist in the HTML is a working tool, with no server and no dependency (one inline script, one `<details>` per row):

- **Tick off** an action; a progress bar counts actions done. A group (confirmations by type, close in the portal, optional suggestions, detection tuning) expands into one
  tickable line per entity and its box shows partial progress (3/5). Ticking the group ticks every entity.
- **Details** on each row: what the investigation found, impact if wrong, the full ask and the "if the answer is no" follow-up.
- **Copy** a message (one action) or **Copy open list** (everything not yet ticked, as a bullet list to paste into a ticket or chat).
- **Filter** All / P1 / P2 / P3 / Not done; **Expand all**; **Reset**.
- Ticks are saved in the viewer's browser (`localStorage`, keyed by account and week), so a reload keeps them. They are not shared; a colleague opening the file starts unticked.
  If the file is opened where storage is blocked, it still works for the session.
- **Open in Fluency**: with `--link-template`, each entity opens its incident page.
- **Printing** hides every control and the details, shows the checklist unticked, and adds static tables for confirmations, suggestions and close-in-portal (§2 to §4),
  because paper cannot be expanded.

## How an incident is sorted

Using the live status and the **latest finished investigation by time** (a run that failed or was skipped is never "latest").
**An incident with no finished investigation is not in the report at all** (not counted, not listed). It is reported in the week it is investigated: an incident first
seen in the week before whose investigation finished this week is included and counted as "from last week".

| Bucket | Rule | Where it appears |
|---|---|---|
| Open, needs an answer | status not closed and the investigation is `actionable` | §1 (P1 if medium or higher, or its rating moved; else P2), with its "if no" line |
| Closed, confirm | has a customer action and is `actionable` | §1 (one P2 group per type, one tick per entity) ; static list in §2 for print |
| Optional suggestion | has a customer action, not `actionable` | §1 (one P3 group); static list in §3 for print |
| Close in portal | status not closed, finished benign, no action | §1 (one P3 group); entity list in §4 for print |
| Settled | everything else | counted only |

§1 also gets a P3 line for the investigation-budget skips and one for the detection themes in `--notes`; §5 carries them, one sentence each.

The **entity** (user, guest, device or service account) identifies every row; the portal ticket key (SOC-…) is not shown. An entity that triggered several incidents appears once per incident, told apart by its first-seen date. In `--notes`, `tickets` may still be ticket keys; the
report prints their entities.

Severity is the investigation's, never the portal's risk score (not shown). An incident whose rating moved during the week (for
example confirmed, then downgraded) is flagged in §1 with its peak. The report never says "no compromise" without the rating behind it; it says none is **rated** confirmed.

## What the report will not do

- It does not invent actions: the "Confirm" and "If the answer is no" text are the investigation's own `customer_action`, split at the first conditional.
- It does not re-investigate or change any ticket; closing tickets and re-running investigations are listed as actions for a person.
- Closed incidents are summarised from the list reply; if their latest run changed after the list was cached, §2 can lag. Open incidents are always read live.
- Names in actions are users and help-desk staff as written in the investigation. This report is for the customer's security and IT team, not for a wider audience.
