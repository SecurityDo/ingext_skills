---
name: setup-proofpoint-tap-connector
version: 1.0.0
description: >-
  Set up the Proofpoint TAP connector on Fluency / Ingext: import Proofpoint Targeted Attack
  Protection threat events (blocked/permitted clicks, delivered/blocked malicious messages) via
  the TAP SIEM API. Guides the customer through the Proofpoint-side work — creating a service
  credential (service principal + secret) in the TAP Dashboard under Settings → Connected
  Applications — with every step backed by cited documentation, then performs the Fluency-side
  install itself via create_connector. The TAP side is portal-only (a TAP Dashboard admin must
  click the console), so the agent guides those steps and does everything else. SELF-CONTAINED:
  it ends by creating the "ProofpointTAP" connector itself — when routed from
  customer-onboarding, do NOT chain into add-connector afterward. Triggers: "add Proofpoint TAP
  to Ingext", "connect Proofpoint Targeted Attack Protection", "import TAP clicks and threat
  events into Fluency", "set up the Proofpoint TAP connector", "ingest Proofpoint threat data".
  Do NOT use for Proofpoint ESSENTIALS — that is a different product with its own template
  (ProofpointEssentials) and no dedicated skill yet; route it to add-connector. When the user
  just says "Proofpoint", ask which product before proceeding.
---

# Set up the Proofpoint TAP connector

Import **Proofpoint Targeted Attack Protection (TAP)** threat events — blocked and permitted
clicks, delivered and blocked malicious messages — into Fluency / Ingext via TAP's **SIEM API**.
Two things are needed, and only one of them is yours to collect from the customer:

