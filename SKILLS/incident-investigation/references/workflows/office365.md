# Office365 workflow (incident-investigation, step 3)

Run this when the ticket is an **Office365 / Entra ID** incident — its `behaviorRules`
start with `O365_`, `AzureAD_` or `Fluency_O365_` (see the routing table in SKILL.md
step 3). It is three checks, usually run in this order; each one's result goes into the
step-5 closure with the index it came from.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled past tickets of this type, in a sensible order. Add checks or reorder them
> when the evidence points elsewhere. Skip one only when it cannot apply to this ticket
> (say which and why in the closure); a check that applies runs its bundled queries
> before any of your own (non-negotiable 4). Accuracy comes before speed and cost.

Every query below lives in `assets/queries/` of the incident-investigation skill, uses
the placeholders listed in SKILL.md "Assets", and is run with `validate_kql` then
`kql_search` on `ACCOUNT` only. **Don't modify a bundled query or trim its output** — no
aggregating, no dropped columns (see SKILL.md "Assets") — and add your own queries
alongside them whenever the ticket needs something they do not cover.

Tables used: `AzureSigninLogs`, `AzureAuditLogs`, `Office365`, `office365User`. Check they
exist with `list_data_tables` first — a tenant without `AzureSigninLogs` needs the
Office365-only path, and `office-user-investigation` covers it. A tenant without
`AzureAuditLogs` runs the Office365 fallback queries below. Record any check that
cannot run for a missing table as a gap, never as a pass.

**A tenant with an `Okta` table may sign in to Microsoft 365 through Okta.** Its failed
passwords, legacy-authentication attempts and lockouts are then in `Okta`, not here, so
also run `references/workflows/okta.md` for any sign-in or lockout question.

## No `AzureAuditLogs`? The Office365 fallback, and what it cannot see

Not every site collects the AzureAudit feed. `Office365` rows with
`Workload == "AzureActiveDirectory"` and `RecordType == 8` carry Entra's **Core Directory**
audit events: user, group, role, licence, device-object and application changes. On a
tenant with both feeds they matched `AzureAuditLogs` operation for operation. Use them
only when `AzureAuditLogs` is absent. Where both exist, `AzureAuditLogs` is the source.

| AzureAuditLogs query | Fallback | Notes |
|---|---|---|
| `dir_changes_summary.kql` | `dir_changes_summary_o365.kql` | `Initiator` is `UserId` (a UPN, or `ServicePrincipal_<id>`); `InitiatorName` is the actor's display name (`MS-PIM`). |
| `dir_changes_targeting.kql` | `dir_changes_targeting_o365.kql` | Same one-row-per-operation shape; `Changes` from `ModifiedProperties`. |
| `dir_changes_detail.kql` | `dir_changes_detail_o365.kql` | `{CID}` is `InterSystemsId`, the same value as `CorrelationId`. |
| `app_actions_audit.kql` | `app_actions_o365.kql` (already run in 3c) | Its `Workload == "AzureActiveDirectory"` rows are the app's directory actions: `UserId` is `ServicePrincipal_<spid>` for the same events `InitiatedBy.app.servicePrincipalId` names. |
| `campaign_census.kql` | `campaign_census_o365.kql` | Counts users whose method list **grew or shrank** per day, from `Update user.` rows. It tracks the shape of real registrations, a little lower. |

Operation names end in a period in `Office365` (`Add member to group.`), and the time
column is `timestamp`.

**What Office365 never has.** These Entra services do not write to it at all. Zero rows
for any of them is a coverage gap, never a negative:

- **Authentication Methods**: "User registered / deleted / changed security info",
  passkey creation. Their effect still shows as `Update user.` with
  `StrongAuthenticationMethod`, `StrongAuthenticationPhoneAppDetail` or
  `SearchableDeviceKey` modified. That is what 3b's `auth_method_changes.kql` already
  reads, and it covers successful changes only; failed or abandoned attempts are gone.
- **PIM**: activation requests, completions and expiries. The role grant PIM performs
  arrives as `Add member to role.` by `MS-PIM`, so a role *was* granted is visible, but
  *who asked for it and why* is not.
