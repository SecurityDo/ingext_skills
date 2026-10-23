#!/usr/bin/env python3
"""Evaluate the health of a tenant's installed applications and render the report (HTML + CSV).

The status logic is a port of the Fluency 9 Applications page (ApplicationsPage.tsx, activity.ts,
traffic.ts, pipeline.ts): each installed application instance is Running, Error, Attention,
Disabled or Other. Every number is computed here from the saved raw tool results in
--evidence-dir; nothing is typed in by hand. Missing evidence is stated, never assumed healthy.

Evidence files:
  apps.json         scrub_connectors.py output (from list_connectors): state, wiring, resource ids
  integrations.json scrub_connectors.py output (from list_integrations): live integration ids
  streams.json      stream_list_configs: live router, pipe, sink and source ids
  bytes24.json      prom_query, 24 h: sum by (id, component, action) (increase(
                    platform_component_bytes{action=~"input|output|error"}[24h])) > 0
  active90.json     prom_query, 90 d: sum by (component, id) (increase(platform_component_bytes[90d])) > 0
  dumps.json        list_resource_dumps (optional; informational freshness of resource sources)

Status, first match wins (as the Applications page does):
  error      state is Aborted, or the instance carries an error message
  disabled   any source of the application is disabled
  attention  inactive (state Inactive, or no traffic and a component with no recorded activity),
             or a missing component, or state WaitingForConsent / Aborted
  running    traffic in the last 24 h, or state Running
  other      anything else
"""
import argparse, csv, datetime, html, json, os, sys

# Sources of these integrations write to a resource index, not through a router (constants.js).
NO_CONNECTION = {"Office365ResourceWatch", "SentinelOne", "LDAP", "Qualys", "TenableCloud", "BlackKite", "Bitwarden",
                 "MSDefenderEndpoint", "FalconResource", "GSuiteResource", "NetskopeResource"}
KINDS = {"error": ("Error", "#b91c1c"), "attention": ("Attention", "#b45309"), "disabled": ("Disabled", "#64748b"),
         "other": ("Other", "#64748b"), "running": ("Running", "#15803d")}
ORDER = {"error": 0, "attention": 1, "disabled": 2, "other": 3, "running": 4}


