---
name: parser-rule
version: 1.1.0
description: >-
  Create, test, deploy and release an Ingext parser rule: a registered EventWatch rule whose
  matching runs in an FPL processor instead of the eventwatch engine. The processor (a channel
  rule) emits the rule's signal lines into the CorrelationService sink, and fsm_service, mantis and
  the behavior summary service treat them exactly like an eventwatch rule's. Use this skill when
  the user asks to "create a parser rule", "move a rule's matching into the parser", "emit
  signals from FPL for a registered rule", "write a channel rule", "test a parser rule",
  "compare a parser rule with its static rule", or "release a parser rule". Covers choosing a
  parser rule over a static rule or a dynamic behavior signal, the rule file, the hit and
  aggregation lines, writing the channel rule, tagging @behaviors, local validation with
  fplJobValidate -signals, rule_test, wiring a site-local test pipe without touching standard
  processors, verifying fsm_service keeps the lines, side-by-side comparison, warm-up, and
  release with sync_cli.
---

# Parser rules: create, test, deploy, release

A parser rule is an ordinary registered EventWatch rule (`EventWatchBucket`) with `parser` set.
eventwatch never matches it. Its matching and attribute capture run in FPL, which writes the
same signal lines eventwatch would, under the rule's registered name, into the
`CorrelationService` sink. From there fsm_service, mantis and the behavior summary service
handle them like any eventwatch rule's signals: same behavior events, same `first` and
`aggregation` correlations, same DeployedOn grace and mantis learning window.

What it buys: the matching can be anything FPL can do (cross-field logic, parsing, lookups),
and **a parser release does not restart the rule's warm-up** — only a change to the rule
itself does.

For the rule JSON itself (behaviorRule, attributes, correlation types, thresholds, ids,
global versus local) read **eventwatch-rule** first; this skill covers only what differs.

## Which kind of rule

| You want | Use |
| --- | --- |
| A selector over fields eventwatch can express | a static rule (**eventwatch-rule**) |
| Matching eventwatch cannot express, or that changes with the parser, on a **registered** rule with `first` / `aggregation` correlations | a parser rule (this skill) |
| A vendor's own alert names mapped straight to behavior signals, names unknown in advance | a dynamic behavior signal: a processor tagged `behaviorSignal=<Prefix>` emitting `behaviorRule: "<Prefix>:<Alert>"` with `ruleVersion` (no registered rule) |

## Requirements on the tenant

| Piece | Minimum | Why |
| --- | --- | --- |
| account api (ingext_remote) | 9.12.31 | stores `parser`; keeps parser rules out of `rules.json` (eventwatch never loads them) and writes them to `rules_parser.json` |
| account api + account platform | 9.12.32 + 9.0.6 | `rule_test` of a parser rule (runs the processor in the platform service) |
| account fsm | 3.3.2 | reads the CorrelationService archives |
| sink `CorrelationService` | redis, queue `queue:CorrelationService:JobQueue` | where the lines go |

Check the sink: `ingext stream list-sink | grep -i correlation`. If it is missing:

```bash
ingext stream add-sink --sink-type redis --name CorrelationService \
    --queue queue:CorrelationService:JobQueue
```

A `Platform_Sink` to a sink name that does not exist is dropped with only a log line in the
platform worker — the processor sees no error.

## Anatomy

Three objects, all required:

```
rule              rules/<Group>/rule_<Name>.json, a normal EventWatchBucket plus:
  parser            the processor that emits its lines (the channel rule below)
  eventSelector     exactly eventFilter "_na_:_na_" + query {"term":{"_na_":"_na_"}},
                    no mustFilters / mustNotFilters / jsonQuery, matchAll and lvdbQueryFlag off
  aggregations, signals, tagActions   empty
  behaviorRule      as for a static rule: key, keyType, fields, attributes, rules[]
channel rule      an fpl_rule processor with a channel; it matches and emits the lines
caller            a processor on the vendor's router that calls Platform_Channel(channel, {obj})
```

`assets/parser-rule.json` (hit lines, `first` correlations) and `assets/parser-rule-aggregation.json`
(a `count` aggregation) are the kql pilot's working rules; copy one. **Both forms of the never-matching selector must be in
the file**: gitsync stores the file as written and does not compile `eventFilter`, and the
native engine treats a selector without a compiled query as match-all. `sync_cli` refuses a
release that gets this wrong, and refuses a name or `behaviorRule.name` containing `:`.

### The lines

A **hit line** — what eventwatch writes when a behavior rule matches:

```json
{"signal":"behavior:<Rule>","ts":<sec, rounded down to 120 s>,"count":1,
 "key":"<entity>","valueMap":{"<field path>":"<string>", ...}}
```

