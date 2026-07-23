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

var keyVaultName = 'kv-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var postgresServerName = 'psql-${namingPrefix}-${environment}'
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

resource docIntelAccount2 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName2
}

resource docIntelAccount3 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName3
}

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
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
resource secretDocIntelKey2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY-2'
  properties: {
    value: docIntelAccount2.listKeys().key1
  }
}

resource secretDocIntelEndpoint2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-ENDPOINT-2'
  properties: {
    value: docIntelAccount2.properties.endpoint
  }
}

resource secretDocIntelKey3 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY-3'
  properties: {
    value: docIntelAccount3.listKeys().key1
  }
}

resource secretDocIntelEndpoint3 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
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

output secretsSeeded int = 7
