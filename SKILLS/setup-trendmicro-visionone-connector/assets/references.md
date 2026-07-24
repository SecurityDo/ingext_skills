# References — Trend Vision One vendor-side steps

Verified 2026-07-24 against Trend Micro's public Automation Center (automation.trendmicro.com)
and its docs.trendmicro.com mirrors. Re-check at next skill revision; Trend rebrands pages
("TrendAI Vision One") and moves help-center paths.

| Claim in SKILL.md | Source |
|---|---|
| API key creation path: console → Administration → API Keys → Add API Key; fields Name / Role / Expiration time / Status / Details | [First steps toward using the APIs — Trend Vision One Automation Center](https://automation.trendmicro.com/xdr/Guides/First-steps-toward-using-the-APIs/) |
| The token is shown once — "you cannot see the authentication token again after you click Close" | [First steps toward using the APIs — Trend Vision One Automation Center](https://automation.trendmicro.com/xdr/Guides/First-steps-toward-using-the-APIs/) |
| Authentication tokens expire one year after creation by default; a Master Administrator can delete and regenerate tokens at any time | [First steps toward using the APIs — Trend Vision One Automation Center](https://automation.trendmicro.com/xdr/Guides/First-steps-toward-using-the-APIs/) |
| API keys use predefined or custom user roles; built-in roles are Master Administrator, Operator, Senior Analyst, Analyst, Auditor (Auditor = read-only access to specific apps); custom roles via Administration → User Roles | [First steps toward using the APIs — Trend Vision One Automation Center](https://automation.trendmicro.com/xdr/Guides/First-steps-toward-using-the-APIs/); [API Keys — Trend Vision One help](https://www.docs.trendmicro.com/en-us/enterprise/trend-vision-one/administrative-setti/accountspartlegacy/user-accounts/api-keys.aspx) |
| Regional API domains: US `api.xdr.trendmicro.com`; US-Gov `api.usgov.xdr.trendmicro.com`; Germany `api.eu.xdr.trendmicro.com`; UK `api.uk.xdr.trendmicro.com`; Japan `api.xdr.trendmicro.co.jp`; Singapore `api.sg.xdr.trendmicro.com`; Australia `api.au.xdr.trendmicro.com`; India `api.in.xdr.trendmicro.com`; UAE `api.mea.xdr.trendmicro.com`; "you must specify the correct domain name for your region in the request URI" | [Regional domains — Trend Vision One Automation Center](https://automation.trendmicro.com/xdr/Guides/Regional-domains/) |

Explicitly UNVERIFIED (stubbed in SKILL.md, per the do-not-guess rule):

- **Whether the built-in Auditor role covers every endpoint the Fluency connector polls.** Trend
  documents that the key's permissions come from its role, and that Auditor is the read-only
  built-in, but the Fluency connector's exact endpoint/permission list is not published — the
  skill starts at Auditor and instructs escalation (custom role via Administration → User Roles,
  or Trend / Fluency support) only if the connector reports permission errors. It never asserts
  a specific permission string.

Notes:

- The regional-domain table is copied verbatim from the primary source, with `https://`
  prefixed to match the connector's `baseURL` parameter ("API Endpoint URL (Regional
  domains)").
- The skill deliberately avoids naming a console menu that proves the tenant's region; Trend's
  public docs don't pin one, so it says "confirm in the console or with Trend support".
