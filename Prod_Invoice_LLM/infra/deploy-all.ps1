# Invoice-LLM Infrastructure Deployment Script
# Deploys infrastructure in 4 stages to avoid circular dependencies

param(
    [string]$ResourceGroup = "invoice-llm-dev",
    [string]$Location = "eastus2",
    [string]$Environment = "dev",
    [string]$NamingPrefix = "invoice-llm",
    [string]$ParamsFile = ""
)

# Error handling
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrEmpty($ParamsFile)) {
    $ParamsFile = "$PSScriptRoot/params.dev.json"
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Invoice-LLM Infrastructure Deployment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location: $Location"
Write-Host "Environment: $Environment"
Write-Host ""

# Check if resource group exists
$exists = az group exists --name $ResourceGroup
if ($exists -eq "false") {
    Write-Host "Creating resource group: $ResourceGroup" -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location | Out-Null
    Write-Host "Resource group created successfully" -ForegroundColor Green
} else {
    Write-Host "Resource group already exists: $ResourceGroup" -ForegroundColor Green
}

# Step 1: Core Infrastructure
Write-Host ""
Write-Host "Step 1: Deploying Core Infrastructure (VNet, Identities, Key Vault, Data Services)..." -ForegroundColor Cyan
Write-Host "This may take 10-15 minutes..." -ForegroundColor Yellow

$step1Output = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main-step1.bicep" `
    --parameters $ParamsFile `
    --parameters environment=$Environment `
    --parameters location=$Location `
    --parameters namingPrefix=$NamingPrefix

if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 1 failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Step 1 completed successfully" -ForegroundColor Green

# Extract outputs from Step 1
$keyVaultName = ($step1Output | ConvertFrom-Json).properties.outputs.keyVaultName.value
$identityId = ($step1Output | ConvertFrom-Json).properties.outputs.identityId.value
$identityClientId = ($step1Output | ConvertFrom-Json).properties.outputs.identityClientId.value
$vnetName = ($step1Output | ConvertFrom-Json).properties.outputs.vnetName.value
$storageAccountName = ($step1Output | ConvertFrom-Json).properties.outputs.storageAccountName.value
$acrName = ($step1Output | ConvertFrom-Json).properties.outputs.acrName.value

Write-Host "Key Vault: $keyVaultName" -ForegroundColor Gray
Write-Host "Identity ID: $identityId" -ForegroundColor Gray
Write-Host "VNet: $vnetName" -ForegroundColor Gray

# Get storage account key for Step 3
$storageAccountKey = az storage account keys list `
    --resource-group $ResourceGroup `
    --account-name $storageAccountName `
    --query '[0].value' -o tsv

# Step 2: AI Services
Write-Host ""
Write-Host "Step 2: Deploying AI Services (OpenAI, Document Intelligence)..." -ForegroundColor Cyan
Write-Host "This may take 5-10 minutes..." -ForegroundColor Yellow

$step2Output = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main-step2.bicep" `
    --parameters environment=$Environment `
    --parameters location=$Location `
    --parameters namingPrefix=$NamingPrefix `
    --parameters azureOpenAiModelVersion="2025-08-07" `
    --parameters vnetName=$vnetName

if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 2 failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Step 2 completed successfully" -ForegroundColor Green

# Extract outputs from Step 2
$openaiEndpoint = ($step2Output | ConvertFrom-Json).properties.outputs.openaiEndpoint.value
$docIntelEndpoint = ($step2Output | ConvertFrom-Json).properties.outputs.docIntelEndpoint.value

Write-Host "OpenAI Endpoint: $openaiEndpoint" -ForegroundColor Gray
Write-Host "Doc Intel Endpoint: $docIntelEndpoint" -ForegroundColor Gray

# Add API Keys to Key Vault (Post-Step 2)
Write-Host ""
Write-Host "Adding API Keys to Key Vault..." -ForegroundColor Cyan

# Get OpenAI API key
$openaiKey = az cognitiveservices account keys list `
    --name "openai-$NamingPrefix-$Environment" `
    --resource-group $ResourceGroup `
    --query key1 -o tsv

az keyvault secret set `
    --vault-name $keyVaultName `
    --name AZURE-OPENAI-API-KEY `
    --value $openaiKey | Out-Null

Write-Host "OpenAI API key added to Key Vault" -ForegroundColor Green

# Get Document Intelligence key
$docIntelKey = az cognitiveservices account keys list `
    --name "docintel-$NamingPrefix-$Environment" `
    --resource-group $ResourceGroup `
    --query key1 -o tsv

az keyvault secret set `
    --vault-name $keyVaultName `
    --name AZURE-DOC-INTEL-KEY `
    --value $docIntelKey | Out-Null

Write-Host "Document Intelligence API key added to Key Vault" -ForegroundColor Green

# Step 3: Container Apps Environment + ChromaDB
Write-Host ""
Write-Host "Step 3: Deploying Container Apps Environment + ChromaDB..." -ForegroundColor Cyan
Write-Host "This may take 5-10 minutes..." -ForegroundColor Yellow

$step3Output = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main-step3.bicep" `
    --parameters environment=$Environment `
    --parameters location=$Location `
    --parameters namingPrefix=$NamingPrefix `
    --parameters vnetName=$vnetName `
    --parameters identityId=$identityId `
    --parameters storageAccountName=$storageAccountName `
    --parameters storageAccountKey=$storageAccountKey

if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 3 failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Step 3 completed successfully" -ForegroundColor Green

# Extract outputs from Step 3
$caeId = ($step3Output | ConvertFrom-Json).properties.outputs.caeId.value
$chromaDbFqdn = ($step3Output | ConvertFrom-Json).properties.outputs.chromaDbFqdn.value

Write-Host "CAE ID: $caeId" -ForegroundColor Gray
Write-Host "ChromaDB FQDN: $chromaDbFqdn" -ForegroundColor Gray

# Step 4: Container Apps + RBAC
Write-Host ""
Write-Host "Step 4: Deploying Container Apps + RBAC..." -ForegroundColor Cyan
Write-Host "This may take 5-10 minutes..." -ForegroundColor Yellow

# Get parameter values from params file
$params = Get-Content $ParamsFile | ConvertFrom-Json
$nextPublicClerkPublishableKey = $params.parameters.nextPublicClerkPublishableKey.value
$backendImage = $params.parameters.backendImage.value
$celeryWorkerImage = $params.parameters.celeryWorkerImage.value
$frontendImage = $params.parameters.frontendImage.value

$step4Output = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main-step4.bicep" `
    --parameters environment=$Environment `
    --parameters location=$Location `
    --parameters namingPrefix=$NamingPrefix `
    --parameters nextPublicClerkPublishableKey=$nextPublicClerkPublishableKey `
    --parameters azureOpenAiEndpoint=$openaiEndpoint `
    --parameters azureOpenAiDeploymentName="gpt-5-mini" `
    --parameters azureDocIntelEndpoint=$docIntelEndpoint `
    --parameters backendImage=$backendImage `
    --parameters celeryWorkerImage=$celeryWorkerImage `
    --parameters frontendImage=$frontendImage `
    --parameters vnetName=$vnetName `
    --parameters identityId=$identityId `
    --parameters identityClientId=$identityClientId `
    --parameters keyVaultName=$keyVaultName `
    --parameters storageAccountName=$storageAccountName `
    --parameters acrName=$acrName `
    --parameters caeId=$caeId `
    --parameters chromaDbFqdn=$chromaDbFqdn

if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 4 failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Step 4 completed successfully" -ForegroundColor Green

# Extract final outputs
$frontendUrl = ($step4Output | ConvertFrom-Json).properties.outputs.frontendUrl.value
$backendUrl = ($step4Output | ConvertFrom-Json).properties.outputs.backendUrl.value

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Deployment Completed Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Frontend URL: https://$frontendUrl" -ForegroundColor Yellow
Write-Host "Backend URL: https://$backendUrl" -ForegroundColor Yellow
Write-Host "Key Vault: $keyVaultName" -ForegroundColor Gray
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Build and push container images to ACR" -ForegroundColor White
Write-Host "2. Run Alembic migrations on PostgreSQL" -ForegroundColor White
Write-Host "3. Test the application endpoints" -ForegroundColor White
