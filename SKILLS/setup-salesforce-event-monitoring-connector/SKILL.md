---
name: setup-salesforce-event-monitoring-connector
version: 1.0.0
description: >-
  Set up the Salesforce Event Monitoring connector on Fluency / Ingext: import Salesforce
  EventLogFile data (logins, API activity, report exports, and other event types) via the
  Salesforce API. HARD PREREQUISITE: full Event Monitoring requires the Event Monitoring add-on
  license (standalone or as part of Salesforce Shield) — without it only a small free subset of
  log types exists. Guides the customer through the Salesforce-side work — a dedicated run-as
  integration user with the "API Enabled" and "View Event Log Files" permissions, and an
  External Client App (or legacy Connected App) using the OAuth client credentials flow — with
  every step backed by Salesforce documentation, then performs the Fluency-side install itself
  via create_connector. The Salesforce Setup UI is portal-only (a Salesforce admin must click
  it), so the agent guides those steps and does everything else. SELF-CONTAINED: it ends by
  creating the "SalesforceEM" connector itself — when routed from customer-onboarding, do NOT
  chain into add-connector afterward. Triggers: "add Salesforce to Ingext", "connect Salesforce
  event monitoring", "import Salesforce EventLogFile into Fluency", "set up the Salesforce
  connector", "ingest Salesforce audit logs". Do NOT use for Salesforce Marketing Cloud or
  Commerce Cloud logs (different products, no template), and not for generic connector installs
  where the user already holds a working consumer key/secret and base URL and just says
  "install connector X" — add-connector also handles that.
---

# Set up the Salesforce Event Monitoring connector

Import **Salesforce Event Monitoring** data — the `EventLogFile` event types covering logins,
API calls, report exports, and more — into Fluency / Ingext via the Salesforce API. Two things
are needed, and only one of them is yours to collect from the customer:

