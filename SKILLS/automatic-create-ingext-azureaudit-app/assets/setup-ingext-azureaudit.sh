#!/usr/bin/env bash
#
# setup-ingext-azureaudit.sh — create (or update) the "ingext-azureaudit" Entra (Azure AD)
# application registration that Fluency / Ingext authenticates as (app-only /
# client-credentials) to import Office 365 Management audit events, Azure AD audit
# events, and Azure AD resources (users / groups / devices / applications).
#
# This is the Azure CLI (az) counterpart of setup-ingext-azureaudit.ps1. It is idempotent:
# if an app named "ingext-azureaudit" already exists it is reused (permissions re-applied,
# a fresh client secret appended) rather than duplicated.
#
# APPLICATION (app-only, type = Role) permissions requested:
#   Microsoft Graph
#     Directory.Read.All, AuditLog.Read.All, Policy.Read.All, Reports.Read.All,
#     UserAuthenticationMethod.Read.All, MailboxSettings.Read
#   Office 365 Management APIs
#     ActivityFeed.Read, ActivityFeed.ReadDlp, ServiceHealth.Read
#
# Each permission's app-role ID is resolved at RUNTIME from the resource service
# principal's appRoles (matched by value + Application member type) — no GUIDs are
# hardcoded, so the script stays correct even if Microsoft's role IDs ever change.
# Only the two resource application IDs are constants.
#
# On success it prints ONE JSON object to stdout:  { "tenantId", "clientId", "clientSecret" }
# All human-readable progress goes to stderr, so stdout stays cleanly parseable.
#
# PREREQUISITES
#   - Azure CLI (az) installed and logged in to the TARGET tenant:
#       az login                 # or:  az login --use-device-code   (headless / no browser)
#     The signed-in identity must be able to BOTH create app registrations AND grant
#     tenant-wide admin consent (Global Administrator, or Privileged Role Administrator
#     + Application Administrator / Cloud Application Administrator).
#
# USAGE
#   ./setup-ingext-azureaudit.sh
#   ./setup-ingext-azureaudit.sh --app-name ingext-azureaudit --secret-years 2
#   ./setup-ingext-azureaudit.sh --yes            # skip the "run against this tenant?" confirmation

set -euo pipefail

APP_NAME="ingext-azureaudit"
SECRET_YEARS=2
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-name)     APP_NAME="$2"; shift 2 ;;
    --secret-years) SECRET_YEARS="$2"; shift 2 ;;
    --yes|-y)       ASSUME_YES=1; shift ;;
    -h|--help)      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s\n' "$*" >&2; }

# --- Well-known Microsoft resource application IDs -------------------------------
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"   # Microsoft Graph
O365_APP_ID="c5393580-f805-4401-95e8-94b7a6ef2fc2"    # Office 365 Management APIs

GRAPH_PERMS=(Directory.Read.All AuditLog.Read.All Policy.Read.All Reports.Read.All UserAuthenticationMethod.Read.All MailboxSettings.Read)
O365_PERMS=(ActivityFeed.Read ActivityFeed.ReadDlp ServiceHealth.Read)

# --- Preflight: az present and logged in ----------------------------------------
command -v az >/dev/null 2>&1 || { log "ERROR: Azure CLI (az) is not installed. See https://learn.microsoft.com/cli/azure/install-azure-cli"; exit 1; }

if ! az account show >/dev/null 2>&1; then
  log "ERROR: not logged in to Azure."
  log "       Run:  az login          (browser)"
  log "        or:  az login --use-device-code   (headless / relay the code to sign in)"
  exit 1
fi

TENANT_ID=$(az account show --query tenantId -o tsv)
SIGNED_IN=$(az account show --query user.name -o tsv)
log "Connected to tenant $TENANT_ID as $SIGNED_IN"

if [[ "$ASSUME_YES" -ne 1 ]]; then
  # Confirmation guards against creating the app in the wrong tenant.
  printf 'Create/update app "%s" in the tenant above? [y/N] ' "$APP_NAME" >&2
  read -r reply || true
  case "$reply" in y|Y|yes|YES) ;; *) log "Aborted."; exit 1 ;; esac
fi

