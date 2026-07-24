# References — Box vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Box has been renaming this surface
("Custom Apps" → "Platform Apps") and Admin Console layouts vary by tenant generation.

| Claim in SKILL.md | Source |
|---|---|
| App creation: Developer Console → New App → **Server** application type; **Client Credentials Grant is the default authentication method for new Server Authentication apps** | [Setup with Client Credentials Grant — Box Dev Docs](https://developer.box.com/guides/authentication/client-credentials/client-credentials-setup/) |
| App Access Level: default reaches only the app's Service Account / App Users; **App + Enterprise Access** extends to the enterprise's managed users | [Setup with Client Credentials Grant — Box Dev Docs](https://developer.box.com/guides/authentication/client-credentials/client-credentials-setup/) |
| Enterprise accounts: the Configuration tab prompts submission for admin approval; admins/co-admins can authorize directly | [Setup with Client Credentials Grant — Box Dev Docs](https://developer.box.com/guides/authentication/client-credentials/client-credentials-setup/) |
| CCG token parameters: `grant_type=client_credentials`, `client_id`, `client_secret`, `box_subject_type=enterprise`, `box_subject_id=<enterprise ID>`; unauthorized-app error "Your application has not been authorized in the Box Admin Console"; reauthorize after app setting changes | [Client Credentials Grant — Box Dev Docs](https://developer.box.com/guides/authentication/client-credentials/) |
| `GET /events` with `stream_type=admin_logs` "returns all events for an entire enterprise", requires admin privileges, requires the **manage enterprise properties** scope; up to 1 year of history; `admin_logs` is chronological/de-duplicated with higher latency vs `admin_logs_streaming` | [Get events — Box API Reference](https://developer.box.com/reference/get-events/) |
| Scope label **Manage enterprise properties** = technical `manage_enterprise_properties`; allows the app to "view the enterprise event stream" plus enterprise attributes/reports (backs the least-privilege and powerful-scope notes) | [Scopes — Box Dev Docs](https://developer.box.com/guides/api-calls/permissions-and-errors/scopes/) |
| Admin authorization path: Admin Console → **Platform** → **Platform Apps** → Add (paste Client ID); Admin or Co-Admin authorizes; developer submit-for-authorization flow with email notification; **Reauthorize App** required after scope/access-level changes | [Platform App Approval — Box Dev Docs](https://developer.box.com/guides/authorization/platform-app-approval) |
| Older Admin Console variants reach the same manager via Apps → **Platform Apps Manager** / **Custom Apps Manager** (secondary) | [Authorizing Platform Applications — Box Support](https://support.box.com/hc/en-us/articles/360043697014-Authorizing-Platform-Applications-in-Sandbox-and-Production-Environments); [Custom Apps Management for Admins — Box Support](https://support.box.com/hc/en-us/articles/360052807733-Custom-Apps-Management-for-Admins) |
| Client ID lives in the Configuration tab → OAuth 2.0 Credentials section | [Platform App Approval — Box Dev Docs](https://developer.box.com/guides/authorization/platform-app-approval) |
| Fetching the client secret requires **2FA enabled** on the Box account; Enterprise ID appears on the app's **General Settings** tab as the "Box Subject ID" (secondary — official Box SDK docs) | [Box .NET SDK — Authentication docs (box/box-dotnet-sdk-gen, official Box repo)](https://github.com/box/box-dotnet-sdk-gen/blob/main/docs/Authentication.md) |
| Enterprise ID also visible to an admin under Admin Console → Account & Billing (Account Information) (secondary — support/community sourcing) | [Box Support community — finding the enterprise/instance ID](https://support.box.com/hc/en-us/community/posts/30302210143123-How-to-find-BOX-Instance-ID-from-Admin-Console) |

Notes:

- The exact UI control for **rotating** the client secret was not verified at build time; the
  SKILL.md security note therefore says only that credentials are managed in the Configuration
  tab's OAuth 2.0 Credentials section and to update the connector after any change — it does
  not name a specific reset button. Confirm the current control in the Developer Console when
  rotating.
- The "admin privileges" requirement on `admin_logs` is satisfied in this design by the CCG
  enterprise token (service account acting with enterprise subject) plus the
  `manage_enterprise_properties` scope and admin authorization — the same pattern major SIEM
  integrations use for Box enterprise events. The skill deliberately routes all
  admin-privilege questions through app authorization rather than a named admin user.
- Box's enterprise-events guide notes the historical feed emphasizes "completeness over
  latency" — the basis for the honest-latency wording ([Enterprise events — Box Dev
  Docs](https://developer.box.com/guides/events/enterprise-events/for-enterprise/)).
