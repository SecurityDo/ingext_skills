#!/usr/bin/env bash
#
# setup-ingext-eventhub.sh — create (or reuse) the Azure Event Hubs resources that Fluency /
# Ingext consumes events from, then print the Listen-only "Connection string–primary key"
# that the Ingext "Azure Event Hubs" connector takes as its `endpoint` parameter.
#
# This is the Azure CLI (az) counterpart of setup-ingext-eventhub.ps1. It is idempotent:
# every resource is reused if it already exists, so re-runs are safe.
#
# Resources created (or reused):
#   Resource group        default: ingext-eventhub-rg
#   Event Hubs namespace  default: ingext-ehns-<first 8 chars of subscription id>
#                         (globally unique DNS name; SKU Standard, 1 throughput unit)
#   Event hub             default: ingext-events (2 partitions, 24 h retention)
#   SAS policy            default: ingext-listen — rights: Listen ONLY, created ON THE EVENT
#                         HUB (not the namespace) so its connection string embeds EntityPath
#   Consumer group        only with --consumer-group NAME; otherwise $Default is used
#
# COST: an Event Hubs namespace is a BILLABLE Azure resource (charged per throughput unit
# per hour, plus ingress). This is unlike an Entra app registration, which is free.
#
# On success it prints ONE JSON object to stdout:
#   { "connectionString", "namespace", "eventHub", "resourceGroup", "location", "consumerGroup" }
# All human-readable progress goes to stderr, so stdout stays cleanly parseable.
# "connectionString" is the value the Azure portal labels "Connection string–primary key".
#
# PREREQUISITES
#   - Azure CLI (az) installed and logged in to the TARGET subscription:
#       az login                 # or:  az login --use-device-code   (headless / no browser)
#     The signed-in identity needs rights to create resource groups and Event Hubs
#     resources — Contributor (or Owner) on the subscription, or Contributor on an
#     existing resource group passed via --resource-group.
#   - If the account has several subscriptions, pick one first:
#       az account set --subscription <id-or-name>     # or pass --subscription below
#
# USAGE
#   ./setup-ingext-eventhub.sh
#   ./setup-ingext-eventhub.sh --resource-group my-rg --location westus2
#   ./setup-ingext-eventhub.sh --namespace my-unique-ns --eventhub-name my-hub --sku Basic
#   ./setup-ingext-eventhub.sh --consumer-group ingext        # dedicated group (Standard+)
#   ./setup-ingext-eventhub.sh --subscription <id> --yes      # non-interactive

set -euo pipefail

RESOURCE_GROUP="ingext-eventhub-rg"
LOCATION="eastus"
NAMESPACE=""                 # default derived from subscription id after login
EVENTHUB_NAME="ingext-events"
POLICY_NAME="ingext-listen"
SKU="Standard"
PARTITION_COUNT=2
RETENTION_HOURS=24
CONSUMER_GROUP_ARG=""
SUBSCRIPTION=""
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group)  RESOURCE_GROUP="$2"; shift 2 ;;
    --location)        LOCATION="$2"; shift 2 ;;
    --namespace)       NAMESPACE="$2"; shift 2 ;;
    --eventhub-name)   EVENTHUB_NAME="$2"; shift 2 ;;
    --policy-name)     POLICY_NAME="$2"; shift 2 ;;
    --sku)             SKU="$2"; shift 2 ;;
    --partition-count) PARTITION_COUNT="$2"; shift 2 ;;
    --retention-hours) RETENTION_HOURS="$2"; shift 2 ;;
    --consumer-group)  CONSUMER_GROUP_ARG="$2"; shift 2 ;;
    --subscription)    SUBSCRIPTION="$2"; shift 2 ;;
    --yes|-y)          ASSUME_YES=1; shift ;;
    -h|--help)         grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s\n' "$*" >&2; }

# --- Preflight: az present and logged in ----------------------------------------
command -v az >/dev/null 2>&1 || { log "ERROR: Azure CLI (az) is not installed. See https://learn.microsoft.com/cli/azure/install-azure-cli"; exit 1; }

