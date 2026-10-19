---
name: ingext-log-analytics-evidence
version: 1.0.0
description: >-
  The incident-investigation checks that read a customer's own Azure Log Analytics
  workspace, for the few Fluency/Ingext accounts that connect one (an AzureLogAnalytics
  integration). There the workspace, not the datalake, is the evidence: non-interactive
  sign-ins, session capture and replay, Microsoft Graph requests, on-prem password
  resets, post-containment password use, Defender for Endpoint process, PowerShell and
  logon telemetry behind an alert, and who changed an Azure or Arc resource. Nine bundled
  la_ queries run with the azure_logs tools. A dependency of incident-investigation
  (step 0 decides whether it applies). Triggers: "check the customer's Log Analytics for
  this incident", "trace this session id", "what did the stolen token ask Graph for",
  "was the password really changed", "what did this Defender alert fire on", "who
  rebuilt this host in Azure". For free-form workspace queries outside an incident, use
  azure-log-analytics-search.
---

# Incident evidence from a Log Analytics workspace

Most accounts keep their Microsoft data only in the datalake. A few also connect the
customer's own **Azure Log Analytics** workspace through an `AzureLogAnalytics`
integration, reached with the `azure_logs_*` tools. On those accounts the workspace is
the authoritative source for every question below, and the datalake copy is partial.

This skill is the workspace half of **incident-investigation**. It does not stand
alone: the incident's account, ticket, base rate and verdict come from that skill, and
its rules all apply here — one account (`ACCOUNT`) on every call, no zero without a
control, bundled queries run unmodified before your own, every query bounded to 30 days
and 1,000 rows. For the KQL dialect and the tools themselves, see
**azure-log-analytics-search**.

## Does this account have a workspace?

incident-investigation step 0 asks once, on every account:

```json
azure_logs_list_tables { "account": "<ACCOUNT>", "filter": "signin" }
```

- **An error saying no AzureLogAnalytics integration is configured**: this skill does
  not apply. The datalake is the only source; say so once in the closure.
- **A listing**: the workspace exists. Get the schemas you will need in one call, then
  use this skill for every check in the tables below:

```json
azure_logs_list_tables { "filter": "Device" }
azure_logs_get_schema  { "tables": ["SigninLogs", "AADNonInteractiveUserSignInLogs",
  "MicrosoftGraphActivityLogs", "AuditLogs", "IdentityDirectoryEvents", "CloudAppEvents",
  "EmailEvents", "UrlClickEvents", "DeviceProcessEvents", "DeviceEvents",
  "DeviceLogonEvents", "AlertEvidence", "AzureActivity"] }
```

A table in `notFound` is a gap for the checks that need it, never a negative.

## Why the workspace wins

- **Where the workspace has a table, it is the source for that question.** In the case
  that taught this, the datalake's `AzureSigninLogs` held 9 of the subject's ~20
  sign-ins in the hour that mattered, and none of the non-interactive ones. The session
  capture, the attacker's Graph directory dump and the on-prem password reset were all
  in the workspace and in none of the datalake tables. An investigation built on the
  datalake alone called the incident "contained" while the attacker still held a valid
  password.
- **What only the workspace has:** non-interactive sign-ins
  (`AADNonInteractiveUserSignInLogs`, where a replayed token shows up), Microsoft Graph
  requests (`MicrosoftGraphActivityLogs`), on-prem AD changes on a synced account
  (`IdentityDirectoryEvents`, Defender for Identity), and Defender XDR's own email,
  click and cloud-app tables.
- **On an endpoint ticket, the workspace is the telemetry.** The datalake's Defender
  index carries the *alert*; the workspace carries what the device *did*:
  `DeviceProcessEvents`, `DeviceEvents` (PowerShell content, AMSI, WMI),
  `DeviceLogonEvents`, `DeviceNetworkEvents`. A Defender **custom detection's** alert
  lists only the machine as evidence — no account, process or command — and its query
  lives in the customer's Defender portal, out of reach. An AI assist that read only the
  alert closed one as "no supporting telemetry" while every process, script line and
  logon behind it sat in the workspace.
