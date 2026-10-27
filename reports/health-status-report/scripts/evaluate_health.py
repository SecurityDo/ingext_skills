#!/usr/bin/env python3
"""Evaluate the health of a tenant's installed applications and write health.json.

The status logic is a port of the Fluency 9 Applications page (ApplicationsPage.tsx, activity.ts,
traffic.ts, pipeline.ts): each installed application instance is Running, Error, Attention,
Disabled or Other. Every value is computed here from saved tool results; nothing is typed in.

Two modes, chosen by the input:
  full        --apps apps.json        from scrub_config.py (list_connector_config): state, errors, live
                                      components, last-active times and 24 h byte totals
  state_only  --connectors connectors.json   from reduce_connectors.py (list_connectors): state only.
                                      No traffic, errors or last-active exist, so status comes from the
                                      connector state alone and the limits say so
Optional: --dumps dumps.json (list_resource_dumps) adds the age of each resource feed.

Status, first match wins (as the Applications page does):
  error      state is Aborted, or the instance has an error message, or a component has an error
             state with errors, or whose last alert was raised in the hour before the pull
  disabled   any source has disable set
  attention  inactive (state Inactive, or no traffic and a component with no activity in the
             24 h window), or a missing component, or state WaitingForConsent / Aborted
  running    traffic in the last 24 h, or state Running
  other      anything else
Missing component: a pending action names a resource that is not a live component (types
collector, datalakeIndex, resourceGroup, routerSource are ignored; an invitation counts only
while the state is WaitingForConsent).

  evaluate_health.py (--apps apps.json | --connectors connectors.json) [--dumps dumps.json] --out health.json [--captured-at ISO]
"""
import argparse, datetime, json, re, sys

# Sources of these integrations write to a resource index, not through a router (constants.js).
NO_CONNECTION = {"Office365ResourceWatch", "SentinelOne", "LDAP", "Qualys", "TenableCloud", "BlackKite", "Bitwarden",
                 "MSDefenderEndpoint", "FalconResource", "GSuiteResource", "NetskopeResource"}
LABEL = {"error": "Error", "attention": "Attention", "disabled": "Disabled", "other": "Other", "running": "Running"}
ORDER = {"error": 0, "attention": 1, "disabled": 2, "other": 3, "running": 4}
IGNORED_MISSING = {"collector", "datalakeIndex", "resourceGroup", "routerSource"}  # ApplicationsPage.tsx
HOUR_MS = 3600000


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("cannot read %s: %s" % (path, e))


def parse_iso(t):
    try:
        txt = re.sub(r"(\.\d{6})\d+", r"\1", str(t).replace("Z", "+00:00"))
        d = datetime.datetime.fromisoformat(txt)
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def is_resource_source(s):
    integ = s.get("integration") if s.get("type") == "plugin" else (s.get("integration") or s.get("type"))
    return bool(integ and integ in NO_CONNECTION)


def has_error(app, now_ms):
    if app.get("state") == "Aborted" or app.get("errorMsg"):
        return True
    for es in app.get("errorStates") or []:
        if es.get("errors"):
            return True
        t = parse_iso((es.get("lastAlert") or {}).get("createdOn"))
        if t and t.timestamp() * 1000 > now_ms - HOUR_MS:
            return True
    return False


def has_missing(app, live):
    for act in app.get("actions") or []:
        res, rid = act.get("resource"), act.get("id") or ""
        if not res or res in IGNORED_MISSING:
            continue
        if res == "routerPipe":
            pid = rid.split("-")[1] if "-" in rid else rid
            if pid and pid not in live:
                return True
        elif res == "invitation":
            if app.get("state") == "WaitingForConsent":
                return True
        elif rid and rid not in live:
            return True
    return False


