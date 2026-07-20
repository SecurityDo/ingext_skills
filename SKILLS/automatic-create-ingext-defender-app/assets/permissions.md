# `ingext-defender` — required application permissions

Both permissions are **Application** permissions (app-only, `type = Role` — no signed-in user),
requested on a single Microsoft API — **Microsoft Graph**. Tenant-wide **admin consent** is required
for each one.

The az CLI script (`setup-ingext-defender.sh`) resolves each permission's role ID at runtime from
the resource service principal's `appRoles` (matched by `value`, `allowedMemberTypes` contains
`Application`), so per-permission GUIDs are **not** hardcoded and cannot go stale. Only the Microsoft
Graph resource application ID is a constant.

## Microsoft Graph — resourceAppId `00000003-0000-0000-c000-000000000000`

| Permission (`value`) | Type | Backs | Purpose |
|---|---|---|---|
| `SecurityIncident.Read.All` | Role | `GET /security/incidents` | Read all Microsoft Defender security incidents |
| `SecurityAlert.Read.All` | Role | `GET /security/alerts_v2` | Read all Microsoft Defender security alerts |

## Notes

- Both permissions live on the standard **Microsoft Graph** tab in the Azure portal's permission
  picker — there is no need to open **APIs my organization uses**.
- After adding both, grant tenant-wide admin consent — with the CLI:
  `az ad app permission admin-consent --id <clientId>`. In the portal, each row's Status must show a
  green **“Granted for &lt;tenant&gt;.”**
