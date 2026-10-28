# Office365 workflow (incident-investigation, step 3)

Run this when the ticket is an **Office365 / Entra ID** incident — its `behaviorRules`
start with `O365_`, `AzureAD_` or `Fluency_O365_` (see the routing table in SKILL.md
step 3). It is three checks, usually run in this order, plus **3d** for an outbound-spam
or sending-limit alert, **3e** for a DLP match and **3f** for file uploads, downloads and
sharing; each one's result goes into the step-5 closure with the index it came from.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled past tickets of this type, in a sensible order. Add checks or reorder them
> when the evidence points elsewhere. Skip one only when it cannot apply to this ticket
> (say which and why in the closure); a check that applies runs its bundled queries
> before any of your own (non-negotiable 4). Accuracy comes before speed and cost.

**A Teams helpdesk-impersonation or mail-bombing ticket also runs
`references/workflows/helpdesk.md`.** This file proves what did not happen to the
*account*; in that family the attacker never touches the account from outside, so a
clean result here is expected and decides nothing. Engagement on the call and the device
timeline do.

Every query below lives in `assets/queries/` of the incident-investigation skill, uses
the placeholders listed in SKILL.md "Assets", and is run with `validate_kql` then
`kql_search` on `ACCOUNT` only. **Don't modify a bundled query or trim its output** — no
aggregating, no dropped columns (see SKILL.md "Assets") — and add your own queries
alongside them whenever the ticket needs something they do not cover.

Tables used: `AzureSigninLogs`, `AzureAuditLogs`, `Office365`, `office365User`,
`office365ConditionalAccessPolicy` with `office365Group` (3a, "Why did it get through?"),
and where the tenant has them `DuoAuthentication` (3a, 3b) and `WindowsAudit` (3c).
`list_data_tables` lists the `office365*` snapshot tables under `resourceTables`: query
them with `kql_search` like any other table. Check they
exist with `list_data_tables` first — a tenant without `AzureSigninLogs` needs the
Office365-only path, and `office-user-investigation` covers it. A tenant without
`AzureAuditLogs` runs the Office365 fallback queries below. Record any check that
cannot run for a missing table as a gap, never as a pass.

**`list_data_tables` can name a raw table (`Duo`) when the typed one is what KQL reads.**
A tenant whose Duo source shows up as `Duo` is queried as `DuoAuthentication`; probe it
with `DuoAuthentication | where timestamp > ago(1d) | project timestamp, txid | take 1`
before calling Duo a gap. Selecting the nested fields from `Duo` returns nulls, not an
error.

**A tenant with an `Okta` table may sign in to Microsoft 365 through Okta.** Its failed
passwords, legacy-authentication attempts and lockouts are then in `Okta`, not here, so
also run `references/workflows/okta.md` for any sign-in or lockout question.

## A Log Analytics workspace? Hand those checks to the sub-skill

When step 0 found an `AzureLogAnalytics` integration (SKILL.md, "Find every source"), the
workspace is the source for the sign-in profile and detail (3a), the session trace
(3a′), and the Graph and containment checks (3c), and the datalake tables are not.
**`ingext-log-analytics-evidence`** carries those checks and their `la_*` queries; run
it at each step marked *workspace* below. Directory changes still come from
`AzureAuditLogs`, and the Exchange checks (`bec_sweep`, `activity_profile`) still run on
the datalake's `Office365`. On an account without a workspace — most of them — skip
every *workspace* step and record what it would have answered as a gap where this file
says so.

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

**First, look the addresses up in the tenant's own subnet inventory.** Call
`list_entity_tables` and take every table with `lookupType: CIDR`. Read each one's
description: an inventory of the organisation's own ranges (an IPAM export, an office or
ISP-circuit list) is what proves an address is *their* network. A watchlist such as
"critical subnets" only labels a range. Run `assets/queries/subnet_lookup.kql` once per
inventory table, over the same addresses. It takes the table's `kqlName`, its CIDR
column and a label built from its other columns. Then grade every address before you
write about it:

| Evidence | Grade | How to write it |
|---|---|---|
| Inside a range in the organisation's own inventory | **owned** | "<Org>'s own network (`<table>`: `<cidr>` <label>)" |
| No inventory match, but `ip_census` shows dozens of users | **shared** | "shared by N users in 30 days; not in `<table>`". Never "<Org>'s own" |
| `decidable: false` (the table holds no range of that family, often no IPv6 at all) | **undecided by the inventory** | grade it on the census alone, and say the inventory cannot answer |
| No table with `lookupType: CIDR` | — | say so once; every address is graded on the census |

- **No match is not "external".** An inventory can miss a circuit. On one tenant, one of
  the two HQ egress addresses, used by 1,064 users, was absent from a 1,547-row IPAM
  export, while the other one matched. An address that is shared at that scale but not
  in the inventory is a side finding: the customer's inventory may be incomplete.
- **Owned settles where, not who.** A match says the sign-in came from inside the
  organisation's network. A compromised laptop, or an attacker on the VPN, comes from
  there too. It answers the location question and nothing else.
- **Account notes do not replace the lookup.** A note listing "the org's shared corporate
  IPs" records a past census. Run the lookup on this ticket's addresses anyway, and when
  you save or revise such a note, keep owned and shared addresses in separate lists.

**Before calling an address "new" or "never used", check it in two steps.**

1. **Pre-filter in the behavior index (milliseconds).** Run `behavior_event_search` over
   30 days with the quoted IPs as `searchStr`. If it shows the address on this user, or
   on other users, before the ticket, the address is not new and you can stop.
2. **Deep search only when the address is absent there or first seen at the ticket:**
   run `ip_client_o365.kql`. The behavior index holds only a sign-in fingerprint, so
   when it finds nothing, that proves nothing.

This applies on every tenant, and above all on one without `AzureSigninLogs`. Office365
sign-in rows are sparse, because one token covers hours of use. An address can be absent
from the sign-in census and still have carried the user's Outlook, or a colleague's, for
days. The query adds Outlook desktop (`Client=MSExchangeRPC`) and OWA rows, which carry
the client's own address. Use them only to test whether it is the **same IP**, by user
(`actor`) and by mailbox. They are never a source of location: take location only from
sign-in rows. Do not widen the query to other Exchange clients. `REST`/`RESTSystem` rows
carry Microsoft datacenter addresses.

The ticket's addresses are the minimum, not the limit. When the picture needs it, resolve
more: the IP the flagged action actually came from in the raw audit event (it can differ
from the sign-in IPs the summary lists), the subject's other sign-in IPs around the event,
and any address a 3c negative turns up. Say which extra addresses you resolved and why.

**The subject's own sign-ins, in two steps — summary first.** On an account with a
workspace, run `ingext-log-analytics-evidence`'s `la_signin_summary` and
`la_signin_detail` in their place (*workspace*): they add the non-interactive sign-ins,
`SessionId` and each authentication step, which these two cannot see.

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
| Dozens of users, hundreds of events | Corporate egress / VPN NAT. Not an anomaly, whatever the GeoIP city says. Call it the organisation's own only when `subnet_lookup` matched it. |
| Many users first seen on the same day | A network change — new circuit, new VPN, office move. |
| A handful of users, recent | A site, an event, a travelling group. Corroborate in 3c. |
| Exactly one user, one event | Keep going — but run `ip_prefix_sweep.kql` first. |

`ip_prefix_sweep.kql` is the one that saves you. Before calling a single-user proxy
address attacker infrastructure, check the provider's prefix across the whole tenant.
In the worked case the "unknown Cloudflare IPv6" shared a `/32` with two unrelated
employees on Apple devices through *Apple Internet Accounts* — iCloud Private Relay,
which egresses through Cloudflare. One query turned the strongest-looking indicator
into a consumer privacy feature.

**On a Duo tenant, also run `duo_ip_census.kql` over the same addresses.** It counts
users on each side of a Duo event: the computer (`access_device`) and the phone
(`auth_device`). Staff phones on an office Wi-Fi report that network as their
`auth_device.ip`, and phones never appear in `AzureSigninLogs`. So an office network can
look like "a handful of users" in `ip_census.kql` and still be dozens of users' phones in
Duo. Many users on the phone side of an address means it is the organisation's own
network.