# --- Ensure resource service principals exist (needed to receive consent) --------
ensure_sp() {
  local app_id="$1" label="$2"
  if ! az ad sp show --id "$app_id" >/dev/null 2>&1; then
    log "  $label service principal not found in tenant — creating it..."
    az ad sp create --id "$app_id" >/dev/null
  fi
}
ensure_sp "$GRAPH_APP_ID" "Microsoft Graph"
ensure_sp "$O365_APP_ID"  "Office 365 Management APIs"

# --- Resolve permission name -> app-role ID at runtime ---------------------------
resolve_role_id() {
  local resource_app_id="$1" name="$2" id
  id=$(az ad sp show --id "$resource_app_id" \
        --query "appRoles[?value=='$name' && contains(allowedMemberTypes, 'Application')].id | [0]" -o tsv)
  if [[ -z "$id" || "$id" == "None" ]]; then
    log "ERROR: application permission '$name' not found on resource $resource_app_id."
    log "       Check the permission name and that the resource API exists in this tenant."
    exit 1
  fi
  printf '%s' "$id"
}

graph_pairs=()
for p in "${GRAPH_PERMS[@]}"; do graph_pairs+=("$(resolve_role_id "$GRAPH_APP_ID" "$p")=Role"); done
o365_pairs=()
for p in "${O365_PERMS[@]}"; do o365_pairs+=("$(resolve_role_id "$O365_APP_ID" "$p")=Role"); done

# --- Create or reuse the application --------------------------------------------
CLIENT_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [[ -n "$CLIENT_ID" ]]; then
  log "Application '$APP_NAME' already exists (appId $CLIENT_ID) — updating permissions."
  az ad app update --id "$CLIENT_ID" --sign-in-audience AzureADMyOrg >/dev/null
else
  log "Creating application '$APP_NAME'..."
  CLIENT_ID=$(az ad app create --display-name "$APP_NAME" --sign-in-audience AzureADMyOrg --query appId -o tsv)
fi

# --- Apply the application permissions (additive / idempotent) -------------------
log "Applying ${#graph_pairs[@]} Microsoft Graph + ${#o365_pairs[@]} Office 365 Management permissions..."
az ad app permission add --id "$CLIENT_ID" --api "$GRAPH_APP_ID" --api-permissions "${graph_pairs[@]}" >/dev/null 2>&1
az ad app permission add --id "$CLIENT_ID" --api "$O365_APP_ID"  --api-permissions "${o365_pairs[@]}"  >/dev/null 2>&1

# --- Ensure the app's own service principal exists (required for consent) --------
# A freshly created app can lag directory replication, so retry briefly.
if ! az ad sp show --id "$CLIENT_ID" >/dev/null 2>&1; then
  for attempt in 1 2 3 4 5 6; do
    if az ad sp create --id "$CLIENT_ID" >/dev/null 2>&1; then break; fi
    [[ "$attempt" -eq 6 ]] && { log "ERROR: could not create service principal for $CLIENT_ID"; exit 1; }
    sleep 5
  done
fi

# --- Grant tenant-wide admin consent (retry for replication lag) -----------------
log "Granting admin consent for all application permissions..."
consented=0
for attempt in 1 2 3 4 5 6; do
  if az ad app permission admin-consent --id "$CLIENT_ID" >/dev/null 2>&1; then consented=1; break; fi
  sleep 5
done
if [[ "$consented" -ne 1 ]]; then
  log "WARNING: admin consent did not complete. The signed-in identity may lack consent rights"
  log "         (needs Global Administrator, or Privileged Role Admin + Application/Cloud App Admin)."
  log "         The app and permissions exist; a Global Admin can grant consent with:"
  log "           az ad app permission admin-consent --id $CLIENT_ID"
fi

# --- Add a client secret ---------------------------------------------------------
# --append keeps any existing secrets and adds a fresh one (idempotent re-runs).
log "Adding a client secret (${SECRET_YEARS}-year expiry)..."
CLIENT_SECRET=$(az ad app credential reset \
  --id "$CLIENT_ID" --append --years "$SECRET_YEARS" \
  --display-name "$APP_NAME" \
  --query password -o tsv)

# --- Emit the three fields (JSON to stdout, only line on stdout) -----------------
log ""
log "==================== ingext-azureaudit credentials ===================="
log "The client secret is shown ONCE below — copy it now."
log ""
cat <<JSON
{
  "tenantId": "$TENANT_ID",
  "clientId": "$CLIENT_ID",
  "clientSecret": "$CLIENT_SECRET"
}
JSON
log ""
log "Provide these three fields to Fluency / Ingext (install-application stage)."
