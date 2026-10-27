#!/usr/bin/env python3
"""Render the Office365 / Entra resource-posture review (HTML + CSV) from saved resource dumps.

Three areas, computed locally from the tenant's Office 365 resource dumps (no FPL report, no event query):
users (office365User), applications (office365Application), devices (office365Device).

  build_report.py --evidence-dir DIR --out posture.html [--csv findings.csv] --tenant NAME --site Develop [--as-of ISO]

Layout of DIR (one set per Office 365 feed, a feed being one customer name in list_resource_dumps):
  resources.json                       optional, the list_resource_dumps result for the account
  users__<customer>.jsonl.gz           office365User dump
  apps__<customer>.jsonl.gz            office365Application dump
  devices__<customer>.jsonl.gz         office365Device dump
Each feed is assessed on its own and never summed with another feed. A dump that resources.json lists but
whose file is missing is "not collected"; a resource with no dump at all is "no dump"; neither is a clean result.

Rules (ported from the three local posture reports; thresholds are constants below)
  users (enabled accounts only)   privileged role; weak MFA (EMAIL or MOBILE_PHONE registered); OAuth apps connected;
                                  refresh or sign-in token baseline older than 365 days; passwordPolicies is exactly None
  applications                    http:// redirect URI; implicit grant; http:// homepage; no verified publisher;
                                  no secrets or certificates; older than 730 days with implicit grant or http redirect
  devices (enabled only)          no sign-in for 90 days or none recorded; Workplace trust; unmanaged; non-compliant;
                                  rooted; hybrid sync older than 30 days; no username
"""
import argparse, collections, csv, datetime, glob, gzip, html, json, os, re, sys

E = html.escape
NAVY, RED, AMB, GRN, GRY = "#1C2B45", "#B91C1C", "#B45309", "#15803D", "#64748B"
PRIV_ROLES = {"Global Administrator", "Company Administrator", "Security Administrator", "Privileged Role Administrator",
              "User Administrator", "Exchange Administrator", "SharePoint Service Administrator"}
WEAK_FACTORS = {"email", "mobilephone"}   # compared lower-case with underscores removed: dumps carry mobilePhone, the old report MOBILE_PHONE
TOKEN_DAYS, APP_AGE_DAYS, STALE_SIGNIN_DAYS, STALE_SYNC_DAYS = 365, 730, 90, 30
SEV = {"Critical": RED, "High": RED, "Medium": AMB, "Low": GRY}
SHOW = 12   # rows shown per table in the HTML; the CSV holds every row


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


def parse_iso(t):
    try:
        d = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(t).replace("Z", "+00:00")))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def days(t, now):
    d = parse_iso(t) if t else None
    return None if d is None else (now - d).total_seconds() / 86400.0


def alist(v):
    return v if isinstance(v, list) else []


def redirect_uris(a):
    out = []
    web, spa, pub = a.get("web") or {}, a.get("spa") or {}, a.get("publicClient") or {}
    out += [u for u in alist(web.get("redirectUris")) if u]
    out += [o.get("uri") for o in alist(web.get("redirectUriSettings")) if isinstance(o, dict) and o.get("uri")]
    out += [u for u in alist(spa.get("redirectUris")) if u]
    out += [u for u in alist(pub.get("redirectUris")) if u]
    return out


def has_http(uris):
    return any(str(u).startswith("http://") for u in uris)


def implicit(a):
    s = (a.get("web") or {}).get("implicitGrantSettings") or {}
    return bool(s.get("enableAccessTokenIssuance") or s.get("enableIdTokenIssuance"))


