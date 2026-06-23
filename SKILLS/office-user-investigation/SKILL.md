---
name: office-user-investigation
version: 1.0.2
description: >-
  Investigate a Microsoft 365 mailbox / Office 365 user by querying the Office365 datalake
  table directly with KQL (Exchange, SharePoint, AzureActiveDirectory, DLP). Runs a fixed KQL
  set (workload, operations, per-IP summary, sign-ins, inbox rules, OAuth consents, daily
  timeline); the per-IP query returns each IP's country / city / ISP / coordinates from the
  platform GeoIP enrichment, so no IP lookup is needed. Produces a self-contained HTML report
  (source-IP map) and optional PDF. Use for mailbox / Office 365 activity — Exchange operations,
  hidden inbox rules (Business Email Compromise), OAuth consents, mass deletes — or when the Azure
  FPL reports / AzureSigninLogs are not deployed but an Office365 table exists. Triggers:
  "investigate O365/mailbox user X", "look into mailbox activity for X", "check this account for
  BEC / inbox rules", "geoip map of a user's logins". Do NOT use when the goal is purely Azure AD
  sign-in history and directory-change auditing — use the azure-user-signin-investigation skill.
---

# Office365 User Investigation (KQL-based)

Produce a single-page, self-contained HTML investigation report (+ optional PDF)
for a Microsoft 365 mailbox by querying the **Office365 audit table** in the
Ingext/Fluency datalake with KQL. The per-IP query returns each source IP's
country / city / ISP / coordinates from the platform GeoIP enrichment, so the
report needs **no separate IP-geolocation lookup**. It renders a source-IP map,
KPI strip, findings, inbox-rule detail, per-country tables, sign-in timeline and
recommendations.

This is **distinct** from `azure-user-signin-investigation`, which depends on three
FPL reports and the `AzureSigninLogs`/`AzureAuditLogs` tables and focuses on Azure
AD sign-in history + directory changes. This skill needs only an `Office365`
data table (Office 365 Management Activity API data) and focuses on mailbox /
Exchange activity, inbox rules, OAuth consents and a geolocated source-IP map.

## Required inputs

| Argument | Meaning | Example |
|---|---|---|
| `username` | UPN / login of the mailbox | `user@contoso.com` |
| `from` / `to` | Window as **epoch milliseconds** | `1773862340254` |
| connector | Which Ingext/Fluency MCP connector (tenant) | e.g. the Anico connector |

`username` is required — if it's missing, use `AskUserQuestion` to collect it. Match `username`
**case-insensitively** — the stored `UserId` casing often differs from what the user types.

### Time range → epoch milliseconds

If the user already supplied `from` and `to` in their message, use those values directly.
**If no time range is supplied, default to the last 7 days and proceed without asking**
(`from = now_ms - 604_800_000`, `to = now_ms`). Only use `AskUserQuestion` to offer preset
time-range options if the user wants to choose a window, and convert the chosen option to
milliseconds. `now_ms` is the authoritative millisecond epoch from the CURRENT TIME block of your
system prompt — use it verbatim, do not recompute it. `to = now_ms`, and:
  - **Last 24 h**: `from = now_ms - 86_400_000`
  - **Last 7 days** (default): `from = now_ms - 604_800_000`
  - **Last 30 days**: `from = now_ms - 2_592_000_000`
  - **Last 90 days**: `from = now_ms - 7_776_000_000`

Sanity check before running the queries: the year in the human-readable label you showed the user
must equal the year of the epoch you pass. If they differ, you computed the epoch wrong — recompute
from `now_ms`.

---

## Pipeline

```
1. Confirm the Office365 table exists  (list_data_tables -> look for the "Office365" table)
   └─ absent -> stop, tell the user this tenant has no Office365 datalake table
2. Collect username (AskUserQuestion if missing); default window = last 7 days if unspecified
3. Run the KQL queries below via kql_search (pass rangeFrom/rangeTo = from/to ms)
   Save each raw tool result to <workdir>/<name>.json
4. (optional) get_azure_user_record    -> <workdir>/user_record.json
5. Run scripts/build_report.py         -> HTML (+ PDF)
   (country outlines for the map are already bundled — nothing to fetch)
6. Share the HTML and/or PDF with present_files
```

