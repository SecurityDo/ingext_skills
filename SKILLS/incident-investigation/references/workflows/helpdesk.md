# Helpdesk-impersonation workflow (incident-investigation, step 3)

Run this when the ticket belongs to the **fake IT helpdesk** family: an attacker
contacts an employee over Microsoft Teams from an outside tenant, often after
flooding the employee's mailbox, gets them on a call, and has them open a link, start
a remote-support session or run an installer. The routing table in SKILL.md step 3
sends these tickets here. They usually also match the Office365 workflow, so run that
as well and keep the findings apart.

> **Guidance, not a script — but every check that applies runs.** These are the checks
> that settled real tickets of this type, in a sensible order. Add checks or reorder
> them when the evidence points elsewhere. Skip one only when it cannot apply to this
> ticket (say which and why in the closure); a check that applies runs its bundled
> queries before any of your own (non-negotiable 4).

Tables and indexes used: `Office365` (Teams, `TIMailData`, `Endpoint`), `AzureAuditLogs`,
the Defender index through `lake_search` (`@eventType: MSDefenderAlert`), and where the
tenant has them `WindowsAudit` and the SentinelOne index. Check they exist with
`list_data_tables` / `lake_search_list_index` first, and record a missing source as a
gap.

## H0 — In this family, clean sign-ins clear nothing

The rest of this skill guards against confirming a compromise that is not there. This
family fails the other way, and the AI assist has closed real intrusions on it:

- **The attacker never needs to sign in.** They work through the employee's own computer
  and session while the employee is on the call. The employee's sign-ins stay on the
  usual addresses, MFA is untouched and no mailbox rule appears. "Normal, US-only
  sign-ins, no directory changes" is the expected picture of a **successful** attack,
  not evidence against one.
- **The alert logic is Microsoft's, and it is specific.** These titles name the attack
  step itself. "False Positive — incorrect alert logic" is never the verdict for them;
  the question is only whether the employee engaged.
- **Weak evidence in the summary is not weak evidence.** The behavior summary carries
  the title, not the chat, the call or the device timeline. Read those sources (H1–H5)
  before judging.

Treat a ticket as this family when its `behaviorRules` include any of:

| Rule / Defender title | Step it marks |
|---|---|
| `MSDefender:Mail_bombing_activity_detected` | the inbox flood that sets up the "helpdesk" call |
| `MSDefender:Potentially_malicious_IT_support_Teams_impersonation_post_mail_bombing` | the outside "IT" contact after a flood |
| `MSDefender:Microsoft_Teams_chat_initiated_by_a_suspicious_external_user`, `MSDefender:Possible_Teams_phishing_activity`, `MSDefender:Teams_call_reported_by_user_as_security_risk` | the Teams contact, or a link from it opened on a device |
| `O365_Teams_OnMicrosoft_Tenant_Chat` | an inbound chat from a `*.onmicrosoft.com` tenant (keyed on the outside sender; the employee is in `Members`) |
| `O365_Endpoint_Download_From_Azure_CloudApp` | an installer or script downloaded from a `*.cloudapp.azure.com` host |
| `MSDefender:Compromised_account_conducting_hands-on-keyboard_attack`, `MSDefender:Potential_human-operated_malicious_activity`, `MSDefender:Possible_initial_access_from_an_emerging_threat` | someone operating the device or account by hand; on a user who had an outside Teams contact the same day, this is the intrusion itself |

A Defender endpoint ticket (hands-on-keyboard, human-operated) on a user also comes here
whenever H1 finds an outside Teams contact in the 24 hours before it.

## H1 — The Teams contact: who, from where, and did the employee engage

Run `assets/queries/teams_external_contact.kql` for the employee (`{UPN}`), then
`assets/queries/teams_external_census.kql` for the tenant.

- **Read each outside sender.** `user` / `members` on a `*.onmicrosoft.com` address is a
  tenant that never added a domain, which is the throwaway shape: names like
  `<it-sounding-words>.onmicrosoft.com`, or a lookalike of the customer's own name. A
  long-standing partner on a default domain shows steady contact over weeks in the
  census; a wave reaches several users within hours.
