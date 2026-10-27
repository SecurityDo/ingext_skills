#!/usr/bin/env python3
"""Render the MSSP operations SitRep (HTML + JSON) for a connector's accounts from saved tool results.

Four lanes (SOC Manager, Administrator, Operator, Investigator) plus product posture, all computed here
from files in --evidence-dir; nothing is typed in by hand. A missing file is shown as "not collected",
never as zero or healthy.

  build_report.py --evidence-dir DIR --out sitrep.html [--json sitrep.json] --site Conekt --days 7 [--as-of ISO]

Layout of DIR:
  accounts.json            list_accounts result: {"entries": [{"name", "displayName"}]}
  <account>/cases.json     behavior_summary_search result (or an array of pages) for the window, score >= 3000
  <account>/health.json    optional, written by health-status-report (scripts/evaluate_health.py)
  coverage.csv             optional, written by mssp-coverage-map (account, name, bucket, pattern, ...)

Definitions
  ticket       a behavior summary scored 3,000 or more (smaller ones are not counted)
  open         status is not closed or resolved
  unworked     status new and no comment yet (the AI assistant has not run on it)
  escalated    status new after the AI assistant commented: needs an analyst
  age          hours from incidentDetectionTime to --as-of; a ticket without it has no age (no fallback)
"""
import argparse, collections, csv, datetime, html, json, os, re, sys

E = html.escape
ASSISTANT = "AI-Assistant"
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
STALE_HOURS = 24          # an unworked ticket older than this is flagged
PRODUCTS = (("Office365", ("office365", "office 365", "o365", "microsoft 365")),
            ("CrowdStrike Falcon", ("falcon", "crowdstrike")),
            ("SentinelOne", ("sentinelone", "sentinel one")))
CLOSED = ("closed", "resolved")

CSS = """:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#2563eb}
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
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:32px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-top:18px;box-shadow:0 1px 4px rgba(15,26,51,.04)}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}.bar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:16px;color:var(--mut);font-size:12px}.legend em{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0}
td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
td.ctl{border-left:4px solid var(--c);white-space:nowrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;color:var(--navy)}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
.mut{color:var(--mut)}.state{font-size:12px;color:var(--mut)}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.rel{display:flex;flex-wrap:wrap;gap:6px}.rel span{display:inline-flex;align-items:center;gap:6px;background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:2px 9px;font-size:12px;font-family:ui-monospace,Menlo,Consolas,monospace}.rel em{width:9px;height:9px;border-radius:50%;background:var(--c);display:inline-block}
.sum{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0 4px}.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-top:4px solid var(--c)}.sum b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin-bottom:4px}.sum span{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--navy)}.cav{font-size:12px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;margin-bottom:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media (max-width:760px){.kpis,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi,.panel{break-inside:avoid}th{position:static}.kpi,.pill,.bar i,td.ctl,.card,.read{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.kpi span{display:block;line-height:1.3}.nokpi{height:28px}
td.st{border-left:4px solid var(--c)}.muted{color:var(--mut)}p{margin:6px 0}h3{margin:16px 0 4px;color:var(--navy);font-size:14px}
.lane{border-left:4px solid var(--c)}.lane h3:first-child{margin-top:0}.read p{margin:4px 0}.read b{color:#14213d}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}table{table-layout:auto}td{word-wrap:break-word}
@media print{.hero,.read,td.st,.lane{-webkit-print-color-adjust:exact;print-color-adjust:exact}}"""


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def parse_iso(t):
    try:
        d = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(t).replace("Z", "+00:00")))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def norm_cases(res):
    pages = res if isinstance(res, list) else [res]
    out = []
    for pg in pages:
        for d in (pg or {}).get("documents", []):
            c = dict(d.get("source") or d.get("_source") or {})
            if c:
                out.append(c)
    return out


def age_h(c, now):
    t = parse_iso(c.get("incidentDetectionTime"))
    return None if t is None else max(0.0, (now - t).total_seconds() / 3600.0)