- `valueMap` carries every `behaviorRule.fields` path plus every `first` correlation field,
  **all strings**. A missing value is the literal `"__undefined"`, an array is comma-joined —
  that is what eventwatch writes, and matching it makes the behavior events identical.
- A `first` correlation field that is missing or not a string breaks the correlation.
- fsm keeps a parser rule's valueMap keys that the rule does not declare as attributes, under
  their own names; a static rule drops them.
- `key` is the entity; the platform lowercases it.

An **aggregation line** — one per event is fine, mantis adds them into the slot:

```json
{"signal":"behavior:<Rule>:<Correlation>","ts":<sec, rounded down to 60 s>,
 "valueMap":{"<key value>":1}}
```

- `<Correlation>` must be an `aggregation` correlation of the rule; exactly one entry; the
  value an unsigned integer (`1` for a `count`, the field's value for a sum).
- When the window total passes the threshold mantis emits `<signal>_emit` with
  `{"value": n}`, exactly as for a static rule.

`ts` is in **seconds**. The name after `behavior:` is the `behaviorRule.name`.

## Step 1 — Learn the event shape

Same as **eventwatch-rule** step 1, with one difference: the channel rule sees the event **as
the pipe hands it on**, after the vendor's `_Adjustments` processor has enriched it (`_ip`
geo fields and the like), not the raw record. Take samples from the tenant's datalake, which
stores that enriched object.

## Step 2 — Write the rule

Copy the static rule you are replacing, or the nearest one in the group. Then: set `parser`,
replace `eventSelector` with the never-matching one, empty `aggregations` / `signals` /
`tagActions`. Keep `behaviorRule` as is. Name and id follow **eventwatch-rule** (iterate as a
tenant-local copy: `id: 0`, no `repository`, a `_local` suffix on `name` **and**
`behaviorRule.name`).

If the parser rule replaces a static rule side by side, copy the static rule's top-level
`description` too: the behavior event's `ruleDescription` comes from it, and a test text there
is the only difference you will see in an otherwise identical comparison.

## Step 3 — Write the channel rule

Start from `assets/channel-rule-hit.js` (hit line) or `assets/channel-rule-aggregation.js`
(aggregation line). Both are the kql pilot's working rules. The shape:

```js
function main({obj, size}) {
    if (!matchLogin(obj)) {          // the selector, in FPL
        return "skip"
    }
    ...build valueMap / key / ts...
    addBehavior(obj, "<Rule>")       // hit rules with timeline or risks only
    Platform_Sink("CorrelationService", {obj: { signal: "behavior:<Rule>", ... }})
    return "match"
}
```

Rules for a channel rule:

- **Change nothing in `obj` but `@behaviors`** (next section). Every rule of the channel and
  the calling processor share it.
- A channel rule's error does not stop the caller or the other rules; it is only counted.
  Test locally (step 4) — on a tenant it is easy to miss.
- The processor named in the rule's `parser` is the channel rule, not the caller.
- Several rules can share a channel; a call to an unknown channel is a silent no-op, so a
  caller can ship the `Platform_Channel` line to tenants that have no rules on it.

### Tag the event (`@behaviors`)

eventwatch adds a static rule's name to the matched event's `@behaviors` array, so the stored
event says which rules it hit (`"@behaviors": ["AWS_Unauthorized_API_Call"]`). eventwatch
never tags for a parser rule, so the channel rule does it itself:

- **When:** on a hit line, if the rule has `behaviorRule.timelineFlag: true` or non-empty
  risks. **Never for an aggregation rule** — eventwatch does not tag those either.
- **How:** `addBehavior(obj, "<Rule>")` from `assets/channel-rule-hit.js`. It creates the
  array when missing, adds the name once, and leaves a `@behaviors` that is not an array
  alone. Use the rule's registered name.
- **Format: an array of strings, nothing else.** eventwatch's tag action (lv3
  `eventwatch_record_tag_action`) keeps an existing array and appends its own static hits, so
  both survive. But when `@behaviors` exists and is not an array it silently drops its own
  tag, and a non-string element in the array breaks it.
- **When it runs:** the tag must be on `obj` before the event is written to the sink that
  stores it. A released caller therefore calls the channel **before** the parser's
  `Platform_Sink` / `return "pass"`. The site-local test caller (step 5) runs after the
  vendor's main pipe has already sunk the event; its tags reach the stored event only
  because the job router serializes that same object when it flushes. That is fine for a
  test, but don't design around it.

