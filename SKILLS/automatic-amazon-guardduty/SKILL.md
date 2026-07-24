---
name: automatic-amazon-guardduty
version: 1.0.0
description: >-
  Automatic variant for importing Amazon GuardDuty findings into Fluency / Ingext. On the AWS
  side it creates, per AWS documentation, a least-privilege IAM user (default
  ingext-guardduty) with the AWS managed AmazonGuardDutyReadOnlyAccess policy attached and
  issues the access key pair the connector polls with — GuardDuty itself must ALREADY be
  enabled in the chosen regions (enabling it starts billing; this skill never enables it). On
  the Fluency side it creates (or guides creating) an "Amazon GuardDuty" connector
  (AmazonGuardDuty) with that key pair and the region list. MODE A — the operator has IAM-admin
  rights in the target account and the aws CLI signed in on this machine, so cowork runs the
  bundled bash script directly (aws CLI only — no PowerShell variant; the aws CLI is
  cross-platform, see the deviation note); MODE B — a fallback that guides a third-party admin
  who runs the script or an IAM-console walkthrough in their own account. SELF-CONTAINED like
  setup-aws-cloudtrail-connector: it finishes by creating the AmazonGuardDuty connector itself,
  so customer-onboarding must NOT chain into add-connector afterward. Triggers: "import
  GuardDuty findings into Ingext", "connect Amazon GuardDuty to Fluency", "set up the GuardDuty
  connector", "get GuardDuty alerts into the datalake", "create the ingext guardduty IAM user".
  Do NOT use for AWS CloudTrail events — that's setup-aws-cloudtrail-connector; if GuardDuty
  findings are already exported to an S3 bucket, prefer the S3/SQS CloudTrail-style plumbing
  route instead of API polling; and not for generic connector creation with an existing working
  key pair — add-connector also handles that.
---

# Import Amazon GuardDuty findings into Ingext — automatically (aws CLI)

Set up the pipeline that lets Fluency / Ingext import **Amazon GuardDuty** findings:

- **AWS side** — a least-privilege **IAM user** (no console access) with the AWS managed
  **`AmazonGuardDutyReadOnlyAccess`** policy attached, and one **access key pair**. That key
  pair is the only thing the connector needs from AWS — unlike `AWSCloudTrail`, this template
  has **no `AWS_Role` / `AWS_User` option**; an IAM access key pair is the only auth.
- **Fluency / Ingext side** — an **Amazon GuardDuty** connector (template `AmazonGuardDuty`)
  with the key pair and the list of regions to poll.

One script is bundled for the AWS side: `assets/setup-ingext-guardduty.sh` (bash + aws CLI).
It is idempotent for the user and policy attachment, and prints one JSON object. **cowork runs
it for the operator** instead of handing them instructions — the operator only completes the
AWS sign-in.

> **Scope note — GuardDuty must already be on.** This skill imports findings from a GuardDuty
> that is **already enabled** (a detector exists) in each chosen region. Enabling GuardDuty
> starts a 30-day free trial and then **billing**, so that decision belongs to the customer —
> the skill checks and asks, but never enables it.

Every AWS-side claim below is backed by AWS documentation; citations live in
`assets/references.md`.

## What this creates

| Side | Item | Detail |
|---|---|---|
| AWS | IAM user | Default `ingext-guardduty` — programmatic only, no console access, no password |
| AWS | Policy attachment | AWS managed **`AmazonGuardDutyReadOnlyAccess`** (`arn:aws:iam::aws:policy/AmazonGuardDutyReadOnlyAccess`) — GuardDuty `Get*` / `List*` / `Describe*` only |
| AWS | Access key | One key pair for that user; the secret is shown **once** at creation. AWS allows at most **two** keys per user |
| Ingext | Connector | Template `AmazonGuardDuty` ("Amazon GuardDuty"): `Regions` (list), `IAM_AccessKey`, `IAM_AccessSecret` |

**Nothing this skill creates is billable** (IAM users, policy attachments, and access keys are
free). GuardDuty itself bills per region once enabled — this skill does not touch that switch.

---

## Prerequisites

- **GuardDuty already enabled** in every region the connector will poll. GuardDuty is a
  regional service — each region has its own detector. Confirm with the operator, or in Mode A
  check directly: `aws guardduty list-detectors --region <r>` (empty result = not enabled
  there). If it isn't enabled, stop and let the customer decide — enabling starts the free
  trial and then billing.
- **Mode A toolchain:** the **AWS CLI** (`aws --version` succeeds) on this machine, signed in
  to the target account (`aws configure`, `aws sso login`, or environment variables). The
  signed-in identity needs IAM admin rights: `iam:CreateUser`, `iam:GetUser`,
  `iam:AttachUserPolicy`, `iam:ListAttachedUserPolicies`, `iam:CreateAccessKey`,
  `iam:ListAccessKeys` (plus `guardduty:ListDetectors` for the region check).
