// Windows Server activity report: ingestion statistics (events and bytes by host and event ID, the content of
// WindowsSrv_Ingress_Search_Report) extended with security activity: user logons and failures, source addresses,
// logon types, privileged logons, account and group changes, services and scheduled tasks, and audit-log tampering.
// It is built for the scheduled daily run, which is archived (the archive is summed over a week, month or quarter);
// the activity-report skills read the tables it returns.
// Source: WindowsAudit (the parsed NXLog Windows event log). The older nxlogAD events in the default table are not read.
// The window is half-open (from <= timestamp < to), so back-to-back daily runs never count a boundary second twice.
// interval is a KQL timespan: "1d" for archived daily runs, "1h" for a single-day view.
//
// Four scans (one table each, plus "sources"):
//   win_trend         one row per interval: every headline count, whose sum is the period total.
//   win_facets        one facet query: one table per breakdown (value plus count_). Counts only.
//   win_failed_source top 100 source addresses of failed logons, with the distinct user names tried (the spray test).
//   win_ingest        events and bytes per host and event ID (top 300 pairs), with the event name from the AD_EventID lookup.
// It covers what WindowsSrv_Ingress_Search_Report returns (total events, hosts, events by host and by event ID with the
// AD_EventID names) and adds bytes and the security tables. It does not read the nxlogAD events of the default table.
// The facet tables carry user names, account names and IP addresses (user, failedUser, failedIp, privAccount,
// acctActor, acctTarget, groupActor, tamperActor), as do win_failed_source (addresses); the archive is personal data and a
// report shared outside the tenant should not use them.
//
// What adds up across days: every count (events, bytes, logons, failures, changes, facet counts). What does not: the
// distinct counts in win_failed_source (usernames, hosts) and the hosts figure of win_trend; read them per day. Facets
// and win_failed_source keep the top 100 values of the run, so for an archived daily run a range total is a lower
// bound for a value outside a day's top 100. Facet pairs are not kept: acctActor and acctTarget are separate lists.
// User logons are 4624 events of user accounts: machine accounts (names ending in $) and the empty name "-" are left
// out, as in summary_windows. Failed logons are 4625 (SubStatus gives the reason). Network logons (type 3) are
// counted with the others; remote desktop is logon type 10 (and 7 for an unlock of a remote session).
// Privileged logons are 4672 of user accounts; SYSTEM, the service accounts, DWM-* and UMFD-* are left out.
// Host names are the part before the first dot, so "dc1" and "dc1.corp.local" are one host.
//
// A scan that fails (no WindowsAudit table on the tenant, or any query error) returns an empty table and is recorded in
// "sources" with status "not available" and the error text; an "ok" scan with no rows is a day without events. A tenant
// without Windows data is never an error.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let win_trend = GetTrend(status, rangeFrom, rangeTo, interval)
    let win_facets = GetFacets(status, rangeFrom, rangeTo)
    let win_failed_source = GetFailedSource(status, rangeFrom, rangeTo, interval)
    let win_ingest = GetIngest(status, rangeFrom, rangeTo, interval)
    let sources = jsonTable(status.rows)
    return {
        win_trend,
        win_facets,
        win_failed_source,
        win_ingest,
        sources
    }
}

function validateTimeRange(from, to) {
    if (from.After(to)) {
        throw new Error("rangeFrom must be less than rangeTo", "RangeError")
    }
    if (to.After(from.Add("40d"))) {
        throw new Error("total duration must not exceed 40 days", "RangeError")
    }
    return true
}

// The shared window and the cleaned fields: eid (EventID text), usr (target account, lower case), isUser (a user
// account: not empty, not "-", not a machine account), host (short lower-case host name), subj (subject account, lower
// case) and subjUser (a person: not empty, not "-", not a machine account, SYSTEM, a service account, DWM-* or UMFD-*).
function base(rangeFrom, rangeTo) {
    return `
    WindowsAudit
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | extend eid = tostring(EventID), usr = tolower(tostring(TargetUserName)), subj = tolower(tostring(SubjectUserName)), host = tolower(tostring(split(tostring(Hostname), ".")[0]))
    | extend isUser = isnotempty(usr) and usr != "-" and not(usr endswith "$")
    | extend subjUser = isnotempty(subj) and subj != "-" and not(subj endswith "$") and subj != "system" and subj != "local service" and subj != "network service" and not(subj startswith "dwm-") and not(subj startswith "umfd-")
    `
}

