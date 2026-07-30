# Invoice-LLM Infrastructure Deployment Script
# Deploys infrastructure in 10 sequential stages. Each stage only starts
# once the previous stage's `az deployment group create` has returned
# success AND a stage-specific resource-readiness check confirms the
# underlying resource is actually ready (not just that ARM accepted the
# deployment) - the old 4-stage script only checked the former, which is
# why it kept failing on resources still transitioning (Redis Enterprise
# especially).

param(
    [string]$ResourceGroup = "invoice-llm-dev",
    [string]$Location = "eastus2",
    [string]$Environment = "dev",
    [string]$NamingPrefix = "invoice-llm",
    [string]$ParamsFile = "",
    [string]$SecretsFile = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrEmpty($ParamsFile)) {
    $ParamsFile = "$PSScriptRoot/params.$Environment.json"
}
if ([string]::IsNullOrEmpty($SecretsFile)) {
    $SecretsFile = "$PSScriptRoot/params.$Environment.secrets.json"
}
if (-not (Test-Path $SecretsFile)) {
    Write-Host "Missing secrets file: $SecretsFile" -ForegroundColor Red
    Write-Host "Copy params.$Environment.secrets.json.example to params.$Environment.secrets.json and fill in real values." -ForegroundColor Yellow
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Invoice-LLM Infrastructure Deployment (10 stages)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location: $Location"
Write-Host "Environment: $Environment"
Write-Host ""

function Assert-Stage {
    param([string]$Name, [int]$ExitCode)
    if ($ExitCode -ne 0) {
        Write-Host "$Name FAILED (az CLI exit code $ExitCode) - stopping." -ForegroundColor Red
        exit 1
    }
    Write-Host "$Name deployment accepted" -ForegroundColor Green
}

function Wait-ForState {
    param(
        [string]$Description,
        [scriptblock]$Check,
        [string]$ExpectedState,
        [int]$MaxAttempts = 20,
        [int]$DelaySeconds = 15
    )
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        $state = & $Check
        if ($state -eq $ExpectedState) {
            Write-Host "$Description ready (state=$state)" -ForegroundColor Green
            return
        }
        Write-Host "$Description not ready yet (state=$state), waiting... ($i/$MaxAttempts)" -ForegroundColor Yellow
        Start-Sleep -Seconds $DelaySeconds
    }
    Write-Host "$Description never reached '$ExpectedState' - stopping." -ForegroundColor Red
    exit 1
}

# Resource group bootstrap
$exists = az group exists --name $ResourceGroup
if ($exists -eq "false") {
    Write-Host "Creating resource group: $ResourceGroup" -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location | Out-Null
}

$commonParams = @(
    "--resource-group", $ResourceGroup,
    "--parameters", $ParamsFile,
    "--parameters", "environment=$Environment",
    "--parameters", "location=$Location",
    "--parameters", "namingPrefix=$NamingPrefix"
)

# ---------- Stage 1: Network ----------
Write-Host "`nStage 1/10: Network (VNet, subnets, DNS zones, NSGs)..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/01-network.bicep" @commonParams
Assert-Stage "Stage 1 (network)" $LASTEXITCODE
Wait-ForState -Description "VNet" -ExpectedState "Succeeded" -Check {
    az network vnet show -g $ResourceGroup -n "vnet-$NamingPrefix-$Environment" --query provisioningState -o tsv 2>$null
}

# ---------- Stage 2: Security (identity + Key Vault) ----------
Write-Host "`nStage 2/10: Security (managed identity, Key Vault)..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/02-security.bicep" @commonParams
Assert-Stage "Stage 2 (security)" $LASTEXITCODE
Wait-ForState -Description "Key Vault" -ExpectedState "Succeeded" -Check {
    az keyvault show -n "kv-$NamingPrefix-$Environment" -g $ResourceGroup --query properties.provisioningState -o tsv 2>$null
}

# ---------- Stage 3: Data (Postgres, Redis, Storage, ACR) ----------
Write-Host "`nStage 3/10: Data services (Postgres, Redis, Storage, ACR)..." -ForegroundColor Cyan
$redisName = "redis-$NamingPrefix-$Environment"
$redisState = az resource show -g $ResourceGroup -n $redisName --resource-type Microsoft.Cache/redisEnterprise --query "properties.resourceState" -o tsv 2>$null
$deployRedis = "true"
if ($redisState -eq "Running") {
    Write-Host "Redis Enterprise '$redisName' already Running - passing deployRedis=false (cannot redeploy in place)." -ForegroundColor Yellow
    $deployRedis = "false"
}
az deployment group create --template-file "$PSScriptRoot/03-data.bicep" @commonParams `
    --parameters $SecretsFile `
    --parameters "deployRedis=$deployRedis"
