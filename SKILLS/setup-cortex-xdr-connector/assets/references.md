# References — Cortex XDR vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Palo Alto periodically restructures
docs-cortex.paloaltonetworks.com (several 3.x/4.x guide URLs already redirect to the 5.x
landing page).

| Claim in SKILL.md | Source |
|---|---|
| Key creation path: Settings → Configurations → Integrations → API Keys → + New Key | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| Security levels: Advanced keys are hashed with a nonce and timestamp to prevent replay attacks; Standard keys are used as-is | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| The key is generated with a selected Role (or Custom granular permissions); the key can only do what its role permits | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| **Viewer** is a predefined Cortex XDR user role | [Viewer — Cortex XDR Administrator Guide](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-3.x-Documentation/Viewer) ("Learn more about the Cortex XDR predefined user role called Viewer") |
| The API Key ID is the **ID** column value in the API Keys table (sent as the `x-xdr-auth-id` header) | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| API base URL format `https://api-{fqdn}`, obtainable via right-click → View Examples (curl example embeds it) | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| **Copy API URL** button on the API Keys page; API URL is distinct from the console URL | [Configuring Palo Alto Networks CORTEX XDR Connectors — Stellar Cyber](https://docs.stellarcyber.ai/prod-docs/5.3.x/Configure/Connectors/Palo-Alto-Networks-CORTEX-XDR-Connectors.htm) *(secondary — SIEM-vendor integration guide)* |
| Key value shown once; cannot be viewed again after generation (only regenerated) | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| Optional **Enable Expiration Date**; expiry notifications one week and one day before the deadline | [Get Started with Cortex XDR APIs — Cortex XDR REST API](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR-REST-API/Get-Started-with-Cortex-XDR-APIs) |
| API-polling integrations against Cortex XDR run on ~10-minute poll intervals (basis for the 15–30 min first-event expectation) | [Palo Alto Cortex XDR Source — Sumo Logic](https://www.sumologic.com/help/docs/send-data/hosted-collectors/cloud-to-cloud-integration-framework/palo-alto-cortex-xdr-source/) *(secondary — SIEM-vendor integration guide)* |

Notes:

- The role-permission matrix pages on docs-cortex render client-side and could not be captured
  at build time, so the skill deliberately instructs the admin to **confirm in the tenant
  console** what the chosen role permits, rather than asserting a permission matrix here. The
  Viewer role's existence as a predefined role is documented (row above); its exact permission
  set is tenant-visible in the console.
- The `authMode` ↔ security-level match (`advanced` ↔ Advanced key, `standard` ↔ Standard key)
  is a Fluency-side template semantic (template default `advanced`), not a vendor claim; the
  vendor-side fact backing it is the Standard/Advanced distinction cited above.
- Sumo Logic's guide uses a Standard-level key for its own source; Stellar Cyber notes XSOAR
  requires Advanced — the security level is integration-specific, which is why the skill pins it
  to the connector's `authMode` instead of declaring one universally correct.