- **Proofpoint side (customer's TAP Dashboard):** a **service credential** — a **service
  principal** plus **secret** — created under Settings → Connected Applications. Portal-only —
  guide it, step by step.
- **Fluency side (yours):** install the **`ProofpointTAP`** connector (display name "Proofpoint
  TAP") with those two values. Do this for the operator via the MCP.

Vendor-side steps below are backed by Proofpoint's SIEM API documentation (primary) plus SIEM
vendor integration guides (secondary) for the exact console path; citations live in
`assets/references.md`.

> **TAP vs Essentials:** the platform also carries a **`ProofpointEssentials`** template — a
> different Proofpoint product with a different credential model and a regional base URL. That
> variant has no dedicated skill; route it to `add-connector`. Confirm which product the
> customer runs before starting.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Proofpoint | TAP service credential | Named e.g. `ingext-tap`; a service principal + secret pair, shown **once** at generation |
| Ingext | Connector | Template **`ProofpointTAP`** ("Proofpoint TAP"), instance e.g. `proofpointtap`; datalake table: confirm live (the template exposes no index parameter) |

Nothing here is billable on the Proofpoint side — TAP itself is the licensed product; the SIEM
API comes with the TAP Dashboard.

---

## Prerequisites

- A **TAP Dashboard administrative user** — someone who can sign in at
  `https://threatinsight.proofpoint.com` and has the privilege to create service credentials
  under Settings → Connected Applications. Proofpoint documents no finer-grained role name
  publicly; "an administrative user with rights to create service credentials" is the working
  requirement.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The TAP Dashboard cannot be driven by the agent — a TAP admin clicks those steps. Ask (use
`AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the credential creation
  click-by-click, collect the two values (service principal, secret), and then **you** create
  the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the TAP admin isn't in this conversation. Offer to resume the install step whenever
  they return with the values.

If the operator already has a working service principal and secret in hand, skip straight to
the [Ingext-side install](#ingext-side--install-the-connector).

---

## Proofpoint side — create the service credential (guided)

### 1 — Create the credential

In the **TAP Dashboard** (`https://threatinsight.proofpoint.com`), as an administrative user:

1. Open **Settings → Connected Applications**.
2. Click **Create New Credential**.
3. Name the credential set **`ingext-tap`** and click **Generate**.
4. A dialog ("Generated Service Credential") shows the **Service Principal** and **Secret**.
   **Copy both immediately** — they are not available again after the dialog closes.
5. Back on the Connected Applications page, confirm the new credential is listed with an
   **Active** status.

### 2 — Know what the credential is for

The connector calls the **TAP SIEM API** at `tap-api-v2.proofpoint.com` over SSL, using **HTTP
Basic authentication** — the service principal is the username and the secret is the password.
Nothing else is collected: the live `ProofpointTAP` template takes only `principal` and
`secret`.

Two operational facts worth telling the customer up front (both from Proofpoint's SIEM API
docs):

- **Rate limits:** the SIEM API allows **1800 requests per 24 hours** per throttle pool. The
  connector's polling cadence lives comfortably inside that — but a second consumer of the same
  credential (another SIEM, a script) shares the pool.
- **Retention:** the API serves at most the **last 7 days**. A connector outage longer than
  that loses the gap permanently — worth knowing before it matters.

**Deliverables from this section:** `principal` + `secret` (the secret is a credential — never
echo it back; refer to it as "the secret from step 1").

---

## Ingext side — install the connector

With the two values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`ProofpointTAP`** template ("Proofpoint
   TAP") and use its current parameter schema; the names below are a snapshot, not truth. Take
   care **not** to grab `ProofpointEssentials` by mistake.
2. **`list_connectors`** — if a Proofpoint connector already exists (either template), show its
   instance/state and confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `ProofpointTAP`
   - `instance`: `proofpointtap` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Proofpoint TAP`
   - `inputParameters`: **every** template parameter — in the current snapshot that is just
     `principal` and `secret` (sensitive); include whatever the live schema shows.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Proofpoint
TAP**, paste the principal and secret, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake table — the template exposes **no index parameter**, so confirm the live table
  name with `list_data_tables` once events land rather than guessing. Do not echo the secret
  anywhere in the summary.
- **Latency expectation:** the connector polls the SIEM API; when the org has recent TAP
  activity, first events should land within roughly **15–30 minutes**. But TAP is
  **threat-driven** — an org with no recent malicious messages or clicks legitimately shows
  zero events for hours. Compare with the TAP Dashboard before judging; mark ⏳ inside the
  window (or while the dashboard itself is quiet), not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "ProofpointTAP",
  "instance": "proofpointtap",
  "index": "confirm live with list_data_tables — the template exposes no index parameter",
  "credential": "TAP service credential 'ingext-tap' (service principal held by the customer)",
  "retention": "TAP SIEM API serves at most the last 7 days; outages longer than that lose the gap"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, find the live table with **`list_data_tables`** and count rows over the
   last hour via the **`ingext-kql`** skill. A plain row count is the smoke test.
3. Cross-check against the customer's own **TAP Dashboard** — TAP data is threat-driven, so if
   the dashboard shows no clicks/threat events for the same window, an empty table is correct
   behavior, not a failure. Only if the dashboard shows events and the datalake shows none past
   the latency window, move to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / auth failure | Principal or secret mistyped, or the credential was deleted in the dashboard. Check Settings → Connected Applications for the credential's status; regenerate a fresh pair and update the connector. |
| Credential values not captured | Shown once. Create a new credential set in Settings → Connected Applications, use the new pair, and delete the orphaned one. |
| 429 / rate-limited | The SIEM API pools allow 1800 requests per 24 h. Check whether another integration shares the same service credential; give each consumer its own credential set. |
| Zero events but connector healthy | TAP is threat-driven — compare with the TAP Dashboard. A quiet org genuinely produces nothing. Only dashboard-visible events missing from the datalake indicate a real problem. |
| Connector was down for more than 7 days | The gap is unrecoverable — the SIEM API serves at most the last 7 days. Resume ingestion and note the gap honestly. |
| Customer actually runs Proofpoint Essentials | Different product, different template (`ProofpointEssentials`, with a regional base URL). Route to `add-connector` — this skill's runbook does not apply. |
| A Proofpoint TAP connector already exists | Ask before adding a second instance (`proofpointtap-2`); two instances polling the same tenant share the same rate-limit pool for no benefit. |

---

## Security notes

- The secret is a credential: never paste it into logs, tickets, summaries, or long-lived chat
  beyond the `create_connector` call. The service principal is an identifier, but there is no
  reason to spread it around either.
- Give the Ingext integration **its own** credential set (`ingext-tap`) — sharing a pair across
  consumers muddies rotation and rate-limit accounting.
- Rotation: create a new credential set in Settings → Connected Applications, update the
  connector, then delete the old set. Do the same immediately if the secret is ever exposed.
- Treat the pair as a read credential for TAP threat data; Proofpoint documents no
  finer-grained scoping for service credentials, so possession is access.

---

## Layout

```
setup-proofpoint-tap-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Proofpoint documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
