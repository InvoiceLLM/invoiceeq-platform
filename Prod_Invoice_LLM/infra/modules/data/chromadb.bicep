param location string
param caeId string
param appName string
param storageAccountName string
@secure()
param storageAccountKey string

@description('vCPU allocation, e.g. \'0.5\'.')
param cpu string = '0.5'

@description('Memory allocation, e.g. \'1.0Gi\'.')
param memory string = '1.0Gi'

@description('Minimum replica count. ChromaDB is stateful (single AzureFile-backed volume) so this stays at 1 for both envs -- more than 1 replica would need a different persistence story.')
param minReplicas int = 1

@description('Maximum replica count.')
param maxReplicas int = 1

// ================= Variables =================
var fileShareName = 'chromadb-data'
var storageResourceName = 'chromadb-storage'
// Extract the CAE name from the full resource ID
var caeName = last(split(caeId, '/'))

// ================= 1. Create File Share in existing Storage Account =================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-01-01' existing = {
  parent: storageAccount
  name: 'default'
}
resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  parent: fileService
  name: fileShareName
  properties: {
    shareQuota: 10  // 10 GB
  }
}

// ================= 2. Link File Share to Container Apps Environment =================
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

resource caeStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  name: storageResourceName
  parent: cae
  properties: {
    azureFile: {
      accountName: storageAccountName
      accountKey: storageAccountKey
      shareName: fileShareName
      accessMode: 'ReadWrite'
    }
  }
  dependsOn: [fileShare]
}

// ================= 3. ChromaDB Container App with Persistent Volume =================
resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
      }
    }
    template: {
      volumes: [
        {
          name: 'chromadb-volume'
          storageType: 'AzureFile'
          storageName: storageResourceName
        }
      ]
      containers: [
        {
          name: 'chromadb'
          image: 'chromadb/chroma:latest'
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          volumeMounts: [
            {
              volumeName: 'chromadb-volume'
              mountPath: '/chroma/chroma'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
  dependsOn: [caeStorage]
}

output internalFqdn string = chromaDbApp.properties.configuration.ingress.fqdn
