#!/usr/bin/env python3
"""
office-user-investigation : build_report.py

Turns raw Office365-datalake KQL results (saved by the agent as JSON) into a
single self-contained HTML investigation report + GeoIP map, and optionally a PDF.

Geolocation is done OFFLINE via the bundled MaxMind GeoLite2-City database
(pip package `maxminddb-geolite2`). Country outlines are loaded from
assets/countries/<ISO3>.geo.json (seeded set) plus any <ISO3>.geo.json the agent
fetched into <workdir>/countries/ for countries not already bundled.

Usage:
  python3 build_report.py \
    --workdir   /tmp/oui_work \
    --skill-dir /abs/path/to/office-user-investigation \
    --username  user@contoso.com \
    --from-ms   1773862340254 \
    --to-ms     1781638340254 \
    --output    /tmp/oui_work/report.html \
    [--pdf      /tmp/oui_work/report.pdf]

Expected files in --workdir (raw kql_search tool output is fine; see SKILL.md):
  ip_summary.json   (required) ClientIP, events, logins, failed, sends, firstSeen, lastSeen
  inbox_rules.json  (optional) timestamp, Operation, ClientIP, ResultStatus, Parameters
  oauth.json        (optional) timestamp, Operation, ClientIP, ResultStatus, Target ...
  timeline.json     (optional) bin, Operation, logins
  workload.json     (optional) Workload, events
  operation.json    (optional) Operation, events
  user_record.json  (optional) get_azure_user_record output
"""
import argparse, json, os, glob, math, html as _H, datetime as dt, collections

# ----------------------------- helpers --------------------------------------
def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return None

def table_to_dicts(obj):
    """Accept raw kql_search output (or already-extracted forms) -> list[dict]."""
    if obj is None:
        return []
    data = obj
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], dict):
            data = obj["data"]
        if "Tables" in data:
            t = data["Tables"][0]
            cols = [c["ColumnName"] for c in t["Columns"]]
            return [dict(zip(cols, r)) for r in t["Rows"]]
        if "objects" in obj:  # FPL-style fallback
            try:
                tbl = obj["objects"][0]["table"]
                cols = [c["name"] for c in tbl["columns"]]
                rows = tbl["rows"]
                if rows and isinstance(rows[0], dict):
                    return rows
                return [dict(zip(cols, r)) for r in rows]
            except Exception:
                return []
    if isinstance(obj, list):
        return obj
    return []

def num(x):
    try:
        return int(x)
    except Exception:
        try:
            return float(x)
        except Exception:
            return 0

def parse_ts(s):
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None

# ----------------------------- geolocation ----------------------------------
def get_geo_reader():
    from geolite2 import geolite2
    return geolite2.reader()

def geolocate(reader, ip):
    try:
        m = reader.get(ip)
    except Exception:
        m = None
    if not m:
        return (None, None, None, None)
    cc = (m.get("country", {}) or {}).get("iso_code")
    city = ((m.get("city", {}) or {}).get("names", {}) or {}).get("en")
    loc = m.get("location", {}) or {}
    return (cc, city, loc.get("latitude"), loc.get("longitude"))

CCNAME = {"US":"United States","ES":"Spain","IR":"Iran","DK":"Denmark","GB":"United Kingdom",
 "DE":"Germany","FR":"France","NL":"Netherlands","RU":"Russia","CN":"China","NG":"Nigeria",
 "CA":"Canada","BR":"Brazil","IN":"India","TR":"Turkey","UA":"Ukraine","RO":"Romania",
 "PL":"Poland","IT":"Italy","PT":"Portugal","??":"Unresolved"}
def ccn(cc):
    return CCNAME.get(cc, cc or "?")

# ----------------------------- rule parsing ---------------------------------
def parse_params(raw):
    """inbox-rule Parameters -> dict {Name:Value}."""
    if not raw:
        return {}
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
        return {d.get("Name"): d.get("Value") for d in arr if isinstance(d, dict)}
    except Exception:
        return {}

