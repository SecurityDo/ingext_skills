---
name: setup-sophos-central-connector
version: 1.0.0
description: >-
  Set up the Sophos EDR connector on Fluency / Ingext: import Sophos endpoint detection events
  from Sophos Central via its API. Guides the customer through the Sophos-side work — a Super
  Admin creating a least-privilege API credential (Global Settings → Access Control → API
  Credentials, role "Service Principal Read-Only") in the Sophos Central Admin console — with
  every step backed by Sophos documentation, then performs the Fluency-side install itself via
  create_connector. The Sophos side is portal-only (an admin must click the console; there is no
  agent-drivable CLI), so the agent guides those steps and does everything else. SELF-CONTAINED:
  it ends by creating the "SophosEDR" connector itself — when routed from customer-onboarding, do
  NOT chain into add-connector afterward. Triggers: "add Sophos to Ingext", "connect Sophos
  Central", "import Sophos EDR events into Fluency", "set up the Sophos connector", "ingest
  Sophos Central alerts". Do NOT use for Sophos Firewall (XG/XGS) or Sophos UTM syslog — those
  are the different SophosFWLog / SophosUTMSyslog connectors with no dedicated skill; route them
  to add-connector. Also not for generic installs where the user already holds a working Sophos
  API credential and just says "install connector X" — add-connector also handles that.
---

# Set up the Sophos EDR (Sophos Central) connector

Import **Sophos Central EDR** events — endpoint detections and related security events — into
Fluency / Ingext via the Sophos Central API. Two things are needed, and only one of them is
yours to collect from the customer:

- **Sophos side (customer's admin console):** an **API credential** (Client ID + Client Secret),
  created by a Super Admin with a least-privilege role. Portal-only — guide it, step by step.
- **Fluency side (yours):** install the **`SophosEDR`** connector (display name "Sophos EDR")
  with those two values. Do this for the operator via the MCP.

Vendor-side steps below are backed by Sophos documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Sophos | API credential | Named `ingext-sophos`; role **Service Principal Read-Only**; issues a Client ID + Client Secret; the **Client Secret is shown once** |
| Ingext | Connector | Template **`SophosEDR`** ("Sophos EDR"), instance e.g. `sophosedr`; the template carries no index parameter — confirm the live datalake table with `list_data_tables` |

Nothing here is billable on the Sophos side.

---

## Prerequisites

- A **Sophos Central Super Admin** — Sophos requires the Super Admin role to manage and add API
  credentials.
- Access to the customer's own **Sophos Central Admin** console (the customer/tenant console).
  The Partner and Enterprise consoles have their own API-credential pages, but those issue
  partner-/organization-scoped credentials for managing many tenants — this connector wants a
  credential created in the customer tenant's own Admin console.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  pastes the values into the Fluency UI instead.

---

## The offer — who does what

The Sophos Central console cannot be driven by the agent — a Sophos admin clicks those steps.
Ask (use `AskUserQuestion` if unclear) whether the operator wants:

- **(a) Guided + agent installs (default):** you walk the admin through the credential creation
  click-by-click, collect the two values (Client ID, Client Secret), and then **you** create the
  Ingext connector and verify ingestion.
- **(b) Runbook only:** print the full procedure (both sides) for the customer to run later —
  e.g. when the Sophos admin isn't in this conversation. Offer to resume the install step
  whenever they return with the values.

If the operator already has a working Client ID and Client Secret in hand, skip straight to the
[Ingext-side install](#ingext-side--install-the-connector).

---

## Sophos side — create the API credential (guided)

### 1 — Confirm the right console and the right admin

- The admin must be a **Super Admin** in the customer's **Sophos Central Admin** console — only
  Super Admins can manage and add API credentials.
- Make sure it's the customer's own Admin console, **not** the Sophos Central **Partner** or
  **Enterprise** console. Those consoles issue credentials scoped to the partner/organization
  rather than to this tenant; the connector expects a tenant credential.

### 2 — Create the credential

In **Sophos Central Admin**:

1. **Global Settings → Access Control → API Credentials** (labelled "API Credentials
   Management") → **Add Credential**.
2. Name it **`ingext-sophos`** and give it a description.
3. Choose the role: **Service Principal Read-Only** — it can view all information in the account
   but can't add, modify, or remove anything, which is all the connector needs. (The other roles
   offered — Super Admin, Management, Forensics, Active Directory Sync, Firewall — are either
   more privilege than needed or the wrong scope entirely.)
4. Click **Add**. Sophos generates a **Client ID** and a **Client Secret**.
5. **Copy both immediately** — the **Client Secret is shown only once**.

> **Credential lifetime:** Sophos sends **no alert** when an API credential expires — an expired
> credential simply stops authenticating and is automatically removed from Sophos Central. The
> public docs don't publish a fixed lifetime, so if ingestion ever stops with auth errors, check
> whether the credential still appears in the API Credentials list (see Failure modes).

### 3 — What happens with these values (context, no action needed)

Fluency exchanges the credential pair for a short-lived (1-hour) access token at Sophos's
central OAuth endpoint and discovers the tenant ID and data region automatically — which is why
the connector needs only the two values and no region or tenant parameter.

**Deliverables from this section:** `clientID` + `clientSecret` (both form a credential — never
echo the secret back; refer to it as "the Client Secret from step 2").

---

## Ingext side — install the connector

With the two values in hand, do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`SophosEDR`** template ("Sophos EDR") and
   use its current parameter schema; the names below are a snapshot, not truth.
2. **`list_connectors`** — if a Sophos EDR connector already exists, show its instance/state and
   confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `SophosEDR`
   - `instance`: `sophosedr` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Sophos EDR`
   - `inputParameters`: **every** template parameter — at the time of writing `clientID` and
     `clientSecret` (sensitive); if the live schema has grown more (e.g. datalake/index),
     include them too (user value → default → `""`).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Sophos
EDR**, paste the Client ID and Client Secret, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; run the install section above before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and the
  datalake table (the template carries no index parameter, so the platform assigns it — confirm
  the live name with `list_data_tables`). Do not echo the Client Secret anywhere in the summary.
- **Latency expectation:** the connector polls the Sophos Central API; first events should land
  within roughly **15–30 minutes** — *if there are events to fetch*. A healthy, quiet endpoint
  fleet genuinely produces few EDR events; compare with what the customer's own Sophos Central
  console shows for the same window before calling it broken. Mark ⏳ inside that window,
  not ❌.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials):

```json
{
  "connector": "SophosEDR",
  "instance": "sophosedr",
  "index": "<confirm live with list_data_tables>",
  "credentialName": "ingext-sophos",
  "credentialRole": "Service Principal Read-Only",
  "credentialScope": "tenant (created in Sophos Central Admin)"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. After ~15–30 min, count rows in the Sophos datalake table over the last hour via the
   **`ingext-kql`** skill (confirm the live table name with `list_data_tables` first — the
   template has no index default). A plain row count is the smoke test.
3. Cross-check against the customer's own Sophos Central console — if it shows endpoint events
   for the same window and the datalake shows none past the latency window, move to Failure
   modes. If both are quiet, the fleet may genuinely be quiet.

---

## Failure modes

| Situation | Response |
|---|---|
| Connector errors with 401 / auth failure | Secret mistyped (it was shown once), the credential expired (no alert is sent; expired credentials vanish from the console list), or it was deleted. Check Global Settings → Access Control → API Credentials — if `ingext-sophos` is gone, recreate it (step 2) and update the connector. |
| Credential created in the wrong console | A credential from the Partner or Enterprise console is partner-/organization-scoped, not tenant-scoped. Recreate it in the customer's own Sophos Central Admin console. |
| Wrong role on the credential | Firewall / Active Directory Sync roles can't read EDR data; recreate the credential with **Service Principal Read-Only**. |
| Admin can't see Add Credential | Only **Super Admins** can manage API credentials — get a Super Admin for step 2. |
| Client Secret not captured | Shown once. Delete the half-created credential in the API Credentials page and add a new one. |
| A Sophos EDR connector already exists | Ask before adding a second instance (`sophosedr-2`); two instances polling the same tenant double the API load for no benefit unless they intentionally target different datalakes. |
| Customer actually wants firewall/UTM logs | That's `SophosFWLog` (Sophos Firewall Syslog) or `SophosUTMSyslog` — different connectors with no dedicated skill; route to `add-connector`. |

---

## Security notes

- The Client ID + Client Secret pair is a credential: never paste the secret into logs, tickets,
  summaries, or long-lived chat beyond the `create_connector` call.
- **Least privilege lives in the role** — assign **Service Principal Read-Only** so the
  credential can view but never change anything in Sophos Central.
- Rotation: add a new credential, update the connector, then delete the old credential in
  **Global Settings → Access Control → API Credentials**. Do the same immediately if the secret
  is ever exposed.
- Expiry is silent — Sophos sends no alert and removes expired credentials automatically. Note
  the credential in the customer's rotation calendar rather than waiting for ingestion to stop.
- The 1-hour access tokens Fluency derives from the pair are short-lived and managed by the
  platform; only the credential pair itself needs protecting.

---

## Layout

```
setup-sophos-central-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Sophos documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
