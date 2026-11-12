// Microsoft 365 / Entra resource inventory report: the directory facts the compliance-assessment skill reads from the
// Office 365 resource dumps (office365User, office365Device, office365ConditionalAccessPolicy, office365Application,
// office365InstalledApp, office365Group), computed here as counts so they can be archived once a day and read later
// without downloading a dump. Account hygiene (users, enabled, disabled, guests, administrators, MFA registration),
// device currency and compliance, Conditional Access policies by state, app-registration credential hygiene and
// requested permissions, enterprise applications and group shape. Everything is a count except one table,
// o365res_noncompliant_users, which NAMES the users who fail the MFA test so that a single run identifies them. That
// table is personal data (user principal names and display names), so the archive of this report is personal data and a
// report built from it should not leave the tenant's owner. No device, app or group names, members or secret values are
// returned.
// The resource tables are snapshots of the directory as it is now, not event logs, so they have no time column. Every
// table carries asOf, the end of the run window: the archived day is the state when the daily run took the snapshot, and
// a later day replaces an earlier one. NEVER add the days of this report together; read the latest archived day, or the
// day nearest the end of a period, and compare days to see change. Only the 90-day and 730-day tests use the window.
// from and to only fix the run window (and asOf); a daily archived run uses -1d@d to @d, like the other archived reports.
//
// Eleven scans (one table each, plus "sources"):
//   o365res_users          one row: users, enabled, disabled, guests, admins, registrationKnown, enabledMfaRegistered,
//                          enabledNoMfa, adminsNoMfa, then the administrator counts globalAdmins, adminsEnabled,
//                          adminsLicensed, adminsStacked, adminsSharedStyle, adminsPasswordless, adminsNew90d.
//   o365res_role_holders   one row per directory role: role, holders, enabled, disabled, noMfa, licensed, asOf. Counts only.
//   o365res_devices        one row: devices, managedKnown, managed, complianceKnown, nonCompliant, stale90d.
//   o365res_ca             one row per Conditional Access policy state: state, policies.
//   o365res_apps           one row of app-registration counts: apps, secrets, certificates, appsNoCredentials, multiTenant.
//   o365res_app_secrets    one row of client-secret tests: secrets, expired, expiring90d, longLived.
//   o365res_app_perms      one row: appsAppOnly, the registrations that request an application-type (app-only) permission.
//   o365res_enterprise     one row of enterprise-application (service principal) counts.
//   o365res_groups         one row of group counts.
//   o365res_noncompliant_users   one row per enabled user with no MFA registered: userPrincipalName, displayName, userType,
//                          finding, isAdmin, roles, asOf. Administrators come first. See the definitions below.
//   o365res_licensed_users one row per user holding at least one license: userPrincipalName, displayName, userType,
//                          accountEnabled, licenseCount, licenses, asOf. licenses is the product names, comma separated.
//
// Definitions (the same as compliance-assessment's build_report.py):
//   admin               userRegistration.isAdmin is true, or the user holds at least one directory role.
//   enabled             accountEnabled is true. disabled is accountEnabled false. A user with neither is in users only.
//   registrationKnown   users with an MFA registration record (userRegistration.id present). When it is 0 the MFA figures
//                       are not known and must not be read as "no MFA". MFA registration is not MFA enforcement.
//   enabledMfaRegistered / enabledNoMfa / adminsNoMfa   isMfaRegistered true / false on enabled users / on enabled admins.
//   guests              userType is "Guest".
//   globalAdmins        users whose roles include Global Administrator (enabled or not).
//   adminsEnabled / adminsLicensed   administrators (broad definition above) with accountEnabled true / holding at least one license.
//   adminsStacked       administrators holding six or more directory roles.
//   adminsSharedStyle   administrators whose user principal name starts with helpdesk, admin, it, support, service, info or
//                       noreply followed by @ or a dot (a shared or generic account name). A name pattern, not proof.
//   adminsPasswordless  administrators with userRegistration.isPasswordlessCapable true.
//   adminsNew90d        administrators whose createdDateTime is within 90 days before asOf.
//   role holders        o365res_role_holders counts the users holding each directory role (a user with several roles is counted
//                       once in each); noMfa is the enabled holders whose isMfaRegistered is false. Counts only: no names. Like
//                       the other tables it is a state, so read the latest day and compare days to see change. Role history
//                       begins the day this table was first archived; a snapshot cannot be backfilled.
//   licensed user       a user whose assignedLicenses holds at least one skuId, enabled or not. licenses are the product names
//                       from the Microsoft365_License_Table lookup (SKUID to Product name, as in Microsoft365_Status_Resource_Report);
//                       a skuId the lookup does not know is shown as the skuId so no license is dropped. The users per license
//                       are a count of this table. Personal data.
//   noncompliant user   an enabled user (accountEnabled true) whose userRegistration.isMfaRegistered is false. finding is
//                       "Admin without MFA" for an administrator (the broad definition above, so a user holding any
//                       directory role counts) and "Enabled user without MFA" for any other user. Guests and members are both
//                       listed; userType tells them apart. The list has one row per user and no limit, and its row count equals
//                       enabledNoMfa in o365res_users. A tenant that reports no MFA registration (registrationKnown 0) has an
//                       empty list: that is not knowledge that everyone has MFA. MFA registration is not MFA enforcement.
//   managed / nonCompliant   isManaged true / isCompliant false; managedKnown and complianceKnown count the devices where
//                       the field is present (0 means the tenant does not report it, not that every device is unmanaged).
//   stale90d            devices whose approximateLastSignInDateTime is more than 90 days before asOf.
//   secrets / certificates   passwordCredentials / keyCredentials entries on app registrations.
//   expired / expiring90d    secrets whose end date is before asOf / within 90 days after it.
//   longLived           secrets valid for more than 730 days (end minus start).
//   appsAppOnly         registrations whose requiredResourceAccess asks for a resourceAccess of type Role. It shows what is
//                       requested, not what an administrator consented to.
//   multiTenant         signInAudience AzureADMultipleOrgs, AzureADandPersonalMicrosoftAccount or PersonalMicrosoftAccount.
//   enterprise          service principals: microsoftOwned (owner tenant is a Microsoft first-party tenant), registeredHere
//                       (the appId is an app registration of this tenant), thirdParty (another publisher, not registered here,
//                       owner tenant known), assignmentRequired, withCredentials.
//   groups              securityEnabled, microsoft365 (group type Unified), publicGroups (visibility Public), roleAssignable,
//                       dynamicGroups (DynamicMembership), emptyGroups (no members), membersTotal (membership entries, not people).
//
// A scan that fails (no such resource table on the tenant, or any query error) returns an empty table and is recorded in
// "sources" with status "not available" and the error text; an "ok" scan with a zero count is an empty directory table.
// A tenant without Microsoft 365 is never an error.