def rule_effect(p):
    bits = []
    for k in ("From", "FromAddressContainsWords", "SubjectContainsWords", "SentTo"):
        if p.get(k):
            bits.append(f"from/match <b>{_H.escape(str(p[k]))}</b>")
    if p.get("MoveToFolder"):
        bits.append(f"&rarr; <b>{_H.escape(str(p['MoveToFolder']))}</b>")
    if str(p.get("DeleteMessage", "")).lower() == "true":
        bits.append("<b>delete</b>")
    if str(p.get("MarkAsRead", "")).lower() == "true":
        bits.append("mark read")
    if str(p.get("StopProcessingRules", "")).lower() == "true":
        bits.append("stop-processing")
    return "; ".join(bits) or "&mdash;"

# ----------------------------- map ------------------------------------------
def build_map_svg(points, skill_dir, workdir):
    # gather country outlines we have
    outlines = []
    for d in (os.path.join(skill_dir, "assets", "countries"), os.path.join(workdir, "countries")):
        for f in glob.glob(os.path.join(d, "*.geo.json")):
            fc = load(f)
            if not fc:
                continue
            for feat in fc.get("features", [fc]):
                g = feat.get("geometry") or feat
                if g and g.get("type") in ("Polygon", "MultiPolygon"):
                    outlines.append(g)
    pts = [p for p in points if p["lat"] is not None]
    if not pts:
        return '<div class="note">No geolocatable IPs to map.</div>'
    # dynamic crop around points
    lons = [p["lon"] for p in pts]; lats = [p["lat"] for p in pts]
    LON0 = max(-180, min(lons) - 12); LON1 = min(180, max(lons) + 12)
    LAT0 = max(-58, min(lats) - 8);   LAT1 = min(82, max(lats) + 8)
    if LON1 - LON0 < 40: LON0 -= 20; LON1 += 20
    if LAT1 - LAT0 < 20: LAT0 -= 10; LAT1 += 10
    W = 1180; H = max(220, int(W * (LAT1 - LAT0) / (LON1 - LON0)))
    def proj(lo, la):
        return ((lo - LON0) / (LON1 - LON0) * W, (LAT1 - la) / (LAT1 - LAT0) * H)
    paths = []
    for g in outlines:
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                if len(ring) < 3:
                    continue
                paths.append("M" + "L".join(f"{proj(a,b)[0]:.1f},{proj(a,b)[1]:.1f}" for a, b in ring) + "Z")
    land = " ".join(paths)
    grat = []
    lon = math.ceil(LON0/20)*20
    while lon <= LON1:
        x,_ = proj(lon, 0); grat.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{H}"/>'); lon += 20
    lat = math.ceil(LAT0/20)*20
    while lat <= LAT1:
        _,y = proj(0, lat); grat.append(f'<line x1="0" y1="{y:.1f}" x2="{W}" y2="{y:.1f}"/>'); lat += 20
    col = {"primary":"#3fb950","home_other":"#4493f8","foreign":"#f85149","attacker":"#b81d13"}
    # jitter identical coords
    seen = collections.defaultdict(int)
    for p in pts:
        k = (round(p["lat"],2), round(p["lon"],2)); n = seen[k]; seen[k]+=1
        if n:
            a = n*2.39996; rn=(n//8)+1
            p["lat"] += 0.5*math.cos(a)*rn; p["lon"] += 0.5*math.sin(a)*rn
    def rad(e): return max(3.4, min(20, 2.6 + math.sqrt(max(0,e))*0.85))
    circ = []
    for p in sorted(pts, key=lambda d:-d["events"]):
        if not (LON0 <= p["lon"] <= LON1 and LAT0 <= p["lat"] <= LAT1):
            continue
        x,y = proj(p["lon"], p["lat"]); c = col.get(p["cls"], "#4493f8")
        tip = f'{p["ip"]} | {(p["city"] or "")} {p["cc"] or "?"} | events {p["events"]}, logins {p["logins"]}, failed {p["failed"]}, sends {p["sends"]}'
        circ.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad(p["events"]):.1f}" fill="{c}" fill-opacity="0.55" stroke="{c}" stroke-width="1"><title>{_H.escape(tip)}</title></circle>')
    return (f'<svg class="geomap" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0a0e14"/>'
            f'<g stroke="#162030" stroke-width="0.6">{"".join(grat)}</g>'
            f'<path d="{land}" fill="#1b2532" stroke="#33414f" stroke-width="0.5"/>'
            f'{"".join(circ)}</svg>')

