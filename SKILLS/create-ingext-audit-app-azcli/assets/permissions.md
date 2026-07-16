# `ingext-audit` — required application permissions

All permissions are **Application** permissions (app-only, `type = Role` — no signed-in user),
requested across two Microsoft APIs. Tenant-wide **admin consent** is required for every one.

The az CLI script (`setup-ingext-audit.sh`) resolves each permission's role ID at runtime from the
resource service principal's `appRoles` (matched by `value`, `allowedMemberTypes` contains
`Application`) — via `az ad sp show ... --query "appRoles[?value=='<name>'...]"` — so per-permission
GUIDs are **not** hardcoded and cannot go stale. Only the two resource application IDs are constants.

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

- The Office 365 Management APIs service principal may not exist in a tenant yet; the script
  creates it (`az ad sp create --id c5393580-...`) before resolving its roles.
- Consent is granted in one call — `az ad app permission admin-consent --id <appId>` — which
  creates the app-role assignments for every added permission.
