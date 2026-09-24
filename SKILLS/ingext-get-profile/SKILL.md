---
name: ingext-get-profile
version: 1.0.0
description: >-
  Resolve an entity (a user, a group or a device) on one Fluency/Ingext tenant account
  and return its profile: which system it belongs to (Google Workspace, Microsoft 365 /
  Entra ID, Defender, SentinelOne, CrowdStrike, Qualys) and what it IS — admin flags and
  roles, status, MFA state and recovery contacts for a user; OS, last user, IPs, join and
  compliance state, agent health, threat and exposure level for a device. Determines the
  entity type from the resource tables list_data_tables reports for the account, then
  queries only those. A dependency of incident-investigation (step 1). Triggers: "get the
  profile for user@corp.com", "who is this user", "is this account an admin", "is X a
  Google or Office 365 user", "look up this host", "what is asset_<host>_<date>", "look up
  this group". Reads directory and inventory state only, not activity; for what the entity
  did, use incident-investigation, office-user-investigation or ingext-kql.
---

# Get an entity's profile

Before judging what an account did, establish what it **is**. A Global Administrator
assigning licences is expected; the same action from an unroled Member is a ticket. A
super-admin approving an OAuth app is routine; a suspended account doing it is not.
A device is the same question asked of a machine: a hybrid-joined, Intune-compliant
company laptop with a healthy EDR agent reads differently from an unmanaged host with no
agent. This skill answers the "what is it" question and nothing else, and hands a
normalized profile back to whoever called it.

It is a **sub-skill**. Callers (today: `incident-investigation`) invoke it with an
account and an entity and read the profile block it returns. It can also be run on
its own when a user asks who someone is.

## Inputs

| Input | Meaning | Example |
|---|---|---|
| connector | the MCP connector the caller is using | `Develop` |
| account | the **single** tenant account — passed in by the caller, never chosen here | `contoso` |
| entity | an email / UPN, a host name or FQDN, a directory / agent id, a display name, or a behavior-summary id | `adele.vance@contoso.com`, `corp-ws101`, `asset_corp-ws101_20260924` |
| kind (optional) | `user`, `group` or `device` if the caller already knows | `device` |

**One account only.** This skill inherits the caller's account boundary. Every call
passes exactly the `account` it was given. It never searches other accounts or other
connectors to find where an entity lives, even when the entity is not found — "not
found on this account" is an answer, not a reason to look elsewhere. When run
standalone, confirm the account once with `list_accounts` and stop if it is not there.

## Step 0 — Normalize the entity

- **A behavior-summary id is not an entity.** Summary documents are keyed
  `<keyType>_<key>_<YYYYMMDD>` — `username_adele.vance@contoso.com_20260916`,
  `asset_corp-ws101_20260924`. Strip the prefix and the date: the key is the entity and
  the prefix is its kind (`username` → user, `asset` → device). Say in the result that you
  did this, and what you stripped.
- **Lower-case it.** Every bundled query compares lower-cased values.
- **Infer the kind when not given.** An `@` address → user or group (both are queried —
  a group has an address too). A GUID or numeric id → any kind. A bare name with no `@`
  and no spaces → device first, then group display name. When unsure, query every kind.

## Step 1 — Which directories and inventories does this account have?

Call `list_data_tables` for the account **once** and read `resourceTables`. The
resource tables present decide which identity systems the entity can belong to:

| Resource table present | Identity system | Entity kind | Query |
|---|---|---|---|
| `gsuiteUser` | Google Workspace | user | `assets/queries/gsuite_user.kql` |
| `office365User` | Microsoft 365 / Entra ID | user | `assets/queries/office365_user.kql` + `get_azure_user_record` |
| `gsuiteGroup` | Google Workspace | group | `assets/queries/gsuite_group.kql` |
| `office365Group` | Microsoft 365 / Entra ID | group | `assets/queries/office365_group.kql` |
| `msDefenderMachine` | Microsoft Defender for Endpoint | device | `assets/queries/msdefender_machine.kql` |
| `office365Device` | Entra ID / Intune | device | `assets/queries/office365_device.kql` |
| `sentinelOneAgent` | SentinelOne | device | `assets/queries/sentinelone_agent.kql` |
| `falconAgent` | CrowdStrike Falcon | device | `assets/queries/falcon_agent.kql` |
| `qualysHost` | Qualys | device | `assets/queries/qualys_host.kql` |

