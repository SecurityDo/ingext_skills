---
name: incident-investigation
version: 1.2.0
description: >-
  Investigate an escalated Fluency/Ingext behavior incident and close it with a verdict and
  evidence. Use whenever the user hands over a behavior incident, an AI-assist ticket,
  an alert or a risk score and asks what it really is — "investigate this incident", "triage this
  ticket", "is this a true positive", "the AI assist says actionable, check it", "why did this user
  score 3600", "should we escalate this alert". Covers
  pulling the behavior summary and AI-assist verdict from eventwatch, then the four
  checks that decide a verdict — the in-tenant base rate for the rule that fired, resolving
  every source IP against the rest of the tenant, reading which device approved the change, and
  proving what did NOT happen afterwards — plus the timestamp, error-code, user-agent, duplicate-
  row and geolocation traps that manufacture findings. Ends in a closure (benign, escalate or
  confirmed) with tuning, and a Fluency-branded HTML closure report on request. Queries only the
  incident's own tenant account.
---

# Investigate a behavior incident

An incident is a score, and a score is a hypothesis. This skill is the procedure for
testing it.

The failure mode is not missing a compromise — it is confirming one that is not there.
A high-severity rule plus a first-seen ML boost plus an unfamiliar IP reads like an
account takeover, and every one of those three can be the ordinary operation of the
tenant. The checks below are ordered so the cheapest disqualifier runs first: the
base rate has closed more tickets here than everything after it combined.

**Never write a verdict from the summary alone.** The behavior summary tells you what
fired, never whether it matters.

## Hard rule — one incident, one account

**Every call in this investigation targets the incident's own tenant account and no
other.** An MSSP grid connector exposes many customers behind one endpoint, and every
tool takes an `account` argument. That makes a cross-tenant query one keystroke away —
and querying another customer's data to "compare" or "get a base rate" is a
data-segregation breach, however useful the comparison looks. It is never part of this
procedure.

- **Lock the account in step 0 and never change it.** Write it down as `ACCOUNT=<name>`
  and pass exactly that value to every tool call. The only other tenant-scoped call
  allowed is `list_accounts`, once, to confirm the name exists.
- **If the requested account is not found, do not investigate at all.** When
  `list_accounts` on the named connector has no entry matching the account the user
  asked for, stop before any other call. Do not guess a close match, do not try other
  connectors or accounts to locate it, and do not run any search, query or rule call.
  Tell the user the account was not found on that connector and ask them to confirm
  the name or connector.
- **"Base rate", "census", "fleet", "campaign", "how common is this" all mean
  *within this account*.** Other entities in the same tenant, never other tenants.
- **No exceptions for research value.** Not to check whether a vendor rollout hit
  other customers, not to validate a rule, not to compare scores, not "just a count".
  If a verdict would genuinely benefit from cross-tenant context, **stop and ask the
  user** — say what you would query and why — and proceed only on an explicit yes
  naming the accounts. A request that names one account is not permission for others.
- **Other connectors count too.** If the session has several MCP connectors
  (`mcp__<Connector>__*`), use only the one the user named. Same tool name on a
  different connector is a different provider's data.
- **Before every call, check the `account` argument equals `ACCOUNT`.** If a call went
  to the wrong account, stop, discard its result entirely (do not cite it, summarise it
  or let it shape the verdict), and tell the user plainly which account was queried and
  what was run.
- **The closure states the boundary.** End the write-up with one line naming the
  connector and account every finding came from.

## Required inputs

| Argument | Meaning | Example |
|---|---|---|
| target | the connector **and** the single tenant account — the only account this run may touch | `Develop` / `contoso` |
| entity | the key the incident is on — username, asset or IP | `user@corp.com` |
| window | epoch ms; default the last 30 days | `--from 1787246734000` |

If the target account or connector is missing or ambiguous, ask — never pick one, and
never fan out across accounts to find where the entity lives. If the entity is missing,
ask for it. If the window is missing, use 30 days — shorter windows hide the baseline the whole procedure is measured against.

## Step 0 — Point at the right tenant, and prove it

**Prefer the MCP tools.** The platform exposes this investigation as MCP tools on
every tenant's `/mcp` endpoint, and on the provider's grid server. They remove the
whole class of targeting bug described below, return structured JSON instead of a
parsed log, and need no binary installed.

| Need | MCP tool | Replaces |
|---|---|---|
| The incident rows | `behavior_summary_search` | `eventwatch search_summary` |
| The events behind one | `behavior_event_search` | — |
| Query the datalake | `kql_search`, `validate_kql` | `ingext kql` |
| Raw documents | `lake_search` | `ingext datalake search` |
| Which indexes exist | `lake_search_list_index`, `list_data_tables` | `datalake list-index` |
| Who the subject IS | `get_azure_user_record` | — |
| Read a rule | `eventwatch_rule_list`, `eventwatch_rule_get` | `eventwatch rule_list/rule_get` |
| Test a rule | `eventwatch_rule_test` | `eventwatch rule_test` |

