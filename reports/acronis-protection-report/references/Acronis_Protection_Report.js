// Acronis Cyber Protect Cloud protection report: what the Acronis feed (alerts, activities, EDR incidents; the Acronis index) and the
// Acronis agent inventory (acronisAgent, acronisTenant) say about endpoint protection, as counts and short lists that can be archived
// once a day and read later. It is the source for an Acronis data review (EDR cases, agent hygiene, backup, alert quality).
// Host names, Acronis unit names (the administrator's name and e-mail) and process file names are returned; no user names or full paths.
//
// Two kinds of table, and they are read differently:
//   EVENT tables (the window from <= timestamp < to, half-open, so back-to-back daily runs never count a second twice). Default is
//   the previous day (-1d@d .. @d). They are built to be merged: acr_trend, acr_activities and acr_backup are counters (sum them);
//   acr_alerts, acr_incidents, acr_edr_triggers and acr_update_failures are keyed by the vendor's own id, so merge the days by key
//   (Acronis re-sends an alert each time it changes, so an alert seen on two days is ONE alert, and counts of distinct alerts, devices or
//   agents are taken over the merged keyed table, never summed).
//   SNAPSHOT tables (acr_agent_*, acr_defs_age, acr_versions, acr_units, acr_stale_agents, acr_duplicates, acr_no_active_protection,
//   acr_tenants) describe the inventory as it is when the run takes it. Every row carries asOf, the end of the run window.
//   NEVER add the days of a snapshot table together; read the latest archived day.
//
// Tables (plus "sources"):
//   acr_trend              one row per interval: Date, events, alertEvents, activityEvents, incidentEvents.
//   acr_alerts             one row per alert id (first 3000): alertId, events (re-sends), firstSeen, lastSeen, resolved (events that carry
//                          a deletedAt), category, alertType, severity, device, planName (each as of the alert's latest event),
//                          domain (URL host), process (file name only). A day with more than 3000 alerts is clipped at the cap.
//   acr_incidents          one row per incident short id and host (latest state): shortId, host, events, lastUpdate, lastState,
//                          lastMitigation, severity, created, transferredTo (the incident it was merged into, if any).
//   acr_edr_triggers       one row per EDR alert incident and device: incident, device, lastSeen, mitigation, detection, trigger (the file).
//   acr_activities         one row per activity type and title: activityType, title, runs, ok, notOk (runs are distinct activity uuids).
//                          An activity that is re-sent on the next day is counted on both days, so a merged month overstates runs slightly
//                          at each day boundary; the keyed tables (alerts, incidents, failed updates) have no such overlap per key.
//   acr_update_failures    one row per failed update-type activity, agent and unit (first 1000): agentId, unit, activityType, failed,
//                          lastFailure, errorCode. Update types: UpdateVapm, UpdateAgent, Download, DownloadInstaller, AutoUpdateStandby.
//   acr_backup             one row per device and backup plan: device, plan, runs, ok, failed, gbProcessed, lastRun, errors (top 5 codes).
//                          Backup jobs are the activities whose title is "Backing up".
//   acr_agent_summary      one row: agents, online, offline, disabled, uniqueHosts, duplicateHosts, duplicateRecords, units, onLatest,
//                          behind, latestInstaller, defsFresh (under 30 days), defsStale (30 days or more), defsStaleOnline, defsStaleOffline,
//                          defsNoData, noActiveProtection, windows, other, asOf.
//   acr_defs_age           one row per age bucket of each agent's most recent protection-component update: bucket, agents.
//   acr_versions           one row per installer version: version, agents, isLatest.
//   acr_units              one row per Acronis unit: unit, agents, online, stale.
//   acr_stale_agents       agents whose protection definitions are 30 days old or more (first 300, oldest first): host, unit, online,
//                          days, installer, os, id.
//   acr_duplicates         hosts that have more than one agent record: host, records, units, states.
//   acr_no_active_protection  online agents with no Active Protection component: host, unit, installer, days (of the other components).
//   acr_tenants            the Acronis tenant tree (acronisTenant): id, name, kind, parentId, enabled, created.
//
// Definitions:
//   definition age       days from the end of the run window to the most recent update_time of any protection component of the agent
//                        (the Acronis inventory has no last check-in time). An online agent that does not update is a broken updater.
//   stale                a definition age of 30 days or more. Agents with no component data are counted as "no data", not stale.
//   no active protection an agent that is online and has no ACTIVE_PROTECTION component in its protection list.
//   latest installer     the release_id the inventory itself calls the latest (installer_version.latest.release_id).
//
// A query that fails returns an empty table and is recorded in "sources" with status "not available" and the error text. A tenant
// without the AcronisCP connector is never an error: every table comes back empty.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let acr_trend = GetTrend(status, rangeFrom, rangeTo, interval)
    let acr_alerts = GetAlerts(status, rangeFrom, rangeTo)
    let acr_incidents = GetIncidents(status, rangeFrom, rangeTo)
    let acr_edr_triggers = GetEdrTriggers(status, rangeFrom, rangeTo)
    let acr_activities = GetActivities(status, rangeFrom, rangeTo)
    let acr_update_failures = GetUpdateFailures(status, rangeFrom, rangeTo)
    let acr_backup = GetBackup(status, rangeFrom, rangeTo)
    let agents = GetAgents(status, rangeTo)
    let acr_tenants = GetTenants(status)
    let sources = jsonTable(status.rows)
    return {
        acr_trend,
        acr_alerts,
        acr_incidents,
        acr_edr_triggers,
        acr_activities,
        acr_update_failures,
        acr_backup,
        acr_agent_summary: agents.summary,
        acr_defs_age: agents.defsAge,
        acr_versions: agents.versions,
        acr_units: agents.units,
        acr_stale_agents: agents.stale,
        acr_duplicates: agents.duplicates,
        acr_no_active_protection: agents.noAp,
        acr_tenants,
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

// The event window shared by every event query. type is the Acronis event type: acronisAlert, acronisActivity or acronisIncident.
function EventPrefix(rangeFrom, rangeTo, eventType) {
    return `
    Acronis
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | where tostring(['@event_type']) == "${eventType}"
    `
}

// ---- Events ----------------------------------------------------------------------------------------------

// Events per interval and type. Summing the rows gives the period totals.
function GetTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    Acronis
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | extend et = tostring(['@event_type'])
    | summarize events = count(), alertEvents = countif(et == "acronisAlert"), activityEvents = countif(et == "acronisActivity"), incidentEvents = countif(et == "acronisIncident")
      by Date = bin(timestamp, ${interval})
    | sort by Date asc
    `
    return Run(status, "Acronis (trend)", query)
}

// One row per alert id. Acronis re-sends an alert each time it changes, so the events column is the number of re-sends, not alerts.
// The domain is the host of the blocked URL and the process is the file name only (no path).
function GetAlerts(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisAlert") + `
    | extend alertId = tostring(['@acronisAlert'].id), p = tostring(['@acronisAlert'].details.processFullPath), u = tostring(['@acronisAlert'].details.url),
        sev = tostring(['@acronisAlert'].severity), cat = tostring(['@acronisAlert'].category), typ = tostring(['@acronisAlert'].type),
        dev = tostring(['@acronisAlert'].details.resourceName), plan = tostring(['@acronisAlert'].details.planName)
    | extend procName = iff(isempty(p), "", tostring(split(p, "\\")[array_length(split(p, "\\")) - 1]))
    | extend domain = iff(isempty(u), "", tostring(split(u, "/")[iff(u contains "://", 2, 0)]))
    | summarize events = count(), firstSeen = min(timestamp), lastSeen = max(timestamp),
        resolved = countif(isnotempty(tostring(['@acronisAlert'].deletedAt))),
        category = arg_max(timestamp, cat), alertType = arg_max(timestamp, typ), severity = arg_max(timestamp, sev),
        device = arg_max(timestamp, dev), planName = arg_max(timestamp, plan), domain = max(domain), process = max(procName)
      by alertId
    | sort by firstSeen asc
    | take 3000
    `
    return Run(status, "Acronis (alerts)", query)
}

// One row per incident short id and host, at its latest state.
function GetIncidents(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisIncident") + `
    | extend shortId = tostring(['@acronisIncident'].incident_short_id), host = tostring(['@acronisIncident'].host_name),
        st = tostring(['@acronisIncident'].state), mit = tostring(['@acronisIncident'].mitigation_state),
        sev = tostring(['@acronisIncident'].severity), created = tostring(['@acronisIncident'].created_at),
        xfer = tostring(['@acronisIncident'].transferred_to_incident_id)
    | summarize events = count(), lastUpdate = max(timestamp), lastState = arg_max(timestamp, st), lastMitigation = arg_max(timestamp, mit),
        severity = arg_max(timestamp, sev), created = max(created), transferredTo = max(xfer)
      by shortId, host
    | sort by shortId asc
    `
    return Run(status, "Acronis (incidents)", query)
}

// EDR incidents seen as alerts: the trigger file, detection time and mitigation per device. An incident merged across devices
// appears only here, with one row per device.
function GetEdrTriggers(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisAlert") + `
    | where tostring(['@acronisAlert'].type) == "EDRIncidentDetected"
    | extend incident = tostring(['@acronisAlert'].details.customerIncidentId), device = tostring(['@acronisAlert'].details.resourceName),
        trig = tostring(['@acronisAlert'].details.incidentTrigger), mit = tostring(['@acronisAlert'].details.mitigationState),
        det = tostring(['@acronisAlert'].details.detectionTime)
    | summarize lastSeen = max(timestamp), mitigation = max(mit), detection = min(det), trigger = max(trig) by incident, device
    | sort by incident asc
    | take 500
    `
    return Run(status, "Acronis (EDR triggers)", query)
}

// Activities by type and title: runs are distinct activity uuids (Acronis can send an activity more than once).
function GetActivities(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisActivity") + `
    | extend activityType = tostring(['@acronisActivity'].type), r = tostring(['@acronisActivity'].result.code), u = tostring(['@acronisActivity'].uuid)
    | summarize runs = dcount(u), ok = dcountif(u, r == "ok"), notOk = dcountif(u, r != "ok"), title = max(tostring(['@acronisActivity'].context.title))
      by activityType
    | sort by runs desc
    | take 100
    `
    return Run(status, "Acronis (activities)", query)
}

// Failed update activities per agent and unit. The agent id is the executing agent. Distinct failing agents are counted by the reader.
function GetUpdateFailures(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisActivity") + `
    | extend activityType = tostring(['@acronisActivity'].type), r = tostring(['@acronisActivity'].result.code)
    | where activityType in ("UpdateVapm", "UpdateAgent", "Download", "DownloadInstaller", "AutoUpdateStandby") and r != "ok"
    | extend agentId = tostring(['@acronisActivity'].executor.id), unit = tostring(['@acronisTenant'].name)
    | summarize failed = dcount(tostring(['@acronisActivity'].uuid)), lastFailure = max(timestamp), errorCode = max(tostring(['@acronisActivity'].result.error.code))
      by agentId, unit, activityType
    | sort by failed desc
    | take 1000
    `
    return Run(status, "Acronis (update failures)", query)
}

// Backup jobs per device and plan. The backup activity type is a GUID, so the jobs are found by their title.
function GetBackup(status, rangeFrom, rangeTo) {
    let query = EventPrefix(rangeFrom, rangeTo, "acronisActivity") + `
    | where tostring(['@acronisActivity'].context.title) == "Backing up"
    | extend device = tostring(['@acronisActivity'].resource.name), plan = tostring(['@acronisActivity'].policy.name),
        r = tostring(['@acronisActivity'].result.code), u = tostring(['@acronisActivity'].uuid),
        b = iff(isnull(todouble(['@acronisActivity'].progress.bytesProcessed)), 0.0, todouble(['@acronisActivity'].progress.bytesProcessed))
    | summarize runs = dcount(u), ok = dcountif(u, r == "ok"), failed = dcountif(u, r != "ok"),
        gbProcessed = round(sum(b) / 1073741824.0, 1), lastRun = max(timestamp),
        errors = make_set_if(tostring(['@acronisActivity'].result.error.code), isnotempty(tostring(['@acronisActivity'].result.error.code)), 5)
      by device, plan
    | sort by device asc
    | take 1000
    `
    return Run(status, "Acronis (backup)", query)
}

// ---- Inventory (acronisAgent, acronisTenant) ----------------------------------------------------------------

// update_time is RFC 1123 ("Fri, 12 Jun 2026 10:32:48 +0200"): todatetime cannot read it, so the date is rebuilt from the space-separated
// parts (day, month name, year), which also copes with an unpadded day. A value in any other shape gives no date and counts as "no data".
function DefsQuery(rangeTo) {
    return `
    acronisAgent
    | mv-expand comp = meta.atp.components
    | extend cname = tostring(comp.name), ut = tostring(comp.update_time)
    | extend parts = split(ut, " ")
    | extend dd = tostring(parts[1]), mon = tostring(parts[2]), yyyy = tostring(parts[3])
    | extend dd = iff(strlen(dd) == 1, strcat("0", dd), dd)
    | extend mm = iff(mon == "Jan", "01", iff(mon == "Feb", "02", iff(mon == "Mar", "03", iff(mon == "Apr", "04", iff(mon == "May", "05", iff(mon == "Jun", "06", iff(mon == "Jul", "07", iff(mon == "Aug", "08", iff(mon == "Sep", "09", iff(mon == "Oct", "10", iff(mon == "Nov", "11", "12")))))))))))
    | extend d = todatetime(strcat(yyyy, "-", mm, "-", dd, "T00:00:00Z"))
    | extend days = datetime_diff("day", datetime("${rangeTo}"), d)
    | summarize minDays = min(days), activeProtection = countif(cname == "ACTIVE_PROTECTION") by id
    `
}

function AgentQuery() {
    return `
    acronisAgent
    | project id, host = hostname, unit = tostring(tenant.name), online, enabled,
        installer = tostring(installer_version.current.release_id), latest = tostring(installer_version.latest.release_id),
        family = tostring(platform.family), osName = tostring(platform.name)
    `
}

function AgeBucket(days) {
    if (!IsNumber(days)) { return "no data" }
    if (days < 2) { return "< 2 days" }
    if (days <= 7) { return "2-7 days" }
    if (days < 30) { return "7-30 days" }
    if (days <= 90) { return "30-90 days" }
    return "> 90 days"
}

// typeof reports the Go type: a whole number is int64, a fraction float64, never "number". `days != null` is not a safe test.
function IsNumber(v) {
    let t = typeof(v)
    return t == "int64" || t == "float64"
}

function BucketOrder() {
    return ["< 2 days", "2-7 days", "7-30 days", "30-90 days", "> 90 days", "no data"]
}

// One pass over the agent records. Everything here is a count or a short list: the stale list is capped at 300 rows.
function GetAgents(status, rangeTo) {
    let asOf = toString(rangeTo)
    let box = {
        defs: {}, hosts: {}, hostOrder: [], units: {}, unitOrder: [], versions: {}, versionOrder: [], buckets: {},
        agents: 0, online: 0, disabled: 0, onLatest: 0, defsFresh: 0, defsStale: 0, defsStaleOnline: 0, defsStaleOffline: 0, defsNoData: 0,
        noApCount: 0, windows: 0, latestInstaller: "", stale: [], noAp: []
    }
    Run(status, "acronisAgent (protection components)", DefsQuery(rangeTo)).Each((row) => {
        box.defs[toString(row.id)] = {days: row.minDays, ap: row.activeProtection}
    })
    let agentRows = Run(status, "acronisAgent (agents)", AgentQuery())
    // The latest installer is the same on every record that carries it, but an agent may carry none: find it before comparing.
    agentRows.Each((row) => {
        if (toString(row.latest) != "" && box.latestInstaller == "") { box.latestInstaller = toString(row.latest) }
    })
    agentRows.Each((row) => {
        let id = toString(row.id)
        let host = toString(row.host)
        let unit = toString(row.unit)
        let online = (row.online == true)
        let installer = toString(row.installer)
        let d = box.defs[id]
        let days = null
        let ap = 0
        if (d) {
            days = d.days
            ap = d.ap
        }
        let hasDays = IsNumber(days)
        let stale = hasDays && days >= 30
        let bucket = AgeBucket(days)

        box.agents = box.agents + 1
        if (online) { box.online = box.online + 1 }
        if (row.enabled == false) { box.disabled = box.disabled + 1 }
        if (toString(row.family) == "WINDOWS") { box.windows = box.windows + 1 }
        let isLatest = (installer != "" && installer == box.latestInstaller)
        if (isLatest) { box.onLatest = box.onLatest + 1 }

        if (box.buckets[bucket]) { box.buckets[bucket] = box.buckets[bucket] + 1 } else { box.buckets[bucket] = 1 }
        if (!hasDays) { box.defsNoData = box.defsNoData + 1 }
        else if (stale) {
            box.defsStale = box.defsStale + 1
            if (online) { box.defsStaleOnline = box.defsStaleOnline + 1 } else { box.defsStaleOffline = box.defsStaleOffline + 1 }
        } else {
            box.defsFresh = box.defsFresh + 1
        }

        if (online && ap == 0) {
            box.noApCount = box.noApCount + 1
            let apRow = {host, unit, installer, asOf}
            if (hasDays) { apRow.days = days }
            box.noAp = append(box.noAp, apRow)
        }
        if (stale && len(box.stale) < 300) {
            box.stale = append(box.stale, {host, unit, online, days, installer, os: toString(row.osName), id, asOf})
        }

        let ukey = unit
        if (ukey == "") { ukey = "(none)" }
        if (!box.units[ukey]) {
            box.units[ukey] = {unit: ukey, agents: 0, online: 0, stale: 0, asOf}
            box.unitOrder = append(box.unitOrder, ukey)
        }
        box.units[ukey].agents = box.units[ukey].agents + 1
        if (online) { box.units[ukey].online = box.units[ukey].online + 1 }
        if (stale) { box.units[ukey].stale = box.units[ukey].stale + 1 }

        let vkey = installer
        if (vkey == "") { vkey = "(unknown)" }
        if (!box.versions[vkey]) {
            box.versions[vkey] = {version: vkey, agents: 0, isLatest: isLatest, asOf}
            box.versionOrder = append(box.versionOrder, vkey)
        }
        box.versions[vkey].agents = box.versions[vkey].agents + 1

        let hkey = toLower(host)
        if (hkey != "") {
            if (!box.hosts[hkey]) {
                box.hosts[hkey] = {host, records: 0, units: [], states: []}
                box.hostOrder = append(box.hostOrder, hkey)
            }
            box.hosts[hkey].records = box.hosts[hkey].records + 1
            box.hosts[hkey].units = append(box.hosts[hkey].units, unit)
            let state = "Offline"
            if (online) { state = "Online" }
            box.hosts[hkey].states = append(box.hosts[hkey].states, state)
        }
    })

    let dupRows = []
    let dupRecords = 0
    for _, k = range box.hostOrder {
        let h = box.hosts[k]
        if (h.records > 1) {
            dupRecords = dupRecords + h.records
            dupRows = append(dupRows, {host: h.host, records: h.records, units: h.units.Join(" / "), states: h.states.Join(" / "), asOf})
        }
    }
    let bucketRows = []
    for _, b = range BucketOrder() {
        let n = 0
        if (box.buckets[b]) { n = box.buckets[b] }
        bucketRows = append(bucketRows, {bucket: b, agents: n, asOf})
    }
    let unitRows = []
    for _, k = range box.unitOrder { unitRows = append(unitRows, box.units[k]) }
    let versionRows = []
    for _, k = range box.versionOrder { versionRows = append(versionRows, box.versions[k]) }

    let summary = [{
        agents: box.agents,
        online: box.online,
        offline: box.agents - box.online,
        disabled: box.disabled,
        uniqueHosts: len(box.hostOrder),
        duplicateHosts: len(dupRows),
        duplicateRecords: dupRecords,
        units: len(box.unitOrder),
        onLatest: box.onLatest,
        behind: box.agents - box.onLatest,
        latestInstaller: box.latestInstaller,
        defsFresh: box.defsFresh,
        defsStale: box.defsStale,
        defsStaleOnline: box.defsStaleOnline,
        defsStaleOffline: box.defsStaleOffline,
        defsNoData: box.defsNoData,
        noActiveProtection: box.noApCount,
        windows: box.windows,
        other: box.agents - box.windows,
        asOf
    }]

    return {
        summary: jsonTable(summary),
        defsAge: jsonTable(bucketRows),
        versions: jsonTable(versionRows),
        units: jsonTable(unitRows),
        stale: jsonTable(box.stale).Sort(0, "-days"),
        duplicates: jsonTable(dupRows),
        noAp: jsonTable(box.noAp)
    }
}

function GetTenants(status) {
    let query = `
    acronisTenant
    | project id, name, kind, parentId = parent_id, enabled, created = created_at
    | sort by kind asc, name asc
    `
    return Run(status, "acronisTenant", query)
}
