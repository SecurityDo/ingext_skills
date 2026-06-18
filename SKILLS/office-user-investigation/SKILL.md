---
name: office-user-investigation
version: 1.0.0
description: >-
  Investigate a Microsoft 365 mailbox / Office 365 user by querying the
  Ingext/Fluency **Office365 datalake table directly with KQL** (Office 365
  Management Activity API data: Exchange, SharePoint, AzureActiveDirectory, DLP).
  Runs a fixed KQL set (workload, operations, per-IP summary, sign-ins, inbox
  rules, OAuth consents, daily timeline), geolocates every source IP offline
  (GeoLite2), and produces a self-contained HTML report with a GeoIP map plus an
  optional PDF. USE THIS SKILL WHEN the focus is MAILBOX / Office 365 activity —
  Exchange operations, malicious/hidden INBOX RULES (Business Email Compromise),
  OAuth application consents, mass deletes, and a geolocated source-IP map — OR
  when the Azure FPL reports / AzureSigninLogs tables are NOT deployed but an
  `Office365` datalake index exists. Triggers: "investigate O365/mailbox user X",
  "look into mailbox activity for X", "check this account for BEC / inbox rules",
  "run an Office user investigation", "geoip map of a user's logins".
  DO NOT use this when the goal is purely Azure AD / Entra sign-in history and
  directory-change auditing via the saved FPL reports — for that use the
  `azure-user-signin-investigation` skill instead.
---

# Office365 User Investigation (KQL-based)

Produce a single-page, self-contained HTML investigation report (+ optional PDF)
for a Microsoft 365 mailbox by querying the **Office365 audit table** in the
Ingext/Fluency datalake with KQL, geolocating every source IP offline, and
rendering a GeoIP map, KPI strip, findings, inbox-rule detail, per-country
tables, sign-in timeline and recommendations.

This is **distinct** from `azure-user-signin-investigation`, which depends on three
FPL reports and the `AzureSigninLogs`/`AzureAuditLogs` tables and focuses on Azure
AD sign-in history + directory changes. This skill needs only an `Office365`
datalake index (Office 365 Management Activity API data) and focuses on mailbox /
Exchange activity, inbox rules, OAuth consents and a geolocated source-IP map.

## Required inputs

| Argument | Meaning | Example |
|---|---|---|
| `username` | UPN / login of the mailbox | `user@contoso.com` |
| `from` / `to` | Window as **epoch milliseconds** | `1773862340254` |
| connector | Which Ingext/Fluency MCP connector (tenant) | e.g. the Anico connector |

If any are missing, use `AskUserQuestion` first. Offer time presets and convert
to ms yourself: Last 24h = `now-86_400_000`, 7d = `now-604_800_000`,
30d = `now-2_592_000_000`, 90d = `now-7_776_000_000`.
Match `username` **case-insensitively** — the stored `UserId` casing often
differs from what the user types.

---

## Pipeline

```
1. Confirm the Office365 index exists  (list_indexes -> look for datalakeIndex "Office365")
   └─ absent -> stop, tell the user this tenant has no Office365 datalake table
2. Collect username / from / to        (AskUserQuestion if missing)
3. Run the KQL queries below via kql_search (pass rangeFrom/rangeTo = from/to ms)
   Save each raw tool result to <workdir>/<name>.json
4. (optional) get_azure_user_record    -> <workdir>/user_record.json
5. Ensure country outlines exist for every country the data geolocates to
   (see "Country outlines" below)
6. Run scripts/build_report.py         -> HTML (+ PDF)
7. Share the HTML and/or PDF with present_files
```

Use a scratch working dir, e.g. `mkdir -p /tmp/oui_work`.

---

## Step 1 — Confirm the Office365 index

Call `list_indexes` on the connector. Confirm an entry whose `datalakeIndex` is
`Office365`. If absent, stop and report that this tenant doesn't ingest Office365
audit data, so this skill can't run. Optionally `describe_schema Office365` — the
useful audit fields (`UserId`, `Operation`, `Workload`, `ResultStatus`,
`ClientIP`, `Parameters`, `ModifiedProperties`, `Target`, `Actor`, `timestamp`)
are dynamic JSON columns and can be projected directly.

---

## Step 2 — Run the KQL queries

Run each with `kql_search`, passing `rangeFrom`=`<from_ms>` and `rangeTo`=`<to_ms>`.
Replace `{USER}` with the **lower-cased** UPN. Save each raw tool result JSON to
the filename shown (the build script parses the raw `data.Tables[0]` shape).

`ip_summary.json` is **required**; the rest are optional but recommended.

**ip_summary.json** (master table — drives the map, KPIs, IP tables):
```kql
Office365
| where tolower(UserId) == "{USER}"
| where isnotempty(ClientIP)
| summarize events=count(),
            logins=countif(Operation=="UserLoggedIn"),
            failed=countif(Operation=="UserLoginFailed"),
            sends=countif(Operation=="Send"),
            firstSeen=min(timestamp), lastSeen=max(timestamp)
  by ClientIP
| sort by events desc
| take 200
```

