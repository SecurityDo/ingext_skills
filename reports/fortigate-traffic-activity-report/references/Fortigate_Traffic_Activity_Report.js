
// FortiGate traffic activity report: firewall forward-traffic sessions from NetworkFortigateTraffic as daily counts
// and byte volumes, with additive breakdowns by application and category, service, destination country, firewall
// policy, reporting device and internal source host. It complements Fortigate_Security_Activity_Report, which reads
// the event and UTM logs (NetworkFortigateEvent) and deliberately does not scan traffic.
//
// GenAI egress evidence: the genaiDevice, genaiApp, genaiPolicy, genaiSource and genaiDestination dimensions are also
// the evidence for the separate GenAI Egress Report, which reads them from this archive instead of scanning traffic
// again. A session is generative AI when Application Control labels it with the category GenAI, or when its
// application name matches a known GenAI service (the name list in the isGenAI test below, extended as new services
// appear). Traffic logs carry no host name or URL (dstname and _fields.hostname are empty), so a GenAI destination is
// identified by application, destination IP and destination country, never by domain. A tenant whose policies do not
// run Application Control has no application names in the traffic logs, so it shows no GenAI traffic here; that is a
// coverage gap, not a clean result, and "sources" cannot tell the two apart. The reader of the evidence must state it.
//
// Personal data: traffic_talkers and the genaiSource and genaiDestination dimensions carry internal host names and IP
// addresses, so the archive is personal data; a report shared outside the tenant must not use them.
// The window is half-open (from <= timestamp < to), so back-to-back daily runs never count a boundary second twice.
// interval is a KQL timespan: "1d" for archived daily runs, "1h" for a single-day view.
//
// Two scans of the traffic table, both bounded by the engine's 8124-row result limit:
//  1. traffic_dims: one scan that emits one row per dimension value (the dim column) instead of one row per
//     combination, so the result is the SUM of the dimension sizes, not their product (a few hundred rows). Each row
//     is (dim, val, outcome) with events, bytesOut and bytesIn. val holds the dimension value; a dimension with a pair
//     or triple of fields joins them with " | " (the reader splits them again):
//       device            device | day             every event, so the sum over rows is the run total
//       genaiDevice       device | day             GenAI events only
//       app               application | category
//       service           service
//       country           destination country
//       policy            policy id
//       genaiApp          application | category
//       genaiPolicy       policy id | application
//       genaiSource       source address | host | application
//       genaiDestination  destination address | country | application
//     Every dimension covers every event (or every GenAI event), so each dimension sums to the same total.
//     Application and service names of the form tcp/<port> or udp/<port> (a service the firewall could not name) are
//     collapsed to "(unnamed tcp port)" or "(unnamed udp port)": they number in the tens of thousands on a busy
//     firewall and would exceed the row limit.
//  2. traffic_talkers: the top 100 internal sources by bytes sent (a firewall has tens of thousands of sources, far
//     over the row limit, so this is the one top-N table). Together they carry nearly all the bytes sent.
//
// Volumes: sentbyte and rcvdbyte are cumulative per session, so a plain sum double-counts long sessions. Every volume
// here is the per-record delta (_fields.sentdelta / _fields.rcvddelta) with the cumulative value as the fallback when a
// record has no delta (a session-close record of a session with no earlier updates carries the true total).
// logid 0000000020 (the periodic session update) is kept, because it carries the deltas that make long sessions
// count correctly. bytesOut is client to server (sent), bytesIn is server to client (received).
// "events" is a log record, not a session: a long session writes several records. outcome is "blocked" for action
// deny and "allowed" for every other action (accept, close, timeout, client-rst, server-rst, ip-conn, start).
//
// What adds up across days: events and byte volumes in every table. What does not: distinct hosts or IPs (they
// cannot be summed across days). traffic_talkers is the top 100 of a day, so a range total is a lower bound for a
// host outside a day's top 100.

