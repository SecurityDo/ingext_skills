---
name: eventwatch-rule
version: 1.1.0
description: >-
  Create, test, deploy and release an Ingext EventWatch rule — the behavior and aggregation rules
  that turn parsed events into behavior signals. Use this skill whenever the user asks to "create
  an eventwatch rule", "add a behavior rule", "track an activity by user", "alert on multiple
  failed logins", "set up an aggregation rule", "write a detection for a vendor", "tune a rule's
  threshold", or wants an existing rule enabled, disabled, promoted or rolled back on a tenant.
  Covers learning the vendor's real event shape before writing a selector, allocating an id from
  the registries, the first/aggregation rule types, testing with `eventwatch rule_test`,
  validating thresholds by replaying real history rather than guessing, the global-versus-local id
  rule that decides whether a deployed rule can ever be edited again, deploying to a tenant,
  releasing with `sync_cli release`, and the sync and toggle semantics that decide whether a
  released rule actually runs.
---

# EventWatch rules: create, test, deploy

A rule that matches your sample event is not a rule that works. Selectors are easy; what
costs the time is the vendor's real traffic — fields that are `N/A` instead of absent, one
logical action logged as two events, and a noise class that outnumbers the signal ten to one.
Every threshold in this skill's examples was wrong on the first attempt, and the data said so.

## Anatomy

A rule is one JSON file under `rules/<Group>/rule_<Name>.json` in the Scripts repo.

```
id               registry-allocated, or 0 -- see "Global versus local" below. Decides everything.
name             unique per tenant; the file is rule_<name>.json
group            folder name, e.g. Fortigate
eventSelector    which events match
  mustFilters      AND of filters; terms within one filter are OR'd
  mustNotFilters   exclusions; each one drops an event on its own (they are OR'd)
  eventFilter      a Lucene string; the server compiles it into `query`
  query            GENERATED from eventFilter on every write -- never hand-write it
  jsonFilter       Lua script -- deprecated; still evaluated, but do not add new ones
behaviorRule     what to emit when they do
  key / keyType    the entity: a field path, and username | asset | ip
  behavior         security alert | application activity | account login | network access
  description      Go template over the attribute aliases: "{{.Username}} logged in from {{.IP}}"
  fields           field paths carried onto the signal
  attributes       [{field, aliase}] -- aliase is what the description template and UI use
  rules[]          the detections themselves: type "first" or "aggregation"
searchProfile    a facet name that must already exist (facet_release.json)
timeSlices       ["1d","1h","1m"]
```

`filterType` values in use: `field`, `exists`, `entityinfo`, `contains`, `startswith`,
`endswith`. `entityinfo` matches the field against a named EntityInfo list (`HOME_NET`).

### `eventFilter` and `query`: write the Lucene, let the server compile

`query` is not an input. On every `rule_add` / `rule_update` the server rewrites the selector
(unless `matchAll` or `lvdbQueryFlag` is already set):

| What you send | What the server stores |
| --- | --- |
| no `eventFilter`, no must/mustNot filters, no `jsonQuery` | `matchAll: true` |
| `eventFilter` set | `query` = the Lucene parsed into an ES bool, **replacing any `query` you sent**; a parse error refuses the write |
| no `eventFilter`, but must/mustNot filters, no `LVDBQuery` | `query` = `{"match_all":{}}` |

So a hand-written `query` with an empty `eventFilter` is silently replaced by `match_all`, and the
rule matches more than you meant. Put the condition in `eventFilter`. In repo files, keep the
compiled `query` next to it, copied from a `rule_get` read-back, as every existing rule with an
`eventFilter` does.

**An exclusion that needs two conditions together goes in `eventFilter`.** `mustNotFilters`
are OR'd, so two of them drop events matching *either* value — usually far too much. Write the
pair as one Lucene clause:

```
NOT (@fields.ParametersFields.Identity:"DiscoverySearchMailbox{D919BA05-46A6-415f-80AD-7E09334BB852}" AND @fields.ParametersFields.User:"Discovery Management")
```