def evaluate_full(app, now_ms):
    sources, routers, pipes, sinks = app["sources"], app["routers"], app["pipes"], app["sinks"]
    state = app.get("state") or ""
    tr, last = app.get("traffic") or {}, app.get("lastActive") or {}
    error = has_error(app, now_ms)
    disabled = any(s.get("disable") for s in sources)
    eligible = [s for s in sources if not is_resource_source(s)]
    resource_only = bool(sources) and not eligible and not routers and not pipes
    applicable = not resource_only
    inp = sum(tr.get(s["id"], {}).get("input", 0) for s in eligible if s.get("id"))
    out = sum(tr.get(k["id"], {}).get("output", 0) for k in sinks if k.get("id"))
    has_traffic = applicable and (inp > 0 or out > 0)
    inactive_components = False
    if not has_traffic:
        comps = [s for s in eligible if not s.get("disable")] + routers + pipes + sinks
        inactive_components = any(c.get("id") and c["id"] not in last for c in comps)
    active = (not error) and has_traffic
    inactive = (not error) and (not active) and (state == "Inactive" or inactive_components)
    live = {x.get("id") for k in ("sources", "routers", "pipes", "sinks", "integrations") for x in app[k]}
    missing = has_missing(app, live)
    if error:
        kind = "error"
    elif disabled:
        kind = "disabled"
    elif inactive or missing or state in ("WaitingForConsent", "Aborted"):
        kind = "attention"
    elif active or state == "Running":
        kind = "running"
    else:
        kind = "other"
    labels = [LABEL[kind]]
    if kind == "attention":
        reasons = []
        if state == "WaitingForConsent":
            reasons.append("Waiting for consent")
        elif missing:
            reasons.append("Missing component")
        if inactive:
            reasons.append("Inactive")
        if state == "Aborted":
            reasons.append("Aborted")
        labels = reasons or labels
    signals = [x for x, on in (("Error", error), ("Missing component", missing or state == "WaitingForConsent"), ("Disabled source", disabled), ("Inactive", inactive)) if on]
    msgs = []
    if app.get("errorMsg"):
        msgs.append({"component": "application", "message": app["errorMsg"]})
    for es in app.get("errorStates") or []:
        if isinstance(es.get("errors"), list):
            msgs += [{"component": es.get("id"), "message": ((x.get("subject") or "") + " " + (x.get("message") or "")).strip()} for x in es["errors"]]
        elif es.get("lastAlert") and (es["lastAlert"].get("subject") or es["lastAlert"].get("message")):
            msgs.append({"component": es.get("id"), "message": ((es["lastAlert"].get("subject") or "") + " " + (es["lastAlert"].get("message") or "")).strip()})
    comp_ids = [("source", s["id"], s["name"]) for s in sources if s.get("id")] + [("router", r["id"], r["name"]) for r in routers if r.get("id")] \
        + [("pipe", p["id"], p["name"]) for p in pipes if p.get("id")] + [("sink", k["id"], k["name"]) for k in sinks if k.get("id")]
    err_rows = [{"component": comp, "name": name, "bytes": tr.get(cid, {}).get("error", 0)} for comp, cid, name in comp_ids if tr.get(cid, {}).get("error", 0) > 0]
    return {"status": kind, "labels": labels, "signals": signals, "inputBytes": inp if applicable else None, "outputBytes": out if applicable else None,
            "errorBytes": sum(r["bytes"] for r in err_rows), "errorRows": err_rows, "errorMessages": msgs, "resourceOnly": resource_only,
            "lastActiveMs": max(last.values()) if last else None, "resourceSources": [s["name"] for s in sources if is_resource_source(s)]}