# issue -> (severity, label, why it matters)
ISSUES = {
    "priv": ("High", "Privileged roles", "Administrators should be 2 or fewer, plus 1 per 500 employees"),
    "weakmfa": ("Medium", "Weak MFA factors (email or SMS)", "Phishable factors registered"),
    "oauth": ("Medium", "Third-party OAuth apps connected", "Consent review queue, not proof of abuse"),
    "token": ("Medium", "Token baseline older than 365 days", "Session hygiene; re-baseline stale tokens"),
    "pwnone": ("Low", "Password policy set to None", "Validate service or federated accounts"),
    "http": ("High", "HTTP redirect URI", "Transport security: use HTTPS or retire the app"),
    "implicit": ("High", "Implicit grant enabled", "Prefer authorization code with PKCE"),
    "nontls": ("Medium", "HTTP homepage URL", "Transport security"),
    "nopub": ("Medium", "No verified publisher", "Trust review for user-facing or third-party apps"),
    "nocred": ("Low", "No secrets or certificates", "Cleanup candidate, confirm it is unused"),
    "oldrisk": ("Critical", "Older than 730 days with implicit grant or HTTP redirect", "Age and risky settings compound"),
    "stale": ("Low", "No sign-in for 90 days (or none recorded)", "Cleanup candidate"),
    "workplace": ("Medium", "Workplace trust type", "Not Entra joined; weaker policy enforcement"),
    "unmanaged": ("High", "Unmanaged device", "MDM management disabled or unknown"),
    "noncomp": ("High", "Non-compliant device", "Failing compliance policy"),
    "rooted": ("Critical", "Rooted or jailbroken device", "Investigate first"),
    "sync": ("Medium", "Hybrid sync older than 30 days", "Verify hybrid join and sync"),
    "nouser": ("Low", "No username attributed", "Weakens investigation quality"),
}
AREAS = (("users", ("priv", "weakmfa", "oauth", "token", "pwnone")),
         ("applications", ("http", "implicit", "nontls", "nopub", "nocred", "oldrisk")),
         ("devices", ("rooted", "noncomp", "unmanaged", "workplace", "sync", "stale", "nouser")))


def assess_users(recs, now):
    out = collections.defaultdict(list)
    for r in recs:
        if not r.get("accountEnabled"):
            continue
        name, upn = r.get("displayName") or "", r.get("userPrincipalName") or ""
        roles = alist(r.get("roles"))
        methods = [str(m).lower().replace("_", "") for m in alist((r.get("userRegistration") or {}).get("authMethods"))]
        oauth = alist(r.get("oauth2Applications"))
        rd, sd = days(r.get("refreshTokensValidFromDateTime"), now), days(r.get("signInSessionsValidFromDateTime"), now)
        if PRIV_ROLES & set(roles):
            out["priv"].append((upn, name, ", ".join(roles[:3])))
        if WEAK_FACTORS & set(methods):
            out["weakmfa"].append((upn, name, ", ".join(sorted(WEAK_FACTORS & set(methods)))))
        if oauth:
            out["oauth"].append((upn, name, "%d app(s)" % len(oauth)))
        if (rd is not None and rd > TOKEN_DAYS) or (sd is not None and sd > TOKEN_DAYS):
            out["token"].append((upn, name, "%d days" % max(x for x in (rd, sd) if x is not None)))
        if r.get("passwordPolicies") == "None":
            out["pwnone"].append((upn, name, "None"))
    en = [r for r in recs if r.get("accountEnabled")]
    out["_na"] = {k: v for k, v in (
        ("priv", not any("roles" in r for r in en)),
        ("weakmfa", not any((r.get("userRegistration") or {}).get("authMethods") is not None for r in en)),
        ("token", not any("refreshTokensValidFromDateTime" in r or "signInSessionsValidFromDateTime" in r for r in en)),
        ("oauth", not any("oauth2Applications" in r for r in en)),
        ("pwnone", not any("passwordPolicies" in r for r in en))) if v}
    return out, len(en)


def assess_apps(recs, now):
    out = collections.defaultdict(list)
    for a in recs:
        name, aid = a.get("displayName") or "", a.get("appId") or ""
        uris = redirect_uris(a)
        age = days(a.get("createdDateTime"), now)
        http, imp = has_http(uris), implicit(a)
        if http:
            out["http"].append((aid, name, next(u for u in uris if str(u).startswith("http://"))))
        if imp:
            out["implicit"].append((aid, name, "implicit grant"))
        if str((a.get("web") or {}).get("homePageUrl") or "").startswith("http://"):
            out["nontls"].append((aid, name, a["web"]["homePageUrl"]))
        vp = a.get("verifiedPublisher") or {}
        if not (vp.get("verifiedPublisherId") or vp.get("displayName")):   # the dump carries an empty object when unverified
            out["nopub"].append((aid, name, a.get("publisherDomain") or ""))
        if not alist(a.get("passwordCredentials")) and not alist(a.get("keyCredentials")):
            out["nocred"].append((aid, name, "created %s" % (a.get("createdDateTime") or "n/a")[:10]))
        if age is not None and age > APP_AGE_DAYS and (imp or http):
            out["oldrisk"].append((aid, name, "%d days; %s" % (age, "implicit grant" if imp else "http redirect")))
    return out, len(recs)