if ! az account show >/dev/null 2>&1; then
  log "ERROR: not logged in to Azure."
  log "       Run:  az login          (browser)"
  log "        or:  az login --use-device-code   (headless / relay the code to sign in)"
  exit 1
fi

if [[ -n "$SUBSCRIPTION" ]]; then
  az account set --subscription "$SUBSCRIPTION"
fi

TENANT_ID=$(az account show --query tenantId -o tsv)
SUB_ID=$(az account show --query id -o tsv)
SUB_NAME=$(az account show --query name -o tsv)
SIGNED_IN=$(az account show --query user.name -o tsv)
log "Connected to tenant $TENANT_ID"
log "Subscription: '$SUB_NAME' ($SUB_ID) as $SIGNED_IN"

# Default namespace name: deterministic per subscription so re-runs reuse it.
# Event Hubs namespace names are GLOBAL DNS names (6-50 chars, letters/digits/hyphens).
[[ -n "$NAMESPACE" ]] || NAMESPACE="ingext-ehns-${SUB_ID:0:8}"

if [[ "$ASSUME_YES" -ne 1 ]]; then
  # Confirmation guards against creating billable resources in the wrong subscription.
  log ""
  log "About to create (or reuse) in the subscription above:"
  log "  resource group '$RESOURCE_GROUP' ($LOCATION), namespace '$NAMESPACE' (SKU $SKU — BILLABLE),"
  log "  event hub '$EVENTHUB_NAME', Listen-only SAS policy '$POLICY_NAME'"
  printf 'Proceed? [y/N] ' >&2
  read -r reply || true
  case "$reply" in y|Y|yes|YES) ;; *) log "Aborted."; exit 1 ;; esac
fi

# --- Ensure the Microsoft.EventHub resource provider is registered ----------------
# First-ever Event Hubs use in a subscription needs the provider registered; best-effort.
PROV_STATE=$(az provider show --namespace Microsoft.EventHub --query registrationState -o tsv 2>/dev/null || echo "Unknown")
if [[ "$PROV_STATE" != "Registered" ]]; then
  log "Registering resource provider Microsoft.EventHub (one-time per subscription)..."
  az provider register --namespace Microsoft.EventHub --wait >/dev/null 2>&1 \
    || log "WARNING: provider registration did not confirm — continuing; creation may still succeed."
fi

# --- Resource group (idempotent: create succeeds if it already exists) ------------
log "Ensuring resource group '$RESOURCE_GROUP' in $LOCATION..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" >/dev/null

# --- Event Hubs namespace ---------------------------------------------------------
if az eventhubs namespace show --resource-group "$RESOURCE_GROUP" --name "$NAMESPACE" >/dev/null 2>&1; then
  log "Namespace '$NAMESPACE' already exists — reusing it."
else
  log "Creating Event Hubs namespace '$NAMESPACE' (SKU $SKU, capacity 1) — takes a minute or two..."
  if ! az eventhubs namespace create \
        --resource-group "$RESOURCE_GROUP" --name "$NAMESPACE" \
        --location "$LOCATION" --sku "$SKU" --capacity 1 >/dev/null; then
    log "ERROR: could not create namespace '$NAMESPACE'."
    log "       Namespace names are GLOBALLY unique. If the error above says the name is"
    log "       unavailable, re-run with:  --namespace <another-globally-unique-name>"
    exit 1
  fi
fi

# --- Event hub --------------------------------------------------------------------
if az eventhubs eventhub show --resource-group "$RESOURCE_GROUP" --namespace-name "$NAMESPACE" \
     --name "$EVENTHUB_NAME" >/dev/null 2>&1; then
  log "Event hub '$EVENTHUB_NAME' already exists — reusing it."
else
  log "Creating event hub '$EVENTHUB_NAME' ($PARTITION_COUNT partitions, ${RETENTION_HOURS}h retention)..."
  # Retention flags changed across az versions: try current, then legacy, then defaults.
  az eventhubs eventhub create --resource-group "$RESOURCE_GROUP" --namespace-name "$NAMESPACE" \
      --name "$EVENTHUB_NAME" --partition-count "$PARTITION_COUNT" \
      --cleanup-policy Delete --retention-time-in-hours "$RETENTION_HOURS" >/dev/null 2>&1 \
  || az eventhubs eventhub create --resource-group "$RESOURCE_GROUP" --namespace-name "$NAMESPACE" \
      --name "$EVENTHUB_NAME" --partition-count "$PARTITION_COUNT" \
      --message-retention 1 >/dev/null 2>&1 \
  || az eventhubs eventhub create --resource-group "$RESOURCE_GROUP" --namespace-name "$NAMESPACE" \
      --name "$EVENTHUB_NAME" --partition-count "$PARTITION_COUNT" >/dev/null
