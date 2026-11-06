#!/usr/bin/env python3
"""Google Workspace resource report: user health, 2-Step Verification, admins, groups and the audit activity of the archived days in one page.

Archive only. Reads the archived daily runs of the scheduled FPL report GoogleWorkspace_Resource_Report (the
download_report_archive output for one Fluency / Ingext account). Each archived run covers one day. Users, org units,
domains, groups and scores are a snapshot from the latest completed day; the audit activity is merged across all archived days. Writes
facts.json, three CSVs, a Fluency-branded print HTML page and a self-contained interactive HTML file.
Standard library plus the fluency-report brand kit (charts and PDF). It never queries the tenant.

  googleworkspace_resource_report.py check  --archive FILE [FILE ...]
  googleworkspace_resource_report.py render --archive FILE [FILE ...] --work DIR --account NAME [--customer TEXT]
"""
import argparse, collections, csv, datetime as dt, html, json, os, shutil, sys
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


REPORT = "GoogleWorkspace_Resource_Report"
MAX_AGE_DAYS = 3            # an archived day older than this is flagged as out of date
USERS_CAP = 200             # the archive lists at most this many users
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
TABLES = ["gw_summary", "gw_users", "gw_orgunits", "gw_domains", "gw_groups", "gw_daily", "gw_events", "gw_admin", "gw_suspicious"]
STATE_COLOR = {"Needs action": "#b3242e", "Watch": "#a06c00", "Healthy": "#175d9a", "Disabled": "#8a8a8a"}


# ---------------------------------------------------------------- loading
ACTIVITY_SUM = [("events", "events"), ("logins", "logins"), ("loginFailures", "loginFailures"), ("suspiciousLogins", "suspicious"),
                ("adminChanges", "adminChanges"), ("tokenGrants", "tokenGrants"), ("mobileEvents", "mobile")]


def _tables_of(res):
    tables = {}
    for o in res.get("objects") or []:
        tb = o.get("table") or {}
        tables[o.get("name")] = tb.get("rows") or []
    return tables


def _covered(tables, rng):
    """The UTC days one archived run covers: windowDays days ending the day before asOf (a daily run is one day)."""
    summ = (tables.get("gw_summary") or [{}])[0]
    as_of = str(summ.get("asOf") or rng)[:10]
    try:
        end = dt.date.fromisoformat(as_of)
    except ValueError:
        return as_of, []
    try:
        w = max(1, int(float(summ.get("windowDays") or 1)))
    except (TypeError, ValueError):
        w = 1
    return as_of, [(end - dt.timedelta(days=i + 1)).isoformat() for i in range(w)]


def load_archive(paths):
    """Read download_report_archive output (one or more files). Returns
    {"asOf", "days", "firstDay", "lastDay", "expected", "gaps", "covered", "overlap", "tables"} or None.
    Users, org units, domains and groups come from the latest completed day (a snapshot). Activity (gw_daily, gw_events, gw_admin,
    gw_suspicious and the activity counts in gw_summary) is merged across every archived day: counts add, one row per day is kept once
    (the latest run wins), lists are unioned, distinct account counts are the peak day."""
    if isinstance(paths, str):
        paths = [paths]
    cands = []
    for path in paths or []:
        if not path or not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("days"), list):
            for d in data["days"]:
                res = d.get("result")
                ent = d.get("entry") or {}
                if res and (ent.get("state") in (None, "completed", "Completed", "complete", "done")):
                    cands.append((str(ent.get("rangeTo") or ""), str(ent.get("completedOn") or ""), res))
        elif isinstance(data, dict):
            cands.append(("", "", data.get("result") or data))
    runs = []
    for rng, done, res in cands:
        tb = _tables_of(res)
        if tb.get("gw_summary"):
            as_of, cov = _covered(tb, rng)
            runs.append({"rng": rng, "done": done, "tables": tb, "asOf": as_of, "cov": cov})
    if not runs:
        return None
    runs.sort(key=lambda r: (r["asOf"], r["rng"], r["done"]))
    latest = runs[-1]
    # keep a run unless every day it covers is already covered by a later run (the later run wins)
    kept, seen, overlap = [], set(), False
    for r in reversed(runs):
        new = [d for d in r["cov"] if d not in seen]
        if not new and r["cov"]:
            continue
        if len(new) != len(r["cov"]):
            overlap = True
        seen.update(r["cov"])
        kept.append(r)
    kept.reverse()
    covered = sorted(seen)
    first, last = (covered[0], covered[-1]) if covered else (latest["asOf"], latest["asOf"])
    expected = (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1 if covered else 1
    gaps = []
    if covered:
        d0 = dt.date.fromisoformat(first)
        gaps = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(expected) if (d0 + dt.timedelta(days=i)).isoformat() not in seen]

    tables = dict(latest["tables"])
    daily = {}
    for r in kept:                                  # later runs overwrite earlier ones for the same day
        for row in r["tables"].get("gw_daily", []):
            daily[day(row.get("day"))] = row
    ev = {}
    for r in kept:
        for row in r["tables"].get("gw_events", []):
            k = (row.get("app"), row.get("type"), row.get("name"))
            cur = ev.setdefault(k, {"app": k[0], "type": k[1], "name": k[2], "events": 0, "actors": 0})
            cur["events"] += n_of(row, "events")
            cur["actors"] = max(cur["actors"], n_of(row, "actors"))
    def union(name, keyf):
        out, have = [], set()
        for r in reversed(kept):
            for row in r["tables"].get(name, []):
                k = keyf(row)
                if k not in have:
                    have.add(k)
                    out.append(row)
        out.sort(key=lambda x: str(x.get("time") or ""), reverse=True)
        return out[:200]
    tables["gw_daily"] = [daily[k] for k in sorted(daily) if k]
    tables["gw_events"] = sorted(ev.values(), key=lambda x: -x["events"])[:200]
    tables["gw_admin"] = union("gw_admin", lambda x: (x.get("time"), x.get("actor"), x.get("name"), x.get("target")))
    tables["gw_suspicious"] = union("gw_suspicious", lambda x: (x.get("time"), x.get("user"), x.get("ip"), x.get("name")))
    summ = dict(latest["tables"]["gw_summary"][0])
    for key, col in ACTIVITY_SUM:
        summ[key] = sum(n_of(r, col) for r in tables["gw_daily"])
    summ["actors"] = max([n_of(r["tables"]["gw_summary"][0], "actors") for r in kept] or [0])
    summ["windowDays"] = len(covered) or 1
    tables["gw_summary"] = [summ]
    return {"asOf": latest["asOf"], "days": len(covered) or 1, "firstDay": first, "lastDay": last, "expected": expected, "gaps": gaps,
            "covered": covered, "overlap": overlap, "tables": tables}


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def n_of(r, k):
    try:
        return int(float(r.get(k) or 0))
    except (TypeError, ValueError):
        return 0


