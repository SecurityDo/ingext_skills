# References — Sophos vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Sophos occasionally restructures its help
paths (docs.sophos.com vs doc.sophos.com mirrors).

| Claim in SKILL.md | Source |
|---|---|
| Credential creation path: Sophos Central Admin → Global Settings → Access Control → API Credentials ("API Credentials Management") → Add Credential | [API Credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/GlobalSettings/AccessControl/APICredentials/index.html) |
| Role list offered in the dialog: Service Principal Super Admin / Management / Forensics / Read-Only / Active Directory Sync / Firewall; Read-Only "can view all information … but can't add, modify, or remove information" | [API Credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/GlobalSettings/AccessControl/APICredentials/index.html) |
| Only Super Admins can manage and add API credentials | [API Credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/GlobalSettings/AccessControl/APICredentials/index.html) |
| The Client Secret is shown only once | [API Credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/GlobalSettings/AccessControl/APICredentials/index.html); [Create API credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/FirewallManagement/AWSAutoscaling/ConfigureAWS/CreateAPICredentials/index.html) |
| No alert on credential expiry; an expired credential stops authenticating and is automatically removed from Sophos Central | [API Credentials — Sophos Central Admin](https://docs.sophos.com/central/customer/help/en-us/ManageYourProducts/GlobalSettings/AccessControl/APICredentials/index.html) |
| Tenant vs partner/organization scope: the Partner and Enterprise consoles have their own, separately scoped API-credential pages — a tenant credential comes from the customer's Admin console | [API Credentials Management — Sophos Central Partner](https://docs.sophos.com/central/partner/help/en-us/Help/Configure/SettingsAndPolicies/APICredentials/index.html); [API Credentials — Sophos Central Enterprise](https://docs.sophos.com/central/enterprise/help/en-us/GlobalSettings/AccessControl/APICredentials/); [Getting Started as a Tenant — Sophos Central APIs](https://developer.sophos.com/getting-started-tenant) |
| Auth flow context: client-credentials grant at `https://id.sophos.com/api/v2/oauth2/token`, access token `expires_in` 3600 s (1 hour); `whoami/v1` returns tenant ID and data-region API hosts | [Getting Started as a Tenant — Sophos Central APIs](https://developer.sophos.com/getting-started-tenant); [Authenticating to Sophos Central APIs — Sophos Community (Recommended Reads)](https://community.sophos.com/sophos-central-api/f/recommended-reads/120745/authenticating-to-sophos-central-apis) |

Notes:

- developer.sophos.com is a JavaScript-rendered portal; its pages did not render for automated
  fetch at build time, but their contents (token endpoint, 3600 s lifetime, whoami flow) were
  verifiable through search-indexed copies and the official Sophos Community "Recommended Reads"
  article, so the claims above are kept and cited to both.
- The public docs do **not** publish a fixed credential lifetime — the SKILL.md deliberately
  says "check whether the credential still appears in the list" instead of asserting a number.
- The skill does not claim which specific Sophos Central menu shows EDR events for cross-check;
  that varies by product mix, so Verification says "the customer's own Sophos Central console"
  without inventing a menu path.
