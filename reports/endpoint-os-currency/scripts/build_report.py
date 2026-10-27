#!/usr/bin/env python3
"""Render the endpoint OS currency report (self-contained HTML + CSV) from one resource dump.

Every figure is computed here from the saved dump; nothing is typed in by hand. A missing or
unreadable dump stops the run (there is nothing to report), it never produces an empty "all good".

Usage:
  build_report.py --source falcon|sentinelone|office365 --dump FILE.jsonl.gz \
      --tenant acme --tenant-name "Example Corp" --site Develop --out report.html --csv hosts.csv

Sources (one per run; use the best one the tenant has, in this order):
  falcon        falconAgent dump          os_version, os_product_name, kernel_version (10.0.BUILD.REV)
  sentinelone   sentinelOneAgent dump     osName, osRevision (build number only, no patch revision)
  office365     office365Device dump      operatingSystem, operatingSystemVersion (no edition / SKU)

Two separate axes, never merged:
  1. Support status: the OS build's vendor support end date from the curated table below, as of
     --as-of. Windows only. macOS is judged by major version; Linux and mobile are inventory only.
  2. Build currency: behind the newest build observed in THIS fleet for the same OS line. The
     fleet maximum, not a vendor-absolute latest.
"""
import argparse, collections, csv, datetime, gzip, html, json, re, sys

# --- curated Windows lifecycle -------------------------------------------------------------
# build -> label, end of security updates for Home/Pro (or the only date), and for Enterprise/Education.
# None means the date is long past and not tracked here. Verify against the Microsoft lifecycle
# pages before quoting a date to a customer; this table carries an as-of date for that reason.
TABLE_AS_OF = "2026-10-23"
CLIENT = {
    7601: ("Windows 7", None, None),
    9200: ("Windows 8", None, None),
    9600: ("Windows 8.1", "2023-01-10", "2023-01-10"),
    19044: ("Windows 10 21H2", "2023-06-13", "2024-06-11"),
    19045: ("Windows 10 22H2", "2025-10-14", "2025-10-14"),
    22000: ("Windows 11 21H2", "2023-10-10", "2024-10-08"),
    22621: ("Windows 11 22H2", "2024-10-08", "2025-10-14"),
    22631: ("Windows 11 23H2", "2025-11-11", "2026-11-10"),
    26100: ("Windows 11 24H2", "2026-10-13", "2027-10-12"),
    26200: ("Windows 11 25H2", "2027-10-12", "2028-10-10"),
}
SERVER = {
    6002: ("Windows Server 2008", "2020-01-14", "2020-01-14"),
    7601: ("Windows Server 2008 R2", "2020-01-14", "2020-01-14"),
    9200: ("Windows Server 2012", "2023-10-10", "2023-10-10"),
    9600: ("Windows Server 2012 R2", "2023-10-10", "2023-10-10"),
    14393: ("Windows Server 2016", "2027-01-12", "2027-01-12"),
    17763: ("Windows Server 2019", "2029-01-09", "2029-01-09"),
    20348: ("Windows Server 2022", "2031-10-14", "2031-10-14"),
    26100: ("Windows Server 2025", "2034-10-10", "2034-10-10"),
}
# Builds shared by a client and a server SKU: with no SKU in the data the status is "verify".
AMBIGUOUS = {14393: "Windows 10 1607", 17763: "Windows 10 1809", 26100: "Windows 11 24H2"}
SOON_DAYS = 180

