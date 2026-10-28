#!/usr/bin/env python3
"""Build the AWS CloudTrail Activity report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv report.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site Develop] [--top 10]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}); several files and
several days per file are merged. This script never queries a tenant. Daily results are combined the only safe way:
the per-day trend rows are kept once each and summed, facet tables are summed by value, a missing value counts as 0,
and a day that was not archived is reported as a GAP, never as zero activity.
Counts only: the archive holds no user names, addresses or ARNs, and neither does this report.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
METRICS = ["events", "consoleLogins", "failedLogins", "iamChanges", "rootEvents", "errors", "accessDenied", "loginsNoMfa", "trailChanges"]
SHORT = {"events": "Events", "consoleLogins": "Logins", "failedLogins": "Failed", "iamChanges": "IAM", "rootEvents": "Root", "errors": "Errors", "accessDenied": "Denied", "loginsNoMfa": "No MFA", "trailChanges": "Trail"}
LABEL = {"events": "Events", "consoleLogins": "Console logins", "failedLogins": "Failed logins", "iamChanges": "IAM changes",
         "rootEvents": "Root events", "errors": "Errors", "accessDenied": "Access denied", "loginsNoMfa": "Logins without MFA",
         "trailChanges": "CloudTrail changes"}
FACETS = ["source", "region", "identityType", "errSource", "errRegion", "errCode", "iamEvent", "rootEvent", "loginIdentity"]
FULL_FACETS = ("source", "region", "identityType")      # cover every event; a gap to the trend total is the 100-value tail
FACET_CAP = 100
SEC_FAMILY = [  # indicative, related not equivalent
    ("Audit events recorded and reviewable", "AU-2, AU-3, AU-6, AU-12", "events, errors by service and region"),
    ("Privileged and identity changes", "AC-2, AC-6, IA-4", "IAM changes by event, root-identity events"),
    ("Console sign-in and MFA", "IA-2, AC-7", "console logins, failed logins, logins without MFA"),
    ("Audit logging kept on", "AU-5, AU-9, CM-3", "changes to CloudTrail itself"),
    ("Access refused", "AC-3, SI-4", "access-denied errors and error codes"),
]
LIMITS = [
    "Counts only. Who did it, from where and to which resource is not in the archive, so nothing here names a person, address or resource.",
    "An archived day is a snapshot taken a few hours after the day ended; events that arrive later are not added (about 0.3% in testing).",
    "Facet tables hold at most 100 values each. Rarer values appear in the (other) row, computed as the day's events minus the listed values.",
    "A day missing from the archive is a gap, not zero activity. Days before the schedule's first run or beyond retention cannot be recovered except by a backfill.",
    "CloudTrail shows API and console activity only. Configuration state, S3 data events that are not logged, and findings from other tools are not evidenced here.",
    "These counts are related to NIST 800-53 controls, not equivalent to them. This report is not a compliance determination, certification or attestation.",
]

STYLE = """
:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px 48px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:38px 0 70px}
.hero .wrap{padding-bottom:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}
.hero p{margin:0;color:#c7d4ee;font-size:14px}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-46px}
.kpis.two{margin-top:14px;grid-template-columns:repeat(5,1fr)}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:30px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}.kpi small{display:block;color:var(--mut);font-size:11px;margin-top:2px}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.gap{border-left:4px solid var(--amb,#B45309);background:#fff7ed;border-radius:0 10px 10px 0;padding:12px 18px;margin-top:12px;color:#7c2d12}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
td.d{white-space:nowrap}
table.dt{font-size:11px}table.dt th,table.dt td{padding:6px 7px}table.dt th{letter-spacing:.03em}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.mut{color:var(--mut)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-size:12px;margin-bottom:4px}
.card svg{width:100%;height:auto;display:block}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
td.bar{width:34%}.bar i{display:block;height:8px;border-radius:4px;background:var(--c);min-width:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media screen and (max-width:760px){.kpis,.kpis.two,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def n(v):
    return "{:,}".format(int(v))


def pct(a, b):
    return "%.2f%%" % (100.0 * a / b) if b else "n/a"


def rows_of(tbl):
    return (tbl or {}).get("rows") or []


def load(paths):
    """Return {day: {'entry':..., 'trend':[rows], 'facets':{name:{value:count}}, 'capped':set}} for completed days,
    plus a {day: state} map for the others."""
    done, other = {}, {}
    files = []
    for p in paths:
        files.extend(sorted(glob.glob(p)) or [p])
    for p in files:
        try:
            d = json.load(open(p))
        except (OSError, ValueError) as e:
            sys.exit("cannot read %s (%s). Save the download_report_archive result as JSON first." % (p, e))
        for day in d.get("days", []):
            en = day.get("entry") or {}
            key = (en.get("rangeFrom") or "")[:10]
            res = day.get("result")
            if not key:
                continue
            if en.get("state") != "completed" or not res:
                other.setdefault(key, en.get("state") or "no result")
                continue
            trend, facets, capped = [], {}, set()
            for o in res.get("objects", []):
                if o.get("name") == "trend":
                    trend = rows_of(o.get("table"))
                elif o.get("name") == "facets":
                    om = (o.get("value") or {}).get("orderedMap") or {}
                    for k, v in zip(om.get("keys", []), om.get("values", [])):
                        if k == "PrimaryResult":
                            continue
                        sx = (v or {}).get("sx") or {}
                        rows = sx.get("rows") or []
                        col = k
                        facets[k] = {str(r.get(col)): int(r.get("count_") or 0) for r in rows}
                        if (sx.get("rowCount") or len(rows)) >= FACET_CAP:
                            capped.add(k)
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = {"entry": en, "trend": trend, "facets": facets, "capped": capped}
    return done, other


def merge(done):
    daily = {}
    for day, d in done.items():
        tot = collections.Counter()
        for r in d["trend"]:
            for m in METRICS:
                tot[m] += int(r.get(m) or 0)
        daily[day] = tot
    fac = {f: collections.Counter() for f in FACETS}
    for d in done.values():
        for f in FACETS:
            for v, c in d["facets"].get(f, {}).items():
                fac[f][v] += c
    return daily, fac


def bars(series, days, color, title):
    """Inline SVG bar chart: one bar per calendar day; a missing day is a hatched gap, never a zero bar."""
    W, H, L, B = 480, 120, 6, 18
    mx = max([v for v in series.values()] + [1])
    k = len(days)
    bw = (W - 2 * L) / max(k, 1)
    o = ["<svg viewBox='0 0 %d %d' role='img' aria-label='%s'>" % (W, H, E(title))]
    o.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#e2e8f0'/>" % (L, H - B, W - L, H - B))
    for i, d in enumerate(days):
        x = L + i * bw
        if d not in series:
            o.append("<rect x='%.1f' y='6' width='%.1f' height='%d' fill='#fef3c7' stroke='#f59e0b' stroke-dasharray='2 2'/>" % (x + 0.5, max(bw - 1, 1), H - B - 6))
            continue
        h = (H - B - 8) * series[d] / mx
        o.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'><title>%s: %s</title></rect>" % (x + 0.5, H - B - h, max(bw - 1, 1), h, color, d, n(series[d])))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b'>%s</text>" % (L, H - 4, days[0] if days else ""))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b' text-anchor='end'>%s</text>" % (W - L, H - 4, days[-1] if days else ""))
    o.append("<text x='%d' y='%d' font-size='10' fill='#64748b' text-anchor='end'>max %s</text>" % (W - L, 10, n(mx)))
    o.append("</svg>")
    return "".join(o)


def table(title, sub, counter, total, color, top, other_total=None, keep_none=True, none_label="no event"):
    items = [(k, v) for k, v in counter.items() if v and (keep_none or k != "(none)")]
    items.sort(key=lambda kv: -kv[1])
    shown = items[:top]
    rest = sum(v for _, v in items[top:])
    if other_total is not None and other_total > 0:
        rest += other_total
    if not shown:
        return "<div class='card' style='--c:%s'><b>%s</b><span class='mut'>None in this period.</span></div>" % (color, E(title))
    mx = shown[0][1]
    r = []
    for k, v in shown:
        r.append("<tr><td class='mono'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='bar'><i style='--c:%s;width:%.0f%%'></i></td></tr>" % (E(k), n(v), pct(v, total), color, 100.0 * v / mx))
    if rest:
        r.append("<tr><td class='mut'>(other)</td><td class='r'>%s</td><td class='r'>%s</td><td></td></tr>" % (n(rest), pct(rest, total)))
    return ("<div style='break-inside:avoid'><h3 style='margin:18px 0 2px;font-size:14px;color:%s'>%s</h3><p class='sub'>%s</p><div class='tw'><table><thead><tr><th>Value</th><th class='r'>Count</th><th class='r'>Share</th><th></th></tr></thead><tbody>%s</tbody></table></div></div>"
            % (NAVY, E(title), E(sub), "".join(r)))


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--summary-json")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    done, other = load(a.archive)
    if not done:
        sys.exit("no completed archived day in the input. Backfill or wait for the schedule; nothing is estimated.")
    first, last = min(done), max(done)
    dfrom, dto = a.dfrom or first, a.dto or last
    expected = days_between(dfrom, dto)
    done = {k: v for k, v in done.items() if dfrom <= k <= dto}
    if not done:
        sys.exit("no archived day falls inside %s to %s." % (dfrom, dto))
    daily, fac = merge(done)
    missing = [d for d in expected if d not in done]
    hashes = collections.Counter(v["entry"].get("env", {}).get("scriptHash", "?") for v in done.values())
    capped_days = sorted(k for k, v in done.items() if v["capped"])
    T = collections.Counter()
    for c in daily.values():
        T.update(c)
    ev = T["events"]
    period = "%s to %s" % (dfrom, dto)

    summary = {"period": period, "days_expected": len(expected), "days_archived": len(done), "missing_days": missing,
               "non_completed": other, "script_hashes": dict(hashes), "totals": {m: T[m] for m in METRICS},
               "daily": {d: {m: daily[d][m] for m in METRICS} for d in sorted(daily)},
               "facets": {f: dict(fac[f].most_common()) for f in FACETS}}
    if a.summary_json:
        json.dump(summary, open(a.summary_json, "w"), indent=1)

    capn = collections.Counter(f for v in done.values() for f in v["capped"])
    capcell = ", ".join("%s %d" % kv for kv in sorted(capn.items())) or "none"
    cov_col = GRN if not missing else (AMB if len(missing) < len(expected) / 2 else RED)
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>AWS CloudTrail Activity Report</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>AWS audit activity</div><h1>AWS CloudTrail Activity Report</h1>"
             "<p>Daily counts of events, sign-ins, IAM changes, root activity and errors, built from the archived daily runs.</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d of %d days archived</span><span class='chip'>Counts, not a determination</span></div></div></div><div class='wrap'>"
             % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(done), len(expected)))

    def kpi(m, color, small=""):
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span>%s</div>" % (color, n(T[m]), LABEL[m], "<small>%s</small>" % E(small) if small else "")
    o.append("<div class='kpis'>%s%s%s%s</div>" % (kpi("events", NAVY, "%s a day on average" % n(ev / len(done))), kpi("errors", AMB, pct(T["errors"], ev) + " of events"),
             kpi("accessDenied", AMB, pct(T["accessDenied"], ev) + " of events"), kpi("iamChanges", BLU, "reads excluded")))
    o.append("<div class='kpis two'>%s%s%s%s%s</div>" % (
        kpi("consoleLogins", NAVY), kpi("failedLogins", RED if T["failedLogins"] else GRN), kpi("loginsNoMfa", RED if T["loginsNoMfa"] else GRN),
        kpi("rootEvents", RED if T["rootEvents"] else GRN), kpi("trailChanges", RED if T["trailChanges"] else GRN)))

    o.append("<div class='read'><b>Read this first.</b> Every figure comes from the daily archive of the CloudTrail Activity scheduled report; "
             "nothing was searched live. The numbers are counts of CloudTrail events, related to NIST 800-53 audit, access and identity controls. "
             "They are not a compliance determination. Zero means no matching event on an archived day; a day that is not archived is a gap.</div>")
    # highlights
    hl = []
    if T["rootEvents"]: hl.append("%s event(s) by the root identity in the period." % n(T["rootEvents"]))
    if T["trailChanges"]: hl.append("%s change(s) to CloudTrail itself (stop, delete, update or selector changes)." % n(T["trailChanges"]))
    if T["failedLogins"]: hl.append("%s failed console login(s)." % n(T["failedLogins"]))
    if T["loginsNoMfa"]: hl.append("%s successful console login(s) without MFA." % n(T["loginsNoMfa"]))
    if not hl: hl.append("No root-identity events, CloudTrail changes, failed console logins or console logins without MFA on the archived days.")
    o.append("<div class='panel' style='margin-top:14px'><ul style='margin:0;padding-left:20px'>%s</ul></div>" % "".join("<li>%s</li>" % E(h) for h in hl))

    # coverage
    o.append("<h2><span class='n'>1</span>Archive coverage</h2><p class='sub'>What this report is built from.</p>")
    o.append("<div class='tw'><table><tbody>"
             "<tr><td>Days archived</td><td class='r'><span class='pill' style='--c:%s'>%d of %d</span></td></tr>"
             "<tr><td>Script version(s)</td><td class='r mono'>%s</td></tr>"
             "<tr><td>Breakdowns that hit the 100-value cap (days)</td><td class='r mono'>%s</td></tr></tbody></table></div>"
             % (cov_col, len(done), len(expected), E(", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common())), E(capcell)))
    if missing:
        o.append("<div class='gap'><b>Gap.</b> %d day(s) are not in the archive and are not counted as zero: %s. Run a backfill for them, then rebuild.%s</div>"
                 % (len(missing), E(", ".join(missing[:31]) + (" ..." if len(missing) > 31 else "")),
                    " Non-completed runs: " + E(", ".join("%s=%s" % kv for kv in sorted(other.items()))) + "." if other else ""))
    if len(hashes) > 1:
        o.append("<div class='gap'><b>Script changed during the period.</b> More than one script version produced these days; confirm the counts are defined the same way before comparing days.</div>")

    # trend
    days = expected
    o.append("<h2><span class='n'>2</span>Daily trend</h2><p class='sub'>One bar per UTC day. Hatched amber columns are days missing from the archive.</p><div class='cards'>")
    for m, c in (("events", NAVY), ("errors", AMB), ("accessDenied", AMB), ("iamChanges", BLU)):
        o.append("<div class='card' style='--c:%s'><b>%s per day</b>%s</div>" % (c, LABEL[m], bars({d: daily[d][m] for d in daily}, days, c, LABEL[m])))
    o.append("</div>")
    hdr = "".join("<th class='r'>%s</th>" % SHORT[m] for m in METRICS)
    body = []
    for d in days:
        if d in daily:
            body.append("<tr><td class='mono d'>%s</td>%s</tr>" % (d, "".join("<td class='r'>%s</td>" % n(daily[d][m]) for m in METRICS)))
        else:
            body.append("<tr><td class='mono d'>%s</td><td colspan='%d' class='mut'>not archived (gap)</td></tr>" % (d, len(METRICS)))
    body.append("<tr><td><b>Total</b></td>%s</tr>" % "".join("<td class='r'><b>%s</b></td>" % n(T[m]) for m in METRICS))
    o.append("<div class='tw' style='margin-top:14px'><table class='dt'><thead><tr><th>Day</th>%s</tr></thead><tbody>%s</tbody></table></div>" % (hdr, "".join(body)))

    # breakdowns
    top = a.top
    o.append("<h2><span class='n'>3</span>Identity, IAM and error detail</h2><p class='sub'>Top %d values per list, merged across the archived days; the rest is in (other).</p>" % top)
    o.append(table("IAM changes by event", "Write events on iam.amazonaws.com; Get, List and Describe excluded.", fac["iamEvent"], T["iamChanges"], BLU, top, keep_none=False))
    o.append(table("Root-identity events by event", "Events whose identity type is Root.", fac["rootEvent"], T["rootEvents"], RED, top, keep_none=False))
    o.append(table("Console logins by identity type", "ConsoleLogin events.", fac["loginIdentity"], T["consoleLogins"], NAVY, top, keep_none=False))
    o.append(table("Errors by error code", "Events carrying an errorCode.", fac["errCode"], T["errors"], AMB, top, keep_none=False))
    o.append(table("Errors by service", "Services returning errors.", fac["errSource"], T["errors"], AMB, top, keep_none=False))
    o.append(table("Errors by region", "Regions returning errors.", fac["errRegion"], T["errors"], AMB, top, keep_none=False))

    o.append("<h2><span class='n'>4</span>Where the activity is</h2><p class='sub'>All events, by service, region and identity type. (not recorded) means the event carried no value; for identity type these are AWS service-generated events.</p>")
    for f, t, s in (("source", "Events by AWS service", "eventSource"), ("region", "Events by region", "awsRegion"), ("identityType", "Events by identity type", "userIdentity.type")):
        tail = max(ev - sum(fac[f].values()), 0)
        o.append(table(t, "Field %s." % s, fac[f], ev, NAVY, top, other_total=tail))

    # mapping
    o.append("<h2><span class='n'>5</span>What these counts relate to</h2><p class='sub'>Indicative crosswalk to NIST SP 800-53 Rev. 5. Related, not equivalent.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Area</th><th>800-53 controls</th><th>Counts that relate</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td>%s</td><td class='mono'>%s</td><td>%s</td></tr>" % (E(x), E(y), E(z)) for x, y, z in SEC_FAMILY))
    o.append("<div class='foot'><b>Limits</b><ul>%s</ul><p>Source: archive of the scheduled report CloudTrail_Activity_Report. No live search was run to build this report.</p></div>" % "".join("<li>%s</li>" % E(l) for l in LIMITS))
    o.append("</div></body></html>")
    open(a.out, "w").write("".join(o))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["section", "key", "metric", "count"])
            for d in days:
                if d in daily:
                    for m in METRICS:
                        w.writerow(["daily", d, m, daily[d][m]])
                else:
                    w.writerow(["daily", d, "gap", ""])
            for m in METRICS:
                w.writerow(["total", dfrom + ".." + dto, m, T[m]])
            for f in FACETS:
                for k, v in fac[f].most_common():
                    w.writerow(["facet:" + f, k, "count", v])
    print("period %s: %d of %d days archived, %s events, %d gap day(s)" % (period, len(done), len(expected), n(ev), len(missing)))


if __name__ == "__main__":
    main()
