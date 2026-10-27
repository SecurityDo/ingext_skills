#!/usr/bin/env python3
"""Render the compliance evidence report (self-contained HTML) from saved tool results.

Every figure is parsed from the raw MCP results saved in --evidence-dir; nothing is typed
in by hand. A missing or unparseable file renders as "not collected", never as a number.

Usage:
  build_report.py --evidence-dir DIR --tenant acme --tenant-name "Example Corp" --site Develop \
      --period 2026-09 --out report.html

Evidence files (each is the raw JSON the tool returned; KQL files hold a kql_search result):
  o365_workloads.json   kql: Office365 | summarize events=count() by Workload
  signin.json           kql: AzureSigninLogs | summarize events=count(), failed=countif(ResultType != "0"), users=dcount(UserPrincipalName)
  audit_categories.json kql: AzureAuditLogs | summarize events=count() by Category
  windows.json          kql: WindowsAudit | summarize events=count()
  behavior.json         behavior_summary_search with limit 0 and facets status, classification, scoreLevel
  users.jsonl.gz        resource dump (get_resource_dump_url): office365User
  devices.jsonl.gz      resource dump: office365Device
  ca_policies.jsonl.gz  resource dump: office365ConditionalAccessPolicy
  qualys.jsonl.gz       resource dump: qualysHost
  connectors.json       list_connectors result reduced to {"entries": [{"application", "state"}]} (no credentials)
  reports.json          list_reports result
Optional extra sources (run only for tables that list_data_tables shows):
  src_<Table>.json      kql: <Table> | summarize events=count()   (network, endpoint, cloud or identity tables; the
                        table name picks its class, see CLASSES; feeds AU-2, SC-7 and SI-3)
  ct_events.json        kql: CloudTrail | summarize events=count()
  ct_console.json       kql: CloudTrail | where eventName == "ConsoleLogin" | summarize logins=count(), failed=countif(tostring(responseElements.ConsoleLogin) == "Failure")
  ct_iam.json           kql: CloudTrail | where eventSource == "iam.amazonaws.com" and not(eventName startswith "Get" or eventName startswith "List" or eventName startswith "Describe") | summarize iam_changes=count()
  ct_root.json          kql: CloudTrail | where ['userIdentity.type'] == "Root" | summarize root_events=count()
  ct_errors.json        kql: CloudTrail | where isnotempty(errorCode) | summarize errors=count()
"""
import argparse, datetime, gzip, html, json, os, re, sys

STATUS = {
    "supported": ("Supported", "#15803d"),
    "partial": ("Partial", "#b45309"),
    "not_observed": ("Not observed", "#64748b"),
    "needs_manual_review": ("Manual review", "#6d28d9"),
}


def load(d, name):
    try:
        with open(os.path.join(d, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_dump(d, name, resource):
    """Records of a gzipped JSONL resource dump (each line wraps the record under @<resource>), or None."""
    try:
        out = []
        with gzip.open(os.path.join(d, name), "rt") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line)["@" + resource])
        return out
    except (OSError, ValueError, KeyError):
        return None


def kql_rows(res):
    """Rows of the first table of a kql_search result as a list of dicts, or None."""
    try:
        t = res["data"]["Tables"][0]
        cols = [c["ColumnName"] for c in t["Columns"]]
        return [dict(zip(cols, r)) for r in t["Rows"]]
    except (TypeError, KeyError, IndexError):
        return None


def first(res):
    rows = kql_rows(res)
    return rows[0] if rows else None


def facet(res, name):
    try:
        return {x["value"]: x["count"] for x in res["facets"][name]}
    except (TypeError, KeyError):
        return None


def n(v):
    return "{:,}".format(v) if isinstance(v, (int, float)) else "not collected"


def bars(rows, color, w=520):
    if not rows:
        return '<p class="small">No data in this window.</p>'
    mx = max(v for _, v in rows) or 1
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (w, 26 * len(rows))]
    for i, (k, v) in enumerate(rows):
        y, bw = i * 26, max(2, int((w - 300) * v / mx))
        out.append('<text x="0" y="%d" font-size="12" fill="#334155">%s</text>' % (y + 17, html.escape(k)))
        out.append('<rect x="170" y="%d" width="%d" height="16" rx="3" fill="%s"/>' % (y + 4, bw, color))
        out.append('<text x="%d" y="%d" font-size="12" fill="#334155">{:,}</text>'.format(v) % (176 + bw, y + 17))
    out.append("</svg>")
    return "".join(out)


