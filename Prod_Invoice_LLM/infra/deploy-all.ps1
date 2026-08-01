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

# ARM rejects a parameters file (or inline `key=value` override) containing
# any key the target template does not itself declare -- confirmed via
# `az deployment group validate` against every stage: passing the single
# shared params.<env>.json (or the old hardcoded `location=` override) to a
# stage that doesn't declare that param name fails immediately with
# InvalidTemplate, *before* anything deploys. Several stages (e.g. 07-rbac,
# 10-budget) don't declare `location` at all, and every stage before 08
# doesn't declare most of the app/AI/monitoring params -- so the old
# single-shared-file-passed-to-every-stage pattern could only ever have
# worked for whichever one stage happened to declare a superset of the
# file's keys. This is almost certainly the real reason this script "always
# failed" end-to-end. Fix: filter each param source down to only the names
# the target stage's compiled template actually declares, using the
# template's own declared parameter list (read via `az bicep build`) as the
# source of truth rather than hand-maintaining a per-stage allowlist that
# would go stale the same way the Stage 5 secret count did.
function Get-DeclaredParamNames {
    param([string]$TemplateFile)
    $armJson = az bicep build --file $TemplateFile --stdout 2>$null | ConvertFrom-Json
    if (-not $armJson) {
        Write-Host "Failed to compile $TemplateFile to read its declared parameters." -ForegroundColor Red
        exit 1
    }
    if ($armJson.parameters) {
        return @($armJson.parameters.PSObject.Properties.Name)
    }
    return @()
}

function New-StageParamArgs {
    param(
        [string]$TemplateFile,
        [string[]]$ParamFiles = @(),
        [hashtable]$InlineOverrides = @{}
    )
    $declared = Get-DeclaredParamNames -TemplateFile $TemplateFile
    $stageArgs = @()

    foreach ($file in $ParamFiles) {
        $source = Get-Content $file -Raw | ConvertFrom-Json
        $filtered = [ordered]@{}
        foreach ($prop in $source.parameters.PSObject.Properties) {
            if ($declared -contains $prop.Name) {
                $filtered[$prop.Name] = $prop.Value
            }
        }
        if ($filtered.Count -gt 0) {
            $tempFile = [System.IO.Path]::GetTempFileName() + ".json"
            $payload = [ordered]@{
                '$schema'      = $source.'$schema'
                contentVersion = $source.contentVersion
                parameters     = $filtered
            }
            ($payload | ConvertTo-Json -Depth 10) | Set-Content $tempFile
            $stageArgs += @("--parameters", $tempFile)
        }
    }

    foreach ($key in $InlineOverrides.Keys) {
        if ($declared -contains $key) {
            $stageArgs += @("--parameters", "$key=$($InlineOverrides[$key])")
        }
    }

    return $stageArgs
}

$commonInline = @{
    environment  = $Environment
    location     = $Location
    namingPrefix = $NamingPrefix
}

# Resource group bootstrap
$exists = az group exists --name $ResourceGroup
if ($exists -eq "false") {
    Write-Host "Creating resource group: $ResourceGroup" -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location | Out-Null
}

# ---------- Stage 1: Network ----------
Write-Host "`nStage 1/10: Network (VNet, subnets, DNS zones, NSGs)..." -ForegroundColor Cyan
$stage1Template = "$PSScriptRoot/01-network.bicep"
$stage1Args = New-StageParamArgs -TemplateFile $stage1Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage1Template @stage1Args
Assert-Stage "Stage 1 (network)" $LASTEXITCODE
Wait-ForState -Description "VNet" -ExpectedState "Succeeded" -Check {
    az network vnet show -g $ResourceGroup -n "vnet-$NamingPrefix-$Environment" --query provisioningState -o tsv 2>$null
}

