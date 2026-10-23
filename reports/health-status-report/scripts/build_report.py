#!/usr/bin/env python3
"""Evaluate a tenant's data sources and render the Data-Source Health & Status report (HTML + CSV).

This is a port of the Fluency MSSP `evaluate_data_sources` engine onto the tenant connector's own
tools. Every number is computed here from the saved raw tool results in --evidence-dir; nothing
is typed in by hand. A source with no evidence is shown as such, never as healthy.

Evidence files (the raw JSON each tool returned):
  streams.json   stream_list_configs                     routers, pipes, sources
  bytes.json     prom_query   sum by (id, application, component, action)
                              (increase(platform_component_bytes{component=~"datasource|pipe"}[24h])) > 0
  counts.json    prom_query   same query on platform_component_total (event counts)
  dumps.json     list_resource_dumps                     optional; freshness of resource fetchers

Verdict surface is exactly ok / error / inactive, decided by the four counters only:
  1. resource fetcher                      -> ok (health comes from the freshness probe below)
  2. significant bytes_errored, or source-side errors > 0   -> error
  3. bytes_received == 0 and bytes_passed == 0             -> inactive
  4. otherwise                                              -> ok
bytes_dropped and bytes_aborted are never failure signals.
"""
import argparse, csv, datetime, html, json, os, re, sys

ERROR, INACTIVE, OK = "error", "inactive", "ok"
FETCHER_APPS = {"LDAP", "Qualys", "Salesforce", "Office365ResourceWatch", "SentinelOneAPI"}
ABS_FLOOR = 1024          # bytes_errored below 1 KB is round-off
REL_FLOOR = 1e-4          # and below 0.01% of throughput
PILL = {ERROR: ("Error", "#b91c1c"), INACTIVE: ("Inactive", "#64748b"), OK: ("OK", "#15803d")}


