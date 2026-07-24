---
name: setup-duo-connector
version: 1.0.0
description: >-
  Set up the Cisco Duo connector on Fluency / Ingext: import Duo authentication, telephony, and
  administrator action logs via the Duo Admin API. Guides the customer through the Duo-side
  work — an Owner-role admin protecting the "Admin API" application in the Duo Admin Panel with
  the read-only "Grant read log" permission and collecting the integration key / secret key /
  API hostname — with every step backed by Duo documentation, then performs the Fluency-side
  install itself via create_connector. The Duo side is portal-only (a Duo Owner must click the
  Admin Panel; there is no agent-drivable CLI), so the agent guides those steps and does
  everything else. SELF-CONTAINED: it ends by creating the "Duo" connector itself — when routed
  from customer-onboarding, do NOT chain into add-connector afterward. Triggers: "add Duo to
  Ingext", "connect Cisco Duo", "import Duo authentication logs into Fluency", "set up the Duo
  connector", "start ingesting Duo MFA events". Do NOT use for generic connector installs where
  the user already holds working Admin API credentials and just says "install connector X" —
  add-connector also handles that — and not for Cisco firewall/router sources (Cisco ASA and
  Cisco Meraki are separate syslog templates via add-connector) or for setting up Duo MFA/SSO
  protection itself.
---

# Set up the Cisco Duo connector

Import **Duo logs** — authentication outcomes, MFA pushes, telephony, and administrator
actions — into Fluency / Ingext via the **Duo Admin API**. Two things are needed, and only one
of them is yours to collect from the customer:

- **Duo side (customer's Admin Panel):** an **Admin API application**, created by a Duo
  **Owner**, restricted to the read-only log permission. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`Duo`** connector (display name "Cisco Duo Admin API")
  with the integration key, secret key, and API hostname. Do this for the operator via the MCP.

Vendor-side steps below are backed by Duo documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Duo | Admin API application | From the Application Catalog; yields **integration key**, **secret key**, **API hostname**; permissions cut down to **Grant read log** only |
| Ingext | Connector | Template **`Duo`** ("Cisco Duo Admin API"), instance e.g. `duo`, datalake index default `Duo` |

Nothing here is billable on the Duo side, but the Admin API application is available to **Duo
Premier, Duo Advantage, and Duo Essentials** plan customers — confirm the org is on one of
those editions before starting.

---

## Prerequisites

- A Duo administrator with the **Owner** role — only Owners can create or modify an Admin API
  application in the Duo Admin Panel. A lesser admin role cannot complete the vendor side.
- A Duo edition that includes the Admin API (Essentials / Advantage / Premier — see above).
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Duo Admin Panel cannot be driven by the agent — a Duo Owner clicks those steps. Ask
(use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the Owner through protecting the Admin
  API application click-by-click, collect the three values (integration key, secret key, API
  hostname), and then **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Duo Owner isn't in this conversation. Offer to resume the install step whenever
  they return with the values.

If the operator already has working Admin API credentials in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Duo side — protect the Admin API application (guided)

### 1 — Create the Admin API application (Owner only)

In the **Duo Admin Panel** (signed in as an **Owner**):

1. Go to **Applications → Application Catalog**.
2. Find the **Admin API** entry and add it (**+ Add**).
3. The new application's page shows the three values the connector needs:
   - **Integration key** (ikey) → connector parameter `integrationKey`
   - **Secret key** (skey) → connector parameter `secretKey` — **a credential; shown in the
     panel; treat it like a password**
   - **API hostname** (e.g. `api-XXXXXXXX.duosecurity.com`) → connector parameter `apiHostname`

If the Owner cannot find the Admin API entry in the catalog, the org's Duo edition may not
include it — see Prerequisites.

### 2 — Cut permissions down to logs only (least privilege)

Admin API permissions are checkboxes on the application's page. For log ingestion the
connector needs exactly one:

- **Check `Grant read log`** — this covers "authentication, offline access, telephony, and
  administrator action log information", which is everything the connector reads.
- **Uncheck everything else** — `Grant resource - Read`, `Grant resource - Write`,
  `Grant applications`, `Grant settings`, `Grant administrators`. None of them are needed, and
  each one widens what a leaked secret key could do.

Save the application settings.

### 3 — Collect the three values

Have the admin copy the **integration key**, **secret key**, and **API hostname** from the
application page. The API hostname is the bare `api-XXXXXXXX.duosecurity.com` host — no
`https://` prefix, no path.

**Deliverables from this section:** `integrationKey` + `secretKey` + `apiHostname` (the secret
key is a credential — never echo it back; refer to it as "the secret key from step 1").

---

## Ingext side — install the connector

With the three values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`Duo`** template ("Cisco Duo Admin API")
   and use its current parameter schema; the names below are a snapshot, not truth.
2. **`list_connectors`** — if a Duo connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `Duo`
   - `instance`: `duo` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on collision)
   - `displayName`: `Cisco Duo Admin API`
   - `inputParameters`: **every** template parameter — `integrationKey`, `secretKey`
     (sensitive), `apiHostname`, and the defaulted `datalake` (`managed`) / `index` (`Duo`)
     unless the operator wants otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Cisco Duo
Admin API**, paste the three values, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake index (default `Duo`; confirm the live table name with `list_data_tables`). Do
  not echo the secret key anywhere in the summary.
- **Latency expectation:** the connector polls the Duo Admin API; with any authentication
  activity in the org, first events should land within roughly **15–30 minutes**. A small org
  outside working hours may genuinely have few authentications — check Duo's own Reports in the
  Admin Panel for comparison before calling it broken. Mark ⏳ inside that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "Duo",
  "instance": "duo",
  "index": "Duo",
  "apiHostname": "api-XXXXXXXX.duosecurity.com",
  "permissions": "Grant read log only (authentication, telephony, offline access, admin action logs)"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the `Duo` datalake index over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first). A plain
   row count is the smoke test.
