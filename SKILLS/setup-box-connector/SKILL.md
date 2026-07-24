---
name: setup-box-connector
version: 1.0.0
description: >-
  Set up the box.com connector on Fluency / Ingext: import Box enterprise events (the
  admin_logs audit stream — logins, downloads, sharing, admin changes) via the Box API. Guides
  the customer through the Box-side work — creating a Platform App with Client Credentials
  Grant, granting App + Enterprise Access and the "Manage enterprise properties" scope, having
  a Box Admin authorize the app in the Admin Console, and collecting the Client ID / Client
  Secret / Enterprise ID — with every step backed by Box developer documentation, then performs
  the Fluency-side install itself via create_connector. The Box side is portal-only (the
  Developer Console and Admin Console are clicked by the customer; there is no agent-drivable
  CLI), so the agent guides those steps and does everything else. SELF-CONTAINED: it ends by
  creating the "BoxCom" connector itself — when routed from customer-onboarding, do NOT chain
  into add-connector afterward. Triggers: "add Box to Ingext", "connect our Box enterprise",
  "import Box audit events into Fluency", "set up the box.com connector", "start ingesting Box
  admin logs". Do NOT use for generic connector installs where the user already holds working
  Box app credentials and just says "install connector X" — add-connector also handles that —
  and not for other file-sharing platforms (Dropbox, OneDrive/SharePoint are the Microsoft 365
  path, Google Drive is the Google Workspace path) or for Box file management tasks.
---

# Set up the box.com connector

Import **Box enterprise events** — the `admin_logs` audit stream covering logins, file
downloads, sharing, and admin changes across the whole enterprise — into Fluency / Ingext via
the Box API. Two things are needed, and only one of them is yours to collect from the customer:

