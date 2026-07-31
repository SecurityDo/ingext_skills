---
name: create-ingext-audit-app-azcli
version: 1.0.0
description: >-
  Azure CLI (az / Bash) variant for creating the "ingext-audit" Entra app registration that
  Fluency / Ingext uses to import Office 365 Management audit events, Azure AD / Entra audit
  events, and Azure AD resources (users, groups, devices, applications). Registers a
  customer-owned, app-only (client-credentials) app, adds nine APPLICATION permissions across
  Microsoft Graph and the Office 365 Management APIs, grants admin consent, creates a client
  secret, and returns three fields — tenantId, clientId, clientSecret — for the downstream
  install-application stage. Supports two modes: MODE A — the cowork operator is themselves the
  tenant's Global Admin, so cowork runs the bundled az CLI script directly (after the user's
  interactive `az login` and per-command permission approval); MODE B — guiding a third-party
  customer admin who runs the script (or the portal walkthrough) in their own tenant. Prefer this
  skill over the PowerShell one when the admin uses az CLI / Linux / macOS, or when the operator
  wants cowork to run the setup for them. Triggers: "install/register the ingext-audit Azure app
  with az CLI", "I'm the Global Admin, run the Ingext Entra app setup for me", "onboard our tenant
  to Ingext using the Azure CLI". Do NOT use for the hosted OAuth consent flow (multi-tenant app +
  adminConsentEmail) — that's the add-connector skill's Office365 / AzureAudit connectors.
---

# Create the `ingext-audit` Entra Application (az CLI)

Register **`ingext-audit`**, a customer-owned application that Fluency / Ingext authenticates as
(app-only / client-credentials) to import:

- **Office 365 Management** audit events — the unified activity feed and DLP events
- **Azure AD / Entra** audit events
- **Azure AD resources** — users, groups, devices, applications, and other directory objects

This skill's job **ends when it has produced three values** — `tenantId`, `clientId`,
`clientSecret` — which the next onboarding stage ("install application") consumes. It does not
start Office 365 subscriptions or configure the Fluency connector; those happen later.

This is the **Azure CLI (`az`) variant** of `create-ingext-audit-app` (which uses PowerShell +
Microsoft.Graph). Same nine permissions, same three-field output — different tooling, plus a
run-it-directly mode.

## What this creates

| Item | Detail |
|---|---|
| App registration | Display name `ingext-audit`, single-tenant (`AzureADMyOrg`) |
| API permissions | 9 **Application** (app-only, type `Role`) permissions across 2 APIs (see below) |
| Admin consent | Tenant-wide consent granted for all 9 permissions |
| Client secret | One secret, 2-year expiry — its value is the `clientSecret` field |

## Permissions granted

All are **Application** permissions (`type = Role`, app-only — no signed-in user). The script
resolves each one's role ID at runtime from the resource service principal, so no GUIDs are
hardcoded. A standalone copy of this table lives in `assets/permissions.md`.

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

## Prerequisites

- **Azure CLI** installed (`az version`).
- An identity that can **both** create app registrations **and grant tenant-wide admin consent** —
  **Global Administrator**, or **Privileged Role Administrator** combined with **Application
  Administrator** / **Cloud Application Administrator**. Without consent rights the app is created
  but the permissions stay unconsented and Ingext cannot read data.

---

## Pick a mode

**Ask who is at the keyboard** (use `AskUserQuestion` if it isn't already clear):

- **Mode A — "I am the tenant's Global Admin and want cowork to run it."** cowork executes the
  bundled `az` script on this machine, against the tenant the operator is signed in to. Use this
  when the cowork operator *is* the admin of the target tenant.
- **Mode B — "I'm onboarding a different tenant / another admin will run it."** cowork does **not**
  run anything against that tenant (it has no credentials there). Hand the admin the script or the
  portal walkthrough and collect the three fields they report back.

> **Why the distinction matters:** app registration + admin consent require an interactive sign-in
> to the *target* tenant. In Mode A that tenant is the operator's own and the sign-in happens on
> this machine, so cowork can drive it. In Mode B the tenant belongs to someone else — cowork
> cannot authenticate there, so its role is to guide.

---

## Mode A — cowork runs the az CLI script

Precondition: the cowork operator is a Global Admin (or equivalent) of the target tenant, and
cowork is running on a machine that can complete an Azure sign-in.

1. **Confirm the target tenant.** Run `az account show`. If it errors (not logged in), have the
   operator sign in — cowork can run it, but the operator completes the browser/device step:

   ```bash
   az login                    # opens a browser
   # or, headless / no browser on this machine:
   az login --use-device-code  # prints a code; the operator finishes sign-in in a browser
   ```

   Then re-run `az account show` and **read back the tenantId + account** so the operator confirms
   it is the intended tenant before anything is created.

2. **Run the bundled script.** It is idempotent — safe to re-run.

   ```bash
   bash ${SKILL_DIR}/assets/setup-ingext-audit.sh
   # optional overrides:
   bash ${SKILL_DIR}/assets/setup-ingext-audit.sh --app-name ingext-audit --secret-years 2
   ```

   - The script **stops for a confirmation prompt** ("Create/update app … in the tenant above?")
     unless run with `--yes`. Surface that prompt to the operator; only pass `--yes` if the
     operator has explicitly approved the target tenant.
   - cowork's normal per-command permission approval governs each `az` call — the operator stays
     in control of what runs.

3. **Capture the output.** The script writes **only the JSON object** to stdout (progress goes to
   stderr):

   ```json
   { "tenantId": "…", "clientId": "…", "clientSecret": "…" }
   ```

   Hand those three fields to the **install-application** stage. Treat `clientSecret` as a
   credential — do not echo it into logs or long-lived chat beyond passing it along.

What the script does, in order: preflight (`az` present + logged in) → read `tenantId` →
confirm target tenant → ensure the Microsoft Graph and Office 365 Management API service
principals exist (creating the O365 one if missing) → resolve each permission name to its
app-role ID → create/reuse the `ingext-audit` app → add the `requiredResourceAccess` →
ensure the app's service principal exists → `az ad app permission admin-consent` (with retry
for replication lag) → append a client secret → print the three fields.

