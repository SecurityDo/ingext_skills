// Description:
// Parser rule test (kql). Emits the signals of the parser rule
// O365_AzureAD_UserLoggedIn_local, a copy of the static rule
// O365_AzureAD_UserLoggedIn, by following that rule's event selector here
// instead of in eventwatch. Compare the two rules' behavior events.
//
// A channel rule (channel Office365ParserRules_local), called from Office365_ParserRules_local
// with Platform_Channel("Office365ParserRules_local", {obj}). It must not change obj:
// every rule of the channel and the calling parser share it.
//
// The line copies what eventwatch writes for a behavior rule hit:
//   {"signal":"behavior:<rule>","ts":<sec, 120 s slot>,"count":1,"key":<key>,
//    "valueMap":{<field path>: <string>, ...}}
// valueMap holds the rule's fields, its first correlations' fields and its key,
// all as strings; a missing field is "__undefined".

// Data input format: ({ obj, size }) or ( doc )
function main({obj, size}) {
    if (!matchLogin(obj)) {
        return "skip"
    }
    let valueMap = {}
    for _, field = range signalFields() {
        valueMap[field] = fieldString(obj, field)
    }
    let key = valueMap["@fields.UserId"]
    let ms = obj["@timestamp"]
    let sec = (ms - ms % 1000) / 1000
    Platform_Sink("CorrelationService", {obj: {
        signal: "behavior:O365_AzureAD_UserLoggedIn_local",
        ts: sec - sec % 120,
        count: 1,
        key: key,
        valueMap: valueMap
    }})
    return "match"
}

// matchLogin is the static rule's eventSelector:
//   must:    @sender office365, @fields.Operation UserLoggedIn, @fields.UserType 0,
//            @fields.ResultStatus Succeeded|Success, @fields._ip.countryCode exists
//   mustNot: @fields._ip.isp "Microsoft Corporation",
//            @fields.LogonError InvalidPasswordExpiredPassword|UserAccountNotFound|UserInformationNotProvided
function matchLogin(obj) {
    if (obj["@sender"] != "office365") {
        return false
    }
    let f = obj["@fields"]
    if (!f) {
        return false
    }
    if (f.Operation != "UserLoggedIn") {
        return false
    }
    if (toString(f.UserType) != "0") {
        return false
    }
    if (f.ResultStatus != "Succeeded" && f.ResultStatus != "Success") {
        return false
    }
    let ip = f["_ip"]
    if (!ip || !ip.countryCode) {
        return false
    }
    if (ip.isp == "Microsoft Corporation") {
        return false
    }
    let le = f.LogonError
    if (le == "InvalidPasswordExpiredPassword" || le == "UserAccountNotFound" || le == "UserInformationNotProvided") {
        return false
    }
    return true
}

// signalFields: behaviorRule.fields, then the first correlations' fields and
// the key (all already in fields for this rule).
function signalFields() {
    return [
        "@fields.ActorIpAddress",
        "@fields.ExtendedPropertiesFields.RequestType",
        "@fields.DevicePropertiesFields.BrowserType",
        "@fields._ip.city",
        "@fields.ClientIP",
        "@fields._ip.country",
        "@fields._ip.isp",
        "@fields.Operation",
        "@fields.DevicePropertiesFields.OS",
        "@fields.UserId",
        "@fields.Workload"
    ]
}

// fieldString reads a dotted path the way eventwatch does for a signal: a
// missing value is "__undefined", an array is comma-joined, anything else is
// its string form.
function fieldString(obj, path) {
    let v = obj
    for _, part = range split(path, ".") {
        if (!v) {
            return "__undefined"
        }
        v = v[part]
    }
    if (isUndef(v) || isNull(v)) {
        return "__undefined"
    }
    if (Array.isArray(v)) {
        let parts = []
        for _, e = range v {
            parts = append(parts, toString(e))
        }
        return parts.join(",")
    }
    return toString(v)
}
