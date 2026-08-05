targetScope = 'resourceGroup'

// ================= Stage 5: Key Vault Secret Seeding =================
// Runs after Stages 2 (vault exists), 3 (Postgres/Redis/Storage exist),
// and 4 (OpenAI/DocIntel exist) — every value written here is read via
// `existing` + listKeys() from those already-deployed resources, so this
// stage never needs the old script's "extract deployment output, pass as
// next stage's param" chain.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Admin login name for PostgreSQL (must match Stage 3)')
param dbAdminLogin string = 'dbadmin'

@description('Secure admin password for PostgreSQL (must match Stage 3)')
@secure()
param dbAdminPassword string

@description('Clerk SSO API Secret Key')
@secure()
param clerkSecretKey string

@description('AES-256 Fernet key for token encryption')
@secure()
param tokenEncryptionKey string

@description('Our company Google Cloud OAuth app Client Secret (connectors: Drive)')
@secure()
param googleClientSecret string

@description('Our company Salesforce Connected App Consumer Secret (connectors)')
@secure()
param salesforceClientSecret string

@description('SendGrid API key (Mail Send scope) -- platform-wide, one key for both inbound and outbound (Gap 124/125). Not per-tenant; see feature_9_connectors.md.')
@secure()
param sendgridApiKey string

@description('Shared secret checked on the SendGrid Inbound Parse webhook path to confirm a request genuinely came from SendGrid (Gap 124 item 2 -- Inbound Parse does not sign its payloads).')
@secure()
param sendgridInboundSecret string

@description('Number of Document Intelligence resources deployed in Stage 4 (must match). Dev=1, prod=3 -- gates whether the DOC-INTEL-KEY-2/3 and DOC-INTEL-ENDPOINT-2/3 secrets are seeded.')
@minValue(1)
@maxValue(3)
param docIntelInstanceCount int = 1

@description('Postgres Flexible Server resource name (must match Stage 3\'s postgresServerName override -- see 03-data.bicep for why this can differ from the naming-convention default).')
param postgresServerName string = 'psql-${namingPrefix}-${environment}'

@description('Whether to (re)write the DATABASE-URL secret from dbAdminPassword. Default true for a fresh environment stand-up; set false when the live Postgres server already has a working DATABASE-URL secret and dbAdminPassword in the local secrets file cannot be trusted to be current (e.g. the server was recreated manually outside this template and the local params file was never updated to match) -- protects a live, working connection string from being silently overwritten with a wrong password.')
param manageDatabaseUrlSecret bool = true

var keyVaultName = 'kv-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var redisName = 'redis-${namingPrefix}-${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var docIntelName2 = 'docintel-${namingPrefix}-${environment}-2'
var docIntelName3 = 'docintel-${namingPrefix}-${environment}-3'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' existing = {
  name: postgresServerName
}

resource redisCache 'Microsoft.Cache/redisEnterprise@2025-04-01' existing = {
  name: redisName
}

resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-04-01' existing = {
  name: 'default'
  parent: redisCache
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName
}

resource docIntelAccount2 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (docIntelInstanceCount >= 2) {
  name: docIntelName2
}

resource docIntelAccount3 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (docIntelInstanceCount >= 3) {
  name: docIntelName3
}

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (manageDatabaseUrlSecret) {
  parent: keyVault
  name: 'DATABASE-URL'
  properties: {
    value: 'postgresql://${dbAdminLogin}:${uriComponent(dbAdminPassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/invoice_db?sslmode=require'
  }
}

resource secretRedisUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'REDIS-URL'
  properties: {
    value: 'rediss://:${uriComponent(redisDatabase.listKeys().primaryKey)}@${redisCache.properties.hostName}:${redisDatabase.properties.port}/0'
  }
}

resource secretStorageConnectionString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-STORAGE-CONNECTION-STRING'
  properties: {
    value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
  }
}

resource secretOpenAiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-OPENAI-API-KEY'
  properties: {
    value: openaiAccount.listKeys().key1
  }
}

resource secretDocIntelKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY'
  properties: {
    value: docIntelAccount.listKeys().key1
  }
}

// Gap 41/42 scaling (Jul 2026): 2 additional Doc Intelligence resources, each
// with its own independent rate limit, round-robined across in code
// (utils/doc_intel_client.py) - see feature_2_pipeline_extraction.md.
resource secretDocIntelKey2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelInstanceCount >= 2) {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY-2'
  properties: {
    value: docIntelAccount2.listKeys().key1
  }
}

resource secretDocIntelEndpoint2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelInstanceCount >= 2) {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-ENDPOINT-2'
  properties: {
    value: docIntelAccount2.properties.endpoint
  }
}

resource secretDocIntelKey3 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelInstanceCount >= 3) {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY-3'
  properties: {
    value: docIntelAccount3.listKeys().key1
  }
}

resource secretDocIntelEndpoint3 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelInstanceCount >= 3) {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-ENDPOINT-3'
  properties: {
    value: docIntelAccount3.properties.endpoint
  }
}

resource secretClerkKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'CLERK-SECRET-KEY'
  properties: {
    value: clerkSecretKey
  }
}

resource secretEncryptionKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'TOKEN-ENCRYPTION-KEY'
  properties: {
    value: tokenEncryptionKey
  }
}

// Connectors (Feature 9): one shared platform-level OAuth app per provider,
// owned by us -- individual tenants authenticate their own Drive/Salesforce
// account through it (see routers/connectors.py::_has_real_credentials).
// Client IDs/redirect URIs are not secret (they're public in the browser
// redirect URL) and are passed as plain params in 08-apps.bicep instead.
resource secretGoogleClientSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'GOOGLE-CLIENT-SECRET'
  properties: {
    value: googleClientSecret
  }
}

resource secretSalesforceClientSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'SALESFORCE-CLIENT-SECRET'
  properties: {
    value: salesforceClientSecret
  }
}

// SendGrid (Gap 124/125): one platform-wide key + one inbound-webhook shared
// secret, not per-tenant -- see feature_9_connectors.md for why no tenant
// ever needs their own SendGrid credential.
resource secretSendgridApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'SENDGRID-API-KEY'
  properties: {
    value: sendgridApiKey
  }
}

resource secretSendgridInboundSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'SENDGRID-INBOUND-SECRET'
  properties: {
    value: sendgridInboundSecret
  }
}

// Computed, not hardcoded: 11 always-seeded secrets (DATABASE-URL, REDIS-URL,
// AZURE-STORAGE-CONNECTION-STRING, AZURE-OPENAI-API-KEY, AZURE-DOC-INTEL-KEY,
// CLERK-SECRET-KEY, TOKEN-ENCRYPTION-KEY, GOOGLE-CLIENT-SECRET,
// SALESFORCE-CLIENT-SECRET, SENDGRID-API-KEY, SENDGRID-INBOUND-SECRET) + 2
// more per additional Doc Intelligence instance beyond the first (KEY +
// ENDPOINT, gated on docIntelInstanceCount). This was hardcoded to 9 and went
// stale the moment Gap 41/42 added the docintel-2/3 secrets, and again just
// now adding the 2 SendGrid secrets (actual count today, with
// docIntelInstanceCount=3, is 15) -- deploy-all.ps1's Stage 5 gate reads this
// output instead of asserting a literal number, so it can't go stale the same
// way again.
output secretsSeeded int = 11 + (2 * (docIntelInstanceCount - 1))
