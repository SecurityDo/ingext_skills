---
name: setup-mimecast-connector
version: 1.0.0
description: >-
  Set up the Mimecast CG Events connector on Fluency / Ingext: import Mimecast Email Security
  Cloud Gateway SIEM events (message flow, threat detections, URL/attachment protection) via
  Mimecast API 2.0. Guides the customer through the Mimecast-side work — registering an API 2.0
  application in the Administration Console (Integrations → API and Platform Integrations, or the
  Integrations Hub on newer consoles) and capturing the client ID / client secret — with every
  step backed by cited documentation, then performs the Fluency-side install itself via
  create_connector. The Mimecast side is portal-only (a Mimecast admin must click the console),
  so the agent guides those steps and does everything else. SELF-CONTAINED: it ends by creating
  the "MimecastCG" connector itself — when routed from customer-onboarding, do NOT chain into
  add-connector afterward. Triggers: "add Mimecast to Ingext", "connect our Mimecast tenant",
  "import Mimecast email security events into Fluency", "set up the Mimecast connector", "start
  ingesting Mimecast logs". Do NOT use for the legacy "Mimecast" template (API 1.0, five
  parameters: baseURL / applicationID / applicationKey / accessKey / secretKey) — API 1.0 is
  superseded and new setups belong on CG / API 2.0; a customer who already holds working 1.0
  credentials can be installed via add-connector instead. Not for Proofpoint or other email
  security products.
---

# Set up the Mimecast CG Events connector

Import **Mimecast Email Security Cloud Gateway** SIEM events — message flow, threat detections,
URL and attachment protection outcomes — into Fluency / Ingext via **Mimecast API 2.0**. Two
things are needed, and only one of them is yours to collect from the customer:

- **Mimecast side (customer's Administration Console):** an **API 2.0 application**, which
  issues a **client ID** and **client secret**. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`MimecastCG`** connector (display name "Mimecast CG
  Events") with those two values. Do this for the operator via the MCP.

Vendor-side steps below are backed by Mimecast documentation (with a SIEM-vendor secondary where
Mimecast's own pages are fetch-gated); citations live in `assets/references.md`.

> **API 1.0 vs 2.0:** the platform also carries a legacy **`Mimecast`** template ("Mimecast
> Events (Legacy)", API 1.0, five parameters). Mimecast has put API 1.0 at end of life — steer
> every new setup here, to CG / API 2.0. Only a customer already holding working 1.0 credentials
> should go the `add-connector` route with the legacy template.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Mimecast | API 2.0 application | Named e.g. `ingext-mimecast`; issues a client ID + client secret (secret shown **once**) |
| Ingext | Connector | Template **`MimecastCG`** ("Mimecast CG Events"), instance e.g. `mimecastcg`, datalake index default `Mimecast` |

No billable vendor resources are created — the API application is a credential object, not a
paid service.

---

## Prerequisites

- A **Mimecast administrator** who can sign in to the Administration Console and reach the
  Integrations area to create API 2.0 applications (Rapid7's integration guide reports a
  **Basic Administrator** role is sufficient — see references).
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Mimecast Administration Console cannot be driven by the agent — a Mimecast admin clicks
those steps. Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the application
  registration click-by-click, collect the two values (client ID, client secret), and then
  **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Mimecast admin isn't in this conversation. Offer to resume the install step
  whenever they return with the values.

If the operator already has an API 2.0 client ID and secret in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector). If what they hold is the **five**
legacy 1.0 values, stop — that is the legacy `Mimecast` template via `add-connector`, not this
skill.

---

## Mimecast side — register the API 2.0 application (guided)

### 1 — Open the API integrations area

In the **Mimecast Administration Console**:

- **Integrations → API and Platform Integrations**, or on newer consoles
  **Integrations → Integrations Hub** → locate the **API 2.0** tile → **View**.

Mimecast is migrating management of API 2.0 applications to the Integrations Hub — applications
created earlier remain manageable on the API and Platform Integrations page, while new ones are
created in the Hub. Either path lands in the same place: your API 2.0 applications.

### 2 — Create the application

1. Create an **API 2.0 Application** and name it **`ingext-mimecast`**; fill the descriptive
   fields as prompted.
2. When the wizard asks which products/data the application may access, select the product set
   covering **Cloud Gateway threat / SIEM events** — Rapid7's guide (secondary source) names it
   **"Threats, Security Events and Data for CG"**; the exact label in the wizard may vary by
   account.
3. On completion a popup shows the **Client ID** and **Client Secret** (masked). **Copy both
   immediately** — since Mimecast's September 2023 credentials change, the secret **cannot be
   retrieved later**; losing it means regenerating (below).

> **Activation delay:** a freshly created application can take **several minutes** to become
> usable. If the connector reports an auth failure right after creation, wait a few minutes
> before treating it as a real credential problem.

> **Rotation / lost secret:** open the application in the API 2.0 list → **Reset Keys** →
> **Regenerate**. This issues fresh credentials and invalidates the old ones — the connector
> must be updated with the new values in the same breath.

### 3 — Confirm the credential model

API 2.0 uses **OAuth 2.0 client credentials** — the connector exchanges the client ID/secret
for short-lived tokens itself; nothing else is collected. Unlike legacy API 1.0 there is **no
regional base URL** to gather: the live `MimecastCG` template takes only `clientId` and
`clientSecret` (plus datalake defaults).

**Deliverables from this section:** `clientId` + `clientSecret` (the secret is a credential —
never echo it back; refer to it as "the client secret from step 2").

---

## Ingext side — install the connector

With the two values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`MimecastCG`** template ("Mimecast CG
   Events") and use its current parameter schema; the names below are a snapshot, not truth.
   Take care **not** to grab the legacy `Mimecast` template by mistake.
2. **`list_connectors`** — if a Mimecast connector already exists (either template), show its
   instance/state and confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `MimecastCG`
   - `instance`: `mimecastcg` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Mimecast CG Events`
   - `inputParameters`: **every** template parameter — `clientId`, `clientSecret` (sensitive),
     and the defaulted `datalake` (`managed`) / `index` (`Mimecast`) unless the operator wants
     otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Mimecast
CG Events**, paste the client ID and secret, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and the
  datalake index (default `Mimecast`; confirm the live table name with `list_data_tables`). Do
  not echo the client secret anywhere in the summary.
- **Latency expectation:** the connector polls the Mimecast API; with normal mail flow, first
  events should land within roughly **15–30 minutes** — remember the few-minute activation
  delay on a brand-new API application sits inside that window. Mark ⏳ inside the window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "MimecastCG",
  "instance": "mimecastcg",
  "index": "Mimecast",
  "apiApplication": "ingext-mimecast (API 2.0; client ID held by the customer)",
  "secretRecovery": "not retrievable after creation — Reset Keys → Regenerate, then update the connector"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the `Mimecast` datalake index over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first). A plain
   row count is the smoke test.
3. Cross-check against the customer's own Mimecast Administration Console (message tracking /
   security event views) — if Mimecast shows activity for the same window and the datalake shows
   none past the latency window, move to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / invalid client | Mistyped client ID/secret, the application was just created (wait several minutes — activation delay), or the keys were reset in the console. Re-copy or regenerate (Reset Keys) and update the connector. |
| Secret not captured at creation | It is shown once and not retrievable afterward. Open the application → Reset Keys → Regenerate, and update the connector with the fresh pair. |
| Customer supplied five values, not two | Those are legacy API 1.0 credentials (`baseURL`, `applicationID`, `applicationKey`, `accessKey`, `secretKey`). Steer to a fresh API 2.0 application here — or, if they insist on reusing working 1.0 credentials, install the legacy `Mimecast` template via `add-connector`. |
| Wizard doesn't offer the expected product selection | Product names in the wizard vary by account/bundle; pick the option covering Cloud Gateway threat/SIEM events, and have the admin confirm with Mimecast support if nothing matches. |
| Events flowed, then stopped | Check whether the API application was deleted or its keys reset in the console, then whether the admin who created it still exists — then contact Mimecast support for API-side throttling or service notices. |
| A Mimecast connector already exists | Ask before adding a second instance (`mimecastcg-2`); two instances polling the same tenant double the API load for no benefit unless they intentionally target different datalake indexes. |

---

## Security notes

- The client secret is a credential: never paste it into logs, tickets, summaries, or long-lived
  chat beyond the `create_connector` call.
- **Least privilege lives in the product selection** — grant the API 2.0 application only the
  Cloud Gateway threat/SIEM events product, nothing broader.
- Rotation: **Reset Keys → Regenerate** on the application, update the connector immediately,
  since the old pair dies at regeneration. Do this at once if the secret is ever exposed.
- The client secret is **not retrievable** after the creation popup (September 2023 change) —
  store it in a secrets manager, not a document.

---

## Layout

```
setup-mimecast-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Mimecast documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
