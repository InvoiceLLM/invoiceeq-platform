param(
    [Parameter(Position=0)]
    [string]$Target = "help"
)

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$envPath = Join-Path $scriptDir "Prod_Invoice_LLM\apps\invoice-be\.env"

function Show-AlertStatus {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "   InvoiceLLM Smart Alert Governance Status" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[Channel: EMAIL] (Crucial / Emergency Alerts Only):" -ForegroundColor Red
    Write-Host "  - Container Environment Down (CAE)"
    Write-Host "  - Key Vault Unreachable"
    Write-Host "  - PostgreSQL Disk Full (>85%)"
    Write-Host "  - Container CrashLoopBackOff (5+ restarts)"
    Write-Host "  - DLQ Poison Message (Data loss protection)"
    Write-Host "  - Sustained 5xx Storms (>15 minutes duration, threshold 25)"
    Write-Host ""
    Write-Host "[Channel: DASHBOARD & WORKBOOKS ONLY] (Zero Email Noise):" -ForegroundColor Green
    Write-Host "  - Container CPU Spikes (Auto-scaler handles)"
    Write-Host "  - Container Memory Spikes (Transient bursts)"
    Write-Host "  - PostgreSQL Connections & CPU"
    Write-Host "  - Redis Enterprise Server Load"
    Write-Host "  - Azure OpenAI & DocIntel 429 Retries"
    Write-Host "  - Storage Egress & Availability"
    Write-Host "  - Routine Invoice Processing Complete (Status: COMPLETED)"
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
}

function Set-EnvVar($key, $val) {
    if (Test-Path $envPath) {
        $content = Get-Content $envPath
        if ($content -match "^$key=") {
            $content = $content -replace "^$key=.*", "$key=$val"
        } else {
            $content += "$key=$val"
        }
        Set-Content -Path $envPath -Value $content
        Write-Host "Updated $key=$val in .env" -ForegroundColor Yellow
    }
}

switch ($Target.ToLower()) {
    "alerts-status" {
        Show-AlertStatus
    }
    "alerts-quiet" {
        Set-EnvVar "ENABLE_STAFF_PROCESSING_EMAILS" "false"
        Write-Host "✅ Muted all routine processing emails for testing/dev." -ForegroundColor Green
    }
    "alerts-digest" {
        Set-EnvVar "ENABLE_STAFF_PROCESSING_EMAILS" "true"
        Set-EnvVar "STAFF_NOTIFY_MIN_SEVERITY" "AUDIT_REQUIRED"
        Write-Host "✅ Dashboard routing active: Routine completed invoices go to dashboard; only audit items send email." -ForegroundColor Green
    }
    "alerts-prod" {
        Set-EnvVar "ENABLE_STAFF_PROCESSING_EMAILS" "true"
        Write-Host "✅ Production alert governance active." -ForegroundColor Green
    }
    default {
        Write-Host "Usage: .\make.ps1 [alerts-status | alerts-quiet | alerts-digest | alerts-prod]" -ForegroundColor Cyan
    }
}