def f_of(r, k):
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def num(n):
    return "{:,}".format(int(n))


def sev(x):
    return ("%g" % x) if x == int(x) else ("%.1f" % x)


def day(s):
    s = str(s or "")
    return "" if s in ("", "null", "None") else s[:10]


def parse_ts(s):
    s = str(s or "")
    if s in ("", "null", "None"):
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None



# ---------------------------------------------------------------- check
def sources_down(arc):
    rows = arc["tables"].get("sources", [])
    names = ("gsuiteUser (summary)", "GSuite (per day)")
    seen = [r for r in rows if r.get("source") in names]
    return bool(seen) and all(r.get("status") != "ok" for r in seen)


def cmd_check(args):
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM  no completed day with a gw_summary table in the archive file(s): the report cannot run")
        return 1
    now = dt.datetime.now(dt.timezone.utc)
    s = arc["tables"]["gw_summary"][0]
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    level, note = "ok", ""
    if sources_down(arc):
        level, note = "PROBLEM", "the user table and the audit stream were both not available on the latest day (no Google Workspace import on the tenant)"
    elif age > MAX_AGE_DAYS:
        level, note = "PROBLEM", "latest archived day is %d days old" % age
    elif not n_of(s, "users") and not n_of(s, "events"):
        note = "no users and no audit events"
    print("%-8s %-32s asOf=%s days_in_file=%d of %d expected users=%s needs_action=%s admin_no_2sv=%s events=%s %s" % (level, REPORT, arc["asOf"], arc["days"], arc["expected"], s.get("users"), s.get("needsAction"), s.get("adminNo2sv"), s.get("events"), note))
    for r in [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]:
        print("         query not available: %s %s" % (r.get("source"), str(r.get("detail") or "")[:100]))
    if arc["gaps"]:
        print("         gap days (not archived, never counted as zero): %s" % ", ".join(arc["gaps"]))
    missing = [t for t in TABLES if t not in arc["tables"]]
    if missing:
        print("         tables absent (an older script version?): %s" % ", ".join(missing))
    return 1 if level == "PROBLEM" else 0


# ---------------------------------------------------------------- analysis
def yes(v):
    return str(v).lower() == "true"


