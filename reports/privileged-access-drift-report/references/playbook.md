# Privileged Access Drift: query playbook

Engine rules (see `ingext-kql`): always pass `rangeFrom` and `rangeTo` as epoch milliseconds; `summarize` needs an aggregate; a join against a large table
fails when the right side is clipped at 8,192 rows. `W` below is the 60-day window. Save every reply as `<name>.json`. No query below returns a user name.

**Snapshots come from resource dumps first.** `office365User` and `office365InstalledApp` are read from their resource dumps (`list_resource_dumps`, `get_resource_dump_url`,
then `scripts/dump_evidence.py`), which writes `roles`, `accounts`, `apps` and the sign-in queries without any search. Section 1 and the publisher query in section 4 are only the
fallback for a tenant whose dump is missing or cannot be downloaded.

## 1. Role inventory and privileged accounts (snapshot; fallback only) -> `roles`, `accounts`

```
office365User | where array_length(roles) > 0 | mv-expand role = roles | extend role=tostring(role)
| summarize holders=count(), enabled=countif(accountEnabled==true), disabled=countif(accountEnabled==false), guests=countif(userType=="Guest") by role
```
```
office365User | where array_length(roles) > 0
| extend nroles=array_length(roles), lic=array_length(assignedLicenses), mfa=tobool(userRegistration.isMfaRegistered), pwl=tobool(userRegistration.isPasswordlessCapable),
  shared=(userPrincipalName matches regex "^(helpdesk|admin|it|support|service|info|noreply)[@.]")
| summarize accounts=count(), enabled=countif(accountEnabled==true), disabled=countif(accountEnabled==false), licensed=countif(lic>0), multi6=countif(nroles>=6),
  shared=countif(shared), noMfa=countif(mfa==false), passwordless=countif(pwl==true), guests=countif(userType=="Guest"), new90=countif(todatetime(createdDateTime) > ago(90d))
```
## 2. Administrator sign-ins (W) -> `signins_<n>`

With the dump: run each `signins_query_<n>.kql` that `dump_evidence.py` wrote (privileged accounts listed inside the query, 150 per batch) and save the replies; `drift_evidence.py` sums the batches.
Without the dump (fallback):

```
AzureSigninLogs
| join kind=inner (office365User | where array_length(roles) > 0 | project UserPrincipalName=userPrincipalName) on UserPrincipalName
| summarize signins=count(), ok=countif(ResultType=="0"), sfa=countif(ResultType=="0" and AuthenticationRequirement=="singleFactorAuthentication") by UserPrincipalName
| summarize admins=count(), signins=sum(signins), ok=sum(ok), sfa=sum(sfa), sfaAdmins=countif(sfa>0), allSfaAdmins=countif(sfa==ok and ok>0)
```
If the join reports a truncated secondary table (more than 8,192 users), read the privileged list once with
`office365User | where array_length(roles) > 0 | summarize upns=make_list(userPrincipalName)` and use `AzureSigninLogs | where UserPrincipalName in (<list>)` for the
same summarize. The list stays inside the query; only the aggregate is saved.

## 3. Role drift (W) -> `role_drift`, `role_activity`

```
AzureAuditLogs | where Category == "RoleManagement"
| where ActivityDisplayName has_any ("outside of PIM", "in PIM completed", "PIM alert", "Update role setting")
| extend role=tostring(TargetResources[0].displayName), appinit=tostring(InitiatedBy.app.displayName)
| extend init=iff(appinit != "", appinit, "(user)")
| summarize n=count(), first=min(TimeGenerated), last=max(TimeGenerated) by ActivityDisplayName, role, init
```
```
AzureAuditLogs | where Category == "RoleManagement"
| extend appinit=tostring(InitiatedBy.app.displayName) | extend init=iff(appinit != "", appinit, "(user or system)")
| summarize n=count() by ActivityDisplayName, init
```
Key activities: "Add member to role outside of PIM (permanent)", "Add member to role in PIM completed (permanent)" / "(timebound)", "Remove member from role in PIM completed (permanent)",
"Add member to role completed (PIM activation)", "Triggered PIM alert", "Resolve PIM alert", "Update role setting in PIM". An application initiator is named; a person is "(user)".

## 4. Application privilege (W) -> `app_grants`, `app_events`, `apps`

```
AzureAuditLogs | where ActivityDisplayName == "Add app role assignment to service principal"
| extend mp = tostring(TargetResources[0].modifiedProperties)
| extend perm = extract('AppRole.Value[^}]*newValue\\W+([A-Za-z.]+)', 1, mp), client = extract('ServicePrincipal.DisplayName[^}]*newValue\\W+([^\\\\"]+)', 1, mp)
| summarize n=count() by day=bin(TimeGenerated, 1d), client, perm
```
```
AzureAuditLogs | where ActivityDisplayName in ("Consent to application","Add delegated permission grant","Add service principal credentials","Add owner to service principal","Add owner to application","Add service principal","Add application")
| summarize n=count() by ActivityDisplayName
```
Publisher (fallback only; the `office365InstalledApp` dump already gives it for every application. Run after the first query with the client names it returned; save as `apps`):
```
office365InstalledApp | where displayName in ("<client 1>", "<client 2>") | project displayName, verified=tostring(verifiedPublisher.displayName)
```
Tiers (`assets/rating_rules.json`): Tier 0 can take over the tenant (RoleManagement.ReadWrite.Directory, Application.ReadWrite.All, AppRoleAssignment.ReadWrite.All, Directory.ReadWrite.All,
Policy.ReadWrite.ConditionalAccess / AuthenticationMethod, DeviceLocalCredential.Read.All, BitlockerKey.Read.All ...). Tier 1 is tenant-wide business data (Sites.FullControl.All, Files.Read.All,
Mail.*, MailboxItem.*, Chat.Read.All, Exchange.ManageAsApp, User/Group.ReadWrite.All ...). Everything else is Tier 2 (Sites.Selected is Tier 2).

## 5. Conditional Access changes (W) -> `ca_changes`

```
AzureAuditLogs | where Category in ("Policy","PolicyManagement") | where ActivityDisplayName has "conditional access"
| summarize n=count() by day=bin(TimeGenerated, 1d), ActivityDisplayName, policy=tostring(TargetResources[0].displayName)
```
## 6. On premises (30 days) -> `windows_archive`: an archive download, not a search

`list_report_archive` for `WindowsSrv_Activity_Report`, then `download_report_archive` (last 30 days, `objects` `win_trend`). `drift_evidence.py` sums `groupAdds` (4728, 4732, 4756),
`accountCreated` (4720), `events` and `logonsOk` over the archived days. No group additions or account creations while events arrive means group auditing is off on the domain
controllers (a coverage gap), not an absence of change. Missing days are reported, and `backfill_report_archive` can fill them; a gap is never filled with a search.
