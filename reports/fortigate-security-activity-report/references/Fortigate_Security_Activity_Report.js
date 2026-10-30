// FortiGate security activity report: SSL-VPN failed logins and access, IPsec tunnels, application-control and
// web-filter blocks, IPS/DoS anomalies and administrator activity. It grew out of Fortigate_SSLVPN_FailedLogin, whose
// failed-login analysis is kept as the core. It is built for the scheduled daily run, which is archived (the archive
// is summed over a week, month or quarter); a dashboard or summary report is built from the tables it returns.
// The tables carrying user names and IP addresses (fg_failed_source, fg_failed_user, fg_vpn_user, fg_admin) make the archive personal data; a report shared outside the tenant should not use them.
// The window is half-open (from <= timestamp < to), so back-to-back daily runs never count a boundary second twice.
// interval is a KQL timespan: "1d" for archived daily runs, "1h" for a single-day view.
// Source: NetworkFortigateEvent (event and UTM logs). Traffic logs are not scanned: they are far larger and the
// measures here do not need them.
//
// What adds up across days: every count (failures, sessions, blocks, changes). What does not: the distinct
// counts (sources, usernames, countries, devices, hosts) in the per-entity tables; they are exact
// for one run and one row, so read them per day. Per-entity tables keep the top 100 rows of the run, so for an archived
// daily run a range total is a lower bound for an entity outside a day's top 100.
// Failed SSL-VPN logins exclude the portal session expiry (reason "wrong vdom (0:0) or time expired"), which is not a
// credential failure; it is counted separately as sessionExpiries. Events with user=N/A are kept, because FortiOS
// leaves the username empty on most failures; they show as "(not recorded)".
// The comparison with the previous period is not computed here; the rollup of the archive gives it.