**An IPv4 and an IPv6 address in the same seconds are one client.** A dual-stack machine
sends some requests over IPv6 (often the MFA registration and the security-info pages)
and others over IPv4 (the sign-ins). When the directory audit's initiator address is
IPv6 and the sign-ins in the same seconds are IPv4, resolve them as one location: the
location of the IPv4 address that 3a has already resolved. Do not call the IPv6 address
"the user's home" because no one else uses it. Each machine gets its own IPv6 address,
so it is almost always unique to one user, and that says nothing about where the user is.

GeoIP is a hypothesis too. Private Relay, VPN and corporate NAT all move the pin, and
a "impossible travel" finding built on an unverified city is manufactured.

**Why did it get through? Read the policies, don't guess them.** Run
`assets/queries/ca_user_policies.kql` whenever the sign-ins show a correct password that
Conditional Access blocked (53003, 399218, `Correct password` in `Methods`) and a later
success, or a success with `AuthRequirement = singleFactorAuthentication` on an account
with no MFA registered. It lists every enabled or report-only policy that matches the
user (by object id, by "All", or through a group, included or excluded) with its grant,
sign-in-risk condition, client apps, target apps and locations. Read the result
against the blocked and the successful sign-ins:

- Only "All" rows, and the blocking one is the risk-based policy (`SignInRisk` high,
  grant block): the user is protected only by Microsoft's risk score. A known password
  from an address with no bad reputation (a residential proxy in the right country)
  gets a risk of "none" and goes straight through. Say so: the gap is in the policies,
  and it usually covers every account set up like this one, not just the subject.
- A location or MFA policy the user's peers are in and the user is not: check what the
  policy's other members are (`office365User.jobTitle`) before calling it a missed
  account. On one retail tenant the per-store "Block if not <store IP>" policies named
  only the stores' shared kiosk PC accounts. Store staff not being in them was the
  design, not an oversight.
- An `exclude-*` row on the policy that should have applied: a standing exclusion, the
  first thing to name in the customer actions.

The sign-ins on Graph-polled tenants leave `appliedConditionalAccessPolicies` empty, so
"policy X blocked this" is inferred from the inventory and the sign-in's risk level and
result. Write it as inference. Roles are not matched by the query: if the user holds a
role (`user_registration.kql`), check the policies scoped by
`conditions.users.includeRoles` yourself.
Never write a sentence about how the tenant's Conditional Access works without this
query's result behind it.

## 3a′ — Trace the session (stolen-session and token alerts) — *workspace*

A "stolen session cookie", "anomalous token" or "Azure AD threat intelligence" alert is
about a **session**, not a sign-in: minted once, replayed later from addresses that
change on almost every request, and none of the replay sign-ins is the moment the
account was lost. Tracing it back to the capture needs the non-interactive sign-ins, so
it runs in **`ingext-log-analytics-evidence`** ("Trace the session"), starting from the
alert's session id (Defender's `cloudLogonSessionEvidence.sessionId`).

- The datalake has none of this when the account has no workspace: say "session origin not
  established" and name the alert's session id as the thing to trace.

## 3b — Read the device that approved the change (authentication incidents only)

For any incident about authentication, MFA, passkeys or credentials, this is the fact
that decides it, and **neither the behavior summary nor the sign-in log contains it**.
For any other Office365 incident (an app registration, a mailbox permission, a policy
change), skip the full check. Do read one row, though: when a sign-in by the subject
precedes the flagged action, read the subject's `Update user.` row at that sign-in, using
`dir_changes_summary_o365` / `dir_changes_summary` ("on subject", initiator
`Azure MFA StrongAuthenticationService`). Its `StrongAuthenticationPhoneAppDetail` diff
shows which enrolled device approved the session. If the device is the same (same `Id`,
same `DeviceToken`, only `LastAuthenticatedTimestamp` and the app version changed), an
already-enrolled factor approved the session. That is the cheapest strong evidence
against a takeover, and it costs one query you have usually already run. A dormant admin
account whose old phone approves the sign-in is the owner, or someone holding the
owner's phone.

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