function main({from="-1d@d", to="@d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let status = {rows: []}
    let o365res_users = GetUsers(status, rangeTo)
    let o365res_devices = GetDevices(status, rangeTo)
    let o365res_ca = GetConditionalAccess(status, rangeTo)
    let o365res_apps = GetApps(status, rangeTo)
    let o365res_app_secrets = GetAppSecrets(status, rangeTo)
    let o365res_app_perms = GetAppPermissions(status, rangeTo)
    let o365res_enterprise = GetEnterpriseApps(status, rangeTo)
    let o365res_groups = GetGroups(status, rangeTo)
    let o365res_noncompliant_users = GetNonCompliantUsers(status, rangeTo)
    let o365res_licensed_users = GetLicensedUsers(status, rangeTo)
    let o365res_role_holders = GetRoleHolders(status, rangeTo)
    let sources = jsonTable(status.rows)
    return {
        o365res_users,
        o365res_devices,
        o365res_ca,
        o365res_apps,
        o365res_app_secrets,
        o365res_app_perms,
        o365res_enterprise,
        o365res_groups,
        o365res_noncompliant_users,
        o365res_licensed_users,
        o365res_role_holders,
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

// ---- Users (office365User) -------------------------------------------------------------------------------
// Account hygiene counts. The users behind the MFA figures are listed by GetNonCompliantUsers.
function GetUsers(status, rangeTo) {
    let query = `
    office365User
    | extend isAdmin = (['userRegistration.isAdmin'] == true) or array_length(roles) > 0
    | extend isEnabled = accountEnabled == true, mfa = ['userRegistration.isMfaRegistered']
    | summarize
        users = count(),
        enabled = countif(isEnabled),
        disabled = countif(accountEnabled == false),
        guests = countif(userType == "Guest"),
        admins = countif(isAdmin),
        registrationKnown = countif(isnotempty(['userRegistration.id'])),
        enabledMfaRegistered = countif(isEnabled and mfa == true),
        enabledNoMfa = countif(isEnabled and mfa == false),
        adminsNoMfa = countif(isAdmin and isEnabled and mfa == false),
        globalAdmins = countif(tostring(roles) has "Global Administrator"),
        adminsEnabled = countif(isAdmin and isEnabled),
        adminsLicensed = countif(isAdmin and array_length(assignedLicenses) > 0),
        adminsStacked = countif(array_length(roles) >= 6),
        adminsSharedStyle = countif(isAdmin and tolower(userPrincipalName) matches regex "^(helpdesk|admin|it|support|service|info|noreply)[@.]"),
        adminsPasswordless = countif(isAdmin and ['userRegistration.isPasswordlessCapable'] == true),
        adminsNew90d = countif(isAdmin and isnotnull(createdDateTime) and createdDateTime >= datetime("${rangeTo}") - 90d)
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "office365User", query)
}

// ---- Devices (office365Device) ---------------------------------------------------------------------------
function GetDevices(status, rangeTo) {
    let query = `
    office365Device
    | summarize
        devices = count(),
        managedKnown = countif(isnotnull(isManaged)),
        managed = countif(isManaged == true),
        complianceKnown = countif(isnotnull(isCompliant)),
        nonCompliant = countif(isCompliant == false),
        stale90d = countif(isnotnull(approximateLastSignInDateTime) and approximateLastSignInDateTime < datetime("${rangeTo}") - 90d)
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "office365Device", query)
}

// ---- Conditional Access policies (office365ConditionalAccessPolicy) -------------------------------------
// One row per state: enabled (enforced), enabledForReportingButNotEnforced (report-only), disabled.
function GetConditionalAccess(status, rangeTo) {
    let query = `
    office365ConditionalAccessPolicy
    | extend state = iff(isempty(state), "(not recorded)", tostring(state))
    | summarize policies = count() by state
    | extend asOf = datetime("${rangeTo}")
    | sort by policies desc
    `
    return Run(status, "office365ConditionalAccessPolicy", query)
}

// ---- App registrations (office365Application) ----------------------------------------------------------
function GetApps(status, rangeTo) {
    let query = `
    office365Application
    | summarize
        apps = count(),
        secrets = sum(array_length(passwordCredentials)),
        certificates = sum(array_length(keyCredentials)),
        appsNoCredentials = countif(not(array_length(passwordCredentials) > 0) and not(array_length(keyCredentials) > 0)),
        multiTenant = countif(signInAudience in ("AzureADMultipleOrgs", "AzureADandPersonalMicrosoftAccount", "PersonalMicrosoftAccount"))
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "office365Application", query)
}

// Client secrets, one row per secret expanded from passwordCredentials. No secret values or hints are returned.
function GetAppSecrets(status, rangeTo) {
    let query = `
    office365Application
    | mv-expand cred = passwordCredentials
    | where isnotempty(tostring(cred.keyId)) or isnotempty(tostring(cred.endDateTime))
    | extend e = todatetime(cred.endDateTime), s = todatetime(cred.startDateTime)
    | summarize
        secrets = count(),
        expired = countif(isnotnull(e) and e < datetime("${rangeTo}")),
        expiring90d = countif(isnotnull(e) and e >= datetime("${rangeTo}") and e < datetime("${rangeTo}") + 90d),
        longLived = countif(isnotnull(e) and isnotnull(s) and (e - s) / 1d > 730)
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "app registration client secrets", query)
}

// Registrations that request at least one application-type (app-only) permission: resourceAccess entries of type Role.
function GetAppPermissions(status, rangeTo) {
    let query = `
    office365Application
    | mv-expand req = requiredResourceAccess
    | mv-expand ra = req.resourceAccess
    | where tostring(ra.type) == "Role"
    | summarize appsAppOnly = dcount(id)
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "app registration permissions", query)
}

// ---- Enterprise applications (office365InstalledApp holds service principals, not software on devices) -----
function GetEnterpriseApps(status, rangeTo) {
    // The tenant's own app registrations are found by a left join of the service principals to office365Application on appId
    // (one row per appId on the right, so no service principal is counted twice). A tenant with no app registration table makes the
    // joined query fail: the scan then runs without the join, registeredHere is 0 and thirdParty counts every non-Microsoft
    // application, and the failure is recorded in sources.
    let joined = EnterpriseAppsQuery(rangeTo, `| join kind=leftouter (office365Application | summarize ownCount = count() by ownAppId = appId) on $left.appId == $right.ownAppId`, "isnotempty(ownAppId)")
    try {
        let r = kql(joined)
        status.rows = append(status.rows, {source: "office365InstalledApp", status: "ok"})
        return r
    } catch (e) {
        status.rows = append(status.rows, {source: "enterprise apps: join to app registrations", status: "not available", detail: toString(e)})
    }
    return Run(status, "office365InstalledApp", EnterpriseAppsQuery(rangeTo, "", "false"))
}

// The enterprise-application scan. joinPart is the optional join to the app registrations; ownExpr says when a row is one of the tenant's own.
function EnterpriseAppsQuery(rangeTo, joinPart, ownExpr) {
    return `
    office365InstalledApp
    ${joinPart}
    | extend isMs = appOwnerOrganizationId in ("f8cdef31-a31e-4b4a-93e4-5f571e91255a", "72f988bf-86f1-41af-91ab-2d7cd011db47")
    | extend isOwn = ${ownExpr}
    | summarize
        total = count(),
        enabled = countif(accountEnabled == true),
        disabled = countif(accountEnabled == false),
        microsoftOwned = countif(isMs),
        registeredHere = countif(isOwn),
        thirdParty = countif(not(isMs) and not(isOwn) and isnotempty(appOwnerOrganizationId)),
        assignmentRequired = countif(appRoleAssignmentRequired == true),
        withCredentials = countif(array_length(passwordCredentials) > 0 or array_length(keyCredentials) > 0)
    | extend asOf = datetime("${rangeTo}")
    `
}

// ---- Groups (office365Group) -----------------------------------------------------------------------------
// Counts only: no group names, no members.
function GetGroups(status, rangeTo) {
    let query = `
    office365Group
    | extend gt = tostring(groupTypes)
    | summarize
        groups = count(),
        securityEnabled = countif(securityEnabled == true),
        microsoft365 = countif(gt has "Unified"),
        publicGroups = countif(visibility == "Public"),
        roleAssignable = countif(isAssignableToRole == true),
        dynamicGroups = countif(gt has "DynamicMembership"),
        emptyGroups = countif(not(array_length(members) > 0)),
        membersTotal = sum(array_length(members))
    | extend asOf = datetime("${rangeTo}")
    `
    return Run(status, "office365Group", query)
}

// ---- Non-compliant users (office365User) -----------------------------------------------------------------
// The enabled users with no MFA registered, one row each, administrators first (the counts enabledNoMfa and adminsNoMfa
// in o365res_users are the totals of this list). roles is the user's directory roles as text. Personal data.
function GetNonCompliantUsers(status, rangeTo) {
    let query = `
    office365User
    | extend isAdmin = iff((['userRegistration.isAdmin'] == true) or array_length(roles) > 0, true, false)
    | where accountEnabled == true and ['userRegistration.isMfaRegistered'] == false
    | extend finding = iff(isAdmin, "Admin without MFA", "Enabled user without MFA")
    | project userPrincipalName, displayName, userType, finding, isAdmin, roles = tostring(roles)
    | extend asOf = datetime("${rangeTo}")
    | sort by isAdmin desc, userPrincipalName asc
    `
    return Run(status, "non-compliant users (no MFA registered)", query)
}

// ---- Licensed users (office365User) ----------------------------------------------------------------------
// Every user holding at least one license, with the license product names. The names come from the
// Microsoft365_License_Table lookup; if the lookup is missing the skuIds are returned and the failure is recorded in
// sources. Personal data.
function GetLicensedUsers(status, rangeTo) {
    let query = `
    office365User
    | mv-apply lic = assignedLicenses on (summarize skuids = make_list_if(tostring(lic.skuId), isnotempty(tostring(lic.skuId))))
    | where array_length(skuids) > 0
    | project userPrincipalName, displayName, userType, accountEnabled, skuids = tostring(skuids)
    | extend asOf = datetime("${rangeTo}")
    | sort by userPrincipalName asc
    `
    let t = Run(status, "licensed users", query)
    try {
        t.NewColumns(({ skuids }) => {
            let arr = JSON.parse(skuids)
            let names = arr.Map((k, v) => {
                let {exist, value} = fluencyEntityinfoLookup("Microsoft365_License_Table", "SKUID", toString(v), "Product name")
                if (exist && toString(value) != "") {
                    return toString(value)
                }
                return toString(v)
            })
            return { licenseCount: len(arr), licenses: names.Join(", ") }
        })
        status.rows = append(status.rows, {source: "license names (Microsoft365_License_Table lookup)", status: "ok"})
    } catch (e) {
        status.rows = append(status.rows, {source: "license names (Microsoft365_License_Table lookup)", status: "not available", detail: toString(e)})
    }
    return t
}

// ---- Role holders (office365User) -------------------------------------------------------------------------
// One row per directory role with the number of users holding it. Counts only, no names; the users behind a count are
// in the resource dump. roles is an array of role display names.
function GetRoleHolders(status, rangeTo) {
    let query = `
    office365User
    | mv-expand role = roles
    | extend role = tostring(role)
    | where isnotempty(role)
    | summarize
        holders = count(),
        enabled = countif(accountEnabled == true),
        disabled = countif(accountEnabled == false),
        noMfa = countif(accountEnabled == true and ['userRegistration.isMfaRegistered'] == false),
        licensed = countif(array_length(assignedLicenses) > 0)
      by role
    | extend asOf = datetime("${rangeTo}")
    | sort by holders desc, role asc
    `
    return Run(status, "role holders (office365User roles)", query)
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