- **Self-service password reset**, and password changes made through it.
- **Device Registration Service**: BitLocker key reads, LAPS password recovery, Windows
  Hello and device-bound passkey adds.
- **Identity Protection**, B2B invitations, Terms of Use, Azure RBAC elevate-access,
  Authentication Methods policy updates.
- Within Core Directory, a few operations are missing too: "Hard Delete" of
  devices/groups/service principals, **"Create application – Certificates and secrets
  management"** (the first credential on a new app; "Update application – …" is present),
  and some licence changes (126 of 176 in the measured week).

**No initiator IP.** `ClientIP` and `ActorIpAddress` are empty on every directory row.
3a cannot resolve the address a directory change came from; use the subject's sign-ins
around that time, and say the change itself carries no IP.

When the fallback runs, the closure states it once: *"AzureAuditLogs not collected;
directory checks ran on Office365 (Core Directory only). PIM, authentication-methods,
self-service password reset and device-registration events, and the initiator IP, were
not available."* Then list every check whose answer depends on those as a gap.

Measured on one large tenant with both feeds, one week: the subject's summary matched on
all 6 Core Directory rows (13/13 role adds, 13/13 removals), and was missing 72 LAPS
password recoveries and 9 PIM self-activations that only `AzureAuditLogs` had.

## 3a — Resolve every address against the rest of the tenant

An IP is not suspicious because it is unfamiliar to one user. Run
`assets/queries/ip_census.kql` over **every address on the ticket** — every IP in every
rule's attributes, not only the IP of the action that scored highest — then
`ip_users.kql` on whatever is left.

The ticket's addresses are the minimum, not the limit. When the picture needs it, resolve
more: the IP the flagged action actually came from in the raw audit event (it can differ
from the sign-in IPs the summary lists), the subject's other sign-in IPs around the event,
and any address a 3c negative turns up. Say which extra addresses you resolved and why.

**The subject's own sign-ins, in two steps — summary first.**

1. `assets/queries/signin_summary.kql` — 30 days as counts per IP × city × country × OS ×
   browser × device × interactive: which addresses, devices and places are normal for
   this user.
2. `assets/queries/signin_detail.kql` — the sign-ins around the incident, `{WFROM}`..`{WTO}`
   = the incident time ±24h (ISO-8601 UTC). One row per sign-in *shape* (IP, device, user
   agent, app, client, result, authentication methods) with its count, first/last time
   and sessions: token refreshes collapse, every distinct shape stays. Read the device
   from `UserAgent`, and `Methods` for how MFA was satisfied.

Never pull 30 days of raw sign-ins: for one busy user that was ~279k tokens and hit the
row cap, so it was both incomplete and most of an investigation's cost.

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

  Without `AzureAuditLogs`, skip `app_actions_audit.kql`: `app_actions_o365.kql`'s
  `AzureActiveDirectory` rows are the same directory actions (see the fallback section).

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
- **Directory changes, in three steps — summary first.**
  1. `assets/queries/dir_changes_summary.kql` — every change touching the account, both
     directions, as counts per activity × initiator × result. "by subject" is what the
     subject did; for an IT admin that is most of the audit log (user updates, licences,
     group adds) and it is ordinary work, not a finding. "on subject" is what the next
     query lists.
  2. `assets/queries/dir_changes_targeting.kql` — who else changed this account, one row
     per operation, with `Changes` as "property: old -> new" (values cut to 80
     characters; a removal carries the group or role in the old value). Read the group's
     real name before calling a membership add a privilege escalation: a licensing group
     added from `O365AdminPortal` for a salesperson is provisioning, and the same query
     usually explains the geography (a Teams group named for an off-site event placed the
     user in the right city).
  3. `assets/queries/dir_changes_detail.kql` — one operation in full (`{CID}` = its
     `CorrelationId`), when a change needs its complete `TargetResources` or
     `AdditionalDetails`. One at a time; never loop it over the list.

  Without `AzureAuditLogs`, run the `_o365` versions of the three queries (fallback
  section above). PIM activations, security-info changes and self-service resets are not
  in them: a directory summary without those rows is not evidence they did not happen.

  An action the subject took that matters (a role granted to someone else, a
  conditional-access or app change) is found in the summary's "by subject" rows; pull
  its operations with the detail query rather than listing all of them.