fi

# --- Listen-only SAS policy ON THE EVENT HUB --------------------------------------
# Hub-level (not namespace-level) so the connection string embeds EntityPath, and
# Listen-only so Ingext holds least-privilege credentials.
if az eventhubs eventhub authorization-rule show --resource-group "$RESOURCE_GROUP" \
     --namespace-name "$NAMESPACE" --eventhub-name "$EVENTHUB_NAME" --name "$POLICY_NAME" >/dev/null 2>&1; then
  log "SAS policy '$POLICY_NAME' already exists — reusing it."
else
  log "Creating Listen-only SAS policy '$POLICY_NAME' on event hub '$EVENTHUB_NAME'..."
  az eventhubs eventhub authorization-rule create --resource-group "$RESOURCE_GROUP" \
    --namespace-name "$NAMESPACE" --eventhub-name "$EVENTHUB_NAME" \
    --name "$POLICY_NAME" --rights Listen >/dev/null
fi

# --- Consumer group (optional) ----------------------------------------------------
CONSUMER_GROUP='$Default'
if [[ -n "$CONSUMER_GROUP_ARG" ]]; then
  if [[ "$SKU" == "Basic" ]]; then
    log "WARNING: the Basic tier supports only the \$Default consumer group — '$CONSUMER_GROUP_ARG' was NOT created."
  elif az eventhubs eventhub consumer-group show --resource-group "$RESOURCE_GROUP" \
         --namespace-name "$NAMESPACE" --eventhub-name "$EVENTHUB_NAME" \
         --name "$CONSUMER_GROUP_ARG" >/dev/null 2>&1; then
    log "Consumer group '$CONSUMER_GROUP_ARG' already exists — reusing it."
    CONSUMER_GROUP="$CONSUMER_GROUP_ARG"
  else
    log "Creating consumer group '$CONSUMER_GROUP_ARG'..."
    az eventhubs eventhub consumer-group create --resource-group "$RESOURCE_GROUP" \
      --namespace-name "$NAMESPACE" --eventhub-name "$EVENTHUB_NAME" \
      --name "$CONSUMER_GROUP_ARG" >/dev/null
    CONSUMER_GROUP="$CONSUMER_GROUP_ARG"
  fi
fi

# --- Fetch the Connection string–primary key --------------------------------------
CONNECTION_STRING=$(az eventhubs eventhub authorization-rule keys list \
  --resource-group "$RESOURCE_GROUP" --namespace-name "$NAMESPACE" \
  --eventhub-name "$EVENTHUB_NAME" --name "$POLICY_NAME" \
  --query primaryConnectionString -o tsv)

if [[ -z "$CONNECTION_STRING" ]]; then
  log "ERROR: could not read the primary connection string for policy '$POLICY_NAME'."
  exit 1
fi

# --- Emit the result (JSON to stdout, only content on stdout) ---------------------
log ""
log "==================== ingext Azure Event Hubs connection ===================="
log "Give \"connectionString\" to the Ingext 'Azure Event Hubs' connector (endpoint field)."
log "Unlike an app secret, it can be re-fetched later from Shared access policies."
log ""
cat <<JSON
{
  "connectionString": "$CONNECTION_STRING",
  "namespace": "$NAMESPACE",
  "eventHub": "$EVENTHUB_NAME",
  "resourceGroup": "$RESOURCE_GROUP",
  "location": "$LOCATION",
  "consumerGroup": "$CONSUMER_GROUP"
}
JSON
log ""
log "Next: create the 'Azure Event Hubs' connector in Fluency / Ingext with this endpoint,"
log "then point Azure diagnostic settings (or other producers) at event hub '$EVENTHUB_NAME'."
