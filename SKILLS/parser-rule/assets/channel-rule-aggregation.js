// Description:
// Parser rule test (kql, aggregation). Emits the aggregation lines of the
// parser rule O365_LoginFailed_Agg_local by following the selector of the static
// rule O365_LoginFailed_Agg_ST (that of O365_AzureAD_UserLoginFailed_Brute_Force).
// Compare the two rules' behavior events.
//
// A channel rule (channel Office365ParserRules_local), called from Office365_ParserRules_local
// with Platform_Channel("Office365ParserRules_local", {obj}). It must not change obj,
// not even "@behaviors": eventwatch never tags an event for an aggregation rule.
//
// The line copies what eventwatch writes for a count aggregation correlation:
//   {"signal":"behavior:<rule>:<correlation>","ts":<sec, 60 s slot>,
//    "valueMap":{<key value>: <count>}}
// eventwatch writes one line per slot holding every key; mantis adds each line
// into the slot, so one line per event with count 1 adds up the same.

// Data input format: ({ obj, size }) or ( doc )
function main({obj, size}) {
    if (!matchLoginFailed(obj)) {
        return "skip"
    }
    let user = obj["@fields"].UserId
    if (isUndef(user) || isNull(user) || toString(user) == "") {
        return "skip"
    }
    let ms = obj["@timestamp"]
    let sec = (ms - ms % 1000) / 1000
    let valueMap = {}
    valueMap[toString(user)] = 1
    Platform_Sink("CorrelationService", {obj: {
        signal: "behavior:O365_LoginFailed_Agg_local:Failed",
        ts: sec - sec % 60,
        valueMap: valueMap
    }})
    return "match"
}

// matchLoginFailed is the static rule's eventSelector:
//   must:    @sender office365, @fields.Workload AzureActiveDirectory,
//            @fields.Operation UserLoginFailed
//   mustNot: @fields.LogonError UserAccountNotFound
function matchLoginFailed(obj) {
    if (obj["@sender"] != "office365") {
        return false
    }
    let f = obj["@fields"]
    if (!f) {
        return false
    }
    if (f.Workload != "AzureActiveDirectory" || f.Operation != "UserLoginFailed") {
        return false
    }
    if (f.LogonError == "UserAccountNotFound") {
        return false
    }
    return true
}
