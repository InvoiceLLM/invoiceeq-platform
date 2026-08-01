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

@description('Number of Document Intelligence resources deployed (must match Stage 4/5). Threaded into queue-worker.bicep so it only wires up the docintel-2/-3 Key Vault secretRefs that Stage 5 actually seeded.')
@minValue(1)
@maxValue(3)
param docIntelInstanceCount int = 1

@description('Name of the shared ACR registry this environment pulls images from. Defaults to this environment\'s own computed name (dev, which owns it); prod must set this explicitly -- see 03-data.bicep.')
param sharedAcrName string = 'acr${replace(namingPrefix, '-', '')}${environment}'

@description('Backend Container App vCPU allocation.')
param backendCpu string = '1.0'
@description('Backend Container App memory allocation.')
param backendMemory string = '2.0Gi'
@description('Backend Container App minimum replica count.')
param backendMinReplicas int = 1
@description('Backend Container App maximum replica count.')
param backendMaxReplicas int = 5

@description('Queue-worker Container App vCPU allocation.')
param workerCpu string = '2.0'
@description('Queue-worker Container App memory allocation.')
param workerMemory string = '4.0Gi'
@description('Queue-worker Container App minimum replica count.')
param workerMinReplicas int = 0
@description('Queue-worker Container App maximum replica count.')
param workerMaxReplicas int = 10
@description('Queue-worker KEDA queue-length scale trigger threshold.')
param workerQueueScaleLength string = '15'

@description('Frontend Container App vCPU allocation.')
param frontendCpu string = '0.5'
@description('Frontend Container App memory allocation.')
param frontendMemory string = '1.0Gi'
@description('Frontend Container App minimum replica count.')
param frontendMinReplicas int = 1
@description('Frontend Container App maximum replica count.')
param frontendMaxReplicas int = 2

@description('Website Container App vCPU allocation.')
param websiteCpu string = '0.5'
@description('Website Container App memory allocation.')
param websiteMemory string = '1.0Gi'
@description('Website Container App minimum replica count. Dev default 0 (scale-to-zero); prod should set >=1 to avoid cold-starts on the public entry point.')
param websiteMinReplicas int = 0
@description('Website Container App maximum replica count.')
param websiteMaxReplicas int = 3

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
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
    acrName: sharedAcrName
    image: backendImage
    clerkJwtIssuer: clerkJwtIssuer
    clerkJwksUrl: clerkJwksUrl
    allowedOrigins: 'https://${frontendFqdn},https://${websiteFqdn}'
    googleClientId: googleClientId
    googleRedirectUri: googleRedirectUri
    salesforceClientId: salesforceClientId
    salesforceRedirectUri: salesforceRedirectUri
    frontendUrl: 'https://${frontendFqdn}'
    cpu: backendCpu
    memory: backendMemory
    minReplicas: backendMinReplicas
    maxReplicas: backendMaxReplicas
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
    acrName: sharedAcrName
    storageAccountName: storageAccountName
    image: queueWorkerImage
    docIntelInstanceCount: docIntelInstanceCount
    cpu: workerCpu
    memory: workerMemory
    minReplicas: workerMinReplicas
    maxReplicas: workerMaxReplicas
    queueScaleLength: workerQueueScaleLength
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
    acrName: sharedAcrName
    image: frontendImage
    cpu: frontendCpu
    memory: frontendMemory
    minReplicas: frontendMinReplicas
    maxReplicas: frontendMaxReplicas
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
    acrName: sharedAcrName
    image: websiteImage
    cpu: websiteCpu
    memory: websiteMemory
    minReplicas: websiteMinReplicas
    maxReplicas: websiteMaxReplicas
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
output websiteUrl string = websiteApp.outputs.fqdn