which compiles to `bool.must_not[ bool.must[ term, term ] ]`. That example is a real one: Exchange
Online periodically re-grants its own Discovery Management role group FullAccess on the built-in
discovery mailbox, and a FullAccess-grant rule fires on it every couple of weeks in every tenant.
Excluding either field alone would also hide a real grant on that mailbox, or a real grant *to*
that role group.

**Don't add a Lua `jsonFilter`.** It is deprecated. Existing rules that carry one still run, and
the engine still evaluates it, so leave them alone unless you are rewriting the rule anyway. For
new work, match the processor-flattened fields with filters: `@fields.ParametersFields.AccessRights`,
not a Lua loop over `@fields.Parameters`.

Two detection types:

```jsonc
// "first" -- fires on the first occurrence of a value within a window
{"name":"NewISP","type":"first","risks":["ML_NEW_GEO_ISP"],
 "first":{"window":{"unit":"day","length":30,"text":"30d"},
          "fields":["@fortigate._ip.isp"],
          "localScope":true}}          // or "entityScope": true -- first across all entities

// "aggregation" -- fires on a count over a window
{"name":"FailedLogin","type":"aggregation","risks":["ALERT_POLICY"],
 "aggregation":{"window":{"unit":"hour","length":4,"text":"4h"},
                "aggType":"count",
                "match":{"operator":"gt","operands":[3,0]}}}   // gt 3 fires at 4, not 3
```

`operands[0]` is compared with `gt`, so **a threshold of `N` fires on `N+1`**. This is the
single most common off-by-one in rule authoring; see step 5.

## Step 1 — Learn the real event shape before writing a selector

Do not write a selector from vendor documentation or a sample file. Read the tenant's own
events.

```bash
ingext config use <cluster>:<namespace>       # --cluster/--namespace flags do NOT switch tenant
ingext datalake search --index default --query '<lucene>' \
    --from <epoch_ms> --to <epoch_ms> --limit 3 \
    --facet '<field>' --facet '<field>' --facet-size 20
```

`datalake search` returns real `_source` documents plus term counts, which is exactly what a
selector is built from. **`ingext kql` is the wrong tool for this**: the `default` index
stores raw docs as `timestamp`/`size`/`doc`/`labels`, so projecting `@`-prefixed fields
returns `PrimaryResult (empty)` while still reporting a whole-index scan count.

Facet every field the rule will filter on or carry, and read the counts, not just the shapes:

```
@fortigate.action        tunnel-up 5511, ssl-login-fail 155, ssl-web-deny 422, ...
@fortigate.reason        wrong vdom (0:0) or time expired 402, sslvpn_login_unknown_user 8, ...
@fortigate.user          N/A 448, Codeplex 5, ...
```

That third line is the kind of thing that changes a design. A rule keyed on the username, for
"multiple failed logins by one user", is near-dead if the vendor logs `N/A` on 98% of
failures — which FortiOS does for SAML SSL-VPN, because authentication happens at the IdP and
the firewall never sees a username. Find that out now, not after deploying.

**`N/A` is not absent.** Vendors write the literal string. `filterType: exists` will happily
match it; exclude it explicitly in `mustNotFilters`.

## Step 2 — Allocate an id

Take the max across **both** registries at the repo root and the rules on disk, then go one
past:

```bash
python3 - <<'EOF'
import json, glob
ids = set()
for f in ('rule_release.json','rule_dump.json'):
    ids |= {e['id'] for e in json.load(open(f))['entries']}
ids |= {json.load(open(p))['id'] for p in glob.glob('rules/*/*.json')}
print('next free:', max(ids) + 1)
EOF
```

`sync_cli` reports the rule range as `100001 to 299999`. The repo README's
`100000 ~ 199999` is the older, narrower convention.

## Step 3 — Write the rule

Copy the nearest existing rule in the same group rather than starting blank — the JSON has
fields (`enableTotal`, `aggregationBucket`, `timeSlices`, `translation`) that matter less than
getting the shape consistent with its neighbours.

