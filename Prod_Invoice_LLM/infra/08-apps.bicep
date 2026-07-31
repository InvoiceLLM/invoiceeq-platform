targetScope = 'resourceGroup'

// ================= Stage 8: Application Container Apps =================
// Backend, queue-worker, frontend. Depends on Stage 6 (CAE + ChromaDB)
// and Stage 7 (RBAC — so the identity can actually pull images / read
// secrets by the time these apps start). All cross-stage values (CAE id,
// ChromaDB FQDN, identity IDs, OpenAI/DocIntel endpoints) are read via
// `existing` resource references instead of being threaded through the
// orchestrator script as deployment outputs.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Clerk SSO Publishable Client Key')
param nextPublicClerkPublishableKey string

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Image tag for backend API container')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for queue worker container')
param queueWorkerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for frontend container')
param frontendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for website container')
param websiteImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Clerk JWT issuer URL (public) -- see invoice-be.bicep for why this is not a secret')
param clerkJwtIssuer string = ''

@description('Clerk JWKS endpoint URL (public)')
param clerkJwksUrl string = ''

@description('Our company Google Cloud OAuth Client ID (connectors: Drive) -- public value, see invoice-be.bicep')
param googleClientId string = ''

@description('Our company Salesforce Connected App Consumer Key (connectors) -- public value, see invoice-be.bicep')
param salesforceClientId string = ''

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName
}

// FE/website FQDNs, computed rather than read from backendApp/frontendApp
// module outputs. Container App FQDNs are `<app-name>.<cae-default-domain>`,
// and the CAE (an `existing` reference, already deployed by an earlier stage)
// exposes that domain directly -- so both names are knowable before either
// app deploys. This matters because backendApp needs the FE/website origins
// for ALLOWED_ORIGINS, and frontendApp needs backendApp's fqdn for
// BACKEND_API_URL -- a real circular dependency if either side tried to read
// the other's module output instead.
var frontendFqdn = 'ca-invoice-fe-${environment}.${cae.properties.defaultDomain}'
var websiteFqdn = 'ca-invoice-website-${environment}.${cae.properties.defaultDomain}'

// OAuth redirect URIs must be the FE's public origin, not the backend's --
// backendApp's ingress is external:false (internal-only), so Google/Salesforce
// redirect the browser back to the FE, whose own /api/connectors/callback/
// [provider] route proxies through to the backend's real callback endpoint.
var googleRedirectUri = 'https://${frontendFqdn}/api/connectors/callback/google_drive'
var salesforceRedirectUri = 'https://${frontendFqdn}/api/connectors/callback/salesforce'

module backendApp './modules/compute/invoice-be.bicep' = {
  name: 'backend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-be-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: acrName
    image: backendImage
    clerkJwtIssuer: clerkJwtIssuer
    clerkJwksUrl: clerkJwksUrl
    allowedOrigins: 'https://${frontendFqdn},https://${websiteFqdn}'
    googleClientId: googleClientId
    googleRedirectUri: googleRedirectUri
    salesforceClientId: salesforceClientId
    salesforceRedirectUri: salesforceRedirectUri
    frontendUrl: 'https://${frontendFqdn}'
  }
}

module queueWorker './modules/compute/queue-worker.bicep' = {
  name: 'worker-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-queue-worker-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: acrName
    storageAccountName: storageAccountName
    image: queueWorkerImage
  }
}

module frontendApp './modules/compute/invoice-fe.bicep' = {
  name: 'frontend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-fe-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    backendApiUrl: backendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    acrName: acrName
    image: frontendImage
  }
}

module websiteApp './modules/compute/invoice-website.bicep' = {
  name: 'website-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-website-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    backendApiUrl: backendApp.outputs.fqdn
    frontendApiUrl: frontendApp.outputs.fqdn
    acrName: acrName
    image: websiteImage
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
output websiteUrl string = websiteApp.outputs.fqdn