- **Engagement decides the ticket.** In order of weight:
  - `CallParticipantDetail` with the employee in `attendees`: a call was answered.
    `JoinTime` / `LeaveTime` give its length; `Device` is the employee's hardware.
  - `MemberAdded` with the employee: the chat was accepted.
  - `MessageSent` / `MessageCreatedHasLink` by the employee in that thread: they replied.
  - `ChatCreated` alone: contact only.
- **Call records arrive about four hours late.** A ticket raised minutes after the chat
  has no call rows yet. Re-run before calling "no call answered" a negative, or record
  it as a gap with the time it can be re-checked.
- **The attacker's own messages carry no URLs here.** The audit log records the outside
  sender's `MessageSent` without its content or links. A lure link appears only on the
  device side (H3).
- **Who else did the same sender reach?** The census row for the sender gives the
  number of this tenant's users in its chats. Every one of them is a contact to list in
  the closure, prioritised by engagement.

Ordinary phone (PSTN) calls also come back from the contact query: their caller is a
phone number and `resTenant` is all zeros. They are not outside tenants. Both queries
scan 30 days of Teams audit and took about four minutes on a busy tenant; run them one
at a time.

Control: the census returns the tenant's legitimate cross-tenant chats too. If it is
empty, check the tenant has any `Workload == "MicrosoftTeams"` rows before calling the
contact absent.

## H2 — Mail bombing before the contact

Run `assets/queries/mail_bomb_hourly.kql` for the employee.

- **The shape.** One or two hours with 50 to 150 flagged inbound messages from as many
  senders, mostly newsletter and mailing-list confirmations in several languages, then
  the outside Teams chat 30 to 90 minutes later. The employee's normal level is a
  handful a day.
- **It undercounts.** Only messages with a threat verdict reach `TIMailData`. Mail
  stopped by a gateway in front of Microsoft 365 (Proofpoint, Mimecast) never reaches
  it, and Proofpoint TAP logs threats, not bulk. A tenant behind a gateway can show no
  flood here while one happened; say so in the closure.
- **Security-awareness simulations are not attacks.** `simSender` counts KnowBe4-style
  senders (`psm.knowbe4.com` and similar). A spike that is mostly simulation is the
  customer's own phishing test.
- **No flood is not exculpatory.** Waves that go straight to Teams skip it. A missing
  flood lowers nothing in H3–H5.

## H3 — What happened on the employee's device during and after the call

Set the window from 30 minutes before the first outside contact to two hours after the
call's `LeaveTime`.

1. **Endpoint records.** Run `assets/queries/endpoint_activity_window.kql`. A
   `FileDownloadedFromBrowser` of an installer, script or archive while the call was
   live decides the ticket. Delivery hosts seen in this family: `*.cloudapp.azure.com`,
   `*.blob.core.windows.net`, `*.s3.*.amazonaws.com`; file names are random letters.
   Then run `file_download_origin.kql` on the hash to see who else downloaded it.
