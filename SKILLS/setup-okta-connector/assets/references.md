# References — Okta vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Okta occasionally reshuffles help-center
paths.

| Claim in SKILL.md | Source |
|---|---|
| Token creation path: Admin Console → Security → API → Tokens → Create token | [Create an API token — Okta Developer](https://developer.okta.com/docs/guides/create-an-api-token/main/) |
| Tokens expire after 30 days of non-use; the timer resets on each API call; period is fixed per org | [Manage Okta API tokens — Okta Help Center](https://help.okta.com/en-us/content/topics/security/api.htm); [Okta API Token Expiration And Deactivation Guidelines — Okta Support](https://support.okta.com/help/s/article/How-an-API-Token-is-expired-and-get-deactivated) |
| A token inherits the permissions of the admin who creates it; deactivating the owner invalidates it | [Create an API token — Okta Developer](https://developer.okta.com/docs/guides/create-an-api-token/main/) |
| Read-Only Administrator is a view-only standard admin role (recommended token owner) | [Read-only administrators — Okta Help Center](https://help.okta.com/en-us/content/topics/security/administrators-read-only-admin.htm); [Standard administrator roles and permissions — Okta Help Center](https://help.okta.com/en-us/content/topics/security/administrators-admin-comparison.htm) |
| Org domain ≠ the `-admin` console domain; how to find the Okta domain | [Find your Okta domain — Okta Developer](https://developer.okta.com/docs/guides/find-your-domain/) |

Notes:

- The "token owner must be able to view the System Log" framing is deliberate — Okta API tokens
  have no scopes of their own, so the skill instructs confirming the owner can open
  Reports → System Log rather than asserting a specific permission string.
- System Log API rate limits are per-org and vary by plan; the failure-modes row references them
  qualitatively on purpose.
