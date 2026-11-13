#!/usr/bin/env python3
"""Render the Microsoft 365 identity hygiene and posture report (HTML, facts JSON, CSV) from saved resource dumps.

Computed locally from the tenant's Office 365 resource dumps (no FPL report, no event query, no live run):
office365User, office365Application, office365Device. One report per Office 365 feed.

  build_report.py --evidence-dir DIR --out report.html [--csv findings.csv] [--facts facts.json]
                  --tenant "Customer display name" [--account iqb] [--site IQX] [--narrative narrative.json] [--as-of ISO]

Layout of DIR (one set per feed, a feed being one customer name in list_resource_dumps):
  resources.json                       optional, the list_resource_dumps result for the account
  users__<customer>.jsonl.gz           office365User dump
  apps__<customer>.jsonl.gz            office365Application dump
  devices__<customer>.jsonl.gz         office365Device dump
A dump that resources.json lists but whose file is missing is "not collected"; a resource with no dump is "no dump";
neither is a clean result. With several feeds, each gets its own report (the feed name is added to --out).

Sections (the identity hygiene layout, Fluency editorial style):
  banner + scorecard (admins, weak MFA, OAuth, old tokens, password None) + highest-impact finding
  1 executive summary and rating · 2 privileged role footprint · 3 MFA, token and password hygiene
  4 third-party OAuth consent · 5 account composition · 6 device OS currency · 7 application registrations
  8 device registration hygiene · 9 analyst callouts · 10 remediation sequence · method
The thesis, top finding, summary, callouts and remediation are generated from the numbers; --narrative replaces any
of them (keys in references/narrative.md). Every figure is computed here; the facts JSON holds them all.

Rules (thresholds are constants below; licence tiers and the OS catalogue are dated files in ../assets)
  accounts      one bucket each: disabled > guest > paid (a core licence) > free > add-on only > unlicensed.
                Headcount (active licensed accounts) = paid. Licence IDs not in sku_tiers.json are named, never guessed.
  identity      enabled users. Admin roles judged against 2 + 1 per 500 headcount; more than 2 Global Administrators;
                admin with a second weakness (compound); weak MFA = email or SMS registered (case-insensitive);
                OAuth apps; token baseline older than 365 days; passwordPolicies exactly None
  OS currency   all device records: end-of-life Windows, out-of-support build, build to confirm, macOS below 14
  apps          http:// redirect; implicit grant; http:// homepage; no verified publisher; no credentials;
                older than 730 days with implicit grant or http redirect
  devices       enabled devices: no sign-in 90 days; Workplace trust; unmanaged; non-compliant; rooted;
                hybrid sync older than 30 days; no username
A check whose field is absent from every record is "not measured", never zero or clean.
"""
import argparse, collections, csv, datetime, glob, gzip, html, json, os, re, sys
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
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
PRIV_ROLES = ["Global Administrator", "Company Administrator", "Security Administrator", "Privileged Role Administrator",
              "User Administrator", "Exchange Administrator", "SharePoint Service Administrator"]
WEAK = {"email": "email", "mobilephone": "sms"}   # methods compared lower-case with underscores removed
TOKEN_DAYS, APP_AGE_DAYS, STALE_SIGNIN_DAYS, STALE_SYNC_DAYS = 365, 730, 90, 30
ADMIN_BASE, ADMIN_PER, GA_MAX, GUEST_SHARE = 2, 500, 2, 0.15
TOP = 10      # accounts named per table in the body; the CSV holds every row
ORDER = ["Critical", "High", "Medium", "Low"]
SEVTAG = {"Critical": "red", "High": "o-red", "Medium": "amber", "Low": "gray"}

# finding -> (severity, label, why it matters). Severity of "priv" is set per feed against the baseline.
ISSUES = {
    "compound": ("Critical", "Privileged account with a second weakness", "Admin with weak MFA, a stale token baseline or password policy None"),
    "priv": ("High", "Privileged roles above baseline", "Baseline is 2, plus 1 per 500 active licensed accounts"),
    "ga": ("High", "More than 2 Global Administrators", "Reduce to 2 named or break-glass accounts"),
    "weakmfa": ("Medium", "Weak MFA factors (email or SMS)", "Phishable factors registered"),
    "oauth": ("Medium", "Third-party OAuth apps connected", "Consent review queue, not proof of abuse"),
    "token": ("Medium", "Token baseline older than 365 days", "Session hygiene; re-baseline stale tokens"),
    "pwnone": ("Low", "Password policy set to None", "Validate service or federated accounts"),
    "guests": ("Medium", "Guest accounts above 15% of the directory", "External access to review; set guest expiry"),
    "unlicensed": ("Medium", "Enabled members with no licence", "Classify each: service, shared mailbox, resource or person"),
    "eol": ("High", "End-of-life Windows", "No supported edition shares this build: replace or upgrade"),
    "oos": ("High", "Out-of-support Windows build", "No security updates: update to a current release"),
    "macold": ("Medium", "macOS below the oldest supported major version", "Upgrade macOS"),
    "verify": ("Low", "Windows build to confirm", "Shared with a supported Server or LTSC edition: confirm the SKU"),
    "oldrisk": ("Critical", "App older than 730 days with implicit grant or HTTP redirect", "Age and risky settings compound"),
    "http": ("High", "App with an HTTP redirect URI", "Transport security: use HTTPS or retire the app"),
    "implicit": ("High", "App with implicit grant enabled", "Prefer authorization code with PKCE"),
    "nontls": ("Medium", "App with an HTTP homepage URL", "Transport security"),
    "nopub": ("Medium", "App with no verified publisher", "Trust review for user-facing or third-party apps"),
    "nocred": ("Low", "App with no secrets or certificates", "Cleanup candidate, confirm it is unused"),
    "rooted": ("Critical", "Rooted or jailbroken device", "Investigate first"),
    "unmanaged": ("High", "Unmanaged device", "MDM management disabled or unknown"),
    "noncomp": ("High", "Non-compliant device", "Failing compliance policy"),
    "workplace": ("Medium", "Workplace trust type", "Not Entra joined; weaker policy enforcement"),
    "sync": ("Medium", "Hybrid sync older than 30 days", "Verify hybrid join and sync"),
    "stale": ("Low", "No sign-in for 90 days (or none recorded)", "Cleanup candidate"),
    "nouser": ("Low", "No username attributed", "Weakens investigation quality"),
}
AREA_OF = {**{k: "identity" for k in ("compound", "priv", "ga", "weakmfa", "oauth", "token", "pwnone")},
           **{k: "accounts" for k in ("guests", "unlicensed")}, **{k: "os" for k in ("eol", "oos", "macold", "verify")},
           **{k: "applications" for k in ("oldrisk", "http", "implicit", "nontls", "nopub", "nocred")},
           **{k: "devices" for k in ("rooted", "unmanaged", "noncomp", "workplace", "sync", "stale", "nouser")}}