def analyse(arc, now):
    tb = arc["tables"]
    s = tb["gw_summary"][0]
    as_of = dt.datetime.fromisoformat(arc["asOf"]).replace(tzinfo=dt.timezone.utc)
    window = n_of(s, "windowDays") or 1

    users = []
    for r in tb.get("gw_users", []):
        users.append({"email": r.get("email") or "", "name": r.get("name") or "", "orgUnit": r.get("orgUnit") or "/", "state": r.get("state") or "", "score": n_of(r, "score"),
                      "reasons": r.get("reasons") or "", "admin": "yes" if yes(r.get("admin")) else "no", "delegated": "yes" if yes(r.get("delegated")) else "no",
                      "suspended": "yes" if yes(r.get("suspended")) else "no", "archived": "yes" if yes(r.get("archived")) else "no",
                      "enrolled2sv": "yes" if yes(r.get("enrolled2sv")) else "no", "enforced2sv": "yes" if yes(r.get("enforced2sv")) else "no",
                      "recovery": "yes" if yes(r.get("recovery")) else "no", "external": "yes" if yes(r.get("external")) else "no", "created": day(r.get("created")),
                      "lastLogin": day(r.get("lastLogin")) or str(r.get("lastLogin") or ""), "daysSince": n_of(r, "daysSinceLogin")})
    order = {"Needs action": 0, "Watch": 1, "Healthy": 2, "Disabled": 3}
    users.sort(key=lambda u: (order.get(u["state"], 9), -u["score"], u["email"]))

    orgs = [{"orgUnit": r.get("orgUnit") or "/", "users": n_of(r, "users"), "admins": n_of(r, "admins"), "no2sv": n_of(r, "no2sv"), "stale90": n_of(r, "stale90"), "needsAction": n_of(r, "needsAction")} for r in tb.get("gw_orgunits", [])]
    domains = [{"domain": r.get("domain") or "", "users": n_of(r, "users"), "external": r.get("external") or "no"} for r in tb.get("gw_domains", [])]
    groups = [{"email": r.get("email") or "", "name": r.get("name") or "", "members": n_of(r, "members"), "adminCreated": r.get("adminCreated") or "", "aliases": n_of(r, "aliases")} for r in tb.get("gw_groups", [])]
    events = [{"app": r.get("app") or "", "type": r.get("type") or "", "name": r.get("name") or "", "events": n_of(r, "events"), "actors": n_of(r, "actors")} for r in tb.get("gw_events", [])]
    admin = [{"time": str(r.get("time") or "")[:19].replace("T", " "), "actor": r.get("actor") or "", "name": r.get("name") or "", "target": r.get("target") or "", "oldValue": r.get("oldValue") or "", "newValue": r.get("newValue") or ""} for r in tb.get("gw_admin", [])]
    susp = [{"time": str(r.get("time") or "")[:19].replace("T", " "), "user": r.get("user") or "", "ip": r.get("ip") or "", "country": r.get("country") or "", "name": r.get("name") or "", "loginType": r.get("loginType") or ""} for r in tb.get("gw_suspicious", [])]

    daily = [{"day": day(r.get("day")), "events": n_of(r, "events"), "logins": n_of(r, "logins"), "loginFailures": n_of(r, "loginFailures"), "suspicious": n_of(r, "suspicious"),
              "adminChanges": n_of(r, "adminChanges"), "tokenGrants": n_of(r, "tokenGrants"), "mobile": n_of(r, "mobile")} for r in tb.get("gw_daily", [])]

    keys = ["users", "active", "suspended", "archived", "admins", "delegatedAdmins", "enrolled2sv", "enforced2sv", "gap2sv", "adminNo2sv", "enforcedNotEnrolled", "neverSignedIn",
            "stale30", "stale90", "noRecovery", "external", "orgUnits", "needsAction", "watch", "healthy", "disabled", "groups", "groupMembers", "emptyGroups", "logins",
            "loginFailures", "suspiciousLogins", "adminChanges", "tokenGrants", "mobileEvents", "events", "actors"]
    summary = {k: n_of(s, k) for k in keys}
    summary.update({"windowDays": window, "topDomain": s.get("topDomain") or ""})
    listed = n_of(s, "listed")
    facts = {
        "account": "", "generated": now.isoformat(), "asOf": arc["asOf"], "archive": {"days": arc["days"], "expected": arc["expected"], "gaps": arc["gaps"], "firstDay": arc["firstDay"], "lastDay": arc["lastDay"]},
        "summary": summary,
        "status": {"needsAction": summary["needsAction"], "watch": summary["watch"], "healthy": summary["healthy"], "disabled": summary["disabled"],
                   "listed": len(users), "listedCap": n_of(s, "listedCap") or USERS_CAP, "truncated": len(users) < summary["users"]},
        "orgUnits": orgs, "domains": domains, "groups": groups, "events": events, "admin": admin, "suspicious": susp, "daily": daily,
    }
    return facts, users


# ---------------------------------------------------------------- narrative
def pl(n, w):
    return "%s %s%s" % (num(n), w, "" if n == 1 else "s")


