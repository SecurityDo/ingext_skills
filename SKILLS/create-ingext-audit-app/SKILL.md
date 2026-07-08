---
name: create-ingext-audit-app
version: 1.0.0
description: >-
  Guide an Azure AD / Entra admin through creating the "ingext-audit" app registration that
  Fluency / Ingext uses to import Office 365 Management audit events, Azure AD / Entra audit
  events, and Azure AD resources (users, groups, devices, applications). Registers a
  customer-owned, app-only (client-credentials) app, adds nine APPLICATION permissions across
  Microsoft Graph and the Office 365 Management APIs, grants admin consent, creates a client
  secret, and returns three fields — tenantId, clientId, clientSecret — for the downstream
  install-application stage. Offers a ready-to-run PowerShell script (Microsoft.Graph SDK) or a
  manual portal walkthrough. Triggers: "create the ingext-audit app", "register the Azure/Entra
  app for Ingext audit import", "onboard a customer tenant to Ingext (app registration stage)".
  Do NOT use for the hosted OAuth consent flow (multi-tenant app + adminConsentEmail) — that's
  the add-connector skill's Office365 / AzureAudit connectors.
---

# Create the `ingext-audit` Entra Application

Walk an Azure AD / Entra administrator through registering **`ingext-audit`**, a customer-owned
application that Fluency / Ingext authenticates as (app-only / client-credentials) to import:

- **Office 365 Management** audit events — the unified activity feed and DLP events
- **Azure AD / Entra** audit events
- **Azure AD resources** — users, groups, devices, applications, and other directory objects

This skill's job **ends when it has produced three values** — `tenantId`, `clientId`,
`clientSecret` — which the next onboarding stage ("install application") consumes. It does not
start Office 365 subscriptions or configure the Fluency connector; those happen later.

> **You (Claude) cannot run this against the customer's tenant.** It requires the admin's own
> interactive sign-in to *their* Entra tenant. Your role is to guide the admin: have them run the
> bundled PowerShell script, or click through the portal, and then collect the three fields they
> report back.

## What this creates

| Item | Detail |
|---|---|
| App registration | Display name `ingext-audit`, single-tenant (`AzureADMyOrg`) |
| API permissions | 9 **Application** (app-only, type `Role`) permissions across 2 APIs (see below) |
| Admin consent | Tenant-wide consent granted for all 9 permissions |
| Client secret | One secret, 24-month expiry — its value is the `clientSecret` field |

## Prerequisites

- An admin who can **both** create app registrations **and grant tenant-wide admin consent** —
  **Global Administrator**, or **Privileged Role Administrator** combined with **Application
  Administrator** / **Cloud Application Administrator**. Without consent rights the app is created
  but the permissions stay unconsented and Ingext cannot read data.
- **Script path only:** PowerShell 7+ and the Microsoft Graph SDK:
  `Install-Module Microsoft.Graph -Scope CurrentUser`.

## Permissions granted

All are **Application** permissions (`type = Role`, app-only — no signed-in user). The exact
`Value` strings below must match; the script resolves each one's role ID at runtime from the
resource service principal, so no GUIDs are hardcoded. A standalone copy of this table lives in
`assets/permissions.md`.

| API (resourceAppId) | Permission | Purpose |
|---|---|---|
| Microsoft Graph `00000003-0000-0000-c000-000000000000` | `Directory.Read.All` | Azure AD resources — users, groups, devices, apps |
| " | `AuditLog.Read.All` | Azure AD audit & sign-in logs |
| " | `Policy.Read.All` | Conditional-access / directory policy |
| " | `Reports.Read.All` | Usage & security reports |
| " | `UserAuthenticationMethod.Read.All` | MFA / authentication-method registration |
| " | `MailboxSettings.Read` | Mailbox settings |
| Office 365 Management APIs `c5393580-f805-4401-95e8-94b7a6ef2fc2` | `ActivityFeed.Read` | O365 unified audit activity feed |
| " | `ActivityFeed.ReadDlp` | DLP events in the activity feed |
| " | `ServiceHealth.Read` | Service health / incidents |

---

## Choose a path

