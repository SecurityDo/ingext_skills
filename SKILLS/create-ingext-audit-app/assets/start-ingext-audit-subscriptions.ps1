<#
.SYNOPSIS
  Stage 2 of Ingext / Fluency onboarding: start the Office 365 Management Activity API
  content subscriptions that the "ingext-audit" app registration will poll.

.DESCRIPTION
  Stage 1 (setup-ingext-audit.ps1 or setup-ingext-audit.sh) registers the app and returns
  tenantId / clientId / clientSecret. Those three fields alone do NOT produce data: the
  Office 365 Management Activity API emits nothing until a subscription is STARTED for each
  content type. This script does that, app-only (client credentials) - no admin sign-in.

  For each content type it POSTs to
    https://manage.office.com/api/v1.0/{tenantId}/activity/feed/subscriptions/start
  then re-reads /subscriptions/list and prints the resulting status for every type.

  Idempotent: a content type that is already enabled reports AF20023 ("already enabled"),
  which is treated as success, not an error. Safe to re-run.

  Default content types:
    Audit.AzureActiveDirectory   sign-ins, directory changes
    Audit.Exchange               mailbox + Exchange admin activity
    Audit.SharePoint             SharePoint / OneDrive file activity
    Audit.General                Teams, Power BI, DLP-free general workloads
    DLP.All                      DLP policy match events (needs ActivityFeed.ReadDlp)