**Targeting is per call, so there is nothing to restore — but everything to check.**
On a tenant's own endpoint the account *is* the endpoint. On the grid server every
tool takes an `account` argument; call `list_accounts` once to confirm the target
account's exact name — if it is not in the list, stop here and run nothing (see the
hard rule) — set `ACCOUNT`, and pass that one value to every call for the
rest of the run (see "Hard rule — one incident, one account"). `list_accounts` shows
you the other customers on the connector; that list is for confirming a name, not a
menu of tenants to query.

### If you must use the CLI

`ingext` takes its target from the active profile **only**. The `--cluster` and
`-n/--namespace` flags are accepted and ignored; if you rely on them you will read
another tenant and never be told.

```bash
ingext config list | grep -i <tenant>        # a provider:tenant name is not the profile name
ingext config use <cluster>:acc-<tenant>     # e.g. msp1:contoso -> useast1:acc-contoso
```

**`ingext config use` is a global mutation, not a session-local one.**
`~/.ingext/config.yaml` is shared by every session on the machine, so switching
tenants changes the target for anyone else working at the same time — and *their*
switch changes yours, mid-run, with nothing in the output to say so.

So do not prove the tenant with `config view`. Prove it **per call** and assert it:

```bash
python3 scripts/ingext_json.py kql out.json query.kql --expect <tenant>
python3 scripts/ingext_json.py run summary.json --expect <tenant> -- eventwatch …
```

Both print the site that actually answered and exit non-zero on a mismatch. This
beats reading `config view` before and after, because a flip and flip-back inside
one call passes both reads while the call itself went elsewhere.

**Spend the attribution effort where it buys something.** Datalake reads are
self-attributing: a query that lands on the wrong cluster returns *nothing* rather
than something plausible. The dangerous calls are the **server-side evaluations** —
`eventwatch rule_test`, `processor test` — which execute on whatever profile is
current and return a confident answer with nothing in it naming the cluster.

Attribute those with `-l info`, **not `-l debug`**:

```bash
ingext -l info eventwatch rule_test --content @rule.json --event ev.json 2>&1 \
  | grep -a siteURL
```

**`-l debug` dumps the `Authorization: Bearer` header** into whatever captures the
output. `siteURL` is logged at INFO, so attribution never needs debug.

Two CLI quirks that cost time: `rule_get` writes its JSON to **stderr**, so
`> rule.json` yields an empty file — capture with `2>`. And an unknown
`--gridaccount` name does not error, it silently serves the manager account.

Restore the profile when you finish, and say which tenant you left it on.

## Step 1 — Pull the summary and the AI-assist verdict

```json
behavior_summary_search {
  "searchStr": "\"user@example.com\"",
  "rangeFrom": <ms>, "rangeTo": <ms>, "limit": 30
}
```

The reply carries `total`, the matching `documents` with their stored `_source`, and
— when you ask for them — facet counts over the **whole** match set. Feed the
documents to `summary_digest.py` for the daily history and the AI verdict, or read
them directly.

Three things about this index cost time if you don't know them:

- **`searchStr` is a Lucene query over the summary document, not a key filter.**
  A bare email address is split on `@` and `.` and matches the wrong rows — quote it
  (`"\"user@example.com\""`). Searching one username on a single-domain tenant still
  returns most of the tenant: one search came back with 69 summaries across 40
  user accounts in that one tenant. Filter on `key`, or add `mustFilters: [{"field":"key","terms":[…]}]`.
- **The time filter runs on `from`,** and sorting defaults to `riskScore` descending.
  Sort on `to` for most-recent-first.
- **Neither `from` nor `to` is an event time** — see step 6.

What to take from it:

- the **daily history**. One spike against 26 quiet days is a different animal from a
  score that has been climbing for a week.
- the **risk decomposition**. Decompose it with the formula below rather than reading
  the number as a severity — in every incident triaged so far the ML first-seen term
  has been the dominant one, and the rule's own severity a minority share.
- the **AI-assist verdict** from `comments[]` (`username: "AI-Assistant"`, content is a
  JSON string). Read its `keyQuestions` as a to-do list, not as findings.
- the **`behaviorRules` list** — the names to hand to `eventwatch_rule_get` in step 7.

Use `behavior_event_search` for the individual events behind a summary row; those
carry true `timestamp` values rather than bucket labels.

<details><summary>CLI equivalent</summary>

```bash
python3 scripts/ingext_json.py run summary.json -- \
    eventwatch search_summary --query '<entity>' --from <ms> --to <ms>
python3 scripts/summary_digest.py summary.json <entity> --ai
```

`eventwatch search_summary` prints only a `Key: …, RiskScore: …` line per hit to
stderr and discards the document; the body exists only in the `-l debug` log, which
is why `ingext_json.py` exists.
</details>

### How a riskScore is actually built

A score is not a severity rating. It is a **capped weighted sum times a
dimension-count multiplier** (`fsbv2/risk/risk_enum.go`, `AppendHit` / `SetScore`):

