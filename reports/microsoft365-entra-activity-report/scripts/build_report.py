#!/usr/bin/env python3
"""Build the Microsoft 365 and Entra Activity report from the scheduled-report ARCHIVE only (HTML + CSV + summary JSON).

  build_report.py --archive day1.json [day2.json ...] --out report.html [--csv report.csv] [--summary-json s.json]
                  [--from YYYY-MM-DD --to YYYY-MM-DD] [--tenant NAME --site Develop] [--top 10]

Each --archive file is the saved result of download_report_archive (days[] of {entry, result}); several files and
several days per file are merged. This script never queries a tenant. Daily results are combined the only safe way:
the per-day trend rows are kept once each and summed, facet tables are summed by value, a missing value counts as 0,
and a day that was not archived is reported as a GAP, never as zero activity.

Five sources are read (Office365, AzureSigninLogs, AzureAuditLogs, AADServicePrincipalSignInLogs,
AADNonInteractiveUserSignInLogs). A source the tenant does not have is reported as "not available" (the archived
`sources` table says so per day), never as zero. A source whose objects are absent from a day's result (older script
version) is listed as not collected that day.
Actors: from archive script version 3 the daily result also holds user names and source IP addresses (top 100 a day:
most active users, failed users, failed IPs, admin actors). The report and the explorer show them, so both are
personal data. The compliance assessment does not read them. Days archived by an earlier script version have counts
only and are missing from those lists.
"""
import argparse, collections, csv, datetime as dt, glob, html, json, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY, BLU, TEAL = "#14213d", "#B91C1C", "#B45309", "#15803D", "#64748B", "#1D4ED8", "#0F766E"
FACET_CAP = 100

