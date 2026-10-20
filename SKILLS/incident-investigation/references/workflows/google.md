# Google Workspace workflow (incident-investigation, step 3)

Run this when the ticket's `behaviorRules` start with `GoogleWorkspace_` (see the routing
table in SKILL.md step 3): a Google sign-in, a login verification, a risky-action or
challenge event, an OAuth grant. It is six checks, W1–W6, usually run in this order;
each result goes into the step-5 closure with the table it came from.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled past Google tickets, in a sensible order. Add checks or reorder them when
> the evidence points elsewhere. Skip one only when it cannot apply to this ticket (say
> which and why in the closure); a check that applies runs its bundled queries before
> any of your own (non-negotiable 4).

Every query below lives in `assets/queries/` (`gw_*.kql`), uses the placeholders listed
in SKILL.md "Assets" (`{USER}` is the lower-cased primary email, `{IPS}` a quoted,
comma-separated list), and is run with `validate_kql` then `kql_search` on `ACCOUNT`
only. The column reference is the **`ingext-kql`** skill's `references/schemas/GSuite/info.yaml`
(nested envelope: `actor.email`, `ipAddress`, `id.applicationName`, `event.name`,
`event.parameters.*`); its six traps apply here.

Tables used: `GSuite` (the Reports API audit stream; time column `timestamp`) and the
`gsuiteUser` inventory. Check they exist with `list_data_tables` first.

**On an account that also has Microsoft 365**, the same person may have both
identities. Run the Office365 workflow too when the ticket also carries `O365_` rules,
and keep the two sets of findings apart in the closure.

## W0 — Which Google reports does this account collect?

Run `gw_app_census.kql` once, first. It counts events per Reports API application
(`login`, `token`, `drive`, `mobile`, `admin`, `user_accounts`, `gmail`, …) across the
account. It is the control for every negative below:

- An application **absent from the census** is a gap. Most often missing is **`gmail`**:
  without it, mail forwarding, filters and delegation cannot be checked at all, and the
  closure says so instead of "no forwarding".
- An application present on the account but empty for the subject is a real zero.

## W1 — Who is the subject?

The profile comes from **`ingext-get-profile`** (step 1), whose `gsuite_user.kql` reads
`gsuiteUser`: title (`organizations[].title`), `isAdmin` / `isDelegatedAdmin`,
`isEnrolledIn2Sv`, `orgUnitPath`, `suspended`, `creationTime`, `lastLoginTime`.

- **The columns are camelCase** (`primaryEmail`, not `PrimaryEmail`). A filter on a
  column that does not exist returns a result with **`Columns: []`**, which reads like an
  unreadable table and is not one. If you improvise the lookup, run the sub-skill's
  readability probe before writing "gsuiteUser is unreadable" anywhere, including in an
  account note.
- **A Google-only user has no Microsoft identity to find.** On a mixed tenant,
  `get_azure_user_record` reporting "not found" proves nothing by itself: it needs an
  `Office365ResourceWatch` integration (`list_integrations`), and without one it says
  "not found" for every user. The evidence that a user has no Microsoft 365 account is a
  zero-row Office365 scan for them next to a populated table.

## W2 — Is the address really new?

The ticket's ML geo risks (`NewCity`, `NewISP`, `NewCountry`, `ML_NEW_GEO_*`) are learned
from the user's **login** events only. Google sign-ins are rare — one session lasts days
and a reauthentication often carries method `none` — while OAuth token traffic
(`id.applicationName == "token"`) flows from every network the user's devices sit on. So
an address can be "first seen" for logins while it has carried the user's apps for weeks.

1. `gw_address_census.kql` — every address the subject used in 30 days, with `events`,
   `logins`, first and last seen and which reports it appeared in. **Read `logins` and
   `events` together.** `logins: 1, events: 60, first: three weeks ago` is the subject's
   own network at its first interactive login.
2. `gw_ip_users.kql` on the ticket's addresses — who else used them. Many users is the
   organisation's network; one user is that user's home or site, or an attacker: W3
   decides which.

| Shape | Reading |
|---|---|
| Many users, every day | Company egress |
| Only the subject, weeks of token events before the ticket | The subject's own home or site, first login from it |
| Only the subject, first event of any kind at the ticket | Keep going: W3 decides |
| Other users first seen on the same day | A network change, or a shared event or site |

The address's GeoIP is a hypothesis. A business-line ISP (`connectionType: Corporate`,
`userType: business`) in a city the company has no office in is a client site, a
co-working space or a VPN; say which you can show, and label the rest unverified.