### Duo (external MFA): was the "new device" just enrolled?

When MFA is Duo, through Entra external authentication methods or any other
integration, the authenticator diff above does not exist: Entra records only "User
registered External MFA". The device is in Duo. Run `duo_device_history.kql`
(30 days, every enrolment and authentication for the subject) and read it as follows:

- **An `enrollment` row for the same `authDeviceKey` shortly before the flagged
  approval** means the alert is the first use of a phone the subject had just enrolled.
  A "device not seen in 30 days" rule fires on it by construction. The question changes
  from "whose phone approved this?" to "who enrolled it?". Answer it with the
  enrolment's surroundings: the subject's own sign-in session (3a), and on a hybrid
  account the password reset that let them in (3c).
- **An approval from a device key that was not just enrolled, while the subject has an
  older key,** is the substitution a takeover produces. Compare it against the older
  key's last use.
- **Ownership after the fact.** A later approval by the same key, with
  `authDeviceIp == accessIp` (phone and computer on one network) at an address the
  subject uses again, ties the phone to the person who uses that computer. Run the
  history up to the time of the run, not only to the ticket time.
- **A brand-new account's first enrolment is expected onboarding.** Duo's own record of
  the account's creation (`DuoAdmin`, `user_create` by the directory sync) and the
  account's age come from step 1. On an account that is days old, every first-seen rule
  fires at its first sign-in. Say so, and do not read the risk score as severity.

## 3c — Prove what did not happen

A benign verdict rests on negatives, and they have to be collected, not assumed.

- `assets/queries/user_registration.kql` — the account as it stands now. The question
  is never only what was added but **what was removed or demoted**: persistence deletes
  or downgrades factors; a rollout adds one alongside the rest. Check `authMethods`,
  the preferred secondary method, `roles`, and `oauth2Applications` for a grant nobody
  recognises. It reads `office365User`, a snapshot table: if it returns zero rows, run
  `ingext-get-profile`'s readability probe on that table before writing "no methods
  registered" — or reuse the step-1 profile, which already did.
- **Is it contained? A revoked session is not a changed password** — *workspace*. A
  session revocation ends tokens but does not change the password, and on a synced
  account an on-prem reset with "must change at next logon" is usually never synced to
  Entra. Whenever the ticket is a credential or session theft and the customer has
  responded, run `ingext-log-analytics-evidence` "Is it contained?". Without a
  workspace, read the password events in `AzureAuditLogs` and the next bullet's on-prem
  path, and say the post-containment sign-ins were not verified.
- **Who changed the password on a hybrid account?** Entra records an on-prem change as
  `Change user password` / `Update PasswordProfile` initiated by the directory-sync
  account (`ConnectSyncProvisioning_*`, or `Action Client Name: DirectorySync`). That
  names the sync, not the person. Whenever such a row falls in the ticket window, and
  the tenant collects `WindowsAudit` from its domain controllers, run
  `onprem_password_events.kql` for the subject's on-prem account name and
  `onprem_resetters.kql` as its control:
  - `4724` with `SubjectUserName` = an admin is a reset by that admin. `4723` is the
    user's own change. `4767` is an unlock, and `4771` with Status `0x18` is a wrong
    password; a run of these before a reset is a user locked out and helped. The first
    `4768` with Status `0x0` after it is the first good logon, and its time matches the
    Entra sync row.
  - `onprem_resetters.kql` shows whether that admin resets passwords routinely. A
    helpdesk account that does it every week is the expected actor. A reset by an
    account that never does it is a finding. If the control returns nothing, the DC
    log is not collected: a gap, not a negative.
  - The `IpAddress` on the `4771` / `4768` rows is the internal client the user typed
    the password on. Internal addresses there place the user on site, whatever GeoIP
    says about their Entra sign-ins.
  - `EventTime` is the DC's local time with no zone. Use `timestamp` (UTC, a few
    seconds late) for the timeline, or work out the offset from the `4768` that
    matches the Entra sync row.

  Do not explain an on-prem password change as "routine propagation" without this
  check. A named admin resetting the password of a locked-out user is the strongest
  benign evidence an onboarding or lockout ticket has, and the sync row hides it.