2. **Defender alert evidence on the device.** Pull every `MSDefenderAlert` on the
   employee and their device in the window with `lake_search` on the Defender index, and
   read `evidence[]` — not the summary. `processEvidence.processCommandLine` holds what
   the summary never shows: for example `msedge.exe … microsoft-edge:///?url=https%3a%2f%2f<bucket>.s3.us-east-1.amazonaws.com%2findex.html%3f<employee>%40<domain>&source=teams`
   (a lure page opened from the Teams link, personalised with the employee's address),
   then `cmd.exe` started by `explorer.exe` a minute later. A
   `firstActivityDateTime` earlier than the first Teams contact means the review starts
   there, not at the call.
3. **Windows event log, where collected.** Query `WindowsAudit` on the host in narrow
   windows (it is slow; one host, hours not days), and read `EventTime` as the host's
   **local** time — compare with UTC before ordering events. Look for:
   - `MsiInstaller` 1040 / 1033: an MSI from `\Users\<user>\Downloads\` installed, with
     random-looking product and manufacturer names.
   - PowerShell 400 (`HostApplication=` in `@message`): a command line that decodes
     Base64 from `$env:` variables, then recon (`InstalledUICulture`,
     `Win32_VideoController`, `SecurityCenter2 AntivirusProduct`,
     `Win32_ComputerSystem.Domain`). That is a loader profiling the machine.
   - 1074 (power off) and the last event the host ever sent: when the employee shut it
     down.
   Process creation (4688) is often not collected; say so rather than calling the
   payload's behaviour clean.
4. **EDR, where collected.** SentinelOne threats on the host in the window (the
   SentinelOne workflow, S1–S5). A ransomware or loader verdict a day later on a host
   that had a screen-shared call is part of this ticket, whatever its own verdict now
   says.

A clean H3 needs controls: the tenant has `Workload == "Endpoint"` rows for this device
in the same week, and the host sent Windows events in the window.

## H4 — Containment: what the customer and Microsoft already did

Read `AzureAuditLogs` for the employee from the first contact onward
(`dir_changes_targeting.kql`, then the detail query on the interesting operations), and
`onprem_password_events.kql` on a hybrid account. Record each with its time and actor:

- `Disable account`, `ConfirmAccountCompromised`, `Update StsRefreshTokenValidFrom
  Timestamp` (sessions revoked), `Reset user password` / `Change user password` (a
  `ConnectSyncProvisioning_*` actor is the on-premises change syncing up),
  `Admin deleted security info` (MFA re-registration required), `Enable account`,
  `Register device` / `Add Windows Hello for Business credential` (the replacement
  laptop).
- Defender's **attack disruption** contains the user automatically; its later alerts
  ("…blocked on multiple devices", "contained user's attempt…") can be the employee's
  **own** work from a new laptop while the containment is still on. Compare the alert
  time with the `Register device` time before calling it lateral movement.
- A device that stopped sending logs right after the call is powered off or isolated.
  Name the last event time; it is not proof the device is clean.

## H5 — The same attacker elsewhere in this tenant

From the H1 census: list every user the same outside sender or tenant reached, with
their engagement level. For each who answered a call, run H3 on their device (at least
the endpoint records and Defender evidence). One successful contact is enough for a
ticket; the closure must still say who else took a call. This stays inside `ACCOUNT`.

## H6 — Verdict for this family

| What the evidence shows | Verdict |
|---|---|
| Something ran or was opened on the device during or after the call (installer, script, lure page, remote-support tool, a command shell started by the user), or Defender saw hands-on-keyboard activity | **Confirmed.** Containment first: device isolated and imaged, account disabled or reset, sessions revoked, MFA re-registered. Say which of these H4 shows already done. |
| A call was answered, or the chat was accepted or replied to, and H3 is clean **with controls** | **Escalate.** The open question is what happened on the call; the employee interview and the device's EDR timeline answer it. |
| A call was answered but H3 could not run (no endpoint data, no Windows events, no EDR) | **Escalate**, with each missing source named as a gap. |
| Contact only: no call answered after the four-hour lag, chat not accepted, no reply, nothing on the device, with controls | **Benign for this employee**, but list the sender and its other contacts (H5), and recommend blocking the tenant. |

Never close this family on sign-in evidence alone, and never as "incorrect alert logic".
A Defender incident still at `New` in the customer's portal is a finding: say so.

## Tuning

- **Do not tune these titles down.** The rule and title above are the attack's own
  steps; volume across a tenant is low. If one sender is a real vendor on a default
  domain, filter that sender (or tenant id) for `O365_Teams_OnMicrosoft_Tenant_Chat`,
  never the title.
- **Recommend the control that ends the family:** a Teams external-access allowlist
  ("Allow only specific external domains") and no chat with unmanaged Teams accounts.
  Blocking attacker domains lags, because each wave uses new tenants.
