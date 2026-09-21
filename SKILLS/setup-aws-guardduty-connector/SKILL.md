---
name: setup-aws-guardduty-connector
version: 1.0.0
description: >-
  End-to-end setup of the Amazon GuardDuty connector on Fluency / Ingext: poll GuardDuty findings
  from one or more AWS regions via an STS assume-role, with no access keys. Runbook: (1)
  get_account_podrole for the tenant pod role ARN; (2) run the IngextSaasPodRole CloudFormation
  template in the AWS account to create the trust-only assume-role; (3) run GuardDutyRole to attach
  the GuardDuty read policy to that same role — overriding its IAMRole default; (4) confirm a
  GuardDuty DETECTOR actually exists in every region you intend to poll, because the connector reads
  findings and cannot create them; (5) add_assumed_role plus test_assumed_role to register and prove
  the role; (6) create_connector to install Amazon GuardDuty with Regions and AWS Role. Triggers:
  "set up the GuardDuty connector", "import GuardDuty findings into Ingext", "connect Amazon
  GuardDuty", "GuardDuty findings in the datalake". Unlike the S3-notification connectors there is no
  bucket, no SQS queue and no prefix — GuardDuty is an API poll.
---

# Set up the Amazon GuardDuty Connector (API poll, assume-role, no keys)

Import GuardDuty findings into Fluency / Ingext. A platform plugin polls the GuardDuty API on a
schedule — `ListDetectors` → `GetDetector` → `ListFindings` → `GetFindings` — per region, using a
cross-account IAM role assumed from the tenant's pod identity. Findings land in the datalake index
named by the connector (default `GuardDuty`).

This is **not** an S3-notification connector. If you came here from
`setup-aws-cloudtrail-connector`, drop the mental model of buckets, prefixes and queues: there are
none. What replaces them is a requirement that has no analogue there — **GuardDuty has to be
enabled, per region, before there is anything to poll** (step 4).

> **You (Claude) cannot run the CloudFormation steps for the customer.** Steps 2 and 3 run in the
> AWS account being monitored, with their credentials. Your job is to fetch the tenant pod role ARN,
> hand over the exact templates and parameter values, then — once they report the stack outputs —
> drive the Fluency-side tools yourself. Steps 1, 5 and 6 are yours; 2, 3 and 4 are theirs.

## What this produces

| Item | Where | Created by |
|---|---|---|
| Trust-only assume-role (`ingextAssumeRole`) | Monitored AWS account | Step 2 template |
| Managed policy with GuardDuty read actions, attached to that role | Monitored AWS account | Step 3 template |
| An enabled GuardDuty detector per region | Monitored AWS account | Step 4 (**not** a template) |
| Registered **AWS Role** (assumed-role entry) | Fluency | Step 5 (`add_assumed_role`) |
| Installed **Amazon GuardDuty** connector | Fluency | Step 6 (`create_connector`) |
| Datalake index `GuardDuty` (schema `GuardDuty`) | Fluency | Created by the install itself — and it stays **empty**, see below |
| Findings as **resource dumps** (`GuarddutyFinding`) | Fluency | Written by the plugin on each poll |

## Tools you will use (Fluency side)

| Tool | `ingext` CLI equivalent | Purpose |
|------|------------------------|---------|
| `get_account_podrole` | `ingext eks get-pod-role` | The tenant's pod identity role ARN — the principal the customer role must trust |
| `list_assumed_role` | `ingext eks list-assumed-role` | Reuse an existing registration instead of adding a duplicate |
| `add_assumed_role` | `ingext eks add-assumed-role --name … --roleArn … [--externalId …]` | Register the role; its **displayName** becomes the connector's AWS Role |
| `platform_instancerole_add_local` | `ingext eks add-local-assumed-role --name … --roleArn …` | Register a role that **already exists**, bypassing saasmgr role management. The only way to register a role in the **hosting account** — see step 1 |
| `test_assumed_role` | `ingext eks test-assumed-role --roleArn …` | Prove Fluency can assume it, before installing |
| `list_connector_templates` | `ingext application list` | Live parameter names — the platform is the source of truth |
| `list_connectors` | `ingext integration list` | Check for an existing GuardDuty instance |
| `create_connector` | `ingext application install --app AmazonGuardDuty …` | Install it |

Templates, bundled in `assets/` and hosted publicly:

- `assets/IngextSaasPodRole.yaml` — https://fluency-cloudformation.s3.us-east-2.amazonaws.com/IngextSaasPodRole.yaml
- `assets/GuardDutyRole.yaml` — https://fluency-cloudformation.s3.us-east-2.amazonaws.com/GuardDutyRole.yaml

---

## Before you start — collect these inputs

- **AWS regions to poll** — one or more, e.g. `us-east-1`. **Required.** The connector takes a
  *list*, so one instance can cover several regions; see step 6 for how to pass it.