```
contribution = factorScore × scopeMultiplier × appends
    scopeMultiplier   global 4 · local 2 · no scope 1
    appends           the rule-level ALERT risk is appended once per behavior
                      event, capped at 2; ML hits append once each
    caps              exact-duplicate hits dropped; max 2 hits sharing a Name
                      per factor; only the first 8 hits of a factor add score

subtotal = Σ contributions
boost    = 1 dimension → 1 · 2 → 2 · 3 → 4 · 4 → 8      (hardcoded 2.0 per
           dimension, product halved once if > 2.1; not in risk_config.json,
           so not tunable from config)
score    = subtotal × boost
```

Factor scores, from `fsbv2/risk/risk_config.json`:

| Factor | Dimension | Score |
|---|---|---|
| `ALERT_SEVERITY_LOW` | alert | 100 |
| `ALERT_SEVERITY_MEDIUM` | alert | 200 |
| `ALERT_POLICY` | alert | **200** |
| `ALERT_SEVERITY_HIGH` | alert | 400 |
| `ALERT_SEVERITY_CRITICAL` | alert | 600 |
| `ML_NEW_ALERT` / `ML_NEW_USER` / `ML_NEW_ASSET` | machine learning | 500 |

**`ALERT_POLICY` and `ALERT_SEVERITY_MEDIUM` are both 200**, so on the alert
dimension they are indistinguishable when you work backwards from a score alone.
Read the actual risk off the summary rather than inferring it — `ALERT_POLICY` is
the risk on many of the Office365 rules, including `O365_Remove_Service_Principal`
and `O365_Update_Application_Credential`.

Worked: a passkey enrolment day with 6 events scoring 3600 —
`ALERT_SEVERITY_HIGH` 400 × 1 × **2 appends (capped)** = 800, plus `ML_NEW_USER`
500 × 2 (local) × 1 = 1000; subtotal 1800, two dimensions → ×2 → **3600**. A
service-principal removal scoring 8400 — `ALERT_POLICY` 200 × 1, plus two
**global** ML hits at 500 × 4 each; subtotal 4200, ×2 → **8400**.

Three consequences that change what you recommend:

- **The `hits` array in the summary is not the append list.** The two are built by
  separate paths in the same function, and only one of them dedupes: the scoring
  path calls `AppendHitByNames` once per behavior event with no dedupe beyond the
  caps above, while the `hitMap` behind the readable array dedupes by hit name for
  rule-level risks and by value-equality for `RuleHits`. So the array you can read
  is deduplicated and the array that was scored is not. Reconstructing a score from
  `hits` alone under-counts exactly when `count > 1`, and in practice only on the
  alert dimension — ML first-seen hits fire once by construction.
- **Trimming a noisy selector does not lower anyone's score.** Past two events the
  alert term is capped, so 11 genuine events and 2 score identically. Selector work
  buys volume and truthful hit counts, not a lower number.
- **Only masking the ML risk reaches the score**, because it removes its
  contribution *and* collapses the multiplier. Masking the severity zeroes the score
  instead. Use a `RiskFilter` with `riskMask` — it reaches `RuleHits[].Risks` as well
  as the top-level risks.

### Who is the subject? Read the directory record, not the audit log

Before judging what an account did, establish what it **is**. For any Microsoft 365
subject call `get_azure_user_record` with the UPN:

```json
get_azure_user_record { "username": "user@example.com" }
```

It resolves the user through Microsoft Graph and returns `displayName`, `userType`
(Member/Guest), `createdDateTime`, and — the part that decides how you read everything
else — the `roles` map of assigned Azure AD directory roles. A subject with
`Global Administrator` is *expected* to assign licences, reset passwords and manage
group membership; the same actions from an account with no roles are a different
ticket entirely. Run it on the **target** too: a privileged actor touching another
privileged account is worth more than one touching a Member.

**Never infer privilege from the absence of role-assignment events.** Searching the
audit index for `Add member to role.` over the investigation window and finding none
does not mean the subject holds no role — it means the role was granted *before the
window*. Directory roles are usually assigned when an account is created and never
touched again, so a long-standing Global Administrator leaves no role event at all in
a 30-day search. This is the "zero against a large scan" trap pointed at the wrong
question: the audit index answers *what changed*, the directory record answers *what
is*. Only the second one establishes privilege.

Resolve **groups** the same way, and by id rather than name. A summary reports a group
by `displayName`, and display names are not unique: one tenant carried three separate
groups called `Custodial` — a pure security group, a distribution list, and a
security-enabled Microsoft 365 group. The membership events carry
`ModifiedPropertiesFieldsOld.Group_ObjectID`; look that id up in `office365Group` and
read `securityEnabled`:

```
office365Group | where id in ("<guid>") 
| project displayName, id, securityEnabled, mailEnabled, groupTypes, description
```

`securityEnabled: false` is a mailing list, and removing people from it costs them
mail. `securityEnabled: true` gates access, and removing people from it costs them
whatever it grants. Deciding which one a bulk membership change touched is the
difference between a housekeeping note and an access-loss incident — and the group's
name will not tell you.

The record also carries roles the incident never mentions — a compliance or Purview
role alongside Global Administrator changes what data the account could reach, and the
behavior summary will not tell you about it.

## Step 2 — The base rate (run this before anything else)