For a device, also call `asset_search` once — the platform's merged asset inventory —
with a case-variant wildcard on `name` and `fqdn` (the index is keyword and
case-sensitive):

```json
asset_search { "account": "<account>",
  "query": "name:<host>* OR name:<HOST>* OR fqdn:<host>* OR fqdn:<HOST>*", "limit": 5 }
```

It is a cross-check, not the source of truth: on some accounts it holds only log-derived
hosts (firewalls) and no endpoints at all. Zero hits there with hits in the vendor
tables is a note, not a contradiction.

Record the list of candidate tables. If there are **none**, stop: return
`found: false` with `reason: "no directory resource tables on this account"`. Do not
fall back to `get_azure_user_record` on an account with no `office365User` table
unless the caller asks — see the trap in step 3.

## Step 2 — Query every candidate table, not the first one

An entity can exist in more than one directory (a company on Google Workspace that
also licenses Microsoft 365; a user synced into both). Run the query for **every**
candidate table from step 1 — they are independent, so issue them in the same turn.

For each query:

1. Substitute `{ENTITY}` with the entity **lower-cased**.
2. Call `validate_kql` on the substituted text. Always. It is one cheap call and it
   catches a wrong column name before it becomes a confident "not found".
3. Call `kql_search`. Resource tables are snapshots: the queries carry no time filter
   and need no dedup.
4. **If the query returned zero rows, run the readability probe before calling it "not
   found".** An empty result means either "the entity is not in this table" or "this
   table's fields cannot be read on this account", and nothing in the result tells them
   apart. `assets/queries/readability_probe.kql` counts the table's rows and how many
   have a non-empty key column — one cheap aggregate:

   | Probe result | Meaning | Record as |
   |---|---|---|
   | `readable > 0` | table is readable | genuinely not in this table |
   | `rows > 0`, `readable == 0` | rows exist but key columns are empty | `gaps: ["<table> has <rows> rows but no readable key fields"]` |
   | `rows == 0` | table is empty on this account | `gaps: ["<table> is empty"]` |

   Key columns per table (`{KEY1}`, `{KEY2}`):

   | Table | Keys | Table | Keys |
   |---|---|---|---|
   | `gsuiteUser` | `primaryEmail`, `id` | `msDefenderMachine` | `computerDnsName`, `id` |
   | `office365User` | `userPrincipalName`, `id` | `office365Device` | `displayName`, `id` |
   | `gsuiteGroup` | `email`, `id` | `sentinelOneAgent` | `computerName`, `uuid` |
   | `office365Group` | `displayName`, `id` | `falconAgent` | `hostname`, `device_id` |
   | | | `qualysHost` | `name`, `id` |

   Only a table that passes the probe may contribute to `found: false`. A kind whose
   every candidate table failed the probe is **unknown**, not absent.

Pick queries by `kind`: users only for `user`, groups only for `group`, devices only for
`device`, and every kind when it is unknown. An email address is not proof of a user — a
group has one too.

**Matching rules the queries already implement** (do not rewrite them):

- Google users match the primary address, **any alias** (`emails[]`,
  `nonEditableAliases[]`) and the numeric id. An incident keyed on
  `adele@contoso.io` resolves to the account whose primary address is
  `adele.vance@contoso.com`.
- Microsoft users match `userPrincipalName`, `mail` and the object id. A guest's UPN is
  rewritten (`alice_contoso.com#EXT#@tenant.onmicrosoft.com`), so the `mail` match is the
  one that finds guests.
