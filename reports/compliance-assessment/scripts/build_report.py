#!/usr/bin/env python3
"""Render the compliance evidence report (self-contained HTML) from saved tool results.

Every figure is parsed from the raw MCP results saved in --evidence-dir; nothing is typed
in by hand. A missing or unparseable file renders as "not collected", never as a number.

Usage:
  build_report.py --evidence-dir DIR --tenant acme --tenant-name "Example Corp" --site Develop \
      --period 2026-09 --out report.html [--summary-json compliance_summary.json] \
      [--history-dir DIR | --prior-summary PATH]

Evidence files (each is the raw JSON the tool returned; KQL files hold a kql_search result):
  windows.json          kql: WindowsAudit | summarize events=count()
  behavior.json         behavior_summary_search with limit 0 and facets status, classification, scoreLevel
  users.jsonl.gz        resource dump (get_resource_dump_url): office365User
  devices.jsonl.gz      resource dump: office365Device
  ca_policies.jsonl.gz  resource dump: office365ConditionalAccessPolicy
  qualys.jsonl.gz       resource dump: qualysHost
  guardduty.jsonl.gz    resource dump: GuarddutyFinding (optional)
  gsuite_users.jsonl.gz resource dump: gsuiteUser (optional)
  apps.jsonl.gz         resource dump: office365Application (optional; app registrations and their secrets)
  enterprise_apps.jsonl.gz resource dump: office365InstalledApp (optional; enterprise applications, i.e. service principals)
  groups.jsonl.gz       resource dump: office365Group (optional)
  mde_machine.jsonl.gz, mde_avhealth.jsonl.gz, mde_vulnerability.jsonl.gz, mde_secureconfig.jsonl.gz,
  mde_recommendation.jsonl.gz, mde_securescore.jsonl.gz
  tenable_asset.jsonl.gz, tenable_agent.jsonl.gz, tenable_plugin.jsonl.gz   resource dumps: tenableAsset, tenableAgent, tenablePlugin (optional)
  sentinelone_agent.jsonl.gz, sentinelone_threat.jsonl.gz                   resource dumps: sentinelOneAgent, sentinelOneThreat (optional)
  falcon_agent.jsonl.gz                                                     resource dump: falconAgent (optional)
                        resource dumps: msDefender* (optional; streamed and reduced to counts, so the 5-million-row
                        vulnerability dump is fine). Feed RA-5, SI-3, CM-8 and the key findings.
  gsuite_groups.jsonl.gz resource dump: gsuiteGroup (optional)
  connectors.json       list_connectors result reduced to {"entries": [{"application", "state"}]} (no credentials)
  reports.json          list_reports result
Optional extra sources (run only for tables that list_data_tables shows):
  src_<Table>.json      kql: <Table> | summarize events=count()   (network, endpoint, cloud or identity tables; the
                        table name picks its class, see CLASSES; feeds AU-2, SC-7 and SI-3). An empty result
                        ({"total": 0}) is read as zero events in the window, which is itself reported.
  history_<Table>.json  kql: <Table> | summarize oldest=min(<time column>), newest=max(<time column>) with a wide
                        rangeFrom (a year or more before the period). Gives the history depth actually observed.
  ct_archive*.json      CloudTrail comes ONLY from the daily archive of the scheduled report CloudTrail_Activity_Report:
                        download_report_archive for the month, saved as received (objects=["trend"] keeps it small).
                        CloudTrail is never searched: there is no ct_*, src_CloudTrail or history_CloudTrail query.
                        The per-day trend rows are summed over the period; a day not archived is a gap, never zero.
                        With --require-cloudtrail the build stops (exit 3) when no day of the period is archived.
  m365_archive*.json    Office 365 and Entra counts come ONLY from the daily archive of the scheduled report
                        Office365_Entra_Activity_Report: download_report_archive for the month, saved as received
                        (objects o365_trend, o365_facets, signin_trend, audit_trend, audit_facets, sp_trend, ni_trend and
                        sources keep it small). Office365, AzureSigninLogs, AzureAuditLogs, AADServicePrincipalSignInLogs
                        and AADNonInteractiveUserSignInLogs are never searched. Trend rows are summed over the period; a
                        day not archived is a gap, and a table the tenant lacks is "not available", never zero. Distinct
                        users are not available from an archive and are not reported.
                        With --require-m365 the build stops (exit 3) when no day of the period is archived.
"""
import argparse, collections, datetime, gzip, html, json, os, re, sys

UTC = datetime.timezone.utc

STATUS = {
    "supported": ("Supported", "#15803D"),
    "partial": ("Partial", "#B45309"),
    "not_observed": ("Not observed", "#64748B"),
    "needs_manual_review": ("Manual review", "#1D4ED8"),
}
RANK = {"not_observed": 0, "needs_manual_review": 0, "partial": 1, "supported": 2}
SEV = {"high": ("High", "#B91C1C", 0), "medium": ("Medium", "#B45309", 1), "low": ("Low", "#1D4ED8", 2)}

# Analyst thresholds for the key-findings panel. They flag what to look at; they are not compliance limits.
STALE_SHARE = 0.5      # share of directory devices with no sign-in in 90 days
CONSOLE_FAIL = 0.10    # share of failed cloud console logins
SIGNIN_FAIL = 0.05     # share of failed Entra sign-ins
SP_SECRET_FAIL = 0.01  # share of service-principal sign-ins that failed on an expired or invalid client secret
ADMIN_SHARE = 0.25     # share of enabled users holding an admin role
HIGH_SEVERITY = 7.0    # GuardDuty numeric severity at which a finding is High
CONFIG_FAIL = 0.25     # share of applicable Defender secure-configuration checks failing
AV_STALE = 0.05        # share of Defender AV devices with out-of-date signatures
AGED_DAYS = 30         # age at which a critical vulnerability is flagged as aged
SCAN_DAYS = 30         # a host not scanned or seen in this many days before the period ended is flagged
AGENT_BAD = 0.05       # share of endpoint agents out of date or off protection at which a finding is Medium

