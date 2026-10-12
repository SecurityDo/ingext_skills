// Windows Host Health dashboard: host health and SentinelOne agent health from
// the winhost_* gauges that the WinHost_Metrics channel rule writes from NXLog
// im_winperfcount events (needs platform 9.0.7+).
//
// Status tables are read at `to`; the charts cover from..to at `interval`.
// The chart window is snapped to the interval grid (alignedRange). The chart
// slots count back from `to`, while VictoriaMetrics rounds a range query of 50+
// points to multiples of the step; unless both ends sit on that grid no point
// matches a slot and every chart reads zero.
// A host is listed for 24h after its last sample, so a host that stops
// reporting shows as NOT REPORTING instead of vanishing (its gauges expire
// after 10 minutes).
//
// PromQL here avoids regex label matchers (=~), which the MCP query path does
// not return; exact and negative matchers only.

// seconds without a sample before a host counts as not reporting. A healthy
// host already reads ~180s: 60s sample cadence + 60s metric push + `to` at @m.
function staleSeconds() {
    return 600
}

// required SentinelOne services, matching WinHost_Metrics requiredProcesses()
function requiredServiceCount() {
    return 5
}

// instant query -> {key: _value}, key = the given label (or labels joined by " ")
function valueMap(query, to, labels) {
    let m = {}
    let t = Platform_Metric_Query(query, to)
    t.Each((row) => {
        let parts = []
        for _, l = range labels {
            parts = append(parts, toString(row[l]))
        }
        m[parts.Join(" ")] = row._value
    })
    return m
}

// legend keys of a range result are ["<label>"]; show the bare value instead
function legendMap(keys) {
    let m = {}
    for _, k = range keys {
        m[`["${k}"]`] = k
    }
    return m
}

// a missing value stays undefined, so jsonTable leaves the cell empty
function round1(v) {
    if (isUndef(v)) {
        return v
    }
    return Math.round(v * 10) / 10
}

function hostStatus(to) {
    let window = "24h"
    let lastSeen = valueMap(`time() - max by (host) (last_over_time(winhost_last_seen_seconds{source="winperfcount_in"}[${window}]))`, to, ["host"])
    let cpu = valueMap(`max by (host) (winhost_cpu_pct)`, to, ["host"])
    let mem = valueMap(`max by (host) (winhost_mem_committed_pct)`, to, ["host"])
    let memAvail = valueMap(`max by (host) (winhost_mem_avail_mb)`, to, ["host"])
    let diskMin = valueMap(`min by (host) (winhost_disk_free_pct)`, to, ["host"])
    let s1Up = valueMap(`sum by (host) (winhost_proc_up)`, to, ["host"])

    let rows = []
    let hosts = []
    for host, age = range lastSeen {
        hosts = append(hosts, host)
        let issues = []
        if (age > staleSeconds()) {
            issues = append(issues, "NOT REPORTING")
        }
        let up = s1Up[host]
        if (!isUndef(up) && up < requiredServiceCount()) {
            issues = append(issues, "S1 SERVICE DOWN")
        }
        let disk = diskMin[host]
        if (!isUndef(disk) && disk < 10) {
            issues = append(issues, "DISK LOW")
        }
        let c = cpu[host]
        if (!isUndef(c) && c > 90) {
            issues = append(issues, "CPU HIGH")
        }
        let status = "OK"
        if (len(issues) > 0) {
            status = issues.Join(", ")
        }
        let s1 = "no data"
        if (!isUndef(up)) {
            s1 = sprintf("%.0f/%d", up, requiredServiceCount())
        }
        rows = append(rows, {
            host,
            status,
            lastSeenSec: Math.round(age),
            cpuPct: round1(cpu[host]),
            memCommittedPct: round1(mem[host]),
            memAvailMB: memAvail[host],
            minDiskFreePct: round1(disk),
            s1ServicesUp: s1
        })
    }
    return {table: jsonTable(rows).Sort(100, "host"), hosts}
}

function s1Status(to) {
    let window = "15m"
    let up = valueMap(`max by (host, process) (last_over_time(winhost_proc_up[${window}]))`, to, ["host", "process"])
    let cpu = valueMap(`max by (host, process) (last_over_time(winhost_proc_cpu_pct[${window}]))`, to, ["host", "process"])
    let rows = []
    for key, v = range up {
        let parts = split(key, " ")
        let state = "RUNNING"
        if (v < 1) {
            state = "NOT RUNNING"
        }
        rows = append(rows, {host: parts[0], process: parts[1], state, cpuPct: round1(cpu[key])})
    }
    return jsonTable(rows).Sort(100, "host")
}