- Devices match the short host name **and** the FQDN (`corp-ws101` finds
  `corp-ws101.corp.local` in Defender and `CORP-WS101` in Entra), plus each vendor's own
  id. Hosts in different vendor tables are the same machine when the ids line up:
  Defender's `aadDeviceId` equals `office365Device.deviceId`. Report the join key you
  used; never merge two records on name alone when an id disagrees.
- Groups resolve **by object id first**. A display-name match can return several groups —
  report all of them and never pick one (one tenant had three groups named `Custodial`: a
  security group, a distribution list and a security-enabled M365 group).

## Step 3 — For a Microsoft 365 user, read the live directory record

When `office365User` returned a row (or the table exists and the caller insists the
entity is a Microsoft user), call:

```json
get_azure_user_record { "account": "<account>", "username": "<UPN>" }
```

It resolves the user through Microsoft Graph and returns `userType`, `createdDateTime`
and the **assigned Azure AD directory roles** with their descriptions. It is the live
state; the `office365User` row is the last snapshot. When they disagree, the live
record wins and the disagreement goes in `notes`.

**Trap: "not found" from `get_azure_user_record` is not "not a Microsoft user".** It
resolves only through the account's `Office365ResourceWatch` integration. An account
can ingest Microsoft 365 audit events without that integration, and then every lookup
says not found — the same subject can have Microsoft 365 sign-ins in the event stream
and no directory record at all. Report that as a gap
(`"M365 directory record unavailable"`), never as proof the account has no roles.

## Step 4 — Normalize and return the profile

Return one block per directory match, in this shape (JSON in a fenced block when a
skill is the caller; a short table when a person asked):

```json
{
  "entity": "adele@contoso.io",
  "account": "contoso",
  "found": true,
  "matches": [
    {
      "system": "google_workspace",
      "kind": "user",
      "table": "gsuiteUser",
      "id": "100000000000000000001",
      "primary": "adele.vance@contoso.com",
      "displayName": "Adele Vance",
      "aliases": ["adele@contoso.io", "adele@contoso.net"],
      "status": "active",
      "privilege": { "isAdmin": false, "isDelegatedAdmin": false, "roles": [] },
      "mfa": { "enrolled": true, "enforced": true },
      "created": "2019-03-04T08:31:15Z",
      "lastSignIn": "2026-09-23T08:59:42Z",
      "orgUnit": "/Sales",
      "recovery": { "email": "adele.personal@example.com", "phone": "+15550100" },
      "source": "kql_search gsuiteUser (1 row)"
    }
  ],
  "tablesChecked": ["gsuiteUser", "gsuiteGroup"],
  "gaps": [],
  "notes": []
}
```

A device returns one match **per source table** (a laptop can be in Defender, Entra
and SentinelOne at once) plus a merged `device` summary:

```json
{
  "entity": "corp-ws101",
  "normalizedFrom": "asset_corp-ws101_20260924",
  "account": "contoso",
  "found": true,
  "device": {
    "hostname": "CORP-WS101",
    "fqdn": "corp-ws101.corp.local",
    "os": "Windows 11 Enterprise 25H2 (26200)",
    "hardware": "Microsoft Corporation Surface Laptop 5",
    "lastUser": { "account": "avance", "adName": "Adele Vance" },
    "ips": { "internal": ["10.1.1.211"], "external": ["192.0.2.114"] },
    "join": "hybrid (ServerAd), Intune co-managed, compliant",
    "domainOU": "CN=CORP-WS101,OU=Workstations,DC=corp,DC=local",
    "coverage": ["msDefenderMachine", "office365Device", "sentinelOneAgent"],
    "edr": [
      { "vendor": "Defender", "health": "Active", "lastSeen": "2026-09-23T13:31:44Z" },
      { "vendor": "SentinelOne", "active": false, "lastActive": "2026-09-24T05:13:15Z",
        "mitigation": "protect", "activeThreats": 0 }
    ],
    "risk": { "defenderRisk": "Medium", "exposure": "High" },
    "joinKey": "aadDeviceId = office365Device.deviceId"
  },
  "matches": [ "... one per source table, raw projected fields ..." ],
  "tablesChecked": ["msDefenderMachine", "office365Device", "sentinelOneAgent", "asset_search"],
  "gaps": [],
  "notes": []
}
```