Two things worth deciding deliberately:

- **The key must be a recurring entity** — an account, a host, an address — never something
  per-event. The `first` detections are all relative to the key, so a key that is unique per
  event makes every event a first occurrence.
- **Attributes must be present on the events you match.** An attribute whose field is missing
  renders as the literal string `__undefined` in the behavior event. If your selector narrows
  to a subset of events, re-check that every attribute still exists on that subset.

  The usual source of a permanent `__undefined` is an attribute borrowed from a sibling
  operation. One Exchange mailbox-permission rule carried a `Trustee` attribute, a parameter of a
  *different* cmdlet that `Add-MailboxPermission` never sends; the real grantee was in an
  attribute named `User`, right next to `UserId` (the actor). Every behavior summary read
  `Trustee: __undefined`, and two automated triage tiers reported the grantee as unknown. Facet
  each attribute's field over the selector's real hits: one that is never populated is removed,
  not tolerated.
- **Name attributes for what they are.** The alias is all a reader (or an AI triage step) sees.
  `Grantee` and `Mailbox` say what `User` and `ObjectId` do not. Renaming an alias changes no
  value, so it does not change the dedup key either.

The platform lowercases the key (`originalKey` keeps the raw value), so mixed-case usernames
collapse to one entity on their own.

## Step 4 — Test against real shapes

```bash
ingext eventwatch rule_test --content @rules/<Group>/rule_<Name>.json --event ./sample.json
ingext eventwatch rule_test --name <DeployedRule> --event ./sample.json
```

Output line one is `hit` or `no hit`; a miss is a result, not a failure, and the exit code is
0 either way. Build a directory of events and drive it as a matrix — one row per event, one
column per rule — so an exclusion that silently stops working is visible:

```
EVENT                    Login    FailUser  FailIP
hit_login_ssl_web        HIT      -         -
hit_login_ssl_tunnel     -        -         -        <- the de-duplication case
fail_user_na             -        -         HIT
fail_user_named          -        HIT       HIT
miss_web_deny            -        -         -
```

Include, at minimum: one event per branch you intend to match, one event per branch you
intend to *exclude*, and one event from a different vendor entirely.

**`--content` tests the file as written, not as it will be stored.** `rule_test` honours a
`query` passed inline, but a deploy recompiles `query` from `eventFilter` (see Anatomy). A
hand-written `query` exclusion therefore passes here and is gone on the tenant. The matrix only
counts once it has been re-run against the read-back rule (step 6). The same tests are available
as MCP tools (`eventwatch_rule_list`, `eventwatch_rule_get`, `eventwatch_rule_test`, all
read-only); passing a `rule_get` result to `eventwatch_rule_test` tests exactly what is stored.
Rule writes (`rule_add`, `rule_update`, `rule_toggle`) are CLI only.

A hit prints the rendered `description`, the `valueMap`, and the full `behaviorEvent` with
resolved attributes — read them. That is where `__undefined` and an unrendered `{{.Alias}}`
show up.

**A known CLI wart:** an aggregation rule that hits prints
`signal 0 is not valid JSON: cannot unmarshal number into ... valueMap of type string`.
The rule matched; the CLI cannot render a signal whose valueMap holds the numeric count.
Read line one (`hit`) and ignore the error.

## Step 5 — Validate thresholds by replaying real history

**Do not pick a threshold by intuition.** Pull the real events the rule matches and compute
the maximum count in a sliding window, per key:

```bash
ingext datalake search --index default --query '<selector as lucene>' \
    --from <7d ago ms> --to <now ms> --limit 500 --output /tmp/hits.json
python3 assets/replay-threshold.py /tmp/hits.json --key '@fortigate.user' --window 4h
```

`assets/replay-threshold.py` prints the per-key maximum and the alert count at each candidate
threshold, so the choice is a number, not a guess:

```
=== max in any 4h window ===
  by USER : {'Codeplex': 5, 'Theunis.gabsten': 1, 'h': 1}
=== alerts per 7d at candidate thresholds ===
  gt2:1  gt3:1  gt4:1  gt5:0  gt7:0
```