- **Who changed a host's Azure side** — an Azure VM, an Arc-connected server or cluster
  node — is in `AzureActivity`.

## Running the queries

Every query is in `assets/queries/`. Substitute the placeholders, run
`azure_logs_validate`, then `azure_logs_search` — never `kql_search`; this is Azure's
own KQL, forwarded verbatim.

- **The time range is ANDed with the query's own filter, and the narrower wins.** With
  no `rangeFrom`/`rangeTo` the tool applies the last 24 hours, so a 30-day query
  silently returns one day. Pass the range each query's header asks for (`rangeFrom` =
  now − 30 days for the 30-day ones).
- **`first` and `last` are reserved words.** Name aggregates `t0`/`t1`.
- **Unioning `SigninLogs` and `AADNonInteractiveUserSignInLogs`:** `DeviceDetail` and
  `LocationDetails` have different types in each table. `parse_json(tostring(...))`
  them, as the bundled queries do; projecting them raw fails the union.
- **`SigninLogs` re-emits a row each time its risk state changes** — same `Id` and
  `CreatedDateTime`, new `TimeGenerated`, up to a day or more later. One attempt can
  become eight rows, which reads as eight attempts, or as an attempt *after* a reset.
  Count distinct `Id`, and order a timeline on `CreatedDateTime`, never `TimeGenerated`.
- **A result code is not an outcome.** A capture row can end in a failure code (e.g.
  `90014` after "MFA completed") and still have minted a session that is replayed the
  next day. Never close a session alert on the sign-in's result; trace the `SessionId`.

### Placeholders

`{USER}` (lower-cased UPN), `{WFROM}`/`{WTO}` (the incident time ±24h, ISO-8601 UTC;
`{WTO}` never later than the run), `{HOST}` (the host as the alert spells it; prefix
match, any case), `{T0}` (for `la_device_trigger`: the Defender alert's
`firstActivityDateTime`), `{SESSION}` (an Entra `SessionId`), `{OID}` (the subject's
Entra object id), `{TCONTAIN}` (the containment time as ISO-8601 UTC: the first session
revocation or password reset `la_password_events` finds), `{AZRES}` (an Azure resource
id from the alert's device evidence, `vmMetadata.resourceId` or
`azureResourceEvidence.resourceId`).

## Sign-in, session and credential checks (Office365 workflow)

