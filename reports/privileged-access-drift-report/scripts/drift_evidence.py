#!/usr/bin/env python3
"""Merge the archived daily results of the privileged-access reports into measured evidence (counts, roles, applications; no administrator is named).

  drift_evidence.py --inventory inventory.json --pad pad.json --asof YYYY-MM-DD
                    [--entra entra.json] [--windows-archive windows_archive.json] [--apps apps.json]
                    [--rules ../assets/rating_rules.json] -o drift_evidence.json

Each archive input is the saved reply of download_report_archive (days[] of {entry, result{objects[]}}) for one scheduled report:
  --inventory        Office365_Resource_Inventory_Report   objects o365res_users, o365res_role_holders, sources     (state: the latest day is used)
  --pad              Privileged_Access_Drift_Report         objects pad_role_events, pad_app_grants, pad_ca_changes, pad_admin_signins, sources   (events: days are added)
  --entra            Office365_Entra_Activity_Report        object audit_facets (the activity breakdown gives the application activity counts)
  --windows-archive  WindowsSrv_Activity_Report             object win_trend
--apps is the apps.json written by dump_evidence.py (appId, displayName, verified publisher): it maps an application id to its publisher.
A missing optional input means that evidence was not collected; the report then lists it as a coverage gap.

How days are combined: event counts (n, sign-ins) are added; distinct-account counts per day (admins that signed in, admins with a single-factor
sign-in) use the busiest day, never a sum; the directory state (privileged accounts, holders per role) is the latest day, and the first-to-last
difference shows the change over the days the archive holds.
"""
import argparse, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    return json.load(open(path, encoding="utf-8")) if path else None


def num(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def day(s):
    return str(s or "")[:10]


def days_of(d):
    if d is None:
        return None
    if isinstance(d, dict):
        d = d.get("result", d) if "days" not in d else d
        d = d.get("days") if isinstance(d, dict) else d
    return list(d or [])


def entry_day(dy):
    return day((dy.get("entry") or {}).get("rangeFrom"))


def objects(dy):
    objs = ((dy.get("result") or {}).get("objects")) or dy.get("objects") or []
    return {o.get("name"): o for o in objs if isinstance(o, dict)}


def table_rows(obj):
    """The rows of a table object as dicts (rows are dicts or lists matched to columns)."""
    tb = (obj or {}).get("table") or {}
    cols = [c if isinstance(c, str) else c.get("name") for c in (tb.get("columns") or [])]
    return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in (tb.get("rows") or [])]


def facet_rows(obj, name):
    """The rows of one facet of a facet object (audit_facets): orderedMap.valueMap[name].sx.rows."""
    om = (((obj or {}).get("value") or {}).get("orderedMap")) or {}
    return (((om.get("valueMap") or {}).get(name) or {}).get("sx") or {}).get("rows") or []


def reply_rows(path):
    """Rows of a saved kql_search-style reply (data.Tables[0]) or a list of row dicts (apps.json)."""
    d = load(path)
    if d is None:
        return None
    if isinstance(d, list):
        return d
    d = d.get("result", d)
    tb = ((d.get("data") or d).get("Tables") or d.get("tables") or [])
    if not tb:
        return []
    t = tb[0]
    cols = [c["ColumnName"] if isinstance(c, dict) else c for c in (t.get("Columns") or t.get("columns") or [])]
    return [dict(zip(cols, r)) for r in (t.get("Rows") or t.get("rows") or [])]


def source_state(days, name):
    """'ok' when any archived day ran the scan, 'na' when every day recorded it as not available, None when no day mentions it."""
    seen = set()
    for dy in days or []:
        for r in table_rows(objects(dy).get("sources")):
            if r.get("source") == name:
                seen.add(str(r.get("status")))
    if not seen:
        return None
    return "ok" if "ok" in seen else "na"


def coverage(days, window):
    present = sorted({entry_day(dy) for dy in (days or []) if objects(dy)})
    return {"days": len(present), "expected": window, "first": present[0] if present else None, "last": present[-1] if present else None}