// A scan that fails (no NetworkFortigateEvent table on the tenant, or any query error) returns an empty table and is
// recorded in "sources" with status "not available" and the error text; an "ok" scan with no rows is a day without
// events. A tenant without FortiGate data is never an error.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let fg_trend = GetTrend(status, rangeFrom, rangeTo, interval)
    let fg_failed_device = GetFailedDevice(status, rangeFrom, rangeTo, interval)
    let fg_totals = Totals(fg_trend, fg_failed_device)
    let fg_failed_country = GetFailedCountry(status, rangeFrom, rangeTo, interval)
    let fg_failed_source = GetFailedSource(status, rangeFrom, rangeTo, interval)
    let fg_failed_user = GetFailedUser(status, rangeFrom, rangeTo, interval)
    let fg_vpn_user = GetVpnUser(status, rangeFrom, rangeTo, interval)
    let fg_anomaly = GetAnomaly(status, rangeFrom, rangeTo, interval)
    let fg_admin = GetAdmin(status, rangeFrom, rangeTo, interval)
    let fg_blocked = GetBlocked(status, rangeFrom, rangeTo, interval)
    let sources = jsonTable(status.rows)
    return {
        fg_trend,
        fg_totals,
        fg_failed_device,
        fg_failed_country,
        fg_failed_source,
        fg_failed_user,
        fg_vpn_user,
        fg_anomaly,
        fg_admin,
        fg_blocked,
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

// ---- Trend and totals ------------------------------------------------------------------------------------
// failedLogins (SSL-VPN ssl-login-fail, session expiry excluded);
// sessionExpiries (ssl-login-fail with reason "wrong vdom (0:0) or time expired"); sslSessions (SSL tunnel-up);
// ipsecTunnelsUp / ipsecTunnelsDown (IPsec tunnel-up / tunnel-down);
// appCtrlBlocks (application control block); webFilterBlocks (web filter blocked); ipsAnomalies (DoS-policy
// anomaly events); adminLogins / adminLoginsFailed (system login by status); adminConfigChanges (system Edit, Add,
// Delete).
// One scan: the prefilter reads only the event types listed. A new metric needs its event type added there, or it counts zero.
function GetTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where (subtype == "vpn" and action in ("ssl-login-fail", "tunnel-up", "tunnel-down")) or (subtype == "app-ctrl" and action == "block") or (subtype == "webfilter" and action == "blocked") or subtype == "anomaly" or (subtype == "system" and action in ("login", "Edit", "Add", "Delete"))
    | extend reason = tostring(_fields.reason), tt = tostring(_fields.tunneltype), st = tostring(_fields.status)
    | summarize
        failedLogins = countif(subtype == "vpn" and action == "ssl-login-fail" and reason != "wrong vdom (0:0) or time expired"),
        sessionExpiries = countif(subtype == "vpn" and action == "ssl-login-fail" and reason == "wrong vdom (0:0) or time expired"),
        sslSessions = countif(subtype == "vpn" and action == "tunnel-up" and tt == "ssl-tunnel"),
        ipsecTunnelsUp = countif(subtype == "vpn" and action == "tunnel-up" and tt == "ipsec"),
        ipsecTunnelsDown = countif(subtype == "vpn" and action == "tunnel-down" and tt == "ipsec"),
        appCtrlBlocks = countif(subtype == "app-ctrl" and action == "block"),
        webFilterBlocks = countif(subtype == "webfilter" and action == "blocked"),
        ipsAnomalies = countif(subtype == "anomaly"),
        adminLogins = countif(subtype == "system" and action == "login" and st == "success"),
        adminLoginsFailed = countif(subtype == "system" and action == "login" and st != "success"),
        adminConfigChanges = countif(subtype == "system" and action in ("Edit", "Add", "Delete"))
        by Date = bin(TimeGenerated, ${interval})
    | sort by Date asc
    `
    return Run(status, "NetworkFortigateEvent trend", query)
}

// One row of headline totals for the run: the sum of fg_trend (failedLogins, sslSessions, blocked = application
// control plus web filter, ipsAnomalies, adminChanges, adminLoginsFailed, ipsecUp, ipsecDown) and sources, the sum over
// fg_failed_device of each device's distinct source addresses (exact for one device; a source hitting two devices is
// counted once per device).
function Totals(trend, device) {
    let box = {failedLogins: 0, sslSessions: 0, blocked: 0, ipsAnomalies: 0, adminChanges: 0, adminLoginsFailed: 0, ipsecUp: 0, ipsecDown: 0, sources: 0}
    trend.Each((r) => {
        box.failedLogins = box.failedLogins + r.failedLogins
        box.sslSessions = box.sslSessions + r.sslSessions
        box.blocked = box.blocked + r.appCtrlBlocks + r.webFilterBlocks
        box.ipsAnomalies = box.ipsAnomalies + r.ipsAnomalies
        box.adminChanges = box.adminChanges + r.adminConfigChanges
        box.adminLoginsFailed = box.adminLoginsFailed + r.adminLoginsFailed
        box.ipsecUp = box.ipsecUp + r.ipsecTunnelsUp
        box.ipsecDown = box.ipsecDown + r.ipsecTunnelsDown
    })
    device.Each((r) => {
        box.sources = box.sources + r.sources
    })
    return jsonTable([{failedLogins: box.failedLogins, sources: box.sources, sslSessions: box.sslSessions, blocked: box.blocked, ipsAnomalies: box.ipsAnomalies, adminChanges: box.adminChanges, adminLoginsFailed: box.adminLoginsFailed, ipsecUp: box.ipsecUp, ipsecDown: box.ipsecDown}])
}

// ---- Failed SSL-VPN logins -------------------------------------------------------------------------------
// The shared selector: failed SSL-VPN logins with the portal session expiry removed, and the cleaned fields
// device, usr (username), cty (country) and rip (remote IP); a missing value is "(not recorded)".
function failBase(rangeFrom, rangeTo) {
    return `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where subtype == "vpn" and action == "ssl-login-fail"
    | extend reason = tostring(_fields.reason), remip = tostring(_fields.remip)
    | where reason != "wrong vdom (0:0) or time expired"
    | extend device = iff(isempty(devname), "(not recorded)", devname)
    | extend usr = iff(isempty(user) or user == "N/A" or user == "null", "(not recorded)", user)
    | extend cty = iff(isempty(srccountry), "(not recorded)", srccountry)
    | extend rip = iff(isempty(remip) or remip == "N/A", "(not recorded)", remip)
    `
}

// Per firewall device and interval.
function GetFailedDevice(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${failBase(rangeFrom, rangeTo)}
    | summarize failures = count(), sources = count_distinct(rip), countries = count_distinct(cty),
                usernames = count_distinct(usr), firstSeen = min(TimeGenerated), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), device
    | sort by Date asc, failures desc
    `
    return Run(status, "failed logins by device", query)
}

