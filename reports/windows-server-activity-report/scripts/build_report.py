#!/usr/bin/env python3
"""Build the Windows Server Activity report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv report.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site Develop] [--top 10] [--no-actors]
                  [--interactive report_interactive.html]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}); several files and
several days per file are merged. This script never queries a tenant. Rules: the per-day trend rows are summed (hosts
is the PEAK day); win_facets (one table per facet) is summed by value, "(none)" dropped; win_failed_source and
win_ingest are summed by key, with distinct counts (user names, hosts) reported as the PEAK single day; a missing
value is 0; a day that is not archived is a GAP, never zero. --no-actors drops every list that names a user or an IP.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, os, sys
import os as _os, sys as _sys, glob as _glob
def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
    here = _os.path.dirname(_os.path.abspath(__file__)); home = _os.path.expanduser("~")
    cands = [_os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = _os.path.dirname(up); cands.append(_os.path.join(up, "fluency-report", "scripts"))
    cands += [_os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += _glob.glob(_os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and _os.path.exists(_os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")
_sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

E = html.escape
NAVY, RED, AMB, GRN, GRY, BLU = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8"
FACET_CAP = 100
METRICS = ["events", "bytes", "hosts", "logonsOk", "logonsFailed", "rdpLogons", "networkLogons", "explicitCreds",
           "kerberosFailures", "ntlmFailures", "lockouts", "privLogons", "accountCreated", "accountEnabled",
           "accountDisabled", "accountDeleted", "passwordChanges", "groupAdds", "servicesInstalled", "tasksCreated",
           "auditPolicyChanges", "logsCleared", "processCreations", "powershellScripts"]
PEAK_METRICS = ("hosts",)
LABEL = {"events": "Events", "bytes": "Bytes ingested", "hosts": "Hosts (peak day)", "logonsOk": "User logons (4624)",
         "logonsFailed": "Failed logons (4625)", "rdpLogons": "Remote-desktop logons", "networkLogons": "Network logons",
         "explicitCreds": "Explicit-credential logons (4648)", "kerberosFailures": "Kerberos pre-auth failures (4771)",
         "ntlmFailures": "NTLM failures (4776)", "lockouts": "Account lockouts (4740)", "privLogons": "Privileged logons (4672)",
         "accountCreated": "Accounts created", "accountEnabled": "Accounts enabled", "accountDisabled": "Accounts disabled",
         "accountDeleted": "Accounts deleted", "passwordChanges": "Password changes / resets", "groupAdds": "Group member adds",
         "servicesInstalled": "Services installed", "tasksCreated": "Scheduled tasks created", "auditPolicyChanges": "Audit-policy changes (4719)",
         "logsCleared": "Audit logs cleared", "processCreations": "Process creations (4688)", "powershellScripts": "PowerShell script blocks (4104)"}
SHORT = {"events": "Events", "hosts": "Hosts", "logonsOk": "Logons", "logonsFailed": "Failed", "rdpLogons": "RDP", "privLogons": "Priv.",
         "lockouts": "Lockouts", "groupAdds": "Grp add", "servicesInstalled": "Svc", "tasksCreated": "Tasks", "auditPolicyChanges": "Policy",
         "logsCleared": "Cleared"}
TABLE_COLS = ["events", "hosts", "logonsOk", "logonsFailed", "privLogons", "groupAdds", "servicesInstalled", "tasksCreated", "auditPolicyChanges", "logsCleared"]
ACTOR_FACETS = ("failedUser", "failedIp", "logonUser", "privAccount", "acctActor", "acctTarget", "groupActor", "tamperActor")
LOGON_TYPE = {"2": "Interactive", "3": "Network", "4": "Batch", "5": "Service", "7": "Unlock", "8": "Network cleartext",
              "9": "New credentials", "10": "Remote desktop", "11": "Cached interactive"}
FAIL_REASON = {"0xc0000064": "Unknown user name", "0xc000006a": "Wrong password", "0xc000006d": "Bad user name or password",
               "0xc000006e": "Account restriction", "0xc000006f": "Outside logon hours", "0xc0000070": "Workstation restriction",
               "0xc0000071": "Password expired", "0xc0000072": "Account disabled", "0xc0000133": "Clock skew",
               "0xc000015b": "Logon type not granted", "0xc0000193": "Account expired", "0xc0000234": "Account locked out",
               "0xc0000224": "Must change password", "0x0": "No code"}
ACCT_EVENT = {"4720": "Account created", "4722": "Account enabled", "4725": "Account disabled", "4726": "Account deleted",
              "4723": "Password change attempt", "4724": "Password reset", "4738": "Account changed", "4767": "Account unlocked"}
TAMPER_EVENT = {"1102": "Security log cleared", "104": "System log cleared", "4719": "Audit policy changed"}
SEC_FAMILY = [  # indicative, related not equivalent
    ("Logon and access", "AC-2, AC-7, AC-17, IA-2", "user logons, failed logons, sources, logon types, remote desktop, lockouts"),
    ("Privileged accounts", "AC-6", "special-privilege logons, group member adds"),
    ("Account management", "AC-2, IA-5", "accounts created, enabled, disabled, deleted, password changes"),
    ("Configuration change and persistence", "CM-3, CM-5, CM-7", "services installed, scheduled tasks created"),
    ("Audit records and protection", "AU-2, AU-9, AU-12", "events ingested per host and event ID, audit-log clears, audit-policy changes"),
]
LIMITS = [
    "The lists name user accounts and source IP addresses, so the report is personal data. Share it only with the customer who owns the data, or build it with --no-actors.",
    "Each list keeps the top 100 values of an archived day, so a range total for a value outside a day's top 100 is a lower bound. Distinct counts (hosts, user names) are the peak single day, never added across days.",
    "Source is the WindowsAudit table (parsed NXLog Windows event log). Hosts are short names: dc1 and dc1.corp.local are one host. User logons are 4624 events of user accounts; machine accounts (ending in $) and '-' are left out.",
    "Event names come from the AD_EventID lookup and, when the lookup does not know an ID, from the description on the event. An ID with neither shows its number only.",
    "Failed logons are 4625 events; the reason is the SubStatus code (else Status). An empty code is shown as (not recorded). A pattern of 10 or more user names from one address in a day is a spray, 50 or more failures is brute force, the rest a probe: a lead, not a verdict.",
    "An archived day is a snapshot taken a few hours after the day ended; events that arrive later are not added.",
    "A day missing from the archive is a gap, not zero activity. A scan the tenant could not run is 'not available', not zero.",
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
.kpis.two{margin-top:14px;grid-template-columns:repeat(4,1fr)}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:30px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}.kpi small{display:block;color:var(--mut);font-size:11px;margin-top:2px}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.gap{border-left:4px solid #B45309;background:#fff7ed;border-radius:0 10px 10px 0;padding:12px 18px;margin-top:12px;color:#7c2d12}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
td.d{white-space:nowrap}
table.dt{font-size:11px}table.dt th,table.dt td{padding:6px 6px}table.dt th{letter-spacing:.02em}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.mut{color:var(--mut)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-size:12px;margin-bottom:4px}
.card svg{width:100%;height:auto;display:block}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
td.bar{width:24%}.bar i{display:block;height:8px;border-radius:4px;background:var(--c);min-width:2px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media screen and (max-width:760px){.g2{grid-template-columns:1fr}.kpis,.kpis.two,.cards{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

def n(v):
    return "{:,}".format(int(v))


def gb(b):
    return "%.2f GB" % (b / 1e9) if b >= 1e9 else "%.1f MB" % (b / 1e6)


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def rows_of(t):
    return (t or {}).get("rows") or []


def load(paths):
    """({day: day-dict}, {day: state}). day-dict: entry, trend[rows], facets{facet:{value:count}}, capped{facet},
    fsrc[rows], ingest[rows], status{scan: ok|not available}, have (which tables the archived script produced)."""
    done, other, files = {}, {}, []
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
            dd = {"entry": en, "trend": [], "facets": {}, "capped": set(), "fsrc": [], "ingest": [], "status": {}, "have": set()}
            for o in res.get("objects", []):
                nm = o.get("name", "")
                dd["have"].add(nm)
                if nm == "win_trend":
                    dd["trend"] = rows_of(o.get("table"))
                elif nm == "win_failed_source":
                    dd["fsrc"] = rows_of(o.get("table"))
                elif nm == "win_ingest":
                    dd["ingest"] = rows_of(o.get("table"))
                elif nm == "sources":
                    for r in rows_of(o.get("table")):
                        s = r.get("source")
                        if r.get("status") == "ok":
                            dd["status"].setdefault(s, ("ok", ""))
                        else:
                            dd["status"][s] = ("not available", r.get("detail") or "")
                elif nm == "win_facets":
                    om = (o.get("value") or {}).get("orderedMap") or {}
                    for k, v in zip(om.get("keys", []), om.get("values", [])):
                        if k == "PrimaryResult":
                            continue
                        sx = (v or {}).get("sx") or {}
                        rows = sx.get("rows") or []
                        dd["facets"][k] = {str(r.get(k)): num(r.get("count_")) for r in rows}
                        if (sx.get("rowCount") or len(rows)) >= FACET_CAP:
                            dd["capped"].add(k)
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = dd
    return done, other


def merge(done):
    daily, fac, capped = {}, collections.defaultdict(collections.Counter), collections.defaultdict(int)
    fsrc, ing = {}, {}
    for day, d in done.items():
        tot = collections.Counter()
        for r in d["trend"]:
            for m in METRICS:
                if m in PEAK_METRICS:
                    tot[m] = max(tot[m], num(r.get(m)))
                else:
                    tot[m] += num(r.get(m))
        if d["trend"]:
            daily[day] = tot
        for f, vals in d["facets"].items():
            for v, c in vals.items():
                if v != "(none)":
                    fac[f][v] += c
        for f in d["capped"]:
            capped[f] += 1
        for r in d["fsrc"]:
            k = str(r.get("remip") or "(local or not recorded)")
            o = fsrc.setdefault(k, {"failures": 0, "usernames": 0, "hosts": 0, "first": None, "last": None})
            o["failures"] += num(r.get("failures"))
            o["usernames"] = max(o["usernames"], num(r.get("usernames")))
            o["hosts"] = max(o["hosts"], num(r.get("hosts")))
            if r.get("firstSeen") and (o["first"] is None or r["firstSeen"] < o["first"]):
                o["first"] = r["firstSeen"]
            if r.get("lastSeen") and (o["last"] is None or r["lastSeen"] > o["last"]):
                o["last"] = r["lastSeen"]
        for r in d["ingest"]:
            k = (str(r.get("host") or ""), str(r.get("eventId") or ""))
            o = ing.setdefault(k, {"events": 0, "bytes": 0, "name": ""})
            o["events"] += num(r.get("events"))
            o["bytes"] += num(r.get("bytes"))
            nm = r.get("eventName") or r.get("description") or ""
            if nm and not o["name"]:
                o["name"] = str(nm)
    return daily, fac, capped, fsrc, ing


def bars(series, days, color, title):
    """One column per calendar day (shared chart helper). A day without data is a hatched gap, never a zero bar."""
    days = [str(d) for d in days]
    return fb.column_chart([d[5:] for d in days], [(title, [series[d] if d in series else None for d in days])],
                           colors=[fb.legacy_color(color)], height=140, show_values=False, y_label=title)


def table(title, sub, rows, headers, color, top, bar=1, note=""):
    """rows: list of tuples (label, v1, v2, ...) with numbers right-aligned; bar on column `bar` (1 = first number)."""
    if not rows:
        return "<div class='card' style='--c:%s;margin-top:14px'><b>%s</b><span class='mut'>None in this period.</span></div>" % (color, E(title))
    rows = sorted(rows, key=lambda r: -r[bar] if isinstance(r[bar], (int, float)) else 0)
    shown = rows[:top]
    mx = max([r[bar] for r in shown] + [1])
    hdr = "".join("<th%s>%s</th>" % (" class='r'" if i else "", E(h)) for i, h in enumerate(headers)) + "<th></th>"
    body = []
    for r in shown:
        cells = "".join("<td class='%s'>%s</td>" % ("r" if isinstance(v, (int, float)) else "d", E(n(v) if isinstance(v, (int, float)) else str(v))) for v in r[1:])
        body.append("<tr><td class='mono'>%s</td>%s<td class='bar'><i style='--c:%s;width:%.0f%%'></i></td></tr>" % (E(str(r[0])), cells, color, 100.0 * r[bar] / mx))
    if len(rows) > top:
        body.append("<tr><td class='mut'>(%d more)</td>%s<td></td></tr>" % (len(rows) - top, "<td></td>" * (len(headers) - 1)))
    return ("<div style='break-inside:avoid'><h3 style='margin:18px 0 2px;font-size:14px;color:%s'>%s</h3><p class='sub'>%s%s</p>"
            "<div class='tw'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></div>" % (NAVY, E(title), E(sub), E(note), hdr, "".join(body)))


def counts(title, sub, counter, color, top, total=None, label=None, headers=("Value", "Events"), note=""):
    rows = [((label(k) if label else k), c) for k, c in counter.items() if c]
    sub2 = sub + ((" Share is of %s." % n(total)) if total else "")
    return table(title, sub2, rows, list(headers), color, top, 1, note)


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def short(ts):
    return (ts or "")[:16].replace("T", " ")


def build_interactive(path, ctx):
    """One self-contained interactive HTML (tabs, search, sort, filter, CSV export, dark mode, hover charts).
    Reuses the merged structures main() already computed; honours --no-actors by never putting user names or IPs in the file."""
    T, fac, fsrc, actors, top = ctx["T"], ctx["fac"], ctx["fsrc"], ctx["actors"], ctx["top"]
    expected, daily, other = ctx["expected"], ctx["daily"], ctx["other"]
    tables = []

    def add(tid, tab, title, sub, cols, rows, color, half=False, sort=None):
        tables.append({"id": tid, "tab": tab, "title": title, "sub": sub, "color": color, "half": half, "sort": sort,
                       "cols": [{"l": c, "n": isinstance(rows[0][i], (int, float)) if rows else (i > 0)} for i, c in enumerate(cols)],
                       "rows": [list(r) for r in rows]})

    def cnt(tid, tab, title, sub, facet, color, hdr, label=None, total=None, half=True):
        rows = [[(label(k) if label else k), c] for k, c in fac.get(facet, collections.Counter()).most_common() if c]
        if total:
            rows = [r + [round(100.0 * r[1] / total, 1)] for r in rows]
        add(tid, tab, title, sub, list(hdr) + (["% of total"] if total else []), rows, color, half)

    add("events_by_host", "events", "Events by host", "Short host names. %s" % ctx["lostnote"].strip(),
        ["Host", "Events", "MB"], [[h, c, round(ctx["host_bytes"][h] / 1e6, 2)] for h, c in ctx["host_tot"].most_common()], NAVY)
    add("events_by_event_id", "events", "Events by event ID", "Names come from the AD_EventID lookup, else the description on the event. %d event ID(s) have no name." % ctx["unnamed"],
        ["Event ID", "Events", "MB"], [[ctx["ename"](e), c, round(ctx["id_bytes"][e] / 1e6, 2)] for e, c in ctx["id_tot"].most_common()], NAVY)
    cnt("logon_types", "logons", "Successful logons by type", "Machine accounts left out.", "logonType", GRN, ("Logon type", "Logons"),
        lambda k: "%s (%s)" % (LOGON_TYPE.get(k, "type"), k), T["logonsOk"])
    cnt("failed_reasons", "logons", "Failed logons by reason", "SubStatus code, else Status.", "failedReason", RED, ("Reason", "Failures"),
        lambda k: "%s (%s)" % (FAIL_REASON.get(k, "code"), k) if k != "(not recorded)" else k, T["logonsFailed"])
    if actors:
        cnt("top_logon_accounts", "logons", "Top accounts by logons", "Target account of successful user logons.", "logonUser", GRN, ("Account", "Logons"), None, T["logonsOk"])
        cnt("top_failed_accounts", "logons", "Top accounts by failures", "Target account of failed logons.", "failedUser", RED, ("Account", "Failures"), None, T["logonsFailed"])
        add("failed_sources", "logons", "Failed logons by source address", "Many user names from one address is a spray, many failures with few names is brute force, the rest is probing. Lower bound: top 100 a day.",
            ["Source", "Failures", "User names (peak day)", "Hosts (peak day)", "Pattern", "First seen", "Last seen"],
            [[k, r["failures"], r["usernames"], r["hosts"], "Credential spray" if r["usernames"] >= 10 else ("Brute force" if r["failures"] >= 50 else "Probe"), short(r["first"]), short(r["last"])] for k, r in fsrc.items()], RED)
    cnt("account_events", "priv", "Account events", "By event.", "acctEvent", BLU, ("Event", "Count"), lambda k: "%s %s" % (k, ACCT_EVENT.get(k, "")))
    cnt("group_additions", "priv", "Group additions", "Group that gained a member.", "groupName", BLU, ("Group", "Adds"))
    if actors:
        cnt("priv_logon_accounts", "priv", "Privileged logons by account", "Special-privilege logons (4672), people only.", "privAccount", AMB, ("Account", "Logons"), None, T["privLogons"])
        cnt("account_actors", "priv", "Account changes by actor", "Who made the change.", "acctActor", BLU, ("Actor", "Events"))
        cnt("account_targets", "priv", "Account changes by target", "The account that was changed.", "acctTarget", BLU, ("Target", "Events"))
        cnt("group_actors", "priv", "Group additions by actor", "Who added the member.", "groupActor", BLU, ("Actor", "Adds"))
    cnt("persist_items", "tamper", "Services and tasks installed", "Name of the service or scheduled task.", "persistItem", AMB, ("Item", "Count"))
    cnt("tamper_events", "tamper", "Log clears and policy changes", "By event.", "tamperEvent", RED, ("Event", "Count"), lambda k: "%s %s" % (k, TAMPER_EVENT.get(k, "")))
    cnt("tamper_hosts", "tamper", "Tampering by host", "Host where the log was cleared or the policy changed.", "tamperHost", RED, ("Host", "Count"))
    if actors:
        cnt("tamper_actors", "tamper", "Tampering by actor", "Account that did it.", "tamperActor", RED, ("Actor", "Count"))
    srows = []
    for s in sorted(ctx["stat"]):
        c = ctx["stat"][s]
        okd, nad = c.get("ok", 0), c.get("not available", 0)
        srows.append([s, "available" if okd and not nad else ("not available" if nad and not okd else "partial"), okd, nad, (ctx["detail"].get(s) or "")[:120]])
    if srows:
        add("scan_status", "coverage", "Scan status", "Whether each scan ran on the archived days.", ["Scan", "Status", "Days ok", "Days not available", "Error"], srows, GRN, sort=None)
    add("crosswalk", "coverage", "What these counts relate to", "Indicative crosswalk to NIST SP 800-53 Rev. 5. Related, not equivalent.",
        ["Area", "800-53 controls", "Counts that relate"], [list(x) for x in SEC_FAMILY], NAVY)
    add("limits", "coverage", "Limits", "Source: archive of the scheduled report WindowsSrv_Activity_Report. No live search was run to build this report.",
        ["Limit"], [[l] for l in LIMITS], GRY)
    dcols = ["Day"] + [SHORT[m] for m in TABLE_COLS]
    drows = [[d] + [daily[d][m] for m in TABLE_COLS] for d in expected if d in daily]
    daily_table = {"id": "daily_trend", "tab": "overview", "title": "Daily counts", "sub": "One row per archived UTC day. Hosts is the peak single day. Days not archived are gaps and are not listed.",
                   "color": NAVY, "half": False, "sort": 0,
                   "cols": [{"l": c, "n": i > 0} for i, c in enumerate(dcols)], "rows": drows}
    data = {"meta": {"tenant": ctx["tenant"], "site": ctx["site"], "period": ctx["period"], "days_archived": len(daily), "days_expected": len(expected),
                     "missing": ctx["missing"], "actors": actors, "nodata": ctx["nodata"], "hashes": ctx["hashes"],
                     "non_completed": ", ".join("%s=%s" % kv for kv in sorted(other.items())), "multi_script": ctx["multi_script"]},
            "totals": {m: T[m] for m in METRICS}, "metrics": list(METRICS), "labels": {m: LABEL[m] for m in METRICS},
            "days": [{"date": d, "gap": d not in daily, "v": ({m: daily[d][m] for m in METRICS} if d in daily else {})} for d in expected],
            "highlights": ctx["hl"], "tables": tables, "daily_table": daily_table, "capped": ["%s (%d d)" % kv for kv in sorted(ctx["capped"].items())]}
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "interactive_template.html"), encoding="utf-8").read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl.replace("{{title}}", E("Windows Server Activity Report - %s" % (ctx["tenant"] or "Tenant"))).replace("{{data}}", blob))


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
    ap.add_argument("--interactive", metavar="PATH", help="also write a single self-contained interactive HTML file (tabs, search, sort, filter, CSV export, dark mode)")
    ap.add_argument("--no-actors", action="store_true", help="omit lists that name user accounts and IP addresses")
    a = ap.parse_args()

    done, other = load(a.archive)
    if not done:
        sys.exit("no completed archived day in the input. Backfill or wait for the schedule; nothing is estimated.")
    dfrom, dto = a.dfrom or min(done), a.dto or max(done)
    expected = days_between(dfrom, dto)
    done = {k: v for k, v in done.items() if dfrom <= k <= dto}
    if not done:
        sys.exit("no archived day falls inside %s to %s." % (dfrom, dto))
    daily, fac, capped, fsrc, ing = merge(done)
    missing = [d for d in expected if d not in done]
    hashes = collections.Counter(v["entry"].get("env", {}).get("scriptHash", "?") for v in done.values())
    stat, detail = collections.defaultdict(collections.Counter), {}
    for d in done.values():
        for s, (st, dt_) in d["status"].items():
            stat[s][st] += 1
            if st != "ok" and dt_:
                detail[s] = dt_
    T = collections.Counter()
    for c in daily.values():
        for m in METRICS:
            T[m] = max(T[m], c[m]) if m in PEAK_METRICS else T[m] + c[m]
    scans = [s for s in stat if s != "event ID names (AD_EventID lookup)"]
    nodata = bool(scans) and all(stat[s].get("ok", 0) == 0 for s in scans)
    period = "%s to %s" % (dfrom, dto)
    top, actors = a.top, not a.no_actors

    host_tot, id_tot, id_name, pair_events = collections.Counter(), collections.Counter(), {}, 0
    host_bytes, id_bytes = collections.Counter(), collections.Counter()
    for (h, e), o in ing.items():
        host_tot[h] += o["events"]; host_bytes[h] += o["bytes"]
        id_tot[e] += o["events"]; id_bytes[e] += o["bytes"]
        pair_events += o["events"]
        if o["name"] and e not in id_name:
            id_name[e] = o["name"]
    unnamed = sum(1 for e in id_tot if e not in id_name)
    ingest_lost = max(T["events"] - pair_events, 0)

    def ename(e):
        return "%s  %s" % (e, id_name[e]) if e in id_name else e

    summary = {"period": period, "days_expected": len(expected), "days_archived": len(done), "missing_days": missing,
               "non_completed": other, "script_hashes": dict(hashes), "no_windows_data": nodata, "totals": {m: T[m] for m in METRICS},
               "daily": {d: {m: daily[d][m] for m in METRICS} for d in sorted(daily)},
               "sources": {s: dict(c) for s, c in stat.items()}, "actors_included": actors,
               "events_not_in_host_eventid_pairs": ingest_lost, "event_ids_without_name": unnamed,
               "hosts": [{"host": h, "events": c, "bytes": host_bytes[h]} for h, c in host_tot.most_common(100)],
               "event_ids": [{"eventId": e, "name": id_name.get(e, ""), "events": c, "bytes": id_bytes[e]} for e, c in id_tot.most_common(100)],
               "facets_capped_days": dict(capped)}
    for f, c in fac.items():
        if f in ACTOR_FACETS and not actors:
            continue
        summary.setdefault("facets", {})[f] = dict(c.most_common(100))
    if actors:
        summary["failed_sources"] = [dict(remip=k, **o) for k, o in sorted(fsrc.items(), key=lambda kv: -kv[1]["failures"])[:100]]
    if a.summary_json:
        json.dump(summary, open(a.summary_json, "w"), indent=1)

    cov_col = GRN if not missing else (AMB if len(missing) < len(expected) / 2 else RED)
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Windows Server Activity Report</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Windows server activity</div><h1>Windows Server Activity Report</h1>"
             "<p>Event ingestion by host and event ID, logons and failures, privileged logons, account and group changes, services, tasks and audit-log tampering, built from the archived daily runs.</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d of %d days archived</span><span class='chip'>Counts, not a determination</span>%s</div></div></div><div class='wrap'>"
             % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(done), len(expected),
                "" if actors else "<span class='chip'>User and IP lists omitted</span>"))

    def kpi(label, val, color, small=""):
        v = val if isinstance(val, str) else n(val)
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span>%s</div>" % (color, E(v), E(label), "<small>%s</small>" % E(small) if small else "")
    o.append("<div class='kpis'>%s%s%s%s</div>" % (
        kpi("Events", T["events"], NAVY, "%s ingested, %s hosts (peak day)" % (gb(T["bytes"]), n(T["hosts"]))),
        kpi("User logons", T["logonsOk"], GRN, "%s network, %s remote desktop" % (n(T["networkLogons"]), n(T["rdpLogons"]))),
        kpi("Failed logons", T["logonsFailed"], RED if T["logonsFailed"] else GRN, "%s Kerberos, %s NTLM failures" % (n(T["kerberosFailures"]), n(T["ntlmFailures"]))),
        kpi("Privileged logons", T["privLogons"], AMB, "event 4672, user accounts")))
    chg = T["accountCreated"] + T["accountDeleted"] + T["accountDisabled"] + T["accountEnabled"] + T["passwordChanges"]
    o.append("<div class='kpis two'>%s%s%s%s</div>" % (
        kpi("Account changes", chg, BLU, "%s created, %s deleted" % (n(T["accountCreated"]), n(T["accountDeleted"]))),
        kpi("Group adds", T["groupAdds"], BLU, "%s lockouts" % n(T["lockouts"])),
        kpi("Services / tasks added", "%s / %s" % (n(T["servicesInstalled"]), n(T["tasksCreated"])), AMB),
        kpi("Log clears / policy changes", "%s / %s" % (n(T["logsCleared"]), n(T["auditPolicyChanges"])), RED if T["logsCleared"] else NAVY)))
    o.append("<div class='read'><b>Read this first.</b> Every figure comes from the daily archive of the WindowsSrv_Activity_Report scheduled report; nothing was searched live. "
             "The numbers are counts of Windows event log records, related to NIST 800-53 access, account, change and audit controls. They are not a compliance determination. "
             "Zero means no matching event on an archived day; a day that is not archived is a gap, and a scan the tenant could not run is not available.</div>")
    if nodata:
        o.append("<div class='gap'><b>No Windows data.</b> Every scan on every archived day reports the WindowsAudit table as not available. This tenant does not collect Windows events (or the table has a different name); the counts above are not zeros of activity.</div>")
    hl = []
    if T["logonsFailed"]:
        sp = [k for k, r in fsrc.items() if r["usernames"] >= 10]
        hl.append("%s failed logon(s) (%s of all logon attempts)." % (n(T["logonsFailed"]), "%.1f%%" % (100.0 * T["logonsFailed"] / max(T["logonsFailed"] + T["logonsOk"], 1))))
        if sp and actors:
            hl.append("%d source address(es) tried 10 or more user names in one day (credential spray pattern)." % len(sp))
    for k, lab in (("logsCleared", "audit log clear(s)"), ("auditPolicyChanges", "audit-policy change(s)"), ("accountCreated", "account(s) created"),
                   ("accountDeleted", "account(s) deleted"), ("groupAdds", "group member add(s)"), ("servicesInstalled", "service install(s)"),
                   ("tasksCreated", "scheduled task(s) created"), ("lockouts", "account lockout(s)")):
        if T[k]:
            hl.append("%s %s." % (n(T[k]), lab))
    if not hl:
        hl.append("No failed logons, lockouts, account or group changes, new services or tasks, log clears or policy changes on the archived days.")
    o.append("<div class='panel' style='margin-top:14px'><b>Worth a look</b><ul style='margin:6px 0 0;padding-left:20px'>%s</ul></div>" % "".join("<li>%s</li>" % E(h) for h in hl))

    # 1 coverage
    o.append("<h2><span class='n'>1</span>Archive coverage</h2><p class='sub'>What this report is built from, and which scans the tenant could run.</p>")
    srows = []
    for s in sorted(stat):
        c = stat[s]
        okd, nad = c.get("ok", 0), c.get("not available", 0)
        label = "available" if okd and not nad else ("not available" if nad and not okd else "partial")
        col = GRN if label == "available" else (RED if label == "not available" else AMB)
        srows.append("<tr><td>%s</td><td><span class='pill' style='--c:%s'>%s</span></td><td class='r'>%d ok / %d n.a.</td><td class='mono'>%s</td></tr>" % (E(s), col, label, okd, nad, E((detail.get(s) or "")[:90])))
    o.append("<div class='tw'><table><tbody><tr><td>Days archived</td><td colspan='3' class='r'><span class='pill' style='--c:%s'>%d of %d</span></td></tr>"
             "<tr><td>Script version(s)</td><td colspan='3' class='r mono'>%s</td></tr></tbody></table></div>"
             % (cov_col, len(done), len(expected), E(", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common()))))
    if srows:
        o.append("<div class='tw'><table><thead><tr><th>Scan</th><th>Status</th><th class='r'>Days</th><th>Error</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(srows))
    if missing:
        o.append("<div class='gap'><b>Gap.</b> %d day(s) are not in the archive and are not counted as zero: %s. Run a backfill for them, then rebuild.%s</div>"
                 % (len(missing), E(", ".join(missing[:31]) + (" ..." if len(missing) > 31 else "")),
                    " Non-completed runs: " + E(", ".join("%s=%s" % kv for kv in sorted(other.items()))) + "." if other else ""))
    if len(hashes) > 1:
        o.append("<div class='gap'><b>Script changed during the period.</b> More than one script version produced these days; confirm the counts are defined the same way before comparing days.</div>")

    # 2 trend
    o.append("<h2><span class='n'>2</span>Daily trend</h2><p class='sub'>One bar per UTC day. Hatched amber columns are days missing from the archive.</p><div class='cards'>")
    for m, c in (("events", NAVY), ("logonsOk", GRN), ("logonsFailed", RED), ("privLogons", AMB)):
        o.append("<div class='card' style='--c:%s'><b>%s per day</b>%s</div>" % (c, LABEL[m], bars({d: daily[d][m] for d in daily}, expected, c, LABEL[m])))
    o.append("</div>")
    hdr = "".join("<th class='r'>%s</th>" % SHORT[m] for m in TABLE_COLS)
    body = []
    for d in expected:
        if d in daily:
            body.append("<tr><td class='mono d'>%s</td>%s</tr>" % (d[5:], "".join("<td class='r'>%s</td>" % n(daily[d][m]) for m in TABLE_COLS)))
        else:
            body.append("<tr><td class='mono d'>%s</td><td colspan='%d' class='mut'>not archived (gap)</td></tr>" % (d[5:], len(TABLE_COLS)))
    body.append("<tr><td><b>Total</b></td>%s</tr>" % "".join("<td class='r'><b>%s</b></td>" % n(T[m]) for m in TABLE_COLS))
    o.append("<div class='tw' style='margin-top:14px'><table class='dt'><thead><tr><th>Day</th>%s</tr></thead><tbody>%s</tbody></table></div>"
             "<p class='sub' style='margin-top:8px'>Hosts is the peak single day. Also counted: remote-desktop logons %s, lockouts %s, explicit-credential logons %s, network logons %s, accounts enabled %s, accounts disabled %s, accounts deleted %s, password changes %s, process creations %s, PowerShell script blocks %s.</p>"
             % (hdr, "".join(body), n(T["rdpLogons"]), n(T["lockouts"]), n(T["explicitCreds"]), n(T["networkLogons"]), n(T["accountEnabled"]), n(T["accountDisabled"]), n(T["accountDeleted"]), n(T["passwordChanges"]), n(T["processCreations"]), n(T["powershellScripts"])))

    # 3 ingestion
    o.append("<h2><span class='n'>3</span>Event ingestion</h2><p class='sub'>The content of the Windows ingress report: events and bytes by host and by event ID.</p>")
    lostnote = (" %s event(s) are outside the daily top-300 host and event ID pairs, so the lists are lower bounds." % n(ingest_lost)) if ingest_lost else " The lists cover every event."
    o.append(table("Events by host", "Short host names." + lostnote, [(h, c, host_bytes[h] / 1e6) for h, c in host_tot.items()],
                   ["Host", "Events", "MB"], NAVY, top))
    o.append(table("Events by event ID", "Names come from the AD_EventID lookup, else the description on the event. %d event ID(s) have no name." % unnamed,
                   [(ename(e), c, id_bytes[e] / 1e6) for e, c in id_tot.items()], ["Event ID", "Events", "MB"], NAVY, max(top, 15)))

    # 4 logons
    o.append("<h2><span class='n'>4</span>Logons and failures</h2><p class='sub'>Successful user logons (4624) and failed logons (4625).</p><div class='g2'>")
    o.append(counts("Successful logons by type", "Machine accounts left out.", fac.get("logonType", collections.Counter()), GRN, top, T["logonsOk"],
                    lambda k: "%s (%s)" % (LOGON_TYPE.get(k, "type"), k), ("Logon type", "Logons")))
    o.append(counts("Failed logons by reason", "SubStatus code, else Status.", fac.get("failedReason", collections.Counter()), RED, top, T["logonsFailed"],
                    lambda k: "%s (%s)" % (FAIL_REASON.get(k, "code"), k) if k != "(not recorded)" else k, ("Reason", "Failures")))
    o.append("</div>")
    if actors:
        o.append("<div class='g2'>")
        o.append(counts("Top accounts by logons", "Target account of successful user logons.", fac.get("logonUser", collections.Counter()), GRN, top, T["logonsOk"], None, ("Account", "Logons")))
        o.append(counts("Top accounts by failures", "Target account of failed logons.", fac.get("failedUser", collections.Counter()), RED, top, T["logonsFailed"], None, ("Account", "Failures")))
        o.append("</div>")
        rows = [(k, r["failures"], r["usernames"], r["hosts"], "Credential spray" if r["usernames"] >= 10 else ("Brute force" if r["failures"] >= 50 else "Probe"), short(r["first"]), short(r["last"])) for k, r in fsrc.items()]
        o.append(table("Failed logons by source address", "Many user names from one address is a spray, many failures with few names is brute force, the rest is probing. Lower bound: top 100 a day.",
                       rows, ["Source", "Failures", "User names (peak day)", "Hosts (peak day)", "Pattern", "First seen", "Last seen"], RED, top))
    else:
        o.append("<div class='panel'>Account names and source addresses are omitted in this build.</div>")

    # 5 privileged and account/group changes
    o.append("<h2><span class='n'>5</span>Privileged access and account changes</h2><p class='sub'>Special-privilege logons, and account, group and password events.</p><div class='g2'>")
    o.append(counts("Account events", "By event.", fac.get("acctEvent", collections.Counter()), BLU, top, None, lambda k: "%s %s" % (k, ACCT_EVENT.get(k, "")), ("Event", "Count")))
    o.append(counts("Group additions", "Group that gained a member.", fac.get("groupName", collections.Counter()), BLU, top, None, None, ("Group", "Adds")))
    o.append("</div>")
    if actors:
        o.append("<div class='g2'>")
        o.append(counts("Privileged logons by account", "Special-privilege logons (4672), people only.", fac.get("privAccount", collections.Counter()), AMB, top, T["privLogons"], None, ("Account", "Logons")))
        o.append(counts("Account changes by actor", "Who made the change.", fac.get("acctActor", collections.Counter()), BLU, top, None, None, ("Actor", "Events")))
        o.append(counts("Account changes by target", "The account that was changed.", fac.get("acctTarget", collections.Counter()), BLU, top, None, None, ("Target", "Events")))
        o.append(counts("Group additions by actor", "Who added the member.", fac.get("groupActor", collections.Counter()), BLU, top, None, None, ("Actor", "Adds")))
        o.append("</div>")

    # 6 persistence and tampering
    o.append("<h2><span class='n'>6</span>Services, tasks and audit tampering</h2><p class='sub'>New services and scheduled tasks, cleared logs and audit-policy changes.</p><div class='g2'>")
    o.append(counts("Services and tasks installed", "Name of the service or scheduled task.", fac.get("persistItem", collections.Counter()), AMB, top, None, None, ("Item", "Count")))
    o.append(counts("Log clears and policy changes", "By event.", fac.get("tamperEvent", collections.Counter()), RED, top, None, lambda k: "%s %s" % (k, TAMPER_EVENT.get(k, "")), ("Event", "Count")))
    o.append(counts("Tampering by host", "Host where the log was cleared or the policy changed.", fac.get("tamperHost", collections.Counter()), RED, top, None, None, ("Host", "Count")))
    if actors:
        o.append(counts("Tampering by actor", "Account that did it.", fac.get("tamperActor", collections.Counter()), RED, top, None, None, ("Actor", "Count")))
    o.append("</div>")
    if capped:
        o.append("<p class='sub' style='margin-top:10px'>Lists that reached the 100-value limit on at least one day (so later values are lost): %s.</p>" % E(", ".join("%s (%d d)" % kv for kv in sorted(capped.items()))))

    # 7 mapping + limits
    o.append("<h2><span class='n'>7</span>What these counts relate to</h2><p class='sub'>Indicative crosswalk to NIST SP 800-53 Rev. 5. Related, not equivalent.</p>")
    o.append("<div class='tw'><table><thead><tr><th>Area</th><th>800-53 controls</th><th>Counts that relate</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td>%s</td><td class='mono'>%s</td><td>%s</td></tr>" % (E(x), E(y), E(z)) for x, y, z in SEC_FAMILY))
    o.append("<div class='foot'><b>Limits</b><ul>%s</ul><p>Source: archive of the scheduled report WindowsSrv_Activity_Report. No live search was run to build this report.</p></div>" % "".join("<li>%s</li>" % E(l) for l in LIMITS))
    o.append("</div></body></html>")
    open(a.out, "w").write(fb.apply_brand("".join(o)))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["section", "key", "metric", "count"])
            for d in expected:
                if d in daily:
                    for m in METRICS:
                        w.writerow(["daily", d, m, daily[d][m]])
                else:
                    w.writerow(["daily", d, "gap", ""])
            for m in METRICS:
                w.writerow(["total", dfrom + ".." + dto, m, T[m]])
            for h, c in host_tot.most_common():
                w.writerow(["host", h, "events", c]); w.writerow(["host", h, "bytes", host_bytes[h]])
            for e, c in id_tot.most_common():
                w.writerow(["event_id", ename(e), "events", c]); w.writerow(["event_id", ename(e), "bytes", id_bytes[e]])
            for f, c in fac.items():
                if f in ACTOR_FACETS and not actors:
                    continue
                for v, cnt in c.most_common():
                    w.writerow(["facet:" + f, v, "count", cnt])
            if actors:
                for k, r in sorted(fsrc.items(), key=lambda kv: -kv[1]["failures"]):
                    w.writerow(["failed_source", k, "failures", r["failures"]]); w.writerow(["failed_source", k, "peak_day_usernames", r["usernames"]])
    if a.interactive:
        build_interactive(a.interactive, {"T": T, "fac": fac, "fsrc": fsrc, "actors": actors, "top": top, "expected": expected, "daily": daily, "other": other,
                                          "lostnote": lostnote, "host_bytes": host_bytes, "host_tot": host_tot, "id_bytes": id_bytes, "id_tot": id_tot,
                                          "ename": ename, "unnamed": unnamed, "stat": stat, "detail": detail, "tenant": a.tenant, "site": a.site,
                                          "period": period, "missing": missing, "nodata": nodata, "hashes": ", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common()),
                                          "multi_script": len(hashes) > 1, "capped": capped, "hl": hl})
    print("period %s: %d of %d days archived, %s events, %s logons, %s failed, %d gap day(s)%s"
          % (period, len(done), len(expected), n(T["events"]), n(T["logonsOk"]), n(T["logonsFailed"]), len(missing), ", NO WINDOWS DATA" if nodata else ""))


if __name__ == "__main__":
    main()
