// CloudTrail activity dashboard: the counts the compliance assessment uses (events, console
// logins and failures, IAM changes, root-identity events, errors), a trend per interval, and
// the IAM, root and error breakdowns. Counts only: no user names, addresses or ARNs.
// The window is half-open (from <= timestamp < to), so back-to-back daily runs never count the
// boundary second twice. Every section is additive, so a daily run can be archived and summed over a month.
// Two scans: the trend (counts per interval, whose sum is the period total) and one facet query that
// returns every breakdown at once as full, additive distributions (top-N is taken by the reader).
// interval is a KQL timespan: "1d" for a month view, "1h" for a single-day view.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let trend = GetTrend(rangeFrom, rangeTo, interval)
    let facets = GetFacets(rangeFrom, rangeTo)
    return {
        trend,
        facets
    }
}

function validateTimeRange(from, to) {
    // start of the range must come before the end
    if (from.After(to)) {
        throw new Error("rangeFrom must be less than rangeTo", "RangeError")
    }
    // cap the window so a report can't scan an unbounded amount of data
    if (to.After(from.Add("40d"))) {
        throw new Error("total duration must not exceed 40 days", "RangeError")
    }
    return true
}

// Counts per interval: events, console logins, failed logins, IAM changes, root events, errors,
// access-denied errors, console logins without MFA, and changes to CloudTrail itself.
// Summing the rows gives the period totals.
function GetTrend(rangeFrom, rangeTo, interval) {
    let query = `
    CloudTrail
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | summarize
        events = count(),
        consoleLogins = countif(eventName == "ConsoleLogin"),
        failedLogins = countif(eventName == "ConsoleLogin" and tostring(responseElements.ConsoleLogin) == "Failure"),
        iamChanges = countif(eventSource == "iam.amazonaws.com" and not(eventName startswith "Get" or eventName startswith "List" or eventName startswith "Describe")),
        rootEvents = countif(['userIdentity.type'] == "Root"),
        errors = countif(isnotempty(errorCode)),
        accessDenied = countif(errorCode in ("AccessDenied", "Client.UnauthorizedOperation", "UnauthorizedOperation", "AccessDeniedException")),
        loginsNoMfa = countif(eventName == "ConsoleLogin" and tostring(responseElements.ConsoleLogin) == "Success" and tostring(['additionalEventData.MFAUsed']) != "Yes"),
        trailChanges = countif(eventSource == "cloudtrail.amazonaws.com" and eventName in ("StopLogging", "DeleteTrail", "UpdateTrail", "PutEventSelectors", "PutInsightSelectors"))
        by Date = bin(timestamp, ${interval})
    | sort by Date asc
    `
    return kql(query)
}

// Every breakdown in one pass. The result holds one table per facet, each a value column plus count_:
//   source, region, identityType              events by AWS service, region and identity type
//   errSource, errRegion, errCode             errors by service, region and error code
//   iamEvent                                  IAM changes by event name (reads excluded)
//   rootEvent                                 root-identity events by event name
//   loginIdentity                             console logins by identity type
// The first three cover every event; a missing value is labelled "(not recorded)" (for identityType
// these are AWS service-generated events, which carry no user identity). The other facets describe a
// subset, and every event outside it is labelled "(none)", so "(none)" is the complement of the
// subset (for errCode, every event without an error). Tables are complete for summing daily files,
// except that the engine returns at most 100 values per facet: a column with more distinct values
// (eventSource had 128 in one day) loses its rarest ones. The difference between a facet's total and
// the trend's events total is that omitted tail (about 0.001% here); show it as "(other)" if wanted.
function GetFacets(rangeFrom, rangeTo) {
    let query = `
    CloudTrail
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | extend identityType = iff(isempty(tostring(['userIdentity.type'])), "(not recorded)", tostring(['userIdentity.type']))
    | extend source = iff(isempty(eventSource), "(not recorded)", eventSource), region = iff(isempty(awsRegion), "(not recorded)", awsRegion)
    | extend isError = isnotempty(errorCode)
    | extend isIam = (eventSource == "iam.amazonaws.com" and not(eventName startswith "Get" or eventName startswith "List" or eventName startswith "Describe"))
    | extend errSource = iff(isError, source, "(none)"), errRegion = iff(isError, region, "(none)"), errCode = iff(isError, errorCode, "(none)"), iamEvent = iff(isIam, eventName, "(none)"), rootEvent = iff(identityType == "Root", eventName, "(none)"), loginIdentity = iff(eventName == "ConsoleLogin", identityType, "(none)")
    | facet by source, region, identityType, errSource, errRegion, errCode, iamEvent, rootEvent, loginIdentity with (take 0)
    `
    return kql(query)
}
