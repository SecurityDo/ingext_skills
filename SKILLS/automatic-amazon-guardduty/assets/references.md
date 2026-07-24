# References — Amazon GuardDuty AWS-side steps

Verified 2026-07-24. Re-check at next skill revision; AWS occasionally reshuffles console
flows and managed-policy contents.

| Claim in SKILL.md / script | Source |
|---|---|
| The read-only AWS managed policy is named exactly `AmazonGuardDutyReadOnlyAccess`; it grants GuardDuty `Get*`/`List*`/`Describe*` plus read-only Organizations lookups | [AWS managed policies for Amazon GuardDuty — GuardDuty User Guide](https://docs.aws.amazon.com/guardduty/latest/ug/security-iam-awsmanpol.html) |
| Policy ARN `arn:aws:iam::aws:policy/AmazonGuardDutyReadOnlyAccess` | [AmazonGuardDutyReadOnlyAccess — AWS Managed Policy Reference](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonGuardDutyReadOnlyAccess.html) |
| Maximum of two access keys per IAM user; the secret access key can be retrieved only at creation time; a lost secret means delete the key and create a new one | [Manage access keys for IAM users — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html) |
| Console access-key flow: Users → user → **Security credentials** tab → **Access keys** → **Create access key**; button deactivated at the two-key limit; **Access key best practices & alternatives** page → choose **Other** → **Next** → optional description tag → **Create access key**; **Retrieve access key** page with **Show** / **Download .csv file**, only chance to view the secret. Also the deactivate/delete rotation steps | [How an IAM administrator can manage IAM user access keys — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-keys-admin-managed.html) |
| Console user-creation flow (programmatic workload user): Users → **Create user** → **Specify user details** → permissions → **Create user**; console access is optional and skipped for programmatic-only users; CLI `aws iam create-user` | [Create an IAM user for workloads that can't use IAM roles — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/getting-started-workloads.html); [Create an IAM user in your AWS account — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html) |
| The **Attach policies directly** option on the Set/Add permissions page (exact console label) | [Change permissions for an IAM user — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_change-permissions.html) |
| `aws iam attach-user-policy --user-name … --policy-arn …` attaches a managed policy to a user | [attach-user-policy — AWS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/iam/attach-user-policy.html) |
| `aws sts get-caller-identity` returns the caller's `Account`, `Arn`, `UserId` (the script's sign-in preflight) | [get-caller-identity — AWS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html) |
| GuardDuty is a **regional** service — configuration must be repeated per region; first enable in a region starts a **30-day free trial** for that region; enabling is done in the GuardDuty console (**Get started** → **Enable GuardDuty**) | [Getting started with GuardDuty — GuardDuty User Guide](https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_settingup.html) |
| `aws guardduty list-detectors` lists the detector ids in the current region (empty = GuardDuty not enabled there) | [list-detectors — AWS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/guardduty/list-detectors.html) |
| Sample findings: console **Settings** → **Sample findings** → **Generate sample findings**; CLI `aws guardduty create-sample-findings --detector-id <id> [--finding-types …]`; samples are placeholders titled **[SAMPLE]** with `"sample": true` in the finding JSON | [Generating sample findings in GuardDuty — GuardDuty User Guide](https://docs.aws.amazon.com/guardduty/latest/ug/sample_findings.html); [create-sample-findings — AWS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/guardduty/create-sample-findings.html) |
| Monitor access-key usage with CloudTrail; review/rotate/delete keys regularly | [Manage access keys for IAM users — IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html) (Monitoring recommendations) |

Notes:

- The console use-case page instruction ("choose **Other**, then **Next**") follows AWS's own
  documented administrator procedure verbatim; other use-case options exist on that page but
  AWS's docs route long-term-key creation through **Other**.
- The `AmazonGuardDuty` template's parameter set (Regions list + `IAM_AccessKey` +
  `IAM_AccessSecret`, no role option, no `datalake`/`index`) was confirmed against the live
  `list_connector_templates` on 2026-07-24; the skill still instructs a live re-fetch at
  runtime.
- The datalake table name for GuardDuty rows is deliberately uncited: the template exposes no
  index parameter, so the skill instructs confirming the live name with `list_data_tables`
  rather than asserting one.
