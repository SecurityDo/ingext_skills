# References — Bitwarden vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Bitwarden help paths are stable but the
Admin Console UI evolves.

| Claim in SKILL.md | Source |
|---|---|
| Organization API key location: Admin Console → Settings → Organization info → API key section, obtained by an **owner** | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| Organization API key `client_id` format is `organization.ClientId` | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| OAuth token endpoints: US cloud `https://identity.bitwarden.com/connect/token`, EU cloud `https://identity.bitwarden.eu/connect/token`, self-hosted `https://your.domain.com/identity/connect/token` (backs the `region` US/EU mapping and the self-hosted caveat) | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| OAuth scope is `api.organization` | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| Public API access is available to all **Enterprise and Teams** organizations | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| Rotate API key: Settings → Organization info → Rotate API key; documented as the response to a compromised key | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| Sharing the key with a non-owner should use a secure method such as Bitwarden Send | [Bitwarden Public API — Bitwarden Help](https://bitwarden.com/help/public-api/) |
| Event logs are for **Teams or Enterprise** organizations; viewable in Admin Console → Reporting → Event logs; also served as JSON via the Public API events endpoint; SIEM export integrations exist | [Event Logs — Bitwarden Help](https://bitwarden.com/help/event-logs/) |
| "Server events are recorded instantly, client events, the majority, are transmitted to the server every 60 seconds" (backs the latency note) | [Event Logs — Bitwarden Help](https://bitwarden.com/help/event-logs/) |

Notes:

- The template's `region` parameter is Fluency-side: the snapshot showed a plain string with
  default `US` and no enums. The `US`/`EU` values map to the two documented Bitwarden clouds;
  the skill instructs re-checking the **live** template for enums at install time rather than
  trusting the snapshot.
- The self-hosted caveat is honest by construction: Bitwarden documents a distinct self-hosted
  identity endpoint, and the template exposes no host parameter — so the skill tells the
  operator to confirm self-hosted support with Fluency instead of improvising.
- The event-logs help page does not state which org roles can view event logs in the Admin
  Console, so the skill makes no claim about that.
