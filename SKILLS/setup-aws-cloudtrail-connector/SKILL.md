---
name: setup-aws-cloudtrail-connector
version: 1.0.0
description: >-
  End-to-end setup of the AWS CloudTrail connector on Fluency / Ingext: import CloudTrail events in
  real time from an existing customer S3 bucket (with optional object prefix). Wires an S3 "new
  object" notification into a new SQS queue, grants Ingext cross-account read access via an STS
  assume-role, registers the role, and installs the connector. Runbook: (1) get_account_podrole for
  the tenant pod role ARN; (2) run the IngextSaasPodRole CloudFormation template on the customer
  account to create the trust-only assume-role; (3) run IngextS3SqsNotification to create the SQS
  queue + S3 notification and attach the read policy; (4) add_assumed_role to register the role; (5)
  create_connector to install AWS CloudTrail with Region, SQS URL, and AWS Role. Triggers: "set up
  the AWS CloudTrail connector", "import CloudTrail from our S3 bucket in real time", "connect
  CloudTrail via SQS". Also fits other S3-notification imports (CloudWatch Logs S3, Fluent Bit S3,
  GuardDuty in S3) — swap the connector in step 5.
---

# Set up the AWS CloudTrail Connector (real-time import from S3 via SQS)

Wire an existing customer S3 bucket of CloudTrail events into Fluency / Ingext so events import
**in real time**. CloudTrail writes event archive objects to S3; the platform learns about each new
object through an **S3 "new object" notification → SQS queue**, then assumes a cross-account IAM
role to read the queue and download the objects.

Setting this up requires three things on the **customer's AWS account** and two on the **Fluency**
side:

1. An SQS queue that receives `s3:ObjectCreated:*` events for the bucket (and optional prefix).
2. An **S3 → SQS** notification on the bucket, pointed at that queue.
3. A cross-account **IAM assume-role** that Ingext's pod identity can assume, with read access to
   the queue and the bucket prefix.
4. Registering that role with Fluency (so it becomes a selectable **AWS Role**).
5. Installing the **AWS CloudTrail** connector, pointed at the region, the SQS URL, and the role.

> **You (Claude) cannot run the CloudFormation steps for the customer.** Steps 2 and 3 run in the
> customer's own AWS account (Console or `aws cloudformation`), with their credentials. Your job is
> to fetch the tenant pod role ARN, hand the customer the exact templates and parameter values, and
> then — once they report the stack outputs back — drive the Fluency-side tools (`add_assumed_role`,
> `create_connector`) yourself. Steps 1, 4, and 5 are yours; steps 2 and 3 are the customer's.

## What this produces

| Item | Where | Created by |
|---|---|---|
| SQS queue (`ingext-s3-notification`) | Customer AWS | Step 3 template |
| S3 → SQS `ObjectCreated` notification (append-only) | Customer AWS | Step 3 template |
| Trust-only assume-role (`ingextAssumeRole`) | Customer AWS | Step 2 template |
| Read policy on that role (SQS receive/delete + `s3:GetObject` on prefix) | Customer AWS | Step 3 template |
| Registered **AWS Role** (an assumed-role entry) | Fluency | Step 4 (`add_assumed_role`) |
| Installed **AWS CloudTrail** connector | Fluency | Step 5 (`create_connector`) |

## Tools you will use (Fluency side)

| Tool | Purpose |
|------|---------|
| `get_account_podrole` | Get this tenant's pod identity role ARN — the principal the customer role must trust |
| `add_assumed_role` | Register the customer's assume-role ARN with Fluency; returns an id, and its `displayName` becomes the connector's **AWS Role** |
| `test_assumed_role` | Verify Fluency can actually assume the role (STS GetCallerIdentity) before installing |
| `list_assumed_role` | List already-registered assumed roles (reuse / avoid duplicates) |
| `list_connector_templates` | Get the live CloudTrail template `name` and exact parameter names |
| `list_connectors` | Check whether a CloudTrail connector already exists |
| `create_connector` | Install the CloudTrail connector |