Verified on kql (Office365, 2026-10-11): a `UserLoggedIn` event hit by both the parser rule
and its static twin was stored with
`"@behaviors": ["O365_AzureAD_UserLoggedIn_local", "O365_AzureAD_UserLoggedIn"]` (the parser
tag first, eventwatch's appended). A `TeamsSessionStarted` event that only the parser rule
`O365_Teams_SessionStarted_local` matched was stored with
`"@behaviors": ["O365_Teams_SessionStarted_local"]`.

## Step 4 — Validate locally: `fplJobValidate -signals`

fsbv2 `cmd/fplJobValidate` runs processors on sample events in the job-mode environment and
checks every line they sink against the rule files.

```bash
cd ~/cc/fsbv2 && go build -o /tmp/fplJobValidate ./cmd/fplJobValidate
/tmp/fplJobValidate -signals -dir <repo>/fplProcessors -rules <repo>/rules -v
```

- Samples: `<dir>/samples/<Processor>/*.json` (one event per file) or `*.jsonl` (one per
  line), raw events — the tool wraps each as `{obj, size}`. Put them under the **caller**;
  the channel rules run through `Platform_Channel` exactly as on the tenant.
- `-v` prints each recorded line with the processor that emitted it — read them.
- Fails on: a processor error on a sample, a rule whose `parser` is not a processor, and any
  line problem (unregistered rule, a static rule's name, another parser's rule, `ts` not in
  seconds, empty key, a `first` field missing or not a string, an aggregation line naming no
  aggregation correlation or not exactly one unsigned-integer entry).
- Warns: a parser rule its samples never emit (usually a rename or a dead rule).
- geoip, entity info, assets, REST and site info are stubs that return nothing; samples that
  depend on them must already carry the enriched fields.

To try files that are not in a repo, lay out a scratch tree (`fplProcessors/meta/<Name>.json`
with `type` and `channel`, `fplProcessors/code/<Name>.js`, `rules/<Group>/rule_*.json`,
`fplProcessors/samples/<Caller>/*.jsonl`) and point `-dir` / `-rules` at it.

## Step 5 — Deploy to a tenant (test)

```bash
ingext config use <cluster>:<namespace>       # --cluster / --namespace do NOT switch tenant
ingext processor add --name <Rule>_local --type fpl_rule --channel <Channel>_local \
    --content @<Rule>_local.js
ingext eventwatch rule_add --content @rule_<Rule>_local.json
ingext eventwatch rule_get --name <Rule>_local 2>&1     # read back: parser kept, query is the _na_ term
```

`--content` takes `@path` for a file (or `-` for stdin); a bare path is taken as the script
text itself and fails to compile. Rule `tags` must be plain strings.

### Wire a caller without touching standard processors

**Never edit a released processor on a tenant to add the `Platform_Channel` call.** The next
release of that processor is synced over it and the parser rules go silent — this happened on
the kql pilot, and nothing reports it. For a test, add a site-local caller in its own pipe:

```bash
ingext processor add --name <Vendor>_ParserRules_local --type fpl_processor \
    --content @assets/channel-caller-local.js          # edit the channel name in it first
ingext stream add-pipe --router <Vendor>-<Instance> --name <Vendor>-<Instance>-ParserRules_local \
    --processor <Vendor>_ParserRules_local --priority 1500 --match-all \
    --tag application=<Vendor> --tag appInstance=<Instance>
ingext stream list-router          # check the order: main 0 or 1000, this 1500, Behavior 2000
```

Why 1500 and `"abort"`: a router stops at the first pipe that does not return `"abort"`
(see **deploy-fpl-processor**, step 7b). The vendor's `_Behavior` processor returns `"drop"`,
so the caller must run **before** it and return `"abort"` so the event still reaches it; and
after the main pipe, which enriches the event and hands it on. The pipe needs no sinks: a
named `Platform_Sink` goes straight to that sink. Where the main pipe sinks the event itself
(`Platform_Sink("", {obj})` then `"abort"`, as Office365 does), the event is already stored
by then; see "Tag the event" for what that means for `@behaviors`.

gitsync only deletes objects a release lists as deleted or renamed, so `_local` objects that
never appear in the repo are safe from it.

## Step 6 — Test with `rule_test`

```bash
ingext eventwatch rule_test --name <Rule>_local --event ./sample.json
```

For a rule with `parser`, the API does not use eventwatch: it runs the **stored** processor
named in `parser` on the event in the platform service, takes that rule's CorrelationService
lines as `signals` (`hit` when there is one), and renders the behavior event as fsm would.
Nothing is written to a sink.

- The processor is the deployed one, by name — deploy the channel rule before testing, and
  re-deploy it after every edit. `--content` changes the rule, not the processor.
- The event is the processor's input object (the enriched event).
- A run counts in the channel rule's counters and tail on the tenant.
- An aggregation hit prints `signal: behavior:<Rule>:<Corr> key <k> value 1`; a hit line
  prints the key and the rendered behavior event. Aggregation-only rules produce no behavior
  event in a test — that comes from mantis.

Side by side with the static rule it replaces, the two tests should differ only in the rule
name. Compare `-l debug` raw responses, or the JSON output, field by field.

## Step 7 — Verify on live traffic

fsm_service logs one line per CorrelationService archive:

```
parserSignalFile: /cloud/_platform/sink_<id>/v3_....log.gz => /data/fsm_dump/parser_....log:
    read 4 parser signals, kept 4, dropped [] in 36 ms
```

```bash
kubectl --context <ctx> -n acc-<tenant> logs fsm-0 --since=2h | grep parserSignalFile
```

Drop reasons, by rule: `unknown` (no registered rule of that name), `notParser` (the name is a
static rule — FPL may not emit those), `disabled` (the rule is toggled off; `rule_toggle` is
how you pause a parser rule). No `parserSignalFile` line at all means nothing reached the sink:
check the caller's pipe order, the channel name, and the sink.

Then the behavior events, as in **eventwatch-rule** step 7:

```bash
ingext datalake search --index behavior --query '<Rule>_local*' --from <ms> --to <ms> --limit 5
```

For a side-by-side test, compare per user over the same window: count, key, attributes
(alias and value), rendered description, `ruleRisks`. Day-0 differences are match logic or
valueMap gaps in the channel rule.

If the channel rule tags, check the stored events in the vendor's index. Each matched event
should carry the parser rule in `@behaviors`, next to any static rules that also hit it:

```bash
ingext datalake search --index <VendorIndex> --query '@behaviors:<Rule>_local' \
    --from <ms> --to <ms> --limit 10 --facet '@behaviors'
```

Only events processed after the channel rule was deployed carry the tag.

**Warm-up.** A new parser rule starts with no history: mantis's learning window (7 × the
correlation window unit) and the 7-day DeployedOn grace apply, so its `first` hits differ from
a static rule with years of history until both have run 7+ days. Renaming the rule (including
`_PR` to `_local`) starts it over; changing the channel rule does not.