CSS = """:root{--navy:#14213d;--ink:#1f2937;--mut:#64748b;--line:#e2e8f0;--bg:#f4f6fa;--card:#fff;--acc:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:0 28px 48px}
.hero{background:linear-gradient(135deg,#0f1a33 0%,#1d3461 100%);color:#fff;padding:38px 0 70px}
.hero .wrap{padding-bottom:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:#9db4e0;font-weight:600}
.hero h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}
.chips{margin-top:18px}.chip{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#e6edfb;border-radius:999px;padding:3px 12px;font-size:12px;margin:0 8px 6px 0}
.chip code{font-family:ui-monospace,Menlo,Consolas,monospace}
.kpis{display:grid;grid-template-columns:repeat(var(--k,4),1fr);gap:14px;margin-top:-46px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,26,51,.06);border-top:4px solid var(--c)}
.kpi b{display:block;font-size:32px;line-height:1.1;color:var(--c)}.kpi span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.kpi small{display:block;margin-top:4px;font-size:11px;color:var(--mut)}.up{color:#15803D!important}.down{color:#B91C1C!important}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-top:18px;box-shadow:0 1px 4px rgba(15,26,51,.04)}
.panel p{margin:6px 0}.panel p:first-child{margin-top:0}.panel p:last-child{margin-bottom:0}
h2{font-size:18px;margin:34px 0 4px;color:var(--navy);display:flex;align-items:center;gap:10px;break-after:avoid;page-break-after:avoid}
h2 .n{background:var(--navy);color:#fff;border-radius:6px;font-size:12px;padding:2px 8px;font-weight:600}
.read{border-left:4px solid var(--acc);background:#eff4ff;border-radius:0 10px 10px 0;padding:14px 18px;margin-top:18px;color:#1e3a8a;break-inside:avoid}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}.bar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:16px;color:var(--mut);font-size:12px}.legend em{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed;font-size:13px}
th{background:#f1f5f9;color:#475569;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0}
td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:#f8fafc}
td.ctl{border-left:4px solid var(--c);font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;color:var(--navy)}
.tw{border:1px solid var(--line);border-radius:12px;overflow:hidden;overflow:clip;background:var(--card);margin-top:10px}
.pill{display:inline-block;color:#fff;border-radius:999px;padding:2px 11px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--c)}
.small{font-size:12px;color:var(--mut)}.cap{font-size:12px;color:var(--navy);margin-bottom:4px;font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px;align-items:start}.two>div{min-width:0}
.two .panel{margin-top:0}.fig{break-inside:avoid}.fig svg{display:block;max-width:100%;height:auto}
.gaps{margin:0;padding-left:20px}.gaps li{margin:5px 0}
.act{color:#334155;font-size:12.5px;margin-top:4px}.zero{color:#B45309;font-weight:600}
.chg{font-size:12px;white-space:nowrap}.chg.better{color:#15803D;font-weight:600}.chg.worse{color:#B91C1C;font-weight:600}.chg.same{color:var(--mut)}
.foot{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}.foot p{margin:4px 0}
@media (max-width:760px){.kpis{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.hero h1{font-size:24px}}
@media print{body{background:#fff}.wrap{max-width:none;padding:0 0 16px}.hero{border-radius:12px;padding:26px 0 62px}.hero .wrap{padding:0 24px}.kpis{grid-template-columns:repeat(var(--k,4),1fr);margin:-46px 14px 0}.two{grid-template-columns:1fr 1fr}tr,.card,.kpi,.panel,.fig,.read{break-inside:avoid}.tw.keep{break-inside:avoid}th{position:static}.hero,.kpi,.pill,.bar i,td.ctl,.read,.n,.legend em,.chip{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


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


def kql_events(res):
    """Event count of a `summarize events=count()` result. An empty result (total 0, no table) is zero events."""
    r1 = first(res)
    if r1:
        return r1.get("events")
    if isinstance(res, dict) and res.get("total") == 0 and "data" not in res:
        return 0
    return None


def facet(res, name):
    try:
        return {x["value"]: x["count"] for x in res["facets"][name]}
    except (TypeError, KeyError):
        return None


def n(v):
    return "{:,}".format(v) if isinstance(v, (int, float)) else "not collected"


def parse_ts(s):
    try:
        t = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(s).replace("Z", "+00:00")))
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    except ValueError:
        return None


def bars(rows, color, w=380, suffix=""):
    if not rows:
        return '<p class="small">No data in this window.</p>'
    mx = max(v for _, v in rows) or 1
    lab, right = 152, 66
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img">' % (w, 28 * len(rows))]
    for i, (k, v) in enumerate(rows):
        y, bw = i * 28, max(2, int((w - lab - right) * v / mx))
        out.append('<text x="0" y="%d" font-size="14" fill="#334155">%s</text>' % (y + 18, html.escape(k)))
        out.append('<rect x="%d" y="%d" width="%d" height="17" rx="3" fill="%s"/>' % (lab, y + 4, bw, color))
        out.append('<text x="%d" y="%d" font-size="14" fill="#334155">%s%s</text>' % (lab + 6 + bw, y + 18, "{:,}".format(v), suffix))
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
        t = parse_ts(r.get("approximateLastSignInDateTime"))
        return bool(t) and (end - t).days > 90
    comp_known = any(r.get("isCompliant") is not None for r in d_rec)
    man_known = any(r.get("isManaged") is not None for r in d_rec)
    return {"devices": len(d_rec), "managed": sum(1 for r in d_rec if r.get("isManaged") is True) if man_known else None,
            "non_compliant": sum(1 for r in d_rec if r.get("isCompliant") is False) if comp_known else None,
            "stale_90d": sum(1 for r in d_rec if old(r))}


def guardduty_facts(g_rec, start, end):
    """GuardDuty findings from the resource dump: latest snapshot per finding id, no resource names."""
    if g_rec is None:
        return None
    latest = {}
    for r in g_rec:
        k = r.get("Id")
        if k is None:
            continue
        if k not in latest or str(r.get("UpdatedAt")) > str(latest[k].get("UpdatedAt")):
            latest[k] = r
    def sev(r):
        try:
            return float(r.get("Severity"))
        except (TypeError, ValueError):
            return 0.0
    def archived(r):
        return bool((r.get("Service") or {}).get("Archived"))
    openf = [r for r in latest.values() if not archived(r)]
    inwin = [r for r in latest.values() if (parse_ts(r.get("UpdatedAt")) or start) >= start and (parse_ts(r.get("UpdatedAt")) or start) < end]
    types = collections.Counter(str(r.get("Type")) for r in openf)
    return {"findings": len(latest), "open": len(openf), "high_open": sum(1 for r in openf if sev(r) >= HIGH_SEVERITY),
            "updated_in_period": len(inwin), "high_updated_in_period": sum(1 for r in inwin if sev(r) >= HIGH_SEVERITY),
            "top_types": types.most_common(5)}


def gsuite_facts(g_rec):
    if g_rec is None:
        return None
    admins = [r for r in g_rec if r.get("isAdmin") is True or r.get("isDelegatedAdmin") is True]
    return {"users": len(g_rec), "suspended": sum(1 for r in g_rec if r.get("suspended") is True), "admins": len(admins),
            "enrolled_2sv": sum(1 for r in g_rec if r.get("isEnrolledIn2Sv") is True),
            "admins_2sv": sum(1 for r in admins if r.get("isEnrolledIn2Sv") is True)}


MS_TENANTS = ("f8cdef31-a31e-4b4a-93e4-5f571e91255a", "72f988bf-86f1-41af-91ab-2d7cd011db47")   # Microsoft first-party owner tenants
LONG_SECRET_DAYS = 730   # client secret valid for more than two years


def app_facts(a_rec, end):
    """App registrations (office365Application dump): credential hygiene and requested permissions. No names or secret values."""
    if a_rec is None:
        return None
    pw = [c for r in a_rec for c in (r.get("passwordCredentials") or [])]
    def when(c, k):
        return parse_ts(c.get(k))
    expired = [c for c in pw if when(c, "endDateTime") and when(c, "endDateTime") < end]
    soon = [c for c in pw if when(c, "endDateTime") and end <= when(c, "endDateTime") < end + datetime.timedelta(days=90)]
    longlived = [c for c in pw if when(c, "endDateTime") and when(c, "startDateTime") and (when(c, "endDateTime") - when(c, "startDateTime")).days > LONG_SECRET_DAYS]
    apponly = {r.get("id") for r in a_rec for req in (r.get("requiredResourceAccess") or []) for x in (req.get("resourceAccess") or []) if x.get("type") == "Role"}
    return {"apps": len(a_rec), "secrets": len(pw), "certificates": sum(len(r.get("keyCredentials") or []) for r in a_rec),
            "secrets_expired": len(expired), "secrets_expiring_90d": len(soon), "secrets_long_lived": len(longlived),
            "apps_no_credentials": sum(1 for r in a_rec if not (r.get("passwordCredentials") or r.get("keyCredentials"))),
            "apps_app_only_permissions": len(apponly),
            "multi_tenant": sum(1 for r in a_rec if r.get("signInAudience") in ("AzureADMultipleOrgs", "AzureADandPersonalMicrosoftAccount", "PersonalMicrosoftAccount"))}


def enterprise_app_facts(s_rec, a_rec):
    """Enterprise applications (office365InstalledApp dump holds service principals, not software installed on devices)."""
    if s_rec is None:
        return None
    own = {r.get("appId") for r in (a_rec or [])}
    ms = [r for r in s_rec if r.get("appOwnerOrganizationId") in MS_TENANTS]
    other = [r for r in s_rec if r.get("appOwnerOrganizationId") not in MS_TENANTS]
    ext = [r for r in other if r.get("appId") not in own and r.get("appOwnerOrganizationId")]
    return {"total": len(s_rec), "enabled": sum(1 for r in s_rec if r.get("accountEnabled") is True), "disabled": sum(1 for r in s_rec if r.get("accountEnabled") is False),
            "microsoft_owned": len(ms), "registered_here": sum(1 for r in s_rec if r.get("appId") in own),
            "third_party": len(ext), "assignment_required": sum(1 for r in s_rec if r.get("appRoleAssignmentRequired") is True),
            "with_credentials": sum(1 for r in s_rec if r.get("passwordCredentials") or r.get("keyCredentials"))}


def group_facts(g_rec):
    """Entra / Microsoft 365 groups (office365Group dump): counts only, no names or members."""
    if g_rec is None:
        return None
    return {"groups": len(g_rec), "security_enabled": sum(1 for r in g_rec if r.get("securityEnabled") is True),
            "microsoft365": sum(1 for r in g_rec if "Unified" in (r.get("groupTypes") or [])),
            "public": sum(1 for r in g_rec if r.get("visibility") == "Public"),
            "role_assignable": sum(1 for r in g_rec if r.get("isAssignableToRole") is True),
            "dynamic": sum(1 for r in g_rec if "DynamicMembership" in (r.get("groupTypes") or [])),
            "empty": sum(1 for r in g_rec if not (r.get("members") or [])),
            "members_total": sum(len(r.get("members") or []) for r in g_rec)}


def gsuite_group_facts(g_rec):
    """Google Workspace groups (gsuiteGroup dump): membership shape, no addresses."""
    if g_rec is None:
        return None
    ext_groups = owner_less = members = 0
    for r in g_rec:
        dom = str((r.get("Group") or {}).get("email", "")).rpartition("@")[2].lower()
        mem = r.get("Members") or []
        members += len(mem)
        if any(str(m.get("email", "")).rpartition("@")[2].lower() != dom for m in mem if m.get("type") == "USER" and dom):
            ext_groups += 1
        if not any(m.get("role") == "OWNER" for m in mem):
            owner_less += 1
    return {"groups": len(g_rec), "members": members, "with_external_members": ext_groups, "without_owner": owner_less}


def iter_dump(d, name, resource):
    """Stream the records of a gzipped JSONL resource dump (large dumps are never held in memory); yields nothing if missing."""
    try:
        with gzip.open(os.path.join(d, name), "rt") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)["@" + resource]
                    except (ValueError, KeyError):
                        continue
    except OSError:
        return


def mde_facts(d, period_end, used):
    """Microsoft Defender for Endpoint resource dumps, streamed and reduced to counts. No device names, CVE ids or paths are kept.
    Files: mde_machine, mde_avhealth, mde_vulnerability, mde_secureconfig, mde_recommendation, mde_securescore (all .jsonl.gz)."""
    out = {}
    def have(fn):
        return os.path.exists(os.path.join(d, fn))
    if have("mde_machine.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "mde_machine.jsonl.gz", "msDefenderMachine"):
            c["devices"] += 1
            c["onboarded"] += r.get("onboardingStatus") == "Onboarded"
            c["can_onboard"] += r.get("onboardingStatus") == "CanBeOnboarded"
            c["inactive"] += r.get("healthStatus") not in (None, "Active")
            c["high_exposure"] += r.get("exposureLevel") == "High"
            c["high_risk"] += r.get("riskScore") == "High"
        if c["devices"]:
            out["machines"] = dict(c); used.append("msDefenderMachine")
    if have("mde_avhealth.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "mde_avhealth.jsonl.gz", "msDefenderAvHealth"):
            c["devices"] += 1
            c["sig_stale"] += r.get("avIsSignatureUpToDate") == "False"
            c["engine_stale"] += r.get("avIsEngineUpToDate") == "False"
            c["platform_stale"] += r.get("avIsPlatformUpToDate") == "False"
            c["scan_not_completed"] += r.get("quickScanResult") not in ("Completed",)
        if c["devices"]:
            out["av"] = dict(c); used.append("msDefenderAvHealth")
    if have("mde_vulnerability.jsonl.gz"):
        cutoff = period_end - datetime.timedelta(days=AGED_DAYS)
        c = collections.Counter(); devs, exp_devs = set(), set()
        for r in iter_dump(d, "mde_vulnerability.jsonl.gz", "msDefenderVulnerability"):
            cve = r.get("CveId") or r.get("cveId")
            if not cve:
                continue
            c["findings"] += 1
            dev = r.get("DeviceId") or r.get("machineId")
            devs.add(dev)
            sev = r.get("VulnerabilitySeverityLevel") or r.get("severity")
            if sev == "Critical":
                c["critical"] += 1
                t = parse_ts(r.get("FirstSeenTimestamp"))
                if t and t < cutoff:
                    c["critical_aged"] += 1
            elif sev == "High":
                c["high"] += 1
            if r.get("ExploitabilityLevel") in ("ExploitIsPublic", "ExploitIsVerified", "ExploitIsInKit"):
                c["exploit"] += 1; exp_devs.add(dev)
            if r.get("SecurityUpdateAvailable") is False:
                c["no_patch"] += 1
        if c["findings"]:
            out["vuln"] = dict(c, devices=len(devs), exploit_devices=len(exp_devs)); used.append("msDefenderVulnerability")
    if have("mde_secureconfig.jsonl.gz"):
        c = collections.Counter(); bad_devs = set(); cats = collections.Counter()
        for r in iter_dump(d, "mde_secureconfig.jsonl.gz", "msDefenderSecureConfig"):
            if r.get("isApplicable") is not True:
                continue
            c["checks"] += 1
            if r.get("isCompliant") is False:
                c["noncompliant"] += 1; bad_devs.add(r.get("deviceId")); cats[r.get("configurationCategory") or "Other"] += 1
        if c["checks"]:
            out["config"] = dict(c, devices_with_gaps=len(bad_devs), by_category=cats.most_common(5)); used.append("msDefenderSecureConfig")
    if have("mde_recommendation.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "mde_recommendation.jsonl.gz", "msDefenderRecommendation"):
            c["total"] += 1
            c["active"] += r.get("status") == "Active"
            c["public_exploit"] += r.get("publicExploit") is True
            c["active_alert"] += r.get("activeAlert") is True
        if c["total"]:
            out["recommendations"] = dict(c); used.append("msDefenderRecommendation")
    if have("mde_securescore.jsonl.gz"):
        for r in iter_dump(d, "mde_securescore.jsonl.gz", "msDefenderSecureScore"):
            out["secure_score"] = {"score": r.get("score"), "time": r.get("time")}; used.append("msDefenderSecureScore")
            break
    return out or None


def _cutoff(end, days):
    return end - datetime.timedelta(days=days)


def vendor_facts(d, period_end, q_rec, used):
    """Vulnerability scanners (Tenable, Qualys) and endpoint protection (SentinelOne, CrowdStrike Falcon) from resource dumps.
    Streamed and reduced to counts; no host names, addresses or file paths are kept."""
    out = {}
    cut = _cutoff(period_end, SCAN_DAYS)
    def have(fn):
        return os.path.exists(os.path.join(d, fn))
    # Tenable
    if have("tenable_asset.jsonl.gz") or have("tenable_agent.jsonl.gz") or have("tenable_plugin.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "tenable_asset.jsonl.gz", "tenableAsset"):
            if r.get("deleted_at") or r.get("terminated_at"):
                continue
            c["assets"] += 1
            t = parse_ts(r.get("last_scan_time"))
            c["scanned_recent"] += bool(t and t >= cut)
            c["authenticated"] += bool(r.get("last_authenticated_scan_date"))
            c["with_agent"] += r.get("has_agent") is True
        for r in iter_dump(d, "tenable_agent.jsonl.gz", "tenableAgent"):
            c["agents"] += 1
            c["agents_on"] += r.get("status") == "on"
        for r in iter_dump(d, "tenable_plugin.jsonl.gz", "tenablePlugin"):
            try:
                hits = int(r.get("hitCount") or 0)
            except (TypeError, ValueError):
                hits = 0
            if r.get("risk_factor") in ("critical", "high"):
                c[r["risk_factor"] + "_hits"] += hits
                c[r["risk_factor"] + "_plugins"] += 1 if hits else 0
        if c["assets"] or c["agents"] or c["critical_hits"] or c["high_hits"]:
            out["tenable"] = dict(c); used.append("tenableAsset / tenableAgent / tenablePlugin")
    # Qualys (host inventory dump, already loaded)
    if q_rec:
        c = collections.Counter()
        for r in q_rec:
            c["hosts"] += 1
            ai = r.get("agentInfo") or {}
            if str(r.get("trackingMethod")) == "QAGENT":
                c["agent_hosts"] += 1
                c["agent_active"] += ai.get("status") == "STATUS_ACTIVE"
            t = parse_ts(r.get("lastVulnScan"))
            if not t or t.year < 2000:
                c["never_scanned"] += 1
            elif t < cut:
                c["stale_scan"] += 1
        out["qualys"] = dict(c)
    # SentinelOne
    if have("sentinelone_agent.jsonl.gz") or have("sentinelone_threat.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "sentinelone_agent.jsonl.gz", "sentinelOneAgent"):
            if r.get("isDecommissioned") is True or r.get("isUninstalled") is True:
                c["retired"] += 1
                continue
            c["agents"] += 1
            c["inactive"] += r.get("isActive") is False
            c["out_of_date"] += r.get("isUpToDate") is False
            c["infected"] += (r.get("infected") is True) or ((r.get("activeThreats") or 0) > 0)
            c["not_protect"] += r.get("mitigationMode") not in (None, "protect")
        for r in iter_dump(d, "sentinelone_threat.jsonl.gz", "sentinelOneThreat"):
            ti = r.get("threatInfo") or {}
            c["threats"] += 1
            c["unresolved"] += ti.get("incidentStatus") == "unresolved"
            c["not_mitigated"] += ti.get("mitigationStatus") == "not_mitigated"
            c["malicious"] += ti.get("confidenceLevel") == "malicious"
        if c["agents"] or c["threats"]:
            out["sentinelone"] = dict(c); used.append("sentinelOneAgent / sentinelOneThreat")
    # CrowdStrike Falcon
    if have("falcon_agent.jsonl.gz"):
        c = collections.Counter()
        for r in iter_dump(d, "falcon_agent.jsonl.gz", "falconAgent"):
            c["sensors"] += 1
            c["contained"] += r.get("status") == "contained"
            c["reduced"] += r.get("reduced_functionality_mode") == "yes"
            prev = ((r.get("device_policies") or {}).get("prevention") or {})
            c["no_prevention"] += prev.get("applied") is not True
            t = parse_ts(r.get("last_seen"))
            c["not_seen_recent"] += bool(t and t < cut)
        if c["sensors"]:
            out["falcon"] = dict(c); used.append("falconAgent")
    return out or None


def history_facts(d, period_end):
    """History depth actually observed per source: oldest record to the end of the period (not a retention setting)."""
    out = []
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith("history_") and fn.endswith(".json")):
            continue
        res = load(d, fn)
        r1 = first(res)
        old = parse_ts(r1.get("oldest")) if r1 else None
        if old is None:
            out.append({"table": fn[8:-5], "days": None})
            continue
        new = parse_ts(r1.get("newest")) or period_end
        days = (min(new, period_end) - old).days
        rf = res.get("range_from") if isinstance(res, dict) else None
        bounded = rf is not None and (old - datetime.datetime.fromtimestamp(rf / 1000, tz=UTC)).days < 1
        out.append({"table": fn[8:-5], "oldest": old.date().isoformat(), "days": days, "at_least": bounded})
    return out or None


RETENTION_TARGET_DAYS = 365


def retention_facts(d, period_end):
    """Bounded retention probes: files retention_<Table>_<age>.json hold one kql_search ("<Table> | take 1") over a short
    window that ends <age> days before the period end. A hit proves records exist at that depth. Not a retention setting."""
    tabs = {}
    for fn in sorted(os.listdir(d)):
        m = re.match(r"retention_(.+)_(\d+)\.json$", fn)
        if not m:
            continue
        res = load(d, fn)
        if not isinstance(res, dict) or res.get("range_to") is None:
            continue
        end = datetime.datetime.fromtimestamp(res["range_to"] / 1000, tz=UTC)
        age = int(round((period_end - end).total_seconds() / 86400.0))
        tabs.setdefault(m.group(1), {})[age] = (res.get("total") or 0) > 0
    out = []
    for t, pr in sorted(tabs.items()):
        hits = [a for a, h in pr.items() if h]
        misses = [a for a, h in pr.items() if not h and (not hits or a > max(hits))]
        out.append({"table": t, "probes": {str(a): pr[a] for a in sorted(pr)}, "deepest_days": max(hits) if hits else None,
                    "first_miss_days": min(misses) if misses else None, "target_met": pr.get(RETENTION_TARGET_DAYS) is True})
    return out or None


def coverage(rows):
    """Evidence coverage: supported = 1, partial = 0.5, over the groups telemetry could evidence (manual review excluded)."""
    scored = [r for r in rows if r[2] != "needs_manual_review"]
    if not scored:
        return None
    return int(round(100.0 * sum(1.0 if r[2] == "supported" else 0.5 if r[2] == "partial" else 0.0 for r in scored) / len(scored)))


def load_prior(history_dir, prior_path, period):
    """The previous month's summary, plus the coverage series of every saved month up to this one."""
    series = {}
    if history_dir and os.path.isdir(history_dir):
        for fn in sorted(os.listdir(history_dir)):
            if fn.endswith(".json"):
                s = load(history_dir, fn)
                if isinstance(s, dict) and s.get("period") and s.get("coverage_pct") is not None:
                    series[s["period"]] = s
    prior = None
    if prior_path:
        prior = load(os.path.dirname(prior_path) or ".", os.path.basename(prior_path))
    elif series:
        earlier = [p for p in series if p < period]
        prior = series[max(earlier)] if earlier else None
    if prior and prior.get("period") and prior.get("coverage_pct") is not None:
        series[prior["period"]] = prior
    return prior, series