3. Cross-check against the customer's own Duo Admin Panel reports (authentication log) — if Duo
   shows events for the same window and the datalake shows none past the latency window, move
   to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with authentication / 401-class failures | Integration key or secret key mistyped, or the secret key was reset in Duo (a reset kills the old value immediately). Re-copy both from the application page — or reset and update the connector. |
| Permission / 403-class failures | The Admin API application is missing **Grant read log**. Have the Owner re-open the application and check it; other unchecked permissions are fine and should stay unchecked. |
| Wrong API hostname | The value must be the org's own `api-XXXXXXXX.duosecurity.com` host from the application page — not `admin.duosecurity.com`, not a URL with `https://`. |
| Admin API entry missing from the Application Catalog | The Duo edition doesn't include it (Admin API is on Essentials / Advantage / Premier) or the signed-in admin isn't an **Owner**. Fix the role first — only Owners see and manage Admin API applications. |
| Events flowed, then stopped | Check (in order): was the secret key reset in Duo without updating the connector? Was the application deleted or its permissions edited? Duo API rate limits (sustained throttling slows polling but should recover). |
| A Duo connector already exists | Ask before adding a second instance (`duo-2`); two instances polling the same Duo account double the API load for no benefit unless they target different datalake indexes on purpose. |

---

## Security notes

- The secret key is a credential: never paste it into logs, tickets, summaries, or long-lived
  chat beyond the `create_connector` call. Duo's own guidance: "Treat your secret key like a
  password."
- **Least privilege lives in the permission checkboxes** — an Admin API application with only
  `Grant read log` can read logs and nothing else. Leave every write-capable permission
  unchecked.
- Rotation: the application page has a **Reset Secret Key** action. The old key is invalid the
  moment it's reset — update the connector with the new value in the same sitting, or ingestion
  stops. Do this immediately if the key is ever exposed.
- Only **Owner**-role admins can modify (or delete) the Admin API application — a useful
  containment property, but also why offboarding the last Owner needs planning.

---

## Layout

```
setup-duo-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Duo documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