---

## Mode B — guide a third-party admin

cowork cannot reach the customer's tenant. Offer the admin either path; the deliverable is the
same three fields.

### Path B1 — az CLI script (recommended for Linux/macOS admins)

Give the admin the script at `${SKILL_DIR}/assets/setup-ingext-audit.sh` (or paste its contents to
save and run). Tell them to:

1. Install Azure CLI if needed, then `az login` (or `az login --use-device-code`) **to their
   tenant** as a Global Admin.
2. Run `bash setup-ingext-audit.sh` and answer the confirmation prompt.
3. Copy the printed JSON (`tenantId`, `clientId`, `clientSecret`) back to you — the secret is
   shown once.

### Path B2 — manual Azure portal walkthrough

Direct the admin through **[https://entra.microsoft.com](https://entra.microsoft.com)** (or the
Azure portal → **Microsoft Entra ID**):

1. **App registrations → New registration.** Name it **`ingext-audit`**. Supported account types:
   **Accounts in this organizational directory only (single tenant)**. Leave Redirect URI blank.
   **Register**.
2. On **Overview**, copy **Directory (tenant) ID** → `tenantId`, and **Application (client) ID** →
   `clientId`.
3. **API permissions → Add a permission → Microsoft Graph → Application permissions.** Check these
   six, then **Add permissions**: `Directory.Read.All`, `AuditLog.Read.All`, `Policy.Read.All`,
   `Reports.Read.All`, `UserAuthenticationMethod.Read.All`, `MailboxSettings.Read`.
4. **Add a permission →** open **APIs my organization uses** → search **`Office 365 Management
   APIs`** → **Application permissions.** Check these three, then **Add permissions**:
   `ActivityFeed.Read`, `ActivityFeed.ReadDlp`, `ServiceHealth.Read`.
5. **Grant admin consent for &lt;tenant&gt;** and confirm. Every row's **Status** must turn green
   **"Granted for &lt;tenant&gt;."**
6. **Certificates & secrets → Client secrets → New client secret.** Description `ingext-audit`,
   expiry 24 months, **Add**. **Copy the secret Value immediately** — shown once — this is
   `clientSecret`. (Copy the **Value**, not the Secret ID.)

---

## Output — the three fields

Present the result both human-readably and as a JSON block so a calling onboarding task can parse
it deterministically. **The client secret is shown once** — make sure it was captured.

```json
{
  "tenantId": "<Directory (tenant) ID>",
  "clientId": "<Application (client) ID>",
  "clientSecret": "<client secret value>"
}
```

Hand these three fields to the **install-application** stage.

---

## Verification

- **Consent granted:** every permission shows as granted for the tenant. From the CLI:
  `az ad app permission list-grants --id <clientId>` shows delegated grants; for the app-role
  (application) assignments, check the app's service principal:
  `az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals(appId='<clientId>')/appRoleAssignments"`
  (9 assignments expected).
- **Fields captured:** `tenantId` and `clientId` are GUIDs; `clientSecret` is a non-empty value
  (not the Secret ID).
- In Mode B you cannot verify inside the customer's tenant — rely on the admin's confirmation or
  the script's printed output.

---

## Failure modes

| Situation | Response |
|---|---|
| `az account show` fails / "Please run 'az login'" | Not signed in. Run `az login` (or `az login --use-device-code`), confirm the tenant, then re-run the script. |
| **admin-consent** step warns it didn't complete | The signed-in identity lacks consent rights. A Global Admin (or Privileged Role Admin + Application/Cloud App Admin) runs `az ad app permission admin-consent --id <clientId>`. The app + permissions already exist; only consent is missing. |
| Wrong tenant selected | `az account show` shows the tenant before anything is created; the script also prompts for confirmation. Switch with `az login --tenant <id>` (or `az account set --subscription <id>`), then re-run. |
| **Office 365 Management APIs** SP missing | Expected in some tenants — the script creates it (`az ad sp create --id c5393580-...`). In the portal, find the API under **APIs my organization uses**. |
| Client secret value not captured | It is shown once. Re-run the script (it appends a fresh secret) or add a new one in **Certificates & secrets**. |
| App named `ingext-audit` already exists | Expected on re-runs — the script reuses it (re-applies permissions, appends a fresh secret). In the portal, reuse the existing registration. |
| `permission not found on resource` | A permission name is misspelled or the resource API isn't available in the tenant — verify against the Permissions table. |

---

## Security notes

- Every permission is **read-only** (`*.Read` / `*.Read.All`) — least privilege for an audit importer.
- The client secret is a credential shown once and never retrievable again. It expires in **2 years**
  — rotate by re-running the script (or adding a new secret in the portal) before expiry and updating
  the install-application stage.
- Don't paste the secret into logs, tickets, or persistent chat beyond handing it to the next stage.
- **Mode A** creates the app in the operator's own tenant — confirm the tenant (`az account show`)
  before running, and prefer the interactive confirmation prompt over `--yes`.

---

## Layout

```
create-ingext-audit-app-azcli/
├── SKILL.md
├── assets/
│   ├── setup-ingext-audit.sh    ← az CLI script: creates app, grants consent, prints the 3 fields
│   └── permissions.md            ← standalone reference table of the 9 permissions
└── evals/
    └── evals.json                ← trigger phrases for skill selection
```