def default_narrative(f):
    s, st = f["summary"], f["status"]
    if not s["users"]:
        return ["<p>The user directory held <strong>no users</strong> as of %s. %s audit events were recorded over %s archived.</p>" % (esc(f["asOf"]), num(s["events"]), pl(s["windowDays"], "day"))]
    cov = pct(s["enrolled2sv"], s["users"])
    s1 = ("<p>The Google Workspace directory holds <strong>%s</strong> (%s active, %s suspended or archived) in %s. <strong>%s need action</strong> and %s are worth watching. "
          "<strong>%s of %s users (%s%%) are enrolled in 2-Step Verification</strong>; %s active user%s %s not, and <strong>%s admin%s without it</strong>.</p>"
          % (pl(s["users"], "user"), num(s["active"]), num(s["suspended"] + s["archived"]), pl(s["orgUnits"], "org unit"), num(st["needsAction"]), num(st["watch"]),
             num(s["enrolled2sv"]), num(s["users"]), cov, num(s["gap2sv"]), "" if s["gap2sv"] == 1 else "s", "is" if s["gap2sv"] == 1 else "are", num(s["adminNo2sv"]), "" if s["adminNo2sv"] == 1 else "s"))
    s2 = ("<p>%s hold an admin role (%s delegated). Among active users, <strong>%s have not signed in for more than 90 days</strong> (%s for more than 30), %s never signed in and %s have no recovery email or phone%s.</p>"
          % (pl(s["admins"], "user"), num(s["delegatedAdmins"]), num(s["stale90"]), num(s["stale30"]), num(s["neverSignedIn"]), num(s["noRecovery"]),
             ("; %s use%s an address outside %s" % (num(s["external"]), "s" if s["external"] == 1 else "", esc(s["topDomain"]))) if s["external"] else ""))
    s3 = ("<p>Over the %s archived (to %s) the audit log recorded <strong>%s events</strong> from %s: %s successful and %s failed sign-ins, <strong>%s flagged as suspicious</strong>, %s admin change%s and %s app authorizations. "
          "The directory has %s with %s direct members.</p>"
          % (pl(s["windowDays"], "day"), esc(f["asOf"]), num(s["events"]), pl(s["actors"], "account"), num(s["logins"]), num(s["loginFailures"]), num(s["suspiciousLogins"]), num(s["adminChanges"]),
             "" if s["adminChanges"] == 1 else "s", num(s["tokenGrants"]), pl(s["groups"], "group"), num(s["groupMembers"])))
    return [s1, s2, s3]


def default_steps(f):
    s = f["summary"]
    out = []
    if s["adminNo2sv"]:
        out.append({"when": "This week", "tone": "urgent", "text": "Enroll the %d admin%s without 2-Step Verification, or enforce it for the admin org unit. Admin accounts are the highest value target." % (s["adminNo2sv"], "" if s["adminNo2sv"] == 1 else "s")})
    if s["suspiciousLogins"]:
        out.append({"when": "This week", "tone": "urgent", "text": "Review the %d sign-in%s Google flagged as suspicious (listed in the report) and confirm each with the user." % (s["suspiciousLogins"], "" if s["suspiciousLogins"] == 1 else "s")})
    if s["gap2sv"] - s["adminNo2sv"] > 0:
        out.append({"when": "Within 14 days", "tone": "normal", "text": "Enroll the other %d user%s without 2-Step Verification and turn on enforcement for the org units that are not covered." % (s["gap2sv"] - s["adminNo2sv"], "" if s["gap2sv"] - s["adminNo2sv"] == 1 else "s")})
    if s["stale90"] or s["neverSignedIn"]:
        out.append({"when": "Within 30 days", "tone": "normal", "text": "Review the %d account%s with no sign-in for 90 days or more and the %d that never signed in; suspend or archive those no longer needed." % (s["stale90"], "" if s["stale90"] == 1 else "s", s["neverSignedIn"])})
    if s["noRecovery"]:
        out.append({"when": "Within 30 days", "tone": "normal", "text": "Ask the %d user%s without a recovery email or phone to add one so account recovery does not depend on an admin." % (s["noRecovery"], "" if s["noRecovery"] == 1 else "s")})
    if s["external"]:
        out.append({"when": "Within 30 days", "tone": "normal", "text": "Confirm the %d account%s outside the main domain %s are expected." % (s["external"], "" if s["external"] == 1 else "s", s["topDomain"])})
    out.append({"when": "Quarterly", "tone": "routine", "text": "Repeat this review and compare 2-Step Verification coverage, stale accounts and admin changes with the previous quarter."})
    return out[:6]


# ---------------------------------------------------------------- html helpers
def panel(title, body, cols=6, sub="", cls=""):
    return ('<div class="panel col-%d %s"><div class="panel-header"><h3 class="panel-title">%s</h3>%s</div>%s</div>'
            % (cols, cls, esc(title), '<span class="panel-subtitle">%s</span>' % esc(sub) if sub else "", body))


def bars(items, total=None, color="var(--blue)", empty="No data."):
    items = [i for i in items if i["count"]]
    if not items:
        return '<p class="panel-subtitle">%s</p>' % esc(empty)
    col = fb.semantic_color(color)
    rows = []
    for i in items:
        name = str(i["name"])
        label = name if len(name) <= 44 else name[:41] + "..."
        rows.append((label, i["count"], i.get("color") or col, fb._fmt(i["count"]) + ((" · %s%%" % pct(i["count"], total)) if total else "")))
    return fb.bar_rows(rows)


