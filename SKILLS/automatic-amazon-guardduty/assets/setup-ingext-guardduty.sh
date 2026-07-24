#!/usr/bin/env bash
#
# setup-ingext-guardduty.sh — create (or reuse) the least-privilege AWS IAM user and access
# key that the Fluency / Ingext "Amazon GuardDuty" connector uses to poll GuardDuty findings.
#
# This is the AWS CLI counterpart of setup-ingext-eventhub.sh (Azure). It is idempotent for
# the user and policy attachment: both are reused if they already exist, so re-runs are safe.
# NOTE: each successful run creates a NEW access key (secrets cannot be re-fetched from AWS),
# up to the AWS maximum of TWO access keys per user — delete superseded keys after rotating.
#
# Resources created (or reused):
#   IAM user        default: ingext-guardduty (no console access, no password)
#   Policy attach   AWS managed policy AmazonGuardDutyReadOnlyAccess
#                   (arn:aws:iam::aws:policy/AmazonGuardDutyReadOnlyAccess — GuardDuty
#                   Get*/List*/Describe* only; least privilege for a findings consumer)
#   Access key      one new key pair for that user (the connector's credentials)
#
# NOT created: GuardDuty itself. GuardDuty must ALREADY be enabled (a detector must exist)
# in every region the connector will poll — enabling it starts AWS billing after the free
# trial, so that decision belongs to the account owner, not this script. Use --check-regions
# to have the script warn about regions with no detector.
#
# COST: nothing this script creates is billable (IAM users, policies, and access keys are
# free). GuardDuty itself bills per region once enabled — this script never enables it.
#
# On success it prints ONE JSON object to stdout:
#   { "accessKeyId", "secretAccessKey", "userName", "accountId" }
# All human-readable progress goes to stderr, so stdout stays cleanly parseable.
# "secretAccessKey" is shown ONCE — AWS cannot re-display it. Treat the JSON as a credential
# hand-off: feed it to the connector, don't paste it anywhere else.
#
# PREREQUISITES
#   - AWS CLI (aws) installed and signed in to the TARGET account:
#       aws configure            # long-term keys, or:
#       aws sso login            # IAM Identity Center, or environment variables
#     The signed-in identity needs IAM admin rights: iam:CreateUser, iam:GetUser,
#     iam:AttachUserPolicy, iam:ListAttachedUserPolicies, iam:CreateAccessKey,
#     iam:ListAccessKeys — plus guardduty:ListDetectors for --check-regions.
#
# USAGE
#   ./setup-ingext-guardduty.sh
#   ./setup-ingext-guardduty.sh --user-name my-ingext-user
#   ./setup-ingext-guardduty.sh --check-regions us-east-1,us-west-2
#   ./setup-ingext-guardduty.sh --check-regions us-east-1 --yes    # non-interactive

set -euo pipefail

USER_NAME="ingext-guardduty"
POLICY_ARN="arn:aws:iam::aws:policy/AmazonGuardDutyReadOnlyAccess"
CHECK_REGIONS=""
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user-name)     USER_NAME="$2"; shift 2 ;;
    --policy-arn)    POLICY_ARN="$2"; shift 2 ;;
    --check-regions) CHECK_REGIONS="$2"; shift 2 ;;
    --yes|-y)        ASSUME_YES=1; shift ;;
    -h|--help)       grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s\n' "$*" >&2; }

# --- Preflight: aws present and signed in -----------------------------------------
command -v aws >/dev/null 2>&1 || { log "ERROR: AWS CLI (aws) is not installed. See https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"; exit 1; }

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  log "ERROR: no working AWS credentials."
  log "       Run:  aws configure      (access keys)"
  log "        or:  aws sso login      (IAM Identity Center)"
  log "       then re-run this script."
  exit 1
fi

read -r ACCOUNT_ID CALLER_ARN <<<"$(aws sts get-caller-identity --query '[Account,Arn]' --output text)"
log "AWS account: $ACCOUNT_ID"
log "Signed in as: $CALLER_ARN"

