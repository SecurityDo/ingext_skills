# `ingext-defender` — required application permissions

Both permissions are **Application** permissions (app-only, `type = Role` — no signed-in user),
requested on a single Microsoft API — **Microsoft Graph**. Tenant-wide **admin consent** is required
for each one.

The PowerShell script (`setup-ingext-defender.ps1`) resolves each permission's role ID at runtime
from the resource service principal's `AppRoles` (matched by `Value`, `AllowedMemberTypes`
contains `Application`), so per-permission GUIDs are **not** hardcoded and cannot go stale. Only the
Microsoft Graph resource application ID is a constant.

## Microsoft Graph — resourceAppId `00000003-0000-0000-c000-000000000000`

| Permission (`Value`) | Type | Backs | Purpose |
|---|---|---|---|
| `SecurityIncident.Read.All` | Role | `GET /security/incidents` | Read all Microsoft Defender security incidents |
| `SecurityAlert.Read.All` | Role | `GET /security/alerts_v2` | Read all Microsoft Defender security alerts |

## Notes

- Both permissions live on the standard **Microsoft Graph** tab in the Azure portal's permission
  picker — there is no need to open **APIs my organization uses**.
- After adding both, click **Grant admin consent for &lt;tenant&gt;**; each row's Status must show a
  green **“Granted for &lt;tenant&gt;.”**
