<#
.SYNOPSIS
  Create (or update) the "ingext-azureaudit" Entra (Azure AD) application registration that
  Fluency / Ingext uses to import Office 365 Management audit events, Azure AD audit
  events, and Azure AD resources (users / groups / devices / applications).

.DESCRIPTION
  Run this as an Azure AD admin who can BOTH create app registrations AND grant
  tenant-wide admin consent (Global Administrator, or Privileged Role Administrator +
  Application Administrator / Cloud Application Administrator).

  The script is idempotent: if an app named "ingext-azureaudit" already exists it is reused
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
  PowerShell 7+. The required Microsoft.Graph submodules are installed automatically
  on first run (see -ModuleScope / -SkipModuleInstall).

.PARAMETER ModuleScope
  Where to install missing modules: CurrentUser (default) or AllUsers (needs root).

.PARAMETER SkipModuleInstall
  Don't install anything; only import what's already present. Use in locked-down or
  air-gapped environments where modules are staged ahead of time.

.PARAMETER UseDeviceCode
  Authenticate with device-code flow instead of launching a browser. Required on
  headless servers (e.g. a RHEL box with no desktop session).

.EXAMPLE
  ./setup-ingext-azureaudit.ps1
  ./setup-ingext-azureaudit.ps1 -UseDeviceCode
  ./setup-ingext-azureaudit.ps1 -AppName "ingext-azureaudit" -SecretMonths 24
#>

[CmdletBinding()]
param(
    [string] $AppName      = "ingext-azureaudit",
    [int]    $SecretMonths = 24,

    [ValidateSet("CurrentUser", "AllUsers")]
    [string] $ModuleScope  = "CurrentUser",

    [switch] $SkipModuleInstall,
    [switch] $UseDeviceCode
)

$ErrorActionPreference = "Stop"

# --- Bootstrap: make sure the Microsoft.Graph cmdlets are available ---------------
# Only these two submodules are needed. The Microsoft.Graph meta-module pulls in ~40
# submodules and several hundred MB for no benefit here.
$RequiredModules = @(
    "Microsoft.Graph.Authentication",   # Connect-MgGraph, Get-MgContext
    "Microsoft.Graph.Applications"      # *-MgApplication, *-MgServicePrincipal*
)

function Initialize-GraphModule {
    param([string[]] $Names, [string] $Scope, [switch] $NoInstall)

    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "PowerShell 7+ is required. Detected $($PSVersionTable.PSVersion). Install pwsh and re-run."
    }

    $missing = @($Names | Where-Object { -not (Get-Module -ListAvailable -Name $_) })

    if ($missing.Count -gt 0) {
        if ($NoInstall) {
            throw "Missing module(s): $($missing -join ', '). Re-run without -SkipModuleInstall, or install them manually."
        }

        Write-Host "Installing missing module(s): $($missing -join ', ')" -ForegroundColor Cyan
        Write-Host "(first run only — this can take a minute)" -ForegroundColor DarkGray

        # PowerShellGet needs the NuGet provider; PS7 usually has it, so this is best-effort.
        try {
            if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
                Install-PackageProvider -Name NuGet -Scope $Scope -Force -ErrorAction Stop | Out-Null
            }
        } catch {
            Write-Verbose "NuGet provider bootstrap skipped: $($_.Exception.Message)"
        }

        foreach ($name in $missing) {
            # -Force also suppresses the "untrusted repository" prompt for PSGallery,
            # which would otherwise block an unattended run.
            Install-Module -Name $name `
                -Repository PSGallery `
                -Scope $Scope `
                -Force -AllowClobber -ErrorAction Stop
        }
    }

    foreach ($name in $Names) { Import-Module $name -ErrorAction Stop }

    # Mixed major versions across Microsoft.Graph.* submodules cause obscure runtime
    # failures (assembly conflicts). Warn rather than guess at a fix.
    $majors = @($Names | ForEach-Object { (Get-Module $_).Version.Major } | Select-Object -Unique)
    if ($majors.Count -gt 1) {
        Write-Warning ("Mismatched Microsoft.Graph module versions detected (major: $($majors -join ', ')). " +
                       "If you hit odd errors, remove them all and re-run: " +
                       "Get-Module Microsoft.Graph.* -ListAvailable | Uninstall-Module -Force -AllVersions")
    }
}

Initialize-GraphModule -Names $RequiredModules -Scope $ModuleScope -NoInstall:$SkipModuleInstall

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
$connectArgs = @{
    Scopes = @(
        "Application.ReadWrite.All",
        "AppRoleAssignment.ReadWrite.All",
        "Directory.Read.All"
    )
    NoWelcome = $true
}
if ($UseDeviceCode) { $connectArgs.UseDeviceCode = $true }

Connect-MgGraph @connectArgs

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
    DisplayName   = "ingext-azureaudit ($(Get-Date -Format 'yyyy-MM-dd'))"
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
Write-Host "==================== ingext-azureaudit credentials ====================" -ForegroundColor Cyan
Write-Host "The client secret is shown ONCE below — copy it now." -ForegroundColor Yellow
Write-Host ""
$result | ConvertTo-Json
Write-Host ""
Write-Host "Provide these three fields to Fluency / Ingext (install-application stage)." -ForegroundColor Cyan
