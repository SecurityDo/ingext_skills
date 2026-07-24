# References — Proofpoint TAP vendor-side steps

Verified 2026-07-24. Re-check at next skill revision.

Proofpoint's SIEM API reference on help.proofpoint.com is public and was fetched in full
(primary source). The exact TAP Dashboard menu path for credential creation is not spelled out
on that page ("generated on the settings page" is as specific as it gets), so SIEM vendor
integration guides — **secondary sources** per the research protocol — back the click path.

| Claim in SKILL.md | Source |
|---|---|
| SIEM API host `tap-api-v2.proofpoint.com`; SSL required; HTTP Basic auth with service principal as username and secret as password | [SIEM API — Proofpoint help](https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API) (primary, fetched) |
| Rate limits: 1800 requests per 24 hours per throttle pool (clicks/permitted in one pool; other SIEM endpoints in the other) | [SIEM API — Proofpoint help](https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API) (primary) |
| Retention: at most the last 7 days queryable, maximum fetch window 1 hour | [SIEM API — Proofpoint help](https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API) (primary) |
| Credentials are generated on the TAP Dashboard settings page | [SIEM API — Proofpoint help](https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API) (primary) |
| Exact path: TAP Dashboard (`threatinsight.proofpoint.com`) → Settings → Connected Applications → Create New Credential → name → Generate → "Generated Service Credential" dialog with Service Principal + Secret | [Proofpoint TAP — Rapid7 InsightIDR docs](https://docs.rapid7.com/insightidr/proofpoint-tap/) (**secondary**, fetched); [Proofpoint TAP — Elastic integrations](https://www.elastic.co/docs/reference/integrations/proofpoint_tap) (**secondary**, fetched) |
| Values must be copied immediately — not available after the dialog closes; credential should show Active status afterwards | [Configuring Proofpoint TAP Connectors — Stellar Cyber docs](https://docs.stellarcyber.ai/prod-docs/5.1.x/Configure/Connectors/Proofpoint-TAP-Connectors.htm) (**secondary**) |
| An administrative TAP Dashboard user with privileges to create service credentials is required (no finer public role name) | [Proofpoint TAP Source — Sumo Logic docs](https://www.sumologic.com/help/docs/send-data/hosted-collectors/cloud-to-cloud-integration-framework/proofpoint-tap-source/) (**secondary**, fetched); [Configure Proofpoint TAP — Arctic Wolf docs](https://docs.arcticwolf.com/en/active-response-log-forwarding-and-security-monitoring/cloud-detection-and-response-integrations/configure-proofpoint-targeted-attack-protection-tap) (**secondary**) |
| The `ProofpointTAP` template takes only `principal` and `secret`, and exposes no datalake/index parameter (hence "confirm live" for the table name) | Live `list_connector_templates` schema for `ProofpointTAP`, fetched 2026-07-24 (platform-side fact, not a vendor claim) |

Notes:

- The "admin role needed" claim is deliberately phrased as "an administrative user with rights
  to create service credentials" — Proofpoint's public docs name no specific TAP role for this,
  and inventing one would violate the do-not-guess rule.
- No licensing claim beyond "TAP itself is the licensed product" — the primary SIEM API page
  states no additional license requirement for the API.