Ask the admin which path they prefer (use `AskUserQuestion` if the caller didn't specify):

- **Path A — PowerShell (recommended):** fastest and least error-prone; creates the app, applies
  all permissions, grants consent, and prints the three fields in one run.
- **Path B — Manual (Azure portal):** click-through, for admins who prefer the UI or can't run the
  Graph SDK.

Either way, the deliverable is the same three fields.

---

## Path A — PowerShell (recommended)

The script is bundled at `assets/setup-ingext-audit.ps1`. **Have the admin run it themselves** on a
machine signed in to their tenant — you cannot run it for them.

1. Install the SDK once (if needed): `Install-Module Microsoft.Graph -Scope CurrentUser`.
2. Run the script. Give the admin the path (`${SKILL_DIR}/assets/setup-ingext-audit.ps1`), or paste
   its contents for them to save and run:

   ```powershell
   ./setup-ingext-audit.ps1
   # optional overrides:
   ./setup-ingext-audit.ps1 -AppName "ingext-audit" -SecretMonths 24
   ```
3. A browser / device-code prompt appears — the admin signs in and consents to the script's own
   scopes (`Application.ReadWrite.All`, `AppRoleAssignment.ReadWrite.All`, `Directory.Read.All`).
4. The script is **idempotent**: if `ingext-audit` already exists it reuses it, re-applies the
   permissions, and adds a fresh secret rather than creating a duplicate.
5. It prints a JSON object with `tenantId`, `clientId`, `clientSecret`. Collect those three values.

What the script does, in order: connect → read `tenantId` from `Get-MgContext` → get the Microsoft
Graph and Office 365 Management API service principals (creating the O365 one if the tenant lacks
it) → resolve each permission name to its app-role ID → create/update the `ingext-audit` app with
`requiredResourceAccess` → ensure the app's service principal exists → add a 24-month client secret
→ grant admin consent by creating an app-role assignment per permission → emit the three fields.

---

## Path B — Manual (Azure portal)

Direct the admin through **[https://entra.microsoft.com](https://entra.microsoft.com)** (or the
Azure portal → **Microsoft Entra ID**):

1. **App registrations → New registration.** Name it **`ingext-audit`**. Supported account types:
   **Accounts in this organizational directory only (single tenant)**. Leave Redirect URI blank.
   Click **Register**.
2. On the app's **Overview**, copy **Directory (tenant) ID** → this is `tenantId`, and
   **Application (client) ID** → this is `clientId`.
3. **API permissions → Add a permission → Microsoft Graph → Application permissions.** Search for
   and check each of these six, then **Add permissions**:
   - `Directory.Read.All`, `AuditLog.Read.All`, `Policy.Read.All`, `Reports.Read.All`,
     `UserAuthenticationMethod.Read.All`, `MailboxSettings.Read`
4. **Add a permission →** open the **APIs my organization uses** tab and search
   **`Office 365 Management APIs`** → **Application permissions.** Check these three, then
   **Add permissions**:
   - `ActivityFeed.Read`, `ActivityFeed.ReadDlp`, `ServiceHealth.Read`
5. **Grant admin consent for &lt;tenant&gt;** and confirm. Every row's **Status** must turn to a green
   **“Granted for &lt;tenant&gt;.”** (If the button is greyed out, the signed-in admin lacks consent
   rights — see Failure modes.)
6. **Certificates & secrets → Client secrets → New client secret.** Description `ingext-audit`,
   expiry **24 months**, **Add**. **Copy the secret Value immediately** — it is shown only once and
   becomes `clientSecret`. (Copy the **Value**, not the Secret ID.)

---

## Output — the three fields

Present the result both human-readably and as a JSON block so a calling onboarding task can parse it
deterministically. **The client secret is shown once** (portal) — make sure the admin captured it.

```json
{
  "tenantId": "<Directory (tenant) ID>",
  "clientId": "<Application (client) ID>",
  "clientSecret": "<client secret Value>"
}
```

Hand these three fields to the **install-application** stage. Do not echo the secret into logs or
long-lived chat history beyond what's needed to pass it along.

---

## Verification

- **Consent granted:** in the portal, every permission row shows a green
  **“Granted for &lt;tenant&gt;.”** From the script path, admin consent is created programmatically;
  the admin can re-check with
  `Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId <appSp.Id>` (9 assignments expected).
- **Fields captured:** `tenantId` and `clientId` are GUIDs; `clientSecret` is a non-empty secret
  value (not the Secret ID).
- You (Claude) cannot verify inside the customer's tenant — rely on the admin's confirmation or the
  script's printed output.

---

## Failure modes

| Situation | Response |
|---|---|
| **Grant admin consent** button greyed out / consent fails | The signed-in admin lacks consent rights. Have a Global Administrator (or Privileged Role Admin + Application/Cloud Application Admin) grant consent. The app + permissions already exist; only consent is missing. |
| **Office 365 Management APIs** not in the permissions picker | It is not on the "Microsoft APIs" tab — open **APIs my organization uses** and search the exact name `Office 365 Management APIs`. |
| Client secret value not copied | The value is shown once. Delete the secret and add a new one (Certificates & secrets), or re-run the script to add a fresh secret. |
| `Microsoft.Graph` module not installed (script path) | Run `Install-Module Microsoft.Graph -Scope CurrentUser`, then re-run the script. |
| App named `ingext-audit` already exists | Expected on re-runs. The script reuses it (re-applies permissions, adds a fresh secret). In the portal, reuse the existing registration rather than creating a second one. |
| Script throws "permission not found on resource" | A permission `Value` is misspelled or the resource API isn't available in the tenant — verify the name against the Permissions table. |

---

## Security notes

- Every permission is **read-only** (`*.Read` / `*.Read.All`) — least privilege for an audit importer.
- The client secret is a credential: it is shown once, and `secretText` is never retrievable again.
  It expires in **24 months** — rotate by re-running the script (or adding a new secret in the
  portal) before expiry and updating the install-application stage.
- Don't paste the secret into logs, tickets, or persistent chat beyond handing it to the next stage.

---

## Layout

```
create-ingext-audit-app/
├── SKILL.md
├── assets/
│   ├── setup-ingext-audit.ps1   ← Microsoft.Graph script: creates app, grants consent, prints the 3 fields
│   └── permissions.md            ← standalone reference table of the 9 permissions
└── evals/
    └── evals.json                ← trigger phrases for skill selection
```