def top_with_other(pairs, keep, other_label):
    pairs = sorted(pairs, key=lambda p: -p[1])
    head, tail = pairs[:keep], pairs[keep:]
    if tail:
        head.append(("%s (%d more)" % (other_label, len(tail)), sum(v for _, v in tail)))
    return head


# A table's class comes from its name; the first class with a matching word wins.
CLASSES = (("network", ("fortigate", "meraki", "netskope", "zscaler", "zpa", "f5", "palo", "firewall", "cisco")),
           ("endpoint", ("sentinelone", "falcon", "defender", "cortex", "crowdstrike")),
           ("cloud", ("cloudtrail", "guardduty")),
           ("identity", ("duo", "gsuite", "okta", "googleworkspace")))


def table_class(name):
    low = name.lower()
    for cls, words in CLASSES:
        if any(w in low for w in words):
            return cls
    return "other"


def hygiene(u_rec):
    """Account hygiene counts from the office365User dump (no user names)."""
    if not u_rec:
        return None
    reg = lambda r: r.get("userRegistration") or {}
    enabled = [r for r in u_rec if r.get("accountEnabled") is True]
    admins = [r for r in u_rec if reg(r).get("isAdmin") is True or r.get("roles")]
    known = sum(1 for r in u_rec if r.get("userRegistration"))
    return {"users": len(u_rec), "enabled": len(enabled), "disabled": sum(1 for r in u_rec if r.get("accountEnabled") is False),
            "guests": sum(1 for r in u_rec if r.get("userType") == "Guest"), "admins": len(admins),
            "mfa_known": known > 0,
            "enabled_mfa_registered": sum(1 for r in enabled if reg(r).get("isMfaRegistered") is True) if known else None,
            "enabled_no_mfa": sum(1 for r in enabled if reg(r).get("isMfaRegistered") is False) if known else None,
            "admins_no_mfa": sum(1 for r in admins if r.get("accountEnabled") is True and reg(r).get("isMfaRegistered") is False) if known else None}