def ct_archive_facts(d, period):
    """Sum the archived CloudTrail_Activity_Report trend rows for the period. Returns None when no completed day
    of the period is in the evidence folder. Missing days are reported, never counted as zero."""
    yy, mm = [int(x) for x in period.split("-")]
    d0 = datetime.date(yy, mm, 1)
    d1 = datetime.date(yy + (mm == 12), mm % 12 + 1, 1)
    expected = [(d0 + datetime.timedelta(i)).isoformat() for i in range((d1 - d0).days)]
    days = {}
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith("ct_archive") and fn.endswith(".json")):
            continue
        res = load(d, fn) or {}
        for day in res.get("days", []):
            en = day.get("entry") or {}
            key = (en.get("rangeFrom") or "")[:10]
            r = day.get("result")
            if key not in expected or en.get("state") != "completed" or not r:
                continue
            if key in days and (days[key][0] or "") >= (en.get("completedOn") or ""):
                continue
            rows = []
            for o in r.get("objects", []):
                if o.get("name") == "trend":
                    rows = (o.get("table") or {}).get("rows") or []
            days[key] = (en.get("completedOn"), rows)
    if not days:
        return None
    tot = {k: 0 for k in ("events", "consoleLogins", "failedLogins", "iamChanges", "rootEvents", "errors", "accessDenied", "loginsNoMfa", "trailChanges")}
    for _, rows in days.values():
        for r_ in rows:
            for k in tot:
                tot[k] += int(r_.get(k) or 0)
    return {"events": tot["events"], "console_logins": tot["consoleLogins"], "console_failed": tot["failedLogins"], "iam_changes": tot["iamChanges"],
            "root_events": tot["rootEvents"], "errors": tot["errors"], "access_denied": tot["accessDenied"], "logins_no_mfa": tot["loginsNoMfa"],
            "trail_changes": tot["trailChanges"], "days_archived": len(days), "days_expected": len(expected),
            "missing_days": [x for x in expected if x not in days], "source": "archive"}

M365_KEYS = {"o365": "Office365", "signin": "AzureSigninLogs", "audit": "AzureAuditLogs",
             "sp": "AADServicePrincipalSignInLogs", "ni": "AADNonInteractiveUserSignInLogs"}


def m365_archive_facts(d, period):
    """Sum the archived Office365_Entra_Activity_Report trend rows for the period, per source. Returns None when no
    completed day of the period is in the evidence folder. A missing day is a gap and a source the tenant lacks is
    "not available"; neither is counted as zero."""
    yy, mm = [int(x) for x in period.split("-")]
    d0 = datetime.date(yy, mm, 1)
    d1 = datetime.date(yy + (mm == 12), mm % 12 + 1, 1)
    expected = [(d0 + datetime.timedelta(i)).isoformat() for i in range((d1 - d0).days)]
    days = {}
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith("m365_archive") and fn.endswith(".json")):
            continue
        res = load(d, fn) or {}
        for day in res.get("days", []):
            en = day.get("entry") or {}
            key = (en.get("rangeFrom") or "")[:10]
            r = day.get("result")
            if key not in expected or en.get("state") != "completed" or not r:
                continue
            if key in days and (days[key][0] or "") >= (en.get("completedOn") or ""):
                continue
            days[key] = (en.get("completedOn"), r.get("objects", []))
    if not days:
        return None
    srcs = {k: {"table": t, "days_ok": 0, "days_not_available": 0, "days_not_collected": 0, "totals": collections.Counter()} for k, t in M365_KEYS.items()}
    workloads, categories = collections.Counter(), collections.Counter()

    def facet_rows(objs, name, facet):
        for o in objs:
            if o.get("name") != name:
                continue
            om = (o.get("value") or {}).get("orderedMap") or {}
            for k_, v_ in zip(om.get("keys", []), om.get("values", [])):
                if k_ == facet:
                    return [(str(r.get(facet)), int(r.get("count_") or 0)) for r in ((v_ or {}).get("sx") or {}).get("rows") or []]
        return []
    for _, objs in days.values():
        names = {o.get("name") for o in objs}
        status = {}
        for o in objs:
            if o.get("name") == "sources":
                for r_ in (o.get("table") or {}).get("rows") or []:
                    if r_.get("status") == "ok":
                        status.setdefault(r_.get("source"), "ok")
                    else:
                        status[r_.get("source")] = "not available"
        for k, t in M365_KEYS.items():
            sr = srcs[k]
            if k + "_trend" not in names and k + "_facets" not in names:
                sr["days_not_collected"] += 1
                continue
            rows = []
            for o in objs:
                if o.get("name") == k + "_trend":
                    rows = (o.get("table") or {}).get("rows") or []
            st = status.get(t) or ("ok" if rows else None)
            if st == "not available":
                sr["days_not_available"] += 1
                continue
            if st is None:
                sr["days_not_collected"] += 1
                continue
            sr["days_ok"] += 1
            for r_ in rows:
                for m_, v_ in r_.items():
                    if m_ != "Date" and isinstance(v_, (int, float)):
                        sr["totals"][m_] += int(v_)
            if k == "o365":
                for v_, c_ in facet_rows(objs, "o365_facets", "workload"):
                    workloads[v_] += c_
            if k == "audit":
                for v_, c_ in facet_rows(objs, "audit_facets", "category"):
                    categories[v_] += c_
    for sr in srcs.values():
        sr["totals"] = dict(sr["totals"])
        sr["totals"].setdefault("events", 0)
        sr["totals"].setdefault("failed", 0)
    return {"sources": srcs, "workloads": dict(workloads), "audit_categories": dict(categories), "days_archived": len(days), "days_expected": len(expected),
            "missing_days": [x for x in expected if x not in days], "source": "archive"}


