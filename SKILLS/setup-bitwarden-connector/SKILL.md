---
name: setup-bitwarden-connector
version: 1.0.0
description: >-
  Set up the Bitwarden connector on Fluency / Ingext: import Bitwarden organization event logs
  (member logins, vault item access, collection/group/member changes) via the Bitwarden Public
  API. Guides the customer through the Bitwarden-side work — an organization Owner retrieving
  the ORGANIZATION API key (client_id starting with "organization.") from the Admin Console
  under Settings → Organization info — with every step backed by Bitwarden documentation, then
  performs the Fluency-side install itself via create_connector. The Bitwarden side is
  portal-only (an Owner must open the Admin Console; there is no agent-drivable CLI), so the
  agent guides those steps and does everything else. SELF-CONTAINED: it ends by creating the
  "Bitwarden" connector itself — when routed from customer-onboarding, do NOT chain into
  add-connector afterward. Triggers: "add Bitwarden to Ingext", "connect our Bitwarden
  organization", "import Bitwarden event logs into Fluency", "set up the Bitwarden connector",
  "start ingesting Bitwarden audit events". Do NOT use for generic connector installs where the
  user already holds the organization API key and just says "install connector X" —
  add-connector also handles that — and not for a user's PERSONAL Bitwarden API key or for
  Bitwarden Secrets Manager, neither of which feeds organization event logs.
---

# Set up the Bitwarden connector

Import **Bitwarden organization event logs** — member logins, vault item access, and
collection / group / member changes — into Fluency / Ingext via the Bitwarden **Public API**.
Two things are needed, and only one of them is yours to collect from the customer:

- **Bitwarden side (customer's Admin Console):** the **organization API key** — a
  `client_id` / `client_secret` pair that only an organization **Owner** can retrieve.
  Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`Bitwarden`** connector with the region and that key
  pair. Do this for the operator via the MCP.

Vendor-side steps below are backed by Bitwarden documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Bitwarden | Nothing new | You retrieve the org's **existing** API key (`client_id` format `organization.ClientId`); a **Rotate API key** action exists if it's ever compromised |
| Ingext | Connector | Template **`Bitwarden`**, instance e.g. `bitwarden`; the template has **no `index` parameter** — confirm the live datalake table with `list_data_tables` after install |

Nothing here is billable on the Bitwarden side, but the Public API — and event logs
themselves — are available to **Teams and Enterprise** organizations only. A Free, Families,
or Premium-individual setup has nothing for this connector to read.

---

## Prerequisites

- A Bitwarden **organization Owner** — the API key is obtained by an owner from the Admin
  Console; lesser roles can't see it. (An Owner may share it with the operator, but should use
  a secure channel such as Bitwarden Send.)
- A **Teams or Enterprise** organization (Public API + event log availability).
- **Bitwarden cloud, US or EU.** The template's `region` parameter selects between the US cloud
  (`identity.bitwarden.com`) and the EU cloud (`identity.bitwarden.eu`). Self-hosted Bitwarden
  servers authenticate against their own endpoint (`https://your.domain.com/identity/...`),
  which this template's region choice does not express — if the customer is self-hosted, stop
  and confirm support with Fluency before promising ingestion.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Bitwarden Admin Console cannot be driven by the agent — an organization Owner clicks those
steps. Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the Owner through retrieving the
  organization API key click-by-click, collect the three values (region, `client_id`,
  `client_secret`), and then **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Owner isn't in this conversation. Offer to resume the install step whenever
  they return with the values.

If the operator already has the organization API key in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Bitwarden side — retrieve the organization API key (guided)

### 1 — Confirm plan, cloud, and region

- Event logs and the Public API require a **Teams or Enterprise** organization.
- Which cloud does the org live on? Web vault at `vault.bitwarden.com` → region **US**;
  `vault.bitwarden.eu` → region **EU**. This becomes the connector's `region` parameter.
- **Self-hosted?** Stop here and check with Fluency support (see Prerequisites) — the
  connector's region values cover the two Bitwarden clouds.

### 2 — Retrieve the organization API key (Owner only)

In the Bitwarden **web app**, as an organization **Owner**:

1. Open the organization's **Admin Console**.
2. Go to **Settings → Organization info** and scroll down to the **API key** section.
3. View the key and copy both values:
   - **`client_id`** — format `organization.ClientId`. If the value doesn't start with
     `organization.`, it's a **personal** API key, which will not work here.
   - **`client_secret`** — **a credential; treat it like a password.**