- **What did the stolen tokens ask Graph for?** — *workspace*. Graph requests are logged
  only in the workspace: run `ingext-log-analytics-evidence` "What did the stolen tokens
  ask Graph for?". Without one, it is a gap.
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

  **Whose app is it?** Decide this before judging anything else, because it changes every
  recommendation:
  - **"Add application." from the subject** means the tenant created its own app
    registration. The subject owns its secrets, and "rotate the secret" is a real lever.
  - **"Add service principal." with no "Add application."**, and no row in
    `app_registration.kql` once the snapshot has caught up, means a **third-party
    multi-tenant app**. Consent creates a local instance of an app that lives in the
    vendor's tenant. Nobody in this tenant created the app or holds its credentials. The
    `Credential` on the service principal event is not a secret the tenant can rotate.
    Never write "self-registered" for this case.
    - Name the vendor from the reply URLs in the event's `AppAddress`, read whole. A
      vendor callback domain or a custom scheme (`<product>://`) names the product. Then
      check the vendor's public documentation where the run can reach it.
    - Say the publisher is unverified until `app_service_principal.kql` shows
      `verifiedPublisher` and `appOwnerOrganizationId`.
    - The levers are the **grant** and the **service principal**: revoke the grant,
      narrow it to named users, drop scopes, or disable or delete the service principal.

  **Read the consent itself, whole** (`dir_changes_detail_o365.kql` /
  `dir_changes_detail.kql` on its `CorrelationId`):
  - `ConsentContext.IsAdminConsent` and `OnBehalfOfAll` (or `ConsentType: AllPrincipals`)
    show whether one person consented for themselves or an admin consented for every user.
  - `ConsentContext.IsAppOnly` decides which usage check below applies.
  - `ConsentAction.Reason` is Entra's own verdict. **"Risky application detected"** means
    Microsoft flagged the app and an admin overrode it.
  - The scope list is on "Add delegated permission grant.".

  **Find who asked for it.** An admin consent usually answers a request. Search the app's
  sign-ins across the tenant for the hour before the consent:
  - `UserLoginFailed` with `LogonError` = **`AdminConsentRequired`** means a user was
    blocked and needed an admin.
  - `DelegationDoesNotExist` is the consent prompt itself.

  `app_delegated_use_o365.kql` returns these rows. A blocked user minutes before the
  consent turns "an admin granted access out of nowhere" into "an admin answered a
  user's request". It also tells you the grant's intended audience: an `AllPrincipals`
  grant made for one requester is the scope finding.

  **Re-run the consent census at the end of the investigation, not only at the start.**
  Grants change after a ticket is raised, and a second admin can widen the scopes the
  same afternoon. List every "Consent to application.", "Add delegated permission grant."
  and "Remove delegated permission grant." for the app up to the time of the run. The
  **remove-then-add pair** is how Entra records a scope change on an existing grant.
- **When the grant is delegated (`IsAppOnly: False`), check what the app did as each
  user.** A delegated app acts *as the signed-in user*, and its actions are recorded
  under that user, never under `ServicePrincipal_<spid>`. So `app_actions_o365.kql`
  cannot see them, and a zero from it says nothing about a delegated mail or Teams grant.
  Run `assets/queries/app_delegated_use_o365.kql`, which matches the app id in `AppId`,
  `ClientAppId`, `ApplicationId` and `AppAccessContext`:
  - **Rows under a user other than the consenting admin** mean the grant is in use in that
    user's data. An Exchange `SoftDelete`, `Send`, `Update` or `Move` with
    `ClientInfoString: Client=REST` is the app writing to that mailbox through Graph.
  - **The control is `assets/queries/app_delegated_use_ctl_o365.kql`.** It counts rows that
    name any client app, per workload. On one tenant Exchange carried client-app ids on
    most rows while OneDrive and SharePoint carried none. A SharePoint or OneDrive zero
    there is a gap.
  - **Most reads are not audited.** `MailItemsAccessed` needs premium auditing, and Teams
    message reads are not in this feed. A zero covers writes and sign-ins only. Write
    "no write or sign-in by the app outside …", never "the app has not been used".