## W3 — Which device and which factor approved it?

The fact that decides a Google sign-in ticket, and the summary carries neither part.

- `gw_login_detail.kql` — the subject's login, SAML, DLP, account and admin events, 30
  days, raw and deduped. On the ticket's `login_success` and `login_verification` rows
  read `event.parameters` whole:
  - `login_challenge_method`: `["password","device_prompt"]` is a password plus a Google
    prompt on an enrolled phone. A repeated `"password"` is one mistyped password, not a
    guessing run.
  - `login_challenge_status: passed` with `is_second_factor: true` is the second factor
    succeeding.
  - `login_type: reauth` with method `["none"]` refreshes an existing session.
  - `is_suspicious` is Google's own risk flag.
- `gw_devices.kql` — the subject's managed devices (mobile report `DEVICE_SYNC_EVENT`).
  **A device that synced in the same second as the flagged login, with weeks of history
  under the same `DEVICE_ID`, is the subject's own machine.** That plus a passed device
  prompt is the strongest benign evidence this ticket type has: an attacker would need
  both the laptop and the phone. A `DEVICE_ID` first seen at the ticket is a new device —
  find who enrolled it.

## W4 — What did the session do next?

- `gw_token_grants.kql` — every OAuth app the subject authorised or revoked in 30 days.
  An app **first authorised minutes after the flagged login** is the follow-on to read.
  Pull that one `authorize` event (`lake_search` on the GSuite index, or a narrow
  `kql_search`) for its full scope list:
  - `openid`, `userinfo.email`, `userinfo.profile` only: a "Sign in with Google" to a web
    app. It gives the app the user's identity, not their mail or files.
  - `gmail.*`, `https://mail.google.com/`, `drive*`, `admin.directory.*`,
    `calendar.events`: the app reads or writes that data. Name the app, its `client_id`,
    and whether anyone else on the account uses it.
- The activity after the login, by report: Drive views, downloads and sharing changes;
  chat; DLP `rules` hits (`message_send_warned` names the policy, not the content).
  The `ingext-kql` GSuite queries (`gsuite-user-activity-timeline`,
  `gsuite-drive-mass-access`, `gsuite-drive-external-sharing`) cover these when the
  ticket needs more than counts.

## W5 — Prove what did not happen

Each zero paired with its control from W0:

- `gw_admin_on_subject.kql` — admin-console and account-security events by or on the
  subject: password changes and resets, 2-Step Verification changes, role and OU moves,
  suspensions, data transfers. Control: `admin` and `user_accounts` counts in W0, or the
  same query on the account's known Google admin (rows prove it can return some).
- OAuth grants (W4): no new app with data scopes after the login.
- Mail-side persistence: only with a `gmail` application in W0. Without it, write
  "not verified — the account does not collect Gmail audit events".
- Sharing: no new external shares or ownership transfers in Drive after the login, when
  `drive` is collected.

## W6 — Score, base rate and side findings

- **The base rate is usually large.** `GoogleWorkspace_Login_login_verification` fires on
  every 2-Step Verification device prompt, so it fires for a good share of the account's
  users each week; the ticket's question is the ML geo terms, not the rule. Count the
  rule's distinct keys over 7 days (step 2) and say so.
- **Read the score as novelty.** On these tickets the alert term is usually
  `ALERT_SEVERITY_LOW` (100); the rest is first-seen geo, which W2 has already tested.
  A tuning proposal follows SKILL.md step 5: masking the ML geo risk is the lever that
  reaches the score, and only if W2's census shows the login-only baseline is what
  manufactures it.
- Admin actions by the account's Google administrators that W5's control surfaced
  (suspensions, data transfers, API client grants) are side findings: record them
  separately and do not let them change this ticket's verdict.

| What W1–W5 show | Verdict |
|---|---|
| The subject's own device synced at the login, device prompt passed, an address already carrying the subject's token traffic, no data-scope grant or admin change after | Benign: first interactive login from a known network |
| A new `DEVICE_ID` or a new address with no prior events, but the factor passed and nothing followed | Escalate with one question: did the user sign in from <place> on <device>? |
| A new address and device, a passed factor, then a data-scope grant, a forwarding or sharing change, or an admin change on the account | Confirmed: contain (sign out all sessions, reset the password, revoke the app's token, review 2-Step Verification methods), then trace what the grant read |
