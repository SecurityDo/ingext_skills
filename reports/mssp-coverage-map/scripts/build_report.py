#!/usr/bin/env python3
"""Render the fleet identity-versus-endpoint coverage map (HTML + CSV) from saved dumps.

For every tenant: licensed Microsoft 365 seats (office365User dump) against the endpoints and users that
the tenant's EDR dumps (CrowdStrike Falcon, SentinelOne, Microsoft Defender) show. Everything is computed
here from files in --evidence-dir; nothing is typed in by hand.

  build_report.py --evidence-dir DIR --out coverage.html --csv coverage.csv --site Develop [--prepared YYYY-MM-DD]

Layout of DIR:
  accounts.json                      list_accounts result: {"entries": [{"name", "displayName"}]}
  <account>/resources.json           list_resource_dumps result for the account (what exists, record counts, dump times)
  <account>/users*.jsonl.gz          office365User dump(s)            (one file per customer; counts are summed)
  <account>/falcon*.jsonl.gz         falconAgent dump(s)
  <account>/sentinelone*.jsonl.gz    sentinelOneAgent dump(s)
  <account>/defender*.jsonl.gz       msDefenderMachine dump(s)
A dump that resources.json lists but whose file is missing is reported as not collected, never as zero.

Definitions
  licensed seat   an enabled Member account with at least one assigned license
  EDR host        Falcon: every record. SentinelOne: not decommissioned and not uninstalled.
                  Defender: onboardingStatus is Onboarded.
  EDR user        distinct last-login user of the EDR hosts (Falcon last_login_user, SentinelOne
                  lastLoggedInUserName), lower-cased with any DOMAIN\\ prefix and @domain suffix removed;
                  Defender has no user field. Users are the union across products.
  gap             licensed seats minus EDR users (directional)
Pattern (thresholds are constants below): under-covered when the gap exceeds UNDER of the seats, over when
EDR users exceed the seats by more than OVER, otherwise aligned.
"""
import argparse, collections, csv, datetime, glob, gzip, html, json, os, re, sys