// Per source country and interval.
function GetFailedCountry(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${failBase(rangeFrom, rangeTo)}
    | summarize failures = count(), sources = count_distinct(rip), usernames = count_distinct(usr)
        by Date = bin(TimeGenerated, ${interval}), country = cty
    | sort by Date asc, failures desc
    `
    return Run(status, "failed logins by country", query)
}

// Top 100 source addresses by failures. pattern: many usernames from one address is a credential spray, a high count
// with few usernames is brute force, the rest is probing.
function GetFailedSource(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${failBase(rangeFrom, rangeTo)}
    | summarize failures = count(), usernames = count_distinct(usr), country = take_any(cty), device = take_any(device),
                firstSeen = min(TimeGenerated), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), remip = rip
    | extend pattern = iff(usernames >= 10, "Credential spray", iff(failures >= 50, "Brute force", "Probe"))
    | top 100 by failures desc
    `
    return Run(status, "failed logins by source", query)
}

// Top 100 usernames by failures.
function GetFailedUser(status, rangeFrom, rangeTo, interval) {
    let query = `
    ${failBase(rangeFrom, rangeTo)}
    | summarize failures = count(), sources = count_distinct(rip), countries = count_distinct(cty),
                devices = count_distinct(device), firstSeen = min(TimeGenerated), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), user = usr
    | top 100 by failures desc
    `
    return Run(status, "failed logins by user", query)
}

// ---- Access, threats and administration ------------------------------------------------------------------
// Established SSL-VPN tunnels per user: sessions, and the distinct source addresses, countries and devices.
function GetVpnUser(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where subtype == "vpn" and action == "tunnel-up" and tostring(_fields.tunneltype) == "ssl-tunnel"
    | extend remip = tostring(_fields.remip)
    | extend usr = iff(isempty(user) or user == "N/A" or user == "null", "(not recorded)", user)
    | extend rip = iff(isempty(remip) or remip == "N/A", "(not recorded)", remip)
    | extend cty = iff(isempty(srccountry), "(not recorded)", srccountry)
    | extend device = iff(isempty(devname), "(not recorded)", devname)
    | summarize sessions = count(), sources = count_distinct(rip), countries = count_distinct(cty),
                devices = count_distinct(device), firstSeen = min(TimeGenerated), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), user = usr
    | top 100 by sessions desc
    `
    return Run(status, "SSL-VPN sessions by user", query)
}

// IPS/DoS anomalies by attack type and severity.
function GetAnomaly(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where subtype == "anomaly"
    | extend attack = iff(isempty(tostring(_fields.attack)), "(not recorded)", tostring(_fields.attack))
    | extend severity = iff(isempty(tostring(_fields.severity)), "(not recorded)", tostring(_fields.severity))
    | summarize events = count(), sources = count_distinct(srcip), firstSeen = min(TimeGenerated), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), attack, severity
    | sort by Date asc, events desc
    `
    return Run(status, "IPS and DoS anomalies", query)
}

// Administrator accounts: successful and failed logins and configuration changes (Edit, Add, Delete), one row each.
function GetAdmin(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where subtype == "system" and action in ("login", "Edit", "Add", "Delete")
    | extend st = tostring(_fields.status)
    | extend usr = iff(isempty(user) or user == "N/A" or user == "null", "(not recorded)", user)
    | summarize loginsOk = countif(action == "login" and st == "success"),
                loginsFailed = countif(action == "login" and st != "success"),
                changes = countif(action != "login"), lastSeen = max(TimeGenerated)
        by Date = bin(TimeGenerated, ${interval}), admin = usr
    | top 100 by changes desc
    `
    return Run(status, "administrator activity", query)
}

// Application-control blocks (by application) and web-filter blocks (by category), with the distinct internal hosts.
function GetBlocked(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateEvent
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | where (subtype == "app-ctrl" and action == "block") or (subtype == "webfilter" and action == "blocked")
    | extend control = iff(subtype == "app-ctrl", "Application control", "Web filter")
    | extend item = iff(subtype == "app-ctrl", tostring(app), tostring(_fields.catdesc))
    | extend item = iff(isempty(item), "(not recorded)", item)
    | summarize blocks = count(), hosts = count_distinct(srcip)
        by Date = bin(TimeGenerated, ${interval}), control, item
    | top 100 by blocks desc
    `
    return Run(status, "blocked applications and categories", query)
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