The two CloudFormation templates are bundled in `assets/` and also hosted publicly:

- `assets/IngextSaasPodRole.yaml` — https://fluency-cloudformation.s3.us-east-2.amazonaws.com/IngextSaasPodRole.yaml
- `assets/IngextS3SqsNotification.yaml` — https://fluency-cloudformation.s3.us-east-2.amazonaws.com/IngextS3SqsNotification.yaml

---

## Before you start — collect these inputs

Gather from the user (use `AskUserQuestion` if not already provided):

- **S3 bucket name** — the existing bucket CloudTrail writes to. **Required.**
- **S3 object prefix** — the folder within the bucket (e.g. `AWSLogs/123456789012/CloudTrail/`).
  Optional; scopes both the notification and the read grant. Leave empty for the whole bucket.
- **AWS region** — the region of the bucket / SQS queue (e.g. `us-east-1`). **Required** for the
  connector.
- **External ID** — optional STS external-id string. If you use one, it must be **identical** across
  steps 2, 3, and 4. Recommended for hardening but can be left blank.

Note the bucket must be a **standard S3 event source** the account owner controls (CloudFormation
appends the notification append-only, preserving any existing notifications on the bucket).

---

## Step 1 — Get the tenant pod role ARN

Call `get_account_podrole`. It returns:

```json
{ "role": "<pod role name>", "arn": "arn:aws:iam::<accountId>:role/<pod role name>" }
```

The **`arn`** is the `PodRoleARN` the customer's role will trust. Hand this ARN to the customer for
steps 2 and 3 — it is the single value that ties their account to this specific Fluency tenant.

---

## Step 2 — Create the trust-only assume-role (customer runs this)

Have the customer deploy **`IngextSaasPodRole.yaml`** in **their** AWS account, in the bucket's
region. This creates a **trust-only** role (no permissions yet) that the pod role can assume. It is
meant to be created **once per account** and shared across every AWS integration; step 3 (and future
integrations) attach their own read policies to it.

Parameters:

| Parameter | Value | Notes |
|---|---|---|
| `IAMRole` | `ingextAssumeRole` (default) | The shared role name. **Remember it — step 3 and step 4 reuse it.** |
| `PodRoleARN` | the `arn` from step 1 | Must match `^arn:aws:iam::[0-9]{12}:role/.+$` |
| `ExternalID` | your external id, or leave blank | If set, reuse the exact same value in steps 3 and 4 |

Console: **CloudFormation → Create stack → Upload template** (`IngextSaasPodRole.yaml`), fill the
parameters, create. Or CLI:

```bash
aws cloudformation deploy \
  --template-file IngextSaasPodRole.yaml \
  --stack-name ingext-saas-podrole \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    IAMRole=ingextAssumeRole \
    PodRoleARN=arn:aws:iam::<tenantAccountId>:role/<podRoleName> \
    ExternalID=<optional>
```

**Output to capture:** `RoleARN` — the ARN of `ingextAssumeRole`. You'll register this in step 4.

---

## Step 3 — Create the SQS queue + S3 notification and attach the read policy (customer runs this)

Have the customer deploy **`IngextS3SqsNotification.yaml`** in the **same account and region**. This
template creates the SQS queue, appends the S3 → SQS `ObjectCreated` notification to the bucket, and
attaches the read policy (SQS receive/delete + `s3:GetObject` on the prefix).

> **Critical:** to attach the policy to the role from step 2 (rather than creating a second role),
> **leave `PodRoleARN` empty**. When `PodRoleARN` is empty the template runs in "attach to existing
> role" mode and adds the read policy to the role named by `IAMRole`, which **must already exist**
> (it does, from step 2). Both templates now default `IAMRole` to **`ingextAssumeRole`**, so if you
> kept the default in step 2 you can leave `IAMRole` at its default here — just make sure it matches
> the role step 2 actually created.

Parameters:

| Parameter | Value | Notes |
|---|---|---|
| `S3Bucket` | the existing bucket name | **Required** |
| `S3BucketPrefix` | the prefix, or leave blank | Scopes notification + `s3:GetObject` |
| `SQSQueueName` | `ingext-s3-notification` (default) | Fine to keep; use a distinct name if the account has other Ingext queues |
| `PodRoleARN` | **empty** | Empty ⇒ attach policy to the existing `IAMRole` instead of creating a new role |
| `IAMRole` | `ingextAssumeRole` (default) | **Must match the step-2 role** and already exist; the default matches step 2's default |
| `ExternalID` | same as step 2, or blank | Only relevant if the role were being created here; keep consistent |

```bash
aws cloudformation deploy \
  --template-file IngextS3SqsNotification.yaml \
  --stack-name ingext-s3sqs-cloudtrail \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    S3Bucket=<bucket-name> \
    S3BucketPrefix=<prefix-or-empty> \
    SQSQueueName=ingext-s3-notification \
    PodRoleARN= \
    IAMRole=ingextAssumeRole
```

**Outputs to capture:**
- `QueueURL` — the SQS queue URL → this is the connector's **SQS URL** in step 5.
- `QueueARN` — the queue ARN (informational).
- `RoleARN` — resolves to the `ingextAssumeRole` ARN (same as step 2's output).

### Single-template shortcut (optional)

`IngextS3SqsNotification.yaml` can do everything **on its own** if you set `PodRoleARN` to the pod
role ARN (instead of leaving it empty). In that mode it *creates* the role named by `IAMRole`
(default `ingextAssumeRole`), attaches the read policy, and trusts the pod role — so you skip step 2
entirely. Use the two-template flow above when the account will host **multiple** AWS integrations
sharing one `ingextAssumeRole`; use the shortcut for a one-off single-bucket setup. (If you take the
shortcut, do **not** also run step 2 with the same `IAMRole` — both would try to create the same
role and the second stack fails with "role already exists.")

---

## Step 4 — Register the role with Fluency

Now register the customer's assume-role ARN so it becomes a selectable **AWS Role**. First check for
an existing registration with `list_assumed_role` (avoid duplicates). Then call `add_assumed_role`:

| Field | Value |
|---|---|
| `displayName` | A clear, human-readable name — **this exact string becomes the connector's AWS Role in step 5.** e.g. `cloudtrail-<customer>` or the account/bucket name |
| `roleARN` | the `RoleARN` from step 2/3 (the `ingextAssumeRole` ARN) |
| `externalID` | the external id from steps 2–3, **only if you used one** (must match exactly) |
| `description` | optional free text (e.g. "CloudTrail S3 import for &lt;customer&gt;") |

`add_assumed_role` returns `{ "id": "role_xxxxxxxxxx" }`.

**Verify before installing:** call `test_assumed_role` with `names: ["<the displayName>"]`. Each
result reports `status: true` on a successful STS assume. If it fails, the trust relationship or
external id is wrong — recheck step 2's `PodRoleARN`/`ExternalID` against step 1 and step 4 before
proceeding. (IAM propagation can take a minute right after the stack finishes; retry once.)

---

## Step 5 — Install the AWS CloudTrail connector

1. Call `list_connector_templates` and match the CloudTrail template (displayName **"AWS
   CloudTrail"**, name typically `AWSCloudTrail` or `CloudTrail`). **Use the live template** for the
   exact parameter names — do not trust names from memory; the platform is the source of truth.
2. Call `list_connectors`; if a CloudTrail connector already exists, tell the user and confirm before
   adding a second instance.
3. Call `create_connector`. Provide the auth as **AWS Role** (the role you just registered) and
   include the full parameter set the template defines. The three values that matter here:

   | Template parameter (match live name) | Value |
   |---|---|
   | `Region` | the AWS region from your inputs (e.g. `us-east-1`) |
   | SQS URL (`SQS-URL` / `SQS_URL`) | the `QueueURL` output from step 3 |
   | AWS Role (`AWS-Role` / `AWS_Role`) | the **`displayName`** you registered in step 4 (NOT the id, NOT the ARN) |

   Auth is a mutually exclusive group — because you're using the registered role, set only the **AWS
   Role** parameter and leave `AWS-User`, `IAM-AccessKey`, `IAM-AccessSecret` empty. Follow the
   `add-connector` skill's conventions for deriving the instance id / display name and for including
   **every** template parameter (defaulted/optional ones with their default or an empty string).

On success, confirm the instance id and note that events begin importing as CloudTrail writes new
objects and S3 notifies the queue.

---

## Verification

- **`test_assumed_role`** returned `status: true` for the registered role (the definitive check that
  the cross-account trust works).
- **SQS is receiving events:** in the customer's AWS console, the queue's *Messages available* /
  *NumberOfMessagesSent* metric rises as CloudTrail delivers new objects (CloudTrail batches roughly
  every ~5 minutes). If the queue stays empty, the S3 → SQS notification or its prefix filter is
  wrong (see Failure modes).
- **Connector installed:** `list_connectors` shows the new CloudTrail instance; events land in the
  datalake shortly after the queue starts draining.

---

## Failure modes

| Situation | Response |
|---|---|
| `test_assumed_role` fails / connector can't assume the role | Trust or external id mismatch. The customer role's `PodRoleARN` (step 2) must equal step 1's `arn`; if an `ExternalID` is used it must be identical in steps 2, 3, and 4. Also allow ~1 min for IAM propagation, then retry. |
| Step 3 stack fails: "role `ingextAssumeRole` does not exist" | Step 2 wasn't run (or used a different `IAMRole` name). Run step 2 first, or set `IAMRole` in step 3 to whatever step 2 actually created. |
| Step 3 stack fails: "role `ingextAssumeRole` already exists" | `PodRoleARN` was left set in step 3, triggering create-role mode against a role step 2 already created. Re-run step 3 with `PodRoleARN` **empty** so it attaches the policy to the existing role instead of recreating it. |
| SQS queue stays empty | The S3 notification prefix doesn't match where CloudTrail writes, or notifications aren't reaching the queue. Verify `S3BucketPrefix` against actual object keys (e.g. `AWSLogs/<acct>/CloudTrail/`), and that the bucket's notification config lists the `ingext-…` queue entry. |
| `s3:GetObject` access denied on download | The prefix in step 3 doesn't cover the objects. The read grant is `s3:GetObject` on `arn:aws:s3:::<bucket>/<prefix>*`; widen or correct `S3BucketPrefix`. |
| CloudFormation "requires capabilities: [CAPABILITY_NAMED_IAM]" | Both templates create named IAM resources. Add `--capabilities CAPABILITY_NAMED_IAM` (CLI) or check the acknowledgement box (Console). |
| Connector template not found | Call `list_connector_templates` and match on displayName "AWS CloudTrail"; the internal `name` may be `AWSCloudTrail` or `CloudTrail` depending on platform version. |
| Bucket already has notifications you don't want disturbed | The step 3 Lambda merges append-only, keyed by `Id` (`ingext-<queue>`), preserving existing notifications. It only manages its own entry. |

---

## Reusing this for other S3-notification sources

The steps 1–4 plumbing (pod role → assume-role → SQS + notification → register) is identical for
other S3-delivered sources. To onboard **AWS CloudWatch Logs (S3)**, **Fluent Bit (S3)**, or
**GuardDuty findings in S3**, run the same four steps against the relevant bucket, then in step 5
install that connector's template instead of CloudTrail — passing the same **SQS URL** and **AWS
Role**. One shared `ingextAssumeRole` can back several integrations; each `IngextS3SqsNotification`
run adds another queue + read policy to it.

---

## Layout

```
setup-aws-cloudtrail-connector/
├── SKILL.md
├── assets/
│   ├── IngextSaasPodRole.yaml          ← trust-only assume-role (step 2)
│   └── IngextS3SqsNotification.yaml    ← SQS + S3 notification + read policy (step 3)
└── evals/
    └── evals.json                       ← trigger phrases for skill selection
```