- **External ID** — optional STS external-id. If used it must be **identical** in steps 2, 3 and 5.
- **Datalake / index** — default `managed` / `GuardDuty`. Override only if the tenant separates
  findings from other AWS data.

Note there is no bucket and no prefix to gather. If someone hands you a bucket name for GuardDuty,
they are describing GuardDuty's S3 **export**, which is a different integration — use
`setup-aws-cloudtrail-connector`'s S3 flow with the GuardDuty connector instead.

---

## Step 1 — Get the tenant pod role ARN

Call `get_account_podrole`. It returns:

```json
{ "role": "<pod role name>", "arn": "arn:aws:iam::<accountId>:role/<pod role name>" }
```

That `arn` is the `PodRoleARN` the role in step 2 will trust — the one value tying the AWS account to
this specific Fluency tenant.

**You cannot use this flow to monitor the Fluency hosting account itself.** saasmgr refuses to
register any role whose ARN lives in the hosting account:

```
saasmgr /v1/accountAPI/register-assumerole: cannot manage roles in the hosting account
```

That is deliberate self-protection (`internal/api/handlers/account_api_handler.go`) — a tenant must
not be able to make the platform assume a role inside the provider's own AWS account. It applies
even when the "customer" is an internal audit tenant of that same account, which is exactly the case
where it bites. There is also no ambient-credentials fallback to work around it: the platform's
`getAuthInfo` requires one of accessKey, user or role and errors `missing access key, user or role`
when all three are empty, so attaching the GuardDuty policy directly to the tenant's pod role and
leaving auth blank does **not** work.

**Use the LOCAL registration instead.** `platform_instancerole_add_local` — exposed as
`ingext eks add-local-assumed-role`, and as `PlatformService.AddLocalAssumedRole` in the Go SDK —
records a role that **already exists** rather than asking saasmgr to manage one, so it does not pass
through the guard. Create the role yourself with the step-2 and step-3 templates, then register it
locally:

```bash
ingext eks add-local-assumed-role --name "<displayName>" --roleArn arn:aws:iam::<hostingAccount>:role/<role>
ingext eks test-assumed-role      --roleArn arn:aws:iam::<hostingAccount>:role/<role>
```

Proven end to end on the rockville audit tenant against a hand-created role in the hosting account:
registration returned a role id, `test-assumed-role` returned `OK`, and the connector polled
successfully. Everything else in this runbook is unchanged — only step 5's registration call differs.

For ordinary customer accounts use the normal `add_assumed_role`, and carry on with step 2.

---

## Step 2 — Create the trust-only assume-role (customer runs this)

Deploy **`IngextSaasPodRole.yaml`** in the monitored account. It creates a **trust-only** role — no
permissions — that the pod role can assume. Create it **once per account** and share it across every
Ingext AWS integration; step 3 attaches this integration's read policy to it.

| Parameter | Value | Notes |
|---|---|---|
| `IAMRole` | `ingextAssumeRole` (default) | **Remember it — steps 3 and 5 reuse it** |
| `PodRoleARN` | the `arn` from step 1 | Must match `^arn:aws:iam::[0-9]{12}:role/.+$` |
| `ExternalID` | your external id, or blank | If set, reuse the identical value in steps 3 and 5 |

```bash
aws cloudformation deploy \
  --template-file IngextSaasPodRole.yaml \
  --stack-name ingext-saas-podrole \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    IAMRole=ingextAssumeRole \
    PodRoleARN=arn:aws:iam::<tenantAccountId>:role/<podRoleName>
```

**Output to capture:** `RoleARN`. If the account already has `ingextAssumeRole` from another Ingext
integration, skip this step and reuse that ARN.

---

## Step 3 — Attach the GuardDuty read policy (customer runs this)

Deploy **`GuardDutyRole.yaml`** in the same account. It creates a managed policy granting
`guardduty:ListDetectors`, `GetDetector`, `ListFindings`, `GetFindings` on `*`, and attaches it to an
**existing** role.

> **Override the `IAMRole` default.** It ships as `fluencyplatform_instancerole`, which is the legacy
> on-prem EC2 instance role — wrong for a SaaS tenant. Set it to the role from step 2
> (`ingextAssumeRole`). Left at its default the stack either fails because no such role exists, or
> succeeds against an unrelated role and the connector then cannot read anything.

| Parameter | Value |
|---|---|
| `IAMRole` | `ingextAssumeRole` — **must match step 2, do not keep the default** |

```bash
aws cloudformation deploy \
  --template-file GuardDutyRole.yaml \
  --stack-name ingext-guardduty-policy \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides IAMRole=ingextAssumeRole
```

The policy is **region-independent** (`Resource: "*"`), so one deployment covers every region the
connector polls. Only one stack per account, however many regions.

