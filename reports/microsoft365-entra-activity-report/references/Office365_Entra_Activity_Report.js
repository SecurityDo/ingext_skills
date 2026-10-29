// Microsoft 365 and Entra activity report: Office365 audit events, Entra sign-in logs and Entra directory-audit
// logs, as daily counts plus additive breakdowns. The actor facets (user, failedUser, failedIp, adminActor, actor,
// failedActor) carry user names and source IP addresses, so the archive is personal data; the report shared for
// compliance evidence must not use them.
// The window is half-open (from <= timestamp < to), so back-to-back daily runs never count a boundary second
// twice. Every section is additive, so daily runs can be archived and summed over a week, month or quarter.
// Per table two scans: a trend (counts per interval, whose sum is the period total) and one facet query that
// returns every breakdown at once as full distributions (the reader takes the top N after merging days).
// interval is a KQL timespan: "1d" for archived daily runs, "1h" for a single-day view.
// Not counted on purpose: distinct users or IPs (they cannot be summed across days). Actor facets are top values
// per day (the engine keeps 100), so a range total is a lower bound for a user outside a day's top 100.

// Missing data is expected and handled: every scan runs through Run(), which catches a table that does not exist
// on the tenant (or any query failure) and returns an empty table instead of failing the report. The "sources"
// table lists each scan with status "ok" or "not available" plus the error text, so a reader can tell a table that
// is absent from a day with no events (an "ok" scan with no rows). A table the tenant lacks is never an error.