def table(headers, rows, widths=None, cls="data"):
    cg = "<colgroup>%s</colgroup>" % "".join('<col style="width:%s">' % w for w in widths) if widths else ""
    th = "".join("<th>%s</th>" % esc(h) for h in headers)
    body = "".join("<tr%s>%s</tr>" % (' class="%s"' % r[1] if isinstance(r, tuple) and r[1] else "", "".join(r[0] if isinstance(r, tuple) else r)) for r in rows)
    return '<table class="%s">%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, cg, th, body)


def td(x, wrap=False):
    return '<td%s>%s</td>' % (' class="wrap"' if wrap else "", esc(x))


def tdn(x):
    return '<td class="num">%s</td>' % (num(x) if isinstance(x, int) else esc(x))


def chip(text, color):
    return '<span class="st"><i style="background:%s"></i>%s</span>' % (color, esc(text))


def kpi(label, value, color, note=""):
    return ('<div class="kpi"><div class="kpi-value %s">%s</div><div class="kpi-label">%s</div>%s</div>'
            % (color, esc(value), esc(label), '<div class="kpi-note">%s</div>' % esc(note) if note else ""))


def daily_chart(daily):
    return fb.column_chart([d["day"][5:] for d in daily],
                           [("Successful", [d["logins"] for d in daily]), ("Failed", [d["loginFailures"] for d in daily])],
                           mode="stack", colors=["#175d9a", "#b3242e"], height=200, y_label="Sign-ins per day")


# ---------------------------------------------------------------- render
def coverage_notes(arc, f, now):
    notes = []
    age = (now.date() - dt.date.fromisoformat(arc["asOf"])).days
    notes.append("Built from the archived %s: %d day%s archived out of %d from %s to %s. Users, groups and scores are the directory on %s (the latest day); audit activity is added across the archived days."
                 % (REPORT, arc["days"], "" if arc["days"] == 1 else "s", arc["expected"], arc["firstDay"] or "?", arc["lastDay"] or "?", arc["asOf"]))
    if arc["gaps"]:
        notes.append("No archive for %s. Those days are gaps, not zeros, so the activity totals are lower bounds for the period." % ", ".join(arc["gaps"]))
    if arc["overlap"]:
        notes.append("Some archived runs overlap. Daily counts keep each day once, but event type counts may include the overlapping days twice.")
    if age > MAX_AGE_DAYS:
        notes.append("The latest archived day is %d days old, so these figures are not current. Check the scheduled report." % age)
    st, s = f["status"], f["summary"]
    notes.append("Users and groups are a snapshot, never added across days. Audit counts (sign-ins, admin changes, app authorizations) are summed over the %d archived day%s; accounts is the busiest single day, and the event, admin and suspicious sign-in lists are lower bounds (top rows per day)." % (s["windowDays"], "" if s["windowDays"] == 1 else "s"))
    if st["truncated"]:
        notes.append("The archive lists the first %d of %d users (needing attention first), so the user table and users.csv are cut. The counts cover every user." % (st["listed"], s["users"]))
    notes.append("Suspended and archived users are shown as Disabled with score 0 and are left out of the 2-Step Verification gap, stale and recovery counts.")
    notes.append("A missing 2-Step Verification, suspended or archived flag on a user record is read as false.")
    bad = [r for r in arc["tables"].get("sources", []) if r.get("status") != "ok"]
    if bad:
        notes.append("These queries did not run on the archived day and their panels are empty: %s." % ", ".join(str(r.get("source")) for r in bad))
    notes.append("Not in the archive, so not shown: group member lists, mail and Drive content, and event detail beyond the admin change and suspicious sign-in lists.")
    return notes