These replace or extend the datalake checks in incident-investigation's
`references/workflows/office365.md`. Directory changes still come from `AzureAuditLogs`
(or the workspace's `AuditLogs`; they hold the same Entra audit). The Exchange checks
(`bec_sweep`, `activity_profile`) still run on the datalake's `Office365`.

| Check (office365.md step) | Datalake query | Workspace query |
|---|---|---|
| 30-day sign-in profile (3a) | `signin_summary.kql` | `la_signin_summary.kql`, interactive and non-interactive |
| Sign-ins around the incident (3a) | `signin_detail.kql` | `la_signin_detail.kql`, with `SessionId` and each authentication step |
| Where a session came from and where it went (3a′) | — | `la_session_trace.kql` |
| Graph requests the subject's tokens made (3c) | — | `la_graph_activity.kql` |
| Was the password actually changed (3c) | — | `la_password_events.kql` |
| Did anyone get the password right after containment (3c) | — | `la_post_containment.kql` |

### Trace the session (3a′)

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

### Is it contained? (3c)

A revoked session is not a changed password. Run `la_password_events.kql` and
`la_post_containment.kql` whenever the ticket is a credential or session theft and the
customer has responded:

- A session revocation (`Update StsRefreshTokenValidFrom Timestamp`, "Revoke Session
  Tokens") ends tokens. It does **not** change the password, and Microsoft's own risk
  remediation for a token-theft risk revokes sessions only.
- On a synced (hybrid) account an on-prem reset is logged only in
  `IdentityDirectoryEvents` (or the domain controllers' Security log — office365.md 3c
  covers that path), never in Entra `AuditLogs`. An "Account Password changed" followed
  seconds later by "Account Password expired" is a reset with "must change at next
  logon", and unless the tenant enabled `UserForcePasswordChangeOnLogonEnabled`, that
  password is **not synced**: Entra keeps the old one.
- Any row in `la_post_containment.kql` from an address or user agent that is not the
  user's is an attacker who still has the password, stopped only by the second factor.
  The closure says **not contained**, and the first recommendation is a password change
  that is confirmed by an Entra password event.

### What did the stolen tokens ask Graph for? (3c)

`la_graph_activity.kql` lists every request. A directory dump (`GET /users?$top=999`), a
`$search` for payroll, finance or HR staff, or a scripted client (`axios`,
`python-requests`) is reconnaissance for the next attack, and the people it found are
who to warn. Graph does not log response bodies: report the bytes, and if you
reconstruct who matched a search from the directory, label it a reconstruction.

## Endpoint and Azure-resource checks (generic workflow)

These extend incident-investigation's `references/workflows/generic.md` for a
Defender for Endpoint alert, or any `asset_…` ticket on a host the workspace covers.

| Check (generic.md step) | Workspace query |
|---|---|
| What the alert fired on (G1) | `la_device_trigger.kql` |
| Who made the change on the Azure side (G4) | `la_azure_activity.kql`, then the caller's `la_signin_summary.kql` |
| Who logged on to the host, from where (G5) | `la_device_logons.kql` |

### What the alert fired on (G1)

Run `la_device_trigger.kql` with `{T0}` = the alert's `firstActivityDateTime`. On an MDE
alert that value is the `Timestamp` of the triggering event to the 100 ns, so the row
with `AtT0 = true` is the event that fired, and the rows before it are the run-up — the
session, parent and script it belonged to. PowerShell content is in `Command`
(`PowerShellCommand` rows). The window is 30 s before `{T0}` to 10 s after; widen to
60 s only if the run-up is cut off, since a busy host fills the result cap.

Also read `firstSeenDateTime` in the alert's device evidence. A device first seen
minutes before the alert is being built, rebuilt or onboarded: a reimaged machine gets
a new Defender device id, so `ML_NEW_ASSET` fires on a host that has existed for months.
The same rule firing on every sibling (`<cluster>host01…04`) within a minute is one
operation, not four intrusions.

### Who made the change (G4)

Activity by `SYSTEM`, a service account or a deployment account was started by someone.

- **Azure side.** When the device evidence carries an Azure resource id, run
  `la_azure_activity.kql` with `{AZRES}`. It lists every create, delete, register and
  deploy in that resource group ±24h by `Caller`. A UPN is a person; a GUID is a service
  principal, usually a resource provider acting on a person's request. A
  delete-then-recreate of the same resources is a rebuild, which also explains a "new"
  device.
- **The person.** Run `la_signin_summary.kql` for that caller: MFA, risk level and
  source addresses. An Azure CLI sign-in from the host's own `lastExternalIpAddress` is
  someone at that site.
- **On-prem side.** `IdentityDirectoryEvents` shows the domain join (computer-account
  password changes by the deployment account) and new computer or cluster objects.

### Who logged on, and from where (G5)

`la_device_logons.kql` gives every logon to the host ±24h by account, type, result and
source. A remote session from anything other than the host's own neighbours (cluster
nodes, management servers) is the lead, and the absence of one is the negative — its
control is the neighbours' own rows in the same result. NTLM failures for a domain
account before a host's domain join are expected.

## What goes in the closure

Label every finding from here with its workspace table (`DeviceEvents`,
`AADNonInteractiveUserSignInLogs`, …) so a reader can tell it from a datalake finding.
Name each check that could not run — a missing table, a query that failed twice under
load — as a gap. Where the datalake and the workspace disagree, the workspace number is
the one in the closure, and the disagreement is worth one line: it tells the next
investigator the datalake copy is partial on this account.
