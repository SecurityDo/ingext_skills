---
name: setup-okta-connector
version: 1.0.0
description: >-
  Set up the Okta Events connector on Fluency / Ingext: import Okta System Log events (sign-ins,
  admin actions, lifecycle events) via the Okta API. Guides the customer through the Okta-side
  work — choosing a least-privilege token owner and creating an API token in the Okta Admin
  Console (Security → API → Tokens) — with every step backed by Okta documentation, then performs
  the Fluency-side install itself via create_connector. The Okta side is portal-only (an Okta
  admin must click the console; there is no agent-drivable CLI), so the agent guides those steps
  and does everything else. SELF-CONTAINED: it ends by creating the "Okta" connector itself — when
  routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers: "add Okta
  to Ingext", "connect our Okta org", "import Okta system log into Fluency", "set up the Okta
  connector", "start ingesting Okta events". Do NOT use for generic connector installs where the
  user already holds a working Okta API token and just says "install connector X" — add-connector
  also handles that — and not for Office 365 / Entra sign-in logs, which are the
  automatic-create-ingext-azureaudit-app path.
---

# Set up the Okta Events connector

Import **Okta System Log** events — sign-ins, MFA outcomes, admin actions, user lifecycle
changes — into Fluency / Ingext via Okta's API. Two things are needed, and only one of them is
yours to collect from the customer:

- **Okta side (customer's admin console):** an **API token**, created by an admin whose
  permissions the token inherits. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`Okta`** connector (display name "Okta Events") with
  the org domain and that token. Do this for the operator via the MCP.

Vendor-side steps below are backed by Okta documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Okta | (Recommended) a dedicated service-account admin | Least-privilege token owner, e.g. **Read-Only Administrator** |
| Okta | API token | Named `ingext-okta`; value shown **once**; inherits the owner's permissions; expires after **30 days of non-use** (timer resets on every API call) |
| Ingext | Connector | Template **`Okta`** ("Okta Events"), instance e.g. `okta`, datalake index default `Okta` |

Nothing here is billable on the Okta side.

---

## Prerequisites

- An **Okta administrator** who can sign in to the Admin Console and create API tokens, and —
  for the recommended least-privilege setup — someone who can create/assign an admin service
  account (Super Admins can; see Security notes).
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Okta Admin Console cannot be driven by the agent — an Okta admin clicks those steps. Ask
(use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the token creation
  click-by-click, collect the two values (org domain, API token), and then **you** create the
  Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Okta admin isn't in this conversation. Offer to resume the install step whenever
  they return with the values.

If the operator already has a working API token and domain in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Okta side — create the API token (guided)

### 1 — Pick the token owner (least privilege)

An Okta API token **inherits the permissions of the admin who creates it** — it is exactly as
powerful as its owner, and it dies with the owner (deactivating the account invalidates the
token). So:

- **Recommended:** create a dedicated service account (e.g. `svc-ingext@<customer-domain>`) and
  assign it the **Read-Only Administrator** role — enough to view the System Log, nothing
  writable. Exempt it from aggressive session policies but keep MFA.
- **Acceptable for a quick start:** an existing admin creates the token; note in your report that
  the integration is tied to that person's account and should be migrated to a service account.

The token owner must be able to view the **System Log** in the Admin Console (Reports → System
Log) — the token can read what the owner can read. Have the admin confirm that view works before
creating the token.

### 2 — Create the token

In the **Okta Admin Console**:

1. **Security → API → Tokens** tab → **Create token**.
2. Name it **`ingext-okta`**.
3. **Copy the token value immediately** — it is shown **once**. This is the connector's `token`
   parameter.

> **Token lifetime:** Okta API tokens expire after **30 days without use**, and the 30-day timer
> resets on every API call. Because the connector polls continuously, the token stays alive in
> normal operation — but a long connector outage (>30 days) silently kills the token. That is
> the first thing to check if ingestion ever stops (see Failure modes).

### 3 — Collect the org domain

The connector's `domain` parameter is the org's **Okta domain**, e.g. `acme.okta.com`,
`acme.okta-emea.com`, or `dev-123456.okta.com`.

> **Gotcha:** if the admin copies the URL from the Admin Console address bar it will read
> `acme-admin.okta.com` — **strip the `-admin`**. Orgs with a custom/vanity domain
> (`login.acme.com`) should still supply the underlying Okta domain; Okta's "Find your domain"
> guide (see references) shows where it is.

**Deliverables from this section:** `domain` + `token` (the token is a credential — never echo
it back; refer to it as "the API token from step 2").

---

## Ingext side — install the connector

With the two values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`Okta`** template ("Okta Events") and use
   its current parameter schema; the names below are a snapshot, not truth.
2. **`list_connectors`** — if an Okta connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `Okta`
   - `instance`: `okta` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on collision)
   - `displayName`: `Okta Events`
   - `inputParameters`: **every** template parameter — `domain`, `token` (sensitive), and the
     defaulted `datalake` (`managed`) / `index` (`Okta`) unless the operator wants otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Okta
Events**, paste the domain and token, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and the
  datalake index (default `Okta`; confirm the live table name with `list_data_tables`). Do not
  echo the API token anywhere in the summary.
- **Latency expectation:** the connector polls the Okta API; with any activity in the org, first
  events should land within roughly **15–30 minutes**. A quiet dev org may genuinely have few
  events — check the Okta System Log UI for comparison before calling it broken. Mark ⏳ inside
  that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "Okta",
  "instance": "okta",
  "index": "Okta",
  "tokenOwner": "<service account or admin who owns the API token>",
  "tokenExpiry": "30 days of inactivity, self-renewing while the connector polls"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the `Okta` datalake index over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first). A plain
   row count is the smoke test.
3. Cross-check against the customer's own **Reports → System Log** in Okta — if that shows
   events for the same window and the datalake shows none past the latency window, move to
   Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / invalid token | Token was mistyped, has expired (30 days unused), or its owner was deactivated/suspended. Create a fresh token (step 2) and update the connector. |
| Wrong domain | The classic mistake is the `-admin` console domain (`acme-admin.okta.com`) or a vanity domain. Use the bare org domain (`acme.okta.com`); see Okta's "Find your domain" guide in references. |
| Token owner can't see the System Log | The token inherits the owner's permissions. Assign the owner a role that can view the System Log (Read-Only Administrator suffices) and recreate the token. |
| Events flowed, then stopped | Check (in order): token owner deactivated? Token expired after a >30-day connector outage? Okta org rate limits (the System Log API is rate-limited per org — sustained 429s slow polling but should recover). |
| Token value not captured | Shown once. Revoke the half-created token in Security → API → Tokens and create a new one. |
| An Okta connector already exists | Ask before adding a second instance (`okta-2`); two instances polling the same org double the API load for no benefit unless they target different datalake indexes on purpose. |

---

## Security notes

- The API token is a credential: never paste it into logs, tickets, summaries, or long-lived
  chat beyond the `create_connector` call.
- **Least privilege lives in the owner, not the token** — Okta API tokens have no scoping of
  their own, so a Read-Only Administrator service account as owner is the control.
- Rotation: create a new token, update the connector, then revoke the old one in
  **Security → API → Tokens**. Do the same immediately if the token is ever exposed.
- Deactivating the owning account revokes the token — plan for this when admins offboard;
  another reason the owner should be a service account.

---

## Layout

```
setup-okta-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Okta documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