# metric: (key, label, short, colour); colour "risk" = red when above zero, green at zero.
# facets: (key, title, subtitle, kind)  kind "full" covers every event; "subset" has "(none)" for the complement.
SOURCES = [
    {"key": "o365", "table": "Office365", "title": "Office 365 audit events", "eyebrow": "Exchange, SharePoint, OneDrive, Teams and more",
     "metrics": [
         ("events", "Events", "Events", NAVY), ("failedOps", "Failed operations", "Failed", AMB), ("adminOps", "Admin operations", "Admin", BLU),
         ("loginsOk", "Logins ok", "Logins", NAVY), ("loginsFailed", "Failed logins", "Login fail", "risk"),
         ("mailItemsAccessed", "Mail items accessed", "Mail read", BLU), ("mailSent", "Mail sent", "Sent", BLU),
         ("hardDeletes", "Hard deletes", "Hard del", "risk"), ("inboxRuleChanges", "Inbox rule changes", "Rules", "risk"),
         ("mailboxPermissionChanges", "Mailbox permission changes", "Perms", "risk"), ("sharingEvents", "Sharing events", "Sharing", BLU),
         ("externalAccess", "External access", "External", AMB), ("adminConfigChanges", "Admin config changes", "Config", AMB),
         ("securityAlerts", "Security alerts", "Alerts", "risk"), ("dlpEvents", "DLP events", "DLP", "risk"), ("copilotEvents", "Copilot events", "Copilot", TEAL)],
     "kpis": ["events", "adminOps", "mailItemsAccessed", "loginsFailed", "hardDeletes", "inboxRuleChanges", "mailboxPermissionChanges", "sharingEvents"],
     "table_cols": ["events", "failedOps", "adminOps", "loginsOk", "loginsFailed", "mailItemsAccessed", "hardDeletes", "sharingEvents", "adminConfigChanges"],
     "charts": [("events", NAVY), ("mailItemsAccessed", BLU), ("adminOps", AMB), ("loginsFailed", RED)],
     "facets": [
         ("workload", "Events by workload", "Office 365 service that logged the event.", "full"),
         ("operation", "Top operations", "The engine keeps 100 values a day; rarer operations are in (other).", "full"),
         ("sensitiveOp", "Sensitive operations", "Mail-rule, permission, delete, sharing and Exchange configuration operations.", "subset"),
         ("adminOp", "Admin operations", "Operations by admin accounts (Admin or DcAdmin user type).", "subset"),
         ("failedOp", "Failed operations", "Operations that did not succeed.", "subset"),
         ("userType", "By user type", "Regular, Admin, Application, System and so on.", "full"),
         ("country", "By country", "Country of the client address.", "full"),
         ("deviceOS", "By device operating system", "Recorded for a minority of events.", "full"),
         ("browser", "By browser", "Recorded for a minority of events.", "full"),
         ("resultStatus", "By result status", "Result recorded on the event.", "full"),
         ("user", "Most active users", "UserId on the event. Names appear: treat this report as personal data.", "full"),
         ("failedUser", "Users with failed operations or logins", "Failed operations and UserLoginFailed, by UserId; (none) is left out.", "subset"),
         ("failedIp", "Source IPs of failed operations or logins", "Client address of failed operations and UserLoginFailed; (none) is left out.", "subset"),
         ("adminActor", "Admin operation actors", "UserId of events by Admin or DcAdmin user types; (none) is left out.", "subset")]},
    {"key": "signin", "table": "AzureSigninLogs", "title": "Entra user sign-ins", "eyebrow": "Interactive sign-ins by people",
     "metrics": [
         ("events", "Sign-ins", "Sign-ins", NAVY), ("failed", "Failed", "Failed", AMB), ("interactive", "Interactive", "Interact", BLU),
         ("mfaRequired", "MFA required", "MFA", GRN), ("singleFactorOk", "Single-factor successes", "1-factor", AMB),
         ("caFailures", "Conditional Access failures", "CA fail", "risk"), ("risky", "Risky sign-ins", "Risky", "risk"),
         ("guests", "Guest sign-ins", "Guests", BLU), ("legacyAuth", "Legacy authentication", "Legacy", "risk")],
     "kpis": ["events", "failed", "mfaRequired", "singleFactorOk", "legacyAuth", "caFailures", "risky", "guests"],
     "table_cols": ["events", "failed", "interactive", "mfaRequired", "singleFactorOk", "caFailures", "risky", "guests", "legacyAuth"],
     "charts": [("events", NAVY), ("failed", RED)],
     "facets": [
         ("app", "By application", "Application the user signed in to.", "full"),
         ("clientApp", "By client app", "Browser, mobile and desktop clients and legacy protocols.", "full"),
         ("failedCode", "Failed sign-ins by error code", "(none) means the sign-in succeeded; it is left out.", "subset"),
         ("authRequirement", "MFA requirement", "Single factor versus multifactor.", "full"),
         ("caStatus", "Conditional Access status", "Result of Conditional Access evaluation.", "full"),
         ("protocol", "By authentication protocol", "OAuth, SAML, WS-Federation and others.", "full"),
         ("country", "By country", "Country of the sign-in.", "full"),
         ("deviceOS", "By device operating system", "From device detail.", "full"),
         ("browser", "By browser", "From device detail.", "full"),
         ("userType", "By user type", "Member or guest.", "full"),
         ("riskLevel", "By sign-in risk level", "Identity Protection risk during sign-in.", "full"),
         ("user", "Most active users", "User principal name; (not recorded) is mostly app-only and failed sign-ins with no user.", "full"),
         ("failedUser", "Users with failed sign-ins", "User principal name of failed sign-ins; (none) is left out.", "subset"),
         ("failedIp", "Source IPs of failed sign-ins", "IP address of failed sign-ins; (none) is left out.", "subset")]},
    {"key": "audit", "table": "AzureAuditLogs", "title": "Entra directory audit", "eyebrow": "Changes to users, groups, roles, apps and policies",
     "metrics": [
         ("events", "Changes logged", "Changes", NAVY), ("failed", "Failed", "Failed", AMB), ("userChanges", "User changes", "Users", BLU),
         ("groupChanges", "Group changes", "Groups", BLU), ("roleChanges", "Role changes", "Roles", "risk"),
         ("appChanges", "Application changes", "Apps", AMB), ("policyChanges", "Policy changes", "Policy", "risk"),
         ("adds", "Adds", "Adds", TEAL), ("updates", "Updates", "Updates", TEAL), ("deletes", "Deletes", "Deletes", AMB),
         ("passwordEvents", "Password events", "Password", AMB)],
     "kpis": ["events", "failed", "userChanges", "groupChanges", "roleChanges", "appChanges", "policyChanges", "passwordEvents"],
     "table_cols": ["events", "failed", "userChanges", "groupChanges", "roleChanges", "appChanges", "policyChanges", "deletes", "passwordEvents"],
     "charts": [("events", NAVY), ("roleChanges", RED)],
     "facets": [
         ("category", "By category", "Directory audit category.", "full"),
         ("activity", "Top activities", "Activity name, for example Update device or Add member to group.", "full"),
         ("opType", "By operation type", "Add, Update, Delete and others.", "full"),
         ("service", "By logging service", "Service that logged the change.", "full"),
         ("result", "By result", "success or failure.", "full"),
         ("failedActivity", "Failed activities", "Activity of failed changes; (none) means success and is left out.", "subset"),
         ("actor", "Who made the changes", "Initiating user principal name, else the initiating app.", "full"),
         ("failedActor", "Who failed", "Initiator of failed changes; (none) is left out.", "subset")]},
    {"key": "sp", "table": "AADServicePrincipalSignInLogs", "title": "Entra service-principal sign-ins", "eyebrow": "Applications and automation, not people",
     "metrics": [
         ("events", "Sign-ins", "Sign-ins", NAVY), ("failed", "Failed", "Failed", AMB),
         ("secretErrors", "Client secret errors", "Secret err", "risk"), ("secretAuth", "Client secret auth", "Secret", AMB),
         ("assertionAuth", "Certificate or federated auth", "Cert/fed", GRN)],
     "kpis": ["events", "failed", "secretErrors", "secretAuth", "assertionAuth"],
     "table_cols": ["events", "failed", "secretErrors", "secretAuth", "assertionAuth"],
     "charts": [("events", NAVY), ("failed", RED)],
     "facets": [
         ("app", "By application", "Service principal that signed in.", "full"),
         ("resource", "By resource", "API or service the application called.", "full"),
         ("credential", "By credential type", "clientSecret, clientAssertion (certificate or federated) or none.", "full"),
         ("failedCode", "Failed sign-ins by error code", "7000222 and 7000215 are an expired or invalid client secret; (none) is left out.", "subset"),
         ("country", "By country", "Country of the sign-in.", "full"),
         ("failedIp", "Source IPs of failed sign-ins", "IP address of failed sign-ins; (none) is left out.", "subset")]},
    {"key": "ni", "table": "AADNonInteractiveUserSignInLogs", "title": "Entra non-interactive user sign-ins", "eyebrow": "Token refreshes and background sign-ins by people",
     "metrics": [("events", "Sign-ins", "Sign-ins", NAVY), ("failed", "Failed", "Failed", AMB), ("guests", "Guest sign-ins", "Guests", BLU)],
     "kpis": ["events", "failed", "guests"],
     "table_cols": ["events", "failed", "guests"],
     "charts": [("events", NAVY), ("failed", RED)],
     "facets": [
         ("app", "By application", "Application the user signed in to.", "full"),
         ("clientApp", "By client app", "Client application type.", "full"),
         ("failedCode", "Failed sign-ins by error code", "(none) means the sign-in succeeded; it is left out.", "subset"),
         ("country", "By country", "Country of the sign-in.", "full"),
         ("failedUser", "Users with failed sign-ins", "User principal name of failed sign-ins; (none) is left out.", "subset"),
         ("failedIp", "Source IPs of failed sign-ins", "IP address of failed sign-ins; (none) is left out.", "subset")]},
]
BYKEY = {s["key"]: s for s in SOURCES}