The single most valuable query in this skill. How many other entities **in this same
tenant account** fired the same rule in the same week? The base rate is always
intra-tenant: run it with `account: ACCOUNT` only. Never measure it by querying other
customers on the connector, even when the suspected cause (a Microsoft rollout, a
vendor release) would plausibly show up there too — that is a cross-tenant query and
is off-limits unless the user explicitly authorises named accounts.

```bash
python3 scripts/ingext_json.py run wave.json -- \
    eventwatch search_summary --query '<BehaviorRuleName>' --from <ms-7d> --to <ms>
python3 scripts/summary_digest.py wave.json --rule <BehaviorRuleName>
```

Then widen it to the underlying directory activity with
`assets/queries/campaign_census.kql`.

More than a handful of distinct entities means the incident is one instance of a
campaign — a rollout, an admin push, a policy change, a vendor release — and the
verdict is about the campaign, not the user. In the worked case: 33 distinct users
fired the rule in seven days, **12 of them raised incidents with the byte-identical
risk signature**, and 55+ users in the tenant registered passkeys across five days. The ticket
was the twelfth copy of one IT project. Nothing downstream could have overturned that,
and everything downstream was cheaper to interpret once it was known.

A base rate of one does not prove an attack. It only means you keep going. When the
entity is a single tenant-wide actor (a service principal, a Microsoft first-party
service), the useful in-tenant base rate is that actor's own 30-day history and the
directory audit around the event — look for a Microsoft-managed initiator such as
`Microsoft Managed Policy Manager` at the same instant — not other tenants.