- **Salesforce side (customer's Setup UI):** an app (External Client App, or a legacy Connected
  App) with the **OAuth client credentials flow** enabled, running as a least-privilege
  integration user. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`SalesforceEM`** connector (display name "Salesforce
  Event Monitoring") with the org's My Domain URL, consumer key, and consumer secret. Do this
  for the operator via the MCP.

> **Hard prerequisite — say this before anything else:** full Event Monitoring requires the
> **Event Monitoring add-on license** (sold standalone or as part of **Salesforce Shield**).
> Without it, the org generates only a small free subset of log types (Login, Logout, API Total
> Usage, and a few others, with 1-day retention on Enterprise/Unlimited/Performance editions) —
> the connector will install fine but import very little. Confirm the license before spending
> the customer's time.

Vendor-side steps below are backed by Salesforce documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Salesforce | (Recommended) a dedicated integration user | The client-credentials **run-as** identity; permission set with **API Enabled** + **View Event Log Files** |
| Salesforce | External Client App (or legacy Connected App) | OAuth enabled, **client credentials flow** on, consumer key + consumer secret |
| Ingext | Connector | Template **`SalesforceEM`** ("Salesforce Event Monitoring"), instance e.g. `salesforceem`; datalake table: no `index` parameter in the template — confirm live with `list_data_tables` |

Nothing this skill creates is billable — but the **prerequisite Event Monitoring add-on is a
paid license** the customer must already hold.

---

## Prerequisites

- The **Event Monitoring add-on license** (standalone or via Salesforce Shield) — the hard gate
  above.
- A **Salesforce administrator** who can create apps in Setup, create users, and assign
  permission sets.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Salesforce Setup UI cannot be driven by the agent — a Salesforce admin clicks those steps.
Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the app and user
  creation click-by-click, collect the three values (base URL, consumer key, consumer secret),
  and then **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Salesforce admin isn't in this conversation. Offer to resume the install step
  whenever they return with the values.

If the operator already has a working consumer key/secret and My Domain URL in hand, skip
straight to the [Ingext-side install](#ingext-side--install-the-connector).

---

## Salesforce side — app, user, and values (guided)

### 0 — Confirm the license (hard gate)

Ask whether the org has **Event Monitoring** (standalone add-on or Salesforce Shield). If the
admin is unsure, have them confirm with their Salesforce account executive. Orgs **with** the
license get hourly event log files across the full set of event types; orgs **without** it get
only the free subset (Login, Logout, API Total Usage, and a few others, 1-day retention,
24-hour generation). Proceed without the license only if the customer knowingly accepts that
thin slice.

### 1 — Create the run-as integration user (least privilege)

The client credentials flow has no interactive login — Salesforce executes every API call **as
a designated user**. That user's permissions are the integration's permissions, so:

- **Recommended:** a dedicated integration user (e.g. `svc-ingext@<customer-domain>`), not a
  person and not a System Administrator.
- Assign it a permission set containing exactly: **API Enabled** and **View Event Log Files** —
  the two permissions the `EventLogFile` object requires. (**View All Data** also grants
  access, but it is far broader than needed — avoid it.)
- Salesforce's own guidance: scope the integration user "to the smallest possible subset of
  necessary features" via permission sets.

### 2 — Create the app and enable the client credentials flow

Salesforce is transitioning from Connected Apps to **External Client Apps** — creation of new
Connected Apps is restricted as of Spring '26, so new setups should use an External Client App.
In **Setup**:

1. **External Client App Manager** → **New External Client App**; give it a name (e.g.
   `Ingext Event Monitoring`) and contact email.
2. Under **API (Enable OAuth Settings)**, select **Enable OAuth**. For scopes, grant the **API**
   scope only — a log-pull integration needs nothing broader.
3. Under **Flow Enablement**, select **Enable Client Credentials Flow** and accept the security
   warning.
4. After saving, open the app's **Policies** tab → **Edit** → under **OAuth Flows and External
   Client App Enhancements**, select **Enable Client Credentials Flow** and set **Run As
   (Username)** to the integration user from step 1 → **Save**. Without a run-as user,
   Salesforce refuses to issue tokens for this flow.

> **Legacy Connected App variant** (only if the org must reuse an existing Connected App): under
> **API (Enable OAuth Settings)** select **Enable Client Credentials Flow**; then from the
> app's page **Manage → Edit Policies → Client Credentials Flow → Run As** and pick the
> integration user.

### 3 — Collect the consumer key and secret

- **External Client App:** the consumer key and consumer secret are shown in the app's OAuth
  settings in External Client App Manager (staged rotation of both values is supported there).
- **Connected App:** next to the app choose **View** → **API (Enable OAuth Settings)** →
  **Manage Consumer Details** (Salesforce may re-verify the admin's identity).

The consumer key is the connector's `clientID`; the consumer secret is `clientSecret`.

### 4 — Collect the My Domain base URL

The connector's `baseURL` is the org's **My Domain login URL**:

```
https://<MyDomainName>.my.salesforce.com
```

(Sandboxes: `https://<MyDomainName>--<SandboxName>.sandbox.my.salesforce.com`.) The admin can
read it from **Setup → My Domain**.

> **Gotcha:** use the `.my.salesforce.com` login-URL form — not the
> `.lightning.force.com` application URL from the browser's address bar.

**Deliverables from this section:** `baseURL` + `clientID` (consumer key) + `clientSecret` (the
secret is a credential — never echo it back; refer to it as "the consumer secret from step 3").

---

## Ingext side — install the connector

With the three values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`SalesforceEM`** template ("Salesforce
   Event Monitoring") and use its current parameter schema; the names below are a snapshot, not
   truth.
2. **`list_connectors`** — if a Salesforce connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `SalesforceEM`
   - `instance`: `salesforceem` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Salesforce Event Monitoring`
   - `inputParameters`: **every** template parameter — the live schema currently lists
     `baseURL`, `clientID`, `clientSecret` (sensitive) and nothing else (no `datalake`/`index`
     parameters); include exactly what the live schema shows.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Salesforce
Event Monitoring**, paste the API URL, consumer key, and consumer secret, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake table (the template defines no `index` parameter — confirm the live table name
  with `list_data_tables`). Do not echo the consumer secret anywhere in the summary.
- **Latency expectation — hours, not minutes.** Salesforce generates `EventLogFile` content in
  **batches**: with the Event Monitoring license, hourly log files typically become available
  **3–6 hours** after the underlying activity (sometimes longer, per Salesforce); without the
  license, the free log types appear only in the daily files, up to **~24 hours** later. Zero
  rows shortly after install is **expected** — mark ⏳ with the follow-up noted, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "SalesforceEM",
  "instance": "salesforceem",
  "index": "confirm live via list_data_tables — the template defines no index parameter",
  "app": "<External Client App / Connected App name>",
  "runAsUser": "<the integration username>",
  "firstEvents": "hours — hourly EventLogFiles lag 3–6h behind activity (license); daily files up to ~24h"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **Confirm the live datalake table first** with `list_data_tables` (the template carries no
   `index` parameter, so the table name must come from the live platform), then count rows over
   the last day via the **`ingext-kql`** skill. A plain row count is the smoke test.
3. **Do not judge inside the batch window.** First rows are expected **3–6 hours** after
   Salesforce activity (up to ~24 h for daily-only orgs). If the window has clearly passed and
   the org has real activity but the table stays empty, move to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Token request fails (`invalid_client` / 401) | Consumer key or secret mistyped, the **client credentials flow isn't enabled** on the app, or no **Run As** user is set — Salesforce refuses tokens for this flow without an execution user. Re-check step 2.4 / the Edit Policies screen. |
| Token works but queries are denied or empty ("the authenticated connection does not have access") | The run-as user is missing **View Event Log Files** or **API Enabled**. Fix the permission set on the integration user (step 1). |
| Connector can't reach the org / wrong URL | A `.lightning.force.com` application URL or an old instance URL was used. Use the My Domain login URL: `https://<MyDomainName>.my.salesforce.com`. |
| Connector healthy but nothing ever lands | In order: (1) still inside the 3–6 h (or ~24 h) batch window — wait; (2) **no Event Monitoring license** — only the free subset of log types is generated, so volume is tiny; (3) the org is genuinely quiet. |
| Secret exposed or lost | Rotate it: External Client Apps support staged rotation (generate staged consumer details, then apply); Connected Apps regenerate under Manage Consumer Details. Update the connector with the new secret. |
| A Salesforce connector already exists | Ask before adding a second instance (`salesforceem-2`); two instances polling the same org double the API usage for no benefit unless they intentionally serve different purposes. |

---

## Security notes

- The consumer secret is a credential: never paste it into logs, tickets, summaries, or
  long-lived chat beyond the `create_connector` call.
- Salesforce's own warning for this flow: **anyone holding the consumer key and secret can
  obtain access tokens as the run-as user.** The control is the run-as user's scope — a
  dedicated integration user with only **API Enabled** + **View Event Log Files**, never a
  System Administrator.
- Rotation: External Client Apps support **staged** consumer-detail rotation (generate the new
  pair, then apply) so the connector can be updated without breakage; rotate immediately if the
  secret is ever exposed.
- The run-as user is the audit identity for every API call this connector makes — keeping it
  dedicated makes the connector's activity easy to distinguish in the org's own logs.

---

## Layout

```
setup-salesforce-event-monitoring-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Salesforce documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
