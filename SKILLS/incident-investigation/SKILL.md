---
name: incident-investigation
version: 1.0.12
description: >
  Investigate an escalated Fluency/Ingext behavior incident and close it with a verdict and
  evidence. Use this skill whenever the user hands over a behavior incident, an AI-assist
  ticket, an alert or a risk score and asks what it really is — "investigate this incident",
  "triage this ticket", "is this a true positive", "the AI assist says actionable, check it",
  "get the behavior summary for <user>", "why did <user> score 3600", "should we escalate
  this alert". Covers pulling the behavior summary and the AI-assist verdict out of the
  eventwatch API, then the four checks that actually decide a verdict — the fleet base rate
  for the rule that fired, resolving every source IP against the rest of the tenant, reading
  which device approved the change, and proving what did NOT happen afterwards — plus the
  timestamp, error-code, user-agent, duplicate-row and geolocation traps that manufacture
  findings that are not there. Ends in a written closure: benign, escalate or confirmed, with the detection
  tuning that stops the next eleven copies of the same ticket.
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

## Required inputs

| Argument | Meaning | Example |
|---|---|---|
| target | `provider:tenant`, or the cluster profile | `msp1:contoso` |
| entity | the key the incident is on — username, asset or IP | `user@corp.com` |
| window | epoch ms; default the last 30 days | `--from 1787246734000` |

If the entity is missing, ask for it. If the window is missing, use 30 days — shorter
windows hide the baseline the whole procedure is measured against.

## Step 0 — Point at the right tenant, and prove it

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
switch changes yours, mid-run, with nothing in the output to say so. Two sessions
triaging different tenants on the same afternoon will silently swap targets under
each other.

So do not prove the tenant with `config view`. Prove it **per call**, from the call's
own debug log, and assert it:

```bash
python3 scripts/ingext_json.py kql out.json query.kql --expect <tenant>
python3 scripts/ingext_json.py run summary.json --expect <tenant> -- eventwatch …
```

Both print the site that actually answered and exit non-zero on a mismatch. This
beats reading `config view` before and after, because a flip and flip-back inside
one call passes both reads while the call itself went elsewhere.

**Spend the attribution effort where it buys something.** Datalake reads are
self-attributing: the rows carry tenant identifiers, and a query that lands on the
wrong cluster returns *nothing* rather than something plausible. The dangerous calls
are the **server-side evaluations** — `ingext eventwatch rule_test` and
`ingext processor test` — which execute on whatever profile is current and return a
confident answer with nothing in it naming the cluster. If two clusters run different
platform versions, such a result is not wrong, it is unattributed.

Those calls print the siteURL too, so attribute them the same way — **with `-l info`,
not `-l debug`**:

```bash
ingext -l info eventwatch rule_test --content @rule.json --event ev.json 2>&1 \
  | grep -a siteURL
```

**`-l debug` dumps the `Authorization: Bearer` header.** It writes the tenant's API
token into whatever captures the output — a transcript, a pipeline, a log file on
disk. `siteURL` is logged at **INFO**, so attribution never needs debug. Reach for
`-l debug` only when you need the response body, which is the one thing INFO does not
carry, and redact the credential before the output is stored: `ingext_json.py`'s `run`
mode does exactly that, while its `kql` mode uses `-l info` because `--output` already
supplies the body.

Restore the profile when you finish, and say which tenant you left it on if anyone
else is working. If no direct profile exists, reach the tenant through its provider
with `--gridaccount <tenant>` — and note that an unknown account name does not error,
it silently serves the manager account.

## Step 1 — Pull the summary and the AI-assist verdict

```bash
python3 scripts/ingext_json.py run summary.json -- \
    eventwatch search_summary --query '<entity>' --from <ms> --to <ms>

python3 scripts/summary_digest.py summary.json <entity> --ai
```

Two things about this API cost time if you don't know them:

- **`eventwatch search_summary` prints almost nothing.** The CLI writes a
  `Key: …, RiskScore: …` line per hit to stderr and discards the document. The full
  body exists only in the `-l debug` log, pretty-printed inside a Go slog `msg="…"`
  field. `ingext_json.py` runs the command and digs it back out. (`ingext kql` is the
  exception — it has `--output`.)
- **`--query` is free text, not a key filter.** Searching one username on a
  single-domain tenant returns most of the tenant: one search for one user came back
  with 69 summaries across 40 accounts. `summary_digest.py` filters on `key`.

What to take from the digest:

- the **daily history**. One spike against 26 quiet days is a different animal from a
  score that has been climbing for a week.
- the **risk decomposition**. Decompose it with the formula below rather than reading
  the number as a severity — in every incident triaged so far the ML first-seen term
  has been the dominant one, and the rule's own severity a minority share.
- the **AI-assist verdict** from `comments[]` (`username: "AI-Assistant"`, content is a
  JSON string). Read its `keyQuestions` as a to-do list, not as findings.
- **no time in the summary is the event time.** The document brackets the truth and
  hits it on neither side, so re-derive every timestamp from the raw index before
  writing a timeline — see "Neither summary timestamp is the event time" in step 6.

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

## Step 2 — The base rate (run this before anything else)

The single most valuable query in this skill. How many other entities fired the same
rule in the same week?

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
risk signature**, and 55+ accounts registered passkeys across five days. The ticket
was the twelfth copy of one IT project. Nothing downstream could have overturned that,
and everything downstream was cheaper to interpret once it was known.

A base rate of one does not prove an attack. It only means you keep going.

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
values from two tenants. So the stamp runs **early** by up to two minutes (03:06:00 for
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

State plainly where you disagree with the AI-assist verdict and why. That workflow
skipped exactly three checks — the base rate, the IP resolution and the approving
device — and each one is a single query.

## Assets

| Path | What it does |
|---|---|
| `scripts/ingext_json.py` | Runs an `ingext` command and recovers the JSON body from the debug log; prints the resolved `siteURL` |
| `scripts/summary_digest.py` | Daily history for one entity, the AI-assist verdict, and the `--rule` base-rate census |
| `scripts/kql_rows.py` | Reads `ingext kql --output` JSON, dedupes, `--count` a column |
| `assets/queries/*.kql` | The twelve queries above, placeholder-substituted and parse-validated |

Queries use `{USER}` (lower-cased UPN), `{TARGET}` (the UPN as `ObjectId` spells it),
`{IPS}`, `{PREFIX}`, `{UA}`, `{FROM}`/`{TO}` (epoch ms). Run
`ingext kql validate @<file>` after substituting — it parses in under a second and
catches a wrong column name before a 20-second scan does.

**Which index a query form works against matters.** These queries target *schema'd*
indexes. `ingext kql` returns no rows against the `default` index, whose raw document
shape does not resolve a column projection over `@`-prefixed fields — read that one
with `ingext datalake search` instead.

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
