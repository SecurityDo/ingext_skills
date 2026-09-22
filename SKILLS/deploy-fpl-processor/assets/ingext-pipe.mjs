#!/usr/bin/env node
// Wire an FPL processor into a tenant's running pipeline, using the ingext-api
// TypeScript client (~/cc/ingext_api/typescript). The client owns auth and the
// provider proxy; nothing here builds a request or handles a token by hand.
//
//   node ingext-pipe.mjs list   --tenant <tenant>
//   node ingext-pipe.mjs wire   --tenant <tenant> --router Varonis-default \
//                               --processor Varonis_Behavior --app Varonis --instance default
//   node ingext-pipe.mjs unwire --tenant <tenant> --router Varonis-default \
//                               --pipe Varonis-default-Behavior --delete-sink
//   node ingext-pipe.mjs tail   --tenant <tenant> --router Varonis-default \
//                               --pipe Varonis-default-Behavior [--status drop] [--limit 5]
//   node ingext-pipe.mjs reload --tenant <tenant> --source Varonis-default
//
// --provider defaults to develop2 and is resolved from /etc/fluency_grid_config.json.
// Add --dry-run to print what wire/unwire would do without calling the API.

import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import os from "node:os";

const GRID_CONFIG = process.env.FLUENCY_GRID_CONFIG ?? "/etc/fluency_grid_config.json";
const API_TS = process.env.INGEXT_API_TS ?? path.join(os.homedir(), "cc/ingext_api/typescript");
const BEHAVIOR_QUEUE = "queue:BehaviorSummary:EventQueue";

function usage(msg) {
  if (msg) console.error(`error: ${msg}\n`);
  console.error(readFileSync(new URL(import.meta.url)).toString().split("\n")
    .filter((l) => l.startsWith("//")).map((l) => l.replace(/^\/\/ ?/, "")).join("\n"));
  process.exit(msg ? 2 : 0);
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) { out._.push(a); continue; }
    const key = a.slice(2);
    if (key === "dry-run" || key === "delete-sink" || key === "help") { out[key] = true; continue; }
    const v = argv[++i];
    if (v === undefined) usage(`--${key} needs a value`);
    out[key] = v;
  }
  return out;
}

// The provider's URL and token. The token is read, never printed.
function provider(name) {
  let cfg;
  try {
    cfg = JSON.parse(readFileSync(GRID_CONFIG, "utf8"));
  } catch (e) {
    usage(`cannot read ${GRID_CONFIG}: ${e.message}`);
  }
  const list = cfg.ingextProviders ?? [];
  const p = list.find((x) => x.name === name);
  if (!p) usage(`no provider ${name}; available: ${list.map((x) => x.name).join(", ")}`);
  return p;
}

async function loadIngext() {
  const entry = path.join(API_TS, "dist/index.js");
  try {
    return await import(pathToFileURL(entry).href);
  } catch (e) {
    usage(`cannot load the ingext-api client from ${entry} (build it with 'npm run build' in ${API_TS}): ${e.message}`);
  }
}

async function topology(ingext) {
  const cfg = await ingext.platform.listConfigs();
  return {
    routers: cfg.routers ?? [],
    pipes: cfg.pipes ?? [],
    sinks: cfg.sinks ?? [],
  };
}

const byRef = (list, ref) => list.find((e) => e && (e.id === ref || e.name === ref));

async function cmdList(ingext) {
  const { routers, pipes, sinks } = await topology(ingext);
  const sinkName = new Map(sinks.map((s) => [s.id, s.name]));
  for (const r of routers) {
    console.log(`Router ${r.name}  (${r.id})`);
    for (const p of pipes.filter((p) => p.routerID === r.id)) {
      const to = (p.sinkIDs ?? []).map((id) => sinkName.get(id) ?? id).join(", ") || "-";
      console.log(`  pipe ${p.name}  (${p.id})  priority=${p.priority ?? 0}  ` +
        `processors=[${(p.processorNames ?? []).join(", ")}]  sinks=[${to}]`);
    }
  }
  console.log(`\nSinks on ${BEHAVIOR_QUEUE}:`);
  for (const s of sinks) {
    if (s.redis?.redis?.queue === BEHAVIOR_QUEUE) console.log(`  ${s.name}  (${s.id})`);
  }
}