- **Box side (customer's Developer Console + Admin Console):** a **Platform App** using
  **Client Credentials Grant** with enterprise access and the events-reading scope, authorized
  by a Box Admin. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`BoxCom`** connector (display name "box.com") with
  the Client ID, Client Secret, and Enterprise ID. Do this for the operator via the MCP.

Vendor-side steps below are backed by Box developer documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Box | Platform App (Server authentication) | Client Credentials Grant; **App + Enterprise Access**; application scope **Manage enterprise properties** only; must be **authorized by an Admin** in the Admin Console before tokens work |
| Ingext | Connector | Template **`BoxCom`** ("box.com"), instance e.g. `boxcom`; the template has **no `index` parameter** — confirm the live datalake table with `list_data_tables` after install |

Nothing here is billable on the Box side. The enterprise event stream is an enterprise
feature — a personal/free Box account has no Admin Console and nothing for this connector to
read.

---

## Prerequisites

- A **Box Admin (or Co-Admin)** — enterprise accounts require admin authorization of the app
  before its tokens work, and the Admin Console is where that happens. (A non-admin developer
  can create the app and submit it for approval; an Admin/Co-Admin can authorize directly.)
- **Two-factor authentication enabled** on the Box account that will reveal the app's client
  secret — the Developer Console requires 2FA to fetch it.
- The org's **Enterprise ID** (the runbook shows two places to read it).
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Box Developer Console and Admin Console cannot be driven by the agent — the customer clicks
those steps. Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the customer through app creation,
  scoping, and admin authorization click-by-click, collect the three values (Client ID, Client
  Secret, Enterprise ID), and then **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Box admin isn't in this conversation. Offer to resume the install step whenever
  they return with the values.

If the operator already has an authorized app's credentials in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Box side — create and authorize the Platform App (guided)

### 1 — Create the app (Developer Console)

In the **Box Developer Console**:

1. Create a **New App** and choose the **Server** application type ("Server Authentication").
2. **Client Credentials Grant (CCG)** is the default authentication method for new Server
   Authentication apps — keep it.

### 2 — Configure access and scope (least privilege)

On the app's **Configuration** tab:

1. **App Access Level** → select **App + Enterprise Access**. (The default level reaches only
   the app's own service account; enterprise events need enterprise access.)
2. **Application Scopes** → check **Manage enterprise properties** (technical name
   `manage_enterprise_properties`) — Box documents it as allowing the app to "view the
   enterprise event stream", which is exactly what the connector reads.
3. Leave every other scope unchecked — especially write-capable ones. Nothing else is needed.
4. Save the configuration.

> The `admin_logs` events stream "returns all events for an entire enterprise" and requires
> admin-level access — for this connector that is satisfied by the CCG app's enterprise token
> plus the scope above, once an admin authorizes the app in step 4.

### 3 — Collect the three values

- **Client ID** — Configuration tab → **OAuth 2.0 Credentials** section.
- **Client Secret** — same section; the console requires **2FA enabled** on the viewing
  account before it will reveal the secret. **A credential; treat it like a password.**
- **Enterprise ID** — the app's **General Settings** tab shows it (Box labels it the "Box
  Subject ID" for CCG); a Box admin can also read it in **Admin Console → Account & Billing**
  (Account Information). The connector uses it because CCG enterprise tokens are requested with
  `box_subject_type=enterprise` and `box_subject_id=<Enterprise ID>`.

### 4 — Authorize the app in the Admin Console (Admin/Co-Admin)

Tokens do not work until the app is authorized. Two routes:

- **Developer submits:** on the Configuration tab, the developer is prompted to **submit the
  app for authorization** — the Admin/Co-Admin gets an email and approves or denies it.
- **Admin adds directly:** a Box Admin or Co-Admin opens **Admin Console → Platform →
  Platform Apps**, clicks **Add**, and pastes the app's **Client ID**. (Older Admin Console
  layouts reach the same manager via **Apps → Platform Apps Manager** / **Custom Apps
  Manager** — a secondary-cited variation; see references.)

> **Reauthorization gotcha:** if the app's scopes or access level ever change, the app **must
> be re-authorized** by the admin for the change to take effect — a scope added in the
> Developer Console silently does nothing until then.

**Deliverables from this section:** `ClientID` + `ClientSecret` + `EnterpriseID` (the client
secret is a credential — never echo it back; refer to it as "the client secret from step 3").

---

## Ingext side — install the connector

With the three values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`BoxCom`** template ("box.com") and use
   its current parameter schema; the names below are a snapshot, not truth (note the
   capitalized parameter names in the snapshot).
2. **`list_connectors`** — if a Box connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `BoxCom`
   - `instance`: `boxcom` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `box.com`
   - `inputParameters`: **every** template parameter — `ClientID`, `ClientSecret` (sensitive),
     `EnterpriseID`.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **box.com**,
paste the three values, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake table. **This template defines no `index` parameter**, so the table name must be
  confirmed live with `list_data_tables` — do not guess it into the checklist. Do not echo the
  client secret anywhere in the summary.
- **Latency expectation:** the connector polls the Box API; with any activity in the
  enterprise, first events should land within roughly **15–30 minutes** — and Box's historical
  `admin_logs` feed deliberately trades latency for completeness (chronological, de-duplicated,
  but slower than real time), so events can trail the action that caused them. Mark ⏳ inside
  that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "BoxCom",
  "instance": "boxcom",
  "enterpriseID": "<Enterprise ID>",
  "index": "confirm live via list_data_tables (template has no index parameter)",
  "appAuthorization": "authorized in Box Admin Console (re-authorize after any scope change)"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **`list_data_tables`** — identify which datalake table the connector writes; the template
   carries no `index` parameter, so the live listing is the only source of truth for the name.
3. After ~15–30 min, count rows in that table over the last hour via the **`ingext-kql`**
   skill. A plain row count is the smoke test.
4. Cross-check against Box's own admin-side event views/reports — if the enterprise plainly has
   activity in the window and the datalake shows nothing past the latency window (allowing for
   the `admin_logs` feed's completeness-over-latency lag), move to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Token request fails / unauthorized | The classic cause, per Box's docs: "Your application has not been authorized in the Box Admin Console." Complete step 4 — or, if scopes/access level changed since authorization, have the admin **Reauthorize App**. |
| Wrong Enterprise ID | CCG enterprise tokens use `box_subject_id=<Enterprise ID>` — a wrong or foreign ID fails. Re-read it from the app's General Settings tab (or Admin Console → Account & Billing) and update the connector. |
| Authenticated but events call is denied | The app lacks **Manage enterprise properties**, or the scope was added but the app was never re-authorized. Check the scope, then re-authorize, in that order. |
| Client secret can't be viewed | The Developer Console requires **2FA enabled** on the account fetching the secret. Enable 2FA on that Box account and retry. |
| App access level left at default | Default CCG apps reach only their own service account — enterprise events need **App + Enterprise Access**. Change it, save, and **re-authorize**. |
| Zero rows, healthy connector | A quiet enterprise, plus the `admin_logs` feed's deliberate latency. Give it the full window and compare against Box-side activity before debugging. |
| A Box connector already exists | Ask before adding a second instance (`boxcom-2`); two instances polling the same enterprise double the API load for no benefit. |

---

## Security notes

- The client secret is a credential: never paste it into logs, tickets, summaries, or
  long-lived chat beyond the `create_connector` call.
- **Least privilege lives in the scope checkboxes** — grant `Manage enterprise properties`
  only. It is a powerful scope (enterprise event stream, enterprise attributes/reports), which
  is exactly why nothing else should be added alongside it.
- Rotation: credentials live in the app's Configuration tab (OAuth 2.0 Credentials). If the
  secret is ever exposed, generate a replacement there and update the connector immediately —
  and remember any app-setting change may require the admin to re-authorize the app.
- The app's power is bounded by admin authorization — an admin can revoke or re-scope it in
  the Admin Console's Platform Apps manager at any time, which is the kill switch if the
  credential leaks.

---

## Layout

```
setup-box-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Box documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
