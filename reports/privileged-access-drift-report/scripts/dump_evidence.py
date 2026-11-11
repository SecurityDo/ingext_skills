#!/usr/bin/env python3
"""Read the Entra snapshot resource dumps locally and write the snapshot evidence (no query needed).

  dump_evidence.py --users office365User.jsonl.gz --asof YYYY-MM-DD [--apps office365InstalledApp.jsonl.gz] [--batch 150] -o OUT_DIR

--users  the office365User dump (get_resource_dump_url, format jsonl; .jsonl, .jsonl.gz or .parquet).
--apps   the office365InstalledApp dump (optional): publisher verification for the applications granted permissions.
Writes to OUT_DIR:
  roles.json, accounts.json   the same shape as the playbook queries 1a and 1b (read by drift_evidence.py)
  apps.json                   application display names with their verified publisher (applications only, no users)
  signins_query_<n>.kql       the sign-in query (playbook 2) with the privileged accounts listed, in batches; run each with kql_search and save
                              the replies as signins_<n>.json (drift_evidence.py sums them)
  privileged_upns.txt         the privileged account names the sign-in query needs. LOCAL WORKING FILE: it names individuals, never put it in a
                              report, a reply or a commit.
Only counts, role names and application names go into the evidence files. A dump is far larger than the conversation: this script is the reader.
"""
import argparse, datetime, gzip, io, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = re.compile(r"^(helpdesk|admin|it|support|service|info|noreply)[@.]", re.I)


def records(path):
    if path.endswith(".parquet"):
        import pandas as pd
        for r in pd.read_parquet(path).to_dict("records"):
            yield r
        return
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def flat(rec):
    """The object itself, whether the dump wraps it (value / source / data) or not."""
    for k in ("value", "source", "data", "record"):
        if isinstance(rec.get(k), dict):
            return rec[k]
    return rec


def get(rec, path, default=None):
    if path in rec:
        return rec[path]
    cur = rec
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return [v] if v else []
    if hasattr(v, "tolist"):
        v = v.tolist()
    return list(v) if isinstance(v, (list, tuple)) else []


def truth(v):
    return v is True or str(v).lower() == "true"


def reply(cols, rows):
    return {"data": {"Tables": [{"TableName": "PrimaryResult", "Columns": [{"ColumnName": c, "DataType": "string"} for c in cols], "Rows": rows}]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--users", required=True); ap.add_argument("--apps"); ap.add_argument("--asof", required=True)
    ap.add_argument("--batch", type=int, default=150); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    asof = datetime.datetime.strptime(a.asof, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    roles, upns = {}, []
    c = dict(accounts=0, enabled=0, disabled=0, licensed=0, multi6=0, shared=0, noMfa=0, passwordless=0, guests=0, new90=0)
    total = 0
    for rec in records(a.users):
        total += 1
        u = flat(rec); rl = [str(x) for x in as_list(get(u, "roles"))]
        if not rl:
            continue
        upn = get(u, "userPrincipalName") or get(u, "upn") or ""
        en = truth(get(u, "accountEnabled", True)); guest = str(get(u, "userType") or "").lower() == "guest"
        for r in set(rl):
            d = roles.setdefault(r, [0, 0, 0, 0]); d[0] += 1; d[1] += en; d[2] += (not en); d[3] += guest
        c["accounts"] += 1; c["enabled"] += en; c["disabled"] += (not en); c["guests"] += guest
        c["licensed"] += len(as_list(get(u, "assignedLicenses"))) > 0; c["multi6"] += len(rl) >= 6
        c["shared"] += bool(SHARED.search(upn)); c["noMfa"] += not truth(get(u, "userRegistration.isMfaRegistered"))
        c["passwordless"] += truth(get(u, "userRegistration.isPasswordlessCapable"))
        try:
            cd = datetime.datetime.fromisoformat(str(get(u, "createdDateTime")).replace("Z", "+00:00"))
            c["new90"] += (asof - cd).days < 90
        except Exception:
            pass
        if upn:
            upns.append(upn)
    json.dump(reply(["role", "holders", "enabled", "disabled", "guests"], [[r] + [int(x) for x in v] for r, v in sorted(roles.items(), key=lambda kv: -kv[1][0])]), open(os.path.join(a.out, "roles.json"), "w"))
    json.dump(reply(list(c), [[int(v) for v in c.values()]]), open(os.path.join(a.out, "accounts.json"), "w"))
    open(os.path.join(a.out, "privileged_upns.txt"), "w").write("\n".join(upns) + "\n")
    q = ('AzureSigninLogs | where UserPrincipalName in (%s) | summarize signins=count(), ok=countif(ResultType=="0"), '
         'sfa=countif(ResultType=="0" and AuthenticationRequirement=="singleFactorAuthentication") by UserPrincipalName | '
         'summarize admins=count(), signins=sum(signins), ok=sum(ok), sfa=sum(sfa), sfaAdmins=countif(sfa>0), allSfaAdmins=countif(sfa==ok and ok>0)')
    nb = 0
    for i in range(0, len(upns), a.batch):
        nb += 1
        open(os.path.join(a.out, "signins_query_%d.kql" % nb), "w").write(q % ", ".join('"%s"' % x.replace('"', '') for x in upns[i:i + a.batch]) + "\n")
    napps = 0
    if a.apps:
        rows = []
        for rec in records(a.apps):
            u = flat(rec); nm = get(u, "displayName")
            if nm:
                rows.append([nm, str(get(u, "verifiedPublisher.displayName") or "")])
        napps = len(rows)
        json.dump(reply(["displayName", "verified"], rows), open(os.path.join(a.out, "apps.json"), "w"))
    print("users read %d | privileged accounts %d (%d roles) | sign-in query batches %d | applications %d | wrote %s" % (total, c["accounts"], len(roles), nb, napps, a.out))


if __name__ == "__main__":
    main()