def assess_devices(recs, now):
    out = collections.defaultdict(list)
    en = [d for d in recs if d.get("accountEnabled")]
    for d in en:
        name, did = d.get("displayName") or "", d.get("deviceId") or ""
        os_ = ("%s %s" % (d.get("operatingSystem") or "", d.get("operatingSystemVersion") or "")).strip()
        last = d.get("approximateLastSignInDateTime")
        dd = days(last, now)
        if not last or (dd is not None and dd > STALE_SIGNIN_DAYS):
            out["stale"].append((did, name, "no sign-in recorded" if not last else "%d days; %s" % (dd, os_)))
        if d.get("trustType") == "Workplace":
            out["workplace"].append((did, name, os_))
        if not d.get("isManaged"):
            out["unmanaged"].append((did, name, os_))
        if d.get("isCompliant") is False:
            out["noncomp"].append((did, name, os_))
        if d.get("isRooted") is True:
            out["rooted"].append((did, name, os_))
        sd = days(d.get("onPremisesLastSyncDateTime"), now)
        if d.get("onPremisesSyncEnabled") and sd is not None and sd > STALE_SYNC_DAYS:
            out["sync"].append((did, name, "%d days" % sd))
        if d.get("username") in (None, "", "None"):
            out["nouser"].append((did, name, os_))
    return out, len(en)


def feeds(ev_dir):
    """feed (customer) -> {area: path}"""
    out = collections.defaultdict(dict)
    for prefix, area in (("users", "users"), ("apps", "applications"), ("devices", "devices")):
        for fp in sorted(glob.glob(os.path.join(ev_dir, prefix + "__*.jsonl.gz"))):
            cust = os.path.basename(fp)[len(prefix) + 2:-len(".jsonl.gz")]
            out[cust][area] = fp
    return out


def listed(ev_dir):
    res = load(os.path.join(ev_dir, "resources.json")) or {}
    out = collections.defaultdict(dict)
    for e in res.get("entries", []):
        key = {"office365User": "users", "office365Application": "applications", "office365Device": "devices"}.get(e.get("resource"))
        if key:
            out[e.get("customer")][key] = e
    return out