// ---- Trend (one row per interval) ------------------------------------------------------------------------
// events, bytes (sum of the record size) and hosts are the ingestion figures. logonsOk (4624, user accounts),
// logonsFailed (4625), rdpLogons (4624 type 10), networkLogons (4624 type 3), explicitCreds (4648), kerberosFailures
// (4771), ntlmFailures (4776 with a non-zero status), lockouts (4740), privLogons (4672, user accounts),
// accountCreated / accountEnabled / accountDisabled / accountDeleted (4720 / 4722 / 4725 / 4726), passwordChanges
// (4723, 4724), groupAdds (4728, 4732, 4756), servicesInstalled (4697, 7045), tasksCreated (4698),
// auditPolicyChanges (4719), logsCleared (1102, 104), processCreations (4688), powershellScripts (4104).
function GetTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${base(rangeFrom, rangeTo)}
    | extend lt = tostring(LogonType), st = tostring(Status)
    | summarize
        events = count(),
        bytes = sum(size),
        hosts = count_distinct(host),
        logonsOk = countif(eid == "4624" and isUser),
        logonsFailed = countif(eid == "4625"),
        rdpLogons = countif(eid == "4624" and isUser and lt == "10"),
        networkLogons = countif(eid == "4624" and isUser and lt == "3"),
        explicitCreds = countif(eid == "4648"),
        kerberosFailures = countif(eid == "4771"),
        ntlmFailures = countif(eid == "4776" and st != "0x0"),
        lockouts = countif(eid == "4740"),
        privLogons = countif(eid == "4672" and subjUser),
        accountCreated = countif(eid == "4720"),
        accountEnabled = countif(eid == "4722"),
        accountDisabled = countif(eid == "4725"),
        accountDeleted = countif(eid == "4726"),
        passwordChanges = countif(eid in ("4723", "4724")),
        groupAdds = countif(eid in ("4728", "4732", "4756")),
        servicesInstalled = countif(eid in ("4697", "7045")),
        tasksCreated = countif(eid == "4698"),
        auditPolicyChanges = countif(eid == "4719"),
        logsCleared = countif(eid in ("1102", "104")),
        processCreations = countif(eid == "4688"),
        powershellScripts = countif(eid == "4104")
        by Date = bin(timestamp, ${interval})
    | sort by Date asc
    `
    return Run(status, "WindowsAudit trend", query)
}

// ---- Facets (one query, one table per facet) -------------------------------------------------------------
// Every facet label is "(none)" for an event outside its subset, so "(none)" is the complement of the subset.
//   host, eventId                  every event (eventId is the EventID)
//   logonType                      type of successful user logons (4624)
//   failedReason, failedUser, failedIp   SubStatus (else Status), target account and source address of failed logons (4625)
//   logonUser                      target account of successful user logons
//   privAccount                    subject account of special-privilege logons (4672), people only
//   acctEvent, acctActor, acctTarget     event ID, actor and target of account events (4720, 4722, 4725, 4726, 4723, 4724, 4738, 4767)
//   groupName, groupActor          group and actor of group additions (4728, 4732, 4756)
//   persistItem                    "Service: <name>" or "Task: <name>" of services and tasks installed (4697, 7045, 4698)
//   tamperEvent, tamperHost, tamperActor  event ID, host and actor of audit-log cleared (1102, 104) and policy changes (4719)
// The engine returns at most 100 values per facet; rarer values are lost (eventId and logonUser can exceed 100).
function GetFacets(status, rangeFrom, rangeTo) {
    let query = `
    ${base(rangeFrom, rangeTo)}
    | extend isLogon = eid == "4624" and isUser, isFail = eid == "4625"
    | extend isAcct = eid in ("4720", "4722", "4725", "4726", "4723", "4724", "4738", "4767")
    | extend isGroup = eid in ("4728", "4732", "4756"), isPersist = eid in ("4697", "7045", "4698"), isTamper = eid in ("1102", "104", "4719")
    | extend src = iff(isempty(IpAddress) or IpAddress == "-" or IpAddress == "::1" or IpAddress == "127.0.0.1", "(local or not recorded)", tostring(IpAddress))
    | extend usrName = iff(isempty(usr) or usr == "-", "(not recorded)", usr), subjName = iff(isempty(subj) or subj == "-", "(not recorded)", subj)
    | extend code = iff(isnotempty(tostring(SubStatus)), tolower(tostring(SubStatus)), iff(isnotempty(tostring(Status)), tolower(tostring(Status)), "(not recorded)"))
    | extend itemName = iff(isnotempty(tostring(TaskName)), tostring(TaskName), iff(isnotempty(tostring(ServiceName)), tostring(ServiceName), "(not recorded)"))
    | extend logonType = iff(isLogon, tostring(LogonType), "(none)"), failedReason = iff(isFail, code, "(none)"), failedUser = iff(isFail, usrName, "(none)"), failedIp = iff(isFail, src, "(none)")
    | extend logonUser = iff(isLogon, usr, "(none)"), privAccount = iff(eid == "4672" and subjUser, subj, "(none)")
    | extend acctEvent = iff(isAcct, eid, "(none)"), acctActor = iff(isAcct, subjName, "(none)"), acctTarget = iff(isAcct, usrName, "(none)")
    | extend groupName = iff(isGroup, usrName, "(none)"), groupActor = iff(isGroup, subjName, "(none)")
    | extend persistItem = iff(isPersist, strcat(iff(eid == "4698", "Task: ", "Service: "), itemName), "(none)")
    | extend tamperEvent = iff(isTamper, eid, "(none)"), tamperHost = iff(isTamper, host, "(none)"), tamperActor = iff(isTamper, subjName, "(none)")
    | extend eventId = eid
    | facet by host, eventId, logonType, failedReason, failedUser, failedIp, logonUser, privAccount, acctEvent, acctActor, acctTarget, groupName, groupActor, persistItem, tamperEvent, tamperHost, tamperActor with (take 0)
    `
    return Run(status, "WindowsAudit facets", query)
}

// ---- Failed logons by source address ---------------------------------------------------------------------
// Top 100 source addresses by failed logons. Many accounts from one address is a spray, many failures with few
// accounts is brute force, the rest is probing. The distinct counts are exact for one run and one row only.
function GetFailedSource(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${base(rangeFrom, rangeTo)}
    | where eid == "4625"
    | extend src = iff(isempty(IpAddress) or IpAddress == "-" or IpAddress == "::1" or IpAddress == "127.0.0.1", "(local or not recorded)", tostring(IpAddress))
    | extend usr = iff(isempty(usr) or usr == "-", "(not recorded)", usr)
    | summarize failures = count(), usernames = count_distinct(usr), hosts = count_distinct(host),
                firstSeen = min(timestamp), lastSeen = max(timestamp)
        by Date = bin(timestamp, ${interval}), remip = src
    | extend pattern = iff(usernames >= 10, "Credential spray", iff(failures >= 50, "Brute force", "Probe"))
    | top 100 by failures desc
    `
    return Run(status, "failed logons by source", query)
}