Use a scratch working dir, e.g. `mkdir -p /tmp/oui_work`.

---

## Step 1 — Confirm the Office365 table

Call `list_data_tables` on the connector. Confirm an `Office365` table appears (in
`streamTables`). If absent, stop and report that this tenant doesn't ingest Office365
audit data, so this skill can't run. The useful audit fields (`UserId`, `Operation`,
`Workload`, `ResultStatus`, `ClientIP`, `Parameters`, `ModifiedProperties`, `Target`,
`Actor`, `timestamp`) are dynamic JSON columns and can be projected directly.

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
| where Operation in ("UserLoggedIn","UserLoginFailed")   // login events only - avoids service-side / internal Microsoft IPs
| where isnotempty(ClientIP)
| summarize events=count(),
            logins=countif(Operation=="UserLoggedIn"),
            failed=countif(Operation=="UserLoginFailed"),
            firstSeen=min(timestamp), lastSeen=max(timestamp)
  by ClientIP,
     Country=tostring(_ip.country), CC=tostring(_ip.countryCode), City=tostring(_ip.city),
     ISP=tostring(_ip.isp), Lat=todouble(_ip.latitude), Lon=todouble(_ip.longitude)
| sort by events desc
| take 200
```

> **Login-only + platform geo (v1.0.2):** the IP summary filters to `UserLoggedIn` /
> `UserLoginFailed` so service-side events from internal Microsoft IP ranges (OneDrive /
> SharePoint backends) are not mistaken for user sign-in locations. Each IP carries its
> `Country`, `CC`, `City`, `ISP`, `Lat`, `Lon` from the platform `_ip` enrichment, so this
> query returns everything the report needs to place the IP — **no GeoIP lookup is performed.**
> `build_report.py` plots `Lat`/`Lon` directly. (If a tenant's `_ip` enrichment is missing
> these fields, the IP is listed without a map dot rather than looked up.)

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
**All ~175 sovereign countries are pre-bundled** (simplified 110m Natural Earth
outlines), so in normal use there is **nothing to fetch** — just run the build.
Dots are always plotted regardless; the outline file only adds the border.

If the build script ever prints `WARN: no outline bundled for ISO3: XXX` for a
minor territory not in the standard set (e.g. a dependency GeoIP maps to its own
ISO3), it's cosmetic — the dot still plots.

> **Do NOT look up a missing country.** Do not fetch its outline from the web or
> any external source. The bundled set is authoritative for this skill; a missing
> entry is a rare minor territory and the dot already conveys the location. If a
> border is genuinely worth adding, **estimate a rough outline from your own
> knowledge** — write an approximate `<ISO3>.geo.json` (a one-feature
> `FeatureCollection` with a `Polygon`/`MultiPolygon` geometry) into
> `<workdir>/countries/` and re-run. Treat it as indicative only, never as
> authoritative geolocation.

ISO2→ISO3 mapping is bundled at `assets/iso2_to_iso3.json`.

---

## Step 4 — Build the report (and PDF)

First run only — install deps in the sandbox (PDF rendering only; no GeoIP package needed):
```bash
pip install weasyprint --break-system-packages -q
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
- Geolocation comes from the query's platform `_ip` enrichment (country / city / ISP /
  coordinates) — **no IP lookup is performed**. Still caption it as approximate and recommend
  live threat-intel verification before formal attribution.
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
│   ├── iso2_to_iso3.json          # ISO2 -> ISO3 (maps query CC to the outline filename)
│   └── countries/                 # <ISO3>.geo.json outlines — all ~175 sovereign countries pre-bundled
└── scripts/
    └── build_report.py            # map (from query geo) + tables + narrative -> HTML (+PDF)
```

## Failure modes

| Situation | Response |
|---|---|
| No `Office365` table on the tenant | Stop; tell the user this skill needs Office365 datalake data |
| `ip_summary.json` empty | The user has no ClientIP-bearing events in the window; report "no activity found" |
| Country outline missing | Rare (all sovereign countries pre-bundled); build still works and dots plot. **Do not look it up** — if a border is worth adding, estimate a rough outline from your own knowledge |
| WeasyPrint libs missing | Build HTML only; convert via the `html-to-pdf` skill |
