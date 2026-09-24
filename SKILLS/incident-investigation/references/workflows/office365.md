# Office365 workflow (incident-investigation, step 3)

Run this when the ticket is an **Office365 / Entra ID** incident — its `behaviorRules`
start with `O365_`, `AzureAD_` or `Fluency_O365_` (see the routing table in SKILL.md
step 3). It is three checks, usually run in this order; each one's result goes into the
step-5 closure with the index it came from.

> **Guidance, not a script.** These are the checks that settled past tickets of this type
> and a sensible order to run them in. Add, reorder or skip any of them when the evidence
> points elsewhere, and say in the closure what you skipped and why. The non-negotiables
> in SKILL.md still apply.

Every query below lives in `assets/queries/` of the incident-investigation skill, uses
the placeholders listed in SKILL.md "Assets", and is run with `validate_kql` then
`kql_search` on `ACCOUNT` only. **Don't modify a bundled query or trim its output** — no
aggregating, no dropped columns (see SKILL.md "Assets") — and add your own queries
alongside them whenever the ticket needs something they do not cover.

Tables used: `AzureSigninLogs`, `AzureAuditLogs`, `Office365`, `office365User`. Check they
exist with `list_data_tables` first — a tenant without `AzureSigninLogs` needs the
Office365-only path, and `office-user-investigation` covers it. Record any check that
cannot run for a missing table as a gap, never as a pass.

## 3a — Resolve every address against the rest of the tenant

An IP is not suspicious because it is unfamiliar to one user. Run
`assets/queries/ip_census.kql` over **every address on the ticket** — every IP in every
rule's attributes, not only the IP of the action that scored highest — then
`ip_users.kql` on whatever is left.

The ticket's addresses are the minimum, not the limit. When the picture needs it, resolve
more: the IP the flagged action actually came from in the raw audit event (it can differ
from the sign-in IPs the summary lists), the subject's other sign-in IPs around the event,
and any address a 3c negative turns up. Say which extra addresses you resolved and why.

| Shape | Reading |
|---|---|
| Dozens of users, hundreds of events | Corporate egress / VPN NAT. Not an anomaly, whatever the GeoIP city says. |
| Many users first seen on the same day | A network change — new circuit, new VPN, office move. |
| A handful of users, recent | A site, an event, a travelling group. Corroborate in 3c. |
| Exactly one user, one event | Keep going — but run `ip_prefix_sweep.kql` first. |

`ip_prefix_sweep.kql` is the one that saves you. Before calling a single-user proxy
address attacker infrastructure, check the provider's prefix across the whole tenant.
In the worked case the "unknown Cloudflare IPv6" shared a `/32` with two unrelated
employees on Apple devices through *Apple Internet Accounts* — iCloud Private Relay,
which egresses through Cloudflare. One query turned the strongest-looking indicator
into a consumer privacy feature.

GeoIP is a hypothesis too. Private Relay, VPN and corporate NAT all move the pin, and
a "impossible travel" finding built on an unverified city is manufactured.

## 3b — Read the device that approved the change (authentication incidents only)

For any incident about authentication, MFA, passkeys or credentials, this is the fact
that decides it, and **neither the behavior summary nor the sign-in log contains it**.
For any other Office365 incident (an app registration, a mailbox permission, a policy
change) skip 3b and record it as "not applicable" — do not force it.

`assets/queries/auth_method_changes.kql` over a tight window around the event returns
`ModifiedProperties`. Two properties matter:

- **`StrongAuthenticationPhoneAppDetail`** — the registered authenticator list, with
  `OldValue` and `NewValue`. Diff them. If the device that authenticated is already in
  `OldValue`, an enrolled factor approved the change and the account was not taken
  over. In the worked case an `iPad Pro (12.9-inch) (5th generation)` had been enrolled
  since two weeks before, authenticated 52 seconds before the registration, and its
  user-agent matched the registration session. An attacker would have needed the
  user's own iPad.
- **`SearchableDeviceKey`** — the FIDO credential written, with `Usage=FIDO`,
  `KeyIdentifier` and `CreationTime`.