async function cmdWire(ingext, args) {
  const { router: routerRef, processor, app, instance } = args;
  if (!routerRef || !processor || !app || !instance) {
    usage("wire needs --router, --processor, --app and --instance");
  }
  const priority = Number(args.priority ?? 2000);
  const pipeName = args.pipe ?? `${app}-${instance}-Behavior`;
  const sinkName = args.sink ?? `Behavior-${app}-${instance}`;
  const tags = [{ name: "application", value: app }, { name: "appInstance", value: instance }];

  // The processor has to be deployed first: a pipe naming one that does not
  // exist is accepted and then fails at run time.
  // getProcessor reports a missing name as an RPC error, not as a null entry.
  let deployed = null;
  try {
    deployed = await ingext.platform.getProcessor(processor);
  } catch (e) {
    if (!/not found/i.test(e.message)) throw e;
  }
  if (!deployed) throw new Error(`processor ${processor} is not deployed on this tenant — deploy it first`);

  const { routers, pipes, sinks } = await topology(ingext);
  const router = byRef(routers, routerRef);
  if (!router) {
    throw new Error(`no router ${routerRef}; available: ${routers.map((r) => r.name).join(", ")}`);
  }
  if (pipes.some((p) => p.routerID === router.id && p.name === pipeName)) {
    console.log(`pipe ${pipeName} already on ${router.name} — nothing to do`);
    return;
  }

  let sink = byRef(sinks, sinkName);
  if (args["dry-run"]) {
    console.log(`would ${sink ? `reuse sink ${sink.name} (${sink.id})` : `create redis sink ${sinkName} on ${BEHAVIOR_QUEUE}`}`);
    console.log(`would add pipe ${pipeName} to ${router.name} (${router.id}) ` +
      `priority=${priority} processors=[${processor}] tags=${JSON.stringify(tags)}`);
    return;
  }

  if (!sink) {
    const resp = await ingext.platform.addDataSink({
      name: sinkName,
      type: "redis",
      redis: { redis: { host: "localhost", port: 6379, queue: BEHAVIOR_QUEUE } },
      flushCount: 1024,
      flushBuffer: 1048576,
      flushInterval: 60,
      tags,
    });
    sink = { id: resp.id, name: sinkName };
    console.log(`sink created: ${sinkName} (${sink.id})`);
  } else {
    console.log(`sink reused: ${sink.name} (${sink.id})`);
  }

  const added = await ingext.platform.addRouterPipe({
    routerID: router.id,
    pipeConfig: {
      name: pipeName,
      id: "",
      routerID: router.id,
      matchAll: false,
      selector: "",
      // A list in the API, but a pipe carries exactly one processor.
      processorNames: [processor],
      sinkIDs: [sink.id],
      priority,
      tags,
    },
  });
  console.log(`pipe created: ${pipeName} (${added.id}) on ${router.name}`);

  // Read back rather than trust the write: priority and tags are the fields a
  // client that does not know about them silently drops.
  const after = await topology(ingext);
  const stored = after.pipes.find((p) => p.id === added.id);
  console.log("stored:", JSON.stringify({
    name: stored?.name, priority: stored?.priority,
    processorNames: stored?.processorNames, sinkIDs: stored?.sinkIDs, tags: stored?.tags,
  }));
}

