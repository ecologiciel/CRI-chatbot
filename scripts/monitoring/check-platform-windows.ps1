[CmdletBinding()]
param(
    [string]$HealthUrl = 'https://2-25-21-84.sslip.io/api/v1/health',
    [string]$StateDirectory = (Join-Path $env:LOCALAPPDATA 'ChatbotDemoMonitor'),
    [switch]$NoNotification
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $StateDirectory | Out-Null
$stateFile = Join-Path $StateDirectory 'state.json'
$logFile = Join-Path $StateDirectory 'events.log'
$failures = 0
$wasAlerting = $false
if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
    try {
        $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $failures = [Math]::Max(0, [int]$previous.failures)
        $wasAlerting = [bool]$previous.alerting
    } catch {
        # A damaged state file must not stop the next health check.
    }
}
$healthy = $false
try {
    $response = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 15
    $healthy = $response.status -eq 'healthy'
} catch {
    # This may be a local Internet problem, not necessarily a server outage.
}
if ($healthy) {
    $failures = 0
    $alerting = $false
} else {
    $failures = [Math]::Min($failures + 1, 1000)
    $alerting = $failures -ge 2
}
$state = [ordered]@{ checked_utc = [DateTime]::UtcNow.ToString('o'); failures = $failures; alerting = $alerting; healthy = $healthy }
$tempFile = Join-Path $StateDirectory ('state-' + [guid]::NewGuid().ToString('N') + '.tmp')
$state | ConvertTo-Json -Compress | Set-Content -LiteralPath $tempFile -Encoding UTF8
Move-Item -LiteralPath $tempFile -Destination $stateFile -Force
if ($alerting -ne $wasAlerting) {
    $message = if ($alerting) {
        'La plateforme ne répond pas correctement depuis ce PC. Vérifiez aussi votre connexion Internet.'
    } else {
        'La plateforme répond de nouveau depuis ce PC.'
    }
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("{0} {1}" -f [DateTime]::UtcNow.ToString('o'), $message)
    if (-not $NoNotification) {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            Add-Type -AssemblyName System.Drawing
            $notification = New-Object System.Windows.Forms.NotifyIcon
            $notification.Icon = [System.Drawing.SystemIcons]::Information
            $notification.Visible = $true
            $notification.ShowBalloonTip(10000, 'Surveillance chatbot', $message, [System.Windows.Forms.ToolTipIcon]::Warning)
            Start-Sleep -Seconds 12
            $notification.Dispose()
        } catch {
            Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("{0} Notification Windows indisponible." -f [DateTime]::UtcNow.ToString('o'))
        }
    }
}
if ($healthy) { Write-Output 'HEALTH_OK'; exit 0 }
Write-Output ("HEALTH_FAILED consecutive={0} alerting={1}" -f $failures, $alerting)
exit 1