STATUS = {
    "eol": ("End of support", "#B91C1C"),
    "ending_soon": ("Ending soon", "#B45309"),
    "supported": ("Supported", "#15803D"),
    "verify": ("Verify SKU/edition", "#1D4ED8"),
    "not_assessed": ("Not assessed", "#64748B"),
    "unknown": ("Unknown build", "#64748B"),
}


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
.kpis.five{grid-template-columns:repeat(5,1fr)}
.kpi b{font-size:30px}
.read b.t{display:block;text-transform:uppercase;letter-spacing:.1em;font-size:11px;margin-bottom:4px}
.read p{margin:4px 0}.read b{color:#1e3a8a}
.call{border-left:4px solid #B45309;background:#fffbeb;border-radius:0 10px 10px 0;padding:12px 16px;margin-top:12px;color:#78350f;font-size:13px}
.small{font-size:12px;color:var(--mut);margin:6px 0}
.fig{margin:0}.cap{font-weight:600;color:var(--navy);font-size:13px;margin-bottom:6px}
.fig svg{display:block;width:100%;max-width:640px;height:auto}
.tw table{table-layout:fixed}
td,th{overflow-wrap:anywhere}
td.ctl{white-space:normal;font-family:inherit;font-weight:600}
td.nm{font-weight:600;color:var(--navy)}
.panel .bar{margin-top:0}
.foot h2{font-size:14px;margin:18px 0 6px}.foot ul{margin:4px 0 4px 18px;padding:0}.foot p{margin:4px 0}
@media (max-width:760px){.kpis.five{grid-template-columns:1fr 1fr}}
@media print{body{font-size:12px}.kpis.five{grid-template-columns:repeat(5,1fr);gap:8px}.kpi{padding:10px 12px}.kpi span{font-size:10px}.kpi b{font-size:22px}.wrap{padding:0}.hero{padding:22px 0 54px;border-radius:10px}.hero .wrap{padding:0 22px}.kpis{margin-top:-36px}.call,.read,.tw,.fig,.foot{break-inside:avoid}h2{break-after:avoid}.pill,.call{-webkit-print-color-adjust:exact;print-color-adjust:exact}.kpi b{font-size:24px}}
"""


def load_dump(path, resource):
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line)["@" + resource])
    return out


def parse_ts(v):
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")[:32]).replace(tzinfo=None)
    except ValueError:
        return None


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def family(text):
    t = (text or "").lower()
    if "windows" in t:
        return "windows"
    if "mac" in t or "os x" in t:
        return "mac"
    if t in ("ios", "android") or "ipados" in t:
        return "mobile"
    if t:
        return "linux" if t in ("linux",) or re.search(r"ubuntu|rhel|red hat|debian|centos|suse|fedora|alma|rocky|oracle linux", t) else "other"
    return "other"


def norm_falcon(b):
    kv = (b.get("kernel_version") or "").split(".")
    build = to_int(kv[2]) if len(kv) >= 3 else None
    rev = to_int(kv[3]) if len(kv) >= 4 else None
    if build is None:
        build = to_int(b.get("os_build") or b.get("build_number"))
    prod = b.get("os_product_name") or b.get("os_version") or ""
    fam = family(b.get("platform_name") or b.get("os_version"))
    return dict(host=b.get("hostname"), fam=fam, line=b.get("os_version") or "Unknown", product=prod, build=build, rev=rev,
                server=("server" in (b.get("os_version") or "").lower() or (b.get("product_type_desc") or "") in ("Server", "Domain Controller")) if fam == "windows" else None,
                last=parse_ts(b.get("last_seen")), raw=(b.get("os_version") or ""))


def norm_s1(b):
    name = b.get("osName") or "Unknown"
    fam = family(b.get("osType") or name)
    line = re.sub(r"\s+(Home|Pro|Enterprise|Education|Standard|Datacenter|Essentials|N|multi-session)\b.*$", "", name)
    return dict(host=b.get("computerName"), fam=fam, line=line, product=name, build=to_int(b.get("osRevision")) if fam == "windows" else None,
                rev=None, server=("server" in name.lower()) if fam == "windows" else None,
                last=parse_ts(b.get("lastActiveDate")), raw=name)


def norm_o365(b):
    os_name = b.get("operatingSystem") or "Unknown"
    fam = family(os_name)
    ver = b.get("operatingSystemVersion") or ""
    parts = ver.split(".")
    build = to_int(parts[2]) if fam == "windows" and len(parts) >= 3 and parts[0] == "10" else None
    rev = to_int(parts[3]) if build is not None and len(parts) >= 4 else None
    if fam == "windows" and build is None and ver.startswith(("6.1", "6.2", "6.3")):
        build = {"6.1": 7601, "6.2": 9200, "6.3": 9600}[ver[:3]]
    if build is None:
        line = os_name
    elif build >= 22000 and build != 26100:
        line = "Windows 11"
    elif 10240 <= build < 22000 and build not in (14393, 17763):
        line = "Windows 10"
    elif build in (14393, 17763, 26100):
        line = "Windows build %d (client/server not distinguishable)" % build
    elif build == 20348:
        line = "Windows Server 2022"
    else:
        line = "Windows (build %d)" % build
    return dict(host=b.get("displayName"), fam=fam, line=line, product=os_name + (" " + ver if ver else ""), build=build, rev=rev,
                server=(True if build == 20348 else None) if fam == "windows" else None,
                last=parse_ts(b.get("approximateLastSignInDateTime")), raw=os_name)


def edition(product):
    p = (product or "").lower()
    return "ent" if re.search(r"enterprise|education|ltsc|iot", p) else "pro"


def support(r, as_of):
    """Return (status, label, end_date|None, note)."""
    fam = r["fam"]
    if fam == "mac":
        m = re.search(r"(?:macos|os x|mac os x)\s*(\d+)", r["raw"], re.I) or re.search(r"^(\d+)\.", r["raw"])
        if m:
            return ("eol" if int(m.group(1)) < 14 else "supported"), "macOS %s" % m.group(1), None, "judged by major version against macOS 14 floor"
        return "not_assessed", r["line"], None, "macOS version not parseable"
    if fam != "windows":
        return "not_assessed", r["line"], None, "inventory only"
    b = r["build"]
    if b is None:
        return "unknown", r["line"], None, "no build number in the record"
    if "ltsc" in (r["product"] or "").lower():
        return "verify", "%s (LTSC)" % r["line"], None, "LTSC/IoT lifecycles differ; confirm the channel"
    srv = r["server"]
    if srv is None and b in AMBIGUOUS:
        return "verify", "%s / %s" % (AMBIGUOUS[b], SERVER[b][0]), None, "build shared by a client and a server SKU; no SKU in this source"
    ent = SERVER if srv else CLIENT
    if srv is None:
        ent = CLIENT if b in CLIENT else SERVER
    if b not in ent:
        if not srv and 10240 <= b < 19044:
            return "eol", "Windows 10 (build %d)" % b, None, "older than 21H2; ended before 2023"
        if b > max(ent):
            r["beyond"] = True
            return "supported", "%s (build %d, newer than the table)" % (r["line"], b), None, "build newer than the curated table; treated as a pre-release or new release, not as EOL"
        return "unknown", "%s build %d" % (r["line"], b), None, "build not in the curated lifecycle table"
    label, pro_end, ent_end = ent[b]
    end = ent_end if edition(r["product"]) == "ent" else pro_end
    if end is None:
        return "eol", label, None, "ended long ago; date not tracked"
    d = datetime.date.fromisoformat(end)
    if d < as_of:
        st = "eol"
    elif (d - as_of).days <= SOON_DAYS:
        st = "ending_soon"
    else:
        st = "supported"
    return st, label, end, "%s edition date" % ("Enterprise/Education" if edition(r["product"]) == "ent" else "Home/Pro")


def esc(s):
    return html.escape(str(s))


def bars(rows, color, w=520):
    if not rows:
        return '<p class="small">No data.</p>'
    mx = max(v for _, v in rows) or 1
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (w, 26 * len(rows))]
    for i, (k, v) in enumerate(rows):
        y, bw = i * 26, max(2, int((w - 300) * v / mx))
        out.append('<text x="0" y="%d" font-size="12" fill="#334155">%s</text>' % (y + 17, esc(k[:26])))
        out.append('<rect x="190" y="%d" width="%d" height="16" rx="3" fill="%s"/>' % (y + 4, bw, color))
        out.append('<text x="%d" y="%d" font-size="12" fill="#334155">%s</text>' % (196 + bw, y + 17, "{:,}".format(v)))
    out.append("</svg>")
    return "".join(out)


def pill(st):
    t, c = STATUS[st]
    return '<span class="pill" style="--c:%s">%s</span>' % (c, t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=["falcon", "sentinelone", "office365"])
    ap.add_argument("--dump", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--as-of", default=datetime.date.today().isoformat())
    ap.add_argument("--stale-days", type=int, default=None, help="default 30 for EDR sources, 90 for office365")
    a = ap.parse_args()
    as_of = datetime.date.fromisoformat(a.as_of)
    resource, norm, label = {"falcon": ("falconAgent", norm_falcon, "CrowdStrike Falcon sensor inventory (falconAgent)"),
                             "sentinelone": ("sentinelOneAgent", norm_s1, "SentinelOne agent inventory (sentinelOneAgent)"),
                             "office365": ("office365Device", norm_o365, "Entra device inventory (office365Device)")}[a.source]
    stale_days = a.stale_days or (90 if a.source == "office365" else 30)
    try:
        recs = [norm(b) for b in load_dump(a.dump, resource)]
    except (OSError, ValueError, KeyError) as e:
        sys.exit("cannot read the %s dump %s: %s" % (resource, a.dump, e))
    if not recs:
        sys.exit("the %s dump is empty; nothing to report" % resource)

    now = datetime.datetime.combine(as_of, datetime.time())
    for r in recs:
        r["status"], r["slabel"], r["end"], r["note"] = support(r, as_of)
        r["stale"] = bool(r["last"] and (now - r["last"]).days > stale_days) if r["last"] else None

    total = len(recs)
    win = [r for r in recs if r["fam"] == "windows"]
    cnt = collections.Counter(r["status"] for r in recs)
    stale_n = sum(1 for r in recs if r["stale"])
    unseen_n = sum(1 for r in recs if r["last"] is None)

    # build currency, per OS line, Windows records with a build only
    cur = collections.defaultdict(list)
    for r in win:
        if r["build"] is not None:
            cur[r["line"]].append(r)
    cur_rows, behind_hosts = [], []
    for line, rs in cur.items():
        ga = [r for r in rs if not r.get("beyond")] or rs
        newest = max((r["build"], r["rev"] or 0) for r in ga)
        old_b = [r for r in rs if r["build"] < newest[0]]
        old_b = [r for r in old_b if not r.get("beyond")]
        old_p = [r for r in rs if r["build"] == newest[0] and r["rev"] is not None and r["rev"] < newest[1]]
        for r in old_b:
            r["currency"] = "older build"
        for r in old_p:
            r["currency"] = "older patch"
        behind_hosts += old_b + old_p
        cur_rows.append((line, len(rs), "%d" % newest[0] + (".%d" % newest[1] if rs[0]["rev"] is not None else ""), len(rs) - len(old_b) - len(old_p), len(old_b), len(old_p) if any(x["rev"] is not None for x in rs) else None))
    cur_rows.sort(key=lambda x: -x[1])
    for r in recs:
        r.setdefault("currency", "current" if r["fam"] == "windows" and r["build"] is not None else "")
    behind_build = sum(1 for r in recs if r["currency"] == "older build")

    # support table grouped by label + status + end
    grp = collections.Counter((r["status"], r["slabel"], r["end"] or "") for r in recs)
    order = {"eol": 0, "ending_soon": 1, "verify": 2, "unknown": 3, "supported": 4, "not_assessed": 5}
    sup_rows = sorted(grp.items(), key=lambda kv: (order[kv[0][0]], -kv[1]))

    by_line = collections.Counter(r["line"] for r in recs)
    top = by_line.most_common(10)
    if len(by_line) > 10:
        top.append(("Other (%d lines)" % (len(by_line) - 10), sum(by_line.values()) - sum(v for _, v in top)))
    fam_cnt = collections.Counter(r["fam"] for r in recs)

    act = [r for r in recs if r["status"] in ("eol", "ending_soon")]
    act.sort(key=lambda r: (order[r["status"]], r["end"] or "0000", r["slabel"], r["host"] or ""))
    worst_rows = "".join("<tr><td class=\"ctl\" style=\"--c:%s\">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        STATUS[r["status"]][1], esc(r["host"] or "(no name)"), esc(r["slabel"]), pill(r["status"]), esc(r["end"] or "ended"),
        esc(r["last"].date().isoformat() if r["last"] else "not recorded")) for r in act[:25])
    more = ("<p class=\"small\">%d more in the CSV.</p>" % (len(act) - 25)) if len(act) > 25 else ""

    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["host", "platform", "os_product", "os_line", "build", "revision", "support_status", "support_end", "currency", "last_seen", "stale", "note"])
        for r in sorted(recs, key=lambda r: (order[r["status"]], r["slabel"], r["host"] or "")):
            w.writerow([r["host"], r["fam"], r["product"], r["line"], r["build"] if r["build"] is not None else "", r["rev"] if r["rev"] is not None else "",
                        r["status"], r["end"] or "", r["currency"], r["last"].date().isoformat() if r["last"] else "",
                        "" if r["stale"] is None else ("yes" if r["stale"] else "no"), r["note"]])

    eol_n, soon_n = cnt.get("eol", 0), cnt.get("ending_soon", 0)
    worst = [(k[1], v) for k, v in sup_rows if k[0] == "eol"][:3]
    worst_txt = ", ".join("%s (%d)" % (k, v) for k, v in worst) or "none"
    title = "%s Endpoint OS Currency Report" % a.tenant_name
    today = as_of.strftime("%d %B %Y")
    kp = "".join('<div class="kpi" style="--c:%s"><b>%s</b><span>%s</span></div>' % (c, "{:,}".format(v), l)
                 for v, l, c in [(total, "Endpoints in inventory", "#14213d"), (eol_n, "On an unsupported OS", "#B91C1C"), (soon_n, "Support ends within %d days" % SOON_DAYS, "#B45309"),
                                 (behind_build, "On an older build than the fleet newest", "#B45309"), (stale_n, "Not seen in %d+ days" % stale_days, "#64748B")])
    sup_html = "".join("<tr><td class=\"ctl\" style=\"--c:%s\">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (STATUS[k[0]][1], esc(k[1]), pill(k[0]), esc(k[2] or "-"), "{:,}".format(v)) for k, v in sup_rows)
    cur_html = "".join("<tr><td class=\"ctl\" style=\"--c:#1D4ED8\">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(l), "{:,}".format(t), esc(nw), "{:,}".format(c), "{:,}".format(ob), "n/a" if op is None else "{:,}".format(op)) for l, t, nw, c, ob, op in cur_rows)
    excluded = total - len(win)
    bar_col = {"eol": "#B91C1C", "ending_soon": "#B45309", "verify": "#1D4ED8", "unknown": "#94A3B8", "supported": "#15803D", "not_assessed": "#64748B"}
    segs = [(st, cnt[st]) for st in order if cnt.get(st)]
    status_bar = ('<div class="bar">' + "".join('<i style="width:%.3f%%;background:%s" title="%s: %d"></i>' % (100.0 * n / total, bar_col[st], esc(STATUS[st][0]), n) for st, n in segs) + "</div>"
                  '<div class="legend">' + "".join('<span><em style="background:%s"></em>%s %s</span>' % (bar_col[st], esc(STATUS[st][0]), "{:,}".format(n)) for st, n in segs) + "</div>")
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
{css}</style></head><body>
<div class="hero"><div class="wrap"><div class="eyebrow">Endpoint OS currency</div><h1>{title}</h1>
<div class="chips"><span class="chip">Tenant: {tname} (grid account <code>{tenant}</code>)</span><span class="chip">Source: {label}</span><span class="chip">Snapshot as of {today}</span></div></div></div>
<div class="wrap">
<div class="kpis five">{kp}</div>
<div class="read"><b class="t">Read this first</b>
<p><b>What the evidence shows.</b> {total} endpoints in the inventory; {nwin} run Windows. {eol_n} are on an OS that no longer receives security updates, led by {worst_txt}.</p>
<p><b>Why it matters.</b> A host past end of support gets no security fixes, so the remedy is an OS upgrade or replacement, not a patch. Hosts on an older build within a supported OS line need patching.</p>
<p><b>Result.</b> {eol_n} unsupported, {soon_n} with support ending within {soon} days, {behind_build} on an older build than the newest seen in this fleet, {stale_n} not seen in {stale_days}+ days (they may simply have missed updates).</p>
<p><b>Evidence strength.</b> Confirmed: the OS and build each sensor reported. Inferred: support dates, from a curated table dated {tbl}; "newest build" is the fleet maximum, not the vendor's latest. Unknown: ESU or extended-support contracts, Windows edition where the source carries none.</p></div>
<h2><span class="n">1</span>Operating systems in use</h2>
<div class="panel"><div class="fig"><div class="cap">Endpoints by OS line</div>{os_chart}</div></div>
<h2><span class="n">2</span>Support status</h2>
{status_bar}
<div class="tw"><table><colgroup><col style="width:36%"><col style="width:24%"><col style="width:22%"><col style="width:18%"></colgroup><thead><tr><th>OS release</th><th>Status</th><th>Support ended / ends</th><th>Endpoints</th></tr></thead><tbody>{sup_html}</tbody></table></div>
<div class="call">Dates are the curated table as of {tbl} and use the Enterprise/Education date for Enterprise, Education and LTSC editions and the Home/Pro date otherwise. Extended Security Updates, where bought, are not visible in this data.</div>
<h2><span class="n">3</span>Hosts to act on first</h2>
<div class="tw"><table><colgroup><col style="width:26%"><col style="width:26%"><col style="width:18%"><col style="width:15%"><col style="width:15%"></colgroup><thead><tr><th>Host</th><th>OS release</th><th>Status</th><th>Support end</th><th>Last seen</th></tr></thead><tbody>{worst_rows}</tbody></table></div>{more}
<h2><span class="n">4</span>Build currency</h2>
<p class="small">Within each Windows line, compared with the newest build seen in this fleet. "Older patch" needs a patch revision, which only some sources carry.</p>
<div class="tw"><table><colgroup><col style="width:30%"><col style="width:12%"><col style="width:18%"><col style="width:12%"><col style="width:14%"><col style="width:14%"></colgroup><thead><tr><th>OS line</th><th>Hosts</th><th>Newest build seen</th><th>On newest or newer</th><th>Older build</th><th>Older patch</th></tr></thead><tbody>{cur_html}</tbody></table></div>
<div class="foot"><h2>Limits</h2><ul>
<li>Only endpoints in the {label} appear. Machines without the sensor or enrolment are not covered; absence is not coverage.</li>
<li>{excluded} endpoint(s) are not Windows (macOS, Linux, mobile) and get no build-currency view; they are listed in the inventory only.</li>
<li>{unseen_n} record(s) carry no last-seen time, so they cannot be marked stale.</li>
<li>Builds are compared only within one OS line, never across lines. "Older patch" counts any revision below the newest seen, so a host one cumulative update behind is included.</li></ul>
<h2>Methodology</h2><p class="small">One resource dump of {resource} was downloaded read-only through the {site} MCP connector and evaluated locally on {today}. Build numbers come from the sensor's own fields. Support dates come from the curated Windows lifecycle table in this skill (as of {tbl}); verify against Microsoft's lifecycle pages before quoting a date. A full per-host list is in the accompanying CSV.</p>
</div></div></body></html>""".format(
        css=CSS, status_bar=status_bar, title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), label=esc(label), today=today, total="{:,}".format(total), nwin="{:,}".format(len(win)),
        eol_n="{:,}".format(eol_n), soon_n="{:,}".format(soon_n), soon=SOON_DAYS, behind_build="{:,}".format(behind_build), stale_n="{:,}".format(stale_n),
        stale_days=stale_days, worst_txt=esc(worst_txt), tbl=TABLE_AS_OF, kp=kp, os_chart=bars(top, "#1D4ED8"), sup_html=sup_html, worst_rows=worst_rows, more=more,
        cur_html=cur_html or '<tr><td colspan="6">No Windows endpoints with a build number.</td></tr>', excluded=excluded, unseen_n=unseen_n, resource=resource, site=esc(a.site))
    with open(a.out, "w") as f:
        f.write(doc)
    print("wrote", a.out, a.csv)


if __name__ == "__main__":
    main()