SRC_OF = {"identity": "users", "accounts": "users", "os": "devices", "applications": "applications", "devices": "devices"}
RES_KEY = {"users": "office365User", "applications": "office365Application", "devices": "office365Device"}


# ---------- loading ----------
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


def feeds(ev_dir):
    out = collections.defaultdict(dict)
    for prefix, area in (("users", "users"), ("apps", "applications"), ("devices", "devices")):
        for fp in sorted(glob.glob(os.path.join(ev_dir, prefix + "__*.jsonl.gz"))):
            out[os.path.basename(fp)[len(prefix) + 2:-len(".jsonl.gz")]][area] = fp
    return out


def listed(ev_dir):
    res = load(os.path.join(ev_dir, "resources.json")) or {}
    out = collections.defaultdict(dict)
    for e in res.get("entries", []):
        key = {v: k for k, v in RES_KEY.items()}.get(e.get("resource"))
        if key:
            out[e.get("customer")][key] = e
    return out


# ---------- assessment ----------
def classify(r, tiers):
    if not r.get("accountEnabled"):
        return "disabled", []
    if r.get("userType") == "Guest":
        return "guest", []
    skus = [str((l or {}).get("skuId") or "").lower() for l in alist(r.get("assignedLicenses")) if isinstance(l, dict)]
    if not skus:
        return "unlicensed", []
    got = {(tiers.get(s) or {}).get("tier") for s in skus}
    if "core" in got:
        return "paid", []
    return ("free" if "service_only" in got else "other_licensed"), [s for s in skus if s not in tiers]


def first_app(a):
    a = alist(a)
    if not a:
        return ""
    x = a[0]
    return str(x.get("displayName") or x.get("appDisplayName") or x.get("appId") or "") if isinstance(x, dict) else str(x)


