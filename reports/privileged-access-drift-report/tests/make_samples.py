#!/usr/bin/env python3
"""Write the archive-shaped sample inputs (assets/sample_evidence/*.sample.json). Synthetic numbers shaped like real download_report_archive replies:
three Privileged_Access_Drift_Report days, three inventory days, one Entra day. Run: python3 tests/make_samples.py"""
import json, os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sample_evidence")


def tbl(name, rows):
    return {"name": name, "table": {"rows": rows}}


def day(d, *objs):
    return {"entry": {"rangeFrom": d + "T00:00:00Z"}, "result": {"objects": list(objs)}}


def sources(*pairs):
    return tbl("sources", [{"source": s, "status": st} for s, st in pairs])


PAD_OK = sources(("AzureAuditLogs role events", "ok"), ("AzureAuditLogs app grants", "ok"), ("AzureAuditLogs conditional access changes", "ok"), ("AzureSigninLogs admin sign-ins", "ok"))
OUT_PIM, ADD, REM = "Add member to role outside of PIM (permanent)", "Add member to role", "Remove member from role"


def pad_day(d, outside, removed, sig, extra=()):
    ev = [{"Date": d, "activity": OUT_PIM, "role": "Global Administrator", "initiator": "Sample Provisioner", "initiatorType": "app", "outsidePim": True, "n": outside[0]},
          {"Date": d, "activity": OUT_PIM, "role": "Exchange Administrator", "initiator": "Sample Provisioner", "initiatorType": "app", "outsidePim": True, "n": outside[1]},
          {"Date": d, "activity": REM, "role": "Global Administrator", "initiator": "Sample Provisioner", "initiatorType": "app", "outsidePim": False, "n": removed}] + list(extra)
    return ev


def build():
    pad = []
    first = pad_day("2026-10-08", (6, 4), 6, 0, [
        {"Date": "2026-10-08", "activity": "Add member to role in PIM completed (permanent)", "role": "Security Administrator", "initiator": "(user)", "initiatorType": "user", "outsidePim": False, "n": 8},
        {"Date": "2026-10-08", "activity": "Remove member from role in PIM completed (permanent)", "role": "Security Administrator", "initiator": "(user)", "initiatorType": "user", "outsidePim": False, "n": 11},
        {"Date": "2026-10-08", "activity": "Add member to role completed (PIM activation)", "role": "Security Administrator", "initiator": "(user)", "initiatorType": "user", "outsidePim": False, "n": 40},
        {"Date": "2026-10-08", "activity": "Triggered PIM alert", "role": "", "initiator": "(system)", "initiatorType": "system", "outsidePim": False, "n": 1}])
    pad.append(day("2026-10-08", tbl("pad_role_events", first),
        tbl("pad_app_grants", [{"Date": "2026-10-08", "client": "Backup Connector", "appId": "app-1", "permission": "RoleManagement.ReadWrite.Directory", "n": 1},
                               {"Date": "2026-10-08", "client": "Policy Portal App", "appId": "app-2", "permission": "Sites.ReadWrite.All", "n": 1}]),
        tbl("pad_ca_changes", [{"Date": "2026-10-08", "activity": "Add conditional access policy", "policy": "Admins MFA", "n": 1}, {"Date": "2026-10-08", "activity": "Update conditional access policy", "policy": "Admins MFA", "n": 3}]),
        tbl("pad_admin_signins", [{"Date": "2026-10-08", "privileged": 66, "adminsSeen": 50, "signins": 600, "ok": 540, "failed": 60, "singleFactorOk": 270, "legacyAuth": 2, "adminsSingleFactor": 30, "adminsAllSingleFactor": 8, "batches": 1, "failedBatches": 0}]),
        PAD_OK))
    pad.append(day("2026-10-21", tbl("pad_role_events", pad_day("2026-10-21", (5, 3), 5, 0)), tbl("pad_app_grants", []), tbl("pad_ca_changes", []),
                   tbl("pad_admin_signins", [{"Date": "2026-10-21", "privileged": 66, "adminsSeen": 52, "signins": 580, "ok": 520, "failed": 60, "singleFactorOk": 280, "legacyAuth": 0, "adminsSingleFactor": 33, "adminsAllSingleFactor": 9, "batches": 1, "failedBatches": 0}]), PAD_OK))
    pad.append(day("2026-11-11", tbl("pad_role_events", pad_day("2026-11-11", (3, 3), 4, 0)), tbl("pad_app_grants", []), tbl("pad_ca_changes", []),
                   tbl("pad_admin_signins", [{"Date": "2026-11-11", "privileged": 66, "adminsSeen": 51, "signins": 640, "ok": 539, "failed": 101, "singleFactorOk": 274, "legacyAuth": 1, "adminsSingleFactor": 31, "adminsAllSingleFactor": 7, "batches": 1, "failedBatches": 0}]), PAD_OK))
    def inv(d, ga, detail, holders):
        u = {"admins": 66, "adminsNoMfa": 4}
        if detail:
            u.update({"globalAdmins": ga, "adminsEnabled": 64, "adminsLicensed": 20, "adminsStacked": 2, "adminsSharedStyle": 3, "adminsPasswordless": 10, "adminsNew90d": 5})
        objs = [tbl("o365res_users", [u])]
        if holders:
            objs.append(tbl("o365res_role_holders", [{"role": "Global Administrator", "holders": ga, "enabled": ga, "disabled": 0, "noMfa": 0, "licensed": 1, "asOf": d},
                                                     {"role": "Azure AD Joined Device Local Administrator", "holders": 4, "enabled": 4, "disabled": 0, "noMfa": 1, "licensed": 2, "asOf": d},
                                                     {"role": "User Administrator", "holders": 6, "enabled": 5, "disabled": 1, "noMfa": 0, "licensed": 3, "asOf": d}]))
        return day(d, *objs)
    inventory = [inv("2026-10-08", 0, False, False), inv("2026-10-21", 4, True, True), inv("2026-11-11", 5, True, True)]
    entra = [day("2026-11-11", {"name": "audit_facets", "value": {"orderedMap": {"valueMap": {"activity": {"sx": {"rows": [
        {"activity": "Consent to application", "count_": 3}, {"activity": "Add service principal credentials", "count_": 5}, {"activity": "Add user", "count_": 90}]}}}}}})]
    for name, data in (("pad", pad), ("inventory", inventory), ("entra", entra)):
        json.dump({"days": data}, open(os.path.join(OUT, name + "_archive.sample.json"), "w"), indent=1)
    apps = [{"appId": "app-1", "displayName": "Backup Connector", "verified": "Backup Vendor Inc."}, {"appId": "app-2", "displayName": "Policy Portal App", "verified": ""}]
    json.dump(apps, open(os.path.join(OUT, "apps.sample.json"), "w"), indent=1)


if __name__ == "__main__":
    build()
