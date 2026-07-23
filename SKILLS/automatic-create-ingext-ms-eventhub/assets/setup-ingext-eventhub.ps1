<#
.SYNOPSIS
  Create (or reuse) the Azure Event Hubs resources that Fluency / Ingext consumes events
  from, then print the Listen-only "Connection string–primary key" that the Ingext
  "Azure Event Hubs" connector takes as its `endpoint` parameter.

.DESCRIPTION
  Run this as an identity with rights to create resource groups and Event Hubs resources
  in the target subscription — Contributor (or Owner) on the subscription, or Contributor
  on an existing resource group passed via -ResourceGroup.

  The script is idempotent: every resource is reused if it already exists, so re-runs are
  safe. It creates (or reuses):

    Resource group        default: ingext-eventhub-rg
    Event Hubs namespace  default: ingext-ehns-<first 8 chars of subscription id>
                          (globally unique DNS name; SKU Standard, 1 throughput unit)
    Event hub             default: ingext-events (2 partitions, 24 h retention)
    SAS policy            default: ingext-listen — rights: Listen ONLY, created ON THE
                          EVENT HUB (not the namespace) so its connection string embeds
                          EntityPath
    Consumer group        only with -ConsumerGroup NAME; otherwise $Default is used

  COST: an Event Hubs namespace is a BILLABLE Azure resource (charged per throughput unit
  per hour, plus ingress). This is unlike an Entra app registration, which is free.

  On success it prints a single JSON object:
    { "connectionString", "namespace", "eventHub", "resourceGroup", "location", "consumerGroup" }
  "connectionString" is the value the Azure portal labels "Connection string–primary key" —
  hand it to the Ingext "Azure Event Hubs" connector (endpoint field).

.PREREQUISITES
  PowerShell 7+. The required Az submodules (Az.Accounts, Az.Resources, Az.EventHub) are
  installed automatically on first run (see -ModuleScope / -SkipModuleInstall).

.PARAMETER SubscriptionId
  Target subscription. If omitted, the account's default subscription is used — the script
  prints which one and asks for confirmation before creating anything.

.PARAMETER ModuleScope
  Where to install missing modules: CurrentUser (default) or AllUsers (needs root).

.PARAMETER SkipModuleInstall
  Don't install anything; only import what's already present. Use in locked-down or
  air-gapped environments where modules are staged ahead of time.

.PARAMETER UseDeviceCode
  Authenticate with device-code flow instead of launching a browser. Required on
  headless servers (e.g. a RHEL box with no desktop session).

.PARAMETER Yes
  Skip the "create these resources in this subscription?" confirmation prompt.

.EXAMPLE
  ./setup-ingext-eventhub.ps1
  ./setup-ingext-eventhub.ps1 -UseDeviceCode
  ./setup-ingext-eventhub.ps1 -ResourceGroup my-rg -Location westus2 -Sku Basic
  ./setup-ingext-eventhub.ps1 -ConsumerGroup ingext -SubscriptionId <guid> -Yes
#>

[CmdletBinding()]
param(
    [string] $ResourceGroup  = "ingext-eventhub-rg",
    [string] $Location       = "eastus",
    [string] $NamespaceName  = "",              # default: ingext-ehns-<first 8 of subscription id>
    [string] $EventHubName   = "ingext-events",
    [string] $PolicyName     = "ingext-listen",

    [ValidateSet("Basic", "Standard", "Premium")]
    [string] $Sku            = "Standard",

    [int]    $PartitionCount = 2,
    [int]    $RetentionHours = 24,
    [string] $ConsumerGroup  = "",              # create + use a dedicated group; else $Default
    [string] $SubscriptionId = "",

    [ValidateSet("CurrentUser", "AllUsers")]
    [string] $ModuleScope    = "CurrentUser",

    [switch] $SkipModuleInstall,
    [switch] $UseDeviceCode,
    [switch] $Yes
)

$ErrorActionPreference = "Stop"

# --- Bootstrap: make sure the Az cmdlets are available -----------------------------
# Only these three submodules are needed. The Az meta-module pulls in ~80 submodules
# and several hundred MB for no benefit here.
$RequiredModules = @(
    "Az.Accounts",     # Connect-AzAccount, Get-AzContext, Set-AzContext
    "Az.Resources",    # *-AzResourceGroup, *-AzResourceProvider
    "Az.EventHub"      # *-AzEventHubNamespace, *-AzEventHub*, Get-AzEventHubKey
)