> **Owner-only:** Bitwarden exposes the organization API key to owners. If the operator running
> this session isn't an Owner, the Owner should retrieve it and pass it over a secure channel
> (Bitwarden's docs suggest Bitwarden Send) — never over email or a ticket.

### 3 — What this key reads

The organization API key authenticates the **Bitwarden Public API** (OAuth scope
`api.organization`), and the connector uses it to pull the org's **event logs** — the same
records visible in the Admin Console under **Reporting → Event logs**. Have the Owner glance at
that page: if events show there, the connector has something to ingest.

**Deliverables from this section:** `region` + `clientId` + `clientSecret` (the client secret
is a credential — never echo it back; refer to it as "the client secret from step 2").

---

## Ingext side — install the connector

With the values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`Bitwarden`** template and use its
   current parameter schema; the names below are a snapshot, not truth. In the snapshot,
   `region` is a plain string defaulting to `US` — if the live template carries enums, use
   those values; otherwise `US` / `EU` per step 1.
2. **`list_connectors`** — if a Bitwarden connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `Bitwarden`
   - `instance`: `bitwarden` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Bitwarden`
   - `inputParameters`: **every** template parameter — `region` (default `US`), `clientId`,
     `clientSecret` (sensitive).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add →
**Bitwarden**, pick the region, paste the client ID and secret, save.

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
- **Latency expectation:** the connector polls the Public API; with any activity in the org,
  first events should land within roughly **15–30 minutes**. (On the Bitwarden side the delay
  is small — server events record instantly and client events upload about every 60 seconds.)
  A small, quiet org may genuinely have few events — check Admin Console → Reporting → Event
  logs for comparison before calling it broken. Mark ⏳ inside that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "Bitwarden",
  "instance": "bitwarden",
  "region": "US",
  "index": "confirm live via list_data_tables (template has no index parameter)",
  "keyOwner": "<organization Owner who retrieved the API key>"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **`list_data_tables`** — identify which datalake table the connector writes; the template
   carries no `index` parameter, so the live listing is the only source of truth for the name.
3. After ~15–30 min, count rows in that table over the last hour via the **`ingext-kql`**
   skill. A plain row count is the smoke test.
4. Cross-check against the customer's own **Admin Console → Reporting → Event logs** — if that
   shows events for the same window and the datalake shows none past the latency window, move
   to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with invalid-client / 401-class failures | `client_id`/`client_secret` mistyped, the key was rotated in Bitwarden (old secret dies immediately), or a **personal** API key was supplied — the org key's `client_id` starts with `organization.`. Retrieve the organization key (step 2) and update the connector. |
| Wrong region | US credentials against the EU cloud (or vice versa) won't authenticate. Match the region to the org's web-vault domain (`vault.bitwarden.com` → US, `vault.bitwarden.eu` → EU) and update the connector. |
| Plan has no Public API | Free / Families / Premium setups have neither the org API key nor event logs. The org must be Teams or Enterprise; there is nothing to work around. |
| Self-hosted server | The template's region choice targets the Bitwarden clouds. Don't improvise an endpoint — confirm self-hosted support with Fluency before retrying. |
| Events flowed, then stopped | Check (in order): was the API key rotated (**Settings → Organization info → Rotate API key**) without updating the connector? Did the org's plan lapse below Teams? |
| A Bitwarden connector already exists | Ask before adding a second instance (`bitwarden-2`); two instances polling the same org double the API load for no benefit. |

---

## Security notes

- The `client_secret` is a credential: never paste it into logs, tickets, summaries, or
  long-lived chat beyond the `create_connector` call.
- The key authenticates the **organization-management Public API** (scope `api.organization`) —
  guard it accordingly, and pass it between people only over a secure channel (Bitwarden's own
  suggestion: Bitwarden Send).
- Rotation: **Settings → Organization info → Rotate API key**. Bitwarden documents this as the
  response to a compromised key; rotating invalidates the old pair immediately, so update the
  connector in the same sitting.
- Only organization **Owners** can retrieve the key — plan for Owner offboarding, since
  whoever holds Owner can mint a fresh view of this credential.

---

## Layout

```
setup-bitwarden-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Bitwarden documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
