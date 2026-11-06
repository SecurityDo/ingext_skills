# Methodology

## Data

The report reads the archive of the scheduled FPL report `GoogleWorkspace_Resource_Report`, one UTC day per archived run. Users, org units, domains,
groups and scores are a snapshot from the latest completed day; the audit activity is merged across all archived days (rules below). Each day carries the tables below, computed in the tenant from three sources: the `gsuiteUser` and `gsuiteGroup`
resource tables (the directory as it is when the run happens, with no history) and the `GSuite` stream table (one row per Google
Workspace audit activity) over the one day the run covers (`-1d@d` to `@d`). `asOf` is the end of the run window.

**Merge rules.** Counts add; one row per day is kept once with the latest run winning; event types sum; admin changes and suspicious sign-ins are unioned and deduplicated; accounts is the peak day, not a sum; the lists are lower bounds because each day keeps its top rows. Snapshot tables are never added. Days with no archive are gaps and are reported, not counted as zero.

| Table | Holds |
|---|---|
| `gw_summary` | one row: users, active, suspended, archived, admins, delegated admins, 2-Step Verification enrolled / enforced / gap, admins without it, never signed in, stale 30 / 90 days, no recovery info, outside the main domain, org units, status counts, groups, members, empty groups, sign-ins, failures, suspicious sign-ins, admin changes, app authorizations, events, accounts, window days |
| `gw_users` | up to 200 users, needing attention first: org unit, status, score, reasons, admin, delegated, suspended, archived, 2SV enrolled and enforced, recovery info, outside the main domain, created, last sign-in, days since sign-in |
| `gw_orgunits` | per org unit: users, admins, not enrolled, stale 90 days, needing action |
| `gw_domains` | per email domain: users, outside the main domain |
| `gw_groups` | up to 100 groups by direct members |
| `gw_daily` | per day: events, successful and failed sign-ins, suspicious, admin changes, app authorizations, mobile events |
| `gw_events` | per application, event type and name (top 100): events, accounts |
| `gw_admin`, `gw_suspicious` | the latest 100 admin changes and the latest 100 suspicious sign-ins |
| `sources` | one row per query with `ok` or `not available` and the error |

The summary counts are exact for any number of users; only the lists are capped.

## User score

Computed by the processor, for a user who is not suspended or archived. Higher is worse.

| Condition | Points |
|---|---|
| Admin or delegated admin, not enrolled in 2-Step Verification | 3 |
| 2-Step Verification enforced, user not enrolled (non-admin) | 2 |
| Not enrolled and not enforced (non-admin) | 1 |
| No sign-in for more than 90 days | 2 |
| No sign-in for more than 30 days (up to 90) | 1 |
| Never signed in, account older than 30 days | 2 |
| No recovery email and no recovery phone | 1 |
| Address in a domain other than the main domain | 1 |

3 or more is Needs action, 1 to 2 is Watch, 0 is Healthy. Suspended or archived users are Disabled with score 0 and are left out of the
2-Step Verification gap, stale, never signed in, recovery and outside-domain counts. A user who never signed in has a last sign-in of
1970 in Google; the processor reads that as never.

## Main domain and groups

The main domain is the email domain most users have; any other domain counts as outside it. Group member counts are Google's direct
member count; the report does not list members. Missing 2-Step Verification, suspended and archived flags are read as false.

## Audit counts

Sign-ins are `login` events (successful `login_success`, failed `login_failure`); suspicious ones are those with `is_suspicious` true.
Admin changes are `admin` application events other than alert center views. App authorizations are `token` `authorize` events.