Two lessons are baked into that output.

**The off-by-one is real.** A rule shipped at `gt 5` against a probe that peaked at exactly 5
fires never. Both aggregation rules in the worked example were shipped a threshold too high
and would have produced zero alerts in a week; the replay is what found it.

**Exclude the noise class before choosing the threshold.** Of 452 SSL-VPN login failures, 402
were a SAML portal session expiry — not a credential failure at all. Counting them, 56 source
addresses exceeded 2-in-4h and nothing was distinguishable. Excluding that one `reason` left
50 real failures and a threshold that alerts about once a week. Facet the reason/status field
and ask what fraction of matches are actually the thing you are detecting.

**Check whether one action produces several events.** Group the matched events by key and
count distinct sub-types:

```bash
python3 assets/replay-threshold.py /tmp/hits.json --key '@fortigate.user' --overlap '@fortigate.tunneltype'
```

FortiOS logs one SSL-VPN login as **two** `tunnel-up` events — the authentication
(`ssl-web`, reason `login successfully`) and the tunnel setup (`ssl-tunnel`, reason
`tunnel established`) — and 149 of 165 users produced both. A selector matching on the action
alone raised two behavior events per login. The fix was a `reason` filter pinning the rule to
the authentication stage, which covers every user exactly once. If `--overlap` shows most keys
carrying more than one value, your rule is probably double-counting.

## Global versus local: decide before the first deploy

**This is the decision that cannot be undone in-tenant.**

| | `id: 0` | `id > 0` |
| --- | --- | --- |
| treated as | tenant-local | global (owned by the Fluency repo) |
| `rule_add` | yes | yes |
| `rule_update` | yes | **refused** — `Global rule is read only` |
| `rule_delete` | yes | **refused** — `Global rule is read only` |
| re-add to fix | n/a | refused — `duplicate bucket` |
| `rule_toggle` | yes | yes — the only write that works |
| reaches other tenants | no | yes, via release + sync |

A global rule pushed to a tenant is **immutable there**. It can be disabled and nothing else;
`ingext import` has no `rule` subcommand, so it cannot be pulled back either. The only route
to changing it is the repo release and the tenant's next sync.

So: **iterate with `id: 0`, ship with the allocated id.** Keep the repo file at its real id
and deploy a copy with `id: 0`, the `repository` field dropped and a `_Local` name suffix —
including `behaviorRule.name`, which is what lands in `@behaviors` and keeps the two
distinguishable. Then `rule_update` works and iteration costs one command.

Stranding a broken global in a customer tenant is a real outcome: it stays there, disabled at
best, until a release reaches it.

## Step 6 — Deploy to a tenant

```bash
ingext config use <cluster>:<namespace>
ingext eventwatch rule_list | grep -i <name>          # check for a name collision first
ingext eventwatch rule_add --content @<file>
ingext eventwatch rule_get --name <name>               # read back what was stored
```

Then re-run the step 4 matrix with `--name` against the deployed rule, not `--content`. They
can differ — a field the server rejects or defaults is only visible on read-back. Check
`eventSelector.query` on the read-back first: `{"match_all":{}}` where you expected an exclusion
means the condition was written into `query` instead of `eventFilter`.

**While a `_Local` copy runs next to its global rule, both fire.** Every matching event raises
two behaviors on the same key, and the local copy starts with no `first` history, so its
first-seen detections fire on the early events. The tenant's scores for those entities are
inflated until the copy is deleted. Say so to whoever triages that tenant, and keep the
window short.

## Step 7 — Verify it fires on live traffic

Rules apply at ingest and are **not retrospective**, so events that arrived before the rule
existed are never tagged. Give it real traffic, then:

```bash
# behaviors tagged on the source events
ingext datalake search --index default --query '<selector>' --from <ms> --to <ms> \
    --limit 1 --facet '@behaviors'

# the behavior events themselves
ingext datalake search --index behavior --query '<RuleName>*' --from <ms> --to <ms> --limit 2
```