The action list includes `guardduty:ListBucketMultipartUploads`, which is not a real GuardDuty
action — a copy-paste artifact in the hosted template. It grants nothing and breaks nothing; leave
it alone rather than forking the template.

---

## Step 4 — Confirm GuardDuty is actually enabled, in every region (customer runs this)

**This step has no analogue in the S3 connectors and it is the one that silently produces an empty
index.** The connector *reads* findings; it cannot enable GuardDuty. A region with no detector
returns no findings, and the poll succeeds — so nothing anywhere reports a problem.

For each region in your input list:

```bash
aws guardduty list-detectors --region <region>     # must return a DetectorId
```

If empty, GuardDuty is off in that region. Enabling it is the customer's decision, not a detail to
slip past them, because of three things:

- **It bills by volume analysed** — CloudTrail management events, VPC flow logs, DNS logs, and (if
  enabled) S3 data events and EKS audit logs. On a busy account the CloudTrail line alone is
  significant; flow-log GB is the usual surprise, and GuardDuty ingests flow logs from the VPC
  whether or not the account stores them.
- **A new detector enables `EBS_MALWARE_PROTECTION` by default.** It snapshots and scans EBS volumes
  on a finding. On a cluster with heavy node churn that is noisy and expensive. Read the config back
  with `get-detector` after creating one and disable the features you did not intend:

  ```bash
  aws guardduty update-detector --detector-id <id> \
    --features '[{"Name":"EBS_MALWARE_PROTECTION","Status":"DISABLED"}]' --region <region>
  ```

- **The 30-day free trial may already be spent**, and you cannot find out first:
  `get-remaining-free-trial-days` requires a detector id, so asking the question starts the meter.
  The trial is per account **per region**, so a region never used before may still have one. If the
  account previously enabled and removed GuardDuty, expect `0` days and immediate billing.

Ask the customer to confirm each region is enabled and to state which protection plans they want
before you continue. Set `FindingPublishingFrequency` to `FIFTEEN_MINUTES` if they want findings to
reach the datalake promptly; the default is six hours.

---

## Step 5 — Register the role with Fluency and prove it

`list_assumed_role` first, to avoid duplicates. Then `add_assumed_role`:

| Field | Value |
|---|---|
| `displayName` | Human-readable — **this exact string becomes the connector's AWS Role in step 6.** e.g. `guardduty-<account>` |
| `roleARN` | the `RoleARN` from step 2 |
| `externalID` | only if you used one; must match steps 2–3 exactly |
| `description` | optional, e.g. "GuardDuty findings for &lt;account&gt;" |

CLI: `ingext eks add-assumed-role --name guardduty-<account> --roleArn <arn>`

**Then `test_assumed_role` before installing.** A `status: true` is the definitive proof the trust
works; the connector's own failure mode is a silent empty index, so do not skip this. IAM
propagation can take a minute after the stack completes — retry once before concluding it is broken.

---

## Step 6 — Install the Amazon GuardDuty connector

1. `list_connector_templates` and match displayName **"Amazon GuardDuty"** (name `AmazonGuardDuty`).
   Read the live parameters — they are the source of truth, and this template has changed: it now
   offers `AWS_Role` alongside the older `IAM_AccessKey` / `IAM_AccessSecret`.
2. `list_connectors` — if a GuardDuty instance exists, confirm with the user before adding another.
3. `create_connector` with:

   | Parameter | Value |
   |---|---|
   | `Regions` | the region **list**, e.g. `["us-east-1"]` |
   | `AWS_Role` | the **displayName** from step 5 — not the id, not the ARN |
   | `IAM_AccessKey` / `IAM_AccessSecret` | **leave empty** — auth is mutually exclusive |
   | `datalake` | `managed` (default) |
   | `index` | `GuardDuty` (default) |

   The install creates the `GuardDuty` datalake index itself, against the built-in `GuardDuty`
   schema. Confirm that schema exists on the site (`ingext datalake list-schema`) if the install
   rejects the index.

**List encoding through the CLI.** `Regions` is a list, and the CLI takes it as a **JSON array in
the value**, not a bare region and not a comma-separated list:

```bash
ingext application install \
  --app AmazonGuardDuty --instance default --displayName "default" \
  --config Regions="[\"us-east-1\"]" \
  --config AWS_Role="guardduty-<account>"
```

`datalake` and `index` can be omitted to take their defaults (`managed` / `GuardDuty`). For several
regions, extend the array. Bear in mind `--config` parses `key=value` pairs with commas as pair
separators, so if a multi-element array does not round-trip, fall back to `create_connector` (which
takes a real JSON array) or install one instance per region — the latter also makes regions
independently removable.

---

## Verification