UNDER, OVER = 0.10, 0.10
NON_USERS = {"", "system", "root", "local service", "network service", "nt authority\\system", "-", "n/a", "none", "null"}
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
PATTERNS = {"under": ("EDR under-coverage", RED), "aligned": ("Aligned", GRN), "over": ("EDR users exceed licensed seats", AMB)}
E = html.escape

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
.kpis6{grid-template-columns:repeat(6,1fr)}.kpis6 .kpi b{font-size:28px}.kpis6 .kpi span{font-size:11px;line-height:1.3;display:block}
td.st{border-left:4px solid var(--c)}.r{text-align:right}.small{font-size:12px;color:var(--mut)}td .small{font-size:11px}table{table-layout:fixed}td{word-wrap:break-word}
.read p{margin:4px 0}.read b{color:#14213d}ul{margin:6px 0 6px 18px;padding:0}.panel svg{display:block;max-width:100%}.panel p{margin:4px 0}
@media (max-width:760px){.kpis6{grid-template-columns:1fr 1fr}}@media print{.hero,.read,.bar i,td.st{-webkit-print-color-adjust:exact;print-color-adjust:exact}}"""


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def records(path, key):
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out.append(r.get("@" + key, r))
    return out


def norm_user(u):
    u = (u or "").strip().lower()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return "" if u in NON_USERS else u


def parse_iso(t):
    try:
        d = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(t).replace("Z", "+00:00")))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


PRODUCTS = (("falcon", "falconAgent", "Falcon"), ("sentinelone", "sentinelOneAgent", "SentinelOne"), ("defender", "msDefenderMachine", "Defender"))


def assess(tdir, warns, name):
    res = load(os.path.join(tdir, "resources.json")) or {}
    listed = {}
    for e in res.get("entries", []):
        listed.setdefault(e.get("resource"), []).append(e)
    t = {"listed": {k: sum(x.get("count") or 0 for x in v) for k, v in listed.items()}, "snapshot": None}
    times = [parse_iso(x.get("createdOn")) for k in ("office365User", "falconAgent", "sentinelOneAgent", "msDefenderMachine") for x in listed.get(k, [])]
    times = [x for x in times if x]
    t["snapshot"] = max(times) if times else None

    def read(prefix, resource):
        files = sorted(glob.glob(os.path.join(tdir, prefix + "*.jsonl.gz")))
        if not files:
            return None
        recs = []
        for fp in files:
            recs += records(fp, resource)
        want = t["listed"].get(resource)
        if want is not None and want != len(recs):
            warns.append("%s: %s file(s) hold %d records but list_resource_dumps reported %d (truncated download?)" % (name, resource, len(recs), want))
        return recs
    users = read("users", "office365User")
    t["users_listed"] = "office365User" in listed
    if users is not None:
        t["raw_users"] = len(users)
        t["seats"] = sum(1 for r in users if r.get("accountEnabled") is True and r.get("userType") == "Member" and r.get("assignedLicenses"))
    else:
        t["raw_users"] = t["seats"] = None
    t["edr"] = {}
    edr_users = set()
    for key, resource, label in PRODUCTS:
        recs = read(key, resource)
        t["edr"][key] = {"listed": resource in listed, "hosts": None, "users": None}
        if recs is None:
            continue
        if key == "falcon":
            hosts, us = len(recs), [r.get("last_login_user") for r in recs]
        elif key == "sentinelone":
            live = [r for r in recs if not r.get("isDecommissioned") and not r.get("isUninstalled")]
            hosts, us = len(live), [r.get("lastLoggedInUserName") for r in live]
        else:
            live = [r for r in recs if r.get("onboardingStatus") == "Onboarded"]
            hosts, us = len(live), []
        nu = {norm_user(x) for x in us} - {""}
        t["edr"][key].update(hosts=hosts, total=len(recs), users=len(nu) if key != "defender" else None)
        edr_users |= nu
    have_edr = [k for k, v in t["edr"].items() if v["hosts"] is not None]
    listed_edr_missing = [k for k, v in t["edr"].items() if v["listed"] and v["hosts"] is None]
    t["edr_hosts"] = sum(t["edr"][k]["hosts"] for k in have_edr) if have_edr else None
    t["edr_users"] = len(edr_users) if any(k in ("falcon", "sentinelone") for k in have_edr) else None
    t["not_collected"] = [("office365User" if t["users_listed"] and users is None else None)] + [dict((p[0], p[1]) for p in PRODUCTS)[k] for k in listed_edr_missing]
    t["not_collected"] = [x for x in t["not_collected"] if x]
    ident = users is not None
    edr = bool(have_edr)
    t["bucket"] = "both" if ident and edr else "edr_only" if edr else "identity_only" if ident else "neither"
    if t["not_collected"]:
        t["bucket"] = "incomplete"
    if t["bucket"] == "both" and t["seats"] is not None and t["edr_users"] is not None:
        t["gap"] = t["seats"] - t["edr_users"]
        t["gap_pct"] = (t["gap"] * 100.0 / t["seats"]) if t["seats"] else None
        if t["seats"] and t["gap"] > UNDER * t["seats"]:
            t["pattern"] = "under"
        elif t["seats"] and -t["gap"] > OVER * t["seats"]:
            t["pattern"] = "over"
        else:
            t["pattern"] = "aligned"
    elif t["bucket"] == "both":
        t["gap"] = t["gap_pct"] = None          # only Defender: hosts but no user list to compare
        t["pattern"] = None
    else:
        t["gap"] = t["gap_pct"] = t["pattern"] = None
    return t


def n(x):
    return "n/a" if x is None else "{:,}".format(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--prepared")
    a = ap.parse_args()
    accts = (load(os.path.join(a.evidence_dir, "accounts.json")) or {}).get("entries") or []
    if not accts:
        sys.exit("accounts.json is missing or empty; save the list_accounts result")
    warns, rows = [], []
    for ac in accts:
        tdir = os.path.join(a.evidence_dir, ac["name"])
        t = assess(tdir, warns, ac["name"]) if os.path.isdir(tdir) else {"bucket": "not_assessed", "listed": {}, "edr": {}, "snapshot": None, "seats": None, "raw_users": None, "edr_hosts": None, "edr_users": None, "gap": None, "gap_pct": None, "pattern": None, "not_collected": []}
        t["name"], t["display"] = ac["name"], ac.get("displayName") or ac["name"]
        rows.append(t)
    prep = a.prepared or datetime.date.today().isoformat()
    cnt = collections.Counter(t["bucket"] for t in rows)
    pat = collections.Counter(t["pattern"] for t in rows if t["pattern"])
    both = sorted([t for t in rows if t["pattern"]], key=lambda t: -(t["gap"] or 0))
    under = [t for t in both if t["pattern"] == "under"]

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account", "name", "bucket", "pattern", "raw_users", "licensed_seats", "falcon_hosts", "sentinelone_hosts", "defender_onboarded", "edr_hosts", "edr_users", "gap", "gap_pct", "snapshot_utc"])
        for t in rows:
            e = t["edr"]
            w.writerow([t["name"], t["display"], t["bucket"], t["pattern"] or "", "" if t["raw_users"] is None else t["raw_users"], "" if t["seats"] is None else t["seats"],
                        *("" if (e.get(k) or {}).get("hosts") is None else e[k]["hosts"] for k in ("falcon", "sentinelone", "defender")),
                        "" if t["edr_hosts"] is None else t["edr_hosts"], "" if t["edr_users"] is None else t["edr_users"], "" if t["gap"] is None else t["gap"],
                        "" if t["gap_pct"] is None else "%.1f" % t["gap_pct"], t["snapshot"].strftime("%Y-%m-%d %H:%M") if t["snapshot"] else ""])

    def host_cell(t):
        e = t["edr"]
        parts = ["%s %s" % (lab, n(e[k]["hosts"])) for k, _, lab in PRODUCTS if (e.get(k) or {}).get("hosts") is not None]
        return E("; ".join(parts) or "—")

    def row_html(t):
        pc = PATTERNS.get(t["pattern"])
        col = pc[1] if pc else GRY
        pct = ('<span class="pill" style="--c:%s">%s</span>' % (col, "%.0f%%" % t["gap_pct"])) if t["gap_pct"] is not None else "n/a"
        return "<tr><td class=\"st\" style=\"--c:%s\">%s<br><span class=\"small\">%s</span></td><td class=\"r\">%s</td><td>%s</td><td class=\"r\">%s</td><td class=\"r\"><b>%s</b></td><td class=\"r\">%s</td></tr>" % (
            col, E(t["display"]), E(t["name"]), n(t["seats"]), host_cell(t), n(t["edr_users"]), n(t["gap"]), pct)
    heads = "<tr><th>Tenant</th><th class=\"r\">Licensed seats</th><th>EDR hosts (per product)</th><th class=\"r\">EDR users</th><th class=\"r\">Gap</th><th class=\"r\">Gap %</th></tr>"

    def table(trs):
        cols = "".join('<col style="width:%s">' % w for w in ("26%", "13%", "29%", "12%", "10%", "10%"))
        return "<div class=\"tw\"><table><colgroup>" + cols + "</colgroup>" + heads + "".join(trs) + "</table></div>"

    def bars(items, color):
        if not items:
            return ""
        mx = max(v for _, v in items) or 1
        out = '<svg viewBox="0 0 720 %d" width="100%%" role="img">' % (24 * len(items) + 4)
        for i, (lab, v) in enumerate(items):
            bw = 360 * v / mx
            out += '<text x="0" y="%d" font-size="12" fill="#0f172a">%s</text><rect x="260" y="%d" width="%.1f" height="15" fill="%s" rx="2"/><text x="%.1f" y="%d" font-size="12" fill="#0f172a">%s</text>' % (i * 24 + 15, E(lab[:34]), i * 24 + 3, max(bw, 1), color, 266 + bw, i * 24 + 15, "{:,}".format(v))
        return out + "</svg>"
    sections = []
    h2n = [1]

    def h2(title):
        h2n[0] += 1
        return '<h2><span class="n">%d</span>%s</h2>' % (h2n[0], title)
    for key in ("under", "over", "aligned"):
        grp = [t for t in both if t["pattern"] == key]
        if grp:
            sections.append("%s%s" % (h2("%s (%d)" % (PATTERNS[key][0], len(grp))), table([row_html(t) for t in grp])))
    edr_only = [t for t in rows if t["bucket"] == "edr_only"]
    id_only = [t for t in rows if t["bucket"] == "identity_only"]
    neither = [t for t in rows if t["bucket"] in ("neither", "not_assessed")]
    incomplete = [t for t in rows if t["bucket"] == "incomplete"]
    defender_only = [t for t in rows if t["bucket"] == "both" and t["pattern"] is None]
    if defender_only:
        sections.append("%s<p class=\"sub\">Defender machines carry no user name, so a seat-to-user gap cannot be computed.</p>%s" % (h2("Identity and Defender only (%d)" % len(defender_only)), table([row_html(t) for t in defender_only])))
    if edr_only:
        tot = sum(t["edr_hosts"] or 0 for t in edr_only)
        sections.append("%s<p class=\"sub\">Endpoints exist but there is no Microsoft 365 user dump to say whose they are: %s endpoints in total.</p>%s" % (
            h2("Identity blind (%d)" % len(edr_only)), n(tot), table([row_html(t) for t in edr_only])))
    if id_only:
        sections.append("%s<p class=\"sub\">A Microsoft 365 user dump but no EDR roster. The tenant may use an EDR that is not collected here.</p><div class=\"tw\"><table><tr><th>Tenant</th><th class=\"r\">Licensed seats</th></tr>%s</table></div>" % (
            h2("Endpoint blind (%d)" % len(id_only)), "".join("<tr><td class=\"st\" style=\"--c:#B45309\">%s<br><span class=\"small\">%s</span></td><td class=\"r\">%s</td></tr>" % (E(t["display"]), E(t["name"]), n(t["seats"])) for t in id_only)))
    if incomplete:
        sections.append("%s<p class=\"sub\">The dump is listed for these tenants but its file was not downloaded, so they are not assessed.</p><div class=\"panel\"><ul>%s</ul></div>" % (
            h2("Not collected (%d)" % len(incomplete)), "".join("<li>%s: %s</li>" % (E(t["display"]), E(", ".join(t["not_collected"]))) for t in incomplete)))
    if neither:
        sections.append("%s<p class=\"sub\">Neither a Microsoft 365 user dump nor an EDR dump.</p><div class=\"panel\"><p>%s</p></div>" % (h2("Not assessable (%d)" % len(neither)), E(", ".join(t["display"] for t in neither))))
    ranked = "".join("<tr><td class=\"st\" style=\"--c:%s\">%d</td><td>%s</td><td class=\"r\"><b>%s</b></td><td class=\"r\"><span class=\"pill\" style=\"--c:%s\">%s</span></td></tr>" % (RED, i + 1, E(t["display"]), n(t["gap"]), RED, ("%.0f%%" % t["gap_pct"])) for i, t in enumerate(under[:15])) or "<tr><td colspan=\"4\">No tenant is under-covered by more than %d%% of its seats.</td></tr>" % int(UNDER * 100)
    kcs = [(len(rows), "Tenants listed", NAVY), (cnt["both"], "With identity and EDR", BLU), (pat["under"], "Under-covered", RED), (cnt["edr_only"], "Identity blind", AMB), (cnt["identity_only"], "Endpoint blind", AMB), (cnt["neither"] + cnt["not_assessed"] + cnt["incomplete"], "Not assessed", GRY)]
    kp = "".join('<div class="kpi" style="--c:%s"><b>%s</b><span>%s</span></div>' % (c, v, l) for v, l, c in kcs)
    bsegs = [kcs[i] for i in (1, 3, 4, 5)]
    btot = sum(v for v, _, _ in bsegs) or 1
    bar = '<div class="bar">%s</div><div class="legend">%s</div>' % (
        "".join('<i style="width:%.2f%%;background:%s"></i>' % (v * 100.0 / btot, c) for v, _, c in bsegs if v),
        "".join('<span><em style="background:%s"></em>%s %s</span>' % (c, l, v) for v, l, c in bsegs))
    stale = [t for t in rows if t["snapshot"] and (datetime.datetime.now(datetime.timezone.utc) - t["snapshot"]).days >= 2]
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Identity versus endpoint coverage map</title><style>
{css}
</style></head><body><div class="hero"><div class="wrap"><div class="eyebrow">Coverage map</div><h1>Identity versus endpoint coverage map</h1>
<p>{n} tenants on the {site} connector &middot; Prepared {prep} &middot; Read-only, from resource dumps</p></div></div>
<div class="wrap"><div class="kpis kpis6">{kp}</div>
<div class="read"><p><b>What it shows.</b> For each tenant, the Microsoft 365 users who hold a license against the endpoints and users that its EDR dumps show. {nu} of the {nb} tenants that have both are under-covered by more than {up}% of their seats; the work queue below ranks them.</p>
<p><b>Read this carefully.</b> The gap is directional, not exact. EDR users are the last-login users of the EDR hosts, so shared machines undercount and users with several hosts overcount; a clean row is not full coverage, and a tenant may use an EDR or identity provider that is not collected here.</p></div>
<div class="panel">{bar}</div>
<h2><span class="n">1</span>Work queue: largest gaps first</h2>
<div class="tw"><table><colgroup><col style="width:8%"><col style="width:52%"><col style="width:20%"><col style="width:20%"></colgroup><tr><th>#</th><th>Tenant</th><th class="r">Licensed users without a managed endpoint (gap)</th><th class="r">Gap %</th></tr>{ranked}</table></div>
<div class="panel">{chart}</div>
{sections}
<div class="foot"><h2>Limits</h2><ul>
<li>A licensed seat is an enabled Member account with at least one assigned license; guests, disabled and unlicensed accounts are not seats. The raw user count is shown in the CSV.</li>
<li>EDR hosts are Falcon records, SentinelOne agents that are not decommissioned or uninstalled, and Defender machines that are Onboarded. Defender has no user field, so it adds hosts but no users.</li>
<li>The gap is seats minus distinct EDR users, and is only computed where a Falcon or SentinelOne dump exists. The CSV's edr_hosts adds the products together, so a machine with two agents counts twice.</li>
<li>Each figure is a snapshot as of the dump time (CSV column snapshot_utc), not a period.{stale_note}</li>
<li>Tenants assessed: {nb} of {n} have both sides; the others are listed above with the reason. No coverage is implied for a tenant that is not in the table.</li></ul>
<h2>Methodology</h2><p class="small">Read-only calls through the {site} MCP connector: one list_resource_dumps per account, and the office365User, falconAgent, sentinelOneAgent and msDefenderMachine dumps of the accounts that have them. Every figure is computed from the downloaded dumps by build_report.py; a per-tenant CSV accompanies this report.</p></div>
</div></body></html>""".format(css=CSS, n=len(rows), site=E(a.site), prep=E(prep), nu=len(under), nb=cnt["both"], up=int(UNDER * 100), kp=kp, bar=bar, ranked=ranked,
                                chart=bars([(t["display"], t["gap"]) for t in under[:10]], RED) or "<span class=\"small\">No under-covered tenant to chart.</span>",
                                sections="".join(sections), stale_note=(" %d tenant(s) have a dump older than two days: %s." % (len(stale), E(", ".join(t["display"] for t in stale)))) if stale else "")
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote %s and %s | %d tenants: %s | patterns: %s" % (a.out, a.csv, len(rows), dict(cnt), dict(pat)))
    for w in warns:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
