# `ingext-azureaudit` — required application permissions

All permissions are **Application** permissions (app-only, `type = Role` — no signed-in user),
requested across two Microsoft APIs. Tenant-wide **admin consent** is required for every one.

Both bundled scripts (`setup-ingext-azureaudit.sh` for az CLI, `setup-ingext-azureaudit.ps1` for
PowerShell 7) resolve each permission's role ID at runtime from the resource service principal's
`appRoles` (matched by `value`, `allowedMemberTypes` contains `Application`), so per-permission
GUIDs are **not** hardcoded and cannot go stale. Only the two resource application IDs are
constants.

## Microsoft Graph — resourceAppId `00000003-0000-0000-c000-000000000000`

| Permission (`value`) | Type | Purpose |
|---|---|---|
| `Directory.Read.All` | Role | Read Azure AD resources — users, groups, devices, applications |
| `AuditLog.Read.All` | Role | Read Azure AD audit logs and sign-in activity |
| `Policy.Read.All` | Role | Read conditional-access and directory policies |
| `Reports.Read.All` | Role | Read usage and security reports |
| `UserAuthenticationMethod.Read.All` | Role | Read users' MFA / authentication-method registration |
| `MailboxSettings.Read` | Role | Read mailbox settings |

## Office 365 Management APIs — resourceAppId `c5393580-f805-4401-95e8-94b7a6ef2fc2`

| Permission (`value`) | Type | Purpose |
|---|---|---|
| `ActivityFeed.Read` | Role | Read the Office 365 unified audit activity feed |
| `ActivityFeed.ReadDlp` | Role | Read DLP (data loss prevention) events in the activity feed |
| `ServiceHealth.Read` | Role | Read Office 365 service health and incident messages |

## Notes

- The Office 365 Management APIs service principal may not exist in a tenant yet; both scripts
  create it from its well-known appId (`az ad sp create --id c5393580-...` /
  `New-MgServicePrincipal`) before resolving its roles.
- In the Azure portal's permission picker, the Office 365 Management APIs live under the
  **APIs my organization uses** tab, not the standard Microsoft APIs tab.
- After adding all nine, grant tenant-wide admin consent — with the CLI:
  `az ad app permission admin-consent --id <clientId>`. In the portal, each row's Status must show
  a green **“Granted for &lt;tenant&gt;.”**