- To have cowork also create the Ingext connector: the **Fluency Ingext MCP** connected for
  the target Ingext instance. Without it, the operator pastes the values into the Fluency UI.

> **Why bash-only, unlike the Event Hubs skill (deviation note):** the Azure sibling ships an
> `az`/bash script *and* a PowerShell variant because Windows Azure admins commonly have only
> PowerShell + Az modules. The AWS CLI is a single cross-platform tool (Linux, macOS, Windows),
> so one bash script covers Mode A everywhere cowork runs; a Windows-only third-party admin in
> Mode B can run it under WSL/Git Bash or use the console walkthrough instead.

---

## Pick a mode

**Ask who is at the keyboard** (use `AskUserQuestion` if it isn't already clear):

- **Mode A — "I have IAM-admin rights in the target account and want cowork to run it."**
  cowork executes the bundled script on this machine against the account the operator signs in
  to. This is the primary path — the setup is performed on the operator's behalf.
- **Mode B — "The AWS account belongs to someone else / another admin will run it."** cowork
  does **not** run anything against that account (it has no credentials there). Hand the admin
  the script or the IAM-console walkthrough and collect the key pair they report back.

> **Why the distinction matters:** creating IAM principals requires credentials for the
> *target* account. In Mode A the sign-in happens on this machine, so cowork can drive it. In
> Mode B the account belongs to someone else — cowork's role is to guide.

---

## Mode A — cowork runs the setup script (primary)

Precondition: the operator has IAM-admin rights in the target account and this machine has (or
can complete) a working AWS sign-in.

**Run the script for the operator — don't hand them instructions.** The only thing they must
do themselves is complete the sign-in if the CLI isn't authenticated yet. **Assume they will
authenticate**; don't stop to ask permission to run the script. cowork's normal per-command
approval already governs what runs, and the script is idempotent — safe to re-run.

### A1 — Preflight the sign-in

Run `aws sts get-caller-identity`. If it errors, have the operator sign in
(`aws configure` for keys, `aws sso login` for IAM Identity Center), then re-run it. **Read
back the `Account` id and caller `Arn`** so the operator confirms it is the intended account
before anything is created. The script re-checks and re-prints both anyway.

### A2 — Collect the regions and confirm GuardDuty is on

Ask which regions to poll — the template's snapshot enum: `us-east-1`, `us-east-2`,
`us-west-1`, `us-west-2`, `ca-central-1`, `af-south-1`, `eu-central-1`, `eu-west-1`,
`eu-west-2`, `eu-west-3`, `eu-north-1` (re-check against the live template in the install
step; the connector polls each listed region). Then verify a detector exists in each:

```bash
aws guardduty list-detectors --region us-east-1
```

An empty `DetectorIds` list means GuardDuty is **not** enabled there — surface that to the
operator and drop the region (or pause while the customer decides about enabling; never
enable it yourself).

### A3 — Run the bundled script

```bash
bash ${SKILL_DIR}/assets/setup-ingext-guardduty.sh --check-regions us-east-1,us-west-2
# optional overrides:
bash ${SKILL_DIR}/assets/setup-ingext-guardduty.sh --user-name my-ingext-user
```

The script **stops for a confirmation prompt** (showing the account id, the caller ARN, the
IAM user, and the policy it is about to attach) unless run with `--yes`. Surface that prompt
to the operator; only pass `--yes` if the operator has explicitly approved the target account.

What the script does, in order: preflight (`aws` present, `aws sts get-caller-identity`
succeeds) → print account id + caller ARN → warn per `--check-regions` region with no
GuardDuty detector (never enables it) → confirm → create/reuse the IAM user → attach/reuse
`AmazonGuardDutyReadOnlyAccess` → create one access key, **erroring clearly if the user
already has two keys** (the AWS maximum) with rotation instructions instead of failing
silently → print the JSON.

### A4 — Capture the output

The script writes **only** the JSON to stdout (progress on stderr):

```json
{
  "accessKeyId": "AKIA…",
  "secretAccessKey": "…",
  "userName": "ingext-guardduty",
  "accountId": "123456789012"
}
```

That JSON **is the credential hand-off**: feed `accessKeyId` / `secretAccessKey` straight into
the connector step and **do not re-echo them** into chat, summaries, or logs — refer to them
as "the access key from the setup script". The secret is shown once; AWS cannot re-display it
(if lost, delete the key and re-run the script for a new one).

---

## Mode B — guide a third-party admin (fallback)

cowork cannot reach the customer's account. Offer the admin either path; the deliverable is
the same four values (`accessKeyId`, `secretAccessKey`, `userName`, `accountId`) plus the
region list, with the secret handled as a credential.

### Path B1 — the script (recommended)

Give the admin `${SKILL_DIR}/assets/setup-ingext-guardduty.sh` (or paste its contents). Tell
them to:

1. Install the AWS CLI if needed and sign in as an IAM admin of the intended account.
2. Run `bash setup-ingext-guardduty.sh --check-regions <r1>,<r2>` and answer the confirmation
   prompt (it names the account before creating anything).
3. Send back the printed JSON — treating `secretAccessKey` as a secret (password manager or
   other secure channel, not email/ticket).

(Windows admins: the script is bash — run it under WSL or Git Bash, or use Path B2.)

### Path B2 — manual IAM console walkthrough

Direct the admin through **https://console.aws.amazon.com/iam/**, following AWS's documented
flow (citations in `assets/references.md`):

1. **Create the user.** **Users → Create user.** On **Specify user details**, name it
   **`ingext-guardduty`** and do **not** enable console access (leave the AWS Management
   Console access option unchecked — this integration is programmatic only). **Next**.
2. **Attach the read-only policy.** On the **Set permissions** page choose **Attach policies
   directly**, search for **`AmazonGuardDutyReadOnlyAccess`**, select it, **Next**, then
   **Create user**.
3. **Create the access key.** Open the user → **Security credentials** tab → **Access keys**
   section → **Create access key**. (If the button is deactivated, the user already has two
   keys — delete one first.) On the **Access key best practices & alternatives** page choose
   **Other**, then **Next**; the description tag is optional; **Create access key**.
4. **Copy both values.** On the **Retrieve access key** page choose **Show** (or **Download
   .csv file**). **This is the only time AWS displays the secret** — it cannot be recovered
   later; a lost secret means delete the key and create a new one.
5. **Confirm GuardDuty is enabled** in each region to be polled: GuardDuty console (per
   region) — an enabled region shows findings/settings; a disabled one shows the enablement
   page (do not enable it just for this — that is the account owner's billing decision).
   Report back which regions are enabled, plus the account id.

---

## Ingext side — create the "Amazon GuardDuty" connector

With the key pair in hand, finish the integration on the Fluency / Ingext side. **If the
Fluency Ingext MCP is connected, do this for the operator too:**

1. Call `list_connector_templates` and locate the **`AmazonGuardDuty`** template (display name
   "Amazon GuardDuty") to confirm its **live** parameter schema — the names below are a
   snapshot, not truth.
2. Call `list_connectors` — if an AmazonGuardDuty connector already exists, show its instance
   and state and confirm before adding a second one.
3. Call `create_connector` with:
   - `application`: `AmazonGuardDuty`
   - `instance`: `amazonguardduty` (lowercase from the template name, ≤20 chars, **never
     `"default"`**; `-2` suffix on collision)
   - `displayName`: `Amazon GuardDuty`
   - `inputParameters`: **every** parameter the live template defines — snapshot: `Regions`
     (the operator's chosen region list; the template marks it `isList`), `IAM_AccessKey` and
     `IAM_AccessSecret` (sensitive) from the script output. The snapshot exposes **no
     `datalake`/`index` parameter** — the destination table is platform-assigned; if the live
     template has grown one, apply the usual user-value → default → `""` rule.
4. Verify with `list_connectors` / `get_connector` that the instance exists and reports
   healthy.

**Without the MCP**, walk the operator through the Fluency UI: **Connectors / Integrations →
Add → Amazon GuardDuty**, pick the regions, paste the access key id and secret, save.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — connector included.** Like
  `setup-aws-cloudtrail-connector` and the Event Hubs sibling, it ends in `create_connector`
  itself. **Do not hand off to `add-connector`** — run the Ingext-side section above before
  returning.
- **Don't re-collect what the router already established** (connected instance, existing
  connectors from its `list_connectors` call). Go straight to picking the mode.
- **If the customer already has a working key pair** for a suitably-permissioned IAM
  principal, skip the AWS-side provisioning and jump to the Ingext-side section.
- **Hand back to the router:** the connector `instance` id, the region list, the IAM user
  name + account id, and the datalake table — the template exposes no index parameter, so
  **confirm the live table name with `list_data_tables`** after install rather than guessing.
  Do **not** echo the access key or secret into the summary — refer to "the access key from
  the setup script".
- **Set verification expectations honestly:** the connector polls the GuardDuty API. Where
  findings exist, expect first rows within roughly **minutes to ~30 minutes**. A quiet,
  healthy account may genuinely produce **zero findings — zero rows is not failure**: mark ⏳,
  and offer the sample-findings smoke test below for a deterministic check.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse. **No credentials in this
block** — the key pair lives only in the script's own output and the `create_connector` call:

```json
{
  "connector": "AmazonGuardDuty",
  "instance": "amazonguardduty",
  "regions": ["us-east-1", "us-west-2"],
  "iamUser": "ingext-guardduty",
  "accountId": "123456789012",
  "datalakeTable": "<confirm live with list_data_tables>"
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **Confirm the live table name with `list_data_tables`** (the template has no index
   parameter), then count rows over the last hour via the **`ingext-kql`** skill. A plain row
   count is the smoke test.
3. **Quiet account?** GuardDuty only emits findings when it detects something — zero rows can
   be correct. For a deterministic test, have the customer generate **sample findings**
   (documented by AWS): GuardDuty console → **Settings** → under **Sample findings** choose
   **Generate sample findings**, or:

   ```bash
   aws guardduty create-sample-findings --detector-id <detectorId> --region <r>
   ```

   (Find the `detectorId` on the Settings page or via `aws guardduty list-detectors`.) Sample
   findings are placeholders titled **[SAMPLE]** with `"sample": true` in their JSON — easy to
   spot in the datalake and archive afterwards.
4. Honest latency: allow the minutes-to-~30-minute polling window (plus GuardDuty's own
   detection delay for real findings) before moving to Failure modes.

---

## Failure modes

| Situation | Response |
|---|---|
| `aws sts get-caller-identity` fails | Not signed in. `aws configure` / `aws sso login`, confirm the account id read-back, re-run. |
| `aws` not installed | Install the AWS CLI (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) or fall back to Mode B. |
| `AccessDenied` on `iam:CreateUser` / `iam:AttachUserPolicy` / `iam:CreateAccessKey` | The signed-in identity lacks IAM admin rights. Have an IAM admin run it (Mode B) or grant the missing permissions. |
| Script errors: user already has two access keys | The AWS per-user maximum. The script prints the existing keys and rotation steps (`get-access-key-last-used` → `update-access-key --status Inactive` → `delete-access-key`) — clean up one key, then re-run. Do not create a parallel user to dodge rotation. |
| `--check-regions` warns "no GuardDuty detector" | GuardDuty isn't enabled in that region. Drop the region or let the customer enable GuardDuty themselves (billable) — never enable it for them. |
| Connector errors with invalid credentials | Key mistyped, deactivated, or deleted; or the user was deleted. Re-check in IAM → Users → `ingext-guardduty` → Security credentials; create a fresh key and update the connector. |
| Connector healthy but zero rows | Expected in a quiet account, and expected for any region where GuardDuty is off. Generate sample findings (Verification §3) to prove the pipe, and re-check the region list matches where detectors exist. |
| Secret lost before it reached the connector | Not recoverable from AWS. Delete that key and re-run the script (or console step 3) for a new pair. |
| An AmazonGuardDuty connector already exists | Ask before adding a second instance (`amazonguardduty-2`); two instances polling the same account/regions duplicate rows for no benefit. |
| Template renamed / schema drift | The install step reads the live `list_connector_templates` — follow the live schema, not this file's snapshot. |
| Resources already exist | Expected on re-runs — the script reuses the user and policy attachment. Note each successful run mints a **new** access key (secrets are not re-fetchable); delete superseded keys. |

---

## Security notes

- **Least privilege by construction:** the user carries only the AWS managed
  `AmazonGuardDutyReadOnlyAccess` policy — GuardDuty `Get*`/`List*`/`Describe*` (plus
  read-only Organizations lookups per AWS's policy description). It cannot write to GuardDuty
  or touch any other service. Never substitute a broader policy for convenience.
- **The key pair is a long-lived credential.** Pass it into `create_connector` and nowhere
  else — never into logs, tickets, summaries, or persistent chat. AWS shows the secret once;
  treat the script's JSON as the single hand-off.
- **Rotation:** create a new key for `ingext-guardduty` (the two-key limit exists precisely to
  allow overlap), update the connector, confirm ingestion, then deactivate and delete the old
  key. Do the same immediately if the secret is ever exposed.
- **Retirement:** when the integration is decommissioned, delete both access keys and then the
  IAM user — a leftover enabled key is standing risk.
- Per AWS's own guidance, monitor access-key usage via CloudTrail; the key should only ever be
  used by the Fluency poller.

---

## Layout

```
automatic-amazon-guardduty/
├── SKILL.md
├── assets/
│   ├── setup-ingext-guardduty.sh   ← aws CLI script: IAM user + read-only policy + access key, prints the credential JSON
│   └── references.md               ← AWS documentation URLs backing every AWS-side step
└── evals/
    └── evals.json                  ← trigger phrases for skill selection
```