**Findings arrive as RESOURCES, not as datalake events.** This is the single most misleading thing
about this connector. The install creates a `GuardDuty` datalake index and the app declares a
DataSink, but the plugin writes each poll into the **resource store** as `GuarddutyFinding`. Measured
on 2026-09-19: one sample finding produced one resource hit and **zero rows in the index**. Querying
the index and concluding the connector is broken is the mistake this paragraph exists to prevent.

Read findings with a resource search:

```bash
ingext resource --resource-type GuarddutyFinding                    # all customers
ingext resource --resource-type GuarddutyFinding --customer <inst>  # one instance
```

**And do not verify by waiting for real findings.** A healthy GuardDuty in a quiet account produces
none for days, so silence proves nothing either way. Verify the pipeline instead:

1. `test_assumed_role` returned `status: true` (step 5).
2. Generate findings on purpose, in the monitored account:

   ```bash
   aws guardduty create-sample-findings --detector-id <id> \
     --finding-types Recon:EC2/PortProbeUnprotectedPort --region <region>
   ```

   Sample findings are real API objects and flow through the whole path, so they prove role,
   permissions, poll and sink in one shot. They are labelled as samples and are the intended way to
   test an integration.
3. Search the resource store after the next poll — `ingext resource --resource-type
   GuarddutyFinding` should return the sample findings, each carrying its `AccountId`, `Region`,
   detector ARN and finding `Type`.

4. If nothing arrives, read the account's `platform-0` log, which narrates the whole path and is the
   fastest way to tell which end failed:

   ```bash
   kubectl -n <account-namespace> logs platform-0 | grep -iE "guardduty|assume"
   ```

   A healthy poll looks like `Downloading public.ecr.aws/ingext/plugin_awsguardduty:latest`, then
   `Wrote N rows … GuarddutyFinding_allregions_<stamp>.parquet`, then `Added resource dump info`.
   A missing role or denied permission fails before the `Wrote` line.

---

## Failure modes

| Situation | Response |
|---|---|
| `GuardDuty` datalake index is empty | **Expected.** Findings go to the resource store, not the index. Use `ingext resource --resource-type GuarddutyFinding`. The index is created by the install and stays empty. |
| No findings in the resource store either, no errors anywhere | The usual cause is **no detector in the polled region** (step 4). `aws guardduty list-detectors --region <r>`; empty means GuardDuty is off there and the poll succeeds against nothing. Second cause: a quiet account with genuinely no findings — settle it with `create-sample-findings`. |
| `test_assumed_role` fails | Trust or external-id mismatch. The role's `PodRoleARN` must equal step 1's `arn`; an `ExternalID`, if used, must be identical in steps 2, 3 and 5. Allow a minute for IAM propagation and retry once. |
| Step 3 stack fails: role does not exist | `IAMRole` was left at the default `fluencyplatform_instancerole`, or step 2 created a different name. Re-run with `IAMRole` set to the step-2 role. |
| Poll returns AccessDenied | The GuardDuty policy is attached to a *different* role than the one registered. Check the policy's `Roles` list against the ARN in `list_assumed_role`. |
| `add_assumed_role` fails: "cannot manage roles in the hosting account" | The role ARN is in the Fluency hosting account, which saasmgr refuses by design. See step 1 — use an access key for that account, or read findings from a delegated administrator in a different account. Registering will never succeed for that ARN, so do not retry it. |
| Connector installed but its data source will not load: "unknown aws role" | The `AWS_Role` value does not match a registered role's displayName on this site. `list_assumed_role` and compare exactly — the install itself does not validate the name, so this surfaces later, at plugin load, not at install time. |
| Findings arrive hours late | `FindingPublishingFrequency` defaults to six hours. Set `FIFTEEN_MINUTES` on the detector. Note this affects updates to existing findings; new findings are available to the API sooner. |
| Unexpected GuardDuty bill | Almost always `EBS_MALWARE_PROTECTION` (on by default) or flow-log volume. `aws guardduty get-usage-statistics --usage-statistic-type SUM_BY_DATA_SOURCE` gives GuardDuty's own per-source cost — it returns an empty array for the first few hours after enabling, which is not an error. |
| Customer wants findings from many accounts | One connector instance per account, each with its own `ingextAssumeRole` and registered AWS Role. A GuardDuty *delegated administrator* aggregates findings across an Organization into one account — if they have that, poll the admin account alone. |
| Someone asks to use an access key instead | The template still accepts `IAM_AccessKey`/`IAM_AccessSecret`, but prefer the role: a long-lived key on the site is the thing this flow exists to avoid. |

---

## Layout

```
setup-aws-guardduty-connector/
├── SKILL.md
├── assets/
│   ├── IngextSaasPodRole.yaml   ← trust-only assume-role (step 2, shared across integrations)
│   └── GuardDutyRole.yaml       ← GuardDuty read policy attached to that role (step 3)
└── evals/
    └── evals.json               ← trigger phrases for skill selection
```