// platform_event_tail: the most recent events one pipe ended with, per status.
// This is the live-debugging call — it says whether a pipe is seeing traffic at
// all, and what it did with it, without waiting for the next vendor event.
async function cmdTail(ingext, args) {
  const { router: routerRef, pipe: pipeRef } = args;
  if (!routerRef || !pipeRef) usage("tail needs --router and --pipe");
  const limit = Number(args.limit ?? 5);
  const statuses = args.status ? [args.status] : ["pass", "abort", "drop", "error"];

  const { routers, pipes } = await topology(ingext);
  const router = byRef(routers, routerRef);
  if (!router) throw new Error(`no router ${routerRef}`);
  const pipe = pipes.find((p) => p.routerID === router.id && (p.id === pipeRef || p.name === pipeRef));
  if (!pipe) throw new Error(`no pipe ${pipeRef} on ${router.name}`);

  console.log(`${pipe.name} (${pipe.id})  processor=${(pipe.processorNames ?? []).join(",")}`);
  for (const status of statuses) {
    const resp = await ingext.platform.eventTail({ id: pipe.id, status, limit });
    const entries = resp.entries ?? [];
    console.log(`  ${status}: ${entries.length} event(s)`);
    for (const e of entries) {
      const line = typeof e === "string" ? e : JSON.stringify(e);
      console.log(`    ${line.length > 220 ? line.slice(0, 220) + "…" : line}`);
    }
  }
}

// Restart a data source. For a plugin source this re-forks the plugin, which is
// what makes a newly published binary take effect -- publishing to the registry
// is not a deploy on its own.
async function cmdReload(ingext, args) {
  const ref = args.source;
  if (!ref) usage("reload needs --source");
  const cfg = await ingext.platform.listConfigs();
  const src = (cfg.sources ?? []).find((s) => s && (s.id === ref || s.name === ref));
  if (!src) {
    throw new Error(`no data source ${ref}; available: ${(cfg.sources ?? []).map((s) => s.name).join(", ")}`);
  }
  if (args["dry-run"]) {
    console.log(`would reload ${src.name} (${src.id})`);
    return;
  }
  await ingext.platform.sourceReload(src.id);
  console.log(`reloaded: ${src.name} (${src.id})`);
}

async function cmdUnwire(ingext, args) {
  const { router: routerRef, pipe: pipeRef } = args;
  if (!routerRef || !pipeRef) usage("unwire needs --router and --pipe");

  const { routers, pipes, sinks } = await topology(ingext);
  const router = byRef(routers, routerRef);
  if (!router) throw new Error(`no router ${routerRef}`);
  const pipe = pipes.find((p) => p.routerID === router.id && (p.id === pipeRef || p.name === pipeRef));
  if (!pipe) throw new Error(`no pipe ${pipeRef} on ${router.name}`);

  const sinkIDs = args["delete-sink"] ? (pipe.sinkIDs ?? []) : [];
  if (args["dry-run"]) {
    console.log(`would delete pipe ${pipe.name} (${pipe.id}) from ${router.name}`);
    for (const id of sinkIDs) console.log(`would delete sink ${byRef(sinks, id)?.name ?? id} (${id})`);
    return;
  }

  await ingext.platform.deleteRouterPipe({ routerID: router.id, pipeID: pipe.id });
  console.log(`pipe deleted: ${pipe.name} (${pipe.id})`);
  for (const id of sinkIDs) {
    // Only ever delete a sink this pipe was the last user of.
    const others = pipes.filter((p) => p.id !== pipe.id && (p.sinkIDs ?? []).includes(id));
    if (others.length) {
      console.log(`sink ${id} kept — still used by ${others.map((p) => p.name).join(", ")}`);
      continue;
    }
    await ingext.platform.deleteDataSink(id);
    console.log(`sink deleted: ${byRef(sinks, id)?.name ?? id} (${id})`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  if (!cmd || args.help) usage(cmd ? null : "a command is required: list | wire | unwire | tail | reload");
  if (!args.tenant) usage("--tenant is required");

  const p = provider(args.provider ?? "develop2");
  const { Ingext } = await loadIngext();
  const ingext = new Ingext({ url: p.url, token: p.token, gridAccount: args.tenant });
  console.log(`${p.name} -> ${p.url}  tenant=${args.tenant}`);

  try {
    if (cmd === "list") await cmdList(ingext);
    else if (cmd === "wire") await cmdWire(ingext, args);
    else if (cmd === "unwire") await cmdUnwire(ingext, args);
    else if (cmd === "tail") await cmdTail(ingext, args);
    else if (cmd === "reload") await cmdReload(ingext, args);
    else usage(`unknown command ${cmd}`);
  } finally {
    await ingext.close();
  }
}

main().catch((e) => {
  console.error(`failed: ${e.message}`);
  process.exit(1);
});
