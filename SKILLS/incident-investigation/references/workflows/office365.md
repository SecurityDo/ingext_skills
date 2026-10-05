# Office365 workflow (incident-investigation, step 3)

Run this when the ticket is an **Office365 / Entra ID** incident — its `behaviorRules`
start with `O365_`, `AzureAD_` or `Fluency_O365_` (see the routing table in SKILL.md
step 3). It is three checks, usually run in this order, plus **3d** for an outbound-spam
or sending-limit alert; each one's result goes into the step-5 closure with the index it
came from.

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

## A Log Analytics workspace? Use it for sign-ins, Graph and password changes

When step 0 found an `AzureLogAnalytics` integration (SKILL.md, "Find every source"), the
workspace is the source for these checks and the datalake tables are not. Run the `la_*`
queries with `azure_logs_search`, passing `rangeFrom`/`rangeTo` as each query's header
says:

| Check | Datalake query | Workspace query |
|---|---|---|
| 30-day sign-in profile (3a) | `signin_summary.kql` | `la_signin_summary.kql`, interactive and non-interactive |
| Sign-ins around the incident (3a) | `signin_detail.kql` | `la_signin_detail.kql`, with `SessionId` and each authentication step |
| Where a session came from and where it went (3a′) | — | `la_session_trace.kql` |
| Graph requests the subject's tokens made (3c) | — | `la_graph_activity.kql` |
| Was the password actually changed (3c) | — | `la_password_events.kql` |
| Did anyone get the password right after containment (3c) | — | `la_post_containment.kql` |

Directory changes still come from `AzureAuditLogs` (or the workspace's `AuditLogs`; they
hold the same Entra audit). The Exchange checks (`bec_sweep`, `activity_profile`) still run
on the datalake's `Office365`.

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

## 3a′ — Trace the session (stolen-session and token alerts)

A "stolen session cookie", "anomalous token" or "Azure AD threat intelligence" alert is
about a **session**, not a sign-in. The session is minted once and then replayed, often
the next day, from residential proxies that change on almost every request. The replay
sign-ins say "MFA satisfied by claim in the token", and none of them is the moment the
account was lost. Take the `SessionId` from the alert (Defender's
`cloudLogonSessionEvidence.sessionId`) or from `la_signin_detail.kql`, and run
`la_session_trace.kql` over 30 days:

- **The first row is the capture.** Its address, user agent and authentication steps
  ("Correct password" plus the second factor, satisfied *on that sign-in*) say where and
  how the session was taken. A browser string that matches the user's own phone while the
  detected OS is a desktop one is what a phishing proxy relaying the victim looks like.
  Look at the subject's own sign-ins in the minutes either side (`la_signin_detail.kql`):
  the victim usually lands on the real site seconds after the capture.
- **Read what happened just before it.** A broken push MFA, a helpdesk-added phone method,
  a new-device enrolment: a user stuck at a prompt is the user who follows a link to get
  past it.
- **Every later row is a use of the stolen session.** Count the addresses and note which
  resource each token was for (Exchange, Graph). Those are what `la_graph_activity.kql`
  and the Exchange checks then follow.
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

## 3c — Prove what did not happen

A benign verdict rests on negatives, and they have to be collected, not assumed.

- `assets/queries/user_registration.kql` — the account as it stands now. The question
  is never only what was added but **what was removed or demoted**: persistence deletes
  or downgrades factors; a rollout adds one alongside the rest. Check `authMethods`,
  the preferred secondary method, `roles`, and `oauth2Applications` for a grant nobody
  recognises. It reads `office365User`, a snapshot table: if it returns zero rows, run
  `ingext-get-profile`'s readability probe on that table before writing "no methods
  registered" — or reuse the step-1 profile, which already did.
- **Is it contained? A revoked session is not a changed password.** Run
  `la_password_events.kql` and `la_post_containment.kql` whenever the ticket is a
  credential or session theft and the customer has responded:
  - A session revocation (`Update StsRefreshTokenValidFrom Timestamp`, "Revoke Session
    Tokens") ends tokens. It does **not** change the password, and Microsoft's own risk
    remediation for a token-theft risk revokes sessions only.
  - On a synced (hybrid) account an on-prem reset is logged only in
    `IdentityDirectoryEvents`, never in Entra `AuditLogs`. An "Account Password changed"
    followed seconds later by "Account Password expired" is a reset with "must change at
    next logon", and unless the tenant enabled `UserForcePasswordChangeOnLogonEnabled`,
    that password is **not synced**: Entra keeps the old one.
  - Any row in `la_post_containment.kql` from an address or user agent that is not the
    user's is an attacker who still has the password, stopped only by the second factor.
    The closure says **not contained**, and the first recommendation is a password change
    that is confirmed by an Entra password event.
- **What did the stolen tokens ask Graph for?** `la_graph_activity.kql` lists every request.
  A directory dump (`GET /users?$top=999`), a `$search` for payroll, finance or HR staff, or
  a scripted client (`axios`, `python-requests`) is reconnaissance for the next attack, and
  the people it found are who to warn. Graph does not log response bodies: report the
  bytes, and if you reconstruct who matched a search from the directory, label it a
  reconstruction.
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

