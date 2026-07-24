---
name: setup-trendmicro-visionone-connector
version: 1.0.0
description: >-
  Set up the TrendMicro VisionOne connector on Fluency / Ingext: import Trend Vision One events
  via its public API. Guides the customer through the Trend-side work — generating an API key in
  the Vision One console (Administration → API Keys) with a least-privilege role, and picking the
  correct regional API base URL from Trend's published regional-domain list — with every step
  backed by Trend Micro's public automation documentation, then performs the Fluency-side install
  itself via create_connector. The Trend side is portal-only (an admin must click the console),
  so the agent guides those steps and does everything else. SELF-CONTAINED: it ends by creating
  the "TrendMicroVisionOne" connector itself — when routed from customer-onboarding, do NOT
  chain into add-connector afterward. Triggers: "add Trend Micro to Ingext", "connect Vision
  One", "import Trend Vision One events into Fluency", "set up the Trend Micro connector",
  "ingest Vision One alerts". Do NOT use for legacy Trend products — Apex One / Apex Central,
  Deep Security, or Cloud One are not Vision One and have no dedicated skill (check the live
  template list via add-connector) — and not for generic installs where the user already holds a
  working Vision One API key and just says "install connector X" — add-connector also handles
  that.
---

# Set up the TrendMicro VisionOne connector

Import **Trend Vision One** events into Fluency / Ingext via Trend's public (v3) API. Two
things are needed, and only one of them is yours to collect from the customer:

- **Trend side (customer's Vision One console):** an **API key**, created with a role whose
  permissions the key inherits, plus the **regional API base URL** for the tenant. Portal-only —
  guide it, step by step.
- **Fluency side (yours):** install the **`TrendMicroVisionOne`** connector (display name
  "TrendMicro VisionOne") with the regional base URL and that key. Do this for the operator via
  the MCP.

Vendor-side steps below are backed by Trend Micro's public Automation Center documentation;
citations live in `assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Trend Vision One | API key | Named `ingext-visionone`; role decides its permissions; value shown **once**; authentication tokens **expire one year after creation by default** (expiration is set in the dialog) |
| Ingext | Connector | Template **`TrendMicroVisionOne`** ("TrendMicro VisionOne"), instance e.g. `trendmicrovisionone`; the template carries no index parameter — confirm the live datalake table with `list_data_tables` |

Nothing here is billable on the Trend side.

---

## Prerequisites

- A **Trend Vision One administrator** who can open **Administration → API Keys** — a **Master
  Administrator** is the safe ask (Trend's docs note a Master Administrator manages token
  deletion/regeneration and role assignment).
- Knowing **which region** the Vision One tenant is hosted in (chosen at provisioning) — it
  determines the API base URL.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Vision One console cannot be driven by the agent — a Trend admin clicks those steps. Ask
(use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the API-key creation
  click-by-click, collect the two values (regional base URL, API key token), and then **you**
  create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Trend admin isn't in this conversation. Offer to resume the install step
  whenever they return with the values.

If the operator already has a working base URL and API key in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Trend side — create the API key (guided)

### 1 — Pick the regional API base URL

The connector's `baseURL` is the API domain for the region where the tenant is hosted. Trend
publishes exactly these regional domains:

| Region | `baseURL` |
|---|---|
| United States | `https://api.xdr.trendmicro.com` |
| United States (for Government) | `https://api.usgov.xdr.trendmicro.com` |
| Germany (EU) | `https://api.eu.xdr.trendmicro.com` |
| United Kingdom | `https://api.uk.xdr.trendmicro.com` |
| Japan | `https://api.xdr.trendmicro.co.jp` |
| Singapore | `https://api.sg.xdr.trendmicro.com` |
| Australia | `https://api.au.xdr.trendmicro.com` |
| India | `https://api.in.xdr.trendmicro.com` |
| United Arab Emirates | `https://api.mea.xdr.trendmicro.com` |

The tenant's region was chosen when it was provisioned; if the admin is unsure, have them
confirm it in the console or with Trend support rather than guessing — a wrong region simply
fails to authenticate.

### 2 — Create the API key

In the **Trend Vision One console**:

1. **Administration → API Keys** → **Add API Key**.
2. **Name:** `ingext-visionone`.
3. **Role:** the key inherits the permissions of the role you pick — predefined or custom.
   Trend's built-in roles are Master Administrator, Operator, Senior Analyst, Analyst, and
   **Auditor** ("read-only access to specific apps") — **Auditor is the least-privilege
   starting point** for a log-reading integration.
   **UNVERIFIED:** the exact permission set the Fluency connector polls with is not published,
   so whether Auditor covers every call can't be confirmed from documentation — if the
   connector reports permission errors after install, escalate to a custom role granting the
   needed read permissions (Administration → User Roles), or obtain the current recommendation
   from Trend Micro / Fluency support.
4. **Expiration time:** by default, authentication tokens **expire one year after creation** —
   set it deliberately and put the rotation on a calendar.
5. **Status:** enabled. Click **Add**.
6. **Copy and store the authentication token immediately** — you cannot see it again after
   clicking Close. This is the connector's `apiToken` parameter.

**Deliverables from this section:** `baseURL` + `apiToken` (the token is a credential — never
echo it back; refer to it as "the API key token from step 2").

---

## Ingext side — install the connector

With the two values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`TrendMicroVisionOne`** template
   ("TrendMicro VisionOne") and use its current parameter schema; the names below are a
   snapshot, not truth.
2. **`list_connectors`** — if a Vision One connector already exists, show its instance/state
   and confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `TrendMicroVisionOne`
   - `instance`: `trendmicrovisionone` (lowercase, ≤20 chars, **never `"default"`**; `-2`
     suffix on collision)
   - `displayName`: `TrendMicro VisionOne`
   - `inputParameters`: **every** template parameter — at the time of writing `baseURL` and
     `apiToken` (sensitive); if the live schema has grown more (e.g. datalake/index), include
     them too (user value → default → `""`).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add →
**TrendMicro VisionOne**, paste the regional base URL and the API key token, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake table (the template carries no index parameter, so the platform assigns it —
  confirm the live name with `list_data_tables`). Do not echo the API key token anywhere in the
  summary.
- **Latency expectation:** the connector polls the Vision One API; first events should land
  within roughly **15–30 minutes** — *if there are events to fetch*. A quiet tenant genuinely
  produces few alerts; compare with what the customer's own Vision One console shows for the
  same window before calling it broken. Mark ⏳ inside that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "TrendMicroVisionOne",
  "instance": "trendmicrovisionone",
  "index": "<confirm live with list_data_tables>",
  "region": "<regional API domain chosen in step 1>",
  "keyRole": "<role assigned to the API key>",
  "keyExpiry": "set at creation — default one year; rotate before it"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the Vision One datalake table over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first — the
   template has no index default). A plain row count is the smoke test.