function Initialize-AzModule {
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
        Write-Host "(first run only — this can take a few minutes)" -ForegroundColor DarkGray

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
}

Initialize-AzModule -Names $RequiredModules -Scope $ModuleScope -NoInstall:$SkipModuleInstall

# --- Connect -----------------------------------------------------------------------
$context = Get-AzContext -ErrorAction SilentlyContinue
if (-not $context -or -not $context.Account) {
    $connectArgs = @{}
    if ($UseDeviceCode) { $connectArgs.UseDeviceAuthentication = $true }
    Connect-AzAccount @connectArgs | Out-Null
    $context = Get-AzContext
}

if ($SubscriptionId) {
    Set-AzContext -Subscription $SubscriptionId | Out-Null
    $context = Get-AzContext
}

$tenantId = $context.Tenant.Id
$subId    = $context.Subscription.Id
$subName  = $context.Subscription.Name
if (-not $subId) {
    throw "The signed-in account has no active subscription. Pass -SubscriptionId, or sign in with an account that has one."
}
Write-Host "Connected to tenant $tenantId" -ForegroundColor Cyan
Write-Host "Subscription: '$subName' ($subId) as $($context.Account.Id)" -ForegroundColor Cyan

# Default namespace name: deterministic per subscription so re-runs reuse it.
# Event Hubs namespace names are GLOBAL DNS names (6-50 chars, letters/digits/hyphens).
if (-not $NamespaceName) { $NamespaceName = "ingext-ehns-" + $subId.Substring(0, 8) }

if (-not $Yes) {
    # Confirmation guards against creating billable resources in the wrong subscription.
    Write-Host ""
    Write-Host "About to create (or reuse) in the subscription above:" -ForegroundColor Yellow
    Write-Host "  resource group '$ResourceGroup' ($Location), namespace '$NamespaceName' (SKU $Sku — BILLABLE)," -ForegroundColor Yellow
    Write-Host "  event hub '$EventHubName', Listen-only SAS policy '$PolicyName'" -ForegroundColor Yellow
    $reply = Read-Host "Proceed? [y/N]"
    if ($reply -notmatch '^(y|yes)$') { throw "Aborted." }
}

# --- Ensure the Microsoft.EventHub resource provider is registered -----------------
# First-ever Event Hubs use in a subscription needs the provider registered; best-effort.
try {
    $prov = Get-AzResourceProvider -ProviderNamespace Microsoft.EventHub |
            Select-Object -First 1
    if ($prov.RegistrationState -ne "Registered") {
        Write-Host "Registering resource provider Microsoft.EventHub (one-time per subscription)..." -ForegroundColor Cyan
        Register-AzResourceProvider -ProviderNamespace Microsoft.EventHub | Out-Null
        for ($i = 0; $i -lt 12; $i++) {
            Start-Sleep -Seconds 5
            $prov = Get-AzResourceProvider -ProviderNamespace Microsoft.EventHub |
                    Select-Object -First 1
            if ($prov.RegistrationState -eq "Registered") { break }
        }
    }
} catch {
    Write-Warning "Provider registration did not confirm — continuing; creation may still succeed."
}

# --- Resource group ----------------------------------------------------------------
$rg = Get-AzResourceGroup -Name $ResourceGroup -ErrorAction SilentlyContinue
if ($rg) {
    Write-Host "Resource group '$ResourceGroup' already exists — reusing it." -ForegroundColor Yellow
} else {
    Write-Host "Creating resource group '$ResourceGroup' in $Location..." -ForegroundColor Cyan
    New-AzResourceGroup -Name $ResourceGroup -Location $Location | Out-Null
}

