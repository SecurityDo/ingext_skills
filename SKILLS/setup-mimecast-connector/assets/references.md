# References — Mimecast vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Mimecast is mid-migration from the "API
and Platform Integrations" page to the Integrations Hub, so menu paths are expected to shift.

**Fetch caveat:** Mimecast's own support articles (mimecastsupport.zendesk.com, mirrored from
community.mimecast.com) block automated fetching (HTTP 403). The claims below attributed to
those articles were verified from their indexed excerpts via web search at build time; the
Rapid7 guide (a SIEM vendor's integration guide, **secondary source** per the research protocol)
was fetched in full and corroborates the console path and adds the role/product details.

| Claim in SKILL.md | Source |
|---|---|
| API 2.0 application creation path: Administration Console → Integrations → API and Platform Integrations; newer consoles: Integrations → Integrations Hub → API 2.0 tile → View; new applications move to the Hub | [API & Integrations - Managing API 2.0 for Cloud Gateway — Mimecast](https://mimecastsupport.zendesk.com/hc/en-us/articles/34000360548755-API-Integrations-Managing-API-2-0-for-Cloud-Gateway); [API clients — Mimecast](https://mimecastsupport.zendesk.com/hc/en-us/articles/42665971063059-API-clients); corroborated by [Mimecast API 2.0 — Rapid7 InsightIDR docs](https://docs.rapid7.com/insightidr/mimecast-2.0/) (secondary) |
| Client ID + Client Secret are shown in a (masked) popup at creation; copy to a secure location — the secret is not shown again | [API & Integrations - Managing API 2.0 for Cloud Gateway — Mimecast](https://mimecastsupport.zendesk.com/hc/en-us/articles/34000360548755-API-Integrations-Managing-API-2-0-for-Cloud-Gateway) |
| Since Sep 2023 the client secret cannot be retrieved after creation; rotation is application → Reset Keys → Regenerate (issues fresh pair, invalidates old) | [API & Integrations - Manage API 2.0 Credentials - Sep 2023 — Mimecast](https://community.mimecast.com/s/article/api-integrations-managing-api-applications-client-secret-regeneration-service-update) |
| API 2.0 auth is OAuth 2.0 (client credentials); GA June 2023 | [Email Security Cloud Gateway - Mimecast API 2.0 - Jun 2023 — Mimecast](https://community.mimecast.com/s/article/email-security-cloud-gateway-mimecast-api-2-0-service-update) |
| API 1.0 is at end of life (steer new setups to 2.0) | [API & Integrations - API 1.0 End of Life - Mar 2025 — Mimecast](https://mimecastsupport.zendesk.com/hc/en-us/articles/39704312201235-API-Integrations-API-1-0-End-of-Life-Mar-2025) |
| Product selection for CG SIEM ingestion: "Threats, Security Events and Data for CG"; a Basic Administrator role suffices to create the application; a freshly created application may take several minutes to become usable | [Mimecast API 2.0 — Rapid7 InsightIDR docs](https://docs.rapid7.com/insightidr/mimecast-2.0/) (**secondary** — SIEM vendor integration guide) |
| No regional base URL is collected for CG / API 2.0 (template takes only clientId/clientSecret + datalake defaults) | Live `list_connector_templates` schema for `MimecastCG`, fetched 2026-07-24 (platform-side fact, not a vendor claim); contrast with the legacy `Mimecast` template's five parameters |

Notes:

- The wizard's product-selection label is quoted from Rapid7 (secondary) and flagged in SKILL.md
  as possibly varying by account — the skill deliberately instructs "the product set covering
  Cloud Gateway threat / SIEM events" rather than asserting the label as universal.
- No claim is made about client-secret *expiry* — no verifiable source documented a fixed
  lifetime; the rotation story (Reset Keys) is what the skill teaches.
- Mimecast's developer portal (developer.services.mimecast.com) is a JS single-page app that
  returns no content to automated fetch; it is the canonical API 2.0 reference for humans and
  worth citing directly once fetchable.