SEC_FAMILY = [  # indicative, related not equivalent
    ("Audit events recorded and reviewable", "AU-2, AU-3, AU-6, AU-12", "Office 365 events, directory changes, sign-in counts"),
    ("User authentication and MFA", "IA-2, IA-5, AC-7", "sign-ins, failed sign-ins, MFA required, single-factor successes, legacy authentication"),
    ("Privileged and role changes", "AC-2, AC-5, AC-6", "admin operations, role changes, Exchange configuration changes"),
    ("Credential and application identity", "IA-4, IA-5", "password events, service-principal secret errors, credential types"),
    ("Mail, sharing and data protection", "AC-4, SI-4, SC-7", "mail items accessed, sharing and external access, DLP events, hard deletes, inbox rules"),
    ("Access policy and risk", "AC-3, AC-17, SI-4", "Conditional Access failures, risky sign-ins, security alerts"),
]
LIMITS = [
    "This report names users and source IP addresses (most active users, failed users, failed IPs, admin actors). Treat it as personal data and share it accordingly. Each list holds at most the top 100 values a day, so a total over several days is a lower bound for a user or address that never reached a day's top 100. Days archived before the actor lists existed are missing from them. Distinct users and addresses are not counted because they cannot be summed across days.",
    "An archived day is a snapshot taken a few hours after the day ended; events that arrive later are not added.",
    "Facet tables hold at most 100 values each. Rarer values appear in the (other) row, computed as the day's events minus the listed values (full-coverage lists only).",
    "A day missing from the archive is a gap, not zero activity. A source the tenant does not have is shown as not available, not as zero.",
    "Entra sign-in tables and Office 365 audit events overlap in what they describe (Office 365 also logs Azure Active Directory logins). The sources are reported separately and are not added together.",
    "Raw AzureAudit and MSEntra tables duplicate the parsed Entra tables and are deliberately not read.",
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
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:14px}
.kpis.top{margin-top:-46px;grid-template-columns:repeat(5,1fr)}.kpis.top .kpi b{font-size:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:26px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}.kpi small{display:block;color:var(--mut);font-size:11px;margin-top:2px}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a}
.gap{border-left:4px solid #B45309;background:#fff7ed;border-radius:0 10px 10px 0;padding:12px 18px;margin-top:12px;color:#7c2d12}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line)}
td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
td.d{white-space:nowrap}
table.dt{font-size:11px}table.dt th,table.dt td{padding:6px 7px}table.dt th{letter-spacing:.03em}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);margin-top:10px}
.mut{color:var(--mut)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;word-break:break-word}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-left:4px solid var(--c)}
.card b{display:block;color:var(--navy);font-size:12px;margin-bottom:4px}
.card svg{width:100%;height:auto;display:block}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
td.bar{width:30%}.bar i{display:block;height:8px;border-radius:4px;background:var(--c);min-width:2px}
.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:0 16px}
.g2 h3{margin:16px 0 2px;font-size:13px;color:var(--navy)}
.g2 .sub{font-size:12px;margin:0 0 6px}
.g2 td.bar,.g2 th:last-child{display:none}.g2 table{font-size:12px}.g2 td,.g2 th{padding:6px 9px}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot li{margin:3px 0}
@media screen and (max-width:760px){.kpis,.kpis.top,.cards,.g2{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}tr,.card,.kpi,.g2>div{break-inside:avoid}.kpi,.pill,.bar i,.card,.read,.gap,svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def n(v):
    return "{:,}".format(int(v))


def pct(a, b):
    return "%.2f%%" % (100.0 * a / b) if b else "n/a"


def rows_of(tbl):
    return (tbl or {}).get("rows") or []


def load(paths):
    """Return ({day: day-dict}, {day: state}) for completed days and the others.
    day-dict: entry, trend{src:[rows] or None}, facets{src:{facet:{value:count}}}, status{src:'ok'|'not available'|None},
    capped{src:set(facet)}."""
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
            trend, facets, status, capped = {}, {}, {}, collections.defaultdict(set)
            names = set()
            for o in res.get("objects", []):
                nm = o.get("name", "")
                names.add(nm)
                if nm == "sources":
                    for r in rows_of(o.get("table")):
                        s = r.get("source")
                        if r.get("status") == "ok":
                            status.setdefault(s, "ok")
                        else:
                            status[s] = "not available"
                elif nm.endswith("_trend"):
                    trend[nm[:-6]] = rows_of(o.get("table"))
                elif nm.endswith("_facets"):
                    src = nm[:-7]
                    om = (o.get("value") or {}).get("orderedMap") or {}
                    fs = {}
                    for k, v in zip(om.get("keys", []), om.get("values", [])):
                        if k == "PrimaryResult":
                            continue
                        sx = (v or {}).get("sx") or {}
                        rows = sx.get("rows") or []
                        fs[k] = {str(r.get(k)): int(r.get("count_") or 0) for r in rows}
                        if (sx.get("rowCount") or len(rows)) >= FACET_CAP:
                            capped[src].add(k)
                    facets[src] = fs
            have = {}
            for s in SOURCES:
                k = s["key"]
                if k + "_trend" not in names and k + "_facets" not in names:
                    have[k] = "not collected"          # older script version: the source did not exist yet
                else:
                    st = status.get(s["table"])
                    have[k] = st or ("ok" if trend.get(k) else "unknown")
            prev = done.get(key)
            if prev and (prev["entry"].get("completedOn") or "") >= (en.get("completedOn") or ""):
                continue
            done[key] = {"entry": en, "trend": trend, "facets": facets, "have": have, "capped": capped}
    return done, other


def merge(done):
    daily = {s["key"]: {} for s in SOURCES}
    fac = {s["key"]: {f[0]: collections.Counter() for f in s["facets"]} for s in SOURCES}
    for day, d in done.items():
        for s in SOURCES:
            k = s["key"]
            if d["have"][k] != "ok":
                continue
            tot = collections.Counter()
            for r in d["trend"].get(k, []):
                for m in s["metrics"]:
                    tot[m[0]] += int(r.get(m[0]) or 0)
            daily[k][day] = tot
            for f in s["facets"]:
                for v, c in d["facets"].get(k, {}).get(f[0], {}).items():
                    fac[k][f[0]][v] += c
    return daily, fac


def bars(series, days, color, title):
    """Inline SVG bar chart: one bar per calendar day; a day without data is a hatched gap, never a zero bar."""
    W, H, L, B = 480, 110, 6, 18
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


def table(title, sub, counter, total, color, top, kind, tail=0):
    items = [(k, v) for k, v in counter.items() if v and (kind == "full" or k != "(none)")]
    items.sort(key=lambda kv: -kv[1])
    shown = items[:top]
    rest = sum(v for _, v in items[top:]) + (tail if kind == "full" else 0)
    head = "<div><h3>%s</h3><p class='sub'>%s</p>" % (E(title), E(sub))
    if not shown:
        return head + "<div class='panel mut'>None in this period.</div></div>"
    mx = shown[0][1]
    r = []
    for k, v in shown:
        r.append("<tr><td class='mono'>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='bar'><i style='--c:%s;width:%.0f%%'></i></td></tr>" % (E(k), n(v), pct(v, total), color, 100.0 * v / mx))
    if rest:
        r.append("<tr><td class='mut'>(other)</td><td class='r'>%s</td><td class='r'>%s</td><td></td></tr>" % (n(rest), pct(rest, total)))
    return head + "<div class='tw'><table><thead><tr><th>Value</th><th class='r'>Count</th><th class='r'>Share</th><th></th></tr></thead><tbody>%s</tbody></table></div></div>" % "".join(r)


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def mcolor(m, val):
    c = m[3]
    if c == "risk":
        return RED if val else GRN
    return c


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
    period = "%s to %s" % (dfrom, dto)

    # per-source availability
    avail = {}
    for s in SOURCES:
        k = s["key"]
        c = collections.Counter(d["have"][k] for d in done.values())
        avail[k] = c
    T = {s["key"]: collections.Counter() for s in SOURCES}
    for s in SOURCES:
        for c in daily[s["key"]].values():
            T[s["key"]].update(c)

    summary = {"period": period, "days_expected": len(expected), "days_archived": len(done), "missing_days": missing,
               "non_completed": other, "script_hashes": dict(hashes),
               "sources": {s["key"]: {"table": s["table"], "days_ok": avail[s["key"]]["ok"], "days_not_available": avail[s["key"]]["not available"],
                                      "days_not_collected": avail[s["key"]]["not collected"],
                                      "totals": {m[0]: T[s["key"]][m[0]] for m in s["metrics"]},
                                      "daily": {d: {m[0]: daily[s["key"]][d][m[0]] for m in s["metrics"]} for d in sorted(daily[s["key"]])},
                                      "facets": {f: dict(c.most_common()) for f, c in fac[s["key"]].items()}} for s in SOURCES}}
    if a.summary_json:
        json.dump(summary, open(a.summary_json, "w"), indent=1)

    cov_col = GRN if not missing else (AMB if len(missing) < len(expected) / 2 else RED)
    o = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Microsoft 365 and Entra Activity Report</title><style>%s</style></head><body>" % STYLE]
    o.append("<div class='hero'><div class='wrap'><div class='eyebrow'>Microsoft 365 and Entra activity</div><h1>Microsoft 365 and Entra Activity Report</h1>"
             "<p>Daily counts of Office 365 audit events, user and application sign-ins and directory changes, built from the archived daily runs.</p>"
             "<div class='chips'><span class='chip'>%s</span><span class='chip'>%s</span><span class='chip'>Period %s</span>"
             "<span class='chip'>%d of %d days archived</span><span class='chip'>Counts, not a determination</span></div></div></div><div class='wrap'>"
             % (E(a.tenant or "Tenant"), E(a.site or "Connector"), E(period), len(done), len(expected)))

    def na(k):
        return avail[k]["ok"] == 0

    def top_kpi(k, label, color):
        if na(k):
            return "<div class='kpi' style='--c:%s'><b>n/a</b><span>%s</span><small>not available</small></div>" % (GRY, E(label))
        return "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span><small>%s a day on average</small></div>" % (color, n(T[k]["events"]), E(label), n(T[k]["events"] / max(avail[k]["ok"], 1)))
    o.append("<div class='kpis top'>%s%s%s%s%s</div>" % (top_kpi("o365", "Office 365 events", NAVY), top_kpi("signin", "User sign-ins", BLU),
             top_kpi("audit", "Directory changes", TEAL), top_kpi("sp", "App sign-ins", AMB), top_kpi("ni", "Non-interactive", GRY)))

    o.append("<div class='read'><b>Read this first.</b> Every figure comes from the daily archive of the Office365_Entra_Activity_Report scheduled report; "
             "nothing was searched live. The numbers are counts of events, related to NIST 800-53 audit, authentication and access controls. "
             "They are not a compliance determination. Zero means no matching event on an archived day; a day that is not archived is a gap, and "
             "a source the tenant does not have is reported as not available.</div>")

    # highlights from the totals
    hl = []
    t = T["sp"]
    if t["secretErrors"]:
        hl.append("%s service-principal sign-in(s) failed on an expired or invalid client secret (%s of that source's sign-ins)." % (n(t["secretErrors"]), pct(t["secretErrors"], t["events"])))
    if t["secretAuth"] and t["events"]:
        hl.append("%s of service-principal sign-ins used a client secret rather than a certificate or federated credential." % pct(t["secretAuth"], t["events"]))
    t = T["signin"]
    if t["legacyAuth"]: hl.append("%s user sign-in(s) used legacy authentication." % n(t["legacyAuth"]))
    if t["caFailures"]: hl.append("%s user sign-in(s) failed Conditional Access." % n(t["caFailures"]))
    if t["risky"]: hl.append("%s user sign-in(s) were flagged risky." % n(t["risky"]))
    if t["singleFactorOk"] and t["events"]: hl.append("%s of user sign-ins succeeded with a single factor." % pct(t["singleFactorOk"], t["events"]))
    t = T["audit"]
    if t["roleChanges"]: hl.append("%s directory role change(s)." % n(t["roleChanges"]))
    if t["policyChanges"]: hl.append("%s directory policy change(s)." % n(t["policyChanges"]))
    t = T["o365"]
    if t["hardDeletes"]: hl.append("%s mailbox hard delete(s)." % n(t["hardDeletes"]))
    if t["inboxRuleChanges"]: hl.append("%s inbox rule change(s)." % n(t["inboxRuleChanges"]))
    if t["mailboxPermissionChanges"]: hl.append("%s mailbox permission change(s)." % n(t["mailboxPermissionChanges"]))
    if t["securityAlerts"]: hl.append("%s Security and Compliance alert(s)." % n(t["securityAlerts"]))
    if not hl: hl.append("No notable counts on the archived days.")
    o.append("<div class='panel' style='margin-top:14px'><b>Worth a look</b><ul style='margin:6px 0 0;padding-left:20px'>%s</ul></div>" % "".join("<li>%s</li>" % E(h) for h in hl))

    # coverage
    o.append("<h2><span class='n'>1</span>Archive coverage</h2><p class='sub'>What this report is built from, and which sources the tenant has.</p>")
    cap_total = sum(1 for d in done.values() for s_, fs in d["capped"].items() for _ in fs)
    o.append("<div class='tw'><table><tbody>"
             "<tr><td>Days archived</td><td class='r'><span class='pill' style='--c:%s'>%d of %d</span></td></tr>"
             "<tr><td>Script version(s)</td><td class='r mono'>%s</td></tr>"
             "<tr><td>Breakdown lists that hit the 100-value cap (day by list)</td><td class='r mono'>%s</td></tr></tbody></table></div>"
             % (cov_col, len(done), len(expected), E(", ".join("%s (%d d)" % (h, c) for h, c in hashes.most_common())), n(cap_total)))
    rowsrc = []
    for s in SOURCES:
        c = avail[s["key"]]
        if c["ok"] == len(done) and not T[s["key"]]["events"]:
            st = "<span class='pill' style='--c:%s'>available, no events</span>" % GRY
        elif c["ok"] == len(done):
            st = "<span class='pill' style='--c:%s'>available</span>" % GRN
        elif c["ok"] == 0 and c["not available"]:
            st = "<span class='pill' style='--c:%s'>not available on this tenant</span>" % AMB
        elif c["ok"] == 0:
            st = "<span class='pill' style='--c:%s'>not collected</span>" % GRY
        else:
            st = "<span class='pill' style='--c:%s'>partial</span>" % AMB
        detail = "%d ok" % c["ok"] + (", %d not available" % c["not available"] if c["not available"] else "") + (", %d not collected" % c["not collected"] if c["not collected"] else "")
        ev = T[s["key"]]["events"]
        rowsrc.append("<tr><td>%s<div class='mono mut'>%s</div></td><td>%s</td><td class='r'>%s</td><td class='r'>%s</td></tr>" % (E(s["title"]), E(s["table"]), st, E(detail), n(ev) if c["ok"] else "n/a"))
    o.append("<div class='tw'><table><thead><tr><th>Source</th><th>Status</th><th class='r'>Days</th><th class='r'>Events</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(rowsrc))
    o.append("<p class='sub' style='margin-top:8px'>not available means the tenant has no such table (the scan was caught and recorded); not collected means an older script version did not include that source yet. Neither is counted as zero.</p>")
    if missing:
        o.append("<div class='gap'><b>Gap.</b> %d day(s) are not in the archive and are not counted as zero: %s. Run a backfill for them, then rebuild.%s</div>"
                 % (len(missing), E(", ".join(missing[:31]) + (" ..." if len(missing) > 31 else "")),
                    " Non-completed runs: " + E(", ".join("%s=%s" % kv for kv in sorted(other.items()))) + "." if other else ""))
    if len(hashes) > 1:
        o.append("<div class='gap'><b>Script changed during the period.</b> More than one script version produced these days; confirm the counts are defined the same way before comparing days.</div>")

    top = a.top
    sec = 2
    days = expected
    for s in SOURCES:
        k = s["key"]
        c = avail[k]
        o.append("<h2><span class='n'>%d</span>%s</h2><p class='sub'>%s. Table <span class='mono'>%s</span>.</p>" % (sec, E(s["title"]), E(s["eyebrow"]), E(s["table"])))
        sec += 1
        if c["ok"] == 0:
            why = ("The tenant has no %s table, so this section is skipped. It is not a zero." % s["table"]) if c["not available"] else \
                  ("The archived days were produced by a script version that did not include this source, so there is nothing to show. It is not a zero.")
            o.append("<div class='gap'><b>No data.</b> %s</div>" % E(why))
            continue
        tot = T[k]
        ev = tot["events"]
        if c["not available"] or c["not collected"]:
            o.append("<div class='gap'><b>Partial coverage.</b> This source has data on %d of %d archived days (%d not available, %d not collected). Totals cover those days only.</div>" % (c["ok"], len(done), c["not available"], c["not collected"]))
        if ev == 0:
            o.append("<div class='panel mut' style='margin-top:10px'>The table exists and returned no events on the %d archived days with data.</div>" % c["ok"])
        mm = {m[0]: m for m in s["metrics"]}
        o.append("<div class='kpis'>%s</div>" % "".join(
            "<div class='kpi' style='--c:%s'><b>%s</b><span>%s</span>%s</div>" % (mcolor(mm[x], tot[x]), n(tot[x]), E(mm[x][1]), "<small>%s of events</small>" % pct(tot[x], ev) if x != "events" and ev else "")
            for x in s["kpis"]))
        o.append("<div class='cards'>")
        for m, col in s["charts"]:
            o.append("<div class='card' style='--c:%s'><b>%s per day</b>%s</div>" % (col, E(mm[m][1]), bars({d: daily[k][d][m] for d in daily[k]}, days, col, mm[m][1])))
        o.append("</div>")
        hdr = "".join("<th class='r'>%s</th>" % E(mm[x][2]) for x in s["table_cols"])
        body = []
        for d in days:
            if d in daily[k]:
                body.append("<tr><td class='mono d'>%s</td>%s</tr>" % (d, "".join("<td class='r'>%s</td>" % n(daily[k][d][x]) for x in s["table_cols"])))
            else:
                body.append("<tr><td class='mono d'>%s</td><td colspan='%d' class='mut'>no data (gap or source not available)</td></tr>" % (d, len(s["table_cols"])))
        body.append("<tr><td><b>Total</b></td>%s</tr>" % "".join("<td class='r'><b>%s</b></td>" % n(tot[x]) for x in s["table_cols"]))
        o.append("<div class='tw' style='margin-top:14px'><table class='dt'><thead><tr><th>Day</th>%s</tr></thead><tbody>%s</tbody></table></div>" % (hdr, "".join(body)))
        if len(s["metrics"]) > len(s["table_cols"]):
            rest = [m for m in s["metrics"] if m[0] not in s["table_cols"]]
            o.append("<p class='sub' style='margin-top:8px'>Also counted: %s.</p>" % E(", ".join("%s %s" % (m[1].lower(), n(tot[m[0]])) for m in rest)))
        o.append("<div class='g2'>")
        for f, title, subt, kind in s["facets"]:
            cnt = fac[k][f]
            tail = max(ev - sum(cnt.values()), 0) if kind == "full" else 0
            o.append(table(title, subt, cnt, ev, NAVY if kind == "full" else AMB, top, kind, tail))
        o.append("</div>")

    o.append("<h2><span class='n'>%d</span>What these counts relate to</h2><p class='sub'>Indicative crosswalk to NIST SP 800-53 Rev. 5. Related, not equivalent.</p>" % sec)
    o.append("<div class='tw'><table><thead><tr><th>Area</th><th>800-53 controls</th><th>Counts that relate</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td>%s</td><td class='mono'>%s</td><td>%s</td></tr>" % (E(x), E(y), E(z)) for x, y, z in SEC_FAMILY))
    o.append("<div class='foot'><b>Limits</b><ul>%s</ul><p>Source: archive of the scheduled report Office365_Entra_Activity_Report. No live search was run to build this report.</p></div>" % "".join("<li>%s</li>" % E(l) for l in LIMITS))
    o.append("</div></body></html>")
    open(a.out, "w").write("".join(o))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["section", "source", "key", "metric", "count"])
            for s in SOURCES:
                k = s["key"]
                for d in days:
                    if d in daily[k]:
                        for m in s["metrics"]:
                            w.writerow(["daily", k, d, m[0], daily[k][d][m[0]]])
                    else:
                        w.writerow(["daily", k, d, "no data", ""])
                for m in s["metrics"]:
                    w.writerow(["total", k, dfrom + ".." + dto, m[0], T[k][m[0]]])
                for f, c in fac[k].items():
                    for v, cnt in c.most_common():
                        w.writerow(["facet:" + f, k, v, "count", cnt])
    print("period %s: %d of %d days archived; %s; %d gap day(s)" % (period, len(done), len(expected),
          ", ".join("%s %s" % (s["key"], n(T[s["key"]]["events"]) if avail[s["key"]]["ok"] else "n/a") for s in SOURCES), len(missing)))


if __name__ == "__main__":
    main()