.PREREQUISITES
  - PowerShell 5.1 or 7+. No modules required - raw REST only.
  - The ingext-audit app must already exist WITH ADMIN CONSENT GRANTED for
    ActivityFeed.Read (and ActivityFeed.ReadDlp for DLP.All). Consent is what puts the
    roles in the token; without it every start returns AF20055 / 401.
  - Unified audit logging must be ON for the tenant (Purview > Audit > "Start recording
    user and admin activity"), and the tenant needs a real Exchange Online licence.
    If ingestion is off, start returns AF20024 or the misleading
    "Tenant <guid> does not exist" - see the guidance the script prints for that case.

.PARAMETER FromJson
  Path to the JSON emitted by stage 1 ({ tenantId, clientId, clientSecret }). Any of
  -TenantId / -ClientId / -ClientSecret given explicitly override the file.

.PARAMETER Action
  Start (default), List (report only, changes nothing), or Stop (disable subscriptions).

.EXAMPLE
  ./start-ingext-audit-subscriptions.ps1 -FromJson ./ingext-audit.json

.EXAMPLE
  ./start-ingext-audit-subscriptions.ps1 -TenantId <guid> -ClientId <guid>
  # prompts for the secret without echoing it

.EXAMPLE
  ./start-ingext-audit-subscriptions.ps1 -FromJson ./ingext-audit.json -Action List

.EXAMPLE
  ./start-ingext-audit-subscriptions.ps1 -FromJson ./c.json -ContentTypes Audit.Exchange,Audit.SharePoint
#>

[CmdletBinding()]
param(
    [string]   $FromJson,
    [string]   $TenantId,
    [string]   $ClientId,
    [string]   $ClientSecret,

    [ValidateSet("Audit.AzureActiveDirectory", "Audit.Exchange", "Audit.SharePoint",
                 "Audit.General", "DLP.All")]
    [string[]] $ContentTypes = @("Audit.AzureActiveDirectory", "Audit.Exchange",
                                 "Audit.SharePoint", "Audit.General", "DLP.All"),

    [ValidateSet("Start", "List", "Stop")]
    [string]   $Action = "Start",

    # Optional webhook. Omit it (the default) for Ingext - Ingext polls the feed.
    [string]   $WebhookAddress
)

$ErrorActionPreference = "Stop"
$ApiBase = "https://manage.office.com/api/v1.0"

# Windows PowerShell 5.1 can still default to TLS 1.0, which Entra and manage.office.com
# reject outright. Force TLS 1.2 before the first call.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

# --- Gather credentials ----------------------------------------------------------
if ($FromJson) {
    if (-not (Test-Path -LiteralPath $FromJson)) { throw "Credential file not found: $FromJson" }
    $creds = Get-Content -LiteralPath $FromJson -Raw | ConvertFrom-Json
    if (-not $TenantId)     { $TenantId     = $creds.tenantId }
    if (-not $ClientId)     { $ClientId     = $creds.clientId }
    if (-not $ClientSecret) { $ClientSecret = $creds.clientSecret }
}
if (-not $TenantId) { $TenantId = Read-Host "Tenant ID (GUID)" }
if (-not $ClientId) { $ClientId = Read-Host "Client ID (GUID)" }
if (-not $ClientSecret) {
    # Read as SecureString so the secret never lands in console history.
    $secure       = Read-Host "Client secret (hidden)" -AsSecureString
    $bstr         = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try   { $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
foreach ($pair in @(@{n="TenantId";v=$TenantId}, @{n="ClientId";v=$ClientId})) {
    if ($pair.v -notmatch '^[0-9a-fA-F-]{36}$') { throw "$($pair.n) does not look like a GUID: $($pair.v)" }
}

# --- Helper: pull the O365 error code/message out of a failed REST call -----------
# PS7 fills ErrorDetails.Message; PS5.1 needs the raw response stream.
function Get-RestErrorDetail {
    param($ErrorRecord)

    $raw = $null
    if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
        $raw = $ErrorRecord.ErrorDetails.Message
    } elseif ($ErrorRecord.Exception.PSObject.Properties.Name -contains "Response" -and
              $ErrorRecord.Exception.Response) {
        try {
            $stream = $ErrorRecord.Exception.Response.GetResponseStream()
            $raw    = (New-Object System.IO.StreamReader($stream)).ReadToEnd()
        } catch { }
    }

    $code    = $null
    $message = $ErrorRecord.Exception.Message
    if ($raw) {
        try {
            $parsed = $raw | ConvertFrom-Json
            # The API returns either { error: { code, message } } or a bare { code, message }.
            $node    = if ($parsed.PSObject.Properties.Name -contains "error") { $parsed.error } else { $parsed }
            $code    = $node.code
            $message = $node.message
        } catch { $message = $raw }
    }
    [pscustomobject]@{ Code = $code; Message = $message; Raw = $raw }
}

# --- Acquire an app-only token for the Management Activity API --------------------
Write-Host "Requesting app-only token for https://manage.office.com ..." -ForegroundColor Cyan
try {
    $token = Invoke-RestMethod -Method POST `
        -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
        -ContentType "application/x-www-form-urlencoded" `
        -Body @{
            client_id     = $ClientId
            client_secret = $ClientSecret
            scope         = "https://manage.office.com/.default"
            grant_type    = "client_credentials"
        }
} catch {
    $d = Get-RestErrorDetail $_
    throw "Token request failed: $($d.Message)`nCheck tenantId/clientId/clientSecret (a rotated or expired secret gives AADSTS7000215)."
}
$headers = @{ Authorization = "Bearer $($token.access_token)" }

# --- Preflight: confirm the token actually carries the ActivityFeed roles ---------
# Consent is the #1 failure here, and the token says plainly whether it was granted.
$grantedRoles = @()
try {
    $payload = $token.access_token.Split(".")[1].Replace("-", "+").Replace("_", "/")
    switch ($payload.Length % 4) { 2 { $payload += "==" } 3 { $payload += "=" } }
    $claims       = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
    $grantedRoles = @($claims.roles | Where-Object { $_ })
} catch {
    Write-Verbose "Could not decode token claims; skipping the consent preflight."
}
if ($grantedRoles.Count) {
    Write-Host "  Token roles: $($grantedRoles -join ', ')" -ForegroundColor DarkGray
    if ($grantedRoles -notcontains "ActivityFeed.Read") {
        Write-Warning "Token has no ActivityFeed.Read role - admin consent is missing. Re-run stage 1 or grant consent in Entra, then retry."
    }
    if (($ContentTypes -contains "DLP.All") -and ($grantedRoles -notcontains "ActivityFeed.ReadDlp")) {
        Write-Warning "Token has no ActivityFeed.ReadDlp role - DLP.All will fail until that permission is consented."
    }
}

# --- Subscription calls ----------------------------------------------------------
$tenantBase = "$ApiBase/$TenantId/activity/feed/subscriptions"
$publisher  = $TenantId   # PublisherIdentifier scopes throttling to this tenant

function Invoke-Subscription {
    param([string] $Op, [string] $ContentType)

    $uri = "$tenantBase/$Op" + "?contentType=$ContentType&PublisherIdentifier=$publisher"
    $req = @{ Method = "POST"; Uri = $uri; Headers = $headers }
    if ($Op -eq "start" -and $WebhookAddress) {
        $req.Body        = (@{ webhook = @{ address = $WebhookAddress; authId = "ingext" } } | ConvertTo-Json -Depth 4)
        $req.ContentType = "application/json"
    }
    Invoke-RestMethod @req
}

$results = @()
if ($Action -ne "List") {
    $verb = $Action.ToLower()
    Write-Host "`n$($Action)ing $($ContentTypes.Count) content type(s) on tenant $TenantId ..." -ForegroundColor Cyan

    foreach ($ct in $ContentTypes) {
        try {
            Invoke-Subscription -Op $verb -ContentType $ct | Out-Null
            Write-Host "  + $ct - $verb ok" -ForegroundColor Green
            $results += [pscustomobject]@{ contentType = $ct; result = "ok"; detail = $null }
        } catch {
            $d    = Get-RestErrorDetail $_
            $code = if ($d.Code) { $d.Code } else { "" }

            if ($code -eq "AF20023") {
                # Already in the requested state - the desired end state, so not a failure.
                Write-Host "  = $ct - already in the requested state" -ForegroundColor DarkGray
                $results += [pscustomobject]@{ contentType = $ct; result = "ok"; detail = "no change needed" }

            } elseif ($d.Message -match "does not exist") {
                # "Tenant <guid> does not exist" does NOT mean the tenant ID is wrong. The
                # Audit API returns it when the tenant has no unified audit log store - either
                # ingestion was never switched on, or the tenant has no real Exchange Online
                # licence (AAD_PREMIUM alone carries only EXCHANGE_S_FOUNDATION), in which case
                # the Activity API cannot serve it at all.
                Write-Host "  ! $ct - tenant has no unified audit log store" -ForegroundColor Red
                Write-Host ""
                Write-Host "    Despite the wording, the tenant ID is fine. Check ingestion from" -ForegroundColor Yellow
                Write-Host "    Exchange Online PowerShell:" -ForegroundColor Yellow
                Write-Host "        Connect-ExchangeOnline" -ForegroundColor Gray
                Write-Host "        Get-AdminAuditLogConfig | Format-List UnifiedAuditLogIngestionEnabled" -ForegroundColor Gray
                Write-Host "    If False, enable it and allow time to propagate:" -ForegroundColor Yellow
                Write-Host "        Set-AdminAuditLogConfig -UnifiedAuditLogIngestionEnabled " -NoNewline -ForegroundColor Gray
                Write-Host '$true' -ForegroundColor Gray
                Write-Host "    If Connect-ExchangeOnline fails, or the tenant has no Exchange Online" -ForegroundColor Yellow
                Write-Host "    licence, this API will never serve it - use Graph-based Entra audit." -ForegroundColor Yellow
                Write-Host ""
                $results += [pscustomobject]@{ contentType = $ct; result = "failed"; detail = "no unified audit log store (tenant 'does not exist')" }

            } elseif ($code -eq "AF20024") {
                Write-Host "  ! $ct - $($d.Message)" -ForegroundColor Red
                Write-Warning "AF20024 usually means unified audit logging is OFF for this tenant. Enable it in Purview > Audit, wait a few minutes, then re-run."
                $results += [pscustomobject]@{ contentType = $ct; result = "failed"; detail = "AF20024: $($d.Message)" }

            } else {
                $label = if ($d.Code) { "$($d.Code): $($d.Message)" } else { $d.Message }
                Write-Host "  ! $ct - $label" -ForegroundColor Red
                $results += [pscustomobject]@{ contentType = $ct; result = "failed"; detail = $label }
            }
        }
    }
}

# --- Verify: read back what the tenant actually reports ---------------------------
Write-Host "`nReading current subscription list ..." -ForegroundColor Cyan
try {
    $list = @(Invoke-RestMethod -Method GET -Headers $headers `
        -Uri "$tenantBase/list?PublisherIdentifier=$publisher")
} catch {
    $d     = Get-RestErrorDetail $_
    $label = if ($d.Code) { "$($d.Code): $($d.Message)" } else { $d.Message }
    throw "subscriptions/list failed: $label"
}

$status = foreach ($ct in $ContentTypes) {
    $entry = $list | Where-Object { $_.contentType -eq $ct }
    [pscustomobject]@{
        contentType = $ct
        status      = if ($entry) { $entry.status } else { "not subscribed" }
    }
}
$status | Format-Table -AutoSize | Out-String | Write-Host

$enabled = @($status | Where-Object { $_.status -eq "enabled" })
$failed  = @($results | Where-Object { $_.result -eq "failed" })

# --- Machine-readable summary ----------------------------------------------------
Write-Host "==================== ingext-audit subscriptions ====================" -ForegroundColor Cyan
[ordered]@{
    tenantId      = $TenantId
    clientId      = $ClientId
    action        = $Action
    requested     = $ContentTypes
    enabled       = @($enabled.contentType)
    failed        = @($failed.contentType)
} | ConvertTo-Json -Depth 4

if ($failed.Count) {
    Write-Host ""
    Write-Warning "$($failed.Count) content type(s) did not $($Action.ToLower()): $($failed.contentType -join ', '). See the messages above."
    exit 1
}
if ($Action -eq "Start") {
    Write-Host "`nAll requested content types are enabled. Events accumulate from now on -" -ForegroundColor Green
    Write-Host "the feed is not retroactive, and the first content blobs can take up to ~24h to appear." -ForegroundColor Green
}
