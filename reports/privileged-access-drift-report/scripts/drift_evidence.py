#!/usr/bin/env python3
"""Turn the saved kql_search replies of the playbook into measured evidence (counts, roles, applications; no administrator is named).

  drift_evidence.py --roles roles.json --accounts accounts.json --signins signins.json [signins_2.json ...] --asof YYYY-MM-DD
                    [--role-drift role_drift.json] [--role-activity role_activity.json] [--app-grants app_grants.json]
                    [--app-events app_events.json] [--ca ca_changes.json] [--onprem onprem.json] [--apps apps.json]
                    [--tables tables.json] [--rules ../assets/rating_rules.json] -o drift_evidence.json

Each input is the saved reply of one playbook query (references/playbook.md): a JSON object with data.Tables[0] (Columns, Rows), or
a list of row dicts. A missing optional file means that evidence was not collected; the report then lists it as a coverage gap.
"""
import argparse, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))


def rows(path):
    if not path:
        return None
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, list):
        return d
    d = d.get("result", d)
    tb = ((d.get("data") or d).get("Tables") or d.get("tables") or [])
    if not tb:
        return []
    t = tb[0]
    cols = [c["ColumnName"] if isinstance(c, dict) else c for c in (t.get("Columns") or t.get("columns") or [])]
    return [dict(zip(cols, r)) for r in (t.get("Rows") or t.get("rows") or [])]