def assess_users(recs, now, tiers):
    f = {"present": True, "records": len(recs)}
    buckets, unknown, plans_only = collections.Counter(), collections.Counter(), 0
    lists = collections.defaultdict(list)
    for r in recs:
        b, unk = classify(r, tiers)
        buckets[b] += 1
        for s in unk:
            unknown[s] += 1
        if b == "unlicensed":
            hp = bool(alist(r.get("assignedPlans")))
            plans_only += hp
            lists["unlicensed"].append({"upn": r.get("userPrincipalName") or "", "name": r.get("displayName") or "", "detail": "service plans but no licence record" if hp else "no licence"})
        if b == "guest":
            lists["_guests"].append({"upn": r.get("userPrincipalName") or "", "name": r.get("displayName") or "", "detail": "guest"})
    en = [r for r in recs if r.get("accountEnabled")]
    for r in en:
        upn, name = r.get("userPrincipalName") or "", r.get("displayName") or ""
        roles = [x for x in alist(r.get("roles")) if isinstance(x, str)]
        meth = {str(m).lower().replace("_", "") for m in alist((r.get("userRegistration") or {}).get("authMethods"))}
        weak = sorted(WEAK[m] for m in meth if m in WEAK)
        rd, sd = days(r.get("refreshTokensValidFromDateTime"), now), days(r.get("signInSessionsValidFromDateTime"), now)
        stale = [x for x in (rd, sd) if x is not None and x > TOKEN_DAYS]
        pw = r.get("passwordPolicies") == "None"
        oauth = alist(r.get("oauth2Applications"))
        if set(roles) & set(PRIV_ROLES):
            flags = [t for t, on in (("Weak MFA", weak), ("Stale token baseline", stale), ("Password policy None", pw)) if on]
            lists["priv"].append({"upn": upn, "name": name, "roles": roles, "ga": "Global Administrator" in roles, "flags": flags,
                                  "detail": ", ".join(roles[:3]) + (" (+%d)" % (len(roles) - 3) if len(roles) > 3 else "")})
            if flags:
                lists["compound"].append({"upn": upn, "name": name, "detail": "; ".join(flags)})
        if "Global Administrator" in roles:
            lists["_ga"].append({"upn": upn, "name": name, "detail": "Global Administrator"})
        if weak:
            lists["weakmfa"].append({"upn": upn, "name": name, "email": "email" in weak, "sms": "sms" in weak, "detail": ", ".join(weak)})
        if oauth:
            lists["oauth"].append({"upn": upn, "name": name, "apps": len(oauth), "example": first_app(oauth), "detail": "%d app(s)" % len(oauth)})
        if stale:
            lists["token"].append({"upn": upn, "name": name, "days": int(max(stale)), "detail": "%d days" % max(stale)})
        if pw:
            lists["pwnone"].append({"upn": upn, "name": name, "detail": "None"})
    lists["priv"].sort(key=lambda u: (not u["ga"], -len(u["roles"])))
    lists["oauth"].sort(key=lambda u: -u["apps"])
    for k in ("weakmfa", "pwnone", "unlicensed", "token"):
        lists[k].sort(key=lambda u: (u["name"] or u["upn"]).lower())
    no_roles = not any("roles" in r for r in en)
    f["na"] = [k for k, absent in (
        ("priv", no_roles), ("ga", no_roles), ("compound", no_roles),
        ("weakmfa", not any((r.get("userRegistration") or {}).get("authMethods") is not None for r in en)),
        ("token", not any("refreshTokensValidFromDateTime" in r or "signInSessionsValidFromDateTime" in r for r in en)),
        ("oauth", not any("oauth2Applications" in r for r in en)), ("pwnone", not any("passwordPolicies" in r for r in en)),
        ("unlicensed", not any("assignedLicenses" in r for r in recs))) if absent]
    headcount = None if "unlicensed" in f["na"] else buckets["paid"]
    total = len(recs)
    guest_share = buckets["guest"] / total if total else 0.0
    f.update({"enabled": len(en), "buckets": dict(buckets), "headcount": headcount, "guest_share": guest_share,
              "unknown_skus": unknown.most_common(), "plans_only": plans_only,
              "baseline": (ADMIN_BASE + headcount // ADMIN_PER) if headcount is not None else None,
              "ga_count": len(lists["_ga"]), "oauth_avg": (sum(u["apps"] for u in lists["oauth"]) / len(lists["oauth"])) if lists["oauth"] else 0,
              "oauth_max": max([u["apps"] for u in lists["oauth"]] + [0]),
              "oauth_example_apps": collections.Counter(u["example"] for u in lists["oauth"] if u["example"]).most_common(6)})
    if guest_share > GUEST_SHARE:
        lists["guests"] = lists["_guests"]
    if len(lists["_ga"]) > GA_MAX:
        lists["ga"] = lists["_ga"]
    lists.pop("_ga", None)
    lists.pop("_guests", None)
    f["lists"] = dict(lists)
    return f


def windows_status(ver, cat):
    parts = str(ver or "").split(".")
    if len(parts) >= 2 and parts[0] == "6":
        hit = cat["windows"].get(".".join(parts[:2]))
        return tuple(hit) if hit else ("Windows NT 6.x", "eol")
    if len(parts) >= 3 and parts[0] == "10" and parts[1] == "0" and parts[2].isdigit():
        hit = cat["windows"].get(".".join(parts[:3]))
        if hit:
            return tuple(hit)
        if int(parts[2]) < cat["windows10_pre2004_below"]:
            return ("Windows 10 pre-2004 client build", "eol")
    return None


def build_key(ver):
    p = str(ver or "").split(".")
    return (".".join(p[:2]) if p and p[0] == "6" else ".".join(p[:3])) or "unknown"


def assess_devices(recs, now, cat):
    f = {"present": True, "records": len(recs)}
    lists = collections.defaultdict(list)
    os_mix, builds = collections.Counter(), collections.Counter()
    for d in recs:   # OS currency over every device record
        osn, ver = d.get("operatingSystem") or "Unknown", str(d.get("operatingSystemVersion") or "")
        name, owner = d.get("displayName") or "", d.get("username") or ""
        os_mix[osn] += 1
        if osn.lower().startswith("windows"):
            st = windows_status(ver, cat)
            builds[build_key(ver)] += 1
            if st and st[1] in ("eol", "out_of_support", "verify"):
                lists[{"eol": "eol", "out_of_support": "oos", "verify": "verify"}[st[1]]].append(
                    {"upn": d.get("deviceId") or "", "name": name, "owner": owner, "build": ver, "detail": "%s (%s)" % (ver, st[0])})
        if osn.lower() in ("macos", "macmdm", "mac os x", "osx"):
            major = ver.split(".")[0]
            if major.isdigit() and int(major) < cat["macos_oldest_supported_major"]:
                lists["macold"].append({"upn": d.get("deviceId") or "", "name": name, "owner": owner, "detail": "%s %s" % (osn, ver)})
    en = [d for d in recs if d.get("accountEnabled")]
    for d in en:   # registration hygiene over enabled devices
        name, did = d.get("displayName") or "", d.get("deviceId") or ""
        os_ = ("%s %s" % (d.get("operatingSystem") or "", d.get("operatingSystemVersion") or "")).strip()
        last = d.get("approximateLastSignInDateTime")
        dd = days(last, now)
        row = lambda det: {"upn": did, "name": name, "detail": det}
        if not last or (dd is not None and dd > STALE_SIGNIN_DAYS):
            lists["stale"].append(row("no sign-in recorded" if not last else "%d days; %s" % (dd, os_)))
        if d.get("trustType") == "Workplace":
            lists["workplace"].append(row(os_))
        if not d.get("isManaged"):
            lists["unmanaged"].append(row(os_))
        if d.get("isCompliant") is False:
            lists["noncomp"].append(row(os_))
        if d.get("isRooted") is True:
            lists["rooted"].append(row(os_))
        sd = days(d.get("onPremisesLastSyncDateTime"), now)
        if d.get("onPremisesSyncEnabled") and sd is not None and sd > STALE_SYNC_DAYS:
            lists["sync"].append(row("%d days" % sd))
        if d.get("username") in (None, "", "None"):
            lists["nouser"].append(row(os_))
    no_ver = not any(d.get("operatingSystemVersion") for d in recs)
    f.update({"enabled": len(en), "os_mix": os_mix.most_common(), "na": ["eol", "oos", "verify", "macold"] if no_ver else [],
              "builds": [(b, n, windows_status(b, cat) or ("not in catalogue", "unknown")) for b, n in builds.most_common(12)],
              "lists": dict(lists)})
    return f


def redirect_uris(a):
    web, spa, pub = a.get("web") or {}, a.get("spa") or {}, a.get("publicClient") or {}
    return ([u for u in alist(web.get("redirectUris")) if u] + [o.get("uri") for o in alist(web.get("redirectUriSettings")) if isinstance(o, dict) and o.get("uri")]
            + [u for u in alist(spa.get("redirectUris")) if u] + [u for u in alist(pub.get("redirectUris")) if u])


def assess_apps(recs, now):
    lists = collections.defaultdict(list)
    for a in recs:
        name, aid = a.get("displayName") or "", a.get("appId") or ""
        uris = redirect_uris(a)
        age = days(a.get("createdDateTime"), now)
        http = any(str(u).startswith("http://") for u in uris)
        s = (a.get("web") or {}).get("implicitGrantSettings") or {}
        imp = bool(s.get("enableAccessTokenIssuance") or s.get("enableIdTokenIssuance"))
        row = lambda det: {"upn": aid, "name": name, "detail": det}
        if http:
            lists["http"].append(row(next(u for u in uris if str(u).startswith("http://"))))
        if imp:
            lists["implicit"].append(row("implicit grant"))
        if str((a.get("web") or {}).get("homePageUrl") or "").startswith("http://"):
            lists["nontls"].append(row(a["web"]["homePageUrl"]))
        vp = a.get("verifiedPublisher") or {}
        if not (vp.get("verifiedPublisherId") or vp.get("displayName")):   # the dump carries an empty object when unverified
            lists["nopub"].append(row(a.get("publisherDomain") or ""))
        if not alist(a.get("passwordCredentials")) and not alist(a.get("keyCredentials")):
            lists["nocred"].append(row("created %s" % (a.get("createdDateTime") or "n/a")[:10]))
        if age is not None and age > APP_AGE_DAYS and (imp or http):
            lists["oldrisk"].append(row("%d days; %s" % (age, "implicit grant" if imp else "http redirect")))
    return {"present": True, "records": len(recs), "na": [], "lists": dict(lists)}


def raised_items(F, k):
    src = F[SRC_OF[AREA_OF[k]]]
    if not src.get("present") or k in src.get("na", []):
        return []
    if k == "priv" and F.get("priv_within"):
        return []
    return src["lists"].get(k, [])


# ---------- narrative ----------
def default_narrative(F):
    u, d = F["users"], F["devices"]
    n = lambda k: len(raised_items(F, k))
    adm = len(u.get("lists", {}).get("priv", [])) if u.get("present") else 0
    base, n_ga, comp = u.get("baseline"), u.get("ga_count", 0), n("compound")
    weak, pw, unl = n("weakmfa"), n("pwnone"), n("unlicensed")
    gp = 100 * u.get("guest_share", 0) if u.get("present") else 0
    eol, oos = n("eol"), n("oos")
    ratio = (adm / base) if base else None
    win = sum(c for b, c, st in d.get("builds", [])) if d.get("present") else 0
    cur = sum(c for b, c, st in d.get("builds", []) if st[1] == "current") if d.get("present") else 0
    bits = []
    if base and adm > base:
        bits.append("admin power is concentrated above baseline")
    if comp and comp == adm:
        bits.append("every admin carries a second weakness")
    elif comp:
        bits.append("%d admins carry a second weakness" % comp)
    if gp > GUEST_SHARE * 100:
        bits.append("the directory is %d%% guests" % round(gp))
    if eol:
        bits.append("end-of-life Windows remains in the estate")
    thesis = ("; ".join(bits) + ".") if bits else "No critical identity finding in this snapshot."
    thesis = thesis[0].upper() + thesis[1:]
    if comp:
        who = ("All %d" % adm) if comp == adm else ("%d of %d" % (comp, adm))
        head = "%s privileged accounts also carry a second weakness%s" % (who, (", %.1f× the admin baseline" % ratio) if ratio and ratio > 1 else "")
        text = ("%d accounts hold administrator roles%s, and %d are Global Administrators. %d of them also have weak MFA, a stale token baseline or "
                "password policy None. One phished admin would give control of the tenant." % (adm, (" against a baseline of %d" % base) if base else "", n_ga, comp))
    elif base and adm > base:
        head = "%d privileged accounts, %.1f× the admin baseline of %d" % (adm, ratio, base)
        text = "Administrator roles are held by more accounts than the tenant's size needs; %d are Global Administrators." % n_ga
    elif eol:
        head, text = "%d Windows devices run an end-of-life build" % eol, "These builds no longer receive security updates and need an upgrade or replacement."
    else:
        head, text = "No critical identity finding", "No admin carries a second weakness and the admin count is within baseline."
    drivers = ("admin accounts: <strong>%d hold privileged roles against a baseline of %s</strong>, %d are Global Administrators, and %d also carry a second weakness"
               % (adm, base if base is not None else "(not computed)", n_ga, comp)) if adm else "the findings below"
    p1 = ("The rating is driven by %s. Outside the admin group, %s enabled users rely on email or SMS for MFA, guests make up %.1f%% of directory records, "
          "and %d Windows devices run an end-of-life build with %d more on out-of-support releases." % (drivers, "{:,}".format(weak), gp, eol, oos))
    p2 = ("%sStart with the admins: cut the count toward %s, move every admin to the Authenticator app or a FIDO2 key, and review the %d accounts exempt from password policy.%s"
          % (("<strong>%s of %s Windows devices run a current build.</strong> " % ("{:,}".format(cur), "{:,}".format(win))) if win else "",
             base if base is not None else "the baseline", pw,
             " Token baselines could not be measured because the fields are absent from this snapshot." if "token" in u.get("na", []) else ""))
    calls = []
    if base and adm > base:
        calls.append(("act", "High", "%d admins, %.1f× the baseline of %d" % (adm, ratio, base), "Every extra admin widens the blast radius of one phished password. Consolidate roles and use just-in-time elevation."))
    if n("ga"):
        calls.append(("act", "High", "%d Global Administrators" % n_ga, "Global Administrator should be limited to two named or break-glass accounts. Move day-to-day administration to scoped roles."))
    if weak:
        calls.append(("watch", "Review", "%s users with email or SMS MFA" % "{:,}".format(weak), "These factors are phishable and SIM-swappable. Register the Authenticator app or a passkey, then remove SMS and email as methods, starting with the admins."))
    if gp > GUEST_SHARE * 100:
        calls.append(("watch", "Review", "Guests are %.1f%% of the directory" % gp, "Run a guest access review and set guest expiry."))
    risky = {x["upn"] for k in ("implicit", "http") for x in raised_items(F, k)}
    if risky:
        calls.append(("act", "High", "%d app registrations use implicit grant or an HTTP redirect" % len(risky),
                      "%d of them are older than two years. Move them to authorization code with PKCE and HTTPS, or retire them." % n("oldrisk")))
    if unl:
        calls.append(("good", "Context", "%d unlicensed enabled accounts to classify" % unl, "These are service accounts, shared mailboxes, resource accounts or people without a licence. Classify each and disable what is no longer needed."))
    if win and cur / win > 0.5:
        calls.append(("good", "Clean", "Most Windows devices are current", "%s of %s Windows devices run a current build; %d run an end-of-life build." % ("{:,}".format(cur), "{:,}".format(win), eol)))
    rem = []
    if comp:
        rem.append(("Critical", "Move every admin to the Authenticator app or a FIDO2 key and remove email and SMS methods", "Identity admin", "Re-run this report: compound admins drop to 0"))
    if (base and adm > base) or n("ga"):
        rem.append(("High", "Reduce Global Administrators to %d and scope the remaining admin roles" % GA_MAX, "Identity admin", "Global Administrators ≤ %d; admins near the baseline%s" % (GA_MAX, (" of %d" % base) if base else "")))
    if risky:
        rem.append(("High", "Remove implicit grant and HTTP redirect URIs from app registrations, or retire the apps", "App owners", "Implicit grant and HTTP redirect counts = 0"))
    if eol or oos:
        rem.append(("High", "Replace or upgrade the %d end-of-life Windows devices and update the %d out-of-support builds" % (eol, oos), "Endpoint team", "End-of-life Windows devices = 0"))
    if n("unmanaged") or n("noncomp"):
        rem.append(("High", "Enrol unmanaged devices in MDM and remediate non-compliant ones", "Endpoint team", "Unmanaged and non-compliant counts fall"))
    if gp > GUEST_SHARE * 100:
        rem.append(("Medium", "Run a guest access review and set guest expiry", "Identity admin", "Guests below 15% of directory"))
    if weak:
        rem.append(("Medium", "Move the remaining users off email and SMS MFA", "Identity admin", "Weak MFA count falls month on month"))
    if unl or pw:
        rem.append(("Low", "Classify the %d unlicensed accounts and review the %d accounts with password policy None" % (unl, pw), "IT operations", "Lists reviewed and signed off"))
    return {"thesis": thesis, "top_finding": {"headline": head, "text": text, "action": "Reduce and harden" if (comp or (base and adm > base)) else "Review"},
            "summary": [p1, p2], "callouts": [dict(kind=k, tag=t, heading=h, text=x) for k, t, h, x in calls[:6]],
            "remediation": [dict(severity=s, action=a, owner=o, verify=v) for s, a, o, v in rem[:8]]}


# ---------- rendering ----------
def gap_note(F, src):
    m = F["listed"].get(src)
    if m:
        return fb.note("<b>Not collected.</b> The %s dump is listed (%s records) but was not downloaded; no result is shown." % (RES_KEY[src], E(str(m.get("count")))))
    return fb.note("<b>No dump.</b> This feed has no %s dump, so this section is not assessed. That is a coverage gap, not a clean result." % RES_KEY[src])


def findings_table(F, keys):
    rows = []
    for k in keys:
        sev, label, why = F["issues"][k]
        src = F[SRC_OF[AREA_OF[k]]]
        na = k in src.get("na", [])
        items = src["lists"].get(k, [])
        rows.append((sev, label, "n/a" if na else "{:,}".format(len(items)), "Not measured: the field is not in this snapshot" if na else why, len(items)))
    rows.sort(key=lambda r: (ORDER.index(r[0]), -r[4]))
    return fb.table(["Severity", "Finding", "Count", "Why it matters"], [[fb.tag(s, SEVTAG[s]), l, c, w] for s, l, c, w, _ in rows],
                    widths=["13%", "38%", "10%", "39%"], num_cols=(2,), raw_cols=(0,))


def scorecard(u, F):
    f = lambda n: "{:,}".format(n)
    L = lambda k: u["lists"].get(k, [])
    na = lambda k: k in u.get("na", [])
    base, adm = u.get("baseline"), len(L("priv"))
    over = base is not None and adm > base

    def tile(label, key, note, review="Review"):
        if na(key):
            return fb.kpi(label, "n/a", "Not in this snapshot", tag="Not measured", tag_kind="gray")
        c = len(L(key))
        return fb.kpi(label, f(c), note, color="amber" if c else "", tag=review if c else "Clean", tag_kind="amber" if c else "clean")
    return fb.kpi_strip([
        fb.kpi("Privileged roles", "n/a" if na("priv") else adm, ("Baseline %d (≤2 +1 / 500 accounts)" % base) if base is not None else "Baseline not computed",
               color="red" if over else "", tag=("Above baseline" if over else "Within baseline") if base is not None else "Not measured", tag_kind="red" if over else "clean" if base is not None else "gray"),
        tile("Weak MFA factors", "weakmfa", "Email / SMS registered"),
        tile("OAuth apps", "oauth", "Users with ≥1 third-party app", "Review consent"),
        tile("Old token baselines", "token", "Refresh / sign-in > 365 days"),
        tile("Password policy None", "pwnone", "No expiry / complexity policy")])


def render(F, nar, a):
    u, d, ap = F["users"], F["devices"], F["applications"]
    f = lambda n: "{:,}".format(n)
    UL = lambda k: u["lists"].get(k, []) if u.get("present") else []
    na = lambda k: k in u.get("na", [])
    hc, base = u.get("headcount"), u.get("baseline")
    snap = F["snapshot"] or F["as_of"][:10]
    tf = nar["top_finding"]
    body = scorecard(u, F) if u.get("present") else ""
    body += fb.netread("Highest-impact finding · %s: %s" % (tf.get("action", "Review"), tf["headline"]), E(tf["text"]))
    body += '<h2><span class="n">1</span>Executive summary %s</h2>%s' % (
        fb.tag("%s risk" % F["rating"], {"Elevated": "red", "Moderate": "amber", "Good": "clean"}[F["rating"]]), "".join("<p>%s</p>" % p for p in nar["summary"]))
    if u.get("present"):
        bk = u["buckets"]
        eolc = len(raised_items(F, "eol"))
        body += fb.kpi_strip([
            fb.kpi("Active licensed accounts", f(hc) if hc is not None else "n/a", "of %s directory records" % f(u["records"])),
            fb.kpi("Guest accounts", f(bk.get("guest", 0)), "%.1f%% of directory" % (100 * u["guest_share"]), color="amber" if u["guest_share"] > GUEST_SHARE else ""),
            fb.kpi("Unlicensed, enabled", f(bk.get("unlicensed", 0)), "To classify: service / shared / human"),
            fb.kpi("EOL Windows devices", f(eolc) if d.get("present") else "n/a", ("of %s Entra devices" % f(d["records"])) if d.get("present") else "No device dump", color="red" if eolc else "")])
    # 2 privileged role footprint
    if u.get("present") and not na("priv"):
        adm = UL("priv")
        tbl = fb.table(["Account", "Roles (top 2)", "Roles", "Compound flags"],
                       [["%s<br><span class='fn'>%s</span>" % (E(x["name"]), E(x["upn"])),
                         " · ".join(("<strong>%s</strong>" % E(r)) if r == "Global Administrator" else E(r)
                                    for r in ((["Global Administrator"] if x["ga"] else []) + [r for r in x["roles"] if r != "Global Administrator"])[:2]),
                         len(x["roles"]), " ".join(fb.tag(t, {"Weak MFA": "o-red", "Password policy None": "amber"}.get(t, "gray")) for t in x["flags"])] for x in adm[:TOP]],
                       widths=["30%", "36%", "8%", "26%"], num_cols=(2,), raw_cols=(0, 1, 3), row_class=lambda r: "sev-high" if "Global Administrator" in r[1] else "",
                       foot=("+%d more privileged accounts — full list in the CSV. " % (len(adm) - TOP) if len(adm) > TOP else "") + "A bar on the first cell marks a Global Administrator.")
        sub = ("Baseline for %s accounts is %d — this tenant is at <strong>%.1f× baseline</strong>. " % (f(hc), base, len(adm) / base)) if base else "Baseline not computed: no headcount. "
        body += fb.section(2, "Privileged role footprint", "<h3>%d privileged accounts · %d Global Administrators</h3><p>%sFlags mark admins that also appear in another finding.</p>%s"
                           % (len(adm), u["ga_count"], sub, tbl))
    else:
        body += fb.section(2, "Privileged role footprint", gap_note(F, "users") if not u.get("present") else fb.note("<b>Not measured.</b> No record carries roles."))
    # 3 MFA, token and password
    if u.get("present"):
        wk = UL("weakmfa")
        wt = (fb.note("<b>Not measured.</b> No record carries MFA methods.") if na("weakmfa") else
              fb.table(["Account", "Email", "SMS"], [[x["name"] or x["upn"], "yes" if x["email"] else "—", "yes" if x["sms"] else "—"] for x in wk[:TOP]],
                       widths=["60%", "20%", "20%"], foot="First %d of %s." % (min(TOP, len(wk)), f(len(wk)))))
        tp = [[x["name"] or x["upn"], "Stale token", str(x["days"])] for x in UL("token")] + [[x["name"] or x["upn"], "Password policy None", "—"] for x in UL("pwnone")]
        pt = fb.table(["Account", "Finding", "Days"], tp[:TOP], widths=["50%", "38%", "12%"], num_cols=(2,), foot="First %d of %s." % (min(TOP, len(tp)), f(len(tp))))
        th = ("Stale token baselines — not measured" if na("token") else "Stale token baselines — %s" % f(len(UL("token")))) + " · Password policy None — %s" % f(len(UL("pwnone")))
        tsub = (("Token baseline fields are not in this snapshot, so stale tokens could not be checked. " if na("token") else "Tokens not re-anchored in over a year. ")
                + "Accounts exempt from password expiry or complexity are hygiene unless privileged.")
        body += fb.section(3, "MFA, token and password hygiene",
                           "<div class='two'><div><h3>Weak MFA factors — %s</h3><p>Email or SMS registered as an authentication method. Both are phishable; move these users to the Authenticator app or a FIDO2 key.</p>%s</div>"
                           "<div><h3>%s</h3><p>%s</p>%s</div></div>" % ("n/a" if na("weakmfa") else f(len(wk)), wt, E(th), tsub, pt))
    else:
        body += fb.section(3, "MFA, token and password hygiene", gap_note(F, "users"))
    # 4 OAuth
    if u.get("present") and not na("oauth"):
        oa = UL("oauth")
        body += fb.section(4, "Third-party OAuth consent",
                           "<h3>%s users · avg %.1f apps · max %d</h3><p>Users with the most third-party app consents.</p>%s<h3>Most common apps</h3><p>Count of users whose first-listed app is this one.</p>%s"
                           % (f(len(oa)), u["oauth_avg"], u["oauth_max"],
                              fb.table(["Account", "Apps", "Example app"], [[x["name"] or x["upn"], x["apps"], x["example"]] for x in oa[:TOP]], widths=["40%", "10%", "50%"], num_cols=(1,)),
                              fb.bar_rows(u["oauth_example_apps"]) if u["oauth_example_apps"] else "<p class='fn'>No app names in the snapshot.</p>"))
    else:
        body += fb.section(4, "Third-party OAuth consent", gap_note(F, "users") if not u.get("present") else fb.note("<b>Not measured.</b> No record carries OAuth grants."))
    # 5 account composition
    if u.get("present") and hc is not None:
        bk = u["buckets"]
        comp = [("Paid seat", bk.get("paid", 0)), ("Guest", bk.get("guest", 0)), ("Disabled", bk.get("disabled", 0)), ("Add-on only", bk.get("other_licensed", 0)),
                ("Unlicensed", bk.get("unlicensed", 0)), ("Free only", bk.get("free", 0))]
        unl, unk = UL("unlicensed"), u["unknown_skus"]
        unote = ("<p class='fn'>%d licence ID(s) are not in the licence-tier list (%s); members holding only those are counted outside the active licensed accounts, so the headcount may be understated.</p>"
                 % (len(unk), E(", ".join("%s (%d)" % (s, c) for s, c in unk[:6])))) if unk else ""
        body += fb.section(5, "Account composition",
                           "<div class='two'><div><h3>%s directory records → %s active licensed accounts</h3><p>Raw records overstate headcount. Only enabled, non-guest users with a core paid licence are counted as accounts.</p>%s%s</div>"
                           "<div><h3>Unlicensed enabled accounts — %s</h3><p>Each is a service account, shared mailbox, resource account or an unlicensed person. Please classify; disable what is no longer needed.</p>%s</div></div>"
                           % (f(u["records"]), f(hc), fb.bar_rows(comp, lead_blue=False), unote, f(len(unl)),
                              fb.table(["Account"], [["%s <span class='fn'>%s</span>" % (E(x["name"]), E(x["upn"]))] for x in unl[:TOP]], raw_cols=(0,),
                                       foot="First %d of %s." % (min(TOP, len(unl)), f(len(unl))))))
    else:
        body += fb.section(5, "Account composition", gap_note(F, "users") if not u.get("present") else fb.note("<b>Not measured.</b> No record carries licences, so the headcount cannot be computed."))
    # 6 device OS currency
    if d.get("present") and not d.get("na"):
        stat = {"current": ("current", "clean"), "aging": ("aging", "gray"), "eol": ("eol", "red"), "out_of_support": ("out of support", "o-red"), "verify": ("confirm SKU", "amber")}
        vrows = [[b, "%s %s" % (fb.tag(*stat.get(st[1], ("not in catalogue", "gray"))), E(st[0] if st[1] != "unknown" else "")), f(c)] for b, c, st in d["builds"][:8]]
        eol, oos, ver = d["lists"].get("eol", []), len(d["lists"].get("oos", [])), len(d["lists"].get("verify", []))
        tail = "%d devices on out-of-support Windows 11 or Windows 10 releases — update to a current release. %d devices on builds shared with Server or LTSC: confirm the SKU." % (oos, ver)
        eol_t = (fb.table(["Device", "Owner", "Build"], [[x["name"], x["owner"] or "—", x["build"]] for x in eol[:TOP]], widths=["30%", "45%", "25%"], foot=tail)
                 if eol else "<p>None. %s</p>" % tail)
        body += fb.section(6, "Device OS currency",
                           "<h3>%s Entra devices by OS</h3><p>From Entra device registrations (not EDR). Windows builds labelled from the build catalogue (as of %s).</p>%s%s"
                           "<div style='break-inside:avoid;page-break-inside:avoid'><h3>End-of-life Windows — %d devices</h3><p>Builds with no supported SKU. These need an OS upgrade or replacement, not a patch.</p>%s</div>"
                           % (f(d["records"]), E(F["os_as_of"]), fb.bar_rows(d["os_mix"][:8]),
                              fb.table(["Windows build", "Label", "Devices"], vrows, widths=["18%", "70%", "12%"], num_cols=(2,), raw_cols=(1,)), len(eol), eol_t))
    else:
        body += fb.section(6, "Device OS currency", gap_note(F, "devices") if not d.get("present") else fb.note("<b>Not measured.</b> No device carries an OS version."))
    # 7 application registrations, 8 device registration hygiene
    body += "<div style='break-inside:avoid;page-break-inside:avoid'>" + fb.section(7, "Application registrations", ("<p>%s app registrations assessed.</p>%s" % (f(ap["records"]), findings_table(F, ("oldrisk", "http", "implicit", "nontls", "nopub", "nocred"))))
                       if ap.get("present") else gap_note(F, "applications")) + "</div>"
    body += "<div style='break-inside:avoid;page-break-inside:avoid'>" + fb.section(8, "Device registration hygiene", ("<p>%s enabled devices assessed (%s records).</p>%s" % (f(d["enabled"]), f(d["records"]), findings_table(F, ("rooted", "unmanaged", "noncomp", "workplace", "sync", "stale", "nouser"))))
                       if d.get("present") else gap_note(F, "devices")) + "</div>"
    # 9 analyst callouts, 10 remediation sequence
    if nar["callouts"]:
        body += fb.section(9, "Analyst callouts", fb.callouts([fb.callout(c["kind"], c["tag"], c["heading"], c["text"]) for c in nar["callouts"]]))
    if nar["remediation"]:
        body += fb.section(10, "Suggested remediation sequence",
                           fb.table(["#", "Severity", "Action", "Owner", "How to verify"],
                                    [[str(i), fb.tag(r["severity"], SEVTAG.get(r["severity"], "gray")), r["action"], r["owner"], r["verify"]] for i, r in enumerate(nar["remediation"], 1)],
                                    widths=["5%", "12%", "43%", "15%", "25%"], raw_cols=(1,)))
    where = " · ".join(x for x in (("tenant %s" % a.account) if a.account else "", a.site) if x) or "this tenant"
    method = ("<p><strong>Method.</strong> Prepared from Fluency's Microsoft 365 resource snapshot of %s (%s), computed locally from the downloaded office365User, office365Application and "
              "office365Device dumps. Counts are point-in-time configuration, not sign-in activity, and one account can appear in several findings — do not add the finding counts together.</p>"
              "<p><strong>Baselines.</strong> Privileged accounts: ≤2, +1 per 500 active licensed accounts (members holding a licence the tier list marks core, as of %s). Weak MFA: email or SMS "
              "registered. Stale token: refresh or sign-in baseline older than 365 days. Device end-of-life: curated Windows build catalogue (as of %s); no \"behind the fleet\" comparison is made. "
              "Rating: Elevated when any Critical finding is raised, Moderate when any High, otherwise Good.</p>"
              "<p><strong>Not covered.</strong> MFA coverage (users with no MFA), Conditional Access policy, mailbox and sign-in activity. Never read these counts as compliance or compromise.</p>"
              % (E(snap), E(where), E(F["sku_as_of"]), E(F["os_as_of"])))
    cust = a.tenant or "Tenant"
    fields = [("Active licensed accounts", f(hc) if hc is not None else "n/a"), ("Directory records", f(u["records"]) if u.get("present") else "n/a"),
              ("Entra devices", f(d["records"]) if d.get("present") else "n/a"), ("Snapshot", snap)]
    return fb.page("%s — Microsoft 365 identity & access hygiene" % cust, "Microsoft 365 Identity Hygiene · Configuration snapshot", body=body, subtitle=nar["thesis"],
                   fields=fields, meta="Read-only", method=method, footer_left="%s — Microsoft 365 Identity Hygiene" % cust, data_date=snap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--facts", help="write every computed figure and the narrative used as JSON (default: <out>.facts.json)")
    ap.add_argument("--tenant", default="", help="customer display name for the title")
    ap.add_argument("--account", default="", help="tenant account id, shown once in the method note")
    ap.add_argument("--site", default="")
    ap.add_argument("--narrative", help="JSON that replaces any of thesis, top_finding, summary, callouts, remediation")
    ap.add_argument("--as-of")
    a = ap.parse_args()
    now = parse_iso(a.as_of) if a.as_of else datetime.datetime.now(datetime.timezone.utc)
    skus, cat = load(os.path.join(ASSETS, "sku_tiers.json")), load(os.path.join(ASSETS, "os_catalog.json"))
    if not skus or not cat:
        sys.exit("assets/sku_tiers.json or assets/os_catalog.json is missing or unreadable")
    custom = {}
    if a.narrative:
        custom = load(a.narrative)
        if custom is None:
            sys.exit("cannot read --narrative %s" % a.narrative)
    fd, ls = feeds(a.evidence_dir), listed(a.evidence_dir)
    names = sorted(set(fd) | set(ls))
    if not names:
        sys.exit("no users__*, apps__* or devices__* dump files and no resources.json in %s" % a.evidence_dir)
    csv_rows, warns, notes = [], [], []
    for cust in names:
        F = {"feed": cust, "as_of": now.isoformat(), "sku_as_of": skus["as_of"], "os_as_of": cat["as_of"], "listed": ls.get(cust, {})}
        snaps = []
        for src in ("users", "applications", "devices"):
            path, meta = fd.get(cust, {}).get(src), ls.get(cust, {}).get(src)
            if not path:
                F[src] = {"present": False, "lists": {}, "na": []}
                continue
            recs = records(path, RES_KEY[src])
            if meta and meta.get("count") != len(recs):
                warns.append("%s %s: file holds %d records but list_resource_dumps reported %s (truncated download?)" % (cust, src, len(recs), meta.get("count")))
            if meta and meta.get("createdOn"):
                snaps.append(meta["createdOn"][:10])
            F[src] = (assess_users(recs, now, skus["skus"]) if src == "users" else assess_apps(recs, now) if src == "applications" else assess_devices(recs, now, cat))
        F["snapshot"] = max(snaps) if snaps else ""
        u = F["users"]
        F["issues"] = dict(ISSUES)
        if u.get("present") and u.get("baseline") is not None:
            over = len(u["lists"].get("priv", [])) > u["baseline"]
            F["issues"]["priv"] = ("High" if over else "Low", "Privileged roles (baseline %d)" % u["baseline"], ISSUES["priv"][2])
            F["priv_within"] = not over      # within baseline: listed in the report, not raised as a finding
        if u.get("unknown_skus"):
            notes.append("%s: %d licence ID(s) not in assets/sku_tiers.json: %s" % (cust, len(u["unknown_skus"]), ", ".join("%s (%d)" % x for x in u["unknown_skus"][:8])))
        raised = collections.Counter()
        for k, (sev, label, why) in F["issues"].items():
            items = raised_items(F, k)
            if items:
                raised[sev] += 1
            for x in items:
                csv_rows.append([cust, AREA_OF[k], sev, label, x.get("upn", ""), x.get("name", ""), x.get("detail", "")])
        F["raised"] = dict(raised)
        F["rating"] = "Elevated" if raised["Critical"] else "Moderate" if raised["High"] else "Good"
        nar = default_narrative(F)
        for k in ("thesis", "top_finding", "summary", "callouts", "remediation"):
            if k in custom:
                nar[k] = custom[k]
        tag = "" if len(names) == 1 else "__" + re.sub(r"[^A-Za-z0-9_.-]+", "_", cust)
        out = re.sub(r"(\.html?)?$", tag + ".html", a.out, count=1) if tag else a.out
        with open(out, "w") as fh:
            fh.write(render(F, nar, a))
        facts = (re.sub(r"(\.json)?$", tag + ".json", a.facts, count=1) if a.facts else re.sub(r"\.html?$", "", out) + ".facts.json")
        slim = json.loads(json.dumps({k: v for k, v in F.items() if k != "issues"}, default=str))
        for src in ("users", "applications", "devices"):
            slim[src]["counts"] = {k: len(v) for k, v in (slim[src].get("lists") or {}).items()}
            slim[src]["lists"] = {k: v[:TOP] for k, v in (slim[src].get("lists") or {}).items()}
        with open(facts, "w") as fh:
            json.dump({"facts": slim, "narrative": nar}, fh, indent=1)
        print("wrote %s | rating %s | headcount %s | admins %d (baseline %s)" % (out, F["rating"], u.get("headcount"), len(u.get("lists", {}).get("priv", [])), u.get("baseline")))
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["feed", "area", "severity", "finding", "id", "name", "detail"])
            w.writerows(csv_rows)
    for w in warns:
        print("WARNING:", w)
    for n in notes:
        print("NOTE:", n)


if __name__ == "__main__":
    main()