**Know which side of the emission boundary your number came from.** The dedup that
collapses concurrent events runs at behavior-event *emission*, before the event is
buffered, so a blocked event never reaches a summary at all. The raw index sits
upstream and is untouched by it. Therefore a base rate counted from **summaries can
be collapsed**, and one counted from **raw rows cannot**. You do not need to
cross-check every count — you need to know which kind you are holding. A raw-side
census (the directory audit for an activity class, an object's full history) is
already immune; a `search_summary` count is not.

## Step 3 — Resolve every address against the rest of the tenant

An IP is not suspicious because it is unfamiliar to one user. Run
`assets/queries/ip_census.kql` over every address in the incident, then
`ip_users.kql` on whatever is left.

| Shape | Reading |
|---|---|
| Dozens of users, hundreds of events | Corporate egress / VPN NAT. Not an anomaly, whatever the GeoIP city says. |
| Many users first seen on the same day | A network change — new circuit, new VPN, office move. |
| A handful of users, recent | A site, an event, a travelling group. Corroborate in step 5. |
| Exactly one user, one event | Keep going — but run `ip_prefix_sweep.kql` first. |

`ip_prefix_sweep.kql` is the one that saves you. Before calling a single-user proxy
address attacker infrastructure, check the provider's prefix across the whole tenant.
In the worked case the "unknown Cloudflare IPv6" shared a `/32` with two unrelated
employees on Apple devices through *Apple Internet Accounts* — iCloud Private Relay,
which egresses through Cloudflare. One query turned the strongest-looking indicator
into a consumer privacy feature.

GeoIP is a hypothesis too. Private Relay, VPN and corporate NAT all move the pin, and
a "impossible travel" finding built on an unverified city is manufactured.

## Step 4 — Read the device that approved the change

For any incident about authentication, MFA, passkeys or credentials, this is the fact
that decides it, and **neither the behavior summary nor the sign-in log contains it**.

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

## Step 5 — Prove what did not happen

A benign verdict rests on negatives, and they have to be collected, not assumed.

- `assets/queries/user_registration.kql` — the account as it stands now. The question
  is never only what was added but **what was removed or demoted**: persistence deletes
  or downgrades factors; a rollout adds one alongside the rest. Check `authMethods`,
  the preferred secondary method, `roles`, and `oauth2Applications` for a grant nobody
  recognises.
- `assets/queries/bec_sweep.kql` — 30 days of what an actor does *after* taking an
  account: inbox rules, forwarding, delegated mailbox access, transport rules, OAuth
  consent. Zero hits across all of them is strong evidence and takes one query.
- `assets/queries/activity_profile.kql` — place the incident in the account's real
  work. A mass `FileDownloaded` run after the event is exfiltration; a Teams session
  and three file previews is a Thursday.
- `assets/queries/dir_changes_targeting.kql` — who else changed this account. Read
  `modifiedProperties` for the group's real name before calling a membership add a
  privilege escalation: a licensing group added from `O365AdminPortal` for a
  salesperson is provisioning, and the same query usually explains the geography
  (a Teams group named for an off-site event placed the user in the right city).

## Step 6 — Re-derive every number the ticket asserts

Summaries round, merge and mislabel. Seven traps:

**A zero against a large scan is a predicate bug until proven otherwise.** The result
count and the scan total sit next to each other in every response, and only one of
them answers the question. `total: 24377719` with no result rows does not mean the
index is empty — it means 24M rows were read and the filter matched none of them,
which is far more often a wrong column than an absent fact.

The usual cause is **the time column, which differs per index family**. `Office365`
and the `behavior` index use `timestamp`; `AzureSigninLogs` and `AzureAuditLogs` use
`TimeGenerated`; the static-Parquet FortiGate indexes `NetworkFortigateEvent` and
`NetworkFortigateTraffic` also use `TimeGenerated` and do **not** populate
`timestamp`. Carry a column across families and every query returns a confident zero.
Read the time column from the schema doc for each table — never from the last table
you queried.

**The same trap in a projection: a column that does not exist returns null.** A
`project` over a name the schema lacks yields `null` for every row, indistinguishable
from a field that is genuinely empty — and unlike the zero case the result set is
*populated*, so nothing looks wrong at all. On the FortiGate lockout event, a
projection of `srcip, user, method, logdesc` returned four nulls; two were real and two
were artifacts of `method` and `logdesc` not being promoted columns in that Parquet
schema. The field that actually held the source address, `ui`, was never projected
because nobody thought to ask for it.

Two defences. Read the schema before projecting, or query the nested container
(`_fields`, `@fortigate`) and see the whole object rather than a list of names you
chose in advance. And when a field you expect is null, check whether the column exists
before concluding the data is missing.

**Behavior rules read the event stream, not the lake.** Column promotion is a
lake-schema property, so a field absent from the Parquet index may be perfectly
available to a rule. Validate rule field paths against the raw `default` index, never
against the schema'd one.

Before reporting any absence, prove the query can return something: drop the filter
and count, or run it against a window you know holds data. An absence is a claim, and
it is the one kind of result that looks identical whether it is true or broken.

**A summary's `count` can be lower than the number of real events.** The engine
dedupes behavior events on a key built from `Key`, `KeyType`, `BehaviorRule` **and
every attribute value joined together**; a second event with the same key inside the
interval is blocked. So when a rule's attributes cannot tell two concurrent events
apart, one is silently dropped — not hidden in the summary, never emitted.

The check is cheap because the boundary is sharp: this runs at emission, so **every
count in a summary is suspect and every count from the raw index is not**. Compare
the two for the same window whenever a count carries weight.

This is how one tenant's credential-rule gap was found: the lake held **two**
`Certificates and secrets management` events on 2026-09-05, one per application,
while the summary said `count: 1`. The sibling rule on the same day counted 3 of 3,
because it carried the target as an attribute and the credential rule did not. The
score confirms it independently — 8400 only closes with one append; two would give
8800. Which leads to the rule in step 7: **attributes are not cosmetic.**

Two corollaries. A **base rate of 1 may be a collapse rather than a lone event**, so
verify it against raw counts before concluding anything from it. And a correctness
fix here **raises** scores — restoring the second event adds an alert append, taking
that day from 8400 to 8800. That is a previously hidden event surfacing, not an
escalation, and it will read as a regression to anyone watching score trends.

**Neither summary timestamp is the event time.** `from`/`to` are **2-minute bucket
labels**, not event times: the eventwatch engine buffers on a 2-minute window, and the
document carries the start of the bucket the event fell into. Every `from`/`to` value is
an exact multiple of 120,000 ms — zero seconds, even minute, no exceptions across 210
values checked. So the stamp runs **early** by up to two minutes (03:06:00 for
an event at 03:06:16; 06:54:00 for one at 06:55:15), while `incidentDetectionTime` runs
**late** by minutes (07:05:00 for that same 06:55:15 event), and the AI-assist summary
quotes the late one. Two consequences:

- A correlation window anchored on the summary time can miss the very event the incident
  is about. Widen to the bucket plus a margin, or anchor on the raw index.
- A timeline built from summary times can come out in the **wrong order**. On the
  service-principal removal the event would have been placed at 06:54, ahead of role
  removals that actually preceded it at 06:55:14 — inverting a four-step transaction
  whose sequence was the entire argument.

Rule: use the summary to find *which* events to pull, never to say *when* they happened.

**Error codes are not interchangeable.** Decompose any "N failed logins" with
`assets/queries/login_failures.kql` before calling it a brute force.

| Code | Meaning | Weight |
|---|---|---|
| `50126` | Invalid username or password | The only credential failure |
| `50074` | Strong authentication required | An MFA interrupt inside a normal flow |
| `70044` | Session expired or invalid | A mobile client re-authenticating |
| `502xx` | Interrupts in the strong-auth (SAS) flow | Confirm the specific code; not a guess at a password |

Then check *where* they came from. Five `50126` on the user's own Entra-joined,
compliant, managed laptop from the corporate egress, each followed by success seven
seconds later, is a typo — and it was reported as "6 failed logins followed by a
successful sign-in", which reads like a password spray.

**The user-agent beats the OS label.** Azure's `DeviceDetail.operatingSystem` and the
real `UserAgent` disagree — a device labelled `Ios 26.6.2` whose UA says
`iPhone OS 18_7`. Trust the label and you invent a "new device" that is the user's own
phone. `signin_detail.kql` projects both.

**Rows are duplicated.** The same event comes back two or three times with identical
values; on one 30-day sign-in pull, 224 rows deduped to 175. Any hand count off raw
rows is inflated. `kql_rows.py` dedupes and reports how many it dropped.

**A tenant-wide convention is not an account anomaly.** "UPN/email domain mismatch"
sounds like an indicator until `domain_census.kql` shows 808 of the tenant's users
share it. Any finding phrased as "unusual for this account" gets one census query.

## Step 7 — Write the verdict

Three outcomes, and say which:

- **Benign** — closed, with the disqualifying evidence named.
- **Escalate** — a specific unanswered question, and what would answer it. Never
  "medium likelihood" with no next step.
- **Confirmed** — containment first, write-up second.

The closure carries five things:

1. **The verdict in one sentence**, first, before any evidence.
2. **The incident record** — document id, uuid, window, score, rules, risks.
3. **Flagged → found → source**, one row per thing the ticket raised. Every row cites
   the index or API it came from; a finding with no source is an opinion.
4. **The timeline**, re-derived from the audit log, not from the summary's detection
   time.
5. **Disposition and tuning.** If step 2 found a campaign, the ticket is not closed
   until the rule is tuned — otherwise the same verdict gets written eleven more
   times. But a tuning proposal is a claim like any other, and it gets tested before
   it is handed over. Three questions, in order:

   - **Can the engine express it?** Behavior filters see only the rule's own
     attributes plus `key`/`keyType`/`behavior`. They cannot compare two fields to
     each other, reach a different source, or correlate across events in a window.
     A condition that needs any of those is not a tuning proposal.
   - **Does it discriminate?** Facet the condition over the rule's **own selector**
     before proposing it. A condition that matches every hit is not a filter.
   - **Is the rule over-matching instead?** Count hits per entity per real-world
     action. Several hits per action means the selector is catching the stages of
     one ceremony, and trimming it beats any suppression.

   Worked example of getting this wrong. For the passkey rollout I proposed
   suppressing when the change is self-initiated **and** MFA was satisfied on an
   already-registered device **and** no method was deleted. Measured against the
   tenant, **all 212 hits over 7 days were self-initiated** — zero discriminating
   power, and suppressing on it would have disabled the rule outright. The other two
   clauses were not expressible at all. The real defect was the selector: it matched
   three events per enrolment — "User started security info registration", "User
   registered security info", "User registered all required security info" — so 75%
   of hits were not additions. Excluding the two non-add activities took 212 hits to
   54 with no detection loss. Measure first; a plausible-sounding condition is not
   evidence.

   **Know which lever you are pulling.** Selector work and risk masking do different
   things, and conflating them oversells the fix. Trimming a selector cuts volume and
   makes the hit counts truthful; it does **not** lower anyone's score, because the
   alert term is capped at two appends (see "How a riskScore is actually built").
   Masking the **ML** risk is the only lever that reaches the score — it removes the
   contribution and collapses the dimension multiplier. Masking the severity zeroes
   the score instead. Say which one you are proposing and what it actually buys: on
   the passkey rollout the selector fix cut 212 hits to 54 while every genuine
   enroller kept scoring 3600.

   **Attributes are not cosmetic.** On this engine the dedup key is built from the
   rule's attribute *values*, so an attribute set that cannot distinguish two
   concurrent events causes one of them to be silently dropped. "The summary omits
   the target" and "the rule only fired once" are therefore often the *same defect*,
   and the fix for the first is the fix for the second. When you find a rule whose
   attributes do not identify what it acted on, say so as a detection gap and not as
   a readability complaint — that framing is what gets it prioritised correctly.

   One handover detail: the `ruleID` in a behavior summary is a tenant-side UUID.
   The Scripts repo keys rules on **integer ids**, and those are what its release
   registries and history track. Quote both, or the maintainer cannot find the rule.

   **A relayed claim inherits none of the original's confidence.** When you hand a
   finding to someone who will act on it — a rule maintainer, another team, another
   session — the relay is where an unverified number gets laundered into a fact.
   Attribution is not verification: "the other side measured X" reads as established
   while being exactly as good as X was. Either check it with your own access, or
   label it plainly as unverified and say what would confirm it. Leading with the
   consequence ("something of yours is broken") puts weight on a number nobody has
   re-read, and that weight is what carries it to a person who then acts.

   This happened today in both directions on one finding: an absence reported from a
   mistyped time column, relayed to another team as silent breakage, escalated to a
   human — and caught only when a third party questioned the premise. The fix is
   cheap and it is procedural: verify, or label.

   **Know where a finding stops being yours.** Triage produces two kinds of output:
   things about this rule or this tenant, which belong in the ticket and in a note to
   whoever maintains the rule; and things about how the platform behaves for every
   rule in every tenant — when first-seen boosts, how the dimension multiplier works,
   what the engine buffers. The second kind is a much larger blast radius than any
   ticket, it is a different repo, and nobody asked for it. Write it down, name it as
   an observation, and put it in front of a person. Two agents agreeing that a change
   is a good idea is not authorisation, and the failure mode where each one treats the
   other's agreement as a mandate is how a triage ticket turns into a platform change
   nobody approved.

**Tuning evidence is intra-tenant too.** Facet a proposed filter over this account's
hits only. A claim like "this fires the same way for other customers" is not something
this skill measures; if it matters, say it is unverified and name who could check it.

**Close with the data boundary.** The last line of the closure names the connector and
the single account every finding came from, e.g. "All findings: Develop / contoso
only."

State plainly where you disagree with the AI-assist verdict and why. That workflow
skipped exactly three checks — the base rate, the IP resolution and the approving
device — and each one is a single query.

### Proving a tuning change before you propose it

A verdict that ends "suppress this rule" is a claim about a rule you have probably
not read. Three calls, no CLI:

```
eventwatch_rule_list {"nameContains": "Add_Authentication"}   -> id, group, enabled
eventwatch_rule_get  {"name": "<exact name>"}                 -> the whole selector
eventwatch_rule_test {"rule": <that rule>, "event": <a real event>}
```

Take the event from `lake_search` and pass its `source` verbatim. `hit` tells you
whether the selector matches; for a behavior rule that hits, `behaviorEvent` is the
rendered row.

Three things this catches that reading the rule does not:

- **The rule may not watch the index you think.** `AzureAD_User_Add_Authentication_Method`
  selects on `@azureDirectoryAudit.*` and matches nothing in `Office365` — feeding it
  Office365 documents returns a perfectly correct `hit: false` that looks like a
  broken rule. Check which envelope the `mustFilters` name before choosing events.
- **`mustNotFilters` do most of the work.** In one window six `operationType: Add`
  events reached that rule and four were excluded by name; only the remaining two fired.
  A "noisy rule" is often a rule whose exclusion list is one value short.
- **A rule with no `name` panics the endpoint** rather than reporting an error. The
  MCP tool refuses it before the wire; the CLI does not.

Testing a rule does not deploy it, and the engine forces `disabled: false` for the
test — so a rule disabled on the tenant still evaluates. Write the suppression itself
with the **`eventwatch-rule`** skill.


## Step 8 — The closure report (only when asked)

The investigation **stops at the verdict**: the step-7 closure in chat is the default
deliverable. End it with a one-line offer to render the HTML closure report. Build the
report only when the user or the customer asks for one — "write it up", "send the
customer a report", "give me the HTML".

**How it is built.** The report is rendered from a JSON file by
`scripts/render_closure.py`; never hand-write it as free-form HTML. Fields are
documented in `assets/closure_schema.md`. Start from the example that matches the
incident's shape (both are anonymised):

- `assets/examples/sendas_admin_closure.json` — a multi-day incident with a score
  history (`score_table`, `base_rate`).
- `assets/examples/credential_policy_closure.json` — a single event or transaction
  (`timeline`).

```bash
python3 scripts/render_closure.py closure.json \
    -o <account>-<entity>-<YYYY-MM-DD>-closure.html
```

The script refuses JSON missing a required section (`title`, `lede`, `verdict`, `meta`,
`grounds`, `negatives`, `recommendation`, `footer`) or with a `verdict.outcome` other than
`benign`, `escalate` or `confirmed`. Fluency branding (navy header with the embedded
logo, a `Confidential · <Tenant> · Incident Closure` tag, the Fluency palette and a
"Powered by Fluency" footer) is applied on every run — never post-process the HTML.
Always put `Subject` and `Tenant` in `meta`; the header and footer are built from them.
**The logo is replaceable:** pass `--logo <image>` (PNG, JPEG, SVG, WebP or GIF), or set
`"logo": "<path relative to the JSON>"` in the closure JSON; `--logo` wins. Without
either, the bundled `assets/fluency_logo.png` is used. A logo path that cannot be read
stops the render rather than silently falling back to the wrong brand.
If `scripts/render_closure.py` is not present (an install that carries only SKILL.md),
say so and offer to fetch the skill package from `cowork/incident-investigation.skill`
in the `SecurityDo/ingext_skills` repo; do not hand-write a substitute report.

**Section order**, fixed by the renderer, each mapped to a step above: title + lede →
verdict card (step 7) → metadata grid (step 1) → "N grounds for escalation, tested"
(steps 1, 3, 6) → timeline for a single event **or** score-vs-activity bars for a
multi-day incident (step 6 / step 1) → base-rate table when the base rate is above one
(step 2) → what did not happen (step 5) → callouts → recommendation (step 7) → footer.

**Fill rules.**

- **Every number is one you measured in this run, on `ACCOUNT` only.** The base-rate
  table, the peer cohort and every control count are intra-tenant. A report is the
  place a cross-tenant number would do the most damage, so the hard rule applies with
  extra force: if a figure did not come from this account, it does not appear.
- **Name the tenant by its display name, and never name the connector.** The report
  goes to the customer; the MCP connector is internal plumbing. Use the `displayName`
  that `list_accounts` returned for `ACCOUNT` (e.g. `Contoso Ltd`, not `contoso`, and
  never `<connector> : contoso`) for `Tenant` in `meta` — which also feeds the header tag and footer —
  and wherever the tenant is named in the title, lede, captions and findings. Fall back
  to the account name only when no display name exists.
- **Section titles state findings.** "The score does not follow the activity", not
  "Risk score analysis". If the evidence does not support a one-line claim, leave the
  section out.
- **Quote the ticket, then test it.** Each ground's `claim` is the AI-assist text
  verbatim, including any number it got wrong; the `finding` names the index each
  number came from.
- **No zero without a control.** Each negative states its zero next to the count of the
  same operation elsewhere on the tenant. A check that could not be run is written as
  a gap ("not verified — no Gmail logs ingested"), never as a pass.
- Timeline times come from the raw index (step 6), never from summary buckets.
- `footer.evidence` lists every index or API consulted with its row or hit count and
  ends with the data-boundary line using the display name: "All findings: `<display
  name>` only." (The chat closure in step 7 still names connector and account; the
  report does not.)

**Deliver it.** Render into the working directory, open it once (or take a screenshot)
to check the layout, then send the file with the session's file tool; when a folder of
the user's is connected, save it there. The page loads Google Fonts when online and
falls back to system fonts offline, so it still works when emailed. Keep the chat reply
to the verdict and the one action — do not paste the report back into chat.

## Assets

| Path | What it does |
|---|---|
| `scripts/ingext_json.py` | Runs an `ingext` command and recovers the JSON body from the debug log; prints the resolved `siteURL` |
| `scripts/summary_digest.py` | Daily history for one entity, the AI-assist verdict, and the `--rule` base-rate census |
| `scripts/kql_rows.py` | Reads `ingext kql --output` JSON, dedupes, `--count` a column |
| `scripts/render_closure.py` | Step 8: renders a closure JSON into the Fluency-branded HTML report; validates required sections |
| `assets/closure_schema.md` | Step 8: field reference for the closure JSON |
| `assets/examples/*.json` | Step 8: anonymised worked closures (multi-day admin, single event) |
| `assets/fluency_logo.png` | Embedded into the report header as a data URI |

The three scripts exist for the CLI path. On the MCP path `behavior_summary_search`
returns the documents directly, so only `summary_digest.py` still earns its place —
feed it the `documents` array. `ingext_json.py` is unnecessary there: it exists solely
to recover a JSON body from a debug log, and MCP returns one.
| `assets/queries/*.kql` | The twelve queries above, placeholder-substituted and parse-validated |

Queries use `{USER}` (lower-cased UPN), `{TARGET}` (the UPN as `ObjectId` spells it),
`{IPS}`, `{PREFIX}`, `{UA}`, `{FROM}`/`{TO}` (epoch ms). Run
`ingext kql validate @<file>` after substituting — it parses in under a second and
catches a wrong column name before a 20-second scan does.

**A KQL field reference that starts with `@` silently returns null.** This is the
single most dangerous syntax trap here, because it never errors:

```
| where @fields.Operation == "Send"      // count 0      <- WRONG, and silent
| where Operation == "Send"              // count 8806
```

Null compared to anything is false, so every row is filtered out and the query
"succeeds" with a confident zero. A `summarize ... by op=@fields.Operation` collapses
the whole result into one bucket keyed `null`.

The rule is about the leading `@`, not about dots — `Item.Subject`, `_ip.country` and
`AppAccessContext.AADSessionId` all resolve unquoted. Bracket-quoting fixes it
(`['@fields.Operation']`, `['@timestamp']`, `['@source']` all resolve), but the
documented interface is the **flat schema name**, so use that:

| Tool | Field spelling | Why |
|---|---|---|
| `kql_search` | `Operation`, `UserId`, `_ip.country` | the datalake projects `@fields.*` up to top-level KQL columns |
| `lake_search` `searchStr` | `@fields.Operation:Send` | Lucene over the raw `_source`, which has no such projection |

The column list is not in any MCP tool — `list_data_tables` returns names and
descriptions only. It lives in the **`ingext-kql` skill**, at
`references/schemas/<Table>/info.yaml`: 66 documented columns for `Office365`, none
of them `@`-prefixed, plus ten canned queries. Note `Item.Subject` works but is not
documented there.

**Two matching traps on Office365 `Operation` values.** The credential operation is
spelled `Update application – Certificates and secrets management ` — with an **en
dash**, not a hyphen, **and a trailing space**. An exact-equality match fails on
either, and the CLI's `--must` filter does not round-trip the en dash at all (0 hits
while the facet shows the event exists). Through `ingext kql` all of these work:

```
| where Operation contains "Certificates and secrets"     // cleanest, avoids the dash
| where Operation has "Update application"                // also catches "Update application."
| where Operation startswith "Update application"
| where Operation endswith "secrets management "          // note the trailing space
```

Tables used: `AzureSigninLogs`, `AzureAuditLogs`, `Office365`, `office365User`. Check
they exist on the tenant with `ingext datalake list-index --datalake managed` — a
tenant without `AzureSigninLogs` needs the Office365-only path, and
`office-user-investigation` covers it.

## Related skills

- **`office-user-investigation`** — a full mailbox investigation with a GeoIP map, for
  when the subject is the mailbox rather than one incident.
- **`azure-user-signin-investigation`** — sign-in and directory-change history via the
  three FPL reports, where they are deployed.
- **`eventwatch-rule`** — once step 2 says the rule is noisy, this is how the
  suppression is written, tested against real history and released.
- **`ingext-kql`** — any query beyond the twelve here; never hand-write KQL from
  memory against an unverified schema.
