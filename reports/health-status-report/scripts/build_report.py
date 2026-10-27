#!/usr/bin/env python3
"""Render the Installed Applications Health report (HTML + CSV) from health.json.

health.json is written by scripts/evaluate_health.py, which applies the
Fluency 9 Applications-page status logic. This script only lays the result out; it computes nothing about
status, so the report and every other consumer of health.json agree. Missing evidence is stated,
never assumed healthy.

  build_report.py --health health.json --tenant acme --tenant-name "Example Corp" --site Develop --out report.html --csv applications.csv
"""
import argparse, csv, datetime, html, json, os, sys

KINDS = {"error": ("Error", "#b91c1c"), "attention": ("Attention", "#b45309"), "disabled": ("Disabled", "#64748b"),
         "other": ("Other", "#64748b"), "running": ("Running", "#15803d")}
ORDER = {"error": 0, "attention": 1, "disabled": 2, "other": 3, "running": 4}


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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


def age(ms, now_ms):
    if not ms:
        return "no activity in 24 h"
    h = (now_ms - ms) / 3600000.0
    return "%.0f min ago" % (h * 60) if h < 1 else "%.1f h ago" % h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--health", required=True, help="health.json from scripts/evaluate_health.py")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()
    h = load(a.health)
    if not h or not h.get("applications"):
        sys.exit("health.json is missing or lists no applications; run scripts/evaluate_health.py first")
    now_ms = h["capturedAtMs"]
    now = datetime.datetime.fromtimestamp(now_ms / 1000.0, datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    state_only = h.get("mode") == "state_only"
    views = []
    for r in h["applications"]:
        views.append({"kind": r["status"], "labels": r["labels"], "signals": r["signals"], "input": r["inputBytes"], "output": r["outputBytes"],
                      "error_bytes": r["errorBytes"], "err_rows": [(e["component"], e["name"], e["bytes"]) for e in r["errorRows"]],
                      "err_msgs": [(m["component"], m["message"]) for m in r["errorMessages"]], "resource_only": r["resourceOnly"], "state": r["state"],
                      "last_active": r["lastActiveMs"], "app": {"application": r["application"], "instance": r["instance"], "displayName": r["displayName"], "instanceName": r["instanceName"],
                                                                 "sources": [{"name": x["name"], "newest": x["newestDumpMs"]} for x in r["resourceSources"]]}})
    cnt = h["counts"]
    tot_in, tot_out = h["totals"]["inputBytes"], h["totals"]["outputBytes"]

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["application", "instance", "display_name", "connector_state", "status", "reasons", "input_bytes_24h", "output_bytes_24h", "error_bytes_24h", "signals"])
        for v in views:
            ap_ = v["app"]
            w.writerow([ap_["application"], ap_["instance"], ap_["displayName"], v["state"], v["kind"], " | ".join(v["labels"]),
                        "" if v["input"] is None else v["input"], "" if v["output"] is None else v["output"], "" if v["error_bytes"] is None else v["error_bytes"], " | ".join(v["signals"])])

    def traffic(v):
        return "n/a (state only)" if state_only else ("n/a" if v["input"] is None else "%s / %s" % (size(v["input"]), size(v["output"])))
    rows = "".join("<tr><td>%s<br><span class=\"small\">%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(v["app"]["displayName"]), esc(v["app"]["instanceName"] or v["app"]["instance"] or ""),
        " ".join(pill(v["kind"], l) for l in v["labels"]), traffic(v),
        "n/a" if v["error_bytes"] is None else size(v["error_bytes"]), "n/a" if (v["resource_only"] or state_only) else esc(age(v["last_active"], now_ms))) for v in views)
    err_rows = [(v["app"]["displayName"], c, n, b) for v in views for c, n, b in v["err_rows"]]
    err_tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(x[0]), esc(x[1]), esc(x[2]), size(x[3])) for x in err_rows) \
        or '<tr><td colspan="4">%s</td></tr>' % ("Not collected in state-only mode." if state_only else "No component reported error bytes in the last 24 hours.")
    res_rows = []
    for v in views:
        for src in v["app"]["sources"]:
            res_rows.append("<tr><td>%s</td><td>%s</td></tr>" % (esc(src["name"]), esc(("%.1f h ago" % ((now_ms - src["newest"]) / 3600000.0)) if src["newest"] else "no dump listed")))
    res_tr = "".join(res_rows) or '<tr><td colspan="2">No resource sources.</td></tr>'
    msg_tr = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(v["app"]["displayName"]), esc(c or "-"), esc(m.strip() or "(no message)"))
                     for v in views for c, m in v["err_msgs"]) or '<tr><td colspan="3">No error or recent alert messages.</td></tr>'
    attn = [v for v in views if v["kind"] in ("error", "attention")]
    actions = ["<li><b>%s</b>: %s. %s</li>" % (esc(v["app"]["displayName"]), esc(" · ".join(v["labels"])),
               "Open the application and read its error." if v["kind"] == "error" else "Check the installation and its data sources.") for v in attn] \
        or ["<li>No application needs attention from this evidence.</li>"]
    title = "%s Installed Applications Health Report" % a.tenant_name
    head = "no application is in error or needs attention" if not attn else "%d application(s) need attention or are in error" % len(attn)
    kp = "".join('<div class="kpi"><div class="nn" style="color:%s">%s</div><div class="small">%s</div></div>' % (c, v, l) for v, l, c in [
        (len(views), "Installed", "#0f172a"), (cnt["running"], "Running", "#15803d"), (cnt["error"], "Error", "#b91c1c"),
        (cnt["attention"] + cnt["disabled"] + cnt["other"], "Inactive or needs attention", "#b45309"), ("n/a" if state_only else "%s / %s" % (size(tot_in), size(tot_out)), "In / out, 24 h", "#0f172a")])
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
<p><b>Evidence strength.</b> {strength}</p></div>
<div class="kpis">{kp}</div>
<h2>Installed applications</h2>
<table><colgroup><col style="width:28%"><col style="width:24%"><col style="width:20%"><col style="width:12%"><col style="width:16%"></colgroup><tr><th>Application</th><th>Status</th><th>In / out, 24 h</th><th>Error bytes</th><th>Last active</th></tr>{rows}</table>
<div class="call">Running means the connector reports Running or the application moved data in the last 24 hours. A Running connector does not prove its data is current: a resource source (Office 365 resource watch, Qualys) has no traffic, so check the freshness table below.</div>
<h2>Error bytes by component</h2>
<table><colgroup><col style="width:30%"><col style="width:18%"><col style="width:32%"><col style="width:20%"></colgroup><tr><th>Application</th><th>Component</th><th>Name</th><th>Error bytes</th></tr>{err_tr}</table>
<h2>Error and alert messages</h2>
<table><colgroup><col style="width:28%"><col style="width:22%"><col style="width:50%"></colgroup><tr><th>Application</th><th>Component id</th><th>Message</th></tr>{msg_tr}</table>
<h2>Resource sources: freshness</h2>
<table><colgroup><col style="width:60%"><col style="width:40%"></colgroup><tr><th>Source</th><th>Newest dump written</th></tr>{res_tr}</table>
<p class="small">Informational only; it does not change an application's status.</p>
<h2>Recommended actions</h2><ul>{actions}</ul>
<h2>Limits</h2><ul>{limits}</ul>
<h2>Methodology</h2><p class="small">Read-only calls through the {site} MCP connector against account <code>{tenant}</code> on {now} UTC, evaluated by scripts/evaluate_health.py ({mode}). Credentials in the raw result were removed before use. A per-application CSV accompanies this report.</p>
</div></body></html>""".format(
        title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), now=now.strftime("%d %b %Y %H:%M"), site=esc(a.site), n=len(views),
        c_run=cnt["running"], c_err=cnt["error"], c_att=cnt["attention"], c_dis=cnt["disabled"], c_oth=cnt["other"], head=head[0].upper() + head[1:],
        kp=kp, msg_tr=msg_tr, rows=rows, err_tr=err_tr, res_tr=res_tr, actions="".join(actions),
        limits="".join("<li>%s</li>" % esc(x) for x in h["limits"]), mode=esc("state-only mode" if state_only else "full mode"),
        strength=esc("Confirmed: the connector state of each application. Unknown: traffic, errors, last-active times and missing components, which this run could not read." if state_only else "Confirmed: connector state, errors, 24-hour traffic and error bytes, and each component's last activity within the 24-hour window, all from the tenant's own connector configuration. Unknown: whether a source is disabled beyond its disable setting."))
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote", a.out, a.csv, "| %d apps: %d running, %d error, %d attention, %d disabled, %d other" % (len(views), cnt["running"], cnt["error"], cnt["attention"], cnt["disabled"], cnt["other"]))


if __name__ == "__main__":
    main()