def cmd_render(args):
    now = dt.datetime.now(dt.timezone.utc)
    arc = load_archive(args.archive)
    if not arc:
        print("PROBLEM: no completed archived day with a gw_summary table; nothing to report", file=sys.stderr)
        return 1
    if sources_down(arc):
        print("PROBLEM: the user table and the audit stream were both not available on the archived day; nothing to report", file=sys.stderr)
        return 1
    f, users = analyse(arc, now)
    f["account"] = args.account
    s, st = f["summary"], f["status"]
    notes = coverage_notes(arc, f, now)
    f["notes"] = notes
    os.makedirs(args.work, exist_ok=True)

    narr_path = os.path.join(args.work, "narrative.json")
    narr = json.load(open(narr_path)) if os.path.exists(narr_path) else {}
    summary = narr.get("summary") or default_narrative(f)
    steps = narr.get("nextSteps") or default_steps(f)
    f["narrative"] = {"summary": summary, "nextSteps": steps, "custom": bool(narr)}

    kp = [
        kpi("Users", num(s["users"]), "navy", "%s active, %s disabled" % (num(s["active"]), num(s["disabled"]))),
        kpi("Need action", num(st["needsAction"]), "red" if st["needsAction"] else "green", "%s more on watch" % num(st["watch"])),
        kpi("Admins without 2SV", num(s["adminNo2sv"]), "red" if s["adminNo2sv"] else "green", "%s admin%s in total" % (num(s["admins"]), "" if s["admins"] == 1 else "s")),
        kpi("2-Step Verification", "%s%%" % pct(s["enrolled2sv"], s["users"]), "green" if s["users"] and s["gap2sv"] == 0 else "amber", "%s active user%s not enrolled" % (num(s["gap2sv"]), "" if s["gap2sv"] == 1 else "s")),
        kpi("No sign-in 90 days", num(s["stale90"]), "amber" if s["stale90"] else "green", "%s never signed in" % num(s["neverSignedIn"])),
        kpi("Suspicious sign-ins", num(s["suspiciousLogins"]), "red" if s["suspiciousLogins"] else "green", "%s failed of %s sign-ins" % (num(s["loginFailures"]), num(s["logins"] + s["loginFailures"]))),
    ]

    g = []
    total = s["users"] or 1
    parts = [{"name": k, "count": v, "color": STATE_COLOR[k]} for k, v in (("Needs action", st["needsAction"]), ("Watch", st["watch"]), ("Healthy", st["healthy"]), ("Disabled", st["disabled"]))]
    stack = '<div class="stack">%s</div>' % "".join('<div class="seg" style="width:%.2f%%;background:%s" title="%s: %d"></div>' % (100.0 * x["count"] / total, x["color"], x["name"], x["count"]) for x in parts if x["count"])
    legend = '<div class="legend" style="margin-top:10px">%s</div>' % "".join('<span class="lg"><i style="background:%s"></i>%s: %s</span>' % (x["color"], x["name"], num(x["count"])) for x in parts)
    g.append(panel("Account health", stack + legend, 6, "%s users; score rules in How to read this report" % num(s["users"])))
    twosv = [{"name": "Enrolled", "count": s["enrolled2sv"], "color": "#175d9a"}, {"name": "Not enrolled (active)", "count": s["gap2sv"], "color": "#b3242e"},
             {"name": "Admins not enrolled", "count": s["adminNo2sv"], "color": "#b3242e"}, {"name": "Enforced, not enrolled", "count": s["enforcedNotEnrolled"], "color": "#a06c00"}]
    g.append(panel("2-Step Verification", bars(twosv, s["users"] or None, empty="No users."), 6, "share of all users"))
    rec = [{"name": "No sign-in over 90 days", "count": s["stale90"], "color": "#b3242e"}, {"name": "No sign-in over 30 days", "count": s["stale30"], "color": "#a06c00"},
           {"name": "Never signed in", "count": s["neverSignedIn"], "color": "#a06c00"}, {"name": "No recovery email or phone", "count": s["noRecovery"], "color": "#a06c00"},
           {"name": "Outside the main domain", "count": s["external"], "color": "#175d9a"}]
    g.append(panel("Hygiene", bars(rec, s["active"] or None, empty="Nothing to flag."), 6, "active users; over 30 days includes over 90"))
    ou = [[td(o["orgUnit"]), tdn(o["users"]), tdn(o["admins"]), tdn(o["no2sv"]), tdn(o["stale90"]), tdn(o["needsAction"])] for o in f["orgUnits"][:8]]
    g.append(panel("Org units", table(["Org unit", "Users", "Admins", "No 2SV", "Stale 90d", "Need action"], ou, ["34%", "13%", "14%", "13%", "13%", "13%"]) if ou else '<p class="panel-subtitle">None.</p>', 6, "%s org unit%s, top 8 by users needing action" % (num(s["orgUnits"]), "" if s["orgUnits"] == 1 else "s")))
    if any(d["logins"] or d["loginFailures"] for d in f["daily"]):
        lg = '<div class="legend"><span class="lg"><i style="background:#175d9a"></i>Successful</span><span class="lg"><i style="background:#b3242e"></i>Failed</span></div>'
        g.append(panel("Sign-ins per day", lg + daily_chart(f["daily"]), 12, "%d archived day%s, UTC; %s successful, %s failed, %s suspicious" % (s["windowDays"], "" if s["windowDays"] == 1 else "s", num(s["logins"]), num(s["loginFailures"]), num(s["suspiciousLogins"]))))
    ev = [[td(e["app"]), td(e["name"], True), tdn(e["events"]), tdn(e["actors"])] for e in f["events"][:10]]
    g.append(panel("Audit activity", table(["Application", "Event", "Events", "Accounts"], ev, ["20%", "46%", "17%", "17%"]) if ev else '<p class="panel-subtitle">No audit events in the period.</p>', 6, "%s events, top 10 by count" % num(s["events"])))
    ad = [[td(a["time"]), td(a["actor"], True), td(a["name"], True), td(a["target"], True)] for a in f["admin"][:8]]
    g.append(panel("Admin changes", table(["Time (UTC)", "By", "Change", "Target"], ad, ["24%", "28%", "30%", "18%"]) if ad else '<p class="panel-subtitle">No admin changes in the period.</p>', 6, "latest 8 of %s" % num(s["adminChanges"])))
    sp = [[td(x["time"]), td(x["user"], True), td(x["country"]), td(x["loginType"])] for x in f["suspicious"][:8]]
    g.append(panel("Suspicious sign-ins", table(["Time (UTC)", "User", "Country", "Type"], sp, ["28%", "38%", "20%", "14%"]) if sp else '<p class="panel-subtitle">No sign-in was flagged as suspicious.</p>', 6, "flagged by Google, latest 8 of %s" % num(s["suspiciousLogins"])))
    gr = [[td(x["email"], True), td(x["name"], True), tdn(x["members"])] for x in f["groups"][:8]]
    g.append(panel("Groups", table(["Group", "Name", "Members"], gr, ["46%", "34%", "20%"]) if gr else '<p class="panel-subtitle">No groups.</p>', 6, "%s group%s, %s empty" % (num(s["groups"]), "" if s["groups"] == 1 else "s", num(s["emptyGroups"]))))

    cap = args.max_listed
    shown = [u for u in users if u["state"] in ("Needs action", "Watch")]
    rows = [([td(u["email"], True), td(u["orgUnit"]), '<td>%s</td>' % chip(u["state"], STATE_COLOR.get(u["state"], "#8a8a8a")), tdn(u["score"]), td(u["lastLogin"]), td(u["reasons"], True)], "") for u in shown[:cap]]
    note = "" if len(shown) <= cap else " (first %d of %d; the CSV has all)" % (cap, len(shown))
    app = [panel("Users needing attention", table(["User", "Org unit", "Status", "Score", "Last sign-in", "Why"], rows, ["26%", "11%", "12%", "7%", "12%", "32%"], "data devlist") if rows
                 else '<p class="panel-subtitle">No user needs attention.</p>', 12, "%d of %s%s" % (min(len(shown), cap), num(st["needsAction"] + st["watch"]), note), "page-break")]
    method = ('<div class="method">'
              '<div><b>Source.</b> The archived daily run of the scheduled report %s for %s. Each run covers one day. Users and groups are the snapshot from the latest completed day; the audit counts are added across the %d archived days.</div>'
              '<div><b>User score.</b> Higher is worse, for a user who is not suspended or archived: admin or delegated admin without 2-Step Verification enrolled 3; enforced but not enrolled 2; not enrolled and not enforced 1; no sign-in for more than 90 days 2 (more than 30 days 1); never signed in, account older than 30 days, 2; no recovery email or phone 1; address outside the main domain 1.</div>'
              '<div><b>Status.</b> 3 or more is Needs action, 1 to 2 is Watch, 0 is Healthy. Suspended and archived users are Disabled with score 0.</div>'
              '<div><b>Main domain.</b> The email domain most users have (%s). Other domains count as outside the main domain.</div>'
              '<div><b>Sign-ins.</b> Google login events: successful, failed, and those Google flags as suspicious. Admin changes are admin console events other than alert views; app authorizations are OAuth token grants.</div></div>'
              % (REPORT, esc(f["asOf"]), s["windowDays"], esc(s["topDomain"])))
    app.append(panel("How to read this report", method, 12))
    app.append(panel("Data notes", '<div class="method">%s</div>' % "".join("<div>%s</div>" % esc(x) for x in notes), 12))

    ns = "".join('<div class="ns-item" style="border-left-color:%s"><div class="ns-num">%d</div><div><div class="ns-when">%s</div><div class="ns-act">%s</div></div></div>'
                 % ({"urgent": "var(--red)", "normal": "var(--blue)"}.get(x.get("tone"), "var(--navy)"), i + 1, esc(x.get("when", "")), esc(x.get("text", ""))) for i, x in enumerate(steps))

    subtitle = args.customer or args.account
    tpl = open(os.path.join(ASSETS, "report_template.html"), encoding="utf-8").read()
    page = {
        "report_title": "Google Workspace Resource Report", "report_subtitle": subtitle,
        "report_date": now.strftime("%Y-%m-%d"), "report_meta": " · account <strong>%s</strong> · as of <strong>%s</strong>" % (esc(args.account), esc(f["asOf"])),
        "kpi_strip": "".join(kp), "summary_html": "".join(summary), "main_grid": "".join(g),
        "next_steps_items": ns, "appendix": "".join(app),
        "footer_page_info": "Google Workspace resource report · %s" % esc(subtitle), "footer_data_date": esc(f["asOf"]),
    }
    for k, val in page.items():
        tpl = tpl.replace("{{%s}}" % k, val)
    with open(os.path.join(args.work, "googleworkspace_resource_report.html"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    os.makedirs(os.path.join(args.work, "assets"), exist_ok=True)
    shutil.copy(os.path.join(ASSETS, "logo2.png"), os.path.join(args.work, "assets", "logo2.png"))

    def out_csv(name, header, rows_):
        with open(os.path.join(args.work, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header + ["as_of"])
            for r in rows_:
                w.writerow(list(r) + [f["asOf"]])

    out_csv("users.csv", ["email", "name", "org_unit", "state", "score", "reasons", "admin", "delegated_admin", "suspended", "archived", "enrolled_2sv", "enforced_2sv", "recovery_info",
                          "outside_main_domain", "created", "last_sign_in", "days_since_sign_in"],
            [[u["email"], u["name"], u["orgUnit"], u["state"], u["score"], u["reasons"], u["admin"], u["delegated"], u["suspended"], u["archived"], u["enrolled2sv"], u["enforced2sv"],
              u["recovery"], u["external"], u["created"], u["lastLogin"], u["daysSince"]] for u in users])
    out_csv("groups.csv", ["group", "name", "direct_members", "admin_created", "aliases"], [[x["email"], x["name"], x["members"], x["adminCreated"], x["aliases"]] for x in f["groups"]])
    out_csv("daily.csv", ["day", "events", "successful_sign_ins", "failed_sign_ins", "suspicious_sign_ins", "admin_changes", "app_authorizations", "mobile_events"],
            [[d["day"], d["events"], d["logins"], d["loginFailures"], d["suspicious"], d["adminChanges"], d["tokenGrants"], d["mobile"]] for d in f["daily"]])
    with open(os.path.join(args.work, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    build_interactive(os.path.join(args.work, "googleworkspace_resource_report_interactive.html"), args, f, users, arc, notes)

    print("as of %s | users %s (active %d, disabled %d), groups %s, events %s in %d days" % (f["asOf"], num(s["users"]), s["active"], s["disabled"], num(s["groups"]), num(s["events"]), s["windowDays"]))
    print("needs action %d, watch %d, healthy %d, disabled %d (user table lists %d)" % (st["needsAction"], st["watch"], st["healthy"], st["disabled"], st["listed"]))
    print("admins %d (no 2SV %d) | 2SV enrolled %d, gap %d | stale 90d %d, never %d, no recovery %d | sign-ins ok %d failed %d suspicious %d | admin changes %d" % (s["admins"], s["adminNo2sv"], s["enrolled2sv"], s["gap2sv"], s["stale90"], s["neverSignedIn"], s["noRecovery"], s["logins"], s["loginFailures"], s["suspiciousLogins"], s["adminChanges"]))
    print("wrote: googleworkspace_resource_report.html, googleworkspace_resource_report_interactive.html, users.csv, groups.csv, daily.csv, facts.json in %s" % args.work)
    return 0


def build_interactive(path, args, f, users, arc, notes):
    """One self-contained interactive HTML file: tabs, search, sort, filters, CSV export, dark mode."""
    srcs = [{"source": r.get("source"), "status": r.get("status"), "detail": str(r.get("detail") or "")[:160]} for r in arc["tables"].get("sources", [])]
    method = [
        "Source: the archived daily runs of the scheduled report %s (%d of %d days). Users and groups are the snapshot from the latest day (%s); audit activity is added across the archived days." % (REPORT, f["archive"]["days"], f["archive"]["expected"], f["asOf"]),
        "Missing days are gaps, never zeros. Audit counts are sums over the archived days; accounts is the peak day.",
        "User score (not suspended or archived): admin or delegated admin without 2-Step Verification 3; enforced but not enrolled 2; not enrolled and not enforced 1; no sign-in over 90 days 2 (over 30 days 1); never signed in with an account older than 30 days 2; no recovery email or phone 1; address outside the main domain 1.",
        "Status: 3 or more Needs action, 1 to 2 Watch, 0 Healthy. Suspended and archived users are Disabled with score 0 and are left out of the gap, stale and recovery counts.",
        "Main domain: the email domain most users have (%s); others count as outside the main domain." % f["summary"]["topDomain"],
        "Admin changes are admin console events other than alert views; app authorizations are OAuth token grants; suspicious sign-ins are the logins Google flags.",
    ]
    data = {"title": "Google Workspace Resource Report", "account": args.account, "customer": args.customer, "snapshot": f["asOf"], "summary": f["summary"], "status": f["status"],
            "users": users, "orgUnits": f["orgUnits"], "domains": f["domains"], "groups": f["groups"], "events": f["events"], "admin": f["admin"], "suspicious": f["suspicious"],
            "daily": f["daily"], "sources": srcs, "notes": notes, "method": method}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    tpl = open(os.path.join(ASSETS, "interactive_template.html"), encoding="utf-8").read()
    tpl = tpl.replace("{{title}}", esc((args.customer or args.account) + " Google Workspace Resource Report")).replace("{{data}}", blob)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r = sub.add_parser("render"); r.add_argument("--archive", nargs="+", required=True, help="download_report_archive JSON file(s) of %s" % REPORT)
    r.add_argument("--work", required=True)
    r.add_argument("--account", required=True); r.add_argument("--customer", default="")
    r.add_argument("--max-listed", type=int, default=20)
    args = ap.parse_args()
    sys.exit(cmd_check(args) if args.cmd == "check" else cmd_render(args))


if __name__ == "__main__":
    main()