def load(d, name):
    try:
        with open(os.path.join(d, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def prom(raw):
    """{(component, action, id): value}"""
    out = {}
    for s in (raw or {}).get("series", []):
        m = s.get("metric", {})
        pts = s.get("points") or [{}]
        k = (m.get("component"), m.get("action"), m.get("id"))
        out[k] = out.get(k, 0) + int(pts[-1].get("value", 0) or 0)
    return out


def is_resource_source(s):
    integ = s.get("integration") if s.get("type") == "plugin" else (s.get("integration") or s.get("type"))
    return bool(integ and integ in NO_CONNECTION)


def size(n):
    if n is None:
        return "-"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024 or u == "PB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


def esc(s):
    return html.escape(str(s))


def pill(kind, label):
    return '<span class="pill" style="background:%s">%s</span>' % (KINDS[kind][1], esc(label))


def evaluate(app, live_ids, ever_active, b24):
    sources, routers, pipes, sinks = app["sources"], app["routers"], app["pipes"], app["sinks"]
    state = app.get("state") or ""
    error = state == "Aborted" or bool(app.get("errorMsg"))
    disabled = any(s.get("disabled") for s in sources)

    eligible = [s for s in sources if not is_resource_source(s) or s.get("router")]
    resource_only = bool(sources) and not eligible and not routers and not pipes
    applicable = not resource_only
    inp = sum(b24.get(("datasource", "input", s["id"]), 0) for s in eligible if s.get("id"))
    out = sum(b24.get(("datasink", "output", k["id"]), 0) for k in sinks if k.get("id"))
    has_traffic = applicable and (inp > 0 or out > 0)

    inactive_components = False
    if ever_active is not None and not has_traffic:
        comps = [s for s in sources if not s.get("disabled") and not is_resource_source(s)] + routers + pipes + sinks
        inactive_components = any(c.get("id") and c["id"] not in ever_active for c in comps)
    active = (not error) and has_traffic
    inactive = (not error) and (not active) and (state == "Inactive" or inactive_components)

    missing = False
    if live_ids is not None:
        for res in sources + routers + pipes + sinks + app["integrations"]:
            if res.get("id") and res["id"] not in live_ids:
                missing = True
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

    labels = [KINDS[kind][0]]
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

    comp_ids = [("datasource", s["id"], s["name"]) for s in sources if s.get("id")] + [("router", r["id"], r["name"]) for r in routers if r.get("id")] \
        + [("pipe", p["id"], p["name"]) for p in pipes if p.get("id")] + [("datasink", k["id"], k["name"]) for k in sinks if k.get("id")]
    seen, err_rows = set(), []
    for comp, cid, name in comp_ids:
        if cid in seen:
            continue
        seen.add(cid)
        v = b24.get((comp, "error", cid), 0)
        if v > 0:
            err_rows.append((comp, name, v))
    return dict(kind=kind, labels=labels, signals=signals, input=inp if applicable else None, output=out if applicable else None,
                error_bytes=sum(v for _, _, v in err_rows), err_rows=err_rows, resource_only=resource_only, state=state,
                missing=missing, inactive=inactive, disabled=disabled)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--captured-at", default=None, help="ISO time of the pull; default now (UTC)")
    a = ap.parse_args()
    d = a.evidence_dir
    now = datetime.datetime.fromisoformat(a.captured_at.replace("Z", "+00:00")).replace(tzinfo=None) if a.captured_at \
        else datetime.datetime.utcnow().replace(microsecond=0)

    apps_raw, b24_raw = load(d, "apps.json"), load(d, "bytes24.json")
    if not apps_raw or not apps_raw.get("entries"):
        sys.exit("apps.json is missing or lists no applications; run list_connectors and scrub_connectors.py first")
    if b24_raw is None:
        sys.exit("bytes24.json is missing; the traffic counters are needed to decide Running vs Inactive")
    b24 = prom(b24_raw)
    act_raw = load(d, "active90.json")
    ever_active = {k[2] for k in prom(act_raw)} if act_raw is not None else None
    streams, ints, dumps = load(d, "streams.json"), load(d, "integrations.json"), load(d, "dumps.json")
    live_ids = None
    if streams is not None and ints is not None:
        live_ids = set()
        for r in streams.get("routers", []):
            live_ids.add(r.get("id"))
            live_ids.update(p.get("id") for p in r.get("pipes", []))
        live_ids.update(x.get("id") for x in streams.get("sinks", []))
        live_ids.update(x.get("id") for x in streams.get("sources", []))
        live_ids.update(x.get("id") for x in ints.get("entries", []))

    dump_age = {}
    for e in (dumps or {}).get("entries", []):
        try:
            t = datetime.datetime.fromisoformat(e["createdOn"].replace("Z", "+00:00")[:26]).replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        c = (e.get("customer") or "").lower()
        if c not in dump_age or t > dump_age[c]:
            dump_age[c] = t

    views = []
    for app in apps_raw["entries"]:
        v = evaluate(app, live_ids, ever_active, b24)
        v["app"] = app
        views.append(v)
    views.sort(key=lambda v: (ORDER[v["kind"]], v["app"]["displayName"] or "", v["app"]["instance"] or ""))
    cnt = {k: sum(1 for v in views if v["kind"] == k) for k in ORDER}
    tot_in = sum(v["input"] for v in views if v["input"] is not None)
    tot_out = sum(v["output"] for v in views if v["output"] is not None)

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["application", "instance", "display_name", "connector_state", "status", "reasons", "input_bytes_24h", "output_bytes_24h", "error_bytes_24h", "signals"])
        for v in views:
            ap_ = v["app"]
            w.writerow([ap_["application"], ap_["instance"], ap_["displayName"], v["state"], v["kind"], " | ".join(v["labels"]),
                        "" if v["input"] is None else v["input"], "" if v["output"] is None else v["output"], v["error_bytes"], " | ".join(v["signals"])])

    rows = "".join("<tr><td>%s<br><span class=\"small\">%s</span></td><td>%s</td><td>%s / %s</td><td>%s</td><td>%s</td></tr>" % (
        esc(v["app"]["displayName"]), esc(v["app"]["instanceName"] or v["app"]["instance"] or ""),
        " ".join(pill(v["kind"], l) for l in v["labels"]),
        "n/a" if v["input"] is None else size(v["input"]), "n/a" if v["output"] is None else size(v["output"]),
        size(v["error_bytes"]), esc(", ".join(v["signals"]) or "-")) for v in views)
    err_rows = [(v["app"]["displayName"], c, n, b) for v in views for c, n, b in v["err_rows"]]
    err_tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(x[0]), esc(x[1]), esc(x[2]), size(x[3])) for x in err_rows) \
        or '<tr><td colspan="4">No component reported error bytes in the last 24 hours.</td></tr>'
    res_rows = []
    for v in views:
        for s in v["app"]["sources"]:
            if is_resource_source(s):
                t = dump_age.get((s["name"] or "").lower())
                res_rows.append("<tr><td>%s</td><td>%s</td></tr>" % (esc(s["name"]), esc(("%.1f h ago" % ((now - t).total_seconds() / 3600)) if t else "no dump listed")))
    res_tr = "".join(res_rows) or '<tr><td colspan="2">No resource sources.</td></tr>'
    attn = [v for v in views if v["kind"] in ("error", "attention")]
    actions = ["<li><b>%s</b>: %s. %s</li>" % (esc(v["app"]["displayName"]), esc(" · ".join(v["labels"])),
               "Open the application and read its error." if v["kind"] == "error" else "Check the installation and its data sources.") for v in attn] \
        or ["<li>No application needs attention from this evidence.</li>"]
    title = "%s Installed Applications Health Report" % a.tenant_name
    head = "no application is in error or needs attention" if not attn else "%d application(s) need attention or are in error" % len(attn)
    kp = "".join('<div class="kpi"><div class="nn" style="color:%s">%s</div><div class="small">%s</div></div>' % (c, v, l) for v, l, c in [
        (len(views), "Installed", "#0f172a"), (cnt["running"], "Running", "#15803d"), (cnt["error"], "Error", "#b91c1c"),
        (cnt["attention"] + cnt["disabled"] + cnt["other"], "Inactive or needs attention", "#b45309"), ("%s / %s" % (size(tot_in), size(tot_out)), "In / out, 24 h", "#0f172a")])
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>
*{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;color:#0f172a;margin:0;font-size:13px;line-height:1.5}}
.wrap{{max-width:7.1in;margin:0 auto}}h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:16px;margin:22px 0 8px;border-bottom:2px solid #0f766e;padding-bottom:4px;break-after:avoid;page-break-after:avoid}}
.sub{{color:#475569;margin-bottom:12px}}.lead{{border-left:5px solid #0f766e;background:#f0fdfa;padding:10px 14px;margin:10px 0;break-inside:avoid}}
.lead b{{color:#0f766e}}.lead p{{margin:4px 0}}.kpis{{display:flex;gap:10px;margin:10px 0}}
.kpi{{flex:1;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;break-inside:avoid}}.kpi .nn{{font-size:20px;font-weight:700}}
.call{{border:1px solid #fcd34d;background:#fffbeb;border-radius:6px;padding:8px 12px;margin:10px 0;break-inside:avoid}}
table{{width:100%;border-collapse:collapse;table-layout:fixed;font-size:11.5px}}th,td{{border-bottom:1px solid #e2e8f0;padding:5px 6px;text-align:left;vertical-align:top;word-wrap:break-word}}
th{{background:#f1f5f9}}tr{{break-inside:avoid}}.pill{{color:#fff;border-radius:10px;padding:1px 8px;font-size:10.5px;white-space:nowrap;display:inline-block;margin:1px 0}}
.small{{font-size:11px;color:#475569}}ul{{margin:4px 0 4px 18px;padding:0}}h2+*{{break-before:avoid;page-break-before:avoid}}
</style></head><body><div class="wrap"><h1>{title}</h1>
<div class="sub">Tenant: {tname} (grid account <code>{tenant}</code>) &middot; Last 24 hours to {now} UTC &middot; Site: {site}</div>
<div class="lead">
<p><b>What the evidence shows.</b> {tname} has {n} installed applications: {c_run} running, {c_err} in error, {c_att} needing attention, {c_dis} disabled, {c_oth} other. {head}.</p>
<p><b>Why it matters.</b> An application in error or waiting for consent is a data source the customer believes is monitored but is not delivering.</p>
<p><b>Result.</b> Status follows the Fluency 9 Applications page: the connector state, recent traffic through the application's sources and sinks, and whether its components exist and have ever carried data.</p>
<p><b>Evidence strength.</b> Confirmed: connector state and 24-hour traffic and error bytes. Inferred: "has ever carried data", from 90 days of platform counters. Unknown: alert history, disabled state and last-active times, which the connector does not expose here.</p></div>
<div class="kpis">{kp}</div>
<h2>Installed applications</h2>
<table><colgroup><col style="width:30%"><col style="width:22%"><col style="width:20%"><col style="width:12%"><col style="width:16%"></colgroup><tr><th>Application</th><th>Status</th><th>In / out, 24 h</th><th>Error bytes</th><th>Signals</th></tr>{rows}</table>
<div class="call">Running means the connector reports Running or the application moved data in the last 24 hours. A Running connector does not prove its data is current: a resource source (Office 365 resource watch, Qualys) has no traffic, so check the freshness table below.</div>
<h2>Error bytes by component</h2>
<table><colgroup><col style="width:30%"><col style="width:18%"><col style="width:32%"><col style="width:20%"></colgroup><tr><th>Application</th><th>Component</th><th>Name</th><th>Error bytes</th></tr>{err_tr}</table>
<h2>Resource sources: freshness</h2>
<table><colgroup><col style="width:60%"><col style="width:40%"></colgroup><tr><th>Source</th><th>Newest dump written</th></tr>{res_tr}</table>
<p class="small">Informational only; it does not change an application's status.</p>
<h2>Recommended actions</h2><ul>{actions}</ul>
<h2>Limits</h2><ul>
<li>Alert and error history for each application, source disabled flags and last-active times are not available through the connector. An application with a recent platform alert but a Running connector therefore shows as Running.</li>
<li>"Inactive" uses 90 days of platform counters as a stand-in for the page's last-active time.</li>
<li>A missing component means a resource the application was installed with no longer exists in the live configuration.</li></ul>
<h2>Methodology</h2><p class="small">Read-only calls through the {site} MCP connector against account <code>{tenant}</code> on {now} UTC: installed applications and their wiring, live stream configuration, integrations, and platform byte counters (24 hours and 90 days). Credentials in the raw connector results were removed before use. A per-application CSV accompanies this report.</p>
</div></body></html>""".format(
        title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), now=now.strftime("%d %b %Y %H:%M"), site=esc(a.site), n=len(views),
        c_run=cnt["running"], c_err=cnt["error"], c_att=cnt["attention"], c_dis=cnt["disabled"], c_oth=cnt["other"], head=head[0].upper() + head[1:],
        kp=kp, rows=rows, err_tr=err_tr, res_tr=res_tr, actions="".join(actions))
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote", a.out, a.csv, "| %d apps: %d running, %d error, %d attention, %d disabled, %d other" % (len(views), cnt["running"], cnt["error"], cnt["attention"], cnt["disabled"], cnt["other"]))


if __name__ == "__main__":
    main()