# ----------------------------- bars -----------------------------------------
def build_bars_svg(timeline_rows):
    by = collections.OrderedDict()
    for r in timeline_rows:
        d = str(r.get("bin") or r.get("timestamp") or "")[:10]
        op = r.get("Operation",""); n = num(r.get("logins") or r.get("count") or 0)
        by.setdefault(d, [0,0])
        if op == "UserLoggedIn": by[d][0]+=n
        elif op == "UserLoginFailed": by[d][1]+=n
    items = [(d,s,f) for d,(s,f) in by.items() if (s or f)]
    if not items:
        return ""
    mx = max(s+f for _,s,f in items) or 1
    n = len(items); BW=900; gap=3; bw=(BW-gap*(n-1))/n; base=110
    out = [f'<rect x="0" y="0" width="{BW}" height="120" fill="#0a0e14"/>']
    for i,(d,s,f) in enumerate(items):
        tot=s+f; h=max(2,80*tot/mx); fs=h*s/tot if tot else 0; ff=h-fs; x=i*(bw+gap)
        out.append(f'<rect x="{x:.1f}" y="{base-ff:.1f}" width="{bw:.1f}" height="{ff:.1f}" fill="#f85149"><title>{d}: {s} ok / {f} failed</title></rect>')
        out.append(f'<rect x="{x:.1f}" y="{base-h:.1f}" width="{bw:.1f}" height="{fs:.1f}" fill="#4493f8"><title>{d}: {s} ok / {f} failed</title></rect>')
    return f'<svg viewBox="0 0 {BW} 120" style="width:100%;height:auto;display:block;border:1px solid #2a3340;border-radius:8px">{"".join(out)}</svg>'

