---
name: automatic-create-ingext-azureaudit-app
version: 1.0.0
description: >-
  Automatic variant for creating the "ingext-azureaudit" Entra app registration that Fluency /
  Ingext uses to import Office 365 Management audit events, Azure AD / Entra audit events, and
  Azure AD resources (users, groups, devices, applications). Registers a customer-owned, app-only
  (client-credentials) app, adds nine Graph + Office 365 Management APPLICATION permissions,
  grants admin consent, creates a client secret, and returns three fields — tenantId, clientId,
  clientSecret — for the downstream install-application stage. Unlike create-ingext-audit-app
  (which only guides an admin), this variant PERFORMS the setup on the caller's behalf: MODE A —
  the operator is the target tenant's Global Admin, so cowork runs a bundled script directly
  (Azure CLI / az preferred, PowerShell 7 / pwsh as automatic fallback when az is absent) and the
  operator only completes the interactive sign-in when prompted; MODE B — a brief fallback that
  guides a third-party admin who runs it in their own tenant (cowork has no credentials there).
  Prefer this skill when the operator wants cowork to run the setup for them; it combines and
  supersedes create-ingext-audit-app / create-ingext-audit-app-azcli. Triggers: "create the
  ingext-azureaudit app for me", "I'm the Global Admin, run the audit-log app setup",
  "automatically register the Entra app for Office 365 / Azure AD audit import". Do NOT use for
  the hosted OAuth consent flow (multi-tenant app + adminConsentEmail) — that's add-connector; nor
  the Defender exporter — that's automatic-create-ingext-defender-app.
---

# Create the `ingext-azureaudit` Entra Application — automatically (az CLI, pwsh fallback)

Register **`ingext-azureaudit`**, a customer-owned application that Fluency / Ingext authenticates
as (app-only / client-credentials) to import:

- **Office 365 Management** audit events — the unified activity feed and DLP events
- **Azure AD / Entra** audit events
- **Azure AD resources** — users, groups, devices, applications, and other directory objects

This skill's job **ends when it has produced three values** — `tenantId`, `clientId`,
`clientSecret` — which the next onboarding stage ("install application") consumes. It does not
start Office 365 subscriptions or configure the Fluency connector; those happen later.

