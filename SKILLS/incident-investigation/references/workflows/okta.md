# Okta workflow (incident-investigation, step 3)

Run this when the ticket is an **Okta** incident: its `behaviorRules` start with `okta_`
(see the routing table in SKILL.md step 3). Run it too for an **Office365 sign-in ticket
on a tenant that signs in to Microsoft 365 through Okta**. There, a failed Microsoft 365
password is checked by Okta, so the failure lands in the Okta log and never in
`Office365` (`login_failures.kql` comes back empty even when Okta holds the attempts). It is six
checks, usually run in this order; each one's result goes into the step-5 closure with
the query it came from.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled past tickets of this type, in a sensible order. Add checks or reorder them
> when the evidence points elsewhere. Skip one only when it cannot apply to this ticket
> (say which and why in the closure); a check that applies runs its bundled queries
> before any of your own (non-negotiable 4). Accuracy comes before speed and cost.

Every query below lives in `assets/queries/` of the incident-investigation skill, uses
the placeholders listed in SKILL.md "Assets", and is run with `validate_kql` then
`kql_search` on `ACCOUNT` only. **Don't modify a bundled query or trim its output** (see
SKILL.md "Assets"), and add your own queries alongside them whenever the ticket needs
something they do not cover.

Tables used: `Okta` (the Okta System Log) and `office365User` (the subject's directory
roles, when the tenant also runs Microsoft 365). `{USER}` is the lower-cased Okta login
(`actor.alternateId`), which is normally the UPN.

## Three things about the Okta table that decide the answer

- **Count events by `uuid`, never by rows.** The datalake can hold the same Okta event
  more than once, the same `uuid` under two lake ids. Every bundled query counts `dcount(uuid)` or dedupes on it. A count of raw
  rows in your own query is wrong by that factor.
- **The request path is only reachable through KQL.** `debugContext.debugData.requestUri`
  says *how* a sign-in happened, and `lake_search` cannot filter on it: a wildcard or a
  phrase on that field returns 0 even for events that carry it. Query it with
  `kql_search` as `["debugContext.debugData.requestUri"]`. Whole documents from
  `lake_search` do contain it, but whole documents for a busy account are very large and
  get cut, so read it from the bundled queries.
- **Column names are the dotted paths, bracket-quoted:** `["actor.alternateId"]`,
  `["outcome.result"]`, `["client.ipAddress"]`, `["securityContext.isp"]`,
  `["request.ipChain"]` (dynamic). `eventType`, `uuid`, `displayMessage` and `timestamp`
  (a datetime) are plain. A query only returns the columns it names.

## K1 — How does the subject authenticate?

The first question on any Okta sign-in ticket is **which path each attempt took**. The
attempt's IPs, countries and counts come second. Run both:

- `assets/queries/okta_auth_paths.kql` — 30 days of the subject's authentication events,
  counted by path, event and outcome.
- `assets/queries/okta_auth_events.kql` — the same events one per row, the incident ±24h
  (`{WFROM}`/`{WTO}`, the end clamped by K6), with the request path, the relay and the
  session id.

Read the `Path` column:

| Path | What it is |
|---|---|
| `legacy: WS-Trust active` (`…/sso/wsfed/active`) | Microsoft 365 **legacy / basic authentication** relayed by Microsoft to Okta: a mail client, script or scanner sending a password, with no browser and no Okta sign-in page. `relays` reads `microsoft corporation`; the client's own address is `client.ipAddress`. |
| `legacy: rich client` (`auth_via_richclient`) | The same class, recorded as a rich-client authentication. |
| `primary: authn API` / `primary: Identity Engine` | The Okta sign-in page or its API: a person (or a bot) at the Okta login. |
| `browser SSO: SAML` / `WS-Fed` / `OAuth / OIDC` | Single sign-on into an app from an existing Okta session. |

**The pattern that settles most failed-login tickets:** failures on a legacy path, with
no user agent (`noUA` equal to `events`), each from a different residential or mobile
address (`ips` close to `events`), while every success is browser SSO or the authn API
with MFA. That is a password spray against legacy authentication. It
explains the lockouts (Okta locks after N failures and unlocks itself after the lockout
period, so they recur), and it decides the recommendation: see "Recommendation" below.

## K2 — Did any of it succeed?

- `assets/queries/okta_attacker_ips.kql` — with `{IPS}` = the failing addresses from
  `okta_auth_events`, every event from them, tenant-wide, counted by actor and outcome.
  The compromise question is answered by the `SUCCESS` rows: zero, and the `FAILURE` rows
  in the same result are the control. A success from an attacking address is the finding
  this workflow exists for. Stop and report it before anything else.
- `assets/queries/okta_legacy_success.kql` — every account that got a **correct
  password** through on the legacy path, tenant-wide, and whether an Okta app sign-on
  rule then refused the app (`denied`). Read its header for the three readings. The one
  that is easy to misread: `successes` and `denied` both 1 means the password was right
  and a rule stopped the sign-in afterwards. That is **a valid password in someone
  else's hands**, a finding to report and a credential to reset, even though nothing got
  in. It also shows the tenant already has a rule that refuses legacy access, which
  changes the recommendation (below). A success with nothing denied, from an address K5
  cannot resolve, is a compromise indicator. From an address K5 resolves, it is a real
  legacy client that a block would break.

Also read `okta_auth_paths` for the subject's legacy rows: `result = SUCCESS` there is
the same question from the subject's side.

## K3 — Is the subject the only target?