def evaluate_state_only(app):
    state = app.get("state") or ""
    kind = {"Running": "running", "Aborted": "error", "WaitingForConsent": "attention", "Inactive": "attention"}.get(state, "other")
    labels = {"WaitingForConsent": ["Waiting for consent"], "Inactive": ["Inactive"], "Aborted": ["Aborted"]}.get(state, [LABEL[kind]])
    return {"status": kind, "labels": labels, "signals": [] if kind in ("running", "other") else [labels[0]], "inputBytes": None, "outputBytes": None, "errorBytes": None,
            "errorRows": [], "errorMessages": [], "resourceOnly": False, "lastActiveMs": None, "resourceSources": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps")
    ap.add_argument("--connectors")
    ap.add_argument("--dumps")
    ap.add_argument("--out", required=True)
    ap.add_argument("--captured-at")
    a = ap.parse_args()
    if bool(a.apps) == bool(a.connectors):
        sys.exit("give exactly one of --apps (full) or --connectors (state only)")
    raw = load(a.apps or a.connectors)
    entries = raw.get("entries") or []
    if not entries:
        sys.exit("the input lists no applications; a failed pull is not a healthy tenant")
    now_ms = raw.get("capturedAtMs")
    if a.captured_at:
        now_ms = int(parse_iso(a.captured_at).timestamp() * 1000)
    if not now_ms:
        now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    mode = "full" if a.apps else "state_only"
    apps = []
    for e in entries:
        r = evaluate_full(e, now_ms) if mode == "full" else evaluate_state_only(e)
        r.update(application=e.get("application"), instance=e.get("instance"), displayName=e.get("displayName") or e.get("application"),
                 instanceName=e.get("instanceName"), state=e.get("state"))
        apps.append(r)
    apps.sort(key=lambda r: (ORDER[r["status"]], r["displayName"] or "", r["instance"] or ""))
    counts = {k: sum(1 for r in apps if r["status"] == k) for k in ORDER}

    feeds, newest = [], {}
    if a.dumps:
        for d in load(a.dumps).get("entries", []):
            t = parse_iso(d.get("createdOn"))
            age = (now_ms - t.timestamp() * 1000) / 86400000.0 if t else None
            cust = (d.get("customer") or "")
            feeds.append({"resource": d.get("resource"), "customer": cust, "createdOnMs": int(t.timestamp() * 1000) if t else None, "ageDays": age,
                          "count": d.get("count"), "empty": d.get("count") == 0, "stale": (age is not None and age > 1) or d.get("count") == 0})
            if t and (cust.lower() not in newest or t.timestamp() * 1000 > newest[cust.lower()]):
                newest[cust.lower()] = int(t.timestamp() * 1000)
    for r in apps:
        r["resourceSources"] = [{"name": n, "newestDumpMs": newest.get((n or "").lower())} for n in r["resourceSources"]]
    limits = ["Status follows the Fluency 9 Applications page. A Running connector does not prove its data is current: resource sources have no traffic, so see the resource-feed ages."]
    if mode == "state_only":
        limits.append("State only: the connector gave no traffic, errors, last-active times or live components, so status comes from the connector state alone. An application with a failing source, no recent data or a missing component still reads Running.")
    else:
        limits += ["The connector does not expose a disabled flag beyond a source's disable setting. Only each error state's latest alert is kept.",
                   "Inactive means a component moved no data in the 24-hour window the connector reports; a quiet application (a syslog listener with no senders) shows as Inactive."]
    if not a.dumps:
        limits.append("Resource-feed freshness was not collected.")
    out = {"mode": mode, "capturedAtMs": now_ms, "applications": apps, "counts": counts,
           "totals": {"inputBytes": sum(r["inputBytes"] for r in apps if r["inputBytes"] is not None) if mode == "full" else None,
                      "outputBytes": sum(r["outputBytes"] for r in apps if r["outputBytes"] is not None) if mode == "full" else None},
           "resourceFeeds": feeds if a.dumps else None, "limits": limits}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote %s | %s mode, %d applications: %d running, %d error, %d attention, %d disabled, %d other" % (a.out, mode, len(apps), counts["running"], counts["error"], counts["attention"], counts["disabled"], counts["other"]))


if __name__ == "__main__":
    main()