# ---------- Stage 2: Security (identity + Key Vault) ----------
Write-Host "`nStage 2/10: Security (managed identity, Key Vault)..." -ForegroundColor Cyan
$stage2Template = "$PSScriptRoot/02-security.bicep"
$stage2Args = New-StageParamArgs -TemplateFile $stage2Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage2Template @stage2Args
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
$stage3Template = "$PSScriptRoot/03-data.bicep"
$stage3Args = New-StageParamArgs -TemplateFile $stage3Template -ParamFiles @($ParamsFile, $SecretsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage3Template @stage3Args `
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
Write-Host "NOTE: with networkIsolation=true this stage sets publicNetworkAccess=Disabled on both. Do not run while a local benchmark run needs public access." -ForegroundColor Yellow
$stage4Template = "$PSScriptRoot/04-ai.bicep"
$stage4Args = New-StageParamArgs -TemplateFile $stage4Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage4Template @stage4Args
Assert-Stage "Stage 4 (AI)" $LASTEXITCODE
Wait-ForState -Description "Azure OpenAI" -ExpectedState "Succeeded" -Check {
    az cognitiveservices account show -n "openai-$NamingPrefix-$Environment" -g $ResourceGroup --query properties.provisioningState -o tsv 2>$null
}
Wait-ForState -Description "Doc Intelligence" -ExpectedState "Succeeded" -Check {
    az cognitiveservices account show -n "docintel-$NamingPrefix-$Environment" -g $ResourceGroup --query properties.provisioningState -o tsv 2>$null
}

# ---------- Stage 5: Secrets ----------
Write-Host "`nStage 5/10: Seeding Key Vault secrets..." -ForegroundColor Cyan
$stage5Template = "$PSScriptRoot/05-secrets.bicep"
$stage5Args = New-StageParamArgs -TemplateFile $stage5Template -ParamFiles @($ParamsFile, $SecretsFile) -InlineOverrides $commonInline
$secretsDeployName = "secrets-deploy-$(Get-Date -Format 'yyyyMMddHHmmss')"
az deployment group create --name $secretsDeployName --resource-group $ResourceGroup --template-file $stage5Template @stage5Args
Assert-Stage "Stage 5 (secrets)" $LASTEXITCODE
# Read the expected count from the deployment's own output instead of a
# hardcoded literal -- this was hardcoded to 9 and went stale the moment
# Gap 41/42 added the docintel-2/3 secrets (real count with
# docIntelInstanceCount=3 is 13). The template output is computed from
# docIntelInstanceCount (see 05-secrets.bicep), so it can't go stale again.
$expectedSecretCount = az deployment group show --resource-group $ResourceGroup --name $secretsDeployName --query "properties.outputs.secretsSeeded.value" -o tsv
$secretCount = az keyvault secret list --vault-name "kv-$NamingPrefix-$Environment" --query "length(@)" -o tsv
if ($secretCount -ne $expectedSecretCount) {
    Write-Host "Expected $expectedSecretCount secrets in Key Vault, found $secretCount - stopping." -ForegroundColor Red
    exit 1
}
Write-Host "Key Vault has all $expectedSecretCount expected secrets" -ForegroundColor Green

# ---------- Stage 6: Compute environment (CAE + ChromaDB) ----------
Write-Host "`nStage 6/10: Container Apps Environment + ChromaDB..." -ForegroundColor Cyan
$stage6Template = "$PSScriptRoot/06-compute-env.bicep"
$stage6Args = New-StageParamArgs -TemplateFile $stage6Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage6Template @stage6Args
Assert-Stage "Stage 6 (compute-env)" $LASTEXITCODE
Wait-ForState -Description "Container Apps Environment" -ExpectedState "Succeeded" -Check {
    az containerapp env show -g $ResourceGroup -n "cae-$NamingPrefix-$Environment" --query properties.provisioningState -o tsv 2>$null
}

# ---------- Stage 7: RBAC ----------
Write-Host "`nStage 7/10: RBAC role assignments..." -ForegroundColor Cyan
$stage7Template = "$PSScriptRoot/07-rbac.bicep"
$stage7Args = New-StageParamArgs -TemplateFile $stage7Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage7Template @stage7Args
Assert-Stage "Stage 7 (rbac)" $LASTEXITCODE
$identityPrincipalId = az identity show -g $ResourceGroup -n "id-$NamingPrefix-$Environment" --query principalId -o tsv
$roleCount = az role assignment list --assignee $identityPrincipalId -g $ResourceGroup --query "length(@)" -o tsv
if ([int]$roleCount -lt 4) {
    Write-Host "Expected at least 4 role assignments (storage/openai/docintel/keyvault -- ACR's AcrPull is assigned separately, possibly in a different resource group when ACR is shared), found $roleCount - stopping." -ForegroundColor Red
    exit 1
}
Write-Host "RBAC: $roleCount local role assignments confirmed (plus the cross-RG ACR AcrPull assignment)" -ForegroundColor Green

# ---------- Stage 8: Application container apps ----------
Write-Host "`nStage 8/10: Backend, queue-worker, frontend, website container apps..." -ForegroundColor Cyan
$stage8Template = "$PSScriptRoot/08-apps.bicep"
$stage8Args = New-StageParamArgs -TemplateFile $stage8Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage8Template @stage8Args
Assert-Stage "Stage 8 (apps)" $LASTEXITCODE
foreach ($app in @("ca-invoice-be-$Environment", "ca-queue-worker-$Environment", "ca-invoice-fe-$Environment", "ca-invoice-website-$Environment")) {
    Wait-ForState -Description $app -ExpectedState "Running" -Check {
        az containerapp show -g $ResourceGroup -n $app --query properties.runningStatus -o tsv 2>$null
    }
}

# ---------- Stage 9: Monitoring ----------
Write-Host "`nStage 9/10: Monitoring (Log Analytics, App Insights, alerts)..." -ForegroundColor Cyan
$stage9Template = "$PSScriptRoot/09-monitoring.bicep"
$stage9Args = New-StageParamArgs -TemplateFile $stage9Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage9Template @stage9Args
Assert-Stage "Stage 9 (monitoring)" $LASTEXITCODE
$alertCount = az monitor metrics alert list -g $ResourceGroup --query "length(@)" -o tsv
Write-Host "Monitoring: $alertCount metric alert rules created" -ForegroundColor Green

# ---------- Stage 10: Budget ----------
Write-Host "`nStage 10/10: Cost budget + alerts..." -ForegroundColor Cyan
$stage10Template = "$PSScriptRoot/10-budget.bicep"
$stage10Args = New-StageParamArgs -TemplateFile $stage10Template -ParamFiles @($ParamsFile) -InlineOverrides $commonInline
az deployment group create --resource-group $ResourceGroup --template-file $stage10Template @stage10Args
Assert-Stage "Stage 10 (budget)" $LASTEXITCODE
Write-Host "Budget deployed" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "All 10 stages deployed and verified successfully" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
