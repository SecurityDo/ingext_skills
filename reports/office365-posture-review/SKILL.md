---
name: office365-posture-review
version: 1.0.0
description: >-
  Review the Office 365 / Entra resource posture of ONE Fluency / Ingext tenant from its resource
  dumps (office365User, office365Application, office365Device) and render an HTML findings page plus
  a CSV: privileged users, weak MFA factors, OAuth-connected users, stale token baselines, password
  policy None; apps with HTTP redirects, implicit grant, no verified publisher or no credentials, and
  long-lived risky apps; devices that are rooted, non-compliant, unmanaged, weakly trusted, stale,
  stale in hybrid sync or without a username. USE THIS SKILL for "Office 365 posture review",
  "Microsoft 365 configuration review", "Entra hygiene", "what O365 misconfigurations do we have",
  "app registration review", "device registration review". Read-only; uses no FPL report and no event
  query. DO NOT use it for activity questions (failed logins, mailbox activity, impossible travel):
  use office-user-investigation or azure-user-signin-investigation.
---

# Office 365 Posture Review

Turns the tenant's Office 365 inventory snapshots into a ranked list of identity, application and
device hygiene findings. It is resource posture, not activity: it never says a risk was exploited.
Read-only; nothing is changed in the tenant.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names. Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. |
| Focus | `users`, `applications`, `devices` or all (default all). |

## Step 1 — Collect

Make a work folder **outside the repository** (the dumps name real users and devices).

1. `list_resource_dumps(account)`; save the result as `WORKDIR/resources.json`.
2. For each of `office365User`, `office365Application`, `office365Device` that is listed, and for each
   customer (feed) it lists, call `get_resource_dump_url(account, resource, customer)` and download with
   `curl -sf -o` (the link expires in 15 minutes; never read it into the conversation). Name the files
   `users__<customer>.jsonl.gz`, `apps__<customer>.jsonl.gz`, `devices__<customer>.jsonl.gz`.
3. A resource that is not listed is absent: skip it, the report shows it as "No dump".
4. Check each file's record count against the `count` that `list_resource_dumps` reported; a mismatch
   is a truncated download. The script warns.

An account can have more than one Office 365 feed (customer name). Each feed is assessed on its own and
never summed with another, because two feeds may describe the same tenant.

## Step 2 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --out WORKDIR/posture.html \
  --csv WORKDIR/findings.csv --tenant "Example Corp" --site Develop
```

## Reading the result

| Severity | Finding patterns |
|---|---|
| Critical | rooted or jailbroken device; app older than 730 days that still has implicit grant or an HTTP redirect |
| High | privileged roles (more than 2, plus 1 per 500 employees); implicit grant; HTTP redirect URI; unmanaged or non-compliant device |
| Medium | weak MFA factors; OAuth consent queue; HTTP homepage; no verified publisher; Workplace trust; stale hybrid sync; stale token baseline |
| Low | password policy None; apps with no credentials; stale sign-ins; no username |

- Lead with the non-zero findings; name only the top rows. The page also states **compound risk**: a
  privileged account that also has weak MFA, a stale token baseline or password policy None.
- A check whose field is absent from the dump shows **n/a** with "FIELD NOT IN DUMP", never zero.
- Weak MFA means email or SMS registered. Dumps carry `mobilePhone` and `email`, and the check ignores
  case and underscores. MFA registration is not MFA enforcement.
- No verified publisher means `verifiedPublisher` has neither an id nor a display name; the dump holds an
  empty object for unverified apps, so a plain "is it set" test would never fire.
- Some findings are expected: service or federated accounts (password policy None), public-client apps
  (no credentials), long-idle devices. Ask the operator to confirm purpose; do not call them failures.

## Honesty rules

- Counts are as of the dump time, not a time window; say so. Preserve counts exactly.
- A tenant with no Office 365 dump is a coverage gap, not a clean result.
- Never write "compromised", "compliant" or "secure" from these counts. Escalate to the activity tools
  when the operator asks whether a risk was used.
- The output names users, devices and apps. Keep it out of the repository and out of release notes.