**workload.json**:
```kql
Office365 | where tolower(UserId) == "{USER}"
| summarize events=count() by Workload | sort by events desc
```

**operation.json**:
```kql
Office365 | where tolower(UserId) == "{USER}"
| summarize events=count() by Operation | sort by events desc | take 40
```

**inbox_rules.json** (BEC smoking gun — keep Parameters):
```kql
Office365 | where tolower(UserId) == "{USER}"
| where Operation in ("New-InboxRule","Set-InboxRule","UpdateInboxRules")
| project timestamp, Operation, ClientIP, ResultStatus, Parameters, ModifiedProperties, ExtendedProperties
| sort by timestamp asc | take 100
```

**oauth.json** (illicit consent):
```kql
Office365 | where tolower(UserId) == "{USER}"
| where Operation in ("Consent to application.","Add delegated permission grant.","Add app role assignment grant to user.")
| project timestamp, Operation, ClientIP, ResultStatus, ModifiedProperties, ExtendedProperties, Target, Actor
| sort by timestamp asc
```

**timeline.json** (daily sign-in bars):
```kql
Office365 | where tolower(UserId) == "{USER}"
| where Operation in ("UserLoggedIn","UserLoginFailed")
| summarize logins=count() by bin(timestamp, 1d), Operation
| sort by timestamp asc
```

> If a `get_report_result`/`kql_search` returns "Output too large", it is saved
> to a file path — read that file and save the `data` object to the `<name>.json`
> instead. Saving the entire raw tool result is fine; the parser is tolerant.

---

## Step 3 — Country outlines for the map

`build_report.py` draws country borders from `assets/countries/<ISO3>.geo.json`.
Seeded: **USA, ESP, IRN, GBR, DEU, DNK**. Dots are always plotted regardless; only
the *outline* needs a file. After you know which countries the IPs resolve to (the
build script prints `WARN: no outline bundled for ISO3: XXX,YYY` if any are
missing), fetch the missing ones and drop them in `<workdir>/countries/`:

- Use **web_fetch** (do not use curl/urllib) on
  `https://raw.githubusercontent.com/johan/world.geo.json/master/countries/<ISO3>.geo.json`
- Save the JSON to `<workdir>/countries/<ISO3>.geo.json`
- Re-run the build. To make a country permanent, copy it into
  `assets/countries/` in this skill.

ISO2→ISO3 mapping is bundled at `assets/iso2_to_iso3.json`.

---

## Step 4 — Build the report (and PDF)

First run only — install deps in the sandbox:
```bash
pip install maxminddb-geolite2 weasyprint --break-system-packages -q
```

Then:
```bash
python3 <SKILL_DIR>/scripts/build_report.py \
  --workdir   /tmp/oui_work \
  --skill-dir <SKILL_DIR> \
  --username  "user@contoso.com" \
  --from-ms   <from_ms> \
  --to-ms     <to_ms> \
  --output    /tmp/oui_work/o365_investigation.html \
  --pdf       /tmp/oui_work/o365_investigation.pdf
```

Notes:
- Geolocation is **offline** (GeoLite2) — always caption it as approximate and
  recommend live threat-intel verification before formal attribution.
- The PDF is rendered with WeasyPrint (no browser needed). If WeasyPrint can't
  load its system libs, drop `--pdf` and convert the HTML with the
  `html-to-pdf` skill instead.
- The script derives the **home country** from the highest-event IP, classifies
  every other-country IP as `foreign`, and any inbox-rule-creating IP as
  `attacker`. Verdict severity is computed from these signals.

---

## Step 5 — Share

Copy the HTML/PDF to the workspace output folder and share with `present_files`.
Add a one-line chat summary of the single most significant finding (e.g.
"Likely active BEC — 6 hidden inbox rules created from foreign IPs, mailbox still
being accessed today").

---

## Layout

```
office-user-investigation/
├── SKILL.md
├── assets/
│   ├── iso2_to_iso3.json          # ISO2 -> ISO3 for outline fetching
│   └── countries/                 # <ISO3>.geo.json outlines (seeded: USA,ESP,IRN,GBR,DEU,DNK)
└── scripts/
    └── build_report.py            # geolocate + map + tables + narrative -> HTML (+PDF)
```

## Failure modes

| Situation | Response |
|---|---|
| No `Office365` index on the tenant | Stop; tell the user this skill needs Office365 datalake data |
| `ip_summary.json` empty | The user has no ClientIP-bearing events in the window; report "no activity found" |
| Country outline missing | Build still works; dots plot, that country has no border — fetch its `<ISO3>.geo.json` |
| WeasyPrint libs missing | Build HTML only; convert via the `html-to-pdf` skill |