- **When a credential was added to that application, check whether it has been used.**
  A new secret or certificate is the part of an app registration an attacker wants, and
  the registration events alone cannot say whether it was ever used. Take `{SPID}` from
  the target `id` of the "Add service principal." audit event (the app object id is a
  different GUID) and run all three:
  - `assets/queries/app_signins.kql` — users signing in *to* the app (delegated use).
  - `assets/queries/app_actions_audit.kql` — directory changes the app made as itself.
  - `assets/queries/app_actions_o365.kql` — Microsoft 365 actions the app took as itself
    (`UserId` = `ServicePrincipal_<spid>`); a 30-day `Office365` scan, so expect minutes.
    App-only use only. What a delegated grant did as each user is in
    `app_delegated_use_o365.kql` (above).

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

## 3d — Outbound spam: find what actually sent the mail

Run this when the ticket is a sending-limit or outbound-spam alert: the rule is an
`O365_SCC_Threat_Management_Alert_*` whose data says `EmailSendingLimitExceeded`, "User
restricted from sending email" or `RecipientRateLimitExceeded`, or the account has a
`HygieneTenantEvents` row with `Event: Listed`. Exchange has already stopped the mailbox
from sending; the question is **what submitted the mail**, because that decides between a
compromised account and a business system that outgrew a mailbox.

The usual reading of these alerts, "high volume, so the account is compromised: block it
and reset the password", is the one to test, not to act on. A reset does nothing to an
application that relays through an on-prem server, and a block stops a business process.

1. **Is this the first?** `assets/queries/sending_limit_census.kql` lists every restriction
   and sending-limit alert on the account in 30 days. Its control is the ticket's own
   restriction. Read `Reason` whole: `RecipientCountLast24Hours`, the limit, and the last
   message trace id (the customer's Message Trace starts from it). The same mailbox listed
   on the same weekday every month is a scheduled job.
2. **Did the mail go through the mailbox?** `assets/queries/send_audit_ctl.kql` counts
   Send / SendAs / SendOnBehalf over the incident window, with the subject's rows split
   by client (`ClientInfoString`) and address. Rows for the subject name the path: a
   mail client, OWA, a REST client or SMTP AUTH, and the address it came from. **Zero
   rows for the subject next to many other senders** means the mail did not pass through
   the mailbox. Mail that an on-prem relay submits through a connector never does. Do not
   write "mailbox auditing is disabled" from that zero alone: it is one explanation, and
   the relay is another.
3. **Can the sign-in table see the sender?** `assets/queries/signin_coverage_ctl.kql`
   splits the sign-in table by interactive and non-interactive, with the subject's rows
   and Authenticated SMTP rows. SMTP AUTH is a non-interactive sign-in. On a feed with **no
   non-interactive rows**, the subject's zero sign-ins rule out an interactive takeover
   only. SMTP AUTH from the internet is then a gap, stated as one, never a negative.
4. **Which host sent it?** On an account with FortiGate tables, run in order, one at a
   time (they scan the traffic table, about a minute each):
   - `assets/queries/fw_smtp_senders.kql` over the 24 hours before the restriction: every
     internal host sending SMTP, to Microsoft's mail edge (`52.101.x` on 25) or to an
     internal relay. A host sending to the mail edge is the relay or an application with
     a connector; hosts sending to that relay are its clients.
   - `assets/queries/fw_smtp_sender_baseline.kql` on each candidate: eight days, per day.
     **Compare working day with working day.** On one account the relay carried about 200
     connections on a weekend day and 547–1,314 on weekdays. The incident Monday's 940 read
     as "five times normal" against the weekend and was ordinary against the week.
   - `assets/queries/fw_smtp_sender_hourly.kql` on the incident day. A large session at the
     same hour on every baseline day is a scheduled job, not the spike.
   - `assets/queries/host_ip_owner.kql` to name each address: a relay often has a second
     address that no inventory knows.
   - Then the relay host's own EDR record (threats on its agent id, SentinelOne workflow
     S5) for anything that ran on it.

   **What the firewall can and cannot say.** It counts SMTP connections, not messages,
   recipients or sender addresses: it cannot tie the subject's 10,000 recipients to one
   relay connection. Hosts on the relay's own subnet reach it without crossing the
   firewall. A relay that sends far more than the firewall saw it receive is not by
   itself the source of the mail. "The mail most likely left through <relay>" is an
   inference from the subject having no cloud sends; label it so. Recipients, sender
   addresses and the client that submitted each message are in the customer's Message
   Trace and the relay's own logs. Name both as the place the question is answered.
