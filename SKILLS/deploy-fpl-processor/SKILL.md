---
name: deploy-fpl-processor
version: 1.0.0
description: >
  Deploy an FPL processor to an Ingext tenant through a provider proxy, and wire it into the
  tenant's running pipeline. Use this skill whenever the user asks to "deploy a processor",
  "push this parser to <tenant>", "install an FPL script on a customer site", "add a behavior
  pipe", "wire this processor into the pipeline", "roll out <Vendor>_Behavior", or wants a
  script that works locally to start running against a tenant's live data. Covers resolving a
  provider and tenant from the grid config, rehearsing on a scratch tenant, validating the
  mapping against the target tenant's own records before wiring anything, creating the pipe
  and sink the CLI cannot create, verifying signals arrive, and rolling back in one call.
  Also covers publishing a plugin binary and the reload that makes it live, and releasing an
  object to the repo registries with sync_cli so it reaches tenants other than the one it was
  deployed to ("release the processor", "release the application template", "update the
  release/dump files"). Trigger for any request that moves an FPL script, a plugin or an
  application template from a repo onto a tenant.
---

# Deploy an FPL processor to a tenant

A processor that passes its fixtures is not a processor that works. Vendors send shapes no
sample shows, and the only reliable source of those shapes is the target tenant's own data.
This skill deploys in an order that finds those surprises before they reach a pipeline.

The running example is a behavior-signal processor (`<Vendor>_Behavior.js`, forking behavior
events to `queue:BehaviorSummary:EventQueue`), but the sequence holds for any processor.

## Preconditions

Assume all of these are present — they are standard on an operator's machine.

| | |
| --- | --- |
| CLI | `/usr/bin/ingext`, source at `~/cc/ingext_api` |
| TypeScript client | `~/cc/ingext_api/typescript` (`npm run build` produces `dist/`) |
| Provider credentials | `/etc/fluency_grid_config.json` — `ingextProviders[]` of `{name, url, token}` |
| Script + fixtures | e.g. `fplProcessors/code/<Name>.js` and `vendor/<vendor>/` in the Scripts repo |

**Never hand-build an API request or pass a bearer token on a command line.** Two sanctioned
clients own auth: the `ingext` CLI, and the `ingext-api` TypeScript client, which this skill's
`assets/ingext-pipe.mjs` uses. Both take `gridaccount` to reach a tenant through a provider
proxy — `--gridaccount <tenant>` on the CLI, `new Ingext({ url, token, gridAccount })` in TS.
The CLI does not read the grid config (it takes `INGEXT_SITE_URL` + `INGEXT_TOKEN`, see
`assets/env.sh`); the TS helper reads it directly and never prints the token.

If a capability is missing from either client, **extend the client** — the API is the open
`api/ds` surface documented in `~/cc/ingext_api/docs/API_OVERVIEW.md`, and both clients are
thin typed wrappers over it. That is how `gridAccount` and the pipe `priority`/`tags` fields
came to exist in the TS client.

## Step 1 — Target a provider and tenant

```bash
. assets/env.sh develop2          # exports INGEXT_SITE_URL / INGEXT_TOKEN, prints neither
ingext grid list-account          # every tenant on this provider
```

Never echo the token. `--gridaccount` is verified before every command
(`internal/api/grid_api.go`): a non-grid site is rejected rather than silently running
against the provider's own account, and an unknown tenant returns the list of valid ones.

Pick two tenants: the **target**, and a **scratch** tenant to rehearse on (e.g. `titan`).

## Step 2 — Read the target's topology

```bash
node assets/ingext-pipe.mjs list --tenant <tenant>   # routers, their pipes, behavior sinks
ingext stream list-router --gridaccount <tenant>     # the same view from the CLI
```

Both read `platform_list_configs`, which returns `routers`, `pipes`, `sinks`, `sources`,
`connections` and `errorStates` in one call. From it, note:

- the router the processor must hang off (e.g. `Varonis-default` → `rt_...`) and its pipes
- **a sibling app that already does what you are adding.** If the tenant runs Falcon or
  MSDefender behavior signals, its pipe and sink are the authoritative template — match their
  shape rather than inventing one:

```
pipe  Falcon-JetAviation-Behavior   priority 2000, matchAll false,
                                    processorNames ["CSFalcon_Behavior"],
                                    sinkIDs ["sink_..."], tags application/appInstance
sink  Behavior-Falcon-JetAviation   type redis, queue queue:BehaviorSummary:EventQueue,
                                    no datalake block
```

`platform_router_dao` has **no `list` action** — it returns `unknown router action:list`.
`platform_list_configs` is the only inventory call.

## Step 3 — Prove the script locally first

Run the whole fixture directory on the runtime before any tenant sees it:

```bash
.claude/skills/fpl-processor/scripts/fpl-test.sh \
  --script fplProcessors/code/<Name>.js --event vendor/<vendor>
```

Plain `ingext processor test` never echoes `Platform_Sink` output, so a processor that
returns `"drop"` looks inert. The wrapper instruments a scratch copy. Add `--compare HEAD`
when changing a processor that is already live.

## Step 4 — Rehearse on the scratch tenant

```bash
ingext processor add --name <Name> --type fpl_processor \
  --desc "<desc>" --content @fplProcessors/code/<Name>.js --gridaccount titan
ingext processor validate --name <Name> --gridaccount titan
```

`validate` is a compile only. To see forked events *through the proxy* — which proves the
`--gridaccount` path, not just the local profile — instrument a copy by hand:

```bash
sed -E 's/Platform_Sink\(([^,]*), *\{obj: *([A-Za-z_][A-Za-z0-9_]*)\}\)/printf("__SINK__ %s", \2); Platform_Sink(\1, {obj: \2})/g' \
  fplProcessors/code/<Name>.js > /tmp/inst.js
ingext processor test --script /tmp/inst.js --event <fixture> --gridaccount titan 2>&1 >/dev/null \
  | grep -o '__SINK__ .*'
```

`processor add` on a tenant that already has the processor is an error — use
`processor update`, which keeps the id, group, tags and repository.

## Step 5 — Validate the mapping against the target's real records

**This is the step that earns its keep.** Fixtures come from one vendor sample; a tenant runs
every shape the vendor emits. Start with aggregates, which read no content:

```bash
ingext kql "<Table> | where timestamp > ago(7d) | summarize count() by <type>, <severity>" \
  --gridaccount <tenant>
```

Then sample a handful of records and rebuild one into an event envelope the runtime accepts:

```bash
ingext kql "<Table> | where timestamp > ago(7d) | project <every field the processor reads> | take 1" \
  --output /tmp/row.json --gridaccount <tenant>
# then wrap the row: {"@eventType":"<type>","@customer":...,"@timestamp":<ms>,"@<root>":{...}}
ingext processor test --script /tmp/inst.js --event /tmp/real.json --gridaccount <tenant>
```

Feed the real event through before wiring anything. On the Varonis rollout this step found two
defects no fixture could have: the tenant's `assets` were `F:(SSYDPFP01)` and
`jeta.aero(AD-jeta.aero)` — a `<resource>(<data source>)` format, never the UNC paths the
parser expected, so every asset signal would have been silently missing — and a
`severityId` of `3` (Informational) that the mapping did not cover.

Fix the script, add a fixture per newly discovered shape, regenerate the expected outputs, and
only then move on.

## Step 6 — Deploy to the target

```bash
ingext processor add --name <Name> --type fpl_processor \
  --desc "<desc>" --content @fplProcessors/code/<Name>.js --gridaccount <tenant>
ingext processor validate --name <Name> --gridaccount <tenant>
```

A deployed processor nothing references is inert — no pipe runs it. This is a safe place to
stop and confirm with the user before changing data flow.

## Step 7 — Wire it in

Decide first **whether to touch the app template or the deployed components**. Editing the
template (`ingext application update` + reinstall) is the durable path but rewrites the
instance; modifying the deployed router/pipes/sinks leaves the template alone and is
reversible in one call. For a test rollout, prefer the latter and say so.

Wiring needs two objects — a redis sink on the behavior queue, and a pipe on the router that
already exists. `assets/ingext-pipe.mjs` creates both through the TypeScript client:

```bash
node assets/ingext-pipe.mjs wire --tenant <tenant> --router <Router> \
     --processor <Name> --app <App> --instance <Instance> --dry-run
node assets/ingext-pipe.mjs wire --tenant <tenant> --router <Router> \
     --processor <Name> --app <App> --instance <Instance>
```

It names the pipe `<App>-<Instance>-Behavior` and the sink `Behavior-<App>-<Instance>`, gives
the pipe `priority: 2000` and the `application`/`appInstance` tags, refuses to run if the
processor is not deployed, reuses a sink of that name rather than making a second one, does
nothing if the pipe already exists, and reads the pipe back so you can see what was stored
rather than what was sent.

**Adding the pipe is not enough — read the next section before you believe it works.**

**Why not the CLI here.** Stock `ingext stream` cannot make either object: `add-sink` offers
only `datalake|hec|webhook|drop`, and there is no `add-pipe` at all. `add-router` exists but
creates a *new* router whose pipe comes out `priority: 0`, no tags, `sinkIDs: []` — verified
on a scratch tenant. Both client libraries were missing the same two things, and both were
extended rather than worked around:

| Gap | Fixed in |
| --- | --- |
| `gridAccount` (tenant proxy) absent from the TS client | `typescript/src/client.ts`, `ingext.ts`, with tests |
| `priority` / `tags` absent from `StreamPipeConfig` | `typescript/src/types/platform.ts`, `model/platform_model.go` |
| No `add-pipe` / `del-pipe` / `del-router` / `list-router`, no redis sink | `internal/commands/stream.go`, `internal/api/stream_api.go` |

So the Go CLI can now do it too, if you prefer one tool:

```bash
ingext stream add-sink --sink-type redis --name Behavior-<App>-<Instance> \
    --queue queue:BehaviorSummary:EventQueue \
    --tag application=<App> --tag appInstance=<Instance> --gridaccount <tenant>
ingext stream add-pipe --router <Router> --name <App>-<Instance>-Behavior \
    --processor <Name> --sink Behavior-<App>-<Instance> --priority 2000 \
    --tag application=<App> --tag appInstance=<Instance> --gridaccount <tenant>
```

## Step 7b — The upstream pipe has to hand the event on

A router runs its pipes in priority order and **stops at the first pipe that does not return
`"abort"`**. So a behavior pipe added behind an application's main pipe receives nothing
unless that main pipe's processor explicitly hands the event on.

| return | the pipe's own sinks | rest of this pipe | next pipe in the router |
| --- | --- | --- | --- |
| `"pass"` / no return | written | runs | **no — the router stops here** |
| `"abort"` | **not** written | skipped | **yes** |
| `"drop"` | not written | skipped | no — the router stops |
| `"error"`, or a runtime exception | written | skipped | no — treated as pass |

`"abort"` is the only status that continues, and it skips the pipe's own sinks, so the
upstream processor must sink the event itself first:

```js
Platform_Sink("", {obj})
return "abort"
```

`CSFalcon_Adjustments.js:43` is the reference, which is why the Falcon behavior pipe works.
The stock `Plugin_Passthrough` returns `"pass"`, so an app installed with it — the plugin
connectors, Varonis among them — needs its main pipe swapped to a continuing variant
(`Plugin_Passthrough_Continue`: same body, `Platform_Sink("", {obj})` then `return "abort"`):

```bash
ingext stream update-pipe-processor --router <Router> --pipe <MainPipe> \
    --processor Plugin_Passthrough_Continue --gridaccount <tenant>
```

Check this **before** wiring, not after: the symptom of getting it wrong is an
indistinguishable silence — a correct processor, a correctly shaped pipe, and no events,
which looks exactly like a connector that has not polled yet.

Three related traps. A pipe with **no sink configured drops the event** whatever its
processor returns. The new pipe's position comes from `priority`, so read back the router's
`pipeIDs` order rather than assuming — if a `"drop"`-returning behavior pipe sorts ahead of
the main pipe, the main pipe stops receiving data. And **a pipe carries exactly one
processor**: `processorNames` is a list in the API and in both client structs, but the extra
entries are not a supported chain. Chaining is what the pipes themselves are for — one
processor per pipe, handed on with `"abort"`.

## Step 8 — Verify

1. `node assets/ingext-pipe.mjs list --tenant <tenant>` — the router lists the new pipe, with
   the `priority`, sink and tags you sent. `wire` prints the same read-back on creation.
2. Events arrive. Behavior signals land in the `behavior` datalake index, so:

   ```bash
   ingext kql "behavior | where timestamp > ago(3h) | summarize count() by behaviorRule, key, keyType" \
     --gridaccount <tenant>
   ```

   The sibling apps' rules (`Falcon:`, `MSDefender:`) show what healthy output looks like.
   Expect a wait: a polled connector produces signals only when the vendor next has an alert.
3. `errorStates` in `platform_list_configs` stays clean for that router, and pipe drop
   counters do not climb.
4. The upstream data still flows. Wiring a second pipe changes what the first one returns, so
   confirm the original destination — usually the datalake index — is still receiving.

**Do not wait for the vendor to prove the wiring.** `platform_event_tail` shows the most
recent events a pipe ended with, per status, so the chain can be verified against whatever
traffic is already moving:

```bash
node assets/ingext-pipe.mjs tail --tenant <tenant> --router <Router> --pipe <MainPipe>
node assets/ingext-pipe.mjs tail --tenant <tenant> --router <Router> --pipe <NewPipe>
```

Read the two together. The upstream pipe should show its events under **abort** — sunk and
handed on — and the new pipe should show *the same events* under whatever its processor
returned. That is the whole contract, verified directly:

```
Varonis-default (pipe_cgsi8whpa2)  processor=Plugin_Passthrough_Continue
  abort: 5 event(s)     <- handed on
Varonis-default-Behavior (pipe_66fwjwicg8)  processor=Varonis_Behavior
  drop: 3 event(s)      <- same events, gated out as not-an-alert
```

A new pipe showing **0 events under every status** is the signature of the upstream pipe
returning `"pass"` — step 7b — not of a quiet connector. Empty on `pass` but busy on `drop`
means the processor is running and rejecting, which for an eventType-gated behavior processor
is correct behaviour on the vendor's non-alert traffic.

For behavior signals specifically: the rule name and key are armed with a first-occurrence
check downstream, so confirm the rule name is an invariant (a policy or detection name, never
interpolated with a user or a count) and the key is a recurring entity (an account, a
hostname) rather than something per-alert like a document path. Get that wrong and every
event is a first occurrence.

## Debugging a live pipe

| Question | Call |
| --- | --- |
| Is this pipe seeing traffic, and what did it do with it? | `platform_event_tail` — `{id: "pipe_xxxx", status, limit}`, wrapped as `ingext-pipe.mjs tail` |
| What did my `printf` / `console.log` print? | `platform_processor_tail` — `{pipeID, processorName, limit}` |
| Is the router erroring or dropping in aggregate? | `errorStates` and the counters in `platform_list_configs` |

`event_tail` keeps a separate buffer per status (`pass`, `abort`, `drop`, `error`), which is
what makes it diagnostic rather than just a sample: *which* buffer an event lands in names the
branch the processor took.

## Deploying a plugin binary, not a processor

An FPL processor is deployed by `processor add` and takes effect immediately. A
**plugin** is a published binary, and publishing it is not a deploy:

```bash
cmd/plugin_<name>/build.sh latest        # go build, then oras push to public.ecr.aws/ingext
node assets/ingext-pipe.mjs reload --tenant <tenant> --source <Source>
ingext stream reload-source --source <Source> --gridaccount <tenant>   # the same call
```

The reload (`platform_source_reload`) restarts the data source, which re-forks
the plugin; the fork re-resolves the tag's digest and re-downloads when it has
changed. Without it the source keeps running the binary it started with until
platform-0 restarts — the image is published and nothing happens, which reads
exactly like a build that did not work.

Three things worth checking first:

- **Which tag the account resolves.** The pin lives in `plugin_config.json` in
  the account's `account-config` configmap; an account without one falls back to
  `latest`. `latest` is not an alias for the newest numbered build and has no
  rollback target, so it is right for a plugin deployed to exactly one tenant and
  wrong for a fleet.
- **Resident or routed.** A stream plugin runs resident (forked in platform-0)
  unless the account routes it to the cluster plugin service, which needs both an
  approved integration and a published `:job` build — `oras repo tags` shows
  whether one exists. A routed plugin picks up a new binary on its next poll pod
  without any reload; a resident one does not.
- **What is in the build.** Build from a clean checkout, not a dirty working
  tree: `git worktree add /tmp/build HEAD`. Confirm with `go tool nm` or
  `strings` that the binary contains what you meant and nothing you did not.

## Releasing to the repo registries

Deploying to a tenant puts an object on **that** tenant. The Scripts repo is how
it reaches any other one: `ingext import` installs from the repo, and it reads
the `<resource>_release.json` / `<resource>_dump.json` registries at the repo
root, not the files on disk. An object committed but never released exists for
nobody — and a template naming a processor that is not in the registry cannot
install at all, because the processor never arrives.

`sync_cli` regenerates those registries from the repo:

```bash
sync_cli release /home/kun/github/Scripts application
sync_cli release /home/kun/github/Scripts schema
sync_cli release /home/kun/github/Scripts fplProcessor
sync_cli release /home/kun/github/Scripts entityinfo
sync_cli release /home/kun/github/Scripts rule
```

The resource name is the registry file's prefix, so the same command covers
`facet`, `filter`, `report`, `fplReport`, `fpl2Report` and `processor` too. Run
the ones your change touched; running the others is harmless and a no-op.

**Commit first.** Each entry records `contentCommit` and `contentGitHash` from
git, so releasing a dirty tree pins the entry to the previous commit. The order
is: write the object and its `meta/` entry → commit → `sync_cli release` →
commit the registries (the repo's convention for that second commit is the
single word `release`).

Four things that decide whether an object is picked up at all:

- **It needs a `meta/` entry.** `sync_cli` walks the registered objects, not the
  directory. A processor whose `.js` exists with no `meta/*.json` is skipped
  silently — which is also why a repo full of untracked work in progress does
  not leak into a release.
- **Its id must already be allocated**, and the registries are where you look to
  find a free one: take the max across `<resource>_release.json` and
  `<resource>_dump.json` and go one past it. Not `meta/`, which is only the
  objects someone happened to write down.
- **`gitPath` must point at the object's own file.** A meta copied from a
  sibling keeps the sibling's path and releases the wrong content.
- **`lastComment` is the whole commit message.** A multi-paragraph message ends
  up verbatim in the registry JSON, where every neighbouring entry is a short
  phrase. Keep the subject line of a released commit terse.

Verify before committing: diff the registries against what they were, by entry,
rather than trusting the totals printed at the end.

```bash
git diff --stat *_release.json *_dump.json
```

The expected shape of a release that adds one processor and changes one template
is exactly three files: `+1` in `fplProcessor_release.json` and
`fplProcessor_dump.json`, and a changed `contentCommit` on that one template in
`application_release.json`. Anything else in the diff is something you did not
mean to release.

## Step 9 — Rollback

```bash
node assets/ingext-pipe.mjs unwire --tenant <tenant> --router <Router> \
     --pipe <App>-<Instance>-Behavior --delete-sink
ingext processor del --name <Name> --gridaccount <tenant>     # optional; inert once unwired
```

Deleting the pipe stops the signals immediately and touches nothing else. `--delete-sink`
removes the sink too, but only after checking no other pipe still points at it.

## Gotchas worth knowing before they cost an hour

- **`$__timeFilter` is not KQL here.** Use `where timestamp > ago(7d)`.
- **`| take 1` returns only the columns the query mentions.** Project every field explicitly
  or you will get two columns and think the data is empty.
- **A scratch tenant cannot rehearse the data path**, only the mechanics, unless it runs the
  same app. Check with `application list` / `platform_list_configs` before assuming.
- **Clean up the rehearsal** with `ingext stream del-router --router <name>`; `unwire` takes
  the pipe and sink. Stock builds have no `del-router`, which is how a scratch router outlives
  the rehearsal that created it.
- **Tagging a hand-made pipe `application=<App>`** matches the app-installed pattern, which
  also means a future template that ships its own pipe will collide with it. Whoever lands
  that template change deletes the hand-made pipe first.
- **Swapping the main pipe to a continuing processor changes a live path.** It is the one
  edit in this procedure that touches data already flowing, so make it deliberately and check
  the original destination afterwards (step 8.4).
