---
name: setup-bitdefender-securitytelemetry-connector
version: 1.0.0
description: >-
  Set up the Bitdefender SecurityTelemetry HEC connector on Fluency / Ingext: stream raw
  security telemetry (EDR events) from Bitdefender GravityZone endpoints into the datalake via
  a Splunk-compatible HEC endpoint the platform generates. The flow is INVERTED relative to
  API-credential skills: install the connector FIRST via create_connector, capture the HEC URL
  and token the platform outputs, then guide the GravityZone admin to point the policy's
  Security Telemetry settings (General → Security Telemetry, SIEM Connection Settings) at those
  values — every vendor step backed by cited Bitdefender documentation. The GravityZone side is
  portal-only, so the agent guides those steps and does everything else. SELF-CONTAINED: it
  ends with the "BitdefenderST" connector created and the vendor-side follow-up handed over —
  when routed from customer-onboarding, do NOT chain into add-connector afterward. Triggers:
  "add Bitdefender to Ingext", "connect GravityZone security telemetry", "stream Bitdefender
  EDR telemetry into Fluency", "set up the Bitdefender HEC connector", "ingest GravityZone raw
  events". Do NOT use for BitdefenderEP (Bitdefender Event Push API) — a different variant with
  no dedicated skill yet; route it to add-connector. When the user just says "Bitdefender", ask
  which variant (Security Telemetry vs Event Push) before proceeding.
---

# Set up the Bitdefender SecurityTelemetry HEC connector

Stream **Bitdefender GravityZone Security Telemetry** — raw security events from endpoints
running the BEST agent with the EDR sensor — into Fluency / Ingext. GravityZone sends this
telemetry to a **Splunk-HEC-compatible** target, and the platform provides exactly that: the
**`BitdefenderST`** connector takes **no input parameters** and instead **outputs** a HEC
Server URL and HEC Token after install.

That inverts the usual order — and the skill's section order below deviates from the standard
blueprint for that reason:

1. **Fluency side first (yours):** install the connector, capture the generated **HEC URL** +
   **HEC Token**.