def device_facts(d_rec, end):
    if not d_rec:
        return None
    def old(r):
        try:
            t = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(r.get("approximateLastSignInDateTime")).replace("Z", "+00:00")))
            return (end - t).days > 90
        except ValueError:
            return False
    comp_known = any(r.get("isCompliant") is not None for r in d_rec)
    man_known = any(r.get("isManaged") is not None for r in d_rec)
    return {"devices": len(d_rec), "managed": sum(1 for r in d_rec if r.get("isManaged") is True) if man_known else None,
            "non_compliant": sum(1 for r in d_rec if r.get("isCompliant") is False) if comp_known else None,
            "stale_90d": sum(1 for r in d_rec if old(r))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary-json", help="also write the control statuses as JSON (used by the CISO_monthly_report skill)")
    a = ap.parse_args()
    d = a.evidence_dir

    wl_rows = kql_rows(load(d, "o365_workloads.json"))
    o365 = sum(r["events"] for r in wl_rows) if wl_rows else None
    si = first(load(d, "signin.json"))
    au_rows = kql_rows(load(d, "audit_categories.json"))
    audit = sum(r["events"] for r in au_rows) if au_rows else None
    win = first(load(d, "windows.json"))
    win_n = win["events"] if win else None
    beh = load(d, "behavior.json")
    beh_total = beh.get("total") if beh else None
    f_status, f_class, f_score = (facet(beh, k) for k in ("status", "classification", "scoreLevel"))
    u_rec = load_dump(d, "users.jsonl.gz", "office365User")
    us = {"users": len(u_rec), "enabled": sum(1 for r in u_rec if r.get("accountEnabled") is True)} if u_rec is not None else None
    hy = hygiene(u_rec)
    d_rec = load_dump(d, "devices.jsonl.gz", "office365Device")
    yy, mm = a.period.split("-")
    period_end = datetime.datetime(int(yy) + (int(mm) == 12), int(mm) % 12 + 1, 1, tzinfo=datetime.timezone.utc)
    dv = device_facts(d_rec, period_end) if d_rec is not None else None
    ca_rec = load_dump(d, "ca_policies.jsonl.gz", "office365ConditionalAccessPolicy")
    ca_rows = ca_rec
    ca = None
    if ca_rec is not None:
        ca = {}
        for r in ca_rec:
            ca[r.get("state")] = ca.get(r.get("state"), 0) + 1
    q_rec = load_dump(d, "qualys.jsonl.gz", "qualysHost")
    qualys = len(q_rec) if q_rec is not None else None
    extra = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("src_") and fn.endswith(".json"):
            r1 = first(load(d, fn))
            extra.append({"table": fn[4:-5], "class": table_class(fn[4:-5]), "events": r1["events"] if r1 else None})
    ct = {k: first(load(d, "ct_%s.json" % k)) for k in ("events", "console", "iam", "root", "errors")}
    ct_events = ct["events"]["events"] if ct["events"] else None
    ctf = {"events": ct_events, "console_logins": ct["console"]["logins"] if ct["console"] else None, "console_failed": ct["console"]["failed"] if ct["console"] else None,
           "iam_changes": ct["iam"]["iam_changes"] if ct["iam"] else None, "root_events": ct["root"]["root_events"] if ct["root"] else None,
           "errors": ct["errors"]["errors"] if ct["errors"] else None} if any(ct.values()) else None
    net_src = [x for x in extra if x["class"] == "network" and x["events"]]
    end_src = [x for x in extra if x["class"] == "endpoint" and x["events"]]
    conns = load(d, "connectors.json")
    reps = load(d, "reports.json")
    conn_list = [(c.get("application"), c.get("state")) for c in conns.get("entries", [])] if conns else None
    rep_n = len(reps.get("entries", [])) if reps else None

    sin = si["events"] if si else None
    failed = si["failed"] if si else None
    new_inc = (f_status or {}).get("new")
    closed_inc = (f_status or {}).get("closed")
    inc_total = (new_inc or 0) + (closed_inc or 0) if f_status else None
    ca_enf = (ca or {}).get("enabled")
    ca_rep = (ca or {}).get("enabledForReportingButNotEnforced", 0)
    ca_all = sum(ca.values()) if ca else None

    mon_name = datetime.date(int(yy), int(mm), 1).strftime("%B")
    srcs_all = [("Office 365", o365), ("Entra sign-in", sin), ("Entra directory-audit", audit), ("Windows audit", win_n), ("CloudTrail", ct_events)] + [(x["table"], x["events"]) for x in extra if x["table"] != "CloudTrail"]
    srcs_on = [(lbl, v_) for lbl, v_ in srcs_all if v_]

    def logging_status():
        return "supported" if len(srcs_on) >= 2 else ("partial" if srcs_on else "not_observed")

    pct = "%.1f%%" % (100.0 * failed / sin) if sin else None
    rows = [
        ("AU-2 / AU-12", "Event logging and audit record generation", logging_status(),
         "%s events: %s." % (mon_name, ", ".join("%s %s" % (n(v_), lbl) for lbl, v_ in srcs_all if v_ is not None) or "none collected")),
        ("SI-4", "System monitoring", "supported" if beh_total else "not_observed",
         "Behavior engine produced %s summaries in the window." % n(beh_total)),
        ("AU-6", "Audit record review and analysis", "partial" if inc_total else "not_observed",
         "%s summaries became incidents; %s closed with a classification, %s still new. No review-cadence record was collected." % (n(inc_total), n(closed_inc), n(new_inc))),
        ("IR-4 / IR-5", "Incident handling and monitoring", "partial" if inc_total else "not_observed",
         "Dispositions: %s. Documented response procedure not supplied." % (", ".join("%s %s" % (v, k) for k, v in (f_class or {}).items()) or "not collected")),
        ("AC-2", "Account management", "partial" if (us or ctf) else "not_observed",
         "%s directory users (%s enabled%s)%s; directory audit categories include user and group management.%s No account-review cadence evidence." % (
             n(us["users"]) if us else "not collected", n(us["enabled"]) if us else "not collected",
             (", %s disabled, %s guests, %s with an admin role" % (n(hy["disabled"]), n(hy["guests"]), n(hy["admins"]))) if hy else "", "",
             (" CloudTrail shows %s IAM change events and %s root-account events." % (n(ctf["iam_changes"]), n(ctf["root_events"]))) if ctf and ctf["iam_changes"] is not None else "")),
        ("AC-7", "Unsuccessful logon attempts", "partial" if (si or (ctf and ctf["console_logins"] is not None)) else "not_observed",
         "%s of %s Entra sign-ins failed (%s).%s Lockout and throttling configuration was not collected." % (n(failed), n(sin), pct or "n/a",
             (" CloudTrail: %s of %s console logins failed." % (n(ctf["console_failed"]), n(ctf["console_logins"]))) if ctf and ctf["console_logins"] is not None else "")),
        ("IA-2 / IA-5", "Authentication and authenticators", "partial" if (ca or (hy and hy["mfa_known"])) else "not_observed",
         "%s%s" % ((("%s Conditional Access policies: %s enforced, %s report-only." % (n(ca_all or 0), n(ca_enf or 0), n(ca_rep))) if ca is not None else "Conditional Access policies were not collected."),
             (" %s of %s enabled users have registered MFA; %s of %s administrators lack it. Registration is not enforcement." % (n(hy["enabled_mfa_registered"]), n(hy["enabled"]), n(hy["admins_no_mfa"]), n(hy["admins"]))) if hy and hy["mfa_known"] else " MFA coverage was not collected.")),
        ("CM-8", "System component inventory", "partial" if (dv or qualys) else "not_observed",
         "%s directory devices%s; %s The inventories were not reconciled." % (n(dv["devices"]) if dv else "not collected",
             (" (%s with no sign-in in the 90 days before the period ended%s%s)" % (n(dv["stale_90d"]), (", %s non-compliant" % n(dv["non_compliant"])) if dv["non_compliant"] is not None else "", (", %s managed" % n(dv["managed"])) if dv["managed"] is not None else "")) if dv else "",
             ("%s Qualys hosts." % n(qualys)) if qualys is not None else "no Qualys host inventory.")),
        ("RA-5", "Vulnerability monitoring", "partial" if qualys else "not_observed",
         ("Qualys inventory has %s hosts. Vulnerability findings were not queried." % n(qualys)) if qualys else "No Qualys host inventory was collected, so vulnerability monitoring is not observed."),
        ("AU-4 / AU-11", "Log storage and retention", "not_observed", "Retention period and storage capacity were not collected in this run."),
        ("SC-7", "Boundary protection", "partial" if net_src else "not_observed",
         ("Network telemetry present: %s. Rules, denied traffic and segmentation were not evaluated." % ", ".join("%s %s events" % (x["table"], n(x["events"])) for x in net_src)) if net_src else "No firewall or network telemetry table is present on this tenant."),
        ("SI-3", "Malicious code protection", "partial" if end_src else "not_observed",
         ("Endpoint telemetry present: %s. Agent coverage and detections were not evaluated." % ", ".join("%s %s events" % (x["table"], n(x["events"])) for x in end_src)) if end_src else "No endpoint-protection data source is connected on this tenant."),
        ("AC-1 / IA-1 / IR-1", "Policy and procedures", "needs_manual_review", "Policy documents are customer-supplied evidence; telemetry cannot prove them."),
    ]
    cnt = {k: sum(1 for r in rows if r[2] == k) for k in STATUS}
    esc = html.escape
    trs = "".join('<tr><td class="nw">%s</td><td>%s</td><td><span class="pill" style="background:%s">%s</span></td><td>%s</td></tr>'
                  % (esc(c), esc(t), STATUS[s][1], STATUS[s][0], esc(e)) for c, t, s, e in rows)
    kp = "".join('<div class="kpi"><div class="nn" style="color:%s">%d</div><div>%s</div></div>' % (STATUS[k][1], cnt[k], STATUS[k][0]) for k in STATUS)
    ctr = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(str(x)), esc(str(y))) for x, y in (conn_list or [])) or '<tr><td colspan="2">Connector list not collected.</td></tr>'
    wl_chart = bars(top_with_other([(r["Workload"], r["events"]) for r in wl_rows], 5, "Other") if wl_rows else [], "#0f766e")
    au_chart = bars(top_with_other([(r["Category"], r["events"]) for r in au_rows], 5, "Other") if au_rows else [], "#1d4ed8")
    order = ["0", "<1000", "1000 - 2000", "2000 - 4000", "4000 - 8000", ">8000"]
    sc_chart = bars([(k, f_score[k]) for k in order if k in (f_score or {})] if f_score else [], "#b45309")
    disp = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), v) for k, v in (f_class or {}).items())
    if new_inc is not None:
        disp += "<tr><td>Still new (not triaged)</td><td>%s</td></tr>" % new_inc

    y, m = a.period.split("-")
    month = datetime.date(int(y), int(m), 1).strftime("%B %Y")
    title = "%s Compliance Evidence Report - %s" % (a.tenant_name, month)
    today = datetime.date.today().strftime("%d %B %Y")
    lead_new = ("%s of %s incidents in the window are still marked new. " % (n(new_inc), n(inc_total))) if inc_total else ""
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>
*{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;color:#0f172a;margin:0;font-size:13px;line-height:1.5}}
.wrap{{max-width:7.1in;margin:0 auto}}h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:16px;margin:22px 0 8px;border-bottom:2px solid #0f766e;padding-bottom:4px;break-after:avoid;page-break-after:avoid}}
.sub{{color:#475569;margin-bottom:12px}}.lead{{border-left:5px solid #0f766e;background:#f0fdfa;padding:10px 14px;margin:10px 0;break-inside:avoid}}
.lead b{{color:#0f766e}}.lead p{{margin:4px 0}}.kpis{{display:flex;gap:10px;margin:10px 0}}
.kpi{{flex:1;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;break-inside:avoid}}.kpi .nn{{font-size:26px;font-weight:700}}
.call{{border:1px solid #fcd34d;background:#fffbeb;border-radius:6px;padding:8px 12px;margin:10px 0;break-inside:avoid}}.call.red{{border-color:#fca5a5;background:#fef2f2}}
table{{width:100%;border-collapse:collapse;table-layout:fixed;font-size:11.5px}}th,td{{border-bottom:1px solid #e2e8f0;padding:5px 6px;text-align:left;vertical-align:top;word-wrap:break-word}}
th{{background:#f1f5f9}}tr{{break-inside:avoid}}td.nw{{white-space:nowrap;font-weight:600}}
.pill{{color:#fff;border-radius:10px;padding:1px 8px;font-size:10.5px;white-space:nowrap}}
.two{{display:flex;gap:16px}}.two>div{{flex:1;break-inside:avoid}}.fig{{break-inside:avoid;margin:8px 0}}.cap{{font-size:11px;color:#475569;margin-bottom:2px;font-weight:600}}
.small{{font-size:11px;color:#475569}}ul{{margin:4px 0 4px 18px;padding:0}}h2+*{{break-before:avoid;page-break-before:avoid}}
</style></head><body><div class="wrap"><h1>{title}</h1>
<div class="sub">Tenant: {tname} (grid account <code>{tenant}</code>) &middot; Site: {site} &middot; Evidence window: {month} &middot; Prepared {today}</div>
<div class="lead">
<p><b>What the evidence shows.</b> {logging_line}</p>
<p><b>Why it matters.</b> Controls that depend on review, identity configuration, inventory and vulnerability data are only partly evidenced, and any control with no data source on this tenant is reported as not observed.</p>
<p><b>Result.</b> 13 control groups assessed: {c_s} supported, {c_p} partial, {c_n} not observed, {c_m} needing customer documentation. {lead_new}</p>
<p><b>Evidence strength.</b> Confirmed: event volumes, incident counts, inventory counts. Inferred: the mapping of evidence to control status. Unknown: retention, MFA coverage, vulnerability findings, policy documents.</p></div>
<div class="kpis">{kp}</div>
<div class="call red"><b>Read this first.</b> This is a reduced, evidence-led view of 13 NIST SP 800-53 Rev. 5 control groups, assembled by read-only queries to the {site} connector. It is not the full Compliance Package and does not certify or attest compliance. "Not observed" means evidence was not collected in this run; it is not a failed control.</div>
<h2>Posture by control group</h2>
<table><colgroup><col style="width:13%"><col style="width:22%"><col style="width:13%"><col style="width:52%"></colgroup><tr><th>Control</th><th>Topic</th><th>Status</th><th>What the evidence shows</th></tr>{trs}</table>
<h2>Monitoring coverage</h2>
<div class="two"><div class="fig"><div class="cap">Office 365 events by workload ({o365} total)</div>{wl_chart}</div>
<div class="fig"><div class="cap">Entra directory-audit events by category ({audit} total)</div>{au_chart}</div></div>
<table><colgroup><col style="width:50%"><col style="width:50%"></colgroup><tr><th>Installed connector</th><th>State</th></tr>{ctr}</table>
<h2>Detection and incident handling</h2>
<div class="two"><div class="fig"><div class="cap">Behavior summaries by risk score ({beh} total)</div>{sc_chart}</div>
<div><div class="cap">Incident disposition</div><table><colgroup><col style="width:68%"><col style="width:32%"></colgroup><tr><th>Disposition</th><th>Count</th></tr>{disp}</table></div></div>
<h2>Gaps and next evidence</h2><ul>
<li><b>Log retention and capacity (AU-4, AU-11):</b> confirm retention settings for each index.</li>
<li><b>MFA and admin protection (IA-2, IA-5):</b> evaluate which Conditional Access policies enforce MFA and for whom.</li>
<li><b>Vulnerability findings (RA-5, SI-2):</b> pull findings, severity and age from the scanner.</li>
<li><b>Network boundary and endpoint protection (SC-7, SI-3):</b> needs a firewall or EDR data source.</li>
<li><b>Configuration evidence (CM-2, CM-6):</b> {rep} saved reports exist on the tenant; none was run for configuration evidence.</li>
<li><b>Policies and procedures (AC-1, IA-1, IR-1):</b> supplied by the customer.</li></ul>
<h2>Methodology</h2><p class="small">Evidence was gathered on {today} by read-only queries through the {site} MCP connector against account <code>{tenant}</code>: KQL over Office365, AzureSigninLogs, AzureAuditLogs and WindowsAudit; behavior-summary search; resource dumps of office365User, office365Device, office365ConditionalAccessPolicy and qualysHost; connector and report inventory. Event and incident counts are for {month}; resource-table counts are current snapshots. Control status is an analyst mapping of that evidence onto NIST SP 800-53 Rev. 5 and is not the output of the Fluency compliance engine. Companion frameworks were not produced. Individual users, case ids and comments are deliberately omitted.</p>
</div></body></html>""".format(
        title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), site=esc(a.site), month=month, today=today,
        logging_line=("Audit logging and monitoring were active in the window." if logging_status() == "supported" else "Audit logging evidence in the window is limited."),
        c_s=cnt["supported"], c_p=cnt["partial"], c_n=cnt["not_observed"], c_m=cnt["needs_manual_review"], lead_new=lead_new, kp=kp, trs=trs,
        o365=n(o365), audit=n(audit), wl_chart=wl_chart, au_chart=au_chart, ctr=ctr, beh=n(beh_total), sc_chart=sc_chart, disp=disp,
        rep=n(rep_n))
    with open(a.out, "w") as f:
        f.write(doc)
    if a.summary_json:
        with open(a.summary_json, "w") as f:
            facts = {
                "events": {"office365": o365, "signin": sin, "signin_failed": failed, "signin_users": si["users"] if si else None, "directory_audit": audit, "windows_audit": win_n},
                "workloads": [[r["Workload"], r["events"]] for r in sorted(wl_rows or [], key=lambda r: -r["events"])],
                "audit_categories": [[r["Category"], r["events"]] for r in sorted(au_rows or [], key=lambda r: -r["events"])],
                "users": us, "hygiene": hy, "devices": dv, "qualys_hosts": qualys, "behavior_summaries": beh_total,
                "cloudtrail": ctf, "sources": extra,
                "conditional_access": ({"total": (ca_all if ca else 0), "enforced": ca_enf or 0, "report_only": ca_rep, "by_state": ca} if ca is not None else None),
                "admins": {r.get("userPrincipalName", "").lower(): sorted(r.get("roles") or []) for r in (u_rec or []) if (r.get("userRegistration") or {}).get("isAdmin") is True or r.get("roles")},
                "directory_users": sorted((r.get("userPrincipalName") or "").lower() for r in (u_rec or []))[:5000],
                "note": "Resource-table counts are a snapshot as of the dump, not the report month; event counts are for the month.",
            }
            json.dump({"period": a.period, "counts": cnt, "rows": [{"control": c, "title": t, "status": s_, "evidence": e} for c, t, s_, e in rows], "facts": facts}, f, indent=1)
    print(a.out)


if __name__ == "__main__":
    sys.exit(main())