def windows_trend(path):
    """Sum win_trend over the archived days of WindowsSrv_Activity_Report (download_report_archive, objects win_trend). None when no day carries it."""
    t = dict(days=0, events=0, logons_ok=0, priv_logons=0, group_adds=0, accounts_created=0)
    for dy in days_of(load(path)) or []:
        tr = objects(dy).get("win_trend")
        if not tr:
            continue
        t["days"] += 1
        for r in table_rows(tr):
            t["events"] += num(r.get("events")); t["logons_ok"] += num(r.get("logonsOk")); t["priv_logons"] += num(r.get("privLogons"))
            t["group_adds"] += num(r.get("groupAdds")); t["accounts_created"] += num(r.get("accountCreated"))
    if not t["days"]:
        return None
    t["group_change_events"] = t["group_adds"] + t["accounts_created"]
    t["dc_activity"] = t["events"] > 0
    return t


def tier_of(perm, R):
    if perm in R["tier0"]:
        return 0
    if perm in R["tier1"]:
        return 1
    return 2


APP_ACTIVITIES = ("Consent to application", "Add delegated permission grant", "Add service principal credentials", "Add owner to service principal",
                  "Add owner to application", "Add service principal", "Add application")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True); ap.add_argument("--pad", required=True)
    for k in ("entra", "windows-archive", "apps"):
        ap.add_argument("--" + k)
    ap.add_argument("--asof", required=True); ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    R = json.load(open(a.rules)); K = R["key_activities"]; W = R["window_days"]
    inv = sorted(days_of(load(a.inventory)) or [], key=entry_day); pad = sorted(days_of(load(a.pad)) or [], key=entry_day); ent = days_of(load(a.entra)) if a.entra else None

    # ---- directory state (inventory archive: latest day, first-to-last change) ---------------------------------------------------
    users_days = [(entry_day(dy), (table_rows(objects(dy).get("o365res_users")) or [None])[0]) for dy in inv]
    users_days = [(d, u) for d, u in users_days if u]
    holders_days = [(entry_day(dy), table_rows(objects(dy).get("o365res_role_holders"))) for dy in inv]
    holders_days = [(d, h) for d, h in holders_days if h]
    u = users_days[-1][1] if users_days else {}
    detail = "adminsLicensed" in u
    hold = holders_days[-1][1] if holders_days else []
    roles = [{"role": r["role"], "holders": num(r["holders"]), "enabled": num(r["enabled"]), "disabled": num(r["disabled"]), "guests": 0} for r in hold]
    ga_row = next((r for r in roles if r["role"] == "Global Administrator"), None)
    n_admins = num(u.get("admins"))
    accounts = {"accounts": n_admins, "enabled": num(u.get("adminsEnabled")) if detail else n_admins,
                "disabled": max(0, n_admins - num(u.get("adminsEnabled"))) if detail else 0,
                "licensed": num(u.get("adminsLicensed")), "multi6": num(u.get("adminsStacked")), "shared": num(u.get("adminsSharedStyle")),
                "noMfa": num(u.get("adminsNoMfa")), "passwordless": num(u.get("adminsPasswordless")), "guests": 0, "new90": num(u.get("adminsNew90d"))}
    ga_holders = num(u.get("globalAdmins")) if "globalAdmins" in u else (ga_row["holders"] if ga_row else 0)
    ga = {"holders": ga_holders, "enabled": ga_row["enabled"] if ga_row else ga_holders}
    ga_by_day = {d: next((num(r["holders"]) for r in h if r["role"] == "Global Administrator"), 0) for d, h in holders_days}
    trend = [{"date": d, "admins": num(x.get("admins")), "admins_no_mfa": num(x.get("adminsNoMfa")), "global_admins": ga_by_day.get(d)} for d, x in users_days]

    # ---- administrator sign-ins (pad_admin_signins) -----------------------------------------------------------------------------
    sg = {"signins": 0, "ok": 0, "failed": 0, "sfa": 0, "legacy": 0, "seen": 0, "sf_admins": 0, "all_sf_admins": 0, "privileged": 0}
    for dy in pad:
        for r in table_rows(objects(dy).get("pad_admin_signins")):
            for k_, f in (("signins", "signins"), ("ok", "ok"), ("failed", "failed"), ("sfa", "singleFactorOk"), ("legacy", "legacyAuth")):
                sg[k_] += num(r.get(f))
            for k_, f in (("seen", "adminsSeen"), ("sf_admins", "adminsSingleFactor"), ("all_sf_admins", "adminsAllSingleFactor"), ("privileged", "privileged")):
                sg[k_] = max(sg[k_], num(r.get(f)))          # distinct accounts per day: the busiest day, never a sum
    signins = {"admins_signed_in": sg["seen"], "signins": sg["signins"], "successful": sg["ok"], "single_factor": sg["sfa"],
               "single_factor_pct": round(100.0 * sg["sfa"] / sg["ok"], 1) if sg["ok"] else None, "admins_with_single_factor": sg["sf_admins"],
               "admins_all_single_factor": sg["all_sf_admins"], "no_signin": None, "failed": sg["failed"], "legacy_auth": sg["legacy"], "peak_day_figures": True}

    st_roles = source_state(pad, "AzureAuditLogs role events"); st_grants = source_state(pad, "AzureAuditLogs app grants")
    st_ca = source_state(pad, "AzureAuditLogs conditional access changes"); st_sign = source_state(pad, "AzureSigninLogs admin sign-ins")

    # ---- role drift (pad_role_events) ----------------------------------------------------------------------------------------
    rows_ev = []
    for dy in pad:
        for r in table_rows(objects(dy).get("pad_role_events")):
            rows_ev.append((day(r.get("Date")) or entry_day(dy), r.get("activity") or "", r.get("role") or "", r.get("initiator") or "(user or system)", num(r.get("n"))))
    drift = None
    if pad and st_roles != "na":
        act = {}
        for d, ac_, rl, ini, n_ in rows_ev:
            act.setdefault(ac_, {})[ini] = act.get(ac_, {}).get(ini, 0) + n_
        tot = lambda name: sum(act.get(name, {}).values())
        by_init = {}
        for d, ac_, rl, ini, n_ in rows_ev:
            if ac_ == K["outside_pim"]:
                x = by_init.setdefault(ini, {"events": 0, "roles": {}, "first": d, "last": d})
                x["events"] += n_; x["roles"][rl] = x["roles"].get(rl, 0) + n_; x["first"] = min(x["first"], d); x["last"] = max(x["last"], d)
        automation = []
        for ini, x in by_init.items():
            human = ini in ("(user)", "(user or system)", "")
            adds = max(act.get(K["direct_add"], {}).get(ini, 0), act.get(K["outside_pim"], {}).get(ini, 0), x["events"])
            rem = act.get(K["direct_remove"], {}).get(ini, 0)
            ratio = round(rem / adds, 3) if adds else 0.0
            automation.append({"initiator": "a person" if human else ini, "human": human, "events": x["events"], "roles": len(x["roles"]),
                               "top_roles": sorted(x["roles"], key=lambda r_: -x["roles"][r_])[:5], "global_admin_events": x["roles"].get("Global Administrator", 0),
                               "removals": rem, "removal_ratio": ratio, "timeboxed": (not human) and ratio >= R["timeboxed_ratio"], "first": x["first"], "last": x["last"]})
        sel = lambda name: [(d, rl, n_) for d, ac_, rl, ini, n_ in rows_ev if ac_ == name]
        pim_add, pim_rem, tb = sel(K["pim_permanent_add"]), sel(K["pim_permanent_remove"]), sel(K["pim_timebound_add"])
        drift = {"outside_pim_events": sum(x["events"] for x in automation), "outside_pim_by_initiator": sorted(automation, key=lambda x: -x["events"]),
                 "pim_permanent_added": sum(n_ for _, _, n_ in pim_add), "pim_permanent_added_roles": sorted({rl for _, rl, _ in pim_add if rl}),
                 "pim_permanent_added_first": min([d for d, _, _ in pim_add], default=None), "pim_permanent_added_last": max([d for d, _, _ in pim_add], default=None),
                 "pim_permanent_removed": sum(n_ for _, _, n_ in pim_rem), "pim_permanent_removed_first": min([d for d, _, _ in pim_rem], default=None),
                 "pim_permanent_removed_last": max([d for d, _, _ in pim_rem], default=None), "pim_timebound_added": sum(n_ for _, _, n_ in tb),
                 "pim_activations": tot(K["pim_activation"]),
                 "pim_alerts": sum(sum(v.values()) for k_, v in act.items() if "PIM alert" in k_ and k_ != K["pim_alert_resolved"]),
                 "pim_alerts_resolved": tot(K["pim_alert_resolved"]),
                 "role_setting_changes": sum(sum(v.values()) for k_, v in act.items() if "Update role setting" in k_),
                 "role_events_total": sum(sum(v.values()) for v in act.values()), "pim_seen": any("PIM" in k_ for k_ in act)}

    # ---- applications (pad_app_grants; publisher mapped from the apps dump by application id) -------------------------------------------
    grants = []
    for dy in pad:
        for r in table_rows(objects(dy).get("pad_app_grants")):
            grants.append((day(r.get("Date")) or entry_day(dy), r.get("client") or "", r.get("appId") or "", r.get("permission") or "", num(r.get("n"))))
    apps = reply_rows(a.apps)
    pub = {x.get("appId"): x.get("verified") or "" for x in (apps or []) if x.get("appId")}
    nonhuman = None
    if pad and st_grants != "na":
        cl = {}
        for d, client, app_id, perm, n_ in grants:
            key = app_id or client or "(unnamed)"
            c = cl.setdefault(key, {"identity": client or "(unnamed)", "appId": app_id, "granted": d, "permissions": {}, "tier": 2})
            c["granted"] = min(c["granted"], d); p = perm or "(unparsed)"; t = tier_of(p, R)
            c["permissions"][p] = t; c["tier"] = min(c["tier"], t)
            c["publisher"] = ("verified: " + pub[app_id]) if pub.get(app_id) else ("not verified" if app_id in pub else "not checked")
        ai = re.compile(R["ai_app_pattern"], re.I)
        nonhuman = [{"identity": v["identity"], "granted": v["granted"], "tier": v["tier"], "publisher": v["publisher"], "ai": bool(ai.search(v["identity"])),
                     "permissions": sorted(v["permissions"], key=lambda p: (v["permissions"][p], p))} for v in cl.values()]
        nonhuman.sort(key=lambda x: (x["tier"], x["granted"]))
    app_events = {}
    for dy in ent or []:
        for r in facet_rows(objects(dy).get("audit_facets"), "activity"):
            nm = str(r.get("activity") or "").strip()
            if nm in APP_ACTIVITIES:
                app_events[nm] = app_events.get(nm, 0) + num(r.get("count_"))

    # ---- conditional access (pad_ca_changes) -------------------------------------------------------------------------------------------
    cond = None
    if pad and st_ca != "na":
        cr = [(day(r.get("Date")) or entry_day(dy), (r.get("activity") or "").lower(), num(r.get("n"))) for dy in pad for r in table_rows(objects(dy).get("pad_ca_changes"))]
        cond = {"added": sum(n_ for _, a_, n_ in cr if a_.startswith("add")), "updated": sum(n_ for _, a_, n_ in cr if a_.startswith("update")),
                "deleted": sum(n_ for _, a_, n_ in cr if a_.startswith(("delete", "remove"))), "days": sorted({d for d, _, _ in cr})}

    onprem = windows_trend(a.windows_archive) if a.windows_archive else None
    present = {"AzureAuditLogs": None if st_roles is None else st_roles == "ok", "AzureSigninLogs": None if st_sign is None else st_sign == "ok",
               "office365InstalledApp": True if apps is not None else (False if grants else None), "office365User": True if users_days else None, "WindowsAudit": None}
    archive = {"inventory": dict(coverage(inv, W), role_history_days=len(holders_days), role_history_first=holders_days[0][0] if holders_days else None, detail=detail),
               "pad": coverage(pad, W), "entra": coverage(ent, W) if ent is not None else None}
    out = {"asof": a.asof, "window_days": W, "tables_present": present, "archive": archive, "roles": roles, "accounts": accounts, "accounts_detail": detail,
           "global_admins": ga, "admin_trend": trend, "signins": signins, "drift": drift, "non_human": nonhuman, "app_events": app_events, "conditional_access": cond, "onprem": onprem}
    json.dump(out, open(a.out, "w"), indent=1)
    print("privileged accounts %d (GA %d) | single-factor %s%% | outside-PIM events %s | app grants %s | archive days: inventory %d, events %d | wrote %s" % (
        accounts["accounts"], ga["holders"], signins["single_factor_pct"], drift["outside_pim_events"] if drift else "n/a", len(nonhuman) if nonhuman is not None else "n/a",
        archive["inventory"]["days"], archive["pad"]["days"], a.out))


if __name__ == "__main__":
    main()