def fmt_age(h):
    if h is None:
        return "n/a"
    return "%dd %dh" % (h // 24, h % 24) if h >= 48 else "%dh" % h if h >= 1 else "%dm" % (h * 60)


def ticket_state(c):
    if c.get("status") in CLOSED:
        return "closed"
    if c.get("status") == "new":
        return "escalated" if c.get("comments") else "unworked"
    return "in_progress"


def assess_cases(res, now):
    if res is None:
        return None
    cases = norm_cases(res)
    t = {"flagged": len(cases), "closed": 0, "unworked": 0, "escalated": 0, "in_progress": 0,
         "stale_unworked": 0, "oldest_open_h": None, "top": [], "no_detection_time": 0}
    rows = []
    for c in cases:
        s = ticket_state(c)
        t[s] += 1
        a = age_h(c, now)
        if a is None:
            t["no_detection_time"] += 1
        if s != "closed":
            if a is not None and (t["oldest_open_h"] is None or a > t["oldest_open_h"]):
                t["oldest_open_h"] = a
            if s == "unworked" and a is not None and a > STALE_HOURS:
                t["stale_unworked"] += 1
            rows.append({"state": s, "key": c.get("key") or "", "score": c.get("riskScore") or 0, "age_h": a,
                         "rules": (c.get("behaviorRules") or [])[:3], "classification": c.get("classification") or ""})
    t["open"] = t["unworked"] + t["escalated"] + t["in_progress"]
    t["top"] = sorted(rows, key=lambda r: (r["state"] != "escalated", -(r["score"] or 0)))[:5]
    t["open_tickets"] = rows
    return t


def product_posture(health):
    """Per product: state counts of the installed applications that match it, from health.json."""
    if health is None:
        return None
    out = {}
    for name, kws in PRODUCTS:
        apps = [a for a in health.get("applications", []) if any(k in (a.get("application") or "").lower() for k in kws)]
        out[name] = {"installed": len(apps), "by_status": dict(collections.Counter(a.get("status") for a in apps)),
                     "problems": [{"instance": a.get("instance") or a.get("application"), "status": a.get("status"),
                                   "labels": a.get("labels") or []} for a in apps if a.get("status") in ("error", "attention", "disabled")]}
    return out


def pill(text, col):
    return '<span class="pill" style="--c:%s">%s</span>' % (col, E(text))


STATUS_COL = {"error": RED, "attention": AMB, "disabled": GRY}


def table(heads, rows, empty="Nothing to show.", col=NAVY, pills=()):
    if not rows:
        return '<p class="muted">%s</p>' % E(empty)
    h = "".join("<th>%s</th>" % E(x) for x in heads)

    def cell(i, c):
        if i in pills and c is not None:
            return pill(str(c), STATUS_COL.get(c, GRY))
        return c if isinstance(c, str) and c.startswith("<") else E(str(c))
    b = "".join("<tr>%s</tr>" % "".join("<td%s>%s</td>" % (' class="st" style="--c:%s"' % col if i == 0 else "", cell(i, c)) for i, c in enumerate(r)) for r in rows)
    return '<div class="tw"><table><thead><tr>%s</thead><tbody>%s</tbody></table></div>' % (h + "</tr>", b)


def na(v):
    return "not collected" if v is None else str(v)


def build(ev_dir, args):
    now = parse_iso(args.as_of) if args.as_of else datetime.datetime.now(datetime.timezone.utc)
    accts = (load(os.path.join(ev_dir, "accounts.json")) or {}).get("entries")
    if not accts:
        sys.exit("accounts.json is missing or has no entries. Save the list_accounts result under that name.")
    cov = {}
    cp = os.path.join(ev_dir, "coverage.csv")
    if os.path.exists(cp):
        with open(cp, newline="") as f:
            cov = {r["account"]: r for r in csv.DictReader(f)}
    rows = []
    for a in accts:
        d = os.path.join(ev_dir, a["name"])
        health = load(os.path.join(d, "health.json"))
        rows.append({"account": a["name"], "name": a.get("displayName") or a["name"],
                     "cases": assess_cases(load(os.path.join(d, "cases.json")), now),
                     "health": health, "posture": product_posture(health), "coverage": cov.get(a["name"]) if cov else None})
    return now, rows


def render(now, rows, args):
    with_cases = [r for r in rows if r["cases"] is not None]
    miss_cases = [r for r in rows if r["cases"] is None]
    tot = collections.Counter()
    for r in with_cases:
        for k in ("flagged", "closed", "unworked", "escalated", "in_progress", "stale_unworked", "open"):
            tot[k] += r["cases"][k]
    with_h = [r for r in rows if r["health"] is not None]
    hc = collections.Counter()
    for r in with_h:
        for k, v in (r["health"].get("counts") or {}).items():
            hc[k] += v or 0
    o = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MSSP Operations SitRep</title><style>%s</style></head><body>' % CSS]
    o.append('<div class="hero"><div class="wrap"><div class="eyebrow">Operations SitRep</div><h1>MSSP Operations SitRep</h1><p>%s &middot; %d accounts &middot; last %s days &middot; as of %s UTC</p></div></div><div class="wrap">'
             % (E(args.site), len(rows), args.days, now.strftime("%Y-%m-%d %H:%M")))
    hn = [0]

    def h2(t, c=None):
        hn[0] += 1
        return '<h2><span class="n">%d</span>%s</h2>' % (hn[0], t)

    def kpi(label, v, col=NAVY):
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span></div>" % (col, E(str(v)), E(label))

    ks = []
    if with_cases:
        ks.append(kpi("tickets flagged", tot["flagged"]) + kpi("open", tot["open"]) +
                 kpi("escalated (need an analyst)", tot["escalated"], RED if tot["escalated"] else GRN) +
                 kpi("unworked by the AI", tot["unworked"], AMB if tot["unworked"] else GRN) +
                 kpi("unworked over %dh" % STALE_HOURS, tot["stale_unworked"], RED if tot["stale_unworked"] else GRN))
    if with_h:
        ks.append(kpi("applications in error", hc["error"], RED if hc["error"] else GRN) + kpi("needing attention", hc["attention"], AMB if hc["attention"] else GRN))
    o.append('<div class="kpis">%s</div>' % "".join(ks) if ks else '<div class="nokpi"></div>')
    o.append(h2("Summary"))
    if miss_cases:
        o.append("<div class='read'><p><b>Not collected:</b> tickets for %d of %d accounts (%s). They are left out of every count, not counted as zero.</p></div>"
                 % (len(miss_cases), len(rows), E(", ".join(r["name"] for r in miss_cases[:8])) + ("…" if len(miss_cases) > 8 else "")))
    if not with_h:
        o.append("<div class='read'><p><b>Not collected:</b> application health for every account. Run health-status-report to fill the Administrator lane and product posture.</p></div>")

    # product posture
    o.append(h2("Product posture"))
    prow = []
    for name, _ in PRODUCTS:
        inst = [r for r in with_h if r["posture"] and r["posture"][name]["installed"]]
        bad = sum(len(r["posture"][name]["problems"]) for r in inst)
        tot_i = sum(r["posture"][name]["installed"] for r in inst)
        prow.append([name, na(tot_i) if with_h else "not collected", len(inst) if with_h else "not collected", bad if with_h else "not collected"])
    o.append(table(["Product", "Application instances", "Accounts with it", "In error, attention or disabled"], prow))
    if cov_present(rows):
        cc = collections.Counter((r["coverage"] or {}).get("bucket") for r in rows if r["coverage"])
        o.append("<p>Identity versus endpoint coverage (mssp-coverage-map): " + ", ".join("%s %d" % (k, v) for k, v in sorted(cc.items())) + ".</p>")
    else:
        o.append("<p class='muted'>Identity-versus-endpoint coverage: not collected (run mssp-coverage-map).</p>")

    ranked = sorted(with_cases, key=lambda r: (-r["cases"]["escalated"], -r["cases"]["unworked"], -r["cases"]["open"]))

    # SOC Manager
    o.append(h2("SOC Manager") + "<div class='panel lane' style='--c:%s'>" % NAVY)
    o.append("<h3>Situation</h3>")
    if with_cases:
        o.append("<p>%d tickets flagged in the window; %d closed, %d open. %d are escalated and %d have not been run by the AI assistant.</p>"
                 % (tot["flagged"], tot["closed"], tot["open"], tot["escalated"], tot["unworked"]))
        o.append(table(["Account", "Flagged", "Open", "Escalated", "Unworked", "Oldest open"],
                       [[r["name"], r["cases"]["flagged"], r["cases"]["open"], r["cases"]["escalated"], r["cases"]["unworked"], fmt_age(r["cases"]["oldest_open_h"])]
                        for r in ranked if r["cases"]["open"]][:15], "No open tickets."))
    else:
        o.append("<p>Tickets were not collected, so there is no queue view.</p>")
    o.append("<h3>Evidence needed</h3><p>Behavior summaries per account (behavior_summary_search, score 3,000 or more) for the window; application health per account (health-status-report).</p></div>")

    # Administrator
    o.append(h2("Administrator") + "<div class='panel lane' style='--c:%s'><h3>Situation</h3>" % BLU)
    if with_h:
        hp = [[r["name"], a.get("instance") or a.get("application"), a.get("status"), ", ".join(a.get("labels") or [])]
              for r in with_h for a in r["health"].get("applications", []) if a.get("status") in ("error", "attention", "disabled")]
        o.append("<p>%d of %d accounts have application health; %d applications are in error, %d need attention and %d are disabled.</p>"
                 % (len(with_h), len(rows), hc["error"], hc["attention"], hc["disabled"]))
        o.append(table(["Account", "Application", "Status", "Reason"], hp[:40], "No application needs attention.", BLU, (2,)))
        stale = [[r["name"], f["resource"], f.get("ageDays"), "empty" if f.get("empty") else "stale"]
                 for r in with_h for f in (r["health"].get("resourceFeeds") or []) if f.get("stale")]
        if stale:
            o.append("<h3>Stale resource feeds</h3>" + table(["Account", "Resource", "Age (days)", "Why"], stale[:40], col=AMB))
    else:
        o.append("<p>Application health was not collected.</p>")
    o.append("<h3>Evidence needed</h3><p>health.json per account from health-status-report.</p></div>")

    # Operator
    o.append(h2("Operator") + "<div class='panel lane' style='--c:%s'><h3>Situation</h3>" % AMB)
    if with_cases:
        o.append("<p>%d tickets have no comment yet; %d of them are older than %d hours.</p>" % (tot["unworked"], tot["stale_unworked"], STALE_HOURS))
        un = [[r["name"], t["key"], t["score"], fmt_age(t["age_h"]), ", ".join(t["rules"])]
              for r in ranked for t in sorted(r["cases"]["open_tickets"], key=lambda x: -(x["age_h"] or 0)) if t["state"] == "unworked"]
        o.append(table(["Account", "Entity", "Score", "Age", "Rules"], un[:25], "No unworked tickets.", AMB))
    else:
        o.append("<p>Tickets were not collected.</p>")
    o.append("<h3>Evidence needed</h3><p>Behavior summaries per account.</p></div>")

    # Investigator
    o.append(h2("Investigator") + "<div class='panel lane' style='--c:%s'><h3>Situation</h3>" % RED)
    if with_cases:
        esc = [[r["name"], t["key"], t["score"], fmt_age(t["age_h"]), ", ".join(t["rules"]), t["classification"] or "unclassified"]
               for r in ranked for t in sorted(r["cases"]["open_tickets"], key=lambda x: -(x["score"] or 0)) if t["state"] == "escalated"]
        o.append("<p>%d tickets are escalated: still new after the AI assistant commented.</p>" % tot["escalated"])
        o.append(table(["Account", "Entity", "Score", "Age", "Rules", "Classification"], esc[:25], "No escalated tickets.", RED))
    else:
        o.append("<p>Tickets were not collected.</p>")
    o.append("<h3>Evidence needed</h3><p>For each escalated ticket, run incident-investigation (or proofpoint-investigation for mail) in the ticket's own account.</p></div>")

    o.append("<div class='foot'><h2>Limits</h2><ul>"
             "<li>Counts come from behavior summaries scored 3,000 or more in the window; smaller summaries are not counted.</li>"
             "<li>Escalated means status <i>new</i> after the AI assistant commented; the platform has no separate escalation flag.</li>"
             "<li>Age runs from <i>incidentDetectionTime</i>; a ticket without it has no age and is not counted in ages (%d such ticket(s)).</li>"
             "<li>A page of results is capped by the page size you used; the script uses what was saved. Check <code>total</code> against the saved documents.</li>"
             "<li>Application health is the state at collection time. It is not a log-flow check unless the full mode of health-status-report was used.</li>"
             "<li>The investigation-gap ledger of the companion app has no equivalent here; this report stores nothing.</li></ul></div>"
             % sum(r["cases"]["no_detection_time"] for r in with_cases))
    o.append("</div></body></html>")
    return "\n".join(o), tot


def cov_present(rows):
    return any(r["coverage"] for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--json")
    ap.add_argument("--site", default="")
    ap.add_argument("--days", default="7")
    ap.add_argument("--as-of")
    args = ap.parse_args()
    now, rows = build(args.evidence_dir, args)
    page, tot = render(now, rows, args)
    with open(args.out, "w") as f:
        f.write(page)
    if args.json:
        slim = [{"account": r["account"], "tickets": {k: v for k, v in (r["cases"] or {}).items() if k not in ("open_tickets", "top")} or None,
                 "health_counts": (r["health"] or {}).get("counts")} for r in rows]
        with open(args.json, "w") as f:
            json.dump({"asOf": now.isoformat(), "accounts": slim, "totals": dict(tot)}, f, indent=1)
    warn = []
    for r in rows:
        c = load(os.path.join(args.evidence_dir, r["account"], "cases.json"))
        if c is not None:
            pages = c if isinstance(c, list) else [c]
            total = pages[-1].get("total")
            got = sum(len(p.get("documents", [])) for p in pages)
            if isinstance(total, int) and total > got:
                warn.append("%s: %d tickets reported, %d saved (page the search with offset)" % (r["name"], total, got))
    print("%d accounts | tickets %s | collected: cases %d, health %d" % (len(rows), dict(tot),
          sum(1 for r in rows if r["cases"] is not None), sum(1 for r in rows if r["health"] is not None)))
    for w in warn:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
