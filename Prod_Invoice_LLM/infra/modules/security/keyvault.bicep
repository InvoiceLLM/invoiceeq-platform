param location string
param keyVaultName string

@secure()
param dbAdminPassword string
@secure()
param clerkSecretKey string
@secure()
param tokenEncryptionKey string
@secure()
param azureOpenAiApiKey string = ''
@secure()
param azureDocIntelKey string = ''
@secure()
param databaseUrl string
@secure()
param redisUrl string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enabledForDeployment: true
    enabledForTemplateDeployment: true
    enabledForDiskEncryption: true
    networkAcls: {
      defaultAction: 'Allow' // Allowing access from ACA env; ideally restricted via Private Endpoints in prod
      bypass: 'AzureServices'
    }
  }
}

// Key Vault Secrets
resource secretDbPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'DATABASE-PASSWORD'
  properties: {
    value: dbAdminPassword
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

resource secretOpenAiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(azureOpenAiApiKey)) {
  parent: keyVault
  name: 'AZURE-OPENAI-API-KEY'
  properties: {
    value: azureOpenAiApiKey
  }
}

resource secretDocIntelKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(azureDocIntelKey)) {
  parent: keyVault
  name: 'AZURE-DOC-INTEL-KEY'
  properties: {
    value: azureDocIntelKey
  }
}

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'DATABASE-URL'
  properties: {
    value: databaseUrl
  }
}

resource secretRedisUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'REDIS-URL'
  properties: {
    value: redisUrl
  }
}

output keyVaultId string = keyVault.id
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultName string = keyVault.name
