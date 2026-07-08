<#
.SYNOPSIS
  Create (or update) the "ingext-audit" Entra (Azure AD) application registration that
  Fluency / Ingext uses to import Office 365 Management audit events, Azure AD audit
  events, and Azure AD resources (users / groups / devices / applications).

.DESCRIPTION
  Run this as an Azure AD admin who can BOTH create app registrations AND grant
  tenant-wide admin consent (Global Administrator, or Privileged Role Administrator +
  Application Administrator / Cloud Application Administrator).

  The script is idempotent: if an app named "ingext-audit" already exists it is reused
  (permissions are re-applied and a fresh client secret is added) rather than duplicated.

  It requests these APPLICATION (app-only, type = Role) permissions:

    Microsoft Graph
      Directory.Read.All, AuditLog.Read.All, Policy.Read.All, Reports.Read.All,
      UserAuthenticationMethod.Read.All, MailboxSettings.Read
    Office 365 Management APIs
      ActivityFeed.Read, ActivityFeed.ReadDlp, ServiceHealth.Read

  Permission role IDs are resolved at runtime from each resource service principal's
  AppRoles (matched by Value) — nothing is hardcoded, so the script stays correct even
  if Microsoft's GUIDs ever change.

  On success it prints a single JSON object:  { "tenantId", "clientId", "clientSecret" }
  Hand those three values to Fluency / Ingext for the "install application" stage.

.PREREQUISITES
  PowerShell 7+ and the Microsoft.Graph module:
    Install-Module Microsoft.Graph -Scope CurrentUser

.EXAMPLE
  ./setup-ingext-audit.ps1
  ./setup-ingext-audit.ps1 -AppName "ingext-audit" -SecretMonths 24
#>

[CmdletBinding()]
param(
    [string] $AppName      = "ingext-audit",
    [int]    $SecretMonths = 24
)

$ErrorActionPreference = "Stop"

# --- Constants: well-known Microsoft resource application IDs ---------------------
$GraphAppId = "00000003-0000-0000-c000-000000000000"   # Microsoft Graph
$O365AppId  = "c5393580-f805-4401-95e8-94b7a6ef2fc2"   # Office 365 Management APIs

# --- The application (app-only) permissions to request, per resource -------------
$GraphPerms = @(
    "Directory.Read.All",
    "AuditLog.Read.All",
    "Policy.Read.All",
    "Reports.Read.All",
    "UserAuthenticationMethod.Read.All",
    "MailboxSettings.Read"
)
$O365Perms = @(
    "ActivityFeed.Read",
    "ActivityFeed.ReadDlp",
    "ServiceHealth.Read"
)

# --- Connect ---------------------------------------------------------------------
# Scopes let us create the app, add credentials, and grant admin consent.
Connect-MgGraph -Scopes @(
    "Application.ReadWrite.All",
    "AppRoleAssignment.ReadWrite.All",
    "Directory.Read.All"
) -NoWelcome

$context  = Get-MgContext
$tenantId = $context.TenantId
Write-Host "Connected to tenant $tenantId as $($context.Account)" -ForegroundColor Cyan

# --- Get the resource service principals -----------------------------------------
# The Office 365 Management APIs SP must exist in the tenant to receive app-role
# assignments; if it is missing we instantiate it from its well-known appId.
function Get-OrAddResourceSp([string] $appId, [string] $label) {
    $sp = Get-MgServicePrincipal -Filter "appId eq '$appId'" -ErrorAction SilentlyContinue
    if (-not $sp) {
        Write-Host "  $label service principal not found in tenant — creating it..." -ForegroundColor Yellow
        $sp = New-MgServicePrincipal -AppId $appId
    }
    return $sp
}

$graphSp = Get-OrAddResourceSp $GraphAppId "Microsoft Graph"
$o365Sp  = Get-OrAddResourceSp $O365AppId  "Office 365 Management APIs"

