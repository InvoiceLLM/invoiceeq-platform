param location string
param storageAccountName string
param subnetId string
param privateDnsZoneId string
param queueDnsZoneId string

@description('Whether to provision private networking. false = public network access (dev); true = private-endpoint-only, blob + queue (prod).')
param networkIsolation bool = false

@description('Storage account replication SKU. Dev default (Standard_LRS) is cheapest -- single-region, no redundancy beyond in-datacenter. Standard_ZRS is recommended for prod since invoice PDFs have no other copy (source-of-truth, not a cache), but it is a real cost delta (roughly +25% on storage) over LRS -- left as an explicit param rather than silently upgraded so the tradeoff is a conscious choice at deploy time, not a bicep default.')
param skuName string = 'Standard_LRS'

@description('Public network access for the storage account. Only meaningful when networkIsolation=false.')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

@description('Network ACL default action. Only meaningful when networkIsolation=false.')
@allowed([
  'Allow'
  'Deny'
])
param networkAclsDefaultAction string = 'Allow'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: skuName
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    // Gap 361 (security pass, 2026-09-01): never declared before, so the
    // live account had drifted to TLS1_0 -- whatever the platform default
    // was when the account was first created, not enforced by this template.
    // Every client this app actually uses (Azure SDKs, httpx against blob
    // endpoints) already speaks TLS1_2+, so this has no compatibility cost.
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: networkIsolation ? 'Disabled' : publicNetworkAccess
    networkAcls: {
      defaultAction: networkIsolation ? 'Deny' : networkAclsDefaultAction
      bypass: 'AzureServices'
    }
  }
}

// Blob Services Containers
resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource invoicesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobServices
  name: 'invoices'
  properties: {
    publicAccess: 'None'
  }
}

// Private Endpoint for Storage Account (Blob service)
resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (networkIsolation) {
  name: '${storageAccountName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${storageAccountName}-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource storagePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (networkIsolation) {
  parent: storagePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

// Private Endpoint for Storage Account (Queue service)
resource storageQueuePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (networkIsolation) {
  name: '${storageAccountName}-queue-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${storageAccountName}-queue-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'queue'
          ]
        }
      }
    ]
  }
}

resource storageQueuePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (networkIsolation) {
  parent: storageQueuePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'queue-config'
        properties: {
          privateDnsZoneId: queueDnsZoneId
        }
      }
    ]
  }
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