5. **Takeover negatives still run.** `bec_sweep.kql` (inbox rules, forwarding, delegated
   access, consent) and the directory summary. A `LastDirSyncTime` change on a long-idle
   synced account reads like someone touching it. Before citing one, count how many
   accounts the same sync service principals touched that day: on one account a single
   morning's sync touched 161 users, 17 of them idle for over a year.

| What 3d shows | Verdict |
|---|---|
| No sign-ins or sends by the subject, no takeover changes, an internal relay carrying the account's mail at its normal weekday volume | Escalate with one question: which system on <relay> sends as this mailbox, and what changed the recipient count? Keep the mailbox restricted until the customer answers; no password reset on this evidence |
| The subject's own Send rows from SMTP AUTH or a REST client at an address 3a does not resolve to the tenant, or inbox rules / forwarding created around the burst | Account compromise: contain (block sign-in, revoke sessions, change the password, remove the rules), then pull the recipients from Message Trace |
| The same mailbox restricted on a regular schedule, sent through the relay at the job's usual hour | Benign business process outgrowing a mailbox: the fix is a bulk-mail path for that system, and the restriction is the symptom |

## 3e — DLP match: read the message before describing it

Run this when the ticket is a DLP rule (`O365_DLP_*`, or an `Office365` `DlpRuleMatch`).
The question the customer has is **did sensitive data leave, and to whom**. The behavior
event cannot answer it: its IP, city and message fields are usually `__undefined`. The raw
`DlpRuleMatch` row can.

1. **Run `assets/queries/dlp_message.kql`** over the incident window, before writing a
   word about the message. It gives one row per message and rule: `From`, `To`, `CC`,
   `BCC`, subject, policy, rule, `RuleMode`, severity, actions, `AccessScope`, and which
   sensitive types matched in which attachment or in the body.
2. **Direction comes from `From`.** `From` equal to the subject mailbox is mail it sent.
   A subject line's "FW:" or "RE:" says nothing about direction. A run read "FW: …" as
   mail forwarded *to* a shared mailbox, and it was that mailbox sending an attachment
   to an outside company.
3. **Name every external recipient domain.** `AccessScope: IncludeExternalUsers` means at
   least one recipient is outside the organization; the domains are in `To` / `CC` /
   `BCC`. "Internal mail" needs every recipient on the tenant's own domains. A gap is
   not a finding: if the recipients weren't read, the closure says "recipients not
   verified" and makes no claim about where the mail went.
4. **Mode and action.** `RuleMode` `TestWithoutNotifyUser` / `TestWithNotifyUser` logs only,
   so nothing was blocked. `Enable` with an empty `Actions` also blocked nothing. Say
   which, because it decides whether the data actually left.
5. **Was the recipient expected?** Look for the request the mail answers: an earlier
   message from the same external address in the subject's mailbox activity, a thread
   subject that names the request, or the same recipient on other `dlp_message` rows in
   30 days. A carrier, payroll provider or benefits administrator asking for exactly what
   was sent is business. A free-mail address, a domain first seen that day, or a
   recipient the mailbox has never written to before is the case to escalate.
