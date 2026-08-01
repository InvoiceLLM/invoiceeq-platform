param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
param backendApiUrl string

// Retained for caller compatibility (main-step4.bicep / deploy-all.ps1 still
// pass it) but intentionally unused: see the Gap 6 note on the env block below.
@description('Unused. NEXT_PUBLIC_* must be a Docker build-arg, not a runtime env var.')
param nextPublicClerkPublishableKey string = ''

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('vCPU allocation, e.g. \'0.5\'.')
param cpu string = '0.5'

@description('Memory allocation, e.g. \'1.0Gi\'.')
param memory string = '1.0Gi'

@description('Minimum replica count.')
param minReplicas int = 1

@description('Maximum replica count.')
param maxReplicas int = 2

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource frontendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedIdentityId
        }
      ]
      ingress: {
        external: false // Internal-only: invoice-website reverse-proxies FE server-side (Multi-Zone), avoiding cross-subdomain cookie handshake (Gap 12)
        targetPort: 3000
        transport: 'http'
      }
      secrets: [
        {
          name: 'clerk-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/CLERK-SECRET-KEY'
          identity: userAssignedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'invoice-fe'
          image: image
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            {
              // Server-side proxy env var — must use http:// for internal Container Apps traffic
              name: 'BACKEND_API_URL'
              value: 'http://${backendApiUrl}'
            }
            // Gap 6: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is deliberately NOT set
            // here. Next.js inlines NEXT_PUBLIC_* into the client bundle during
            // `next build`, so a runtime Container App env var arrives too late
            // and has zero effect on the browser. It is passed as a Docker
            // build-arg in .github/workflows/deploy-dev.yml instead.
            {
              name: 'CLERK_SECRET_KEY'
              secretRef: 'clerk-secret-secret'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
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
}

output fqdn string = frontendApp.properties.configuration.ingress.fqdn