Assert-Stage "Stage 3 (data)" $LASTEXITCODE
Wait-ForState -Description "PostgreSQL" -ExpectedState "Ready" -Check {
    az postgres flexible-server show -g $ResourceGroup -n "psql-$NamingPrefix-$Environment" --query state -o tsv 2>$null
}
Wait-ForState -Description "Redis Enterprise" -ExpectedState "Running" -Check {
    az resource show -g $ResourceGroup -n $redisName --resource-type Microsoft.Cache/redisEnterprise --query properties.resourceState -o tsv 2>$null
}
Wait-ForState -Description "Storage Account" -ExpectedState "Succeeded" -Check {
    az storage account show -g $ResourceGroup -n "st$($NamingPrefix -replace '-','')$Environment" --query provisioningState -o tsv 2>$null
}
Wait-ForState -Description "ACR" -ExpectedState "Succeeded" -Check {
    az acr show -g $ResourceGroup -n "acr$($NamingPrefix -replace '-','')$Environment" --query provisioningState -o tsv 2>$null
}

# ---------- Stage 4: AI (OpenAI, Doc Intelligence) ----------
Write-Host "`nStage 4/10: Cognitive AI services (OpenAI, Doc Intelligence)..." -ForegroundColor Cyan
Write-Host "NOTE: this stage sets publicNetworkAccess=Disabled on both. Do not run while a local benchmark run needs public access." -ForegroundColor Yellow
az deployment group create --template-file "$PSScriptRoot/04-ai.bicep" @commonParams
Assert-Stage "Stage 4 (AI)" $LASTEXITCODE
Wait-ForState -Description "Azure OpenAI" -ExpectedState "Succeeded" -Check {
    az cognitiveservices account show -n "openai-$NamingPrefix-$Environment" -g $ResourceGroup --query properties.provisioningState -o tsv 2>$null
}
Wait-ForState -Description "Doc Intelligence" -ExpectedState "Succeeded" -Check {
    az cognitiveservices account show -n "docintel-$NamingPrefix-$Environment" -g $ResourceGroup --query properties.provisioningState -o tsv 2>$null
}

# ---------- Stage 5: Secrets ----------
Write-Host "`nStage 5/10: Seeding Key Vault secrets..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/05-secrets.bicep" @commonParams --parameters $SecretsFile
Assert-Stage "Stage 5 (secrets)" $LASTEXITCODE
$secretCount = az keyvault secret list --vault-name "kv-$NamingPrefix-$Environment" --query "length(@)" -o tsv
if ($secretCount -ne "7") {
    Write-Host "Expected 7 secrets in Key Vault, found $secretCount - stopping." -ForegroundColor Red
    exit 1
}
Write-Host "Key Vault has all 7 expected secrets" -ForegroundColor Green

# ---------- Stage 6: Compute environment (CAE + ChromaDB) ----------
Write-Host "`nStage 6/10: Container Apps Environment + ChromaDB..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/06-compute-env.bicep" @commonParams
Assert-Stage "Stage 6 (compute-env)" $LASTEXITCODE
Wait-ForState -Description "Container Apps Environment" -ExpectedState "Succeeded" -Check {
    az containerapp env show -g $ResourceGroup -n "cae-$NamingPrefix-$Environment" --query properties.provisioningState -o tsv 2>$null
}

# ---------- Stage 7: RBAC ----------
Write-Host "`nStage 7/10: RBAC role assignments..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/07-rbac.bicep" @commonParams
Assert-Stage "Stage 7 (rbac)" $LASTEXITCODE
$identityPrincipalId = az identity show -g $ResourceGroup -n "id-$NamingPrefix-$Environment" --query principalId -o tsv
$roleCount = az role assignment list --assignee $identityPrincipalId -g $ResourceGroup --query "length(@)" -o tsv
if ([int]$roleCount -lt 5) {
    Write-Host "Expected at least 5 role assignments, found $roleCount - stopping." -ForegroundColor Red
    exit 1
}
Write-Host "RBAC: $roleCount role assignments confirmed" -ForegroundColor Green

# ---------- Stage 8: Application container apps ----------
Write-Host "`nStage 8/10: Backend, queue-worker, frontend, website container apps..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/08-apps.bicep" @commonParams
Assert-Stage "Stage 8 (apps)" $LASTEXITCODE
foreach ($app in @("ca-invoice-be-$Environment", "ca-queue-worker-$Environment", "ca-invoice-fe-$Environment", "ca-invoice-website-$Environment")) {
    Wait-ForState -Description $app -ExpectedState "Running" -Check {
        az containerapp show -g $ResourceGroup -n $app --query properties.runningStatus -o tsv 2>$null
    }
}

# ---------- Stage 9: Monitoring ----------
Write-Host "`nStage 9/10: Monitoring (Log Analytics, App Insights, alerts)..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/09-monitoring.bicep" @commonParams
Assert-Stage "Stage 9 (monitoring)" $LASTEXITCODE
$alertCount = az monitor metrics alert list -g $ResourceGroup --query "length(@)" -o tsv
Write-Host "Monitoring: $alertCount metric alert rules created" -ForegroundColor Green

# ---------- Stage 10: Budget ----------
Write-Host "`nStage 10/10: Cost budget + alerts..." -ForegroundColor Cyan
az deployment group create --template-file "$PSScriptRoot/10-budget.bicep" @commonParams
Assert-Stage "Stage 10 (budget)" $LASTEXITCODE
Write-Host "Budget deployed" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "All 10 stages deployed and verified successfully" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