// ---- Ingestion -------------------------------------------------------------------------------------------
// Events and bytes (sum of the record size) per host and event ID. Top 300 pairs, so a host's and an event ID's totals
// are exact unless more than 300 pairs exist. eventName is the event ID's title from the AD_EventID lookup table
// (as in WindowsSrv_Ingress_Search_Report); description is the title carried on the event, kept as the fallback for
// an ID the lookup does not know; eventName falls back to it, and is empty when neither has one.
function GetIngest(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${base(rangeFrom, rangeTo)}
    | summarize events = count(), bytes = sum(size), description = take_any(tostring(EventIDDescription))
        by Date = bin(timestamp, ${interval}), host, eventId = eid
    | top 300 by events desc
    `
    let t = Run(status, "events and bytes by host and event ID", query)
    try {
        t.NewColumnLambda("eventName", "", (row) => {
            let {exist, value} = fluencyEntityinfoLookup("AD_EventID", "Event ID", toString(row.eventId), "Description")
            if (exist) {
                return toString(value)
            }
            return toString(row.description)
        })
        status.rows = append(status.rows, {source: "event ID names (AD_EventID lookup)", status: "ok"})
    } catch (e) {
        status.rows = append(status.rows, {source: "event ID names (AD_EventID lookup)", status: "not available", detail: toString(e)})
    }
    return t
}

// Runs one scan. A missing table or a failed query returns an empty table and is recorded in status.
function Run(status, name, query) {
    try {
        let r = kql(query)
        status.rows = append(status.rows, {source: name, status: "ok"})
        return r
    } catch (e) {
        status.rows = append(status.rows, {source: name, status: "not available", detail: toString(e)})
        return new Table()
    }
}