Expect roughly ten minutes of indexing lag before a new event is searchable. Read the emitted
behavior and check the rendered `description`, every attribute value, and `history`
(`BehaviorFirstSeen`, `KeyFirstSeen`) — this is the last chance to catch an attribute that is
always `__undefined` or a `first` rule that will fire on every event.

## Step 8 — Release

Deploying puts a rule on one tenant. The registries are how it reaches any other.

```bash
# commit the rule file FIRST -- entries record contentCommit/gitHash from git
sync_cli release /home/kun/github/Scripts rule
git add rule_release.json rule_dump.json && git commit -m release
```

**`sync_cli release <repo> fplProcessor` does not release rules.** The resource name is the
registry file's prefix, and each is separate. A rule committed but never released reaches
nobody, and the symptom is a tenant that syncs cleanly and still runs the old definition.

Verify the registries carry the corrected content, not just the id:

```bash
python3 -c "
import json
d=json.load(open('rule_dump.json'))
e=[x for x in d['entries'] if x['id']==<ID>][0]
print([(f['field'],f['terms']) for f in e['eventSelector']['mustFilters']])"
```

## Promoting a local rule to the global one

After the release reaches the tenant (a `gitsync` on the site, then a few minutes):

1. **Verify the content actually synced.** Check a field you changed, not the id.
   `assets/check-rule-state.py` takes name/threshold expectations and exits non-zero until
   they match, so it can be polled.
2. **Read the enabled state before toggling.** `rule_toggle` *flips*; it does not set. If the
   sync had cleared the flag, a toggle would switch the rule off.
3. **The disabled flag is sticky.** Disabling a global rule in a tenant is a per-tenant
   override that survives the sync — the sync updates content and leaves the flag alone. A
   synced rule does not come back on by itself.
4. **Delete the `_Local` copy before enabling the global**, not after. The overlap window
   would write duplicate behavior events, which persist and are tedious to unpick; a few
   seconds of gap costs one untracked event.
5. Re-run the step 4 matrix against the now-enabled global.

## CLI and API notes

**`rule_get` writes its JSON to stderr, not stdout.** A script that captures stdout alone
gets nothing and will report every rule as missing — which looks exactly like a sync having
deleted them. Always `2>&1`.

The DAO behind every command:

```
POST /api/ds/eventwatch_bucket_dao
{"function":"eventwatch_bucket_dao","kargs":{"action":"delete","args":{"id":"<RULE NAME>"}}}
→ HTTP 200  {"verdict":"ERROR","response":null,"error":"Global rule is read only"}
```

- `args.id` is the rule **name**, not the numeric id.
- Errors return **HTTP 200** with `verdict: ERROR`. The status code is not a success signal,
  and a UI that checks only the status code will report a refused delete as successful.
- The read-only guard is applied per action: `toggle` passes where `update` and `delete` fail.
- `ingext -l debug <cmd>` prints the full request and response, which is the fastest way to
  see what a command actually sent.

## Gotchas worth knowing before they cost an hour

- **`--cluster` / `--namespace` do not switch tenants.** Only `ingext config use
  <cluster>:<namespace>` does. Commands run happily against the previous tenant and return
  plausible-looking data. Switch, work, switch back.
- **`gt N` fires at N+1.** Say the intended firing count out loud when setting `operands`.
- **`N/A` is a value.** `exists` matches it.
- **`searchProfile` must name a facet that exists** in `facet_release.json`; a stale name
  leaves the analyst with no view.
- **A rule with no `behaviorRule` fields hits without producing anything.** `rule_test` prints
  `hit` and no signal, which reads like a broken runtime.
- **`group_delete` takes a whole group.** There is no bulk rule delete that is not also a
  blast radius; the Fortigate group on a live tenant held sixteen rules.
- **Check the tenant for rules that are not in the repo** before assuming a group is yours.
  Tenants carry locally-authored rules with the same naming conventions.
