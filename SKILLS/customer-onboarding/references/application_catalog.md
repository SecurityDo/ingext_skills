# Application catalog

The routing map for `customer-onboarding`. **This is the only file to edit when a new deep-dive
skill lands** — add a row, and the router picks it up.

Two tiers:

- **Guided** — the application has a dedicated skill that handles prerequisites the generic
  connector installer cannot (cloud IAM plumbing, customer-owned app registration). Route there.
- **Standard** — no dedicated skill; `add-connector` discovers the template live via
  `list_connector_templates` and installs it. The rows below are a convenience for recognising the
  request, **not** an authoritative template list. The platform is the source of truth; never quote
  these template names back to the user as "what's available" — call `list_connector_templates`.

---

## Guided applications

### AWS CloudTrail

| Field | Value |
|---|---|
| **Aliases** | CloudTrail, AWS audit logs, AWS API logs |
| **Route** | `setup-aws-cloudtrail-connector` (self-contained — it ends in `create_connector` itself) |
| **Auth path** | AWS cross-account assume-role (`ingextAssumeRole`) + S3 → SQS notification |
| **Prerequisites** | An existing S3 bucket CloudTrail writes to; the bucket's region; ability to run CloudFormation in the customer's own AWS account. Optional: object prefix, external ID |
| **Hands back** | Nothing to carry — the skill installs the connector itself |
| **Datalake table** | `AWSCloudTrail` — confirm the live name with `list_data_tables` before querying |
| **First-event latency** | ~5 min (CloudTrail batches deliveries to S3), plus queue drain |

The same plumbing fits other S3-notification sources — AWS CloudWatch Logs (S3), Fluent Bit (S3),
GuardDuty in S3. That skill documents how to swap the connector in its final step.

### Microsoft 365 / Entra audit logs

| Field | Value |
|---|---|
| **Aliases** | Office 365, O365, Microsoft 365, Entra audit, Azure AD audit, AzureAudit |
| **Route** | `create-ingext-audit-app` → **then** `add-connector` |
| **Auth path** | **Customer-owned app** (app-only client credentials) — *not* the hosted OAuth consent flow |
| **Prerequisites** | An Entra **Global Administrator** (admin consent is required for the nine Application permissions) |
| **Hands back** | `tenantId`, `clientId`, `clientSecret` → carry into `add-connector` |
| **Datalake table** | `Office365`, `AzureAuditLogs` |
| **First-event latency** | Up to ~30–60 min for the first Office 365 Management API events after subscription starts |

> **Fork in the road — ask before routing.** Microsoft 365 has *two* onboarding paths and they are
> not interchangeable:
>
> - **Customer-owned app** → `create-ingext-audit-app` → `add-connector`. The customer registers
>   and owns the app. Use when they want the app in their own tenant, or when policy forbids
>   third-party multi-tenant apps.
> - **Hosted OAuth consent** → `add-connector` **alone**. The Office365 / AzureAudit templates take
>   only `adminConsentEmail`; a consent email goes to that address and the admin authorises
>   Fluency's multi-tenant app. See `add-connector` Step 7.
>
> Never send a customer-owned-app tenant into the consent flow, or vice versa. If it's unclear
> which they want, ask.

### Microsoft Defender

| Field | Value |
|---|---|
| **Aliases** | Defender, MS Defender, Defender XDR, Graph Security incidents/alerts |
| **Route** | `create-ingext-defender-app` → **then** `add-connector` |
| **Auth path** | **Customer-owned app** (app-only client credentials) |
| **Prerequisites** | An Entra **Global Administrator** (admin consent for `SecurityIncident.Read.All`, `SecurityAlert.Read.All`) |
| **Hands back** | `tenantId`, `clientId`, `clientSecret` → carry into `add-connector` |
| **Datalake table** | Confirm with `list_data_tables` — varies by platform version |
| **First-event latency** | Polling-based; allow ~15–30 min, and note incidents only appear if Defender has generated any |

---

## Standard applications (route: `add-connector`)

Aliases mirror `add-connector`'s own matching list, which is authoritative for template matching.

| Application | Aliases | Auth path | Prerequisites | Datalake table |
|---|---|---|---|---|
| Office 365 (consent path) | O365, Microsoft 365 | Hosted OAuth consent | Admin email; admin completes consent | `Office365` |
| Google Workspace | GSuite, G Suite | Hosted OAuth consent | Admin email; admin completes consent | `gsuiteUser`, `gsuiteGroup` |
| FortiGate | Fortinet, FortiGate firewall | Syslog | Device configured to forward syslog to the Fluency endpoint | `NetworkFortigateTraffic`, `NetworkFortigateEvent` |
| SentinelOne | S1 | API key | Console URL + API token | `sentinelOneAgent` |
| Bitdefender | GravityZone | API key | Ask which variant: GravityZone (ST) vs Endpoint (EP) | — |
| Proofpoint | — | API key | Ask which variant: TAP vs Essentials | — |
| Amazon GuardDuty | GuardDuty | AWS role / user / access key | If findings land in S3, prefer the CloudTrail skill's plumbing and swap the connector | — |

**Anything not listed here is still supported.** `add-connector` calls `list_connector_templates`
and matches against the live catalogue. Route unknown vendors there rather than declaring them
unavailable — only `add-connector` can say that, from live data.

---

## FortiGate bandwidth caveat

If a customer onboards FortiGate and later asks about bandwidth, top talkers, or traffic volume,
the `fortigate-bandwidth` skill fires automatically — FortiGate byte fields are cumulative session
counters and a naive `sum()` over-counts badly. Nothing to do at onboarding time; noted here so the
router doesn't hand-roll a verification query that trips over it. For the Step 5 event-count check,
a plain row count is safe.