3. Cross-check against the customer's own Vision One console — if it shows alerts/events for
   the same window and the datalake shows none past the latency window, move to Failure modes.
   If both are quiet, the tenant may genuinely be quiet.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / auth failure | Token mistyped (it was shown once), the key expired (default one year — check the date set at creation), its Status was toggled to disabled, or it was deleted/regenerated by a Master Administrator. Create a fresh key (step 2) and update the connector. |
| Wrong region base URL | Authentication fails against the wrong regional domain. Re-pick from the regional table in step 1 — the tenant's provisioning region is the truth, not a guess. |
| 403 / permission errors | The key's role is too narrow. Escalate per the UNVERIFIED note in step 2: a custom role with the needed read permissions, or Trend/Fluency support's current recommendation. |
| Token value not captured | Cannot be viewed again after Close. Delete the half-created key in Administration → API Keys and add a new one. |
| A Vision One connector already exists | Ask before adding a second instance (`trendmicrovisionone-2` — mind the 20-char limit when suffixing; shorten to e.g. `trendmicrovo-2` if needed); two instances polling the same tenant double the API load for no benefit unless they intentionally target different datalakes. |
| Customer runs Apex One / Deep Security / Cloud One | Legacy Trend products are not Vision One and have no dedicated skill — check the live template list via `add-connector`, or discuss migrating telemetry into Vision One with Trend. |

---

## Security notes

- The API key token is a credential: never paste it into logs, tickets, summaries, or
  long-lived chat beyond the `create_connector` call.
- **Least privilege lives in the role** — start from Auditor (read-only) and grant more only
  when the connector demonstrably needs it.
- Rotation: create a new key, update the connector, then delete the old key in
  **Administration → API Keys**. Do the same immediately if the token is ever exposed. Default
  expiry is one year — calendar it; a lapsed key stops ingestion silently.
- Prefer the **Status: disabled** toggle over deletion when investigating a suspected exposure —
  it stops the key without destroying the audit trail of its existence.

---

## Layout

```
setup-trendmicro-visionone-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Trend Micro documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
