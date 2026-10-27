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
NAVY, RED, AMB, GRN, GRY = "#1C2B45", "#B91C1C", "#B45309", "#15803D", "#64748B"
PATTERNS = {"under": ("EDR under-coverage", RED), "aligned": ("Aligned", GRN), "over": ("EDR users exceed licensed seats", AMB)}
E = html.escape


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
        return "<tr><td>%s<br><span class=\"small\">%s</span></td><td class=\"r\">%s</td><td>%s</td><td class=\"r\">%s</td><td class=\"r\"><b>%s</b></td><td class=\"r\">%s</td></tr>" % (
            E(t["display"]), E(t["name"]), n(t["seats"]), host_cell(t), n(t["edr_users"]), n(t["gap"]), ("%.0f%%" % t["gap_pct"]) if t["gap_pct"] is not None else "n/a")
    heads = "<tr><th>Tenant</th><th class=\"r\">Licensed seats</th><th>EDR hosts (per product)</th><th class=\"r\">EDR users</th><th class=\"r\">Gap</th><th class=\"r\">Gap %</th></tr>"

    def table(trs):
        cols = "".join('<col style="width:%s">' % w for w in ("26%", "13%", "29%", "12%", "10%", "10%"))
        return "<table><colgroup>" + cols + "</colgroup>" + heads + "".join(trs) + "</table>"

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
    for key in ("under", "over", "aligned"):
        grp = [t for t in both if t["pattern"] == key]
        if grp:
            sections.append("<h2>%s (%d)</h2>%s" % (PATTERNS[key][0], len(grp), table([row_html(t) for t in grp])))
    edr_only = [t for t in rows if t["bucket"] == "edr_only"]
    id_only = [t for t in rows if t["bucket"] == "identity_only"]
    neither = [t for t in rows if t["bucket"] in ("neither", "not_assessed")]
    incomplete = [t for t in rows if t["bucket"] == "incomplete"]
    defender_only = [t for t in rows if t["bucket"] == "both" and t["pattern"] is None]
    if defender_only:
        sections.append("<h2>Identity and Defender only (%d)</h2><p class=\"small\">Defender machines carry no user name, so a seat-to-user gap cannot be computed.</p>%s" % (len(defender_only), table([row_html(t) for t in defender_only])))
    if edr_only:
        tot = sum(t["edr_hosts"] or 0 for t in edr_only)
        sections.append("<h2>Identity blind (%d)</h2><p class=\"small\">Endpoints exist but there is no Microsoft 365 user dump to say whose they are: %s endpoints in total.</p>%s" % (
            len(edr_only), n(tot), table([row_html(t) for t in edr_only])))
    if id_only:
        sections.append("<h2>Endpoint blind (%d)</h2><p class=\"small\">A Microsoft 365 user dump but no EDR roster. The tenant may use an EDR that is not collected here.</p><table><tr><th>Tenant</th><th class=\"r\">Licensed seats</th></tr>%s</table>" % (
            len(id_only), "".join("<tr><td>%s<br><span class=\"small\">%s</span></td><td class=\"r\">%s</td></tr>" % (E(t["display"]), E(t["name"]), n(t["seats"])) for t in id_only)))
    if incomplete:
        sections.append("<h2>Not collected (%d)</h2><p class=\"small\">The dump is listed for these tenants but its file was not downloaded, so they are not assessed.</p><ul>%s</ul>" % (
            len(incomplete), "".join("<li>%s: %s</li>" % (E(t["display"]), E(", ".join(t["not_collected"]))) for t in incomplete)))
    if neither:
        sections.append("<h2>Not assessable (%d)</h2><p class=\"small\">Neither a Microsoft 365 user dump nor an EDR dump.</p><p>%s</p>" % (len(neither), E(", ".join(t["display"] for t in neither))))
    ranked = "".join("<tr><td>%d</td><td>%s</td><td class=\"r\"><b>%s</b></td><td class=\"r\">%s</td></tr>" % (i + 1, E(t["display"]), n(t["gap"]), ("%.0f%%" % t["gap_pct"])) for i, t in enumerate(under[:15])) or "<tr><td colspan=\"4\">No tenant is under-covered by more than %d%% of its seats.</td></tr>" % int(UNDER * 100)
    kp = "".join('<div class="kpi"><div class="nn" style="color:%s">%s</div><div class="small">%s</div></div>' % (c, v, l) for v, l, c in [
        (len(rows), "Tenants listed", NAVY), (cnt["both"], "With identity and EDR", NAVY), (pat["under"], "Under-covered", RED), (cnt["edr_only"], "Identity blind", AMB), (cnt["identity_only"], "Endpoint blind", AMB), (cnt["neither"] + cnt["not_assessed"] + cnt["incomplete"], "Not assessed", GRY)])
    stale = [t for t in rows if t["snapshot"] and (datetime.datetime.now(datetime.timezone.utc) - t["snapshot"]).days >= 2]
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Identity versus endpoint coverage map</title><style>
*{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;color:#0f172a;margin:0;font-size:13px;line-height:1.5}}
.wrap{{max-width:7.3in;margin:0 auto;padding:24px}}h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #1C2B45;padding-bottom:4px}}.sub{{color:#475569;margin-bottom:12px}}
.lead{{border-left:5px solid #1C2B45;background:#f1f5f9;padding:10px 14px;margin:10px 0}}.lead p{{margin:4px 0}}
.kpis{{display:flex;gap:10px;margin:10px 0}}.kpi{{flex:1;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center}}.kpi .nn{{font-size:22px;font-weight:700}}
table{{width:100%;border-collapse:collapse;table-layout:fixed;font-size:11.5px;margin:6px 0 12px}}th,td{{border-bottom:1px solid #e2e8f0;padding:5px 6px;text-align:left;vertical-align:top;word-wrap:break-word}}
th{{background:#f1f5f9}}.r{{text-align:right}}.small{{font-size:11px;color:#475569}}ul{{margin:4px 0 4px 18px;padding:0}}
.call{{border:1px solid #fcd34d;background:#fffbeb;border-radius:6px;padding:8px 12px;margin:10px 0}}
</style></head><body><div class="wrap"><h1>Identity versus endpoint coverage map</h1>
<div class="sub">{n} tenants on the {site} connector &middot; Prepared {prep} &middot; Read-only, from resource dumps</div>
<div class="lead"><p><b>What it shows.</b> For each tenant, the Microsoft 365 users who hold a license against the endpoints and users that its EDR dumps show. {nu} of the {nb} tenants that have both are under-covered by more than {up}% of their seats; the work queue below ranks them.</p>
<p><b>Read this carefully.</b> The gap is directional, not exact. EDR users are the last-login users of the EDR hosts, so shared machines undercount and users with several hosts overcount; a clean row is not full coverage, and a tenant may use an EDR or identity provider that is not collected here.</p></div>
<div class="kpis">{kp}</div>
<h2>Work queue: largest gaps first</h2>
<table><colgroup><col style="width:8%"><col style="width:52%"><col style="width:20%"><col style="width:20%"></colgroup><tr><th>#</th><th>Tenant</th><th class="r">Licensed users without a managed endpoint (gap)</th><th class="r">Gap %</th></tr>{ranked}</table>
<div style="border:1px solid #e2e8f0;padding:12px 14px;margin:10px 0">{chart}</div>
{sections}
<h2>Limits</h2><ul>
<li>A licensed seat is an enabled Member account with at least one assigned license; guests, disabled and unlicensed accounts are not seats. The raw user count is shown in the CSV.</li>
<li>EDR hosts are Falcon records, SentinelOne agents that are not decommissioned or uninstalled, and Defender machines that are Onboarded. Defender has no user field, so it adds hosts but no users.</li>
<li>The gap is seats minus distinct EDR users, and is only computed where a Falcon or SentinelOne dump exists. The CSV's edr_hosts adds the products together, so a machine with two agents counts twice.</li>
<li>Each figure is a snapshot as of the dump time (CSV column snapshot_utc), not a period.{stale_note}</li>
<li>Tenants assessed: {nb} of {n} have both sides; the others are listed above with the reason. No coverage is implied for a tenant that is not in the table.</li></ul>
<h2>Methodology</h2><p class="small">Read-only calls through the {site} MCP connector: one list_resource_dumps per account, and the office365User, falconAgent, sentinelOneAgent and msDefenderMachine dumps of the accounts that have them. Every figure is computed from the downloaded dumps by build_report.py; a per-tenant CSV accompanies this report.</p>
</div></body></html>""".format(n=len(rows), site=E(a.site), prep=E(prep), nu=len(under), nb=cnt["both"], up=int(UNDER * 100), kp=kp, ranked=ranked,
                                chart=bars([(t["display"], t["gap"]) for t in under[:10]], RED) or "<span class=\"small\">No under-covered tenant to chart.</span>",
                                sections="".join(sections), stale_note=(" %d tenant(s) have a dump older than two days: %s." % (len(stale), E(", ".join(t["display"] for t in stale)))) if stale else "")
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote %s and %s | %d tenants: %s | patterns: %s" % (a.out, a.csv, len(rows), dict(cnt), dict(pat)))
    for w in warns:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