## Step 8 — Release

1. Rule file in `rules/<Group>/` with its allocated id, no `_local`, `parser` naming the
   released channel rule.
2. Channel rule in `fplProcessors/` (`meta/<Name>.json` with `"type": "fpl_rule"` and
   `"channel"`, `code/<Name>.js`).
3. The `Platform_Channel("<Channel>", {obj})` line in the vendor's released caller. Safe on
   every tenant: an unknown channel is a no-op. If any rule on the channel tags `@behaviors`,
   the call goes in the parser that stores the event, after its enrichment and **before** its
   `Platform_Sink` / `return "pass"`. A channel with only untagged rules (aggregations, no
   timeline or risks) can be called from the `_Behavior` processor, at the top of `main`.
4. Samples under `fplProcessors/samples/<Caller>/` and a clean `fplJobValidate -signals`.
5. Commit, then release both resources — they are separate:

```bash
sync_cli release <repo> rule          # 2.1.0+ refuses a parser rule eventwatch could load
sync_cli release <repo> fplProcessor  # 2.1.1+ refuses an fpl_rule with no channel
```

After the tenant syncs, delete the `_local` rule, channel rule, caller and pipe **before** the
released rule runs, or both write behavior events for the same events.

## Gotchas

- **Tenant switching:** only `ingext config use <cluster>:<namespace>` switches; the flags do
  not. Commands against the previous tenant return plausible data. Switch back afterwards.
- **`ts` in milliseconds** is the easiest mistake: FPL's `@timestamp` is ms; divide and round
  to the slot.
- **Numbers in a hit line's valueMap.** Use strings; a `first` correlation on a number breaks.
- **A rule named in a line must be a parser rule.** Emitting a static rule's name is dropped
  (`notParser`) — FPL cannot add hits to eventwatch's rules.
- **`@behaviors` must stay an array of strings.** A string or object there makes eventwatch
  drop its own static tags without a word, and a non-string element breaks its tag action.
- **`:` in a rule or correlation name** makes the line unparseable; `sync_cli` refuses it.
- **Sample events and `@type`:** `"@type":"event"` is a legacy filter; parser rules do not use
  it. Some old static rules only hit in `rule_test` when the sample carries it — add it when
  comparing against one of those, not to the parser rule's samples.
- **`rule_get` prints to stderr**; capture with `2>&1`.