A spray rotates its addresses, so "none of these IPs touched another account" is what
a campaign looks like, not proof of targeting. Search for the **signature**, not the
addresses:

- `assets/queries/okta_spray_census.kql` — failed legacy / no-user-agent sign-ins per
  account, tenant-wide, with attempts, addresses, countries, lockouts, first and last seen.
- `assets/queries/okta_shared_ips.kql` — addresses whose failures hit more than one
  account. Shared addresses make the accounts one campaign with one fix.

Read `ips` against `attempts` for each account. When they are nearly equal, a new
address for almost every attempt, that is a spray. Many attempts from a handful of
addresses is more often the user's own phone or mail client retrying an old password. Check those addresses with
`okta_ip_users` before counting that account as a target.

A ±24h window around the ticket is too short for this. The census is 30 days on
purpose: inside ±24h the subject can look uniquely targeted while the same signature
has been hitting other accounts for weeks. List every account the census
finds, with its first-seen date, in the closure.

## K4 — What changed on the account?

- `assets/queries/okta_account_changes.kql` — lockouts, unlocks, password, factor,
  privilege and lifecycle events by the subject or on the subject, 30 days. Read the
  `Direction` column. `on subject` and `self` rows are what happened **to** the account.
  `by subject` rows are what it did to others, which is most of them for an admin or
  help-desk account and is ordinary work. `detail` names a role or group where the
  target is one: `user.account.privilege.grant` with "Target assigned to Group Role"
  means the account holds **Okta** admin rights through a group, which is worth stating
  next to any directory role. Who unlocked matters:
  `system@okta.com` is the lockout period expiring, while a person is a help-desk action
  worth confirming. A successful takeover usually leaves a factor enrolment or a password
  reset here.
- `assets/queries/okta_change_types.kql` — the control: the same event families
  tenant-wide. An empty `okta_account_changes` is a negative only when this returns rows.

For a Microsoft 365 tenant, also read the subject's directory roles (`office365User`,
`roles` and `userRegistration.*`, or `get_azure_user_record`). A standing administrator
role on the targeted account raises the stakes and belongs in the closure, whatever the
verdict.

## K5 — What do the real sign-ins look like?

- `assets/queries/okta_success_profile.kql` — the subject's successful sessions over 30
  days by address: sessions, how many passed MFA, browser, network, place.
- `assets/queries/okta_ip_users.kql` — with `{IPS}` = the addresses from the profile,
  how many *other* people sign in from each. An address dozens of colleagues use is the
  organisation's office or VPN egress, even in a country the ticket flags as new. An
  address only the subject uses is a question for the user.

A shared team or admin mailbox shows several people in several countries here. That is a
fact about the account, not an intrusion. Say so, and move the risk to K4's role check.

## K6 — Prove what did not happen, up to where the data reaches

- `assets/queries/okta_freshness.kql` — the newest Okta event the tenant holds. **Every
  negative holds only up to `latest`.** A window that ends after the time of the run
  (the incident +24h, for a fresh ticket) is not evidence of silence past `latest`. Clamp
  `{WTO}` to the run's own time and state the real end in the closure.
- Pair each zero with its control, as step 4 requires: K2's `SUCCESS` rows with its
  `FAILURE` rows, K4's changes with `okta_change_types`, K1's legacy successes with the
  legacy failures in the same result.

## Recommendation

The path decides it:

- **Legacy-path spray:** Okta checks each attempt's password **before** any Okta app
  sign-on rule runs. That is why the lockouts happen. A rule that denies legacy clients
  on the Office 365 app stops a guessed password from being *used*. It does not stop the
  guessing or the lockouts, and `okta_legacy_success` may show the tenant already has one
  (`denied` > 0). Recommend the layers in this order, and say which ones the evidence
  shows are already in place:
  1. **Stop the attempts reaching Okta.** They are relayed by Microsoft, so turn off the
     legacy / basic-authentication protocols on the Microsoft 365 side (Exchange Online
     authentication policies, SMTP AUTH wherever it is not needed) and block legacy
     authentication clients with Entra Conditional Access. Name what the tenant must
     check first: which relying endpoint still accepts basic authentication.
  2. **Stop the lockouts.** Okta ThreatInsight in log-and-enforce mode blocks
     pre-authentication requests from addresses Okta has seen attacking. Where the Okta
     edition offers it, lockout protection for sign-in attempts from unknown devices keeps
     a spray from locking real users out.
  3. **Stop the access.** An Okta app sign-on rule on the Office 365 app that denies
     non-modern-authentication clients ("Other clients"), if `denied` shows none yet.
  Report `okta_legacy_success` first: accounts with a working legacy sign-in and no deny
  must move to modern authentication before any of this, or it breaks them. **Do not
  recommend IP blocking** when `ips` is close to `attempts`: every attempt uses a new
  address, so a list cannot keep up. Do not promise that any single layer "stops the
  attack". Say what each one stops.
- **Primary-path failures** (the Okta sign-in page, a real user agent): a typo, a stale
  saved password or a bot at the login page. The session-level evidence (K5) and the
  address census decide which. Okta's own rate limits and ThreatInsight are the controls
  to name.
- **Any attacker success** (K2): an incident, not a tuning question. Session revocation,
  a credential reset and a factor review come first, and the closure says so in its
  first line.

A lockout rule that fired correctly on a real spray is not a false positive: don't
propose suppressing it. The K3 census stays inside `ACCOUNT` like every other query
(SKILL.md "Hard rule"); "other accounts" there means other users of the same tenant.