# --- Resolve permission names -> app-role objects --------------------------------
function Resolve-AppRoles($sp, [string[]] $names) {
    $names | ForEach-Object {
        $name = $_
        $role = $sp.AppRoles | Where-Object {
            $_.Value -eq $name -and ($_.AllowedMemberTypes -contains "Application")
        }
        if (-not $role) {
            throw "Application permission '$name' was not found on '$($sp.DisplayName)'. Check the permission name and that the resource API is available in this tenant."
        }
        [pscustomobject]@{ Id = $role.Id; Value = $name; ResourceSpId = $sp.Id }
    }
}

$graphRoles = @(Resolve-AppRoles $graphSp $GraphPerms)
$o365Roles  = @(Resolve-AppRoles $o365Sp  $O365Perms)
$allRoles   = $graphRoles + $o365Roles

# --- Build the requiredResourceAccess block --------------------------------------
$requiredResourceAccess = @(
    @{
        ResourceAppId  = $GraphAppId
        ResourceAccess = @($graphRoles | ForEach-Object { @{ Id = $_.Id; Type = "Role" } })
    },
    @{
        ResourceAppId  = $O365AppId
        ResourceAccess = @($o365Roles | ForEach-Object { @{ Id = $_.Id; Type = "Role" } })
    }
)

# --- Create or reuse the application ---------------------------------------------
$app = Get-MgApplication -Filter "displayName eq '$AppName'" -ErrorAction SilentlyContinue |
       Select-Object -First 1
if ($app) {
    Write-Host "Application '$AppName' already exists (appId $($app.AppId)) — updating permissions." -ForegroundColor Yellow
    Update-MgApplication -ApplicationId $app.Id `
        -RequiredResourceAccess $requiredResourceAccess `
        -SignInAudience "AzureADMyOrg"
} else {
    Write-Host "Creating application '$AppName'..." -ForegroundColor Cyan
    $app = New-MgApplication -DisplayName $AppName `
        -SignInAudience "AzureADMyOrg" `
        -RequiredResourceAccess $requiredResourceAccess
}
$clientId = $app.AppId

# --- Ensure the application has a service principal (needed for consent) ----------
# A brand-new app can lag directory replication, so retry briefly.
$appSp = Get-MgServicePrincipal -Filter "appId eq '$clientId'" -ErrorAction SilentlyContinue
if (-not $appSp) {
    for ($attempt = 1; $attempt -le 6 -and -not $appSp; $attempt++) {
        try {
            $appSp = New-MgServicePrincipal -AppId $clientId
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds 5
        }
    }
}

# --- Add a client secret ---------------------------------------------------------
$passwordCredential = @{
    DisplayName   = "ingext-audit ($(Get-Date -Format 'yyyy-MM-dd'))"
    EndDateTime   = (Get-Date).AddMonths($SecretMonths)
}
$secret = Add-MgApplicationPassword -ApplicationId $app.Id -PasswordCredential $passwordCredential
$clientSecret = $secret.SecretText   # returned once, only here

# --- Grant admin consent = create an app-role assignment for each permission -----
Write-Host "Granting admin consent for $($allRoles.Count) application permissions..." -ForegroundColor Cyan
$existing = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id -All
foreach ($role in $allRoles) {
    $already = $existing | Where-Object {
        $_.AppRoleId -eq $role.Id -and $_.ResourceId -eq $role.ResourceSpId
    }
    if ($already) {
        Write-Host "  = $($role.Value) already granted" -ForegroundColor DarkGray
        continue
    }
    # A freshly created service principal can lag replication — retry briefly.
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id `
                -PrincipalId $appSp.Id `
                -ResourceId  $role.ResourceSpId `
                -AppRoleId   $role.Id | Out-Null
            break
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds 5
        }
    }
    Write-Host "  + $($role.Value)" -ForegroundColor Green
}

# --- Emit the three fields -------------------------------------------------------
$result = [ordered]@{
    tenantId     = $tenantId
    clientId     = $clientId
    clientSecret = $clientSecret
}

Write-Host ""
Write-Host "==================== ingext-audit credentials ====================" -ForegroundColor Cyan
Write-Host "The client secret is shown ONCE below — copy it now." -ForegroundColor Yellow
Write-Host ""
$result | ConvertTo-Json
Write-Host ""
Write-Host "Provide these three fields to Fluency / Ingext (install-application stage)." -ForegroundColor Cyan
