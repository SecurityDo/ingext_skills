#!/usr/bin/env python3
"""Render the Installed Applications Health report (HTML + CSV) from health.json.

health.json is written by scripts/evaluate_health.py, which applies the
Fluency 9 Applications-page status logic. This script only lays the result out; it computes nothing about
status, so the report and every other consumer of health.json agree. Missing evidence is stated,
never assumed healthy.

  build_report.py --health health.json --tenant acme --tenant-name "Example Corp" --site Develop --out report.html --csv applications.csv
"""
import argparse, csv, datetime, html, json, os, sys

KINDS = {"error": ("Error", "#B91C1C"), "attention": ("Attention", "#B45309"), "disabled": ("Disabled", "#64748B"),
         "other": ("Other", "#64748B"), "running": ("Running", "#15803D")}
ORDER = {"error": 0, "attention": 1, "disabled": 2, "other": 3, "running": 4}


CSS = """:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px 48px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:38px 0 70px}
.hero .wrap{padding-bottom:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}
.chip code{font-family:ui-monospace,Menlo,Consolas,monospace}
.kpis{display:grid;grid-template-columns:repeat(var(--k,4),1fr);gap:14px;margin-top:-46px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b.sm{font-size:20px;padding:6px 0}.kpi b{display:block;font-size:32px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-top:18px;box-shadow:0 1px 4px rgba(15,26,51,.04)}
.panel p{margin:6px 0}.panel p:first-child{margin-top:0}.panel p:last-child{margin-bottom:0}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px;break-after:avoid;page-break-after:avoid}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a;break-inside:avoid}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}.bar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:16px;color:var(--mut);font-size:12px}.legend em{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0}
td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
td.app{border-left:4px solid var(--c)}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;overflow:clip;background:var(--card);margin-top:10px}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
.small{font-size:12px;color:var(--mut)}.cap{font-size:12px;color:var(--navy);margin-bottom:4px;font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px;align-items:start}.two>div{min-width:0}
.two .panel{margin-top:0}.fig{break-inside:avoid}.fig svg{display:block;max-width:100%;height:auto}
.gaps{margin:0;padding-left:20px}.gaps li{margin:5px 0}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot p{margin:4px 0}
@media (max-width:760px){.kpis{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.hero h1{font-size:24px}}
@media print{.kpi b.sm{font-size:14px;padding:8px 0}body{background:#fff}.wrap{max-width:none;padding:0 0 16px}.hero{border-radius:12px;padding:26px 0 62px}.hero .wrap{padding:0 24px}.kpis{grid-template-columns:repeat(var(--k,4),1fr);margin:-46px 14px 0}.two{grid-template-columns:1fr 1fr}tr,.card,.kpi,.panel,.fig,.read{break-inside:avoid}th{position:static}.hero,.kpi,.pill,.bar i,td.app,.read,.n,.legend em,.chip{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

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
    return '<span class="pill" style="--c:%s">%s</span>' % (KINDS[kind][1], esc(label))


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
    rows = "".join("<tr><td class=\"app\" style=\"--c:%s\"><b>%s</b><br><span class=\"small\">%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        KINDS[v["kind"]][1], esc(v["app"]["displayName"]), esc(v["app"]["instanceName"] or v["app"]["instance"] or ""),
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
    kp = "".join('<div class="kpi" style="--c:%s"><b%s>%s</b><span>%s</span></div>' % (c, ' class="sm"' if len(str(v)) > 8 else "", v, l) for v, l, c in [
        (len(views), "Installed", "#14213D"), (cnt["running"], "Running", "#15803D"), (cnt["error"], "Error", "#B91C1C"),
        (cnt["attention"] + cnt["disabled"] + cnt["other"], "Inactive or needs attention", "#B45309"), ("n/a" if state_only else "%s / %s" % (size(tot_in), size(tot_out)), "In / out, 24 h", "#1D4ED8")])
    nv = len(views) or 1
    pbar = '<div class="bar" aria-hidden="true">%s</div><div class="legend">%s</div>' % (
        "".join('<i style="width:%.1f%%;background:%s"></i>' % (100.0 * cnt[k] / nv, KINDS[k][1]) for k in ORDER if cnt[k]),
        "".join('<span><em style="background:%s"></em>%s %d</span>' % (KINDS[k][1], KINDS[k][0], cnt[k]) for k in ORDER))
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body>
<div class="hero"><div class="wrap"><div class="eyebrow">Application health</div><h1>{title}</h1><div class="chips"><span class="chip">Tenant: {tname} (grid account <code>{tenant}</code>)</span><span class="chip">Last 24 hours to {now} UTC</span><span class="chip">Site: {site}</span></div></div></div>
<div class="wrap">
<div class="kpis" style="--k:5">{kp}</div>
<div class="panel"><b>Status mix</b>{pbar}</div>
<div class="panel">
<p><b>What the evidence shows.</b> {tname} has {n} installed applications: {c_run} running, {c_err} in error, {c_att} needing attention, {c_dis} disabled, {c_oth} other. {head}.</p>
<p><b>Why it matters.</b> An application in error or waiting for consent is a data source the customer believes is monitored but is not delivering.</p>
<p><b>Result.</b> Status follows the Fluency 9 Applications page: the connector state, recent traffic through the application's sources and sinks, and whether its components exist and have ever carried data.</p>
<p><b>Evidence strength.</b> {strength}</p></div>
<h2><span class="n">1</span>Installed applications</h2>
<div class="tw"><table><colgroup><col style="width:28%"><col style="width:24%"><col style="width:20%"><col style="width:12%"><col style="width:16%"></colgroup><thead><tr><th>Application</th><th>Status</th><th>In / out, 24 h</th><th>Error bytes</th><th>Last active</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="read">Running means the connector reports Running or the application moved data in the last 24 hours. A Running connector does not prove its data is current: a resource source (Office 365 resource watch, Qualys) has no traffic, so check the freshness table below.</div>
<h2><span class="n">2</span>Error bytes by component</h2>
<div class="tw"><table><colgroup><col style="width:30%"><col style="width:18%"><col style="width:32%"><col style="width:20%"></colgroup><thead><tr><th>Application</th><th>Component</th><th>Name</th><th>Error bytes</th></tr></thead><tbody>{err_tr}</tbody></table></div>
<h2><span class="n">3</span>Error and alert messages</h2>
<div class="tw"><table><colgroup><col style="width:28%"><col style="width:22%"><col style="width:50%"></colgroup><thead><tr><th>Application</th><th>Component id</th><th>Message</th></tr></thead><tbody>{msg_tr}</tbody></table></div>
<h2><span class="n">4</span>Resource sources: freshness</h2>
<div class="tw"><table><colgroup><col style="width:60%"><col style="width:40%"></colgroup><thead><tr><th>Source</th><th>Newest dump written</th></tr></thead><tbody>{res_tr}</tbody></table></div>
<p class="small">Informational only; it does not change an application's status.</p>
<h2><span class="n">5</span>Recommended actions</h2><div class="panel"><ul class="gaps">{actions}</ul></div>
<div class="foot"><h2><span class="n">6</span>Limits</h2><ul class="gaps">{limits}</ul>
<h2><span class="n">7</span>Methodology</h2><p>Read-only calls through the {site} MCP connector against account <code>{tenant}</code> on {now} UTC, evaluated by scripts/evaluate_health.py ({mode}). Credentials in the raw result were removed before use. A per-application CSV accompanies this report.</p></div>
</div></body></html>""".format(
        css=CSS, pbar=pbar, title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), now=now.strftime("%d %b %Y %H:%M"), site=esc(a.site), n=len(views),
        c_run=cnt["running"], c_err=cnt["error"], c_att=cnt["attention"], c_dis=cnt["disabled"], c_oth=cnt["other"], head=head[0].upper() + head[1:],
        kp=kp, msg_tr=msg_tr, rows=rows, err_tr=err_tr, res_tr=res_tr, actions="".join(actions),
        limits="".join("<li>%s</li>" % esc(x) for x in h["limits"]), mode=esc("state-only mode" if state_only else "full mode"),
        strength=esc("Confirmed: the connector state of each application. Unknown: traffic, errors, last-active times and missing components, which this run could not read." if state_only else "Confirmed: connector state, errors, 24-hour traffic and error bytes, and each component's last activity within the 24-hour window, all from the tenant's own connector configuration. Unknown: whether a source is disabled beyond its disable setting."))
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote", a.out, a.csv, "| %d apps: %d running, %d error, %d attention, %d disabled, %d other" % (len(views), cnt["running"], cnt["error"], cnt["attention"], cnt["disabled"], cnt["other"]))


if __name__ == "__main__":
    main()