This is the **automatic variant** of `create-ingext-audit-app` (which only *guides* the admin) and
combines it with `create-ingext-audit-app-azcli`. Same nine permissions, same three-field output —
but, crucially, **cowork runs it for the operator** instead of handing them instructions. Two
interchangeable scripts are bundled: Azure CLI (`az` + Bash, preferred) and PowerShell 7 (`pwsh` +
Microsoft.Graph, the automatic fallback when `az` isn't installed). Both produce the same three
fields.

## What this creates

| Item | Detail |
|---|---|
| App registration | Display name `ingext-azureaudit`, single-tenant (`AzureADMyOrg`) |
| API permissions | 9 **Application** (app-only, type `Role`) permissions across 2 APIs (see below) |
| Admin consent | Tenant-wide consent granted for all 9 permissions |
| Client secret | One secret, 2-year expiry — its value is the `clientSecret` field |

> **Relation to the older skills:** the guide-only `create-ingext-audit-app` and
> `create-ingext-audit-app-azcli` register an app named **`ingext-audit`**. This skill uses the
> name **`ingext-azureaudit`**, so a tenant that already ran an older skill will end up with both
> apps — harmless (each has its own secret and consent), but retire the unused one when the
> connector has been switched over.

## Permissions granted

All are **Application** permissions (`type = Role`, app-only — no signed-in user) across two
Microsoft APIs. The script resolves each one's role ID at runtime from the resource service
principal, so no GUIDs are hardcoded. A standalone copy of this table lives in
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

## Prerequisites

- **One of two toolchains** on this machine — check in this order, and take the first hit:
  1. **Azure CLI** (`az version` succeeds) → use `assets/setup-ingext-azureaudit.sh` (preferred).
  2. **PowerShell 7+** (`pwsh --version` succeeds) → use `assets/setup-ingext-azureaudit.ps1`. It
     auto-installs the two Microsoft.Graph submodules it needs on first run — no other setup.
  If **neither** is present, install Azure CLI
  (https://learn.microsoft.com/cli/azure/install-azure-cli) if feasible on this machine;
  otherwise fall back to Mode B.
- An identity that can **both** create app registrations **and grant tenant-wide admin consent** —
  **Global Administrator**, or **Privileged Role Administrator** combined with **Application
  Administrator** / **Cloud Application Administrator**. Without consent rights the app is created
  but the permissions stay unconsented and Ingext cannot read data.

---

## Pick a mode

**Ask who is at the keyboard** (use `AskUserQuestion` if it isn't already clear):

- **Mode A — "I am the tenant's Global Admin and want cowork to run it."** cowork executes a
  bundled script on this machine (`az` if installed, `pwsh` otherwise), against the tenant the
  operator signs in to. This is the primary path — the setup is performed on the operator's behalf.
- **Mode B — "I'm onboarding a different tenant / another admin will run it."** cowork does **not**
  run anything against that tenant (it has no credentials there). Hand the admin the script or the
  portal walkthrough and collect the three fields they report back.

> **Why the distinction matters:** app registration + admin consent require an interactive sign-in
> to the *target* tenant. In Mode A that tenant is the operator's own and the sign-in happens on
> this machine, so cowork can drive it. In Mode B the tenant belongs to someone else — cowork
> cannot authenticate there, so its role is to guide.

---

## Mode A — cowork runs the setup script (primary)

Precondition: the operator is a Global Admin (or equivalent) of the target tenant, and this machine
can complete an Azure sign-in.

**Run the script for the operator — don't hand them instructions.** The only thing they must do
themselves is complete the interactive sign-in when it appears. Tell them that up front ("a sign-in
prompt is about to appear — please authenticate as the tenant's Global Admin"), then start.
**Assume they will authenticate**; don't stop to ask permission to run the script. cowork's normal
per-command approval already governs what runs, and both scripts are idempotent — safe to re-run.

### A1 — Pick the tooling

1. `az version` succeeds → **az path** (A2).
2. `az` missing but `pwsh --version` shows 7+ → **pwsh path** (A3).
3. Neither → install Azure CLI if feasible on this machine, else fall back to Mode B or another
   machine.

### A2 — az path

1. **Confirm the target tenant.** Run `az account show`. If it errors (not logged in), run the
   sign-in — the operator completes the browser/device step:

   ```bash
   az login                    # opens a browser
   # or, headless / no browser on this machine:
   az login --use-device-code  # prints a code; relay it and the operator finishes sign-in in a browser
   ```

   Then re-run `az account show` and **read back the tenantId + account** so the operator confirms
   it is the intended tenant before anything is created.

2. **Run the bundled script:**

   ```bash
   bash ${SKILL_DIR}/assets/setup-ingext-azureaudit.sh
   # optional overrides:
   bash ${SKILL_DIR}/assets/setup-ingext-azureaudit.sh --app-name ingext-azureaudit --secret-years 2
   ```

   The script **stops for a confirmation prompt** ("Create/update app … in the tenant above?")
   unless run with `--yes`. Surface that prompt to the operator; only pass `--yes` if the operator
   has explicitly approved the target tenant.

What the sh script does, in order: preflight (`az` present + logged in) → read `tenantId` → confirm
target tenant → ensure the Microsoft Graph and Office 365 Management API service principals exist
(creating the O365 one if missing) → resolve each permission name to its app-role ID →
create/reuse the `ingext-azureaudit` app → add the `requiredResourceAccess` → ensure the app's
service principal exists → `az ad app permission admin-consent` (with retry for replication lag) →
append a client secret → print the three fields.

### A3 — pwsh path (az not installed)

The PowerShell script signs in via `Connect-MgGraph`, which drives its own authentication — there
is no prior `az login` equivalent. Just start the script and let the prompt appear. Pick the auth
flow from the machine's session:

- **Graphical session on this box** (`DISPLAY` / `WAYLAND_DISPLAY` set and a browser installed):

  ```bash
  pwsh ${SKILL_DIR}/assets/setup-ingext-azureaudit.ps1
  ```

  A browser window opens on the operator's desktop for sign-in.

- **Headless** (no display):

  ```bash
  pwsh ${SKILL_DIR}/assets/setup-ingext-azureaudit.ps1 -UseDeviceCode
  ```

  Relay the printed URL + code; the operator finishes sign-in in any browser.

Run it as a **background task and watch the output** — the first run installs two Microsoft.Graph
submodules (`Authentication`, `Applications`, ~a minute) and the operator's sign-in takes as long
as it takes. The operator consents to the script's own scopes (`Application.ReadWrite.All`,
`AppRoleAssignment.ReadWrite.All`, `Directory.Read.All`).

The ps1 script has **no tenant-confirmation prompt** — it proceeds as soon as sign-in completes,
against whichever tenant the operator signed in to. It prints
`Connected to tenant <tenantId> as <account>` first; read that line back to the operator in your
report so a wrong-tenant run is caught immediately (re-run after signing in to the right tenant —
idempotency makes the stray app harmless, but tell the operator to delete it).

What the ps1 script does, in order: ensure/import Graph modules → `Connect-MgGraph` → read
`tenantId` from `Get-MgContext` → get the Microsoft Graph and Office 365 Management API service
principals (creating the O365 one if the tenant lacks it) → resolve each permission name to its
app-role ID → create/reuse the `ingext-azureaudit` app → ensure its service principal exists → add
a 24-month client secret → grant admin consent via app-role assignments → print the three fields.

### A4 — Capture the output

Both scripts end by printing the JSON object (the sh script writes **only** JSON to stdout with
progress on stderr; the ps1 script prints it after a banner):

```json
{ "tenantId": "…", "clientId": "…", "clientSecret": "…" }
```

Hand those three fields to the **install-application** stage. Treat `clientSecret` as a
credential — do not echo it into logs or long-lived chat beyond passing it along.

---

## Mode B — guide a third-party admin (fallback)

cowork cannot reach the customer's tenant. Offer the admin either path; the deliverable is the same
three fields.

### Path B1 — az CLI script (recommended for Linux/macOS admins)

Give the admin the script at `${SKILL_DIR}/assets/setup-ingext-azureaudit.sh` (or paste its
contents to save and run). Tell them to:

1. Install Azure CLI if needed, then `az login` (or `az login --use-device-code`) **to their
   tenant** as a Global Admin.
2. Run `bash setup-ingext-azureaudit.sh` and answer the confirmation prompt.
3. Copy the printed JSON (`tenantId`, `clientId`, `clientSecret`) back to you — the secret is shown
   once.

For an admin who prefers PowerShell (e.g. on Windows), hand them
`${SKILL_DIR}/assets/setup-ingext-azureaudit.ps1` instead — PowerShell 7+, same three-field JSON
output, and it installs its own Microsoft.Graph modules on first run.

### Path B2 — manual Azure portal walkthrough

Direct the admin through **[https://entra.microsoft.com](https://entra.microsoft.com)** (or the
Azure portal → **Microsoft Entra ID**):

1. **App registrations → New registration.** Name it **`ingext-azureaudit`**. Supported account
   types: **Accounts in this organizational directory only (single tenant)**. Leave Redirect URI
   blank. **Register**.
2. On **Overview**, copy **Directory (tenant) ID** → `tenantId`, and **Application (client) ID** →
   `clientId`.
3. **API permissions → Add a permission → Microsoft Graph → Application permissions.** Search for
   and check each of these six, then **Add permissions**:
   - `Directory.Read.All`, `AuditLog.Read.All`, `Policy.Read.All`, `Reports.Read.All`,
     `UserAuthenticationMethod.Read.All`, `MailboxSettings.Read`
4. **Add a permission →** open the **APIs my organization uses** tab and search
   **`Office 365 Management APIs`** → **Application permissions.** Check these three, then
   **Add permissions**:
   - `ActivityFeed.Read`, `ActivityFeed.ReadDlp`, `ServiceHealth.Read`
5. **Grant admin consent for &lt;tenant&gt;** and confirm. Every row's **Status** must turn green
   **“Granted for &lt;tenant&gt;.”** (If the button is greyed out, the signed-in admin lacks consent
   rights — see Failure modes.)
6. **Certificates & secrets → Client secrets → New client secret.** Description
   `ingext-azureaudit`, expiry 24 months, **Add**. **Copy the secret Value immediately** — shown
   once — this is `clientSecret`. (Copy the **Value**, not the Secret ID.)

---

## Output — the three fields

Present the result both human-readably and as a JSON block so a calling onboarding task can parse it
deterministically. **The client secret is shown once** — make sure it was captured.

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

- **Consent granted:** all nine permissions show as granted for the tenant. From the CLI, check the
  app's service principal app-role assignments:
  `az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals(appId='<clientId>')/appRoleAssignments"`
  (9 assignments expected).
- **Fields captured:** `tenantId` and `clientId` are GUIDs; `clientSecret` is a non-empty value
  (not the Secret ID).
- In Mode B you cannot verify inside the customer's tenant — rely on the admin's confirmation or the
  script's printed output.

---

## Failure modes

| Situation | Response |
|---|---|
| `az account show` fails / "Please run 'az login'" | Not signed in. Run `az login` (or `az login --use-device-code`), confirm the tenant, then re-run the script. |
| `az` is not installed | Fall back to the bundled PowerShell script (Mode A3) if `pwsh` 7+ is present. Otherwise install Azure CLI (https://learn.microsoft.com/cli/azure/install-azure-cli) or fall back to Mode B. |
| `pwsh` present but PowerShell < 7 | The ps1 script throws on startup. Install PowerShell 7 (`pwsh`), or use the az path / Mode B. |
| ps1 module install fails (locked-down PSGallery) | Stage `Microsoft.Graph.Authentication` + `Microsoft.Graph.Applications` manually, then re-run with `-SkipModuleInstall`. |
| ps1 run connected to the wrong tenant | The ps1 has no confirmation prompt — it acts on whatever tenant the sign-in selected. Re-run and sign in to the intended tenant; have the operator delete the stray `ingext-azureaudit` app from the wrong tenant. |
| **admin-consent** step warns it didn't complete | The signed-in identity lacks consent rights. A Global Admin (or Privileged Role Admin + Application/Cloud App Admin) runs `az ad app permission admin-consent --id <clientId>`. The app + permissions already exist; only consent is missing. |
| Wrong tenant selected | `az account show` shows the tenant before anything is created; the script also prompts for confirmation. Switch with `az login --tenant <id>` (or `az account set --subscription <id>`), then re-run. |
| **Office 365 Management APIs** SP missing | Expected in some tenants — both scripts create it from its well-known appId (`c5393580-...`). In the portal, find the API under **APIs my organization uses**. |
| Client secret value not captured | It is shown once. Re-run the script (it appends a fresh secret) or add a new one in **Certificates & secrets**. |
| App named `ingext-azureaudit` already exists | Expected on re-runs — the script reuses it (re-applies permissions, appends a fresh secret). In the portal, reuse the existing registration. |
| Tenant already has an `ingext-audit` app | Created by the older guide-only skills. This skill's `ingext-azureaudit` is a separate app — both can coexist; retire the unused one once the connector is switched over. |
| `permission not found on resource` | A permission name is misspelled or the resource API isn't available in the tenant — verify against the Permissions table. |

---

## Security notes

- Every permission is **read-only** (`*.Read` / `*.Read.All`) — least privilege for an audit
  importer.
- The client secret is a credential shown once and never retrievable again. It expires in **2 years**
  — rotate by re-running the script (or adding a new secret in the portal) before expiry and updating
  the install-application stage.
- Don't paste the secret into logs, tickets, or persistent chat beyond handing it to the next stage.
- **Mode A** creates the app in the operator's own tenant — confirm the tenant before anything is
  created. On the az path, read back `az account show` and prefer the interactive confirmation
  prompt over `--yes`. On the pwsh path there is no pre-creation prompt — read back the script's
  `Connected to tenant …` line in your report so a wrong-tenant run is caught immediately.

---

## Layout

```
automatic-create-ingext-azureaudit-app/
├── SKILL.md
├── assets/
│   ├── setup-ingext-azureaudit.sh    ← az CLI script: creates app, grants consent, prints the 3 fields
│   ├── setup-ingext-azureaudit.ps1   ← PowerShell 7 fallback (Microsoft.Graph): same job, same output
│   └── permissions.md                ← standalone reference table of the 9 permissions
└── evals/
    └── evals.json                    ← trigger phrases for skill selection
```
