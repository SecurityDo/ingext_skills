# Privileged Access Drift: archive playbook

No live query. The skill lists and downloads the archives of scheduled reports (`list_report_archive`, `download_report_archive`, `backfill_report_archive`); `scripts/drift_evidence.py`
merges the days. Each saved reply is `{days: [{entry: {rangeFrom...}, result: {objects: [...]}}]}`.

## Where each figure comes from

| Report section | Archive and object | Columns used |
|---|---|---|
| Privileged accounts, licences, MFA, stacked roles, shared-style names, passwordless, new accounts | `Office365_Resource_Inventory_Report` / `o365res_users` (latest day) | admins, adminsNoMfa, globalAdmins, adminsEnabled, adminsLicensed, adminsStacked, adminsSharedStyle, adminsPasswordless, adminsNew90d |
| Role inventory, Global Administrator count, change between snapshots | `Office365_Resource_Inventory_Report` / `o365res_role_holders` | role, holders, enabled, disabled, noMfa, licensed, asOf |
| Outside-PIM and PIM role drift, initiators, removals | `Privileged_Access_Drift_Report` / `pad_role_events` | Date, activity, role, initiator, initiatorType, outsidePim, n |
| Applications granted permissions | `Privileged_Access_Drift_Report` / `pad_app_grants` | Date, client, appId, permission, n |
| Conditional Access changes | `Privileged_Access_Drift_Report` / `pad_ca_changes` | Date, activity, policy, n |
| Administrator sign-ins, single-factor share | `Privileged_Access_Drift_Report` / `pad_admin_signins` | privileged, adminsSeen, signins, ok, failed, singleFactorOk, legacyAuth, adminsSingleFactor, adminsAllSingleFactor |
| Scan status per source | `sources` (both reports) | source, status (ok or not available), detail |
| Application activity counts (consents, delegated grants, credentials) | `Office365_Entra_Activity_Report` / `audit_facets`, facet `activity` | activity, count_ |
| On-premises privileged group changes | `WindowsSrv_Activity_Report` / `win_trend` | events, logonsOk, groupAdds, accountCreated |
| Application publisher | `office365InstalledApp` resource dump, by `appId` (`scripts/dump_evidence.py`) | appId, displayName, verifiedPublisher.displayName |

The `Privileged_Access_Drift_Report` source is `fplProcessors/code/Privileged_Access_Drift_Report.js` in the Scripts repository: one run per day, counts only, no user name. It reads the
privileged accounts inside the run and counts their sign-ins in batches of 150 (a join fails above 8,192 users); `batches` and `failedBatches` in `pad_admin_signins` say if any batch failed.
Role names are read from the target or from the modified properties; an application grant carries `ServicePrincipal.AppId`, `ServicePrincipal.DisplayName` and `AppRole.Value`.

## Key role activities

"Add member to role outside of PIM (permanent)", "Add member to role in PIM completed (permanent)" / "(timebound)", "Remove member from role in PIM completed (permanent)",
"Add member to role completed (PIM activation)", "Triggered PIM alert", "Resolve PIM alert", "Update role setting in PIM", and the direct "Add member to role" / "Remove member from role".
An application initiator is named; a person is "(user)".

## Application tiers

`assets/rating_rules.json`. Tier 0 can take over the tenant (RoleManagement.ReadWrite.Directory, Application.ReadWrite.All, AppRoleAssignment.ReadWrite.All, Directory.ReadWrite.All,
Policy.ReadWrite.ConditionalAccess / AuthenticationMethod, DeviceLocalCredential.Read.All, BitlockerKey.Read.All ...). Tier 1 is tenant-wide business data (Sites.FullControl.All, Files.Read.All,
Mail.*, MailboxItem.*, Chat.Read.All, Exchange.ManageAsApp, User/Group.ReadWrite.All ...). Everything else is Tier 2 (Sites.Selected is Tier 2).

## Gaps and how to close them

- Fewer archived days than the window: `backfill_report_archive` for `Privileged_Access_Drift_Report` (it can be run for past days; the inventory report is a daily snapshot and cannot).
- `sources` shows a scan as "not available" (for example no Conditional Access table): the figure is "Not observed", not zero.
- No group additions or account creations in the Windows archive while events arrive: group auditing is off on the domain controllers (a coverage gap), not an absence of change.