6. **Takeover negatives still run.** Use the subject's sign-ins and `bec_sweep.kql` (rules,
   forwarding, delegates). A shared mailbox has no sign-ins of its own: who sent as it
   is in `send_audit_ctl.kql`'s client rows. A delegate is not "unconfirmed" just
   because the mailbox is shared.

| What 3e shows | Verdict |
|---|---|
| Sent by the subject to a recipient that asked for it (carrier, provider, auditor), from the subject's usual client and address | Benign: name the recipient domain and the rule mode. The tuning question for the customer is whether that data should go out by plain mail at all |
| Sent to a recipient with no history, a free-mail domain, or BCC'd outside, by a delegate or client the mailbox doesn't normally use | Escalate: the external domain, the message id for the customer's Message Trace, and whether the rule blocked it |
| Mail *received* by the subject (`From` external) | Not a leak by the subject. Say who sent it and whether the policy should scan inbound mail |

## 3f — File movement: who moved it, where, and who it was shared with

Run this when the ticket is about files: `O365_SharePoint_OneDrive_FileUploaded_Multiple`,
a mass download or sync, a sharing or anonymous-link rule, or a Defender data-exfiltration
alert. "Many uploads" is not the question. The question is **what moved the files, where
they went, and whether anyone outside got them**.

1. **Run `assets/queries/file_movement.kql`** over the incident window, before describing
   the activity. It gives one row per operation, acting app, agent and site, covering
   uploads, downloads, sync, copy, move and every sharing and link operation.
2. **The app comes before the user.** `ClientApp` is the app that held the token, and
   `Agent` names an AI agent. Copilot acts as the user, so its rows carry the user's
   UPN:
   - `Enterprise Copilot Platform` writes into the user's `Documents/Copilot/Created`;
   - the M365 Copilot agent reads the source documents through a client app whose
     name gives nothing away; `Agent` (`AgentName: M365 Copilot`) is what identifies it.

   Name the app and agent behind every count in the closure. A browser or sync client
   from the user's devices is the user. An app or agent the user doesn't normally use
   is the finding.
3. **Read the sharing rows, never only the uploads.** `SharingLinkCreated` with its
   `scopes` (`SpecificPeople`, `Organization`, `Anonymous`), `AnonymousLinkCreated`,
   `AddedToSecureLink`, `SharingInvitationCreated`, `SharingSet`.
   - An anonymous or Organization link, or any external recipient, is the case to escalate.
   - A `SharingLinks.<id>.Flexible…` target is the link's own group, not a person.
   - When no row names the recipients of a SpecificPeople link, the closure says
     "link recipients not in the audit" as a gap. The customer's sharing report for those
     files answers it.
4. **Where did the files go?** `own` is the subject's own OneDrive. Writes and links
   in the subject's own OneDrive stay inside the account. Writes to another person's
   OneDrive, a site the subject has no history on, or a personal account
   (`FileSyncUploaded*` to an unmanaged device) are the case to escalate. Reads from many
   sites by an agent are normal: it is grounding on what the user can already open.
   Say how many sites and that they are the user's own access.
5. **Whose session was it?** Tie the agent's work to a sign-in by the user: the same hours,
   their device and address from 3a. Copilot running in a session the user didn't start
   is a stolen session, and 3a′ applies.
6. **Takeover negatives still run.** Use `bec_sweep.kql` and the directory summary, as
   in 3c.

| What 3f shows | Verdict |
|---|---|
| Copilot or the user's own clients writing and sharing (SpecificPeople) inside the user's OneDrive, during the user's own session | Benign: name the app and agent, the counts, and that the link recipients are a gap if the audit doesn't name them. Tune the rule to leave out agent-created files |
| Anonymous or Organization links, an external recipient, or writes to a site or OneDrive outside the user's own | Escalate: the files, the link scope and recipients, and whether the links are still live |
| An unfamiliar app or agent doing the moving, or the activity outside any sign-in by the user | Treat it as account compromise: check the session (3a′), the app's consent (bec_sweep) and contain |