// Missing data is expected and handled: a scan that fails (no NetworkFortigateTraffic table on the tenant, or any
// query error) returns an empty table and is recorded in "sources" with status "not available" and the error text;
// an "ok" scan with no rows is a day without traffic. A tenant without FortiGate data is never an error.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let traffic_dims = GetDims(status, rangeFrom, rangeTo, interval)
    let traffic_talkers = GetTalkers(status, rangeFrom, rangeTo)
    let sources = jsonTable(status.rows)
    return {
        traffic_dims,
        traffic_talkers,
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

// Dimensions: events and byte volumes per dimension value and outcome (see the header). One scan; the dynamic list
// copies every record once per dimension and case() picks the value that dimension groups by, so a dimension that does
// not apply to a record (a GenAI dimension for non-GenAI traffic) yields an empty value and is dropped. The final
// top 8000 only guards the 8124-row limit: it drops the smallest rows, and the reader treats a result at that size as
// truncated.
function GetDims(status, rangeFrom, rangeTo, interval) {
    let query = `
    NetworkFortigateTraffic
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend sent = coalesce(tolong(_fields.sentdelta), sentbyte), rcvd = coalesce(tolong(_fields.rcvddelta), rcvdbyte)
    | extend outcome = iff(action == "deny", "blocked", "allowed")
    | extend isGenAI = appcat =~ "GenAI" or tolower(app) matches regex "openai|chatgpt|claude|anthropic|gemini|bard|copilot|perplexity|deepseek|mistral|midjourney|huggingface|character.ai|poe.com|grok|cohere|stability"
    | extend appName = iff(isempty(app), "(not recorded)", app), appCategory = iff(isempty(appcat), "(not recorded)", appcat), serviceName = iff(isempty(service), "(not recorded)", service)
    | extend appName = iff(appName matches regex "^(tcp|udp)/[0-9]+$", strcat("(unnamed ", substring(appName, 0, 3), " port)"), appName)
    | extend serviceName = iff(serviceName matches regex "^(tcp|udp)/[0-9]+$", strcat("(unnamed ", substring(serviceName, 0, 3), " port)"), serviceName)
    | extend device = iff(isempty(devname), "(not recorded)", devname), country = iff(isempty(dstcountry), "(not recorded)", dstcountry), policy = iff(isnull(policyid), "(not recorded)", tostring(policyid))
    | extend host = strcat(iff(isempty(srcip), "(not recorded)", srcip), " | ", iff(isempty(srcname), "(not recorded)", srcname)), destination = strcat(iff(isempty(dstip), "(not recorded)", dstip), " | ", country), day = tostring(bin(TimeGenerated, ${interval}))
    | extend dim = dynamic(["device", "genaiDevice", "app", "service", "country", "policy", "genaiApp", "genaiPolicy", "genaiSource", "genaiDestination"])
    | mv-expand dim
    | extend dim = tostring(dim)
    | extend val = case(dim == "device", strcat(device, " | ", day), dim == "genaiDevice" and isGenAI, strcat(device, " | ", day), dim == "app", strcat(appName, " | ", appCategory), dim == "service", serviceName, dim == "country", country, dim == "policy", policy, dim == "genaiApp" and isGenAI, strcat(appName, " | ", appCategory), dim == "genaiPolicy" and isGenAI, strcat(policy, " | ", appName), dim == "genaiSource" and isGenAI, strcat(host, " | ", appName), dim == "genaiDestination" and isGenAI, strcat(destination, " | ", appName), "")
    | where val != ""
    | summarize events = count(), bytesOut = sum(sent), bytesIn = sum(rcvd) by dim, val, outcome
    | top 8000 by bytesOut desc
    `
    return Run(status, "NetworkFortigateTraffic dimensions", query)
}

// Internal talkers (personal data): events, blocked events and volumes per source host, the top 100 by bytes sent.
function GetTalkers(status, rangeFrom, rangeTo) {
    let query = `
    NetworkFortigateTraffic
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend sent = coalesce(tolong(_fields.sentdelta), sentbyte), rcvd = coalesce(tolong(_fields.rcvddelta), rcvdbyte)
    | extend host = iff(isempty(srcname), "(not recorded)", srcname), source = iff(isempty(srcip), "(not recorded)", srcip)
    | summarize events = count(), blocked = countif(action == "deny"), bytesOut = sum(sent), bytesIn = sum(rcvd) by source, host
    | top 100 by bytesOut desc
    `
    return Run(status, "NetworkFortigateTraffic talkers", query)
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