# ----------------------------- main -----------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--skill-dir", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--from-ms", type=int, required=True)
    ap.add_argument("--to-ms", type=int, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--pdf", default=None)
    a = ap.parse_args()
    wd = a.workdir

    iprows = table_to_dicts(load(os.path.join(wd, "ip_summary.json")))
    rules  = table_to_dicts(load(os.path.join(wd, "inbox_rules.json")))
    oauth  = table_to_dicts(load(os.path.join(wd, "oauth.json")))
    timeln = table_to_dicts(load(os.path.join(wd, "timeline.json")))
    wload  = table_to_dicts(load(os.path.join(wd, "workload.json")))
    if not iprows:
        raise SystemExit("ERROR: ip_summary.json missing or empty in workdir")

    reader = get_geo_reader()
    iso2to3 = load(os.path.join(a.skill_dir, "assets", "iso2_to_iso3.json")) or {}

    pts = []
    for r in iprows:
        ip = r.get("ClientIP") or r.get("clientip")
        if not ip or ip in ("NA", "null", "<>"):
            continue
        ev = num(r.get("events")); lo = num(r.get("logins")); fa = num(r.get("failed")); se = num(r.get("sends"))
        # Prefer the platform _ip enrichment (current, city-accurate) when the
        # query supplies it; fall back to the bundled offline GeoLite2 DB.
        cc   = (str(r.get("CC") or r.get("countryCode") or "")).strip() or None
        city = (str(r.get("City") or r.get("city") or "")).strip() or None
        isp  = (str(r.get("ISP") or r.get("isp") or "")).strip() or None
        try:    lat = float(r.get("Lat")); lon = float(r.get("Lon"))
        except (TypeError, ValueError): lat = lon = None
        if not (cc and lat is not None and lon is not None):
            gcc, gcity, glat, glon = geolocate(reader, ip)
            cc = cc or gcc; city = city or gcity
            if lat is None or lon is None: lat, lon = glat, glon
        pts.append({"ip":ip,"events":ev,"logins":lo,"failed":fa,"sends":se,
                    "cc":cc,"city":city,"isp":isp,"lat":lat,"lon":lon,
                    "first":r.get("firstSeen"),"last":r.get("lastSeen")})
    pts.sort(key=lambda d:-d["events"])

    # home country = country of the highest-event IP
    home_cc = pts[0]["cc"] if pts else None
    attacker_ips = {r.get("ClientIP") for r in rules
                    if r.get("Operation") in ("New-InboxRule","Set-InboxRule") and r.get("ClientIP")}
    # classify
    primary_assigned = 0
    for p in pts:
        if p["ip"] in attacker_ips:
            p["cls"] = "attacker"
        elif p["cc"] and home_cc and p["cc"] == home_cc:
            if primary_assigned < 2 and p["events"] >= 50:
                p["cls"] = "primary"; primary_assigned += 1
            else:
                p["cls"] = "home_other"
        elif p["cc"] is None:
            p["cls"] = "home_other"
        else:
            p["cls"] = "foreign"

    # required country outlines present?
    needed = {p["cc"] for p in pts if p["cc"]}
    have = {os.path.basename(f)[:3] for f in
            glob.glob(os.path.join(a.skill_dir,"assets","countries","*.geo.json")) +
            glob.glob(os.path.join(wd,"countries","*.geo.json"))}
    missing = sorted({iso2to3.get(cc, cc) for cc in needed} - have)
    if missing:
        print("WARN: no outline bundled for ISO3:", ",".join(missing),
              "(dots still plotted; fetch these into <workdir>/countries/ for full coverage)")

    # ---- metrics & signals ----
    tot_events = sum(p["events"] for p in pts)
    succ = sum(p["logins"] for p in pts)
    fail = sum(p["failed"] for p in pts)
    rule_creations = [r for r in rules if r.get("Operation") in ("New-InboxRule","Set-InboxRule")]
    n_rules = len(rule_creations)
    foreign = [p for p in pts if p["cls"] in ("foreign","attacker")]
    n_susp = len(foreign)
    n_oauth = len([r for r in oauth if r.get("Operation") == "Consent to application."]) or len(oauth)
    to_dtm = dt.datetime.fromtimestamp(a.to_ms/1000, dt.timezone.utc)
    def days_ago(ts):
        t = parse_ts(ts)
        if not t: return 999
        if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
        return (to_dtm - t).days
    ongoing = [p for p in foreign if days_ago(p["last"]) <= 7]

    has_rules = n_rules > 0
    has_foreign = any(p["cls"] == "foreign" for p in pts)
    # verdict
    if has_rules and (has_foreign or attacker_ips):
        sev = ("CRITICAL — LIKELY ACTIVE COMPROMISE" if ongoing else "CRITICAL — LIKELY COMPROMISE")
        sevcls = "crit"
    elif has_rules or has_foreign:
        sev = "HIGH — SUSPICIOUS ACTIVITY"; sevcls = "high"
    else:
        sev = "LOW — NO STRONG COMPROMISE INDICATORS"; sevcls = "low"

    # rule targets for narrative
    targets = []
    for r in rule_creations:
        p = parse_params(r.get("Parameters"))
        for k in ("FromAddressContainsWords","From","SubjectContainsWords"):
            if p.get(k): targets.append(str(p[k]))
    targets = list(dict.fromkeys(targets))[:6]

    fmt = lambda ms: dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%b %d %Y")
    win = f"{fmt(a.from_ms)} &rarr; {fmt(a.to_ms)}"

    # ---- narrative strings ----
    foreign_ccs = sorted({ccn(p["cc"]) for p in pts if p["cls"]=="foreign"})
    exec_lines = []
    exec_lines.append(f'Over the investigation window the mailbox <span class="mono">{_H.escape(a.username)}</span> generated {tot_events:,} Office 365 audit events across {len(pts)} source IPs, with {succ} successful and {fail} failed sign-ins.')
    if pts:
        exec_lines.append(f'Highest-volume access is from <span class="mono">{pts[0]["ip"]}</span> ({ccn(pts[0]["cc"])}, {pts[0]["events"]:,} events), treated as the legitimate user.')
    if has_foreign:
        exec_lines.append(f'The mailbox is <b>also accessed from non-home countries</b> ({", ".join(foreign_ccs)}) &mdash; a strong impossible-travel signal.')
    if has_rules:
        tt = (" targeting " + ", ".join(f'<span class="mono">{_H.escape(t)}</span>' for t in targets)) if targets else ""
        exec_lines.append(f'<b>{n_rules} inbox-rule creation/modification event(s)</b> were performed{tt}; rules that move mail to low-visibility folders, mark-as-read and stop-processing are classic Business Email Compromise concealment.')
    if ongoing:
        exec_lines.append(f'<b>Suspicious access is ongoing</b> (last seen within 7 days of the window end). Treat the account as currently compromised.')
    if n_oauth:
        exec_lines.append(f'{n_oauth} OAuth application consent / permission-grant event(s) were recorded &mdash; review for illicit consent.')

    # ---- findings rows ----
    fr = []
    if has_rules:
        ev = f'{n_rules} New/Set-InboxRule from {", ".join(sorted({r.get("ClientIP") for r in rule_creations if r.get("ClientIP")})) or "n/a"}'
        fr.append(("Hidden / maliciously-created inbox rules", ev + ((" — targets: "+", ".join(targets)) if targets else ""), "Critical"))
    if has_foreign:
        topf = ", ".join(f'{p["ip"]} ({p["cc"]})' for p in foreign[:4])
        fr.append(("Concurrent foreign mailbox access", topf, "Critical"))
    if ongoing:
        fr.append(("Activity ongoing near window end", ", ".join(f'{p["ip"]} last {str(p["last"])[:10]}' for p in ongoing[:4]), "Critical"))
    if fail >= 20:
        fr.append(("Elevated failed sign-ins", f"{fail} UserLoginFailed events across the window", "High"))
    if n_oauth:
        fr.append(("OAuth application consent grant(s)", f"{n_oauth} consent/permission event(s) — verify the app(s)", "Review"))
    sevtag = {"Critical":"red","High":"amb","Review":"amb"}

    # ---- tables ----
    roll = collections.defaultdict(lambda:[0,0,0,0,0])
    for p in pts:
        c = p["cc"] or "??"; v = roll[c]
        v[0]+=1; v[1]+=p["events"]; v[2]+=p["logins"]; v[3]+=p["failed"]; v[4]+=p["sends"]
    cc_html = "".join(f"<tr><td>{ccn(c)} <span class=cc>{c}</span></td><td>{v[0]}</td><td>{v[1]:,}</td><td>{v[2]}</td><td>{v[3]}</td><td>{v[4]}</td></tr>"
                      for c,v in sorted(roll.items(), key=lambda x:-x[1][1]))
    lab = {"attacker":"rule/BEC","foreign":"foreign"}
    fr_html = "".join(
        f'<tr><td class=mono>{p["ip"]}</td><td>{ccn(p["cc"])} <span class=cc>{p["cc"] or "?"}</span></td>'
        f'<td>{p["city"] or "—"}</td><td>{p["events"]}</td><td>{p["logins"]}</td><td>{p["failed"]}</td>'
        f'<td>{p["sends"]}</td><td><span class="chip {p["cls"]}">{lab.get(p["cls"],p["cls"])}</span></td></tr>'
        for p in foreign)
    # inbox rule detail
    rr_html = ""
    for r in rule_creations:
        p = parse_params(r.get("Parameters"))
        rr_html += (f'<tr><td class=mono>{str(r.get("timestamp"))[:16]}</td><td>{_H.escape(str(r.get("Operation")))}</td>'
                    f'<td class="mono bad">{_H.escape(str(r.get("ClientIP") or "—"))}</td>'
                    f'<td>{_H.escape(str(p.get("Name","—")))}</td><td>{rule_effect(p)}</td></tr>')
    susp_html = "".join(
        f'<tr><td class=mono {"bad" if p["cls"] in ("foreign","attacker") else ""}>{p["ip"]}</td>'
        f'<td>{ccn(p["cc"])} <span class=cc>{p["cc"] or "?"}</span></td><td>{p["city"] or "—"}</td>'
        f'<td>{p.get("isp") or "—"}</td>'
        f'<td>{p["events"]}</td><td>{p["logins"]}</td><td>{p["failed"]}</td><td>{p["sends"]}</td>'
        f'<td>{str(p["first"])[:10]}</td><td>{str(p["last"])[:10]}</td></tr>'
        for p in pts[:30])
    map_svg = build_map_svg(pts, a.skill_dir, wd)
    bars_svg = build_bars_svg(timeln)

    # recommendations (conditional)
    recs = []
    recs.append(("NOW","Contain the account — reset password, <b>revoke all active sessions / refresh tokens</b>, force re-MFA. A password reset alone will not evict a token-holding attacker."))
    if has_rules:
        recs.append(("NOW","Remove the malicious inbox rules listed above and audit for any others; they persist independently of the password."))
    if n_oauth:
        recs.append(("NOW","Review and revoke any unsanctioned OAuth application grants."))
    if targets:
        recs.append(("HIGH","Warn the affected counterparties / internal users in the rule targets that threads may have been intercepted; verify payment/banking changes out-of-band."))
    recs.append(("HIGH","Recover hidden/deleted mail and review Sent Items from the suspicious IPs for fraudulent outbound messages."))
    if foreign:
        recs.append(("MED","Block / watchlist the suspicious source IPs and enable a conditional-access / impossible-travel policy."))
    recs.append(("MED","Hunt laterally — check whether the same IPs, OAuth apps or inbox-rule patterns appear on other mailboxes."))
    sevc = {"NOW":"c","HIGH":"h","MED":"m"}

    wload_note = ""
    if wload:
        wl = ", ".join(f'{w.get("Workload")} ({num(w.get("events")):,})' for w in wload[:6])
        wload_note = f'<p class="note">Workload breakdown: {wl}.</p>'

    # ----------------------------- HTML -------------------------------------
    HTML = f"""<!DOCTYPE html><html lang=en><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width, initial-scale=1.0">
<title>O365 Investigation — {_H.escape(a.username)}</title><style>
:root{{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--line:#2a3340;--txt:#e6edf3;--muted:#9aa7b4;--blue:#4493f8;--amber:#f0a020;--red:#f85149;--green:#3fb950;--dred:#b81d13}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:14px;line-height:1.5}}
.wrap{{max-width:1100px;margin:0 auto;padding:30px 22px 60px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px;flex-wrap:wrap;gap:14px}}
.brand{{font-weight:700;font-size:17px;letter-spacing:.5px}}.brand span{{color:var(--blue)}}
h1{{font-size:21px;margin:4px 0 6px}}.sub{{color:var(--muted);font-size:13px}}.mono{{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace}}.cc{{color:var(--muted);font-size:11px}}
.meta{{text-align:right;font-size:12px;color:var(--muted)}}.meta b{{color:var(--txt)}}
.verdict{{border-radius:10px;padding:16px 20px;margin:0 0 24px;border:1px solid var(--red);background:linear-gradient(90deg,rgba(248,81,73,.16),rgba(248,81,73,.04))}}
.verdict.high{{border-color:var(--amber);background:linear-gradient(90deg,rgba(240,160,32,.15),rgba(240,160,32,.03))}}
.verdict.low{{border-color:var(--green);background:linear-gradient(90deg,rgba(63,185,80,.13),rgba(63,185,80,.03))}}
.verdict .tag{{display:inline-block;background:var(--red);color:#fff;font-weight:700;font-size:12px;padding:3px 10px;border-radius:20px}}
.verdict.high .tag{{background:var(--amber);color:#000}}.verdict.low .tag{{background:var(--green);color:#000}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:26px}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}.kpi .n{{font-size:24px;font-weight:700}}.kpi .l{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
.kpi.alert .n{{color:var(--red)}}.kpi.warn .n{{color:var(--amber)}}
section{{margin-bottom:28px}}h3{{font-size:15px;border-left:3px solid var(--blue);padding-left:10px;margin:0 0 13px}}h3.r{{border-color:var(--red)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}}
th{{background:var(--panel2);color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}}tr:last-child td{{border-bottom:none}}
td.bad,.bad{{color:var(--red)}}
.chip{{font-size:11px;padding:1px 8px;border-radius:12px;color:#fff;background:var(--panel2);border:1px solid var(--line);white-space:nowrap;display:inline-block}}
.chip.foreign{{background:rgba(248,81,73,.85);border-color:var(--red)}}.chip.attacker{{background:var(--dred);border-color:var(--dred)}}.chip.red{{background:rgba(248,81,73,.85)}}.chip.amb{{background:rgba(240,160,32,.85);color:#000}}
svg.geomap{{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:10px;background:#0a0e14}}
.maplegend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:10px 0 4px}}.maplegend i{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}}
.geocaveat{{border:1px solid var(--amber);background:rgba(240,160,32,.08);border-radius:8px;padding:11px 15px;margin:6px 0 14px;font-size:12px;color:#f0d9a8}}
.geogrid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:14px}}@media(max-width:820px){{.geogrid{{grid-template-columns:1fr}}.kpis{{grid-template-columns:repeat(2,1fr)}}}}
ol.rec{{padding-left:18px}}ol.rec li{{margin-bottom:9px}}.sev{{font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px;margin-right:6px}}.sev.c{{background:var(--red);color:#fff}}.sev.h{{background:var(--amber);color:#000}}.sev.m{{background:var(--blue);color:#fff}}
.note{{color:var(--muted);font-size:12px;margin-top:8px}}footer{{border-top:1px solid var(--line);margin-top:36px;padding-top:14px;color:var(--muted);font-size:11px}}
</style></head><body><div class=wrap>
<header><div><div class=brand>FLUENCY<span>·</span>Ingext</div><h1>Office 365 User Investigation</h1>
<div class="sub mono">{_H.escape(a.username)}</div></div>
<div class=meta><div>Window: <b>{win}</b></div><div>Generated: <b>{dt.datetime.now(dt.timezone.utc).strftime("%b %d %Y")}</b></div>
<div>Source: <b>Office365 datalake (KQL)</b></div><div>Events analysed: <b>{tot_events:,}</b></div></div></header>

<div class="verdict {sevcls}"><span class=tag>{sev}</span>
<p style="margin:10px 0 0">{exec_lines[0]}</p></div>

<div class=kpis>
<div class=kpi><div class="n">{succ}</div><div class=l>Successful sign-ins</div></div>
<div class="kpi warn"><div class="n">{fail}</div><div class=l>Failed sign-ins</div></div>
<div class="kpi {'alert' if n_rules else ''}"><div class="n">{n_rules}</div><div class=l>Malicious inbox rules</div></div>
<div class="kpi {'alert' if n_susp else ''}"><div class="n">{n_susp}</div><div class=l>Suspicious source IPs</div></div>
<div class="kpi {'warn' if n_oauth else ''}"><div class="n">{n_oauth}</div><div class=l>OAuth consent grants</div></div></div>

<section><h3 class=r>Executive summary</h3><p>{" ".join(exec_lines)}</p>{wload_note}</section>

<section><h3 class=r>High-risk findings</h3>
<table><tr><th>#</th><th>Finding</th><th>Evidence</th><th>Severity</th></tr>
{"".join(f'<tr><td>{i+1}</td><td><b>{t}</b></td><td>{_H.escape(e)}</td><td><span class="chip {sevtag.get(s,"amb")}">{s}</span></td></tr>' for i,(t,e,s) in enumerate(fr)) or '<tr><td colspan=4 class=note>No high-risk findings triggered by the heuristics.</td></tr>'}
</table></section>

{f'''<section><h3 class=r>Malicious inbox rules (detail)</h3>
<table><tr><th>Time (UTC)</th><th>Op</th><th>Source IP</th><th>Rule name</th><th>Effect</th></tr>{rr_html}</table>
<p class=note>Rules with obfuscated names, moves to low-visibility folders, mark-as-read and stop-processing flags are concealment techniques used to hijack payment/invoice threads.</p></section>''' if rr_html else ''}

<section><h3 class=r>GeoIP map of all sign-ins &amp; activity</h3>
<div class=geocaveat><b>&#9888; Geolocation is approximate.</b> Source-IP coordinates use the platform&rsquo;s live GeoIP enrichment (country / city / ISP) when present in the query, and fall back to the bundled offline GeoLite2 database otherwise. Treat as indicative, not authoritative &mdash; confirm with live threat intelligence before formal attribution.</div>
{map_svg}
<div class=maplegend><span><i style="background:#3fb950"></i>Primary user (home country)</span><span><i style="background:#4493f8"></i>Other home-country IPs</span><span><i style="background:#f85149"></i>Foreign access</span><span><i style="background:#b81d13"></i>Inbox-rule / BEC IPs</span><span>dot size &prop; event count</span></div>
<div class=geogrid>
<div><h3>Activity by country <span class=cc>(GeoLite, approx.)</span></h3>
<table><tr><th>Country</th><th>IPs</th><th>Events</th><th>Logins</th><th>Failed</th><th>Sends</th></tr>{cc_html}</table></div>
<div><h3 class=r>Foreign &amp; rule-creation IPs</h3>
<table><tr><th>IP</th><th>Country</th><th>City</th><th>Ev</th><th>Login</th><th>Fail</th><th>Send</th><th>Class</th></tr>{fr_html or '<tr><td colspan=8 class=note>None detected.</td></tr>'}</table></div>
</div></section>

{f'''<section><h3>Sign-in timeline (daily success vs. failed)</h3>{bars_svg}<p class=note>Blue = successful logins, red = failed.</p></section>''' if bars_svg else ''}

<section><h3 class=r>Top source IPs</h3>
<table><tr><th>IP</th><th>Country</th><th>City</th><th>ISP</th><th>Events</th><th>Logins</th><th>Failed</th><th>Sends</th><th>First</th><th>Last</th></tr>{susp_html}</table></section>

<section><h3 class=r>Recommended actions</h3><ol class=rec>
{"".join(f'<li><span class="sev {sevc[s]}">{s}</span>{t}</li>' for s,t in recs)}
</ol></section>

<footer>Generated by the office-user-investigation skill from the Office365 datalake via KQL. Inbox-rule, OAuth and IP details extracted directly from Office 365 Management Activity audit records. Geolocation: offline MaxMind GeoLite2-City — verify with live threat intelligence before formal reporting.</footer>
</div></body></html>"""

    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    open(a.output, "w").write(HTML)
    print("HTML written:", a.output)

    if a.pdf:
        try:
            override = "<style>.geogrid{grid-template-columns:1fr !important}table{font-size:11px}td,th{overflow-wrap:anywhere}td.mono,.mono{white-space:nowrap}</style>"
            from weasyprint import HTML as WHTML
            WHTML(string=HTML.replace("</head>", override+"</head>", 1)).write_pdf(a.pdf)
            print("PDF written:", a.pdf)
        except Exception as e:
            print("PDF step skipped (", e, ")")

if __name__ == "__main__":
    main()
