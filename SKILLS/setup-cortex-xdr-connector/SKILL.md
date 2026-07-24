---
name: setup-cortex-xdr-connector
version: 1.0.0
description: >-
  Set up the PaloAlto Cortex XDR connector on Fluency / Ingext: import events from a Palo Alto
  Cortex XDR tenant via the Cortex XDR REST API. Guides the customer through the Cortex-side
  work — creating an API key in the Cortex XDR console (Settings → Configurations → Integrations
  → API Keys) with a least-privilege read role and the right security level (Advanced by
  default), then copying the Key ID and the tenant's api- URL — with every step backed by Palo
  Alto documentation, then performs the Fluency-side install itself via create_connector. The
  Cortex console is portal-only (an admin must click it; there is no agent-drivable CLI), so the
  agent guides those steps and does everything else. SELF-CONTAINED: it ends by creating the
  "CortexXDR" connector itself — when routed from customer-onboarding, do NOT chain into
  add-connector afterward. Triggers: "add Cortex XDR to Ingext", "connect our Cortex XDR
  tenant", "import Cortex XDR events into Fluency", "set up the Cortex XDR connector", "start
  ingesting Palo Alto Cortex data". Do NOT use for Palo Alto FIREWALL logs — PAN-OS / NGFW
  syslog is the separate PaloAlto_FWLog template with no dedicated skill yet; route that to
  add-connector — and not for generic connector installs where the user already holds a working
  API key, Key ID, and URL and just says "install connector X" — add-connector also handles
  that.
---

# Set up the PaloAlto Cortex XDR connector

Import events from a **Palo Alto Cortex XDR** tenant into Fluency / Ingext via the Cortex XDR
REST API. Two things are needed, and only one of them is yours to collect from the customer:

- **Cortex side (customer's console):** an **API key** with a read role, plus its **Key ID** and
  the tenant's **API base URL**. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`CortexXDR`** connector (display name "PaloAlto Cortex
  XDR") with those three values and the matching auth mode. Do this for the operator via the
  MCP.

Vendor-side steps below are backed by Palo Alto documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Cortex XDR | API key | Security level **Advanced** (the connector's default `authMode`) or Standard; value shown **once**; optional expiration date |
| Cortex XDR | (Recommended) a least-privilege role on the key | e.g. the predefined read-only **Viewer** role — the key can only do what its role allows |
| Ingext | Connector | Template **`CortexXDR`** ("PaloAlto Cortex XDR"), instance e.g. `cortexxdr`, datalake index default `Cortex` |

Nothing here is billable on the Cortex side.

---

## Prerequisites

- A **Cortex XDR administrator** who can sign in to the tenant console and create API keys
  (API-key management lives under Settings → Configurations → Integrations → API Keys).
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Cortex XDR console cannot be driven by the agent — a Cortex admin clicks those steps. Ask
(use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the key creation
  click-by-click, collect the three values (API URL, Key ID, API key) plus the chosen security
  level, and then **you** create the Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Cortex admin isn't in this conversation. Offer to resume the install step
  whenever they return with the values.

If the operator already has a working API key, Key ID, and API URL in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector) — but confirm which **security
level** the key was created with, because the connector's `authMode` must match it.

---

## Cortex side — create the API key (guided)

### 1 — Pick the key's role (least privilege)

Every Cortex XDR API key is generated **with a role** — the key can only do what that role
permits. When creating the key the admin selects one of the tenant's roles (or *Custom* for
granular permissions).

- **Recommended:** the predefined read-only **Viewer** role — Palo Alto's predefined role set
  includes it, and a read role is all a log-pull integration needs.
- Role-permission details are shown in the tenant console itself — have the admin confirm there
  that the chosen role can **view** the data they expect the connector to read, rather than
  granting anything writable "just in case".

### 2 — Create the key

In the **Cortex XDR console**:

1. **Settings → Configurations → Integrations → API Keys** → **+ New Key**.
2. **Security Level:** choose **Advanced** (recommended — it matches the connector's default
   `authMode` of `advanced`). Advanced keys are hashed with a nonce and timestamp to prevent
   replay attacks; Standard keys are sent as-is. Either works — but **the connector's `authMode`
   must match the level chosen here** (`advanced` ↔ Advanced, `standard` ↔ Standard).
3. **Role:** select the role from step 1.
4. Optionally **Enable Expiration Date**. If set, Cortex XDR notifies one week and one day
   before expiry — record the date, because the connector dies with the key.
5. Generate, then **copy the key value immediately** — it is shown **once** and cannot be viewed
   again (only regenerated). This is the connector's `apiKey` parameter.

### 3 — Collect the Key ID

In the **API Keys** table, note the **ID** column value for the key just created — a small
number. This is the connector's `apiKeyId` parameter. It identifies *which* key is presented, so
it must be the ID of this exact key, not another row's.

### 4 — Collect the tenant API URL

Select the key in the API Keys table and click **Copy API URL** (or right-click → **View
Examples** — the curl example embeds the same URL). It has the form:

```
https://api-{fqdn}
```

where `{fqdn}` is unique to the tenant. This is the connector's `apiUrl` parameter.

> **Gotcha:** the API URL is **not** the console URL the admin signed in to — it carries the
> `api-` prefix. If the connector later fails to reach the tenant, a pasted console URL is the
> usual cause.

**Deliverables from this section:** `apiUrl` + `apiKeyId` + the security level (→ `authMode`) +
`apiKey` (the key is a credential — never echo it back; refer to it as "the API key from
step 2").

---

## Ingext side — install the connector

With the values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`CortexXDR`** template ("PaloAlto Cortex
   XDR") and use its current parameter schema; the names below are a snapshot, not truth.
2. **`list_connectors`** — if a Cortex XDR connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `CortexXDR`
   - `instance`: `cortexxdr` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `PaloAlto Cortex XDR`
   - `inputParameters`: **every** template parameter — `apiUrl`, `apiKeyId`, `apiKey`
     (sensitive), `authMode` (`advanced` unless the admin created a Standard key — then
     `standard`), and the defaulted `datalake` (`managed`) / `index` (`Cortex`) unless the
     operator wants otherwise.
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **PaloAlto
Cortex XDR**, paste the API URL, Key ID, and key, set the auth mode to match the key's security
level, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and the
  datalake index (default `Cortex`; confirm the live table name with `list_data_tables`). Do not
  echo the API key anywhere in the summary.
- **Latency expectation:** the connector polls the Cortex XDR API; with detection activity in
  the tenant, first events should land within roughly **15–30 minutes**. A quiet tenant may
  genuinely have nothing new to pull — compare with what the customer's own Cortex console shows
  for the same window before calling it broken. Mark ⏳ inside that window, not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "CortexXDR",
  "instance": "cortexxdr",
  "index": "Cortex",
  "authMode": "advanced",
  "keyRole": "<role assigned to the API key, e.g. Viewer>",
  "keyExpiry": "<none unless Enable Expiration Date was set — record the date if so>"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the `Cortex` datalake index over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first). A plain
   row count is the smoke test.
3. Cross-check against the customer's own Cortex XDR console — if it shows activity for the same
   window and the datalake shows none past the latency window, move to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / authentication failure | Key mistyped, revoked, or expired (if an expiration date was set) — or the **`authMode` doesn't match the key's security level** (an Advanced key presented in standard mode, or vice versa). Fix the mode or regenerate the key. |
| Connector can't reach the tenant / wrong URL | The console URL was pasted instead of the `https://api-{fqdn}` API URL. Re-copy via **Copy API URL** on the API Keys page. |
| Auth fails with the right key | Wrong `apiKeyId` — the ID must be the **ID column value of this exact key** in the API Keys table, not another key's. |
| Key works but data is denied | The key's role lacks read access to the data. Create a new key with a role that can view it (the read-only **Viewer** role suffices for pulls) and update the connector. |
| Events flowed, then stopped | Check (in order): key expired (expiration notifications go out 1 week and 1 day ahead)? Key regenerated on the Cortex side (the old value dies)? Role changed? |
| Key value not captured | Shown once. Regenerate the key in **Settings → Configurations → Integrations → API Keys** and update the connector with the new value. |
| A Cortex XDR connector already exists | Ask before adding a second instance (`cortexxdr-2`); two instances polling the same tenant double the API load for no benefit unless they intentionally target different datalake indexes. |

---

## Security notes

- The API key is a credential: never paste it into logs, tickets, summaries, or long-lived chat
  beyond the `create_connector` call.
- **Prefer the Advanced security level** (the default here): Advanced keys are hashed with a
  nonce and timestamp to prevent replay attacks; Standard keys travel as-is.
- **Least privilege lives in the key's role** — assign the read-only **Viewer** role (or a
  custom read-only role) rather than an admin role; the key is exactly as powerful as its role.
- Rotation: regenerate the key (or create a new one) in **Settings → Configurations →
  Integrations → API Keys**, update the connector, then delete the old key. Do the same
  immediately if the key is ever exposed. Consider **Enable Expiration Date** for forced
  rotation — Cortex warns one week and one day before expiry.

---

## Layout

```
setup-cortex-xdr-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Palo Alto documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