def num(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def day(s):
    return str(s or "")[:10]


def tier_of(perm, R):
    if perm in R["tier0"]:
        return 0
    if perm in R["tier1"]:
        return 1
    return 2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("roles", "accounts"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--signins", required=True, nargs="+", help="one reply, or the replies of every sign-in query batch (summed)")
    for k in ("role-drift", "role-activity", "app-grants", "app-events", "ca", "onprem", "apps", "tables"):
        ap.add_argument("--" + k)
    ap.add_argument("--asof", required=True); ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    R = json.load(open(a.rules)); K = R["key_activities"]

    # ---- human privilege (snapshot) ------------------------------------------------------------------------------------
    roles = [{"role": r["role"], "holders": num(r["holders"]), "enabled": num(r["enabled"]), "disabled": num(r["disabled"]), "guests": num(r.get("guests"))} for r in rows(a.roles)]
    acc = (rows(a.accounts) or [{}])[0]
    accounts = {k: num(acc.get(k)) for k in ("accounts", "enabled", "disabled", "licensed", "multi6", "shared", "noMfa", "passwordless", "guests", "new90")}
    ga = next((r for r in roles if r["role"] == "Global Administrator"), {"holders": 0, "enabled": 0})
    sg = {}
    for p in a.signins:
        for k, v in ((rows(p) or [{}])[0]).items():
            sg[k] = sg.get(k, 0) + num(v)
    ok, sfa = num(sg.get("ok")), num(sg.get("sfa"))
    signins = {"admins_signed_in": num(sg.get("admins")), "signins": num(sg.get("signins")), "successful": ok, "single_factor": sfa,
               "single_factor_pct": round(100.0 * sfa / ok, 1) if ok else None, "admins_with_single_factor": num(sg.get("sfaAdmins")),
               "admins_all_single_factor": num(sg.get("allSfaAdmins")),
               "no_signin": max(0, accounts["enabled"] - num(sg.get("admins")))}

    # ---- role drift ---------------------------------------------------------------------------------------------------
    rd = rows(a.role_drift); ra = rows(a.role_activity)
    drift = None
    if rd is not None or ra is not None:
        rd = rd or []; ra = ra or []
        act = {}
        for r in ra:
            act.setdefault(r["ActivityDisplayName"], {})[r["init"]] = act.get(r["ActivityDisplayName"], {}).get(r["init"], 0) + num(r["n"])
        tot = lambda name: sum(act.get(name, {}).values())
        outside = [r for r in rd if r["ActivityDisplayName"] == K["outside_pim"]]
        by_init = {}
        for r in outside:
            d = by_init.setdefault(r["init"], {"events": 0, "roles": {}, "first": None, "last": None})
            d["events"] += num(r["n"]); d["roles"][r["role"]] = d["roles"].get(r["role"], 0) + num(r["n"])
            d["first"] = min(filter(None, [d["first"], day(r.get("first"))]))
            d["last"] = max(filter(None, [d["last"], day(r.get("last"))]))
        automation = []
        for ini, d in by_init.items():
            human = ini in ("(user)", "(user or system)", "")
            adds = max(act.get(K["direct_add"], {}).get(ini, 0), act.get(K["outside_pim"], {}).get(ini, 0), d["events"])
            rem = act.get(K["direct_remove"], {}).get(ini, 0)
            ratio = round(rem / adds, 2) if adds else 0.0
            automation.append({"initiator": "a person" if human else ini, "human": human, "events": d["events"], "roles": len(d["roles"]), "top_roles": sorted(d["roles"], key=lambda x: -d["roles"][x])[:5],
                               "global_admin_events": d["roles"].get("Global Administrator", 0), "removals": rem, "removal_ratio": ratio,
                               "timeboxed": (not human) and ratio >= R["timeboxed_ratio"], "first": d["first"], "last": d["last"]})
        pim_add = [r for r in rd if r["ActivityDisplayName"] == K["pim_permanent_add"]]
        pim_rem = [r for r in rd if r["ActivityDisplayName"] == K["pim_permanent_remove"]]
        tb = [r for r in rd if r["ActivityDisplayName"] == K["pim_timebound_add"]]
        drift = {"outside_pim_events": sum(x["events"] for x in automation), "outside_pim_by_initiator": sorted(automation, key=lambda x: -x["events"]),
                 "pim_permanent_added": sum(num(r["n"]) for r in pim_add), "pim_permanent_added_roles": sorted({r["role"] for r in pim_add}),
                 "pim_permanent_added_first": min([day(r["first"]) for r in pim_add], default=None), "pim_permanent_added_last": max([day(r["last"]) for r in pim_add], default=None),
                 "pim_permanent_removed": sum(num(r["n"]) for r in pim_rem), "pim_permanent_removed_first": min([day(r["first"]) for r in pim_rem], default=None), "pim_permanent_removed_last": max([day(r["last"]) for r in pim_rem], default=None),
                 "pim_timebound_added": sum(num(r["n"]) for r in tb),
                 "pim_activations": tot(K["pim_activation"]), "pim_alerts": sum(num(r["n"]) for r in rd if "PIM alert" in r["ActivityDisplayName"] and r["ActivityDisplayName"] != K["pim_alert_resolved"]),
                 "pim_alerts_resolved": sum(num(r["n"]) for r in rd if r["ActivityDisplayName"] == K["pim_alert_resolved"]),
                 "role_setting_changes": sum(num(r["n"]) for r in rd if "Update role setting" in r["ActivityDisplayName"]),
                 "role_events_total": sum(sum(v.values()) for v in act.values()), "pim_seen": any("PIM" in k for k in act) or bool(pim_add or pim_rem or tb)}

    # ---- applications ---------------------------------------------------------------------------------------------------
    grants = rows(a.app_grants)
    nonhuman = None
    if grants is not None:
        pub = {}
        for r in (rows(a.apps) or []):
            pub[r["displayName"]] = r.get("verified") or ""
        cl = {}
        for g in grants:
            c = cl.setdefault(g["client"] or "(unnamed)", {"identity": g["client"] or "(unnamed)", "granted": day(g["day"]), "permissions": {}, "tier": 2})
            c["granted"] = min(c["granted"], day(g["day"])); p = g["perm"] or "(unparsed)"; t = tier_of(p, R)
            c["permissions"][p] = t; c["tier"] = min(c["tier"], t)
            c["publisher"] = ("verified: " + pub[g["client"]]) if pub.get(g["client"]) else ("not verified" if g["client"] in pub else "not checked")
        ai = re.compile(R["ai_app_pattern"], re.I)
        nonhuman = [{"identity": v["identity"], "granted": v["granted"], "tier": v["tier"], "publisher": v["publisher"], "ai": bool(ai.search(v["identity"])),
                     "permissions": sorted(v["permissions"], key=lambda p: (v["permissions"][p], p))} for v in cl.values()]
        nonhuman.sort(key=lambda x: (x["tier"], x["granted"]))
    ev = {r["ActivityDisplayName"].strip(): num(r["n"]) for r in (rows(a.app_events) or [])}

    # ---- conditional access -----------------------------------------------------------------------------------------------
    ca = rows(a.ca)
    cond = None
    if ca is not None:
        cond = {"added": sum(num(r["n"]) for r in ca if r["ActivityDisplayName"].lower().startswith("add")), "updated": sum(num(r["n"]) for r in ca if r["ActivityDisplayName"].lower().startswith("update")),
                "deleted": sum(num(r["n"]) for r in ca if r["ActivityDisplayName"].lower().startswith(("delete", "remove"))), "days": sorted({day(r["day"]) for r in ca})}

    # ---- on premises --------------------------------------------------------------------------------------------------------
    op = rows(a.onprem)
    onprem = None
    if op is not None:
        e = {str(num(r["EventID"])): num(r["n"]) for r in op}
        onprem = {"events": e, "group_change_events": sum(e.get(x, 0) for x in R["onprem_group_events"]), "dc_activity": any(v > 0 for k, v in e.items() if k in ("4624", "4672"))}

    tb = json.load(open(a.tables)) if a.tables else {}
    names = {t["name"].lower() for t in (tb.get("streamTables") or []) + (tb.get("resourceTables") or [])}
    present = {k: (k.lower() in names) if names else None for k in ("AzureAuditLogs", "AzureSigninLogs", "office365User", "office365InstalledApp", "WindowsAudit")}
    out = {"asof": a.asof, "window_days": R["window_days"], "tables_present": present, "roles": roles, "accounts": accounts, "global_admins": {"holders": ga["holders"], "enabled": ga["enabled"]},
           "signins": signins, "drift": drift, "non_human": nonhuman, "app_events": ev, "conditional_access": cond, "onprem": onprem}
    json.dump(out, open(a.out, "w"), indent=1)
    print("privileged accounts %d (GA %d) | single-factor %s%% | outside-PIM events %s | app grants %s | wrote %s" % (
        accounts["accounts"], ga["holders"], signins["single_factor_pct"], drift["outside_pim_events"] if drift else "n/a", len(nonhuman) if nonhuman is not None else "n/a", a.out))


if __name__ == "__main__":
    main()