function diskStatus(to) {
    let pct = valueMap(`max by (host, drive) (winhost_disk_free_pct)`, to, ["host", "drive"])
    let mb = valueMap(`max by (host, drive) (winhost_disk_free_mb)`, to, ["host", "drive"])
    let rows = []
    for key, v = range pct {
        let parts = split(key, " ")
        rows = append(rows, {host: parts[0], drive: parts[1], freePct: round1(v), freeMB: mb[key]})
    }
    // legend for the chart: every drive seen in 24h, not just the live ones,
    // or an expired drive's line loses its name
    let series = []
    let seen = valueMap(`max by (host, drive) (last_over_time(winhost_disk_free_pct[24h]))`, to, ["host", "drive"])
    for key, _ = range seen {
        series = append(series, key)
    }
    return {table: jsonTable(rows).Sort(100, "host"), series}
}

// "30s", "5m", "1h", "1d" -> seconds
function intervalSeconds(interval) {
    let n = parseInt(trim(interval, "smhd"))
    if (endsWith(interval, "d")) {
        return n * 86400
    }
    if (endsWith(interval, "h")) {
        return n * 3600
    }
    if (endsWith(interval, "m")) {
        return n * 60
    }
    return n
}

// resolve an FPL time ("@m", "-6h@m", ...) to epoch seconds, rounded down to step
function alignedSeconds(t, step) {
    // a lambda cannot assign an outer variable, so write through a map
    let box = {sec: 0}
    Platform_Metric_Query(`time()`, t).Each((row) => {
        box.sec = row._value
    })
    return Math.floor(box.sec / step) * step
}

// from/to for the charts, both on multiples of the interval, as RFC3339
function alignedRange(from, to, interval) {
    let step = intervalSeconds(interval)
    let layout = "2006-01-02T15:04:05Z07:00"
    // new Time takes an integer; Math.floor returns a float
    let f = new Time(parseInt(sprintf("%.0f", alignedSeconds(from, step) * 1000)))
    let t = new Time(parseInt(sprintf("%.0f", alignedSeconds(to, step) * 1000)))
    return {chartFrom: f.Format(layout), chartTo: t.Format(layout)}
}

function hostChart(query, from, to, interval, hosts) {
    let r = Platform_Metric_QueryRange(query, from, to, interval)
    r.ReplaceKey(legendMap(hosts))
    return r
}

function main({from="-6h@m", to="@m", interval="5m"}) {
    let {table: hosts, hosts: hostNames} = hostStatus(to)
    let services = s1Status(to)
    let {table: disks, series: diskSeries} = diskStatus(to)

    let hostsReporting = Platform_Metric_Query(`count(time() - max by (host) (last_over_time(winhost_last_seen_seconds{source="winperfcount_in"}[24h])) < ${toString(staleSeconds())}) or vector(0)`, to)
    let servicesDown = Platform_Metric_Query(`count(max by (host, process) (last_over_time(winhost_proc_up[15m])) < 1) or vector(0)`, to)

    let {chartFrom, chartTo} = alignedRange(from, to, interval)
    let cpu = hostChart(`max by (host) (winhost_cpu_pct)`, chartFrom, chartTo, interval, hostNames)
    let mem = hostChart(`max by (host) (winhost_mem_committed_pct)`, chartFrom, chartTo, interval, hostNames)
    let diskBusy = hostChart(`max by (host) (winhost_disk_busy_pct)`, chartFrom, chartTo, interval, hostNames)
    let net = hostChart(`max by (host) (winhost_net_bytes_ps)`, chartFrom, chartTo, interval, hostNames)
    let s1Cpu = hostChart(`sum by (host) (winhost_proc_cpu_pct{process!="nxlog"})`, chartFrom, chartTo, interval, hostNames)
    let s1Up = hostChart(`sum by (host) (winhost_proc_up)`, chartFrom, chartTo, interval, hostNames)

    let diskFree = Platform_Metric_QueryRange(`max by (series) (label_join(winhost_disk_free_pct, "series", " ", "host", "drive"))`, chartFrom, chartTo, interval)
    diskFree.ReplaceKey(legendMap(diskSeries))

    return {hosts, services, disks, hostsReporting, servicesDown, cpu, mem, diskBusy, net, s1Cpu, s1Up, diskFree}
}
