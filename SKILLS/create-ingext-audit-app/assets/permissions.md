# `ingext-audit` — required application permissions

All permissions are **Application** permissions (app-only, `type = Role` — no signed-in user),
requested across two Microsoft APIs. Tenant-wide **admin consent** is required for every one.

The PowerShell script (`setup-ingext-audit.ps1`) resolves each permission's role ID at runtime
from the resource service principal's `AppRoles` (matched by `Value`, `AllowedMemberTypes`
contains `Application`), so per-permission GUIDs are **not** hardcoded and cannot go stale. Only
the two resource application IDs are constants.

## Microsoft Graph — resourceAppId `00000003-0000-0000-c000-000000000000`

| Permission (`Value`) | Type | Purpose |
|---|---|---|
| `Directory.Read.All` | Role | Read Azure AD resources — users, groups, devices, applications |
| `AuditLog.Read.All` | Role | Read Azure AD audit logs and sign-in activity |
| `Policy.Read.All` | Role | Read conditional-access and directory policies |
| `Reports.Read.All` | Role | Read usage and security reports |
| `UserAuthenticationMethod.Read.All` | Role | Read users' MFA / authentication-method registration |
| `MailboxSettings.Read` | Role | Read mailbox settings |

## Office 365 Management APIs — resourceAppId `c5393580-f805-4401-95e8-94b7a6ef2fc2`

| Permission (`Value`) | Type | Purpose |
|---|---|---|
| `ActivityFeed.Read` | Role | Read the Office 365 unified audit activity feed |
| `ActivityFeed.ReadDlp` | Role | Read DLP (data loss prevention) events in the activity feed |
| `ServiceHealth.Read` | Role | Read Office 365 service health and incident messages |

## Notes

- In the Azure portal, the Office 365 Management APIs do not appear on the **Microsoft APIs**
  tab — find them under **APIs my organization uses** by searching `Office 365 Management APIs`.
- After adding all nine, click **Grant admin consent for &lt;tenant&gt;**; each row's Status must
  show a green **“Granted for &lt;tenant&gt;.”**