# --- Event Hubs namespace ----------------------------------------------------------
$ns = Get-AzEventHubNamespace -ResourceGroupName $ResourceGroup -Name $NamespaceName -ErrorAction SilentlyContinue
if ($ns) {
    Write-Host "Namespace '$NamespaceName' already exists — reusing it." -ForegroundColor Yellow
} else {
    Write-Host "Creating Event Hubs namespace '$NamespaceName' (SKU $Sku, capacity 1) — takes a minute or two..." -ForegroundColor Cyan
    try {
        New-AzEventHubNamespace -ResourceGroupName $ResourceGroup -Name $NamespaceName `
            -Location $Location -SkuName $Sku -SkuCapacity 1 | Out-Null
    } catch {
        Write-Host "ERROR: could not create namespace '$NamespaceName'." -ForegroundColor Red
        Write-Host "       Namespace names are GLOBALLY unique. If the error below says the name is" -ForegroundColor Red
        Write-Host "       unavailable, re-run with:  -NamespaceName <another-globally-unique-name>" -ForegroundColor Red
        throw
    }
}

# --- Event hub ---------------------------------------------------------------------
$hub = Get-AzEventHub -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
        -Name $EventHubName -ErrorAction SilentlyContinue
if ($hub) {
    Write-Host "Event hub '$EventHubName' already exists — reusing it." -ForegroundColor Yellow
} else {
    Write-Host "Creating event hub '$EventHubName' ($PartitionCount partitions, ${RetentionHours}h retention)..." -ForegroundColor Cyan
    # Retention parameters changed across Az.EventHub versions — detect what this one has.
    $createParams = @{
        ResourceGroupName = $ResourceGroup
        NamespaceName     = $NamespaceName
        Name              = $EventHubName
        PartitionCount    = $PartitionCount
    }
    $cmdParams = (Get-Command New-AzEventHub).Parameters
    if ($cmdParams.ContainsKey("CleanupPolicy") -and $cmdParams.ContainsKey("RetentionTimeInHour")) {
        $createParams.CleanupPolicy       = "Delete"
        $createParams.RetentionTimeInHour = $RetentionHours
    } elseif ($cmdParams.ContainsKey("MessageRetentionInDays")) {
        $createParams.MessageRetentionInDays = 1
    }
    New-AzEventHub @createParams | Out-Null
}

# --- Listen-only SAS policy ON THE EVENT HUB ---------------------------------------
# Hub-level (not namespace-level) so the connection string embeds EntityPath, and
# Listen-only so Ingext holds least-privilege credentials.
$rule = Get-AzEventHubAuthorizationRule -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
         -EventHubName $EventHubName -Name $PolicyName -ErrorAction SilentlyContinue
if ($rule) {
    Write-Host "SAS policy '$PolicyName' already exists — reusing it." -ForegroundColor Yellow
} else {
    Write-Host "Creating Listen-only SAS policy '$PolicyName' on event hub '$EventHubName'..." -ForegroundColor Cyan
    New-AzEventHubAuthorizationRule -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
        -EventHubName $EventHubName -Name $PolicyName -Rights @("Listen") | Out-Null
}

# --- Consumer group (optional) -----------------------------------------------------
$effectiveConsumerGroup = '$Default'
if ($ConsumerGroup) {
    if ($Sku -eq "Basic") {
        Write-Warning "The Basic tier supports only the `$Default consumer group — '$ConsumerGroup' was NOT created."
    } else {
        $cg = Get-AzEventHubConsumerGroup -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
               -EventHubName $EventHubName -Name $ConsumerGroup -ErrorAction SilentlyContinue
        if ($cg) {
            Write-Host "Consumer group '$ConsumerGroup' already exists — reusing it." -ForegroundColor Yellow
        } else {
            Write-Host "Creating consumer group '$ConsumerGroup'..." -ForegroundColor Cyan
            New-AzEventHubConsumerGroup -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
                -EventHubName $EventHubName -Name $ConsumerGroup | Out-Null
        }
        $effectiveConsumerGroup = $ConsumerGroup
    }
}

# --- Fetch the Connection string–primary key ---------------------------------------
$keys = Get-AzEventHubKey -ResourceGroupName $ResourceGroup -NamespaceName $NamespaceName `
         -EventHubName $EventHubName -Name $PolicyName
$connectionString = $keys.PrimaryConnectionString
if (-not $connectionString) {
    throw "Could not read the primary connection string for policy '$PolicyName'."
}

# --- Emit the result ---------------------------------------------------------------
$result = [ordered]@{
    connectionString = $connectionString
    namespace        = $NamespaceName
    eventHub         = $EventHubName
    resourceGroup    = $ResourceGroup
    location         = $Location
    consumerGroup    = $effectiveConsumerGroup
}

Write-Host ""
Write-Host "==================== ingext Azure Event Hubs connection ====================" -ForegroundColor Cyan
Write-Host "Give ""connectionString"" to the Ingext 'Azure Event Hubs' connector (endpoint field)." -ForegroundColor Yellow
Write-Host "Unlike an app secret, it can be re-fetched later from Shared access policies." -ForegroundColor DarkGray
Write-Host ""
$result | ConvertTo-Json
Write-Host ""
Write-Host "Next: create the 'Azure Event Hubs' connector in Fluency / Ingext with this endpoint," -ForegroundColor Cyan
Write-Host "then point Azure diagnostic settings (or other producers) at event hub '$EventHubName'." -ForegroundColor Cyan