Also read `AuthenticationDetails` on the sign-in: `"Previously satisfied"` means the
session carried MFA from an earlier authentication, so find that one.

## 3c — Prove what did not happen

A benign verdict rests on negatives, and they have to be collected, not assumed.

- `assets/queries/user_registration.kql` — the account as it stands now. The question
  is never only what was added but **what was removed or demoted**: persistence deletes
  or downgrades factors; a rollout adds one alongside the rest. Check `authMethods`,
  the preferred secondary method, `roles`, and `oauth2Applications` for a grant nobody
  recognises. It reads `office365User`, a snapshot table: if it returns zero rows, run
  `ingext-get-profile`'s readability probe on that table before writing "no methods
  registered" — or reuse the step-1 profile, which already did.
- `assets/queries/bec_sweep.kql` — 30 days of what an actor does *after* taking an
  account: inbox rules, forwarding, delegated mailbox access, transport rules, OAuth
  consent. Zero hits across all of them is strong evidence and takes one query.
- `assets/queries/activity_profile.kql` — place the incident in the account's real
  work. A mass `FileDownloaded` run after the event is exfiltration; a Teams session
  and three file previews is a Thursday.
- **When the subject acted on an application, profile the application here.** The
  subject is still the user; the app is what they changed, and it gets profiled in this
  workflow, not by `ingext-get-profile`. Take the `appId` from the audit event
  (`ModifiedPropertiesFieldsNew.AppId`, `AppPrincipalId`, or the target of "Add
  application." / "Add service principal." / "Update application – Certificates and
  secrets management") and run both:
  - `assets/queries/app_registration.kql` — the app object: created when and by what,
    its secrets and certificates, the API permissions it requests, its redirect URIs.
  - `assets/queries/app_service_principal.kql` — the enterprise app: enabled or not,
    owned by this tenant or a vendor's, SSO mode, credentials, tags, reply URLs.

  Then read them against the audit trail: does the credential in the snapshot match the
  one the audit event added, do the requested permissions fit the app's stated purpose,
  and has anything else touched the app since. An app created minutes ago may not be in
  the snapshot yet — zero rows is a timing gap, not proof it does not exist; say so and
  fall back to the creating audit event.
- **When a credential was added to that application, check whether it has been used.**
  A new secret or certificate is the part of an app registration an attacker wants, and
  the registration events alone cannot say whether it was ever used. Take `{SPID}` from
  the target `id` of the "Add service principal." audit event (the app object id is a
  different GUID) and run all three:
  - `assets/queries/app_signins.kql` — users signing in *to* the app (delegated use).
  - `assets/queries/app_actions_audit.kql` — directory changes the app made as itself.
  - `assets/queries/app_actions_o365.kql` — Microsoft 365 actions the app took as itself
    (`UserId` = `ServicePrincipal_<spid>`); a 30-day `Office365` scan, so expect minutes.

  Each zero needs a control: run the same query with a principal that is known to be
  active in that table (for the audit and Office365 queries, any busy entry under
  `InitiatedBy.app` / `ServicePrincipal_…`; for sign-ins, an app the subject signed in to)
  and show it returns rows. Then say exactly what zero covers. **`AzureSigninLogs` holds
  user sign-ins only**: a client-credentials sign-in with the app's own secret is a
  service-principal sign-in and is not in it. Unless the tenant has a service-principal
  sign-in table, three controlled zeros read "no user sign-ins to the app and no actions
  taken as the app in the directory or Microsoft 365 audit" — and token issuance to the
  secret itself is **not established**, a gap, never "unused".
  Also compare timing: activity that starts minutes after the credential was added, from
  an address 3a did not resolve to the tenant, is the finding this check exists for.
- `assets/queries/dir_changes_targeting.kql` — who else changed this account. Read
  `modifiedProperties` for the group's real name before calling a membership add a
  privilege escalation: a licensing group added from `O365AdminPortal` for a
  salesperson is provisioning, and the same query usually explains the geography
  (a Teams group named for an off-site event placed the user in the right city).
