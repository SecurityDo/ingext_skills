#!/usr/bin/env python3
"""Rate privileged-access drift from the measured evidence and draft the findings JSON.

  rate_evidence.py --evidence drift_evidence.json --tenant "Name" --date YYYY-MM-DD [--rules ../assets/rating_rules.json] --out draft_findings.json

The rating and every finding come from assets/rating_rules.json and the evidence. Text is plain (the renderer escapes it). Applications and
shared-account counts are named; no individual administrator is.
"""
import argparse, datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SEVRANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def n(x):
    return "{:,}".format(int(x))


def dm(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d").strftime("%d %b").lstrip("0")


def span(a, b):
    return dm(a) if a == b else "%s – %s" % (dm(a), dm(b))


def plural(k, one, many=None):
    return "%s %s" % (n(k), one if k == 1 else (many or one + "s"))


def join(xs, k=4):
    xs = list(xs)
    return ", ".join(xs[:k]) + (" and %d more" % (len(xs) - k) if len(xs) > k else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", required=True); ap.add_argument("--tenant", required=True); ap.add_argument("--date", required=True)
    ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json")); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = json.load(open(a.rules)); E = json.load(open(a.evidence)); O = R["owners"]; M = R["mitre"]
    asof = datetime.datetime.strptime(a.date, "%Y-%m-%d"); W = E["window_days"]
    start = (asof - datetime.timedelta(days=W)).strftime("%Y-%m-%d")
    acc, sg, ga, dr, nh, ca, op = E["accounts"], E["signins"], E["global_admins"], E["drift"], E["non_human"], E["conditional_access"], E["onprem"]
    F, T, S, G = [], [], [], []

    def add(sev, title, what, why, rec, owner, when, mitre):
        F.append({"severity": sev, "title": title, "finding": what, "risk": why, "recommendation": rec, "owner": owner, "timeframe": when, "mitre": mitre})

    # ---- non-human identities ---------------------------------------------------------------------------------------------
    t0 = [x for x in (nh or []) if x["tier"] == 0]; t1 = [x for x in (nh or []) if x["tier"] == 1]
    ai1 = [x for x in t1 if x["ai"]]
    if t0:
        perms = sorted({p for x in t0 for p in x["permissions"] if p in R["tier0"]})
        add("critical", "Applications hold tenant-takeover permissions",
            "%s were granted Microsoft Graph application permissions that can take over the tenant (%s). Granted %s." % (plural(len(t0), "application"), join(perms, 6), span(min(x["granted"] for x in t0), max(x["granted"] for x in t0))),
            "Any one of these permissions lets the application make itself Global Administrator, change Conditional Access or authentication methods, or create backdoor credentials. These identities are not covered by user MFA or PIM.",
            "Confirm with each vendor which permissions the product needs and remove the rest. Restrict the applications with Conditional Access for workload identities and alert on their sign-ins from new locations.",
            O["vendor"], "7 days", M["roles"])
    # ---- administrator sign-in ---------------------------------------------------------------------------------------------
    p = sg["single_factor_pct"]
    if p is not None and p > R["sfa_medium_pct"]:
        sev = "high" if p > R["sfa_high_pct"] else "medium"
        add(sev, "Administrator sign-ins are %s single-factor" % ("overwhelmingly" if p > R["sfa_high_pct"] else "often"),
            "%s%% of %s successful sign-ins by privileged accounts in %d days completed with a single factor at sign-in time, across %d of %d privileged accounts that signed in (%d did so every time). Some of this is session reuse after an earlier MFA prompt, but it shows Conditional Access is not demanding fresh strong authentication for administrative access." % (
                "%g" % round(p), n(sg["successful"]), W, sg["admins_with_single_factor"], sg["admins_signed_in"], sg["admins_all_single_factor"]),
            "Stolen session tokens and passwords are the main route to cloud admin takeover. Without per-sign-in MFA and short sessions for admins, a phished token keeps working.",
            "Conditional Access for all directory roles: require phishing-resistant MFA (FIDO2 or Windows Hello) on every sign-in, a short sign-in frequency, and compliant devices for admin portals.",
            O["identity"], "14 days", M["accounts"])
    # ---- applications with tenant-wide data access -----------------------------------------------------------------------------
    if t1:
        add("high" if ai1 else "medium", "Applications gained tenant-wide access to business data" + (" (including AI connectors)" if ai1 else ""),
            "%s received tenant-wide read or write permissions on mail, files, sites, chats or directory objects (%s)%s." % (
                plural(len(t1), "application"), join(sorted({p for x in t1 for p in x["permissions"] if p in R["tier1"]}), 6),
                "; %d of them look like AI connectors" % len(ai1) if ai1 else ""),
            "Tenant-wide rights let an external service index or change sensitive HR, finance and regulated data. Compromise of the vendor or its secret exposes all of it.",
            "Confirm each application is sanctioned and governed by contract. Replace tenant-wide scopes with Sites.Selected or resource-specific consent where the product allows it, and review the sensitivity labels on excluded content.",
            O["m365"], "30 days", M["data"])
    # ---- role drift ----------------------------------------------------------------------------------------------------------------
    if dr and dr["outside_pim_events"]:
        top = dr["outside_pim_by_initiator"]; unsafe = [x for x in top if not x["timeboxed"]]
        lead = top[0]
        gas = sum(x["global_admin_events"] for x in top)
        txt = "%s permanent role assignments were made outside PIM in %d days, by %s. They covered %d roles%s." % (
            n(dr["outside_pim_events"]), W, join(["%s (%s)" % (x["initiator"], n(x["events"])) for x in top], 3), len({r for x in top for r in x["top_roles"]}) if len(top) > 1 else lead["roles"],
            ", including Global Administrator (%s assignments)" % n(gas) if gas else "")
        if any(x["timeboxed"] for x in top):
            tb = [x for x in top if x["timeboxed"]]
            txt += " %s logged %s removals against its additions, so the grants look time-boxed by external tooling; the net standing additions are %s." % (
                join([x["initiator"] for x in tb], 2), n(sum(x["removals"] for x in tb)), n(max(0, sum(x["events"] for x in tb) - sum(x["removals"] for x in tb))))
        add("high" if unsafe else "medium", "Roles are assigned outside PIM", txt,
            "An assignment outside PIM has no approval, no activation record and no expiry in PIM. An application that can assign Global Administrator is itself a tier-0 identity, and a gap between its additions and removals becomes standing privilege.",
            "Confirm the assigning application is sanctioned and its credentials are protected like a Global Administrator. Route the assignments through PIM, or alert on any assignment the tool does not reverse within its agreed window.",
            O["identity"], "14 days", M["roles"])
    if dr and dr["pim_permanent_added"]:
        sev = "high" if dr["pim_permanent_added"] >= 10 else "medium"
        add(sev, "Permanent role grants are still being made in PIM",
            "%s permanent (non-expiring) assignments were made in PIM (%s) while %s permanent assignments were removed%s." % (
                n(dr["pim_permanent_added"]), join(dr["pim_permanent_added_roles"], 4), n(dr["pim_permanent_removed"]), "" if not dr["pim_timebound_added"] else ", plus %s time-bound" % plural(dr["pim_timebound_added"], "assignment")),
            "Permanent assignments are what attackers look for: one compromised account yields standing control without activation, approval or audit trail.",
            "Make every directory role eligible-only, time-bound and approval-gated for sensitive roles. Require a CISO exception for a permanent grant and run quarterly PIM access reviews.",
            O["identity"], "30 days", M["manip"])
    if dr and dr["pim_alerts"] > dr["pim_alerts_resolved"]:
        add("high", "A PIM alert has no recorded resolution",
            "%s PIM alert(s) fired in %d days and %s resolution(s) were recorded." % (n(dr["pim_alerts"]), W, n(dr["pim_alerts_resolved"])),
            "PIM alerts flag roles assigned outside PIM or activated too often. An unresolved alert means the assignment was never reviewed.",
            "Review the alerted assignment, remove or convert it to eligible, and record the resolution.", O["identity"], "7 days", M["roles"])
    if dr is not None and dr["role_events_total"] == 0 and ga["holders"]:
        add("medium", "Role assignment changes cannot be observed",
            "No role-management events were recorded in %d days although %d accounts hold Global Administrator and %d accounts hold directory roles. The tenant either does not use PIM or does not forward role-management audit events." % (W, ga["holders"], acc["accounts"]),
            "A new administrator, or a role moved outside change control, would go unseen, so the drift measures in this report cannot be shown.",
            "Confirm the directory audit stream includes the RoleManagement category, and move standing roles into PIM so assignments carry approval and expiry.", O["identity"], "30 days", M["roles"])
    # ---- human privilege hygiene --------------------------------------------------------------------------------------------------
    if ga["holders"] > R["ga_max"] or (acc["accounts"] and acc["licensed"] >= acc["accounts"] / 2.0 and acc["accounts"] >= 3):
        add("medium", "Too many Global Administrators" if ga["holders"] > R["ga_max"] else "Administrator accounts carry user licences",
            "%d accounts hold Global Administrator (Microsoft recommends fewer than five). %d of %d privileged accounts carry user licences, including mail." % (ga["holders"], acc["licensed"], acc["accounts"]),
            "Licensed admin accounts receive phishing and are used for day-to-day work, turning routine browsing and email into a route to the highest privilege.",
            "Reduce standing Global Administrators to 2–4 eligible-only accounts plus two monitored break-glass accounts. Remove mail and productivity licences from admin accounts and keep daily work on separate user accounts.",
            O["identity"], "30 days", M["accounts"])
    if acc["noMfa"]:
        add("high", "Privileged accounts without a registered MFA method",
            "%d of %d privileged accounts have no registered MFA method; %d are capable of passwordless sign-in." % (acc["noMfa"], acc["accounts"], acc["passwordless"]),
            "An admin account that cannot satisfy MFA is protected by a password alone, or is exempted from the policy that would protect it.",
            "Register phishing-resistant methods for every privileged account and make Conditional Access require them; disable accounts that cannot comply.", O["identity"], "14 days", M["accounts"])
    hyg = []
    if acc["shared"]: hyg.append("%s with shared-style names (helpdesk, admin, service)" % plural(acc["shared"], "account"))
    if acc["multi6"]: hyg.append("%s holding six or more roles" % plural(acc["multi6"], "account"))
    if acc["disabled"]: hyg.append("%s still holding administrator roles while disabled" % plural(acc["disabled"], "account"))
    if sg["no_signin"] > 0 and sg["admins_signed_in"]: hyg.append("%s enabled with no interactive sign-in in %d days" % (plural(sg["no_signin"], "privileged account"), W))
    if acc["new90"]: hyg.append("%s created in the last 90 days" % plural(acc["new90"], "privileged account"))
    if hyg:
        add("medium", "Shared, stacked, dormant and orphaned privileged accounts", "Privileged accounts need clean-up: " + "; ".join(hyg) + ".",
            "Shared accounts break accountability and are rarely protected well. Dormant, disabled and stacked accounts are easy to revive or abuse unnoticed.",
            "Replace shared accounts with named, eligible-only assignments, remove roles from dormant and disabled accounts, split stacked roles into task-based groups, and add a monthly check for privileged accounts without a recent sign-in.",
            O["identity"], "14 days", "T1078 Valid Accounts")
    dl = next((r for r in E["roles"] if r["role"] == R["device_local_admin_role"]), None)
    if dl and dl["holders"] >= 3:
        add("medium", "Broad local-administrator rights on every joined device",
            "%d accounts hold “%s”, granting admin rights on every Entra-joined device. Unique local-admin passwords (LAPS) were not measured." % (dl["holders"], R["device_local_admin_role"]),
            "One compromised account in this group gives administrator access fleet-wide, the classic path to lateral movement and ransomware deployment.",
            "Cut the device local-admin role to a small eligible group, deploy Windows LAPS, and use Endpoint Privilege Management for elevation needs.", O["endpoint"], "60 days", M["local"])
    if op is not None and op["group_change_events"] == 0:
        add("medium", "On-premises privilege changes are not visible",
            "No privileged-group membership additions (4728, 4732, 4756) or account creations (4720) appear in the %s archived Windows report%s%s." % (
                plural(op["days"], "day"), " of %d" % R["windows_days"] if op["days"] < R["windows_days"] else "", "; other Windows events are arriving (%s)" % n(op["events"]) if op["dc_activity"] else ""),
            "A new Domain Admin or a backdoor account on-premises would go unseen, and investigations would lack the history insurers and forensics teams expect.",
            "Enable Audit Security Group Management and User Account Management on all domain controllers and forward those events.", O["secops"], "14 days", M["groups"])
    F.sort(key=lambda f: SEVRANK[f["severity"]])

    # ---- timeline ------------------------------------------------------------------------------------------------------------------
    if dr:
        for x in dr["outside_pim_by_initiator"]:
            T.append({"start": x["first"], "date": span(x["first"], x["last"]), "kind": "drift", "event": "%s permanent role assignments outside PIM by %s across %d roles%s." % (
                n(x["events"]), x["initiator"], x["roles"], " (%s Global Administrator)" % n(x["global_admin_events"]) if x["global_admin_events"] else "") + (" %s removals logged by the same application." % n(x["removals"]) if x["removals"] else "")})
        if dr["pim_permanent_added"]:
            T.append({"start": dr["pim_permanent_added_first"], "date": span(dr["pim_permanent_added_first"], dr["pim_permanent_added_last"]), "kind": "drift", "event": "%s permanent role assignments created in PIM: %s." % (n(dr["pim_permanent_added"]), join(dr["pim_permanent_added_roles"], 5))})
        if dr["pim_permanent_removed"]:
            T.append({"start": dr["pim_permanent_removed_first"], "date": span(dr["pim_permanent_removed_first"], dr["pim_permanent_removed_last"]), "kind": "good", "event": "%s permanent role assignments removed in PIM (standing-privilege clean-up)." % n(dr["pim_permanent_removed"])})
        if dr["pim_alerts"]:
            T.append({"start": start, "date": "In window", "kind": "drift", "event": "%s PIM alert(s) triggered; %s resolution(s) recorded." % (n(dr["pim_alerts"]), n(dr["pim_alerts_resolved"]))})
        if dr["role_setting_changes"]:
            T.append({"start": start, "date": "In window", "kind": "change", "event": "PIM role settings changed %s time(s)." % n(dr["role_setting_changes"])})
    byday = {}
    for x in (nh or []):
        byday.setdefault((x["granted"], x["tier"]), []).append(x)
    for (d, t), xs in sorted(byday.items()):
        kind = "drift" if t < 2 else "change"
        T.append({"start": d, "date": dm(d), "kind": kind, "event": "%s granted Tier %d application permissions: %s." % (join([x["identity"] for x in xs], 3), t, join(sorted({p for x in xs for p in x["permissions"]}), 4))})
    if ca and ca["days"]:
        T.append({"start": ca["days"][0], "date": span(ca["days"][0], ca["days"][-1]), "kind": "change" if not ca["added"] else "good",
                  "event": "Conditional Access: %d policy additions, %d updates, %d deletions across %d days." % (ca["added"], ca["updated"], ca["deleted"], len(ca["days"]))})
    ae = E.get("app_events") or {}
    if any(ae.values()):
        bits = [("%s consent(s)" % n(ae.get("Consent to application", 0))), ("%s delegated grant(s)" % n(ae.get("Add delegated permission grant", 0))), ("%s credential addition(s)" % n(ae.get("Add service principal credentials", 0))), ("%s new service principal(s)" % n(ae.get("Add service principal", 0)))]
        T.append({"start": start, "date": "In window", "kind": "change", "event": "Application activity: " + ", ".join(bits) + "."})
    T.sort(key=lambda x: x["start"])
    for x in T:
        x.pop("start", None)

    # ---- strengths, gaps, detections -----------------------------------------------------------------------------------------------
    if dr and dr["pim_activations"]:
        S.append("PIM is in active use: %s just-in-time role activations in %d days." % (n(dr["pim_activations"]), W))
    if dr and dr["pim_permanent_removed"]:
        S.append("%s permanent role assignments were removed through PIM during the window." % n(dr["pim_permanent_removed"]))
    if ca and (ca["added"] or ca["updated"]):
        S.append("Conditional Access is being maintained: %d policy changes on %d days in the window." % (ca["added"] + ca["updated"], len(ca["days"])))
    if acc["accounts"] and not acc["noMfa"]:
        S.append("Every privileged account has a registered MFA method%s." % ("; %d can sign in passwordless" % acc["passwordless"] if acc["passwordless"] else ""))
    if sg["single_factor_pct"] is not None and sg["single_factor_pct"] <= R["sfa_medium_pct"]:
        S.append("Only %g%% of successful administrator sign-ins were single-factor." % sg["single_factor_pct"])
    if dr and dr["outside_pim_by_initiator"] and all(x["timeboxed"] for x in dr["outside_pim_by_initiator"]):
        S.append("Assignments made outside PIM are reversed by the same tooling (removals are at least %d%% of additions), so little of it becomes standing privilege." % round(R["timeboxed_ratio"] * 100))
    if not t0 and nh is not None:
        S.append("No application was granted a tier-0 Microsoft Graph permission in the window.")
    pt = E["tables_present"]
    if pt.get("AzureAuditLogs") is False: G.append("Entra directory audit logs (AzureAuditLogs) are not collected, so role, application and Conditional Access drift could not be measured.")
    if pt.get("AzureSigninLogs") is False: G.append("Entra sign-in logs are not collected, so administrator single-factor sign-ins could not be measured.")
    if pt.get("office365InstalledApp") is False: G.append("The enterprise application inventory is not collected, so application publishers could not be verified.")
    if nh is not None and any(x["publisher"] == "not checked" for x in nh): G.append("Publisher verification of the applications granted permissions was not checked; confirm in the enterprise application inventory.")
    if op is None: G.append("The archived Windows report (WindowsSrv_Activity_Report) was not available, so on-premises privileged group changes are not covered.")
    elif op["days"] < R["windows_days"]: G.append("Only %d of %d days of the archived Windows report were available, so on-premises changes are shown for those days only; backfill the archive to cover the window." % (op["days"], R["windows_days"]))
    G.append("LAPS deployment is not measured; confirm unique local-administrator passwords on joined devices.")
    G.append("PIM-eligible (inactive) assignments are not in the user snapshot; only active role holders are counted.")
    G.append("Entra logs are retained 12 months by the platform; drift older than the %d-day window is not shown." % W)
    det = [{"name": "Role assigned outside PIM", "logic": "AzureAuditLogs ActivityDisplayName == \"Add member to role outside of PIM (permanent)\" → high-severity case, unless the initiator is an approved tool"},
           {"name": "Permanent role grant in PIM", "logic": "ActivityDisplayName contains \"in PIM completed (permanent)\" and the role is not in the approved list"},
           {"name": "Tier-0 Graph permission granted to an app", "logic": "\"Add app role assignment to service principal\" where AppRole.Value in (RoleManagement.ReadWrite.Directory, Application.ReadWrite.All, Policy.ReadWrite.*, AppRoleAssignment.ReadWrite.All, DeviceLocalCredential.Read.All, BitlockerKey.Read.All)"},
           {"name": "New credential on a privileged app", "logic": "\"Add service principal credentials\" or certificate/secret update on any app holding tier-0 or tier-1 permissions"},
           {"name": "Privileged account single-factor sign-in", "logic": "AzureSigninLogs privileged UserPrincipalName and AuthenticationRequirement == singleFactorAuthentication to admin portals"},
           {"name": "On-premises privileged group change", "logic": "WindowsAudit EventID in (4728, 4732, 4756) where the group is Domain Admins, Enterprise Admins, Schema Admins or Administrators"}]

    # ---- rating --------------------------------------------------------------------------------------------------------------------------------
    high = bool(t0) or (dr and any(not x["timeboxed"] for x in dr["outside_pim_by_initiator"])) or (dr and dr["pim_alerts"] > dr["pim_alerts_resolved"]) or (p is not None and p > R["sfa_high_pct"])
    elev = (dr and (dr["pim_permanent_added"] or dr["outside_pim_events"])) or ga["holders"] > R["ga_max"] or acc["noMfa"] or (p is not None and p > R["sfa_medium_pct"])
    rating = "High" if high else "Elevated" if elev else "Moderate" if F else "Low"

    kp = [{"label": "Privileged human accounts", "value": n(acc["accounts"]), "note": "%d enabled, %d Global Admins" % (acc["enabled"], ga["holders"])},
          {"label": "Tier-0 app grants", "value": ("%d app%s" % (len(t0), "" if len(t0) == 1 else "s")) if nh is not None else "Not observed", "note": "can assign roles & change policy" if t0 else "none in the window"},
          {"label": "Standing role grants", "value": n(dr["pim_permanent_added"] + dr["outside_pim_events"]) if dr and dr["role_events_total"] else "Not observed",
           "note": ("%s permanent in PIM, %s outside PIM" % (n(dr["pim_permanent_added"]), n(dr["outside_pim_events"]))) if dr and dr["role_events_total"] else "no role-change events recorded"},
          {"label": "Admin single-factor", "value": ("%g%%" % round(p)) if p is not None else "Not observed", "note": "of %s successful admin sign-ins" % n(sg["successful"])}]
    cnt = {s: sum(1 for f in F if f["severity"] == s) for s in SEVRANK}
    if high or elev:
        parts = []
        if t0: parts.append("applications hold tenant-takeover permissions")
        if dr and dr["outside_pim_events"]: parts.append("roles are assigned outside PIM")
        if dr and dr["pim_permanent_added"]: parts.append("permanent grants are still made in PIM")
        if p is not None and p > R["sfa_medium_pct"]: parts.append("administrator sign-ins are often single-factor")
        if ga["holders"] > R["ga_max"]: parts.append("%d Global Administrators exceed Microsoft guidance" % ga["holders"])
        jt = join(parts, 3); headline = "%s: %s" % (a.tenant, (jt[:1].upper() + jt[1:]) if parts else "privileged access shows drift")
    elif F:
        headline = "%s privileged access is largely controlled, with hygiene gaps to close" % a.tenant
    else:
        headline = "%s privileged access shows no drift in the window" % a.tenant
    summ = ["%s has %s privileged accounts (%d enabled, %d Global Administrators). %s" % (
        a.tenant, n(acc["accounts"]), acc["enabled"], ga["holders"],
        ("Over the last %d days %s just-in-time activations were recorded and %s permanent role assignments were removed through PIM." % (W, n(dr["pim_activations"]), n(dr["pim_permanent_removed"]))) if dr and dr["pim_seen"] else
        ("No role-management events were recorded, so role drift could not be measured." if dr is not None else "Role drift was not measured because directory audit logs are not available."))]
    mid = []
    if dr and dr["outside_pim_events"]: mid.append("%s permanent role assignments were made outside PIM (%s)" % (n(dr["outside_pim_events"]), join([x["initiator"] for x in dr["outside_pim_by_initiator"]], 2)))
    if dr and dr["pim_permanent_added"]: mid.append("%s new permanent grants were made in PIM" % n(dr["pim_permanent_added"]))
    if t0 or t1: mid.append("%s gained tier-0 or tier-1 permissions" % plural(len(t0) + len(t1), "application"))
    if p is not None and p > R["sfa_medium_pct"]: mid.append("%g%% of successful administrator sign-ins were single-factor" % round(p))
    if mid: summ.append("Privilege drift in the window: " + "; ".join(mid) + ".")
    asks = []
    if t0: asks.append("approve an immediate review of the %d tier-0 application(s) with the vendor" % len(t0))
    if (dr and (dr["outside_pim_events"] or dr["pim_permanent_added"])) or ga["holders"] > R["ga_max"]: asks.append("mandate that all directory roles are eligible-only in PIM (no new permanent grants without CISO exception)")
    if p is not None and p > R["sfa_medium_pct"]: asks.append("require phishing-resistant MFA on every administrator sign-in")
    if acc["noMfa"]: asks.append("register MFA for every privileged account")
    ask = (", ".join(asks[:-1]) + (", and " if len(asks) > 1 else "") + asks[-1] + ". Re-run this report monthly to track drift.") if asks else "keep the monthly run of this report and review any new finding."
    ev = [{"source": "office365User", "reference": "privileged role holders, licences, MFA registration (snapshot)"},
          {"source": "AzureSigninLogs", "reference": "administrator sign-ins and authentication requirement, %d days" % W},
          {"source": "AzureAuditLogs", "reference": "RoleManagement, application consent and Conditional Access activity, %d days" % W}]
    if op is not None: ev.append({"source": "WindowsSrv_Activity_Report (archive)", "reference": "group additions and account creations, %d archived days" % op["days"]})
    out = {"tenant": a.tenant, "assessment_date": a.date, "window_days": W, "period_label": "%s – %s" % (datetime.datetime.strptime(start, "%Y-%m-%d").strftime("%d %b").lstrip("0"), asof.strftime("%d %b %Y").lstrip("0")),
           "drift_rating": rating, "kpis": kp, "headline": headline, "summary": summ, "ciso_ask": ask, "counts": cnt, "timeline": T, "findings": F,
           "non_human": nh or [], "role_inventory": [], "strengths": S, "coverage_gaps": G, "detections_to_add": det, "evidence": ev}
    sens = {r: i for i, r in enumerate(R["sensitive_roles"])}
    inv = sorted(E["roles"], key=lambda r: (sens.get(r["role"], 99), -r["holders"], r["role"]))
    notes = {"Global Administrator": "Above Microsoft guidance" if ga["holders"] > R["ga_max"] else "Within guidance (4 or fewer)", R["device_local_admin_role"]: "Admin on every joined device",
             "User Administrator": "Can reset most passwords", "Authentication Administrator": "Can reset MFA for non-admins", "Privileged Authentication Administrator": "Can reset MFA for any user"}
    for r in inv[:14]:
        out["role_inventory"].append({"role": r["role"], "holders": r["holders"], "enabled": r["enabled"], "disabled": r["disabled"], "note": notes.get(r["role"], ("Holders include disabled accounts" if r["disabled"] else ""))})
    rest = inv[14:]
    if rest:
        out["role_inventory"].append({"role": "%d other roles" % len(rest), "holders": sum(r["holders"] for r in rest), "enabled": sum(r["enabled"] for r in rest), "disabled": sum(r["disabled"] for r in rest), "note": "Lower-risk roles, grouped"})
    json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False)
    print("drift rating %s | findings %s | timeline %d | wrote %s" % (rating, ", ".join("%d %s" % (v, k) for k, v in cnt.items() if v), len(T), a.out))


if __name__ == "__main__":
    main()