def pill(t, c):
    return '<span style="background:%s;color:#fff;border-radius:3px;padding:1px 7px;font-size:11px">%s</span>' % (c, E(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--tenant", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--as-of")
    a = ap.parse_args()
    now = parse_iso(a.as_of) if a.as_of else datetime.datetime.now(datetime.timezone.utc)
    fd, ls = feeds(a.evidence_dir), listed(a.evidence_dir)
    names = sorted(set(fd) | set(ls))
    if not names:
        sys.exit("no users__*, apps__* or devices__* dump files and no resources.json in %s" % a.evidence_dir)
    warns, csv_rows, body = [], [], []
    for cust in names:
        body.append("<h2>Feed: %s</h2>" % E(cust))
        for area, issues in AREAS:
            path, meta = fd.get(cust, {}).get(area), ls.get(cust, {}).get(area)
            body.append("<h3>%s</h3>" % area.capitalize())
            if path is None:
                body.append("<p class='muted'><b>%s.</b> %s</p>" % (
                    "Not collected" if meta else "No dump",
                    "The dump is listed (%s records) but was not downloaded; no result is shown." % meta.get("count") if meta else
                    "This feed has no %s dump, so this area is not assessed. That is a coverage gap, not a clean result." % area))
                continue
            key = {"users": "office365User", "applications": "office365Application", "devices": "office365Device"}[area]
            recs = records(path, key)
            if meta and meta.get("count") != len(recs):
                warns.append("%s %s: file holds %d records but list_resource_dumps reported %s (truncated download?)" % (cust, area, len(recs), meta.get("count")))
            fn = {"users": assess_users, "applications": assess_apps, "devices": assess_devices}[area]
            res, base = fn(recs, now)
            snap = (meta or {}).get("createdOn", "")[:16].replace("T", " ")
            body.append("<p class='muted'>%d %s assessed (%d records in the dump)%s.</p>" % (base, "enabled " + area if area != "applications" else "applications", len(recs), "; snapshot %s UTC" % snap if snap else ""))
            rows = []
            na = res.pop("_na", {})
            for k in issues:
                sev, label, why = ISSUES[k]
                rows.append((k, sev, label, why if k not in na else "FIELD NOT IN DUMP: this check could not run, so no result is shown", res.get(k, []) if k not in na else None))
                for ident, nm, det in (res.get(k, []) if k not in na else []):
                    csv_rows.append([cust, area, sev, label, ident, nm, det])
            if area == "users":
                p = {i for i, _, _ in res.get("priv", [])}
                comp = sorted(p & ({i for i, _, _ in res.get("weakmfa", [])} | {i for i, _, _ in res.get("token", [])} | {i for i, _, _ in res.get("pwnone", [])}))
                if comp:
                    body.append("<p><b>Compound risk:</b> %d privileged account(s) also have weak MFA, a stale token baseline or password policy None: %s.</p>"
                                % (len(comp), E(", ".join(comp[:10]))))
            rows.sort(key=lambda r: (["Critical", "High", "Medium", "Low"].index(r[1]), -len(r[4] or [])))
            t = "<table><thead><tr><th>Severity</th><th>Finding</th><th>Count</th><th>Why it matters</th></tr></thead><tbody>"
            for k, sev, label, why, items in rows:
                t += "<tr><td>%s</td><td>%s</td><td><b>%s</b></td><td>%s</td></tr>" % (pill(sev, SEV[sev]), E(label), "n/a" if items is None else len(items), E(why))
            body.append(t + "</tbody></table>")
            for k, sev, label, why, items in rows:
                if items:
                    body.append("<details><summary>%s (%d)</summary><table><tbody>%s</tbody></table>%s</details>" % (
                        E(label), len(items), "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (E(n), E(i), E(d)) for i, n, d in items[:SHOW]),
                        "<p class='muted'>%d more in the CSV.</p>" % (len(items) - SHOW) if len(items) > SHOW else ""))
    css = ("body{font-family:Arial,Helvetica,sans-serif;color:#1e293b;max-width:1000px;margin:24px auto;padding:0 16px;font-size:13px}"
           "h1{color:%s;margin:0}h2{color:%s;border-bottom:2px solid %s;padding-bottom:4px;margin-top:30px}h3{margin:18px 0 4px}"
           "table{border-collapse:collapse;width:100%%;margin:6px 0}th,td{border:1px solid #cbd5e1;padding:4px 8px;text-align:left;vertical-align:top}"
           "th{background:#f1f5f9}.muted{color:%s}details{margin:4px 0}summary{cursor:pointer}") % (NAVY, NAVY, NAVY, GRY)
    head = "<h1>Office 365 Posture Review</h1><p class='muted'>%s &middot; %s &middot; as of %s UTC</p>" % (E(a.tenant), E(a.site), now.strftime("%Y-%m-%d %H:%M"))
    tail = ("<h2>Limits</h2><ul><li>This is resource posture from inventory snapshots, not activity. It does not say whether a risk was exploited; "
            "use sign-in, audit or incident tools for that.</li>"
            "<li>MFA registration is not MFA enforcement, and Conditional Access policy state is not evaluated here.</li>"
            "<li>Counts are as of the dump time shown, not a time window. Each feed is assessed on its own and not summed with another.</li>"
            "<li>Some findings are expected: service or federated accounts (password policy None), public-client apps (no credentials), stale devices.</li>"
            "<li>Never read these counts as compliance or compromise.</li></ul>")
    wn = "".join("<p><b>Warning:</b> %s</p>" % E(w) for w in warns)
    with open(a.out, "w") as f:
        f.write("<!doctype html><html><head><meta charset='utf-8'><title>Office 365 Posture Review</title><style>%s</style></head><body>%s%s%s%s</body></html>" % (css, head, wn, "".join(body), tail))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["feed", "area", "severity", "finding", "id", "name", "detail"])
            w.writerows(csv_rows)
    print("%d feed(s) | %d finding rows" % (len(names), len(csv_rows)))
    for w in warns:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