def load(d, name):
    try:
        with open(os.path.join(d, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def index(prom):
    """{(component, action, id): value} summed over series; {id: application}."""
    vals, apps = {}, {}
    for s in (prom or {}).get("series", []):
        m = s.get("metric", {})
        pts = s.get("points") or [{}]
        v = pts[-1].get("value", 0) or 0
        k = (m.get("component"), m.get("action"), m.get("id"))
        vals[k] = vals.get(k, 0) + int(v)
        if m.get("id") and m.get("application"):
            apps[m["id"]] = m["application"]
    return vals, apps


def significant_error(errored, passed):
    if errored <= 0 or errored < ABS_FLOOR:
        return False
    total = errored + max(0, passed)
    return total <= 0 or errored / total >= REL_FLOOR


def is_fetcher(app, has_router):
    if has_router or not app:
        return False
    return app in FETCHER_APPS or app.endswith("ResourceWatch") or app.endswith("API")


def classify(received, passed, errored, src_errors, fetcher):
    if fetcher:
        return OK
    if significant_error(errored, passed) or src_errors > 0:
        return ERROR
    if received <= 0 and passed <= 0:
        return INACTIVE
    return OK


def size(n):
    if n is None:
        return "not collected"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


def num(n):
    return "{:,}".format(n) if isinstance(n, int) else "not collected"


def age_text(delta):
    h = delta.total_seconds() / 3600
    if h < 1:
        return "%d min ago" % max(0, int(delta.total_seconds() // 60))
    if h < 48:
        return "%.1f h ago" % h
    return "%.1f days ago" % (h / 24)


def esc(s):
    return html.escape(str(s))


def pill(v):
    t, c = PILL[v]
    return '<span class="pill" style="background:%s">%s</span>' % (c, t)


def bars(rows, color, w=520):
    if not rows:
        return '<p class="small">No data.</p>'
    mx = max(v for _, v in rows) or 1
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (w, 26 * len(rows))]
    for i, (k, v) in enumerate(rows):
        y, bw = i * 26, max(2, int((w - 330) * v / mx))
        out.append('<text x="0" y="%d" font-size="12" fill="#334155">%s</text>' % (y + 17, esc(k[:30])))
        out.append('<rect x="210" y="%d" width="%d" height="16" rx="3" fill="%s"/>' % (y + 4, bw, color))
        out.append('<text x="%d" y="%d" font-size="12" fill="#334155">%s</text>' % (216 + bw, y + 17, size(v)))
    out.append("</svg>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--stale-hours", type=int, default=24)
    ap.add_argument("--captured-at", default=None, help="ISO time of the pull; default now (UTC)")
    a = ap.parse_args()
    now = datetime.datetime.fromisoformat(a.captured_at.replace("Z", "+00:00")).replace(tzinfo=None) if a.captured_at \
        else datetime.datetime.utcnow().replace(microsecond=0)

    streams = load(a.evidence_dir, "streams.json")
    by_bytes, apps_b = index(load(a.evidence_dir, "bytes.json"))
    by_count, apps_c = index(load(a.evidence_dir, "counts.json"))
    dumps = load(a.evidence_dir, "dumps.json")
    if not streams or not streams.get("sources"):
        sys.exit("streams.json is missing or lists no sources; run stream_list_configs first")
    if load(a.evidence_dir, "bytes.json") is None:
        sys.exit("bytes.json is missing; the throughput counters are the only input to the verdict")
    apps = {**apps_c, **apps_b}

    routers = streams.get("routers") or []
    src_router = {}
    for r in routers:
        for sname in r.get("sources") or []:
            src_router[sname] = r
    per_router, router_in = {}, {}
    for sname, r in src_router.items():
        per_router[r["id"]] = per_router.get(r["id"], 0) + 1
    for s in streams["sources"]:
        r = src_router.get(s.get("name") or s["id"])
        if r:
            router_in[r["id"]] = router_in.get(r["id"], 0) + by_bytes.get(("datasource", "input", s["id"]), 0)

    dump_age = {}
    for e in (dumps or {}).get("entries", []):
        try:
            t = datetime.datetime.fromisoformat(e["createdOn"].replace("Z", "+00:00")[:26]).replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        c = e.get("customer", "").lower()
        if c not in dump_age or t > dump_age[c]:
            dump_age[c] = t

    rows, findings = [], []
    for s in streams["sources"]:
        sid, name = s["id"], s.get("name") or s["id"]
        router = src_router.get(name)
        share = max(per_router.get(router["id"], 1), 1) if router else 1
        pipes = [p["id"] for p in router.get("pipes", [])] if router else []
        received = by_bytes.get(("datasource", "input", sid), 0)
        # Sources on one router share its pipe counters. Split them in proportion to the bytes
        # each source received; with no input anywhere on the router, split evenly.
        total_rin = router_in.get(router["id"], 0) if router else 0
        frac = (received / total_rin) if total_rin > 0 else (1.0 / share)

        def pipe_sum(action, table):
            return int(sum(table.get(("pipe", action, pid), 0) for pid in pipes) * frac)

        app = apps.get(sid) or (name.split("-")[0] if "-" in name else None)
        events_in = by_count.get(("datasource", "input", sid), 0)
        src_err = by_count.get(("datasource", "error", sid), 0)
        passed, dropped = pipe_sum("pass", by_bytes), pipe_sum("drop", by_bytes)
        aborted, errored = pipe_sum("abort", by_bytes), pipe_sum("error", by_bytes)
        fetcher = is_fetcher(app, router is not None)
        health = classify(received, passed, errored, src_err, fetcher)
        row = dict(id=sid, name=name, type=s.get("type", ""), app=app or "", router=router["name"] if router else "",
                   shared=share if router and share > 1 else 0, fetcher=fetcher, health=health, received=received,
                   events_in=events_in, passed=passed, dropped=dropped, aborted=aborted, errored=errored, src_err=src_err,
                   fresh=None, age=None, lineage="histogram_24h")
        if fetcher:
            t = dump_age.get(name.lower())
            if t is None:
                row["fresh"], row["lineage"] = "unknown", "freshness_probe (no dump listed)"
            else:
                row["age"] = now - t
                row["fresh"] = "fresh" if row["age"] <= datetime.timedelta(hours=a.stale_hours) else "stale"
                row["lineage"] = "freshness_probe"
                if row["fresh"] == "stale":
                    findings.append(dict(kind="source_stale_resources", source=name, detail="resource index last written %s (limit %d h)" % (age_text(row["age"]), a.stale_hours)))
        if health == ERROR:
            why = ("transform errors: %s errored in 24h" % size(errored)) if significant_error(errored, passed) else "source-side errors: %s in 24h" % num(src_err)
            findings.append(dict(kind="source_error", source=name, detail=why))
        rows.append(row)

    by_h = {OK: 0, ERROR: 0, INACTIVE: 0}
    for r in rows:
        by_h[r["health"]] += 1
    err_findings = [f for f in findings if f["kind"] in ("source_error", "source_stale_resources")]
    if not rows:
        verdict = "no_sources_configured"
    elif err_findings:
        verdict = "error"
    elif by_h[OK] > 0:
        verdict = "ok"
    else:
        verdict = "inactive"
    n_err_src = sum(1 for f in findings if f["kind"] == "source_error")
    n_stale = sum(1 for f in findings if f["kind"] == "source_stale_resources")
    total_in = sum(r["received"] for r in rows)
    total_pass = sum(r["passed"] for r in rows)

    order = {ERROR: 0, OK: 1, INACTIVE: 2}
    rows.sort(key=lambda r: (order[r["health"]], -r["received"], r["name"]))
    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "type", "application", "router", "resource_fetcher", "verdict", "bytes_received_24h", "events_received_24h",
                    "bytes_passed_24h", "bytes_dropped_24h", "bytes_aborted_24h", "bytes_errored_24h", "source_errors_24h", "freshness", "lineage"])
        for r in rows:
            w.writerow([r["name"], r["type"], r["app"], r["router"], "yes" if r["fetcher"] else "no", r["health"], r["received"], r["events_in"],
                        r["passed"], r["dropped"], r["aborted"], r["errored"], r["src_err"], (r["fresh"] or ""), r["lineage"]])

    tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r["name"]), esc(r["app"] or r["type"]), pill(r["health"]),
        "n/a (fetcher)" if r["fetcher"] else size(r["received"]), "n/a (fetcher)" if r["fetcher"] else size(r["passed"]) + (" *" if r["shared"] else ""),
        "n/a" if r["fetcher"] else ("%s / %s / %s" % (size(r["dropped"]), size(r["aborted"]), size(r["errored"]))),
        esc(r["lineage"])) for r in rows)
    f_rows = [r for r in rows if r["fetcher"]]
    fresh_tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r["name"]), esc(age_text(r["age"]) if r["age"] is not None else "no dump listed"),
        {"fresh": "Fresh", "stale": "Stale", "unknown": "Unknown"}[r["fresh"]]) for r in f_rows) or '<tr><td colspan="3">No resource fetchers on this tenant.</td></tr>'
    top = [(r["name"], r["received"]) for r in sorted(rows, key=lambda r: -r["received"]) if r["received"] > 0][:8]
    err_tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(f["source"]), esc(f["kind"]), esc(f["detail"])) for f in err_findings) \
        or '<tr><td colspan="3">No source is in error and no resource index is stale.</td></tr>'
    quiet = [r for r in rows if r["health"] == INACTIVE]
    actions = []
    for f in err_findings:
        if f["kind"] == "source_error":
            actions.append("<li><b>%s</b>: investigate the pipe or source behind the errors (%s). Page-worthy.</li>" % (esc(f["source"]), esc(f["detail"])))
    for f in err_findings:
        if f["kind"] == "source_stale_resources":
            actions.append("<li><b>%s</b>: the resource fetcher has not refreshed its index (%s). Check the connector and its schedule; some fetchers run less often than daily.</li>" % (esc(f["source"]), esc(f["detail"])))
    if quiet:
        actions.append("<li><b>%d inactive source(s)</b> carried no data in 24 hours. That is not a finding by itself; confirm a source you expect to be busy is meant to be quiet.</li>" % len(quiet))
    if not actions:
        actions.append("<li>No action needed from this evidence.</li>")
    shared_note = "<p class=\"small\">* Pipe counters are shared by the sources on one router and split in proportion to the bytes each source received.</p>" if any(r["shared"] for r in rows) else ""

    title = "%s Data-Source Health & Status Report" % a.tenant_name
    head = {"error": "has sources that need attention", "ok": "has data flowing from its sources", "inactive": "has no data flowing", "no_sources_configured": "has no sources configured, so it is not being monitored"}[verdict]
    kp = "".join('<div class="kpi"><div class="nn" style="color:%s">%s</div><div class="small">%s</div></div>' % (c, v, l) for v, l, c in
                 [(len(rows), "Configured sources", "#0f172a"), (by_h[ERROR], "In error", "#b91c1c"), (by_h[INACTIVE], "Inactive", "#64748b"), (by_h[OK], "OK", "#15803d"), (size(total_in), "Received, 24 h", "#0f172a")])
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>
*{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;color:#0f172a;margin:0;font-size:13px;line-height:1.5}}
.wrap{{max-width:7.1in;margin:0 auto}}h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:16px;margin:22px 0 8px;border-bottom:2px solid #0f766e;padding-bottom:4px;break-after:avoid;page-break-after:avoid}}
.sub{{color:#475569;margin-bottom:12px}}.lead{{border-left:5px solid #0f766e;background:#f0fdfa;padding:10px 14px;margin:10px 0;break-inside:avoid}}
.lead b{{color:#0f766e}}.lead p{{margin:4px 0}}.kpis{{display:flex;gap:10px;margin:10px 0}}
.kpi{{flex:1;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;break-inside:avoid}}.kpi .nn{{font-size:22px;font-weight:700}}
.call{{border:1px solid #fcd34d;background:#fffbeb;border-radius:6px;padding:8px 12px;margin:10px 0;break-inside:avoid}}
table{{width:100%;border-collapse:collapse;table-layout:fixed;font-size:11.5px}}th,td{{border-bottom:1px solid #e2e8f0;padding:5px 6px;text-align:left;vertical-align:top;word-wrap:break-word}}
th{{background:#f1f5f9}}tr{{break-inside:avoid}}.pill{{color:#fff;border-radius:10px;padding:1px 8px;font-size:10.5px;white-space:nowrap}}
.fig{{break-inside:avoid;margin:8px 0}}.cap{{font-size:11px;color:#475569;margin-bottom:2px;font-weight:600}}
.small{{font-size:11px;color:#475569}}ul{{margin:4px 0 4px 18px;padding:0}}h2+*{{break-before:avoid;page-break-before:avoid}}
</style></head><body><div class="wrap"><h1>{title}</h1>
<div class="sub">Tenant: {tname} (grid account <code>{tenant}</code>) &middot; Window: last 24 hours to {now} UTC &middot; Site: {site}</div>
<div class="lead">
<p><b>What the evidence shows.</b> {tname} {head}. {by_h_e} error / {by_h_i} inactive / {by_h_o} ok across {n} configured sources.</p>
<p><b>Why it matters.</b> A source in error, or a resource index that has gone stale, is a blind spot the SOC will not notice until something is missed.</p>
<p><b>Result.</b> Tenant verdict: <b>{verdict}</b>. {n_err_src} source(s) with transform or source errors, {n_stale} stale resource fetcher(s), {nq} quiet source(s) (not a finding).</p>
<p><b>Evidence strength.</b> Confirmed: 24-hour throughput counters and error counters per source and pipe. Inferred: which pipes belong to a source, from the router wiring. Unknown: platform alert text, whether a source is disabled, and when a source last sent data.</p></div>
<div class="kpis">{kp}</div>
<h2>Needs attention</h2>
<table><colgroup><col style="width:30%"><col style="width:24%"><col style="width:46%"></colgroup><tr><th>Source</th><th>Finding</th><th>Detail</th></tr>{err_tr}</table>
<h2>Per-source verdicts</h2>
<table><colgroup><col style="width:25%"><col style="width:15%"><col style="width:11%"><col style="width:12%"><col style="width:12%"><col style="width:13%"><col style="width:12%"></colgroup><tr><th>Source</th><th>Application</th><th>Verdict</th><th>Received</th><th>Passed</th><th>Dropped / aborted / errored</th><th>Lineage</th></tr>{tr}</table>{shared_note}
<div class="call">Verdicts use only the throughput and error counters. Dropped bytes are intentional filtering and aborted bytes were handed to the next pipe; neither is a failure. A source with nothing received and nothing passed is quiet, which is not a finding. Resource fetchers write to a resource index, so their health comes from the freshness check, not from throughput.</div>
<h2>Volume</h2>
<div class="fig"><div class="cap">Bytes received by source, last 24 hours (total {total_in}; passed {total_pass})</div>{chart}</div>
<h2>Resource fetchers</h2>
<table><colgroup><col style="width:46%"><col style="width:30%"><col style="width:24%"></colgroup><tr><th>Source</th><th>Index last written</th><th>Status</th></tr>{fresh_tr}</table>
<p class="small">Freshness is the newest resource dump written for the source, against a {sh}-hour limit.</p>
<h2>Recommended actions</h2><ul>{actions}</ul>
<h2>Limits</h2><ul>
<li>Platform alert text and per-source "last active" times are not in this data, so a source with errors cannot be shown to have recovered; it stays in error.</li>
<li>Disabled sources are not identified; a disabled source with no traffic shows as inactive.</li>
<li>The configured-versus-discovered integration cross-check is not included.</li>
<li>Pipes are attributed to sources through the router; sources that share a router split its pipe counters in proportion to the bytes each received.</li></ul>
<h2>Methodology</h2><p class="small">Read-only calls through the {site} MCP connector against account <code>{tenant}</code> on {now} UTC: stream topology, 24-hour platform byte and event counters per datasource and pipe, and the resource dump list. Verdict rules follow the Fluency data-fabric vocabulary (four counters, three verdicts). A per-source CSV accompanies this report.</p>
</div></body></html>""".format(
        title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), now=now.strftime("%d %b %Y %H:%M"), site=esc(a.site), head=head,
        by_h_e=by_h[ERROR], by_h_i=by_h[INACTIVE], by_h_o=by_h[OK], n=len(rows), verdict=verdict, n_err_src=n_err_src, n_stale=n_stale,
        nq=len(quiet), kp=kp, err_tr=err_tr, tr=tr, shared_note=shared_note, total_in=size(total_in), total_pass=size(total_pass),
        chart=bars(top, "#0f766e"), fresh_tr=fresh_tr, sh=a.stale_hours, actions="".join(actions))
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote", a.out, a.csv, "verdict=%s %d error / %d inactive / %d ok" % (verdict, by_h[ERROR], by_h[INACTIVE], by_h[OK]))


if __name__ == "__main__":
    main()