Field mapping:

| Profile field | Google user | Microsoft user | Google group | Microsoft group |
|---|---|---|---|---|
| `status` | `suspended` / `archived` → else `active` | `accountEnabled` false → `disabled` | — | `deletedDateTime` set → `deleted` |
| `privilege.isAdmin` | `isAdmin` (super admin) | `userRegistration.isAdmin`, or any role in the live record | — | `isAssignableToRole` |
| `privilege.roles` | `isDelegatedAdmin` → `["delegated admin"]` | live `roles` from `get_azure_user_record`, else snapshot `roles` | — | — |
| `mfa` | `isEnrolledIn2Sv`, `isEnforcedIn2Sv` | `isMfaRegistered`, `methodsRegistered`, `preferredSecondaryMethod` | — | — |
| `groupType` | — | — | `adminCreated` | `securityEnabled` true → `security`, else `distribution`; `groupTypes` has `Unified` → `m365` |
| `lastSignIn` | `lastLoginTime` (1970 epoch → `never`) | not in the snapshot — say so | — | — |

Device fields:

| Profile field | Defender | Entra / Intune | SentinelOne | Falcon | Qualys |
|---|---|---|---|---|---|
| `hostname` / `fqdn` | `computerDnsName` | `displayName` | `computerName`, `domain` | `hostname`, `machine_domain` | `name`, `fqdn` |
| `os` | `osPlatform` `version` `osBuild` | `operatingSystem` `operatingSystemVersion` | `osName` `osRevision` | `os_product_name` `os_build` | `os` |
| `lastUser` | — | `username` (the literal `None` = empty) | `lastLoggedInUserName`, `adLastUserDN` | `last_login_user` | `lastLoggedOnUser` |
| `ips` | `lastIpAddress`, `lastExternalIpAddress` | — | `lastIpToMgmt`, `externalIp` | `local_ip`, `external_ip` | `address`, `agentConnectedFrom` |
| `join` | `isAadJoined`, `managedBy` | `trustType`, `isManaged`, `isCompliant`, `managementType` | `adComputerDN` | `machine_domain`, `ou` | — |
| `edr` health | `onboardingStatus`, `healthStatus`, `lastSeen` | — | `isActive`, `lastActiveDate`, `offSecond`, `isUpToDate`, `mitigationMode` | `status`, `provision_status`, `last_seen`, `reduced_functionality_mode` | `agentStatus`, `agentLastCheckedIn` |
| `risk` | `riskScore`, `exposureLevel`, `deviceValue` | — | `infected`, `activeThreats`, `appsVulnerabilityStatus` | `criticality` | `lastVulnScan` |
| `status` | `isExcluded`, `mergedIntoMachineId` | `accountEnabled`, `deletedDateTime` | `isDecommissioned`, `isUninstalled` | `status` (`contained`) | — |

Always fill `tablesChecked` with every table queried and `gaps` with every check that
could not run. A profile with an empty `gaps` list is a claim that nothing was missed.

## Traps

- **Absent is not false, and null is not absent.** In `gsuiteUser` the admin flags are
  only present when set, so a raw projection returns `null` for a normal user; the
  queries coalesce them. But a table whose shape on this account differs from the schema
  returns null for every field — and then a match query returns **zero rows**, which reads
  exactly like "not found". Step 2's readability probe is the defence; never skip it on
  an empty result. (Seen live: a `gsuiteGroup` table with 98 rows, every one with only
  `_key` populated.)
- **Never infer privilege from the absence of role events.** A search of the audit index
  for `Add member to role.` that finds nothing over 30 days means the role, if any, was
  granted before the window — directory roles are usually assigned at account creation
  and never touched again. The audit log answers *what changed*; this profile answers
  *what is*. Only the profile establishes privilege.