# --- Preflight: GuardDuty enabled in the regions the connector will poll? ----------
# GuardDuty is a REGIONAL service — a detector must exist in every region the connector
# will read from. This script only checks and warns; enabling GuardDuty is billable and
# is the account owner's decision.
if [[ -n "$CHECK_REGIONS" ]]; then
  IFS=',' read -r -a REGIONS_ARR <<<"$CHECK_REGIONS"
  for r in "${REGIONS_ARR[@]}"; do
    r="${r// /}"
    [[ -n "$r" ]] || continue
    DET_COUNT=$(aws guardduty list-detectors --region "$r" --query 'length(DetectorIds)' --output text 2>/dev/null) || DET_COUNT=""
    if [[ -z "$DET_COUNT" ]]; then
      log "WARNING: could not check GuardDuty in region '$r' (missing guardduty:ListDetectors permission, or bad region name?). Verify manually: aws guardduty list-detectors --region $r"
    elif [[ "$DET_COUNT" == "0" ]]; then
      log "WARNING: no GuardDuty detector found in region '$r' — GuardDuty is NOT enabled there."
      log "         The connector will import nothing from that region until the account owner"
      log "         enables GuardDuty (billable after the 30-day trial). This script will NOT enable it."
    else
      log "OK: GuardDuty detector present in region '$r'."
    fi
  done
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  # Confirmation guards against creating IAM principals in the wrong account.
  log ""
  log "About to create (or reuse) in AWS account $ACCOUNT_ID:"
  log "  IAM user '$USER_NAME' (no console access) with the AWS managed policy"
  log "  '$POLICY_ARN' attached (GuardDuty read-only),"
  log "  plus ONE new long-lived access key for that user."
  log "Nothing billable is created, and GuardDuty itself is NOT enabled or modified."
  printf 'Proceed? [y/N] ' >&2
  read -r reply || true
  case "$reply" in y|Y|yes|YES) ;; *) log "Aborted."; exit 1 ;; esac
fi

# --- IAM user (idempotent) ---------------------------------------------------------
if aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
  log "IAM user '$USER_NAME' already exists — reusing it."
else
  log "Creating IAM user '$USER_NAME'..."
  aws iam create-user --user-name "$USER_NAME" >/dev/null
fi

# --- Attach the GuardDuty read-only managed policy (idempotent) --------------------
ATTACHED=$(aws iam list-attached-user-policies --user-name "$USER_NAME" \
  --query "length(AttachedPolicies[?PolicyArn=='$POLICY_ARN'])" --output text)
if [[ "$ATTACHED" != "0" ]]; then
  log "Policy already attached to '$USER_NAME' — reusing it."
else
  log "Attaching '$POLICY_ARN' to '$USER_NAME'..."
  aws iam attach-user-policy --user-name "$USER_NAME" --policy-arn "$POLICY_ARN"
fi

# --- Access key (respecting the AWS two-keys-per-user maximum) ---------------------
KEY_COUNT=$(aws iam list-access-keys --user-name "$USER_NAME" --query 'length(AccessKeyMetadata)' --output text)
if [[ "$KEY_COUNT" -ge 2 ]]; then
  log "ERROR: user '$USER_NAME' already has two access keys — the AWS maximum per user."
  log "       Existing keys:"
  aws iam list-access-keys --user-name "$USER_NAME" \
    --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output table >&2 || true
  log "       Rotate instead of piling up keys:"
  log "         1. Find which key is stale:   aws iam get-access-key-last-used --access-key-id <id>"
  log "         2. Deactivate it first:       aws iam update-access-key --user-name $USER_NAME --access-key-id <id> --status Inactive"
  log "         3. Delete it once nothing broke:  aws iam delete-access-key --user-name $USER_NAME --access-key-id <id>"
  log "       Then re-run this script to create the new key."
  exit 1
fi
if [[ "$KEY_COUNT" == "1" ]]; then
  log "NOTE: '$USER_NAME' already has one access key (its secret cannot be re-fetched)."
  log "      Creating a second key — after the connector works with the new key, delete the old one."
fi

log "Creating access key for '$USER_NAME'..."
read -r ACCESS_KEY_ID SECRET_ACCESS_KEY <<<"$(aws iam create-access-key --user-name "$USER_NAME" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)"

if [[ -z "$ACCESS_KEY_ID" || -z "$SECRET_ACCESS_KEY" ]]; then
  log "ERROR: access key creation returned no key material."
  exit 1
fi

# --- Emit the result (JSON to stdout, only content on stdout) ---------------------
log ""
log "==================== ingext Amazon GuardDuty credentials ===================="
log "Give \"accessKeyId\" / \"secretAccessKey\" to the Ingext 'Amazon GuardDuty' connector"
log "(IAM_AccessKey / IAM_AccessSecret fields). The secret is shown ONCE — AWS cannot"
log "re-display it. If it is lost, delete this key and re-run the script for a new one."
log ""
cat <<JSON
{
  "accessKeyId": "$ACCESS_KEY_ID",
  "secretAccessKey": "$SECRET_ACCESS_KEY",
  "userName": "$USER_NAME",
  "accountId": "$ACCOUNT_ID"
}
JSON
log ""
log "Next: create the 'Amazon GuardDuty' connector in Fluency / Ingext with these credentials"
log "and the region list, then confirm findings arrive (or generate sample findings:"
log "aws guardduty create-sample-findings --detector-id <id> --region <r>)."