function main({from="-1d@d", to="@d", interval="1d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let o365_trend = GetO365Trend(status, rangeFrom, rangeTo, interval)
    let o365_facets = GetO365Facets(status, rangeFrom, rangeTo)
    let signin_trend = GetSigninTrend(status, rangeFrom, rangeTo, interval)
    let signin_facets = GetSigninFacets(status, rangeFrom, rangeTo)
    let audit_trend = GetAuditTrend(status, rangeFrom, rangeTo, interval)
    let audit_facets = GetAuditFacets(status, rangeFrom, rangeTo)
    let sp_trend = GetSpTrend(status, rangeFrom, rangeTo, interval)
    let sp_facets = GetSpFacets(status, rangeFrom, rangeTo)
    let ni_trend = GetNiTrend(status, rangeFrom, rangeTo, interval)
    let ni_facets = GetNiFacets(status, rangeFrom, rangeTo)
    let sources = jsonTable(status.rows)
    return {
        o365_trend,
        o365_facets,
        signin_trend,
        signin_facets,
        audit_trend,
        audit_facets,
        sp_trend,
        sp_facets,
        ni_trend,
        ni_facets,
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

// ---- Office365 audit events ------------------------------------------------------------------------------
// events; failedOps (ResultStatus Failed/Failure/False); adminOps (UserType Admin or DcAdmin);
// loginsOk / loginsFailed (Azure AD UserLoggedIn / UserLoginFailed); mailItemsAccessed; mailSent; hardDeletes;
// inboxRuleChanges; mailboxPermissionChanges; sharingEvents (links, invitations, group adds);
// externalAccess (events flagged ExternalAccess); adminConfigChanges (Exchange New-/Set-/Remove-/Enable-/Disable-);
// securityAlerts (Security and Compliance alerts); dlpEvents; copilotEvents.
function GetO365Trend(status, rangeFrom, rangeTo, interval) {
    let query = `
    Office365
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | summarize
        events = count(),
        failedOps = countif(ResultStatus in ("Failed", "Failure", "False")),
        adminOps = countif(UserType in (2, 3)),
        loginsOk = countif(Workload == "AzureActiveDirectory" and Operation == "UserLoggedIn"),
        loginsFailed = countif(Workload == "AzureActiveDirectory" and Operation == "UserLoginFailed"),
        mailItemsAccessed = countif(Operation == "MailItemsAccessed"),
        mailSent = countif(Workload == "Exchange" and Operation in ("Send", "SendAs", "SendOnBehalf")),
        hardDeletes = countif(Operation == "HardDelete"),
        inboxRuleChanges = countif(Operation in ("UpdateInboxRules", "New-InboxRule", "Set-InboxRule", "Remove-InboxRule", "Enable-InboxRule", "Disable-InboxRule")),
        mailboxPermissionChanges = countif(Operation in ("ModifyFolderPermissions", "AddFolderPermissions", "RemoveFolderPermissions", "Add-MailboxPermission", "Remove-MailboxPermission", "Add-RecipientPermission", "Add-MailboxFolderPermission", "Set-MailboxFolderPermission")),
        sharingEvents = countif(Operation in ("SharingSet", "SharingInvitationCreated", "AddedToSharingLink", "AddedToSecureLink", "AnonymousLinkCreated", "CompanyLinkCreated", "SecureLinkCreated", "AddedToGroup")),
        externalAccess = countif(ExternalAccess == true),
        adminConfigChanges = countif(Workload == "Exchange" and (Operation startswith "Set-" or Operation startswith "New-" or Operation startswith "Remove-" or Operation startswith "Enable-" or Operation startswith "Disable-")),
        securityAlerts = countif(Workload == "SecurityComplianceCenter" and Operation == "AlertTriggered"),
        dlpEvents = countif(Operation has "Dlp"),
        copilotEvents = countif(Workload == "Copilot")
        by Date = bin(timestamp, ${interval})
    | sort by Date asc
    `
    return Run(status, "Office365", query)
}

// One facet query, one table per facet (value column plus count_). Every facet covers every event;
// a missing value is "(not recorded)". The subset facets (adminOp, sensitiveOp, failedOp) label every event
// outside the subset "(none)", so "(none)" is the complement of the subset.
//   workload, operation, userType, country, deviceOS, browser, resultStatus
//   adminOp      operation of admin (UserType Admin or DcAdmin) events
//   sensitiveOp  operation of mail-rule, permission, delete, sharing and Exchange configuration events
//   failedOp     operation of failed events
//   user, failedUser, failedIp, adminActor   UserId and ClientIP of all, failed (incl. UserLoginFailed) and admin events
// The engine returns at most 100 values per facet; rarer values are lost (operation can exceed 100).
function GetO365Facets(status, rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp >= datetime("${rangeFrom}") and timestamp < datetime("${rangeTo}")
    | extend workload = iff(isempty(Workload), "(not recorded)", Workload), operation = iff(isempty(Operation), "(not recorded)", Operation)
    | extend userType = case(tostring(UserType) == "0", "Regular", tostring(UserType) == "2", "Admin", tostring(UserType) == "3", "DcAdmin", tostring(UserType) == "4", "System", tostring(UserType) == "5", "Application", tostring(UserType) == "6", "ServicePrincipal", tostring(UserType) == "7", "CustomPolicy", tostring(UserType) == "8", "SystemPolicy", "(not recorded)")
    | extend country = iff(isempty(tostring(['_ip.countryCode'])), "(not recorded)", tostring(['_ip.countryCode']))
    | extend deviceOS = iff(isempty(tostring(['DevicePropertiesFields.OS'])), "(not recorded)", tostring(['DevicePropertiesFields.OS']))
    | extend browser = iff(isempty(tostring(['DevicePropertiesFields.BrowserType'])), "(not recorded)", tostring(['DevicePropertiesFields.BrowserType']))
    | extend resultStatus = iff(isempty(ResultStatus), "(not recorded)", ResultStatus)
    | extend isAdmin = UserType in (2, 3)
    | extend isSensitive = Operation in ("UpdateInboxRules", "New-InboxRule", "Set-InboxRule", "Remove-InboxRule", "ModifyFolderPermissions", "AddFolderPermissions", "Add-MailboxPermission", "Add-RecipientPermission", "HardDelete", "SharingSet", "SharingInvitationCreated", "AnonymousLinkCreated", "AddedToSharingLink", "Set-Mailbox", "Set-ConditionalAccessPolicy", "Set-TransportConfig") or (Workload == "Exchange" and (Operation startswith "New-" or Operation startswith "Remove-" or Operation startswith "Enable-" or Operation startswith "Disable-"))
    | extend isFailed = ResultStatus in ("Failed", "Failure", "False")
    | extend adminOp = iff(isAdmin, operation, "(none)"), sensitiveOp = iff(isSensitive, operation, "(none)"), failedOp = iff(isFailed, operation, "(none)")
    | extend uid = iff(isempty(UserId), "(not recorded)", tolower(UserId)), cip = iff(isempty(ClientIP), "(not recorded)", ClientIP)
    | extend isFail2 = isFailed or Operation == "UserLoginFailed"
    | extend user = uid, failedUser = iff(isFail2, uid, "(none)"), failedIp = iff(isFail2, cip, "(none)"), adminActor = iff(isAdmin, uid, "(none)")
    | facet by workload, operation, userType, country, deviceOS, browser, resultStatus, adminOp, sensitiveOp, failedOp, user, failedUser, failedIp, adminActor with (take 0)
    `
    return Run(status, "Office365", query)
}

// ---- Entra sign-in logs ----------------------------------------------------------------------------------
// events; failed (ResultType other than 0); interactive; mfaRequired (authentication requirement MFA);
// singleFactorOk (successful sign-ins that needed one factor only); caFailures (Conditional Access status failure);
// risky (IsRisky or sign-in risk low/medium/high); guests; legacyAuth (IMAP, POP, SMTP, MAPI, ActiveSync and other
// legacy clients).
function GetSigninTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    AzureSigninLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | summarize
        events = count(),
        failed = countif(ResultType != "0"),
        interactive = countif(IsInteractive == true),
        mfaRequired = countif(AuthenticationRequirement == "multiFactorAuthentication"),
        singleFactorOk = countif(ResultType == "0" and AuthenticationRequirement == "singleFactorAuthentication"),
        caFailures = countif(ConditionalAccessStatus == "failure"),
        risky = countif(IsRisky == true or RiskLevelDuringSignIn in ("low", "medium", "high")),
        guests = countif(UserType == "guest"),
        legacyAuth = countif(ClientAppUsed in ("IMAP4", "IMAP", "POP3", "POP", "MAPI Over HTTP", "MAPI", "Exchange ActiveSync", "Authenticated SMTP", "SMTP", "Exchange Online PowerShell", "Exchange Web Services", "Other clients", "Offline Address Book", "Autodiscover", "Exchange ActiveSync"))
        by Date = bin(TimeGenerated, ${interval})
    | sort by Date asc
    `
    return Run(status, "AzureSigninLogs", query)
}

// Facets (every one covers every sign-in; a missing value is "(not recorded)"; failedCode labels successes "(none)"):
//   app, clientApp, authRequirement, caStatus, country, deviceOS, browser, userType, riskLevel, protocol
//   failedCode   ResultType of failed sign-ins, "(none)" for successes
function GetSigninFacets(status, rangeFrom, rangeTo) {
    let query = `
    AzureSigninLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend app = iff(isempty(AppDisplayName), "(not recorded)", AppDisplayName), clientApp = iff(isempty(ClientAppUsed), "(not recorded)", ClientAppUsed)
    | extend authRequirement = iff(isempty(AuthenticationRequirement), "(not recorded)", AuthenticationRequirement), caStatus = iff(isempty(ConditionalAccessStatus), "(not recorded)", ConditionalAccessStatus)
    | extend country = iff(isempty(Location), "(not recorded)", Location), userType = iff(isempty(UserType), "(not recorded)", UserType)
    | extend deviceOS = iff(isempty(tostring(DeviceDetail.operatingSystem)), "(not recorded)", tostring(DeviceDetail.operatingSystem)), browser = iff(isempty(tostring(DeviceDetail.browser)), "(not recorded)", tostring(DeviceDetail.browser))
    | extend riskLevel = iff(isempty(RiskLevelDuringSignIn), "(not recorded)", RiskLevelDuringSignIn), protocol = iff(isempty(AuthenticationProtocol), "(not recorded)", AuthenticationProtocol)
    | extend failedCode = iff(ResultType != "0", ResultType, "(none)")
    | extend upn = iff(isempty(UserPrincipalName), "(not recorded)", tolower(UserPrincipalName)), ip = iff(isempty(IPAddress), "(not recorded)", IPAddress)
    | extend user = upn, failedUser = iff(ResultType != "0", upn, "(none)"), failedIp = iff(ResultType != "0", ip, "(none)")
    | facet by app, clientApp, authRequirement, caStatus, country, deviceOS, browser, userType, riskLevel, protocol, failedCode, user, failedUser, failedIp with (take 0)
    `
    return Run(status, "AzureSigninLogs", query)
}

// ---- Entra directory-audit logs --------------------------------------------------------------------------
// events; failed (Result failure); userChanges, groupChanges, roleChanges, appChanges, policyChanges (by Category);
// adds, updates, deletes (by AADOperationType); passwordEvents (activity names that mention a password).
function GetAuditTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    AzureAuditLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | summarize
        events = count(),
        failed = countif(Result == "failure"),
        userChanges = countif(Category == "UserManagement"),
        groupChanges = countif(Category == "GroupManagement"),
        roleChanges = countif(Category == "RoleManagement"),
        appChanges = countif(Category == "ApplicationManagement"),
        policyChanges = countif(Category == "Policy"),
        adds = countif(AADOperationType == "Add"),
        updates = countif(AADOperationType == "Update"),
        deletes = countif(AADOperationType == "Delete"),
        passwordEvents = countif(ActivityDisplayName has "password")
        by Date = bin(TimeGenerated, ${interval})
    | sort by Date asc
    `
    return Run(status, "AzureAuditLogs", query)
}

// Facets: category, activity, opType, service (LoggedByService), result; failedActivity (activity of failed events,
// "(none)" for the rest).
function GetAuditFacets(status, rangeFrom, rangeTo) {
    let query = `
    AzureAuditLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend category = iff(isempty(Category), "(not recorded)", Category), activity = iff(isempty(ActivityDisplayName), "(not recorded)", ActivityDisplayName)
    | extend opType = iff(isempty(AADOperationType), "(not recorded)", AADOperationType), service = iff(isempty(LoggedByService), "(not recorded)", LoggedByService), result = iff(isempty(Result), "(not recorded)", Result)
    | extend failedActivity = iff(Result == "failure", activity, "(none)")
    | extend who = tostring(coalesce(InitiatedBy.user.userPrincipalName, InitiatedBy.app.displayName))
    | extend actor = iff(isempty(who), "(not recorded)", tolower(who))
    | extend failedActor = iff(Result == "failure", actor, "(none)")
    | facet by category, activity, opType, service, result, failedActivity, actor, failedActor with (take 0)
    `
    return Run(status, "AzureAuditLogs", query)
}

// ---- Entra service-principal sign-ins (apps, not people) ---------------------------------------------------
// In practice most Entra sign-in volume. events; failed (ResultType other than 0); secretErrors (expired or invalid
// client secret, codes 7000222 and 7000215); secretAuth and assertionAuth (client secret versus certificate or
// federated assertion).
function GetSpTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    AADServicePrincipalSignInLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | summarize
        events = count(),
        failed = countif(ResultType != "0"),
        secretErrors = countif(ResultType in ("7000222", "7000215")),
        secretAuth = countif(ClientCredentialType == "clientSecret"),
        assertionAuth = countif(ClientCredentialType == "clientAssertion")
        by Date = bin(TimeGenerated, ${interval})
    | sort by Date asc
    `
    return Run(status, "AADServicePrincipalSignInLogs", query)
}

// Facets: app (ServicePrincipalName), resource (ResourceDisplayName), credential (ClientCredentialType), country (Location),
// failedCode (ResultType of failed sign-ins, "(none)" for successes). Every facet covers every sign-in.
function GetSpFacets(status, rangeFrom, rangeTo) {
    let query = `
    AADServicePrincipalSignInLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend app = iff(isempty(ServicePrincipalName), "(not recorded)", ServicePrincipalName), resource = iff(isempty(ResourceDisplayName), "(not recorded)", ResourceDisplayName)
    | extend credential = iff(isempty(ClientCredentialType), "(not recorded)", ClientCredentialType), country = iff(isempty(Location), "(not recorded)", Location)
    | extend failedCode = iff(ResultType != "0", ResultType, "(none)")
    | extend failedIp = iff(ResultType != "0", iff(isempty(IPAddress), "(not recorded)", IPAddress), "(none)")
    | facet by app, resource, credential, country, failedCode, failedIp with (take 0)
    `
    return Run(status, "AADServicePrincipalSignInLogs", query)
}

// ---- Entra non-interactive user sign-ins --------------------------------------------------------------------
// Same user sign-in fields as AzureSigninLogs. This table is empty on some tenants and absent on others; both are fine.
// (Not verified against data on the audit tenant, where the table is empty.)
function GetNiTrend(status, rangeFrom, rangeTo, interval) {
    let query = `
    AADNonInteractiveUserSignInLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | summarize
        events = count(),
        failed = countif(ResultType != "0"),
        guests = countif(UserType == "guest")
        by Date = bin(TimeGenerated, ${interval})
    | sort by Date asc
    `
    return Run(status, "AADNonInteractiveUserSignInLogs", query)
}

function GetNiFacets(status, rangeFrom, rangeTo) {
    let query = `
    AADNonInteractiveUserSignInLogs
    | where TimeGenerated >= datetime("${rangeFrom}") and TimeGenerated < datetime("${rangeTo}")
    | extend app = iff(isempty(AppDisplayName), "(not recorded)", AppDisplayName), clientApp = iff(isempty(ClientAppUsed), "(not recorded)", ClientAppUsed)
    | extend country = iff(isempty(Location), "(not recorded)", Location)
    | extend failedCode = iff(ResultType != "0", ResultType, "(none)")
    | extend upn = iff(isempty(UserPrincipalName), "(not recorded)", tolower(UserPrincipalName)), ip = iff(isempty(IPAddress), "(not recorded)", IPAddress)
    | extend failedUser = iff(ResultType != "0", upn, "(none)"), failedIp = iff(ResultType != "0", ip, "(none)")
    | facet by app, clientApp, country, failedCode, failedUser, failedIp with (take 0)
    `
    return Run(status, "AADNonInteractiveUserSignInLogs", query)
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