CONNECTOR_TABLE = {"Office365": "Office365", "AzureAudit": "AzureAuditLogs", "AWSCloudTrail": "CloudTrail",
                   "Duo": "Duo", "GoogleWorkspace": "GSuite", "AmazonGuardDuty": "GuardDuty"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tenant-name", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary-json", help="also write the control statuses as JSON (used by the CISO_monthly_report skill and the framework companions)")
    ap.add_argument("--history-dir", help="folder of earlier compliance_summary_YYYY-MM.json files; the latest earlier month becomes the prior month and all months feed the trend")
    ap.add_argument("--prior-summary", help="one earlier compliance_summary.json to compare against (overrides --history-dir for the prior month)")
    ap.add_argument("--require-m365", action="store_true", help="stop with exit 3 when no day of the period is in the Office 365 / Entra archive")
    ap.add_argument("--require-cloudtrail", action="store_true", help="stop with exit 3 when no day of the period is in the CloudTrail archive (use when the tenant has a CloudTrail table)")
    a = ap.parse_args()
    d = a.evidence_dir

    used_tables, used_dumps = [], []
    m365 = m365_archive_facts(d, a.period)
    if m365 is None and a.require_m365:
        sys.stderr.write("OFFICE 365 / ENTRA ARCHIVE REQUIRED: no completed day of %s was found in the archive of the scheduled report "
                         "Office365_Entra_Activity_Report (files m365_archive*.json). Office 365 and Entra tables are never searched live. Set up "
                         "the scheduled report with the archive enabled (microsoft365-entra-activity-report skill, references/archive_format.md) "
                         "and backfill the period with backfill_report_archive, then run this again.\n" % a.period)
        sys.exit(3)

    def m365_src(key):
        s_ = ((m365 or {}).get("sources") or {}).get(key)
        return s_ if s_ and s_["days_ok"] else None
    s_o, s_si, s_au, s_sp, s_ni = (m365_src(k) for k in ("o365", "signin", "audit", "sp", "ni"))

    def cov_label(base, s_):
        if not s_ or s_["days_ok"] >= m365["days_expected"]:
            return base
        return "%s (%d of %d days archived)" % (base, s_["days_ok"], m365["days_expected"])
    o365 = s_o["totals"]["events"] if s_o else None
    wl_rows = [{"Workload": k_, "events": v_} for k_, v_ in m365["workloads"].items()] if s_o else None
    if s_o: used_tables.append("Office365")
    si = {"events": s_si["totals"]["events"], "failed": s_si["totals"]["failed"], "users": None} if s_si else None
    if si: used_tables.append("AzureSigninLogs")
    audit = s_au["totals"]["events"] if s_au else None
    au_rows = [{"Category": k_, "events": v_} for k_, v_ in m365["audit_categories"].items()] if s_au else None
    if s_au: used_tables.append("AzureAuditLogs")
    sp_n = s_sp["totals"]["events"] if s_sp else None
    ni_n = s_ni["totals"]["events"] if s_ni else None
    if s_sp: used_tables.append("AADServicePrincipalSignInLogs")
    if s_ni: used_tables.append("AADNonInteractiveUserSignInLogs")
    win = first(load(d, "windows.json"))
    win_n = win["events"] if win else None
    if win: used_tables.append("WindowsAudit")
    beh = load(d, "behavior.json")
    beh_total = beh.get("total") if beh else None
    f_status, f_class, f_score = (facet(beh, k) for k in ("status", "classification", "scoreLevel"))
    yy, mm = a.period.split("-")
    period_start = datetime.datetime(int(yy), int(mm), 1, tzinfo=UTC)
    period_end = datetime.datetime(int(yy) + (int(mm) == 12), int(mm) % 12 + 1, 1, tzinfo=UTC)

    def dump(name, resource, label):
        rec = load_dump(d, name, resource)
        if rec is not None:
            used_dumps.append(label)
        return rec
    u_rec = dump("users.jsonl.gz", "office365User", "office365User")
    us = {"users": len(u_rec), "enabled": sum(1 for r in u_rec if r.get("accountEnabled") is True)} if u_rec is not None else None
    hy = hygiene(u_rec)
    d_rec = dump("devices.jsonl.gz", "office365Device", "office365Device")
    dv = device_facts(d_rec, period_end) if d_rec is not None else None
    ca_rec = dump("ca_policies.jsonl.gz", "office365ConditionalAccessPolicy", "office365ConditionalAccessPolicy")
    ca = None
    if ca_rec is not None:
        ca = {}
        for r in ca_rec:
            ca[r.get("state")] = ca.get(r.get("state"), 0) + 1
    q_rec = dump("qualys.jsonl.gz", "qualysHost", "qualysHost")
    qualys = len(q_rec) if q_rec is not None else None
    gd = guardduty_facts(dump("guardduty.jsonl.gz", "GuarddutyFinding", "GuarddutyFinding"), period_start, period_end)
    gw = gsuite_facts(dump("gsuite_users.jsonl.gz", "gsuiteUser", "gsuiteUser"))
    ap_rec = dump("apps.jsonl.gz", "office365Application", "office365Application")
    apf = app_facts(ap_rec, period_end)
    sp_rec = dump("enterprise_apps.jsonl.gz", "office365InstalledApp", "office365InstalledApp")
    spf = enterprise_app_facts(sp_rec, ap_rec)
    grf = group_facts(dump("groups.jsonl.gz", "office365Group", "office365Group"))
    ggf = gsuite_group_facts(dump("gsuite_groups.jsonl.gz", "gsuiteGroup", "gsuiteGroup"))
    mdf = mde_facts(d, period_end, used_dumps)
    vnd = vendor_facts(d, period_end, q_rec, used_dumps)
    extra = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("src_") and fn.endswith(".json") and fn[4:-5].lower() != "cloudtrail":
            extra.append({"table": fn[4:-5], "class": table_class(fn[4:-5]), "events": kql_events(load(d, fn))})
            used_tables.append(fn[4:-5])
    ctf = ct_archive_facts(d, a.period)
    if ctf is None and a.require_cloudtrail:
        sys.stderr.write("CLOUDTRAIL ARCHIVE REQUIRED: no completed day of %s was found in the archive of the scheduled report "
                         "CloudTrail_Activity_Report (files ct_archive*.json). CloudTrail is never searched live. Set up the scheduled report "
                         "with the archive enabled (aws-cloudtrail-activity-report skill, references/archive_format.md) and backfill the "
                         "period with backfill_report_archive, then run this again.\n" % a.period)
        sys.exit(3)
    ct_events = ctf["events"] if ctf else None
    ct_label = "CloudTrail" if not ctf or not ctf["missing_days"] else "CloudTrail (%d of %d days archived)" % (ctf["days_archived"], ctf["days_expected"])
    if ctf: used_tables.append("CloudTrail")
    net_src = [x for x in extra if x["class"] == "network" and x["events"]]
    end_src = [x for x in extra if x["class"] == "endpoint" and x["events"]]
    hist = history_facts(d, period_end)
    ret = retention_facts(d, period_end)
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
    srcs_all = [(cov_label("Office 365", s_o), o365), (cov_label("Entra sign-in", s_si), sin), (cov_label("Entra directory-audit", s_au), audit),
                (cov_label("Entra service-principal sign-in", s_sp), sp_n), (cov_label("Entra non-interactive sign-in", s_ni), ni_n),
                ("Windows audit", win_n), (ct_label, ct_events)] + [(x["table"], x["events"]) for x in extra if x["table"] != "CloudTrail"]
    srcs_on = [(lbl, v_) for lbl, v_ in srcs_all if v_]

    def logging_status():
        return "supported" if len(srcs_on) >= 2 else ("partial" if srcs_on else "not_observed")

    def events_of(table):
        low = table.lower()
        for lbl, v_ in (("office365", o365), ("azureauditlogs", audit), ("azuresigninlogs", sin), ("cloudtrail", ct_events)):
            if low == lbl:
                return v_
        for x in extra:
            if x["table"].lower() == low:
                return x["events"]
        return None

    pct = "%.1f%%" % (100.0 * failed / sin) if sin else None
    hist_ok = [h for h in (hist or []) if h.get("days") is not None]
    if ret:
        def _rt(r):
            if r["deepest_days"] is None:
                return "%s no records found at any probed depth" % r["table"]
            miss = ", none at %s days" % r["first_miss_days"] if r["first_miss_days"] else ""
            return "%s records found back to %s days%s" % (r["table"], r["deepest_days"], miss)
        ret_status = "supported" if all(r["target_met"] for r in ret) else "partial"
        ret_text = ("Retention probe (target %s days): %s. Each probe looks for any record in a short window that far before the period end, so it shows how far back records exist, not the configured retention setting. Archive counts are not retention evidence." % (
            RETENTION_TARGET_DAYS, "; ".join(_rt(r) for r in ret)))
        if hist_ok:
            ret_text += " Other sources: " + "; ".join("%s %s%s days" % (h["table"], "at least " if h.get("at_least") else "", n(h["days"])) for h in hist_ok) + "."
    elif hist_ok:
        ret_status = "partial"
        ret_text = "History observed: %s. This is how far back records exist, not the configured retention period, and it can reflect when a source was connected." % "; ".join(
            "%s %s%s days (oldest %s)" % (h["table"], "at least " if h.get("at_least") else "", n(h["days"]), h["oldest"]) for h in hist_ok)
    else:
        ret_status, ret_text = "not_observed", "Retention period and storage capacity were not collected in this run, and no history depth was measured."
    if inc_total is not None:
        au6_text = "%s summaries became incidents: %s still new, %s closed. No review-cadence record was collected." % (n(inc_total), n(new_inc or 0), n(closed_inc or 0))
        ir_text = "%s. Documented response procedure not supplied." % (
            ("Closed incidents by classification: " + ", ".join("%s %s" % (v, k) for k, v in f_class.items())) if f_class else
            ("No incident was closed in the window, so there is no classification to report" if not closed_inc else "Classification of the closed incidents was not returned"))
    else:
        au6_text, ir_text = "Incident status was not collected. No review-cadence record was collected.", "Dispositions: not collected. Documented response procedure not supplied."
    sp_text, ni_text = "", ""
    if s_sp and sp_n:
        t_ = s_sp["totals"]
        sp_text = " Service principals: %s of %s sign-ins failed, %s of them on an expired or invalid client secret; %s used a client secret rather than a certificate or federated credential." % (
            n(t_.get("failed", 0)), n(sp_n), n(t_.get("secretErrors", 0)), n(t_.get("secretAuth", 0)))
    if s_ni and ni_n:
        ni_text = " Non-interactive user sign-ins: %s of %s failed." % (n(s_ni["totals"].get("failed", 0)), n(ni_n))
    gd_text = ""
    if gd:
        gd_text = " GuardDuty snapshot: %s findings, %s open, %s high severity and open, %s updated in the month." % (n(gd["findings"]), n(gd["open"]), n(gd["high_open"]), n(gd["updated_in_period"]))
    gw_text = ""
    if gw:
        gw_text = " Google Workspace: %s users, %s administrators, %s of %s enrolled in 2-Step Verification." % (n(gw["users"]), n(gw["admins"]), n(gw["enrolled_2sv"]), n(gw["users"]))
    rows = [
        ("AU-2 / AU-12", "Event logging and audit record generation", logging_status(),
         "%s events: %s." % (mon_name, ", ".join("%s %s" % (n(v_), lbl) for lbl, v_ in srcs_all if v_ is not None) or "none collected")),
        ("SI-4", "System monitoring", "supported" if beh_total else "not_observed",
         "Behavior engine produced %s summaries in the window.%s" % (n(beh_total), gd_text)),
        ("AU-6", "Audit record review and analysis", "partial" if inc_total else "not_observed", au6_text),
        ("IR-4 / IR-5", "Incident handling and monitoring", "partial" if inc_total else "not_observed", ir_text),
        ("AC-2", "Account management", "partial" if (us or ctf or gw) else "not_observed",
         "%s directory users (%s enabled%s)%s; directory audit categories include user and group management.%s%s No account-review cadence evidence." % (
             n(us["users"]) if us else "not collected", n(us["enabled"]) if us else "not collected",
             (", %s disabled, %s guests, %s with an admin role" % (n(hy["disabled"]), n(hy["guests"]), n(hy["admins"]))) if hy else "", "",
             (" CloudTrail shows %s IAM change events and %s root-account events." % (n(ctf["iam_changes"]), n(ctf["root_events"]))) if ctf and ctf["iam_changes"] is not None else "",
             (" Google Workspace holds %s users (%s administrators)." % (n(gw["users"]), n(gw["admins"]))) if gw else "")),
        ("AC-7", "Unsuccessful logon attempts", "partial" if (si or s_sp or s_ni or (ctf and ctf["console_logins"] is not None)) else "not_observed",
         "%s of %s Entra sign-ins failed (%s).%s%s%s Lockout and throttling configuration was not collected." % (n(failed), n(sin), pct or "n/a",
             (" CloudTrail: %s of %s console logins failed." % (n(ctf["console_failed"]), n(ctf["console_logins"]))) if ctf and ctf["console_logins"] is not None else "", ni_text, sp_text)),
        ("IA-2 / IA-5", "Authentication and authenticators", "partial" if (ca or (hy and hy["mfa_known"]) or gw) else "not_observed",
         "%s%s%s" % ((("%s Conditional Access policies: %s enforced, %s report-only." % (n(ca_all or 0), n(ca_enf or 0), n(ca_rep))) if ca is not None else "Conditional Access policies were not collected."),
             (" %s of %s enabled users have registered MFA; %s of %s administrators lack it. Registration is not enforcement." % (n(hy["enabled_mfa_registered"]), n(hy["enabled"]), n(hy["admins_no_mfa"]), n(hy["admins"]))) if hy and hy["mfa_known"] else " MFA coverage was not collected.",
             (" Google Workspace: %s of %s administrators are enrolled in 2-Step Verification." % (n(gw["admins_2sv"]), n(gw["admins"]))) if gw and gw["admins"] else "")),
        ("CM-8", "System component inventory", "partial" if (dv or qualys) else "not_observed",
         "%s directory devices%s; %s The inventories were not reconciled." % (n(dv["devices"]) if dv else "not collected",
             (" (%s with no sign-in in the 90 days before the period ended%s%s)" % (n(dv["stale_90d"]), (", %s non-compliant" % n(dv["non_compliant"])) if dv["non_compliant"] is not None else "", (", %s managed" % n(dv["managed"])) if dv["managed"] is not None else "")) if dv else "",
             ("%s Qualys hosts." % n(qualys)) if qualys is not None else "no Qualys host inventory.")),
        ("RA-5", "Vulnerability monitoring", "partial" if qualys else "not_observed",
         ("Qualys inventory has %s hosts. Vulnerability findings were not queried." % n(qualys)) if qualys else "No Qualys host inventory was collected, so vulnerability monitoring is not observed."),
        ("AU-4 / AU-11", "Log storage and retention", ret_status, ret_text),
        ("SC-7", "Boundary protection", "partial" if net_src else "not_observed",
         ("Network telemetry present: %s. Rules, denied traffic and segmentation were not evaluated." % ", ".join("%s %s events" % (x["table"], n(x["events"])) for x in net_src)) if net_src else "No firewall or network telemetry table is present on this tenant."),
        ("SI-3", "Malicious code protection", "partial" if end_src else "not_observed",
         ("Endpoint telemetry present: %s. Agent coverage and detections were not evaluated." % ", ".join("%s %s events" % (x["table"], n(x["events"])) for x in end_src)) if end_src else "No endpoint-protection data source is connected on this tenant."),
        ("AC-1 / IA-1 / IR-1", "Policy and procedures", "needs_manual_review", "Policy documents are customer-supplied evidence; telemetry cannot prove them."),
    ]
    def more(cid, text):
        for i_, r_ in enumerate(rows):
            if r_[0] == cid and text:
                rows[i_] = (r_[0], r_[1], r_[2], r_[3] + " " + text)
    more("IA-2 / IA-5", (("App registrations: %s, holding %s client secrets and %s certificates; %s of the secrets had expired by the end of the period and %s were valid for more than two years."
                          % (n(apf["apps"]), n(apf["secrets"]), n(apf["certificates"]), n(apf["secrets_expired"]), n(apf["secrets_long_lived"]))) if apf else ""))
    more("AC-2", " ".join(x for x in (
        ("Entra groups: %s (%s security-enabled, %s Microsoft 365, %s public, %s role-assignable, %s empty)." % (n(grf["groups"]), n(grf["security_enabled"]), n(grf["microsoft365"]), n(grf["public"]), n(grf["role_assignable"]), n(grf["empty"]))) if grf else "",
        ("Google Workspace groups: %s with %s memberships, %s with external members and %s with no owner." % (n(ggf["groups"]), n(ggf["members"]), n(ggf["with_external_members"]), n(ggf["without_owner"]))) if ggf else "")))
    more("CM-8", (("Enterprise applications (service principals): %s, of which %s are owned by Microsoft's first-party tenants and %s by other tenants and not registered here (this can include other Microsoft services); %s are disabled."
                   % (n(spf["total"]), n(spf["microsoft_owned"]), n(spf["third_party"]), n(spf["disabled"]))) if spf else ""))
    mdm, mav, mvu, mcf = ((mdf or {}).get(k) for k in ("machines", "av", "vuln", "config"))
    more("RA-5", "".join(x for x in (
        ("Defender Vulnerability Management reports %s findings across %s devices: %s critical, %s high, and %s with a known exploit (verified, public or in an exploit kit). No scan cadence, credentialed-scan coverage or remediation deadline was collected." % (
            n(mvu["findings"]), n(mvu["devices"]), n(mvu.get("critical", 0)), n(mvu.get("high", 0)), n(mvu.get("exploit", 0)))) if mvu else "",)))
    more("SI-3", ("Defender antivirus health covers %s devices: %s with out-of-date signatures, %s with an out-of-date platform and %s whose last quick scan did not complete." % (
        n(mav["devices"]), n(mav.get("sig_stale", 0)), n(mav.get("platform_stale", 0)), n(mav.get("scan_not_completed", 0)))) if mav else "")
    more("CM-8", " ".join(x for x in (
        ("Defender for Endpoint lists %s devices: %s onboarded, %s that can be onboarded, %s with an inactive or impaired sensor." % (
            n(mdm["devices"]), n(mdm.get("onboarded", 0)), n(mdm.get("can_onboard", 0)), n(mdm.get("inactive", 0)))) if mdm else "",
        ("Secure configuration: %s of %s applicable checks are failing, across %s devices." % (n(mcf.get("noncompliant", 0)), n(mcf["checks"]), n(mcf["devices_with_gaps"]))) if mcf else "")))
    # Defender evidence lifts a control from not observed to partial; it never reaches supported on its own.
    for i_, r_ in enumerate(rows):
        txt_ = r_[3]
        if r_[0] == "RA-5" and mvu:
            txt_ = txt_.replace("No Qualys host inventory was collected, so vulnerability monitoring is not observed. ", "")
        if r_[0] == "SI-3" and mav:
            txt_ = txt_.replace("No endpoint-protection data source is connected on this tenant. ", "")
        rows[i_] = (r_[0], r_[1], "partial" if (r_[2] == "not_observed" and ((r_[0] == "RA-5" and mvu) or (r_[0] == "SI-3" and mav))) else r_[2], txt_)
    vtn, vq, vs1, vfc = ((vnd or {}).get(k) for k in ("tenable", "qualys", "sentinelone", "falcon"))
    more("RA-5", " ".join(x for x in (
        ("Tenable covers %s assets: %s scanned in the %d days before the period ended, %s with an authenticated scan and %s with an agent; plugin hits are %s critical and %s high. Tenable has %s agents, %s online." % (
            n(vtn.get("assets", 0)), n(vtn.get("scanned_recent", 0)), SCAN_DAYS, n(vtn.get("authenticated", 0)), n(vtn.get("with_agent", 0)), n(vtn.get("critical_hits", 0)), n(vtn.get("high_hits", 0)), n(vtn.get("agents", 0)), n(vtn.get("agents_on", 0)))) if vtn else "",
        ("Qualys tracks %s hosts: %s agent-tracked (%s active), %s never scanned for vulnerabilities and %s not scanned in the %d days before the period ended." % (
            n(vq["hosts"]), n(vq.get("agent_hosts", 0)), n(vq.get("agent_active", 0)), n(vq.get("never_scanned", 0)), n(vq.get("stale_scan", 0)), SCAN_DAYS)) if vq else "")))
    more("SI-3", " ".join(x for x in (
        ("SentinelOne: %s agents, %s inactive, %s out of date, %s infected or with active threats and %s not in protect mode; %s threats recorded, %s unresolved and %s not mitigated." % (
            n(vs1.get("agents", 0)), n(vs1.get("inactive", 0)), n(vs1.get("out_of_date", 0)), n(vs1.get("infected", 0)), n(vs1.get("not_protect", 0)), n(vs1.get("threats", 0)), n(vs1.get("unresolved", 0)), n(vs1.get("not_mitigated", 0)))) if vs1 else "",
        ("CrowdStrike Falcon: %s sensors, %s in reduced functionality mode, %s without a prevention policy applied and %s not seen in the %d days before the period ended." % (
            n(vfc["sensors"]), n(vfc.get("reduced", 0)), n(vfc.get("no_prevention", 0)), n(vfc.get("not_seen_recent", 0)), SCAN_DAYS)) if vfc else "")))
    more("CM-8", " ".join(x for x in (
        ("Tenable lists %s assets." % n(vtn.get("assets", 0))) if vtn and vtn.get("assets") else "",
        ("SentinelOne lists %s agents." % n(vs1.get("agents", 0))) if vs1 and vs1.get("agents") else "",
        ("Falcon lists %s sensors." % n(vfc["sensors"])) if vfc else "")))
    for i_, r_ in enumerate(rows):
        if r_[0] == "RA-5" and vtn and r_[2] != "not_observed":
            rows[i_] = (r_[0], r_[1], r_[2], re.sub(r"Qualys inventory has [\d,]+ hosts\. Vulnerability findings were not queried\. ", "", r_[3]))
    for i_, r_ in enumerate(rows):
        if r_[2] == "not_observed" and ((r_[0] == "RA-5" and vtn) or (r_[0] == "SI-3" and (vs1 or vfc))):
            rows[i_] = (r_[0], r_[1], "partial", re.sub(r"Qualys inventory has [\d,]+ hosts\. Vulnerability findings were not queried\. ", "", r_[3]).replace("No endpoint-protection data source is connected on this tenant. ", "").replace("No Qualys host inventory was collected, so vulnerability monitoring is not observed. ", ""))
    cnt = {k: sum(1 for r in rows if r[2] == k) for k in STATUS}
    cov = coverage(rows)

    # Key findings: observations computed from the evidence, each with an action. Thresholds are the analyst's.
    findings = []
    def add(sev, title, ev, act, ctrl):
        findings.append({"severity": sev, "title": title, "evidence": ev, "action": act, "controls": ctrl})
    if ret and not all(r["target_met"] for r in ret):
        short = [r["table"] for r in ret if not r["target_met"]]
        add("low", "Twelve-month retention not yet evidenced", "No record was found %s days before the period end for: %s." % (RETENTION_TARGET_DAYS, ", ".join(short)),
            "Confirm the configured retention for these sources. If the source was connected less than a year ago, the probe cannot prove twelve months until it has existed that long; rerun the probe later.", "AU-4, AU-11")
    if ctf and ctf["root_events"]:
        add("high", "Root account activity", "CloudTrail recorded %s events by the AWS root identity in %s." % (n(ctf["root_events"]), mon_name),
            "Confirm each use was expected, enable MFA on the root user, and use IAM roles for routine work.", "AC-2, IA-2")
    if hy and hy["admins_no_mfa"]:
        add("high", "Administrators without MFA", "%s of %s administrator accounts have no MFA registered." % (n(hy["admins_no_mfa"]), n(hy["admins"])),
            "Register MFA for each administrator and enforce it with a Conditional Access policy.", "IA-2, IA-5")
    if gd and gd["high_open"]:
        add("high", "High-severity GuardDuty findings still open", "%s high-severity findings are unarchived in the snapshot (%s touched in %s)." % (n(gd["high_open"]), n(gd["high_updated_in_period"]), mon_name),
            "Triage each finding, then archive it with a reason or open an incident.", "SI-4, IR-4")
    if inc_total and new_inc:
        add("high" if new_inc == inc_total else "medium", "Incidents not yet triaged", "%s of %s incidents in the window are still marked new." % (n(new_inc), n(inc_total)),
            "Assign and classify each incident and record the disposition.", "AU-6, IR-4")
    if hy and hy["enabled_no_mfa"]:
        add("medium", "Enabled users without MFA", "%s of %s enabled users have no MFA registered." % (n(hy["enabled_no_mfa"]), n(hy["enabled"])),
            "Require MFA registration for every enabled user, then enforce it in Conditional Access.", "IA-2, IA-5")
    if dv and dv["devices"] and dv["stale_90d"] and dv["stale_90d"] >= STALE_SHARE * dv["devices"]:
        add("medium", "Stale device registrations", "%s of %s directory devices had no sign-in in the 90 days before the period ended." % (n(dv["stale_90d"]), n(dv["devices"])),
            "Review and remove devices that are no longer in use so the inventory reflects what exists.", "CM-8")
    if ctf and ctf["console_logins"] and ctf["console_failed"] and ctf["console_failed"] >= CONSOLE_FAIL * ctf["console_logins"]:
        add("medium", "High share of failed cloud console logins", "%s of %s CloudTrail console logins failed." % (n(ctf["console_failed"]), n(ctf["console_logins"])),
            "Check the failures for password guessing or a misconfigured user, and require MFA on console access.", "AC-7")
    if sin and failed and failed >= SIGNIN_FAIL * sin:
        add("medium", "High share of failed Entra sign-ins", "%s of %s sign-ins failed (%s)." % (n(failed), n(sin), pct), "Review the failures by user and source address.", "AC-7")
    if s_sp and sp_n and s_sp["totals"].get("secretErrors", 0) >= SP_SECRET_FAIL * sp_n:
        add("medium", "Service principals failing on expired client secrets", "%s of %s service-principal sign-ins (%s) failed on an expired or invalid client secret in %s." % (
            n(s_sp["totals"]["secretErrors"]), n(sp_n), "%.1f%%" % (100.0 * s_sp["totals"]["secretErrors"] / sp_n), mon_name),
            "Find the integrations behind the failing sign-ins in the Entra service-principal sign-in logs, rotate or retire each expired secret, and prefer certificate or federated credentials.", "IA-5, AC-2")
    for app, tab in sorted(CONNECTOR_TABLE.items()):
        states = [s for ap_, s in (conn_list or []) if ap_ == app]
        ev = events_of(tab)
        if states and "Running" in states and ev == 0:
            add("medium", "Connector running but no events", "The %s connector shows as Running but the %s table received no events in %s." % (app, tab, mon_name),
                "Check the connector's credentials and source-side logging; a silent source is a blind spot.", "AU-2, AU-12")
    if hy and hy["users"] and hy["admins"] and hy["enabled"] and hy["admins"] > ADMIN_SHARE * hy["enabled"]:
        add("medium", "Many accounts hold admin roles", "%s of %s enabled users hold an admin role." % (n(hy["admins"]), n(hy["enabled"])),
            "Remove standing admin roles that are not needed and move the rest to just-in-time elevation.", "AC-2, AC-6")
    if hy and hy["guests"]:
        add("low", "Guest accounts present", "%s guest accounts exist in the directory." % n(hy["guests"]), "Review each guest's access and remove those no longer needed.", "AC-2")
    if apf and apf["secrets_expired"]:
        add("medium", "Expired client secrets on app registrations", "%s of %s client secrets across %s app registrations had expired by the end of %s." % (n(apf["secrets_expired"]), n(apf["secrets"]), n(apf["apps"]), mon_name),
            "Delete expired secrets, rotate any still in use, and prefer certificates or managed identities over long-lived secrets.", "IA-5")
    if apf and apf["secrets_long_lived"]:
        add("low", "Long-lived client secrets", "%s client secrets were issued for more than two years." % n(apf["secrets_long_lived"]),
            "Shorten secret lifetimes and rotate on a schedule.", "IA-5")
    if apf and apf["apps_app_only_permissions"]:
        add("low", "App registrations request application permissions", "%s of %s app registrations request application-type (app-only) permissions. This shows what is requested, not what an admin has consented to." % (n(apf["apps_app_only_permissions"]), n(apf["apps"])),
            "Check the consented permissions for each and remove any broader than the app needs.", "AC-6")
    if spf and spf["third_party"]:
        add("low", "Enterprise applications from other tenants", "%s enterprise applications are owned by tenants other than Microsoft's first-party tenants and are not registered here. Some may be other Microsoft services." % n(spf["third_party"]),
            "Review consent and assignment for each and remove applications no longer in use.", "CM-8, AC-6")
    if grf and grf["public"]:
        add("low", "Public Microsoft 365 groups", "%s of %s groups have Public visibility, so any member of the organisation can see and join them." % (n(grf["public"]), n(grf["groups"])),
            "Make groups that hold sensitive content Private.", "AC-2, AC-3")
    if ggf and ggf["with_external_members"]:
        add("low", "Google groups with external members", "%s of %s Google Workspace groups include members outside the group's own domain." % (n(ggf["with_external_members"]), n(ggf["groups"])),
            "Confirm each external member still needs access.", "AC-2")
    rvu = (mdf or {}).get("vuln")
    if rvu and rvu.get("exploit"):
        add("high", "Vulnerabilities with a known exploit", "%s findings on %s devices have a verified, public or exploit-kit exploit." % (n(rvu["exploit"]), n(rvu["exploit_devices"])),
            "Patch these first, starting with devices rated high exposure.", "RA-5, SI-2")
    if rvu and rvu.get("critical_aged"):
        add("medium", "Critical vulnerabilities open for more than %d days" % AGED_DAYS, "%s of %s critical findings were first seen more than %d days before the end of %s." % (n(rvu["critical_aged"]), n(rvu["critical"]), AGED_DAYS, mon_name),
            "Check these against your patching deadline and escalate the ones past it.", "RA-5, SI-2")
    if mav and mav["devices"] and mav.get("sig_stale"):
        add("medium" if mav["sig_stale"] >= AV_STALE * mav["devices"] else "low", "Out-of-date antivirus signatures", "%s of %s Defender antivirus devices have out-of-date security intelligence." % (n(mav["sig_stale"]), n(mav["devices"])),
            "Find out why these devices are not updating and fix or retire them.", "SI-3")
    if mdm and mdm["devices"] and mdm.get("inactive"):
        add("medium" if mdm["inactive"] >= STALE_SHARE * mdm["devices"] else "low", "Defender devices with an inactive sensor", "%s of %s devices in Defender report an inactive or impaired sensor." % (n(mdm["inactive"]), n(mdm["devices"])),
            "Remove retired devices from the inventory and restore the sensor on live ones.", "CM-8, SI-3")
    if mdm and mdm.get("can_onboard"):
        add("medium", "Devices not onboarded to Defender", "%s devices can be onboarded to Defender for Endpoint but are not." % n(mdm["can_onboard"]),
            "Onboard them, or record why they are out of scope.", "CM-8, SI-3")
    if mcf and mcf["checks"] and mcf.get("noncompliant", 0) >= CONFIG_FAIL * mcf["checks"]:
        add("medium", "High share of failing secure-configuration checks", "%s of %s applicable checks are failing (%s)." % (n(mcf["noncompliant"]), n(mcf["checks"]), "%.0f%%" % (100.0 * mcf["noncompliant"] / mcf["checks"])),
            "Review the most-failing categories and fix them through policy.", "CM-6")
    if mdm and mdm.get("high_exposure"):
        add("low", "Devices rated high exposure", "%s devices have a High exposure rating in Defender Vulnerability Management." % n(mdm["high_exposure"]),
            "Prioritise patching and configuration fixes on these devices.", "RA-5")
    if vtn and vtn.get("critical_hits"):
        add("high", "Critical vulnerabilities reported by Tenable", "Tenable plugins with a critical rating have %s hits (and %s high-rated hits)." % (n(vtn["critical_hits"]), n(vtn.get("high_hits", 0))),
            "Prioritise the critical plugins by hit count and confirm each fix with a rescan.", "RA-5, SI-2")
    if vtn and vtn.get("assets") and vtn["assets"] - vtn.get("scanned_recent", 0) >= 0.25 * vtn["assets"]:
        add("medium", "Tenable assets not scanned recently", "%s of %s Tenable assets were not scanned in the %d days before the period ended." % (n(vtn["assets"] - vtn.get("scanned_recent", 0)), n(vtn["assets"]), SCAN_DAYS),
            "Check the scan schedules and targets, and retire assets that no longer exist.", "RA-5")
    if vtn and vtn.get("agents") and vtn["agents"] - vtn.get("agents_on", 0) >= 0.25 * vtn["agents"]:
        add("low", "Tenable agents offline", "%s of %s Tenable agents are not online." % (n(vtn["agents"] - vtn.get("agents_on", 0)), n(vtn["agents"])),
            "Restore the agents on live hosts and remove the ones for retired hosts.", "RA-5, CM-8")
    if vq and (vq.get("never_scanned") or vq.get("stale_scan")):
        add("medium", "Qualys hosts without a recent vulnerability scan", "%s of %s Qualys hosts were never scanned and %s were not scanned in the %d days before the period ended." % (n(vq.get("never_scanned", 0)), n(vq["hosts"]), n(vq.get("stale_scan", 0)), SCAN_DAYS),
            "Check that the Vulnerability Management module is activated for these hosts.", "RA-5")
    if vs1 and vs1.get("unresolved"):
        add("high", "Unresolved SentinelOne threats", "%s of %s SentinelOne threats are unresolved (%s not mitigated, %s rated malicious)." % (n(vs1["unresolved"]), n(vs1.get("threats", 0)), n(vs1.get("not_mitigated", 0)), n(vs1.get("malicious", 0))),
            "Triage each unresolved threat, then mitigate it or record the reason it is accepted.", "SI-3, IR-4")
    if vs1 and vs1.get("agents") and vs1.get("not_protect"):
        add("medium", "SentinelOne agents not in protect mode", "%s of %s SentinelOne agents are set to detect only or another non-protect mode." % (n(vs1["not_protect"]), n(vs1["agents"])),
            "Move agents to protect mode unless a documented exception applies.", "SI-3")
    if vs1 and vs1.get("agents") and vs1.get("out_of_date"):
        add("medium" if vs1["out_of_date"] >= AGENT_BAD * vs1["agents"] else "low", "SentinelOne agents out of date", "%s of %s SentinelOne agents are not on the expected version." % (n(vs1["out_of_date"]), n(vs1["agents"])),
            "Update the agents or fix the policy that is holding them back.", "SI-3, SI-2")
    if vfc and vfc.get("reduced"):
        add("medium", "Falcon sensors in reduced functionality mode", "%s of %s CrowdStrike Falcon sensors are in reduced functionality mode." % (n(vfc["reduced"]), n(vfc["sensors"])),
            "Update the kernel support or sensor on these hosts so full protection is restored.", "SI-3")
    if vfc and vfc.get("no_prevention"):
        add("medium" if vfc["no_prevention"] >= AGENT_BAD * vfc["sensors"] else "low", "Falcon sensors without a prevention policy applied", "%s of %s CrowdStrike Falcon sensors have no prevention policy applied." % (n(vfc["no_prevention"]), n(vfc["sensors"])),
            "Check that these hosts are assigned a prevention policy and that it has been applied.", "SI-3")
    findings.sort(key=lambda f: SEV[f["severity"]][2])
    fcnt = {k: sum(1 for f in findings if f["severity"] == k) for k in SEV}

    # Trend against earlier months.
    prior, series = load_prior(a.history_dir, a.prior_summary, a.period)
    series[a.period] = {"period": a.period, "coverage_pct": cov}
    prior_status = {r["control"]: r["status"] for r in (prior or {}).get("rows", [])}

    esc = html.escape

    def delta_html(now, then, unit=""):
        if now is None or then is None:
            return ""
        diff = now - then
        cls = "up" if diff > 0 else "down" if diff < 0 else ""
        return '<small class="%s">%s%s%s vs %s</small>' % (cls, "+" if diff > 0 else "", diff, unit, esc(prior["period"])) if diff else ""

    def change_cell(ctrl, status):
        if not prior:
            return ""
        old = prior_status.get(ctrl)
        if old is None:
            return '<td><span class="chg same">New</span></td>'
        if RANK[status] > RANK[old]:
            return '<td><span class="chg better">&#9650; %s &rarr; %s</span></td>' % (STATUS[old][0], STATUS[status][0])
        if RANK[status] < RANK[old]:
            return '<td><span class="chg worse">&#9660; %s &rarr; %s</span></td>' % (STATUS[old][0], STATUS[status][0])
        return '<td><span class="chg same">No change</span></td>'

    chg_head = "<th>Change</th>" if prior else ""
    widths = '<col style="width:10%"><col style="width:19%"><col style="width:17%"><col style="width:13%"><col style="width:41%">' if prior else '<col style="width:14%"><col style="width:20%"><col style="width:18%"><col style="width:48%">'
    trs = "".join('<tr><td class="ctl" style="--c:%s">%s</td><td><b>%s</b></td><td><span class="pill" style="--c:%s">%s</span></td>%s<td>%s</td></tr>'
                  % (STATUS[s][1], esc(c), esc(t), STATUS[s][1], STATUS[s][0], change_cell(c, s), esc(e)) for c, t, s, e in rows)
    kp = "".join('<div class="kpi" style="--c:%s"><b>%d</b><span>%s</span>%s</div>' % (
        STATUS[k][1], cnt[k], STATUS[k][0], delta_html(cnt[k], (prior or {}).get("counts", {}).get(k)) if prior else "") for k in STATUS)
    kp = ('<div class="kpi" style="--c:#14213d"><b>%s</b><span>Evidence coverage</span>%s</div>' % ("%d%%" % cov if cov is not None else "n/a", delta_html(cov, (prior or {}).get("coverage_pct"), " pts"))) + kp
    nrows = len(rows) or 1
    pbar = '<div class="bar" aria-hidden="true">%s</div><div class="legend">%s</div>' % (
        "".join('<i style="width:%.1f%%;background:%s"></i>' % (100.0 * cnt[k] / nrows, STATUS[k][1]) for k in STATUS if cnt[k]),
        "".join('<span><em style="background:%s"></em>%s %d</span>' % (STATUS[k][1], STATUS[k][0], cnt[k]) for k in STATUS))

    # Findings table
    if findings:
        ftr = "".join('<tr><td><span class="pill" style="--c:%s">%s</span></td><td><b>%s</b><div class="small">%s</div></td><td>%s<div class="act"><b>Action:</b> %s</div></td></tr>' % (
            SEV[f["severity"]][1], SEV[f["severity"]][0], esc(f["title"]), esc(f["controls"]), esc(f["evidence"]), esc(f["action"])) for f in findings)
        ftable = '<div class="tw"><table><colgroup><col style="width:11%%"><col style="width:25%%"><col style="width:64%%"></colgroup><thead><tr><th>Severity</th><th>Finding</th><th>Evidence and recommended action</th></tr></thead><tbody>%s</tbody></table></div>' % ftr
        fsub = "%d high, %d medium, %d low. " % (fcnt["high"], fcnt["medium"], fcnt["low"])
        if prior and prior.get("findings") is not None:
            pc = {k: sum(1 for f in prior["findings"] if f.get("severity") == k) for k in SEV}
            fsub += "In %s: %d high, %d medium, %d low. " % (prior["period"], pc["high"], pc["medium"], pc["low"])
    else:
        ftable, fsub = '<div class="panel">No findings crossed an observation threshold in the evidence collected.</div>', ""

    # Trend panel
    ser = sorted(series.items())[-6:]
    if prior and len(ser) > 1:
        trend = '<div class="panel fig"><div class="cap">Evidence coverage by month</div>%s<p class="small">Supported counts 1 and partial 0.5, over the control groups that telemetry can evidence (manual-review groups are left out). Prior month: %s.</p></div>' % (
            bars([(p, s["coverage_pct"]) for p, s in ser], "#1D4ED8", suffix="%"), esc(prior["period"]))
    else:
        trend = '<div class="panel small">No earlier month was supplied, so there is no trend yet. Save each month\'s summary as <code>compliance_summary_YYYY-MM.json</code> in a history folder and pass it with <code>--history-dir</code>.</div>'

    # Connectors, grouped by application with the events each delivered in the period
    grp = collections.OrderedDict()
    for app, st_ in (conn_list or []):
        g = grp.setdefault(str(app), collections.Counter())
        g[str(st_)] += 1
    crow = []
    for app, states in grp.items():
        tab = CONNECTOR_TABLE.get(app)
        ev = events_of(tab) if tab else None
        evc = "&mdash;" if ev is None else ('<span class="zero">0</span>' if ev == 0 else n(ev))
        stc = ", ".join("%s" % k if len(states) == 1 else "%d %s" % (v, k) for k, v in states.items())
        crow.append("<tr><td>%s%s</td><td>%s</td><td>%s</td></tr>" % (esc(app), (" &times;%d" % sum(states.values())) if sum(states.values()) > 1 else "", esc(stc), evc))
    half = (len(crow) + 1) // 2
    chead = "<thead><tr><th>Connector</th><th>State</th><th>Events in %s</th></tr></thead>" % mon_name
    cwid = '<colgroup><col style="width:44%"><col style="width:24%"><col style="width:32%"></colgroup>'
    def ctab(rs):
        return '<div class="tw keep" style="margin-top:0"><table>%s%s<tbody>%s</tbody></table></div>' % (cwid, chead, "".join(rs))
    ctr = ('<div class="two">%s%s</div>' % (ctab(crow[:half]), ctab(crow[half:])) if len(crow) > 1 else ctab(crow)) if crow else '<div class="panel small">Connector list not collected.</div>'

    wl_chart = bars(top_with_other([(r["Workload"], r["events"]) for r in wl_rows], 5, "Other") if wl_rows else [], "#1D4ED8")
    au_chart = bars(top_with_other([(r["Category"], r["events"]) for r in au_rows], 5, "Other") if au_rows else [], "#14213D")
    order = ["0", "<1000", "1000 - 2000", "2000 - 4000", "4000 - 8000", ">8000"]
    sc_chart = bars([(k, f_score[k]) for k in order if k in (f_score or {})] if f_score else [], "#B45309")
    disp = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), v) for k, v in (f_class or {}).items())
    if new_inc is not None:
        disp += "<tr><td>Still new (not triaged)</td><td>%s</td></tr>" % new_inc
    if closed_inc is not None and not f_class:
        disp += "<tr><td>Closed</td><td>%s</td></tr>" % closed_inc

    st_by = {r[0]: r[2] for r in rows}
    gaps = []
    if st_by["AU-4 / AU-11"] != "supported":
        gaps.append("<li><b>Log retention and capacity (AU-4, AU-11):</b> confirm the configured retention for each index; %s</li>" % (
            "the history depth measured above is what exists today, not a setting. Sources whose history was not measured (very large tables time out) need a narrower query." if hist_ok else "measure history depth per source with the history_ queries."))
    if not ca:
        gaps.append("<li><b>MFA and admin protection (IA-2, IA-5):</b> collect the Conditional Access policies to see which enforce MFA and for whom.</li>")
    elif not ca_enf:
        gaps.append("<li><b>MFA enforcement (IA-2, IA-5):</b> no Conditional Access policy is enforced; MFA registration alone is not enforcement.</li>")
    if not qualys:
        gaps.append("<li><b>Vulnerability findings (RA-5, SI-2):</b> pull findings, severity and age from the scanner.</li>")
    if not net_src or not end_src:
        gaps.append("<li><b>%s:</b> needs %s data source.</li>" % (
            "Network boundary and endpoint protection (SC-7, SI-3)" if (not net_src and not end_src) else "Network boundary (SC-7)" if not net_src else "Endpoint protection (SI-3)",
            "a firewall or EDR" if (not net_src and not end_src) else "a firewall" if not net_src else "an EDR"))
    if rep_n:
        gaps.append("<li><b>Configuration evidence (CM-2, CM-6):</b> %s saved reports exist on the tenant; none was run for configuration evidence.</li>" % rep_n)
    if ctf and ctf["missing_days"]:
        gaps.append("<li><b>CloudTrail archive (AU-2, AU-12):</b> %d of %d days of %s are archived, so the CloudTrail counts cover archived days only (not archived: %s%s). "
                    "Backfill the scheduled report CloudTrail_Activity_Report for those days and rebuild.</li>" % (
                        ctf["days_archived"], ctf["days_expected"], a.period, ", ".join(ctf["missing_days"][:10]), " ..." if len(ctf["missing_days"]) > 10 else ""))
    if m365 and m365["missing_days"]:
        gaps.append("<li><b>Office 365 and Entra archive (AU-2, AU-12):</b> %d of %d days of %s are archived, so the Office 365 and Entra counts cover archived days only (not archived: %s%s). "
                    "Backfill the scheduled report Office365_Entra_Activity_Report for those days and rebuild.</li>" % (
                        m365["days_archived"], m365["days_expected"], a.period, ", ".join(m365["missing_days"][:10]), " ..." if len(m365["missing_days"]) > 10 else ""))
    if m365:
        absent = [sr["table"] for sr in m365["sources"].values() if not sr["days_ok"]]
        if absent:
            gaps.append("<li><b>Not in the Office 365 and Entra archive:</b> %s had no data on any archived day (the table is absent on this tenant or the archived script version did not include it). It is not counted as zero.</li>" % ", ".join(absent))
    gaps.append("<li><b>Policies and procedures (AC-1, IA-1, IR-1):</b> supplied by the customer.</li>")

    month = datetime.date(int(yy), int(mm), 1).strftime("%B %Y")
    title = "%s Compliance Evidence Report - %s" % (a.tenant_name, month)
    today = datetime.date.today().strftime("%d %B %Y")
    lead_new = ("%s of %s incidents in the window are still marked new. " % (n(new_inc), n(inc_total))) if inc_total and new_inc else ""
    lead_find = ("%d findings need attention (%d high). " % (len(findings), fcnt["high"])) if findings else ""
    ARCHIVED = {"Office365", "AzureSigninLogs", "AzureAuditLogs", "AADServicePrincipalSignInLogs", "AADNonInteractiveUserSignInLogs", "CloudTrail"}
    live_t = sorted(set(t_ for t_ in used_tables if t_ not in ARCHIVED))
    arch_t = sorted(set(t_ for t_ in used_tables if t_ in ARCHIVED))
    meth_tables = (("KQL over " + ", ".join(live_t)) if live_t else "no live event queries") + (
        ("; counts for %s read from the daily archives of the scheduled reports Office365_Entra_Activity_Report and CloudTrail_Activity_Report, never searched" % ", ".join(arch_t)) if arch_t else "")
    meth_dumps = ", ".join(used_dumps) or "no resource dumps"
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body>
<div class="hero"><div class="wrap"><div class="eyebrow">Compliance evidence report</div><h1>{title}</h1><div class="chips"><span class="chip">Tenant: {tname} (grid account <code>{tenant}</code>)</span><span class="chip">Site: {site}</span><span class="chip">Evidence window: {month}</span><span class="chip">Prepared {today}</span></div></div></div>
<div class="wrap">
<div class="kpis" style="--k:5">{kp}</div>
<div class="panel"><b>Evidence picture</b>{pbar}</div>
<div class="panel">
<p><b>What the evidence shows.</b> {logging_line}</p>
<p><b>Why it matters.</b> Controls that depend on review, identity configuration, inventory and vulnerability data are only partly evidenced, and any control with no data source on this tenant is reported as not observed.</p>
<p><b>Result.</b> 13 control groups assessed: {c_s} supported, {c_p} partial, {c_n} not observed, {c_m} needing customer documentation. Evidence coverage is {cov}{cov_prior}. {lead_find}{lead_new}</p>
<p><b>Evidence strength.</b> Confirmed: event volumes, incident counts, inventory counts. Inferred: the mapping of evidence to control status. Unknown: configured retention, vulnerability findings, policy documents.</p></div>
<div class="read"><b>Read this first.</b> This is a reduced, evidence-led view of 13 NIST SP 800-53 Rev. 5 control groups, assembled by read-only queries to the {site} connector. It is not the full Compliance Package and does not certify or attest compliance. "Not observed" means evidence was not collected in this run; it is not a failed control. Evidence coverage is a measure of how much of the evidence was observed, not a compliance score.</div>
<h2><span class="n">1</span>Key findings</h2>
<p class="small">{fsub}Observations computed from the evidence, using analyst thresholds. They show where to look first; they are not compliance determinations.</p>
{ftable}
<h2><span class="n">2</span>Posture by control group</h2>
<div class="tw"><table><colgroup>{widths}</colgroup><thead><tr><th>Control</th><th>Topic</th><th>Status</th>{chg_head}<th>What the evidence shows</th></tr></thead><tbody>{trs}</tbody></table></div>
{trend}
<h2><span class="n">3</span>Monitoring coverage</h2>
<div class="two"><div class="panel fig"><div class="cap">Office 365 events by workload ({o365} total)</div>{wl_chart}</div>
<div class="panel fig"><div class="cap">Entra directory-audit events by category ({audit} total)</div>{au_chart}</div></div>
<div class="cap" style="margin-top:14px">Installed connectors</div>{ctr}
<h2><span class="n">4</span>Detection and incident handling</h2>
<div class="two"><div class="panel fig"><div class="cap">Behavior summaries by risk score ({beh} total)</div>{sc_chart}</div>
<div><div class="cap">Incident disposition</div><div class="tw" style="margin-top:0"><table><colgroup><col style="width:68%"><col style="width:32%"></colgroup><thead><tr><th>Disposition</th><th>Count</th></tr></thead><tbody>{disp}</tbody></table></div></div></div>
<h2><span class="n">5</span>Gaps and next evidence</h2><div class="panel"><ul class="gaps">
{gaps}</ul></div>
<div class="foot"><h2><span class="n">6</span>Methodology</h2><p>Evidence was gathered on {today} by read-only queries through the {site} MCP connector against account <code>{tenant}</code>: {meth_tables}; behavior-summary search; resource dumps of {meth_dumps}; connector and report inventory. Event and incident counts are for {month}; resource-table counts are current snapshots. Control status is an analyst mapping of that evidence onto NIST SP 800-53 Rev. 5 and is not the output of the Fluency compliance engine. Evidence coverage counts supported as 1 and partial as 0.5 over the control groups telemetry can evidence. Key-finding thresholds are the analyst's. Framework views (NIST, ISO/CMMC, PCI DSS, HIPAA, SOC 2, CIS, FedRAMP, GDPR) are rendered from this run's summary JSON. Individual users, case ids and comments are deliberately omitted.</p></div>
</div></body></html>""".format(
        css=CSS, pbar=pbar, title=esc(title), tname=esc(a.tenant_name), tenant=esc(a.tenant), site=esc(a.site), month=month, today=today,
        logging_line=("Audit logging and monitoring were active in the window." if logging_status() == "supported" else "Audit logging evidence in the window is limited."),
        c_s=cnt["supported"], c_p=cnt["partial"], c_n=cnt["not_observed"], c_m=cnt["needs_manual_review"], cov=("%d%%" % cov) if cov is not None else "n/a",
        cov_prior=(" (%s in %s)" % ("%d%%" % prior["coverage_pct"], prior["period"])) if prior and prior.get("coverage_pct") is not None else "",
        lead_find=lead_find, lead_new=lead_new, kp=kp, trs=trs, widths=widths, chg_head=chg_head, fsub=fsub, ftable=ftable, trend=trend,
        o365=n(o365), audit=n(audit), wl_chart=wl_chart, au_chart=au_chart, ctr=ctr, mon_name=mon_name, beh=n(beh_total), sc_chart=sc_chart, disp=disp,
        gaps="\n".join(gaps), meth_tables=esc(meth_tables), meth_dumps=esc(meth_dumps))
    with open(a.out, "w") as f:
        f.write(doc)
    if a.summary_json:
        with open(a.summary_json, "w") as f:
            facts = {
                "events": {"office365": o365, "signin": sin, "signin_failed": failed, "signin_users": si["users"] if si else None, "directory_audit": audit, "windows_audit": win_n,
                           "service_principal_signin": sp_n, "service_principal_failed": s_sp["totals"].get("failed") if s_sp else None,
                           "service_principal_secret_errors": s_sp["totals"].get("secretErrors", 0) if s_sp else None, "non_interactive_signin": ni_n},
                "workloads": [[r["Workload"], r["events"]] for r in sorted(wl_rows or [], key=lambda r: -r["events"])],
                "audit_categories": [[r["Category"], r["events"]] for r in sorted(au_rows or [], key=lambda r: -r["events"])],
                "users": us, "hygiene": hy, "devices": dv, "qualys_hosts": qualys, "behavior_summaries": beh_total,
                "incidents": {"total": inc_total, "new": new_inc, "closed": closed_inc} if inc_total is not None else None,
                "cloudtrail": ctf, "m365_archive": m365, "sources": extra, "history": hist, "retention": ret, "guardduty": gd, "google_workspace": gw,
                "defender": mdf, "scanners_endpoint": vnd, "app_registrations": apf, "enterprise_apps": spf, "groups": grf, "google_groups": ggf,
                "conditional_access": ({"total": (ca_all if ca else 0), "enforced": ca_enf or 0, "report_only": ca_rep, "by_state": ca} if ca is not None else None),
                "admins": {r.get("userPrincipalName", "").lower(): sorted(r.get("roles") or []) for r in (u_rec or []) if (r.get("userRegistration") or {}).get("isAdmin") is True or r.get("roles")},
                "directory_users": sorted((r.get("userPrincipalName") or "").lower() for r in (u_rec or []))[:5000],
                "note": "Resource-table counts are a snapshot as of the dump, not the report month; event counts are for the month.",
            }
            out = {"period": a.period, "counts": cnt, "coverage_pct": cov,
                   "rows": [{"control": c, "title": t, "status": s_, "evidence": e} for c, t, s_, e in rows],
                   "findings": findings, "facts": facts}
            if prior:
                out["prior"] = {"period": prior["period"], "coverage_pct": prior.get("coverage_pct"), "counts": prior.get("counts"),
                                "rows": [{"control": r["control"], "status": r["status"]} for r in prior.get("rows", [])]}
            json.dump(out, f, indent=1)
    print(a.out)


if __name__ == "__main__":
    sys.exit(main())
