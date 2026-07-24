# References — SentinelOne vendor-side steps

Verified 2026-07-24. **SentinelOne's own product documentation is login-gated**, so per the
research protocol every source below is a **secondary source** — a major SIEM vendor's (or
established integrator's) published guide for the same product. Re-check at next skill
revision; S1 console menus shift between versions.

| Claim in SKILL.md | Source (secondary) |
|---|---|
| Console-user token path: top-right account → My User → Actions → API Token Operators/Operations → Generate API Token; MFA prompt; value shown once | [SentinelOne Integration — Elastic](https://www.elastic.co/docs/reference/integrations/sentinel_one) |
| Permission map for reading via the API: Activity → view, Endpoints → view, Threats → view (plus per-stream others) | [SentinelOne Integration — Elastic](https://www.elastic.co/docs/reference/integrations/sentinel_one) |
| Console-user tokens are time-limited, default expiry 30 days; service-user tokens last the duration chosen at generation | [SentinelOne Integration — Elastic](https://www.elastic.co/docs/reference/integrations/sentinel_one) |
| Six-month token expiry (older/other consoles) — kept as the conflicting data point | [SentinelOne — runZero docs](https://help.runzero.com/docs/sentinelone/); [Understanding SentinelOne API Tokens — NinjaOne](https://www.ninjaone.com/docs/integrations/antivirus/sentinelone/understanding-sentinelone-api-tokens/) |
| API-user creation via Settings → Users → New User with the Admin role (Microsoft's quick-start shortcut); console URL format `https://<SOneInstanceDomain>.sentinelone.net` | [SentinelOne data connector definition — Azure-Sentinel GitHub (Microsoft Sentinel solution)](https://github.com/Azure/Azure-Sentinel/blob/master/Solutions/SentinelOne/Data%20Connectors/SentinelOne_API_FunctionApp.json) |
| Service-user path: Settings → Users → Service Users → Actions → Create New Service User, then generate/copy the token | [SentinelOne Mgmt API Source — Sumo Logic docs](https://www.sumologic.com/help/docs/send-data/hosted-collectors/cloud-to-cloud-integration-framework/sentinelone-mgmt-api-source/) |
| Console base URL is the tenant sign-in URL, `<organization>.sentinelone.net`; tokens can be generated, regenerated, or revoked | [SentinelOne — runZero docs](https://help.runzero.com/docs/sentinelone/) |

Explicitly UNVERIFIED (stubbed in SKILL.md, per the do-not-guess rule):

- **The exact name of the least-privilege built-in role** in a given console. None of the
  public secondary sources commits to one (Microsoft's guide simply assigns **Admin**; Elastic
  lists granular permissions instead). The skill instructs the admin to find a view-only role
  in Settings → Users → Roles or obtain the current recommendation from SentinelOne
  documentation/support — it never asserts a role name.

Notes on conflicts:

- **Token expiry** genuinely conflicts across sources (30-day console-user default per Elastic
  vs six months per runZero/NinjaOne). The skill resolves this honestly: the expiry date the
  console displays at generation is the truth; record it and calendar the rotation.
- Menu label "API Token Operations" vs "API Token Operators" varies across sources/console
  versions; the skill carries both spellings.