2. **Bitdefender side second (customer's Control Center):** configure the policy's **Security
   Telemetry** settings to point at those values. Portal-only — guide it, step by step.

Nothing arrives until step 2 is done and the policy reaches endpoints — **zero rows in the
datalake is expected** until then. Vendor-side steps are backed by Bitdefender GravityZone
documentation; citations live in `assets/references.md`.

> **ST vs EP:** the platform also carries **`BitdefenderEP`** ("Bitdefender EventPush") — the
> GravityZone **Event Push Service API** variant (companyID / accessUrl / apiKey), which pushes
> Control Center *events* rather than endpoint *telemetry*. That variant has no dedicated
> skill; route it to `add-connector`. A customer saying just "Bitdefender" must be asked which
> variant they mean.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Connector | Template **`BitdefenderST`** ("Bitdefender SecurityTelemetry HEC"), instance e.g. `bitdefenderst`; datalake table: confirm live (no index parameter) |
| Ingext | HEC endpoint | Platform-generated **HEC Server URL** + **HEC Token** (the template's `output` block) — these are credentials |
| Bitdefender | Policy change | Security Telemetry enabled in the policy applied to target endpoints, pointed at the HEC URL/token |

No new billable vendor resources — but Security Telemetry **requires a GravityZone license
that includes the EDR feature** (see Prerequisites), which the customer either has or doesn't.

---

## Prerequisites

- A **GravityZone Control Center administrator** who can edit and assign the security policy
  applied to the target endpoints.
- A GravityZone **license providing access to the EDR feature** — Security Telemetry is gated
  on it. Endpoints must run the **BEST agent with the EDR sensor enabled** by policy.
- **Network egress from the endpoints** to the generated HEC URL over HTTPS — GravityZone's
  agent sends telemetry **directly from each endpoint** to the SIEM target, not via the cloud
  console. TLS 1.2 or higher is required.
- The **Fluency Ingext MCP** connected for the target Ingext instance. Without it, the operator
  installs via the Fluency UI instead.

---

## The offer — who does what

First confirm the **variant**: Security Telemetry (this skill) vs Event Push API
(`BitdefenderEP` via `add-connector`). Then the GravityZone Control Center cannot be driven by
the agent — a GravityZone admin clicks those steps. Ask (use `AskUserQuestion` if unclear)
whether the operator wants:

- **(a) Agent installs + guided config (default):** **you** create the Ingext connector,
  surface the generated HEC URL/token once, and walk the admin through the policy change
  click-by-click, then verify ingestion when telemetry starts.
- **(b) Runbook only:** install the connector (that part is always yours if the MCP is
  connected), then print the vendor-side procedure — including the HEC values, clearly marked
  as secrets — for the customer's admin to run later. Offer to resume verification whenever
  the vendor side is done.

If the connector is **already installed** and the operator just needs the vendor side, skip the
install: retrieve the HEC values from the existing instance (below) and go straight to the
[GravityZone side](#gravityzone-side--point-security-telemetry-at-the-hec-endpoint).

---

## Ingext side — install the connector first

Do this for the operator (MCP connected):

1. **`list_connector_templates`** — locate the live **`BitdefenderST`** template ("Bitdefender
   SecurityTelemetry HEC") and use its current schema; the shape described here is a snapshot,
   not truth. Take care **not** to grab `BitdefenderEP` by mistake.
2. **`list_connectors`** — if a Bitdefender connector already exists (either template), show
   its instance/state and confirm before adding a second instance.
3. **`create_connector`** with:
   - `application`: `BitdefenderST`
   - `instance`: `bitdefenderst` (lowercase, ≤20 chars, **never `"default"`**; `-2` suffix on
     collision)
   - `displayName`: `Bitdefender SecurityTelemetry HEC`
   - `inputParameters`: every parameter the live schema shows — in the current snapshot the
     template defines **none**, so this is empty.
4. **Capture the template's `output` values** — the **HEC Server URL** (`url`) and **HEC
   Token** (`token`) — from the create result or from `get_connector` on the new instance; if
   the MCP response doesn't carry them, read them from the connector's page in the Fluency UI.
5. **Display both values exactly once**, explicitly labeled as credentials the admin will paste
   into GravityZone in the next section. Do not repeat them in any later summary, checklist, or
   the JSON output block.

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add →
**Bitdefender SecurityTelemetry HEC**, save, then read the HEC URL and token from the
connector's page.

---

## GravityZone side — point Security Telemetry at the HEC endpoint (guided)

In the **GravityZone Control Center**, as an admin:

1. Open **Policies** and edit the policy applied to the target endpoints (or clone it, edit the
   clone, and reassign — the customer's change-control call).
2. Go to the **General → Security Telemetry** section of the policy (Bitdefender's docs also
   reference it as **General → Agent → Security Telemetry** depending on console/doc version).
3. **Enable the Security Telemetry option.**
4. Under **SIEM Connection Settings**, enter:
   - **SIEM server URL** — the **HEC Server URL** from the connector output.
   - **Token** — the **HEC Token** from the connector output (GravityZone's docs call it the
     "Splunk token" / HTTP Event Collector token).
5. Transport is **HTTPS with TLS 1.2 or higher** — event submission fails otherwise. The
   Fluency endpoint presents a valid certificate, so the **Bypass collector CA validation** /
   **Ignore SSL errors** options should stay off; they exist for self-hosted SIEMs with
   self-signed certificates.
6. Select the event categories the customer wants if the section offers choices. Note from
   Bitdefender's docs: **DNS query and network connection events additionally require the
   Network Attack Defense module** installed and enabled on the endpoints.
7. **Save the policy** and confirm it is assigned to the intended endpoints.

Endpoints send telemetry as JSON **directly** to the HEC URL — so the endpoints (not the
Control Center) need HTTPS egress to it. Policy changes take effect as endpoints sync, which
can be minutes for online machines and longer for offline ones.

**Deliverable of this section:** GravityZone streaming to the connector's HEC endpoint. There
is nothing to collect back — the credentials flowed vendor-ward, which is the inversion.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Do **not** hand off to
  `add-connector`; the connector was created in the install section above.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the router's checklist and verification: the connector `instance` id and
  the datalake table — the template exposes **no index parameter**, so confirm the live table
  name with `list_data_tables` once events land. Do not echo the HEC URL or token anywhere in
  the hand-back (they were displayed once, during vendor-side configuration).
- **Zero rows is EXPECTED at hand-back time** — this is a push source: nothing arrives until
  the GravityZone policy is saved, assigned, synced to endpoints, and those endpoints generate
  telemetry. The router must mark this application **⏳ (pending, vendor-side follow-up)** —
  not ❌ — with the follow-up noted: "GravityZone policy → General → Security Telemetry must
  point at the connector's HEC endpoint". Once endpoints stream, delivery is near-real-time.

---

## Output — the deliverable

Report human-readably plus a JSON block (no credentials — the HEC URL/token were shown once
during configuration and are deliberately absent here):

```json
{
  "connector": "BitdefenderST",
  "instance": "bitdefenderst",
  "index": "confirm live with list_data_tables — the template exposes no index parameter",
  "hecValues": "generated by the platform; displayed once to the operator for the GravityZone policy, not repeated here",
  "vendorFollowUp": "GravityZone policy → General → Security Telemetry → SIEM Connection Settings must carry the HEC URL/token; requires an EDR-capable license and BEST agents with the EDR sensor",
  "status": "pending — zero datalake rows are expected until endpoints start streaming"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state. This alone does
   **not** mean data is flowing; a HEC connector is a listener.
2. Once the customer confirms the policy is saved and assigned, allow for endpoint policy sync
   (minutes for online endpoints), then find the live table with **`list_data_tables`** and
   count rows over the last hour via the **`ingext-kql`** skill.
3. **Honest latency:** delivery is near-real-time *once endpoints stream*, but the total
   time-to-first-event is dominated by the vendor side — policy sync plus actual endpoint
   activity. Zero rows with the vendor side unconfigured or freshly configured is ⏳, not ❌.
4. If rows never arrive after the policy has demonstrably synced and endpoints are active, move
   to Failure modes — and check the endpoints' egress to the HEC URL first.

---

## Failure modes

| Situation | Response |
|---|---|
| No events, vendor side "done" | Verify in order: policy actually saved **and assigned** to the target endpoints; endpoints online and synced since the change; endpoints have HTTPS egress to the HEC URL (host-level firewalls and proxies count — the agent sends directly from each endpoint). |
| Security Telemetry section missing from the policy | The license likely lacks the EDR feature — Security Telemetry is gated on it. Confirm the GravityZone tier with Bitdefender; without EDR entitlement this connector cannot receive anything. |
| TLS / submission errors on the GravityZone side | GravityZone requires HTTPS with TLS 1.2+. Confirm nothing (proxy, TLS-inspection middlebox) downgrades or re-signs the connection; the CA-bypass options are for self-signed targets and should not be needed against Fluency. |
| Expected DNS / network-connection events absent | Those event types require the Network Attack Defense module installed and enabled on the endpoints, per Bitdefender's docs. |
| HEC URL/token lost | Retrieve them from `get_connector` on the instance (the template's output block) or from the connector's page in the Fluency UI — treat the retrieval as a fresh one-time display. |
| HEC token suspected exposed | Create a new connector instance (`bitdefenderst-2` — a fresh token), repoint the GravityZone policy at the new values, then delete the old instance. |
| Customer meant the Event Push variant | `BitdefenderEP` (companyID / accessUrl / apiKey) is a different template with no dedicated skill — route to `add-connector`. |
| A BitdefenderST connector already exists | Don't create a duplicate listener by default — reuse the existing instance's HEC values for the policy unless the customer intentionally wants separate streams. |

---

## Security notes

- The **HEC URL and token are credentials**: anyone holding them can inject events into the
  customer's datalake. Display them once for the policy configuration, then refer to them only
  descriptively ("the HEC values from the install step"). Never put them in logs, tickets,
  summaries, or the JSON output.
- Rotation: the token is platform-generated per instance — rotate by creating a fresh instance,
  repointing the GravityZone policy, and deleting the old instance.
- Keep **Bypass collector CA validation** / **Ignore SSL errors** off unless Bitdefender
  support directs otherwise — they weaken transport security and are unnecessary against a
  properly certificated endpoint.
- Telemetry is raw endpoint security data — treat the datalake table with the same access
  discipline as EDR consoles.

---

## Layout

```
setup-bitdefender-securitytelemetry-connector/
├── SKILL.md
├── assets/
│   └── references.md    ← Bitdefender GravityZone documentation URLs backing each vendor-side step
└── evals/
    └── evals.json       ← trigger phrases for skill selection
```