- **Not found is scoped.** `found: false` means "not in the directory tables of this
  account". The entity may be external (a personal Gmail, a partner's address), a
  service principal, or a user in a directory this account does not sync. Say which
  tables were checked; do not speculate beyond that.
- **Two agents can disagree, and both can be right.** SentinelOne's `networkStatus:
  connected` means *not isolated*; `isActive: false` means *not checked in recently*.
  Defender can report `Active` the same hour SentinelOne reports inactive — they sample at
  different times. Report each agent's own last-seen time rather than one merged "online".
- **Defender's two scores are different axes.** `riskScore` is active threat activity;
  `exposureLevel` is vulnerabilities and misconfiguration. Report both.
- **A device with no EDR row is a coverage gap, not a clean device.** If Entra knows the
  host and no EDR table does, say "no EDR record" in `gaps`.
- **Recovery contacts matter to the caller.** A personal recovery email or phone is how
  an account is taken over and how it is recovered; return them, the caller decides.
- **Roles the incident never mentions still count.** A Purview or compliance role next
  to Global Administrator changes what data the account could reach. Return the full
  role list, not just the admin flag.

## Verification status of the bundled queries

| Query | Verified |
|---|---|
| `gsuite_user.kql` | Parse-validated; run live on a Google Workspace tenant (primary address and alias both resolve). |
| `office365_user.kql` | Parse-validated against the `office365User` schema; same columns as incident-investigation's `user_registration.kql`. Not yet run in this skill's test. |
| `office365_group.kql` | Parse-validated; columns from the schema KB. |
| `gsuite_group.kql` | Parse-validated. On the test tenant every column except `_key` came back null; the readability probe reports it (98 rows, 0 readable) instead of "not a group". |
| `readability_probe.kql` | Run live: the unreadable `gsuiteGroup` (98 / 0), a readable `gsuiteUser` (143 / 143) and a readable `msDefenderMachine` (4311 / 4311). |
| `msdefender_machine.kql` | Parse-validated; run live — matched the short name against the FQDN. |
| `office365_device.kql` | Parse-validated; run live — matched the upper-case display name; `deviceId` joined to Defender's `aadDeviceId`. |
| `sentinelone_agent.kql` | Parse-validated; run live on the same host. |
| `falcon_agent.kql` | Parse-validated against the schema; not run live (no `falconAgent` table on the test account). |
| `qualys_host.kql` | Parse-validated against the schema; not run live. Every bracketed nested column is wrapped in `tostring()` — an untyped one sent the validator to a 500. |

## Assets

| Path | What it does |
|---|---|
| `assets/queries/gsuite_user.kql` | Google Workspace user by primary address, alias or id |
| `assets/queries/office365_user.kql` | Microsoft 365 user by UPN, mail or object id |
| `assets/queries/gsuite_group.kql` | Google Workspace group by email, alias, id or name |
| `assets/queries/office365_group.kql` | Microsoft 365 group by object id, mail or name |
| `assets/queries/msdefender_machine.kql` | Defender device by host, FQDN, MDE id or Entra device id |
| `assets/queries/office365_device.kql` | Entra / Intune device by host, deviceId or object id |
| `assets/queries/sentinelone_agent.kql` | SentinelOne agent by host, uuid or agent id |
| `assets/queries/falcon_agent.kql` | CrowdStrike Falcon host by host name or AID |
| `assets/queries/qualys_host.kql` | Qualys host by name, FQDN, NetBIOS name or IP |
| `assets/queries/readability_probe.kql` | Step 2.4: tells "not in this table" from "table unreadable" after an empty result |

Placeholder: `{ENTITY}` — the entity, lower-cased. Column definitions live in the
`ingext-kql` skill at `references/schemas/<Table>/info.yaml`.

## Related skills

- **`incident-investigation`** — calls this skill in step 1 for the subject and for any
  target account, group or device the incident touched.
- **`ingext-kql`** — any directory question beyond a single entity (e.g. "all admins
  without 2SV").
