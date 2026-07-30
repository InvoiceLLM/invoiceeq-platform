// invoice-website Container App (marketing site + SSO auth pages)
//
// Spec: Cloud_Architecture_Document.md section 4.2 -- External ingress (443),
// 0/3 replicas, 0.5 vCPU / 1Gi. Section 4.3 -- scale to zero when idle.

param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
@description('Backend Container App FQDN. Used server-side only (internal ingress).')
param backendApiUrl string

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource websiteApp 'Microsoft.App/containerApps@2024-03-01' = {
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
        external: true // Public marketing site + login/signup entry point
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
          name: 'invoice-website'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              // Server-side only, used by pages/api/auth/provision.js.
              // Must be http:// -- internal Container Apps traffic is not TLS.
              name: 'BACKEND_API_URL'
              value: 'http://${backendApiUrl}'
            }
            {
              name: 'CLERK_SECRET_KEY'
              secretRef: 'clerk-secret-secret'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            // Gap 6: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY and NEXT_PUBLIC_FE_URL are
            // deliberately NOT set here. Next.js inlines NEXT_PUBLIC_* into the
            // client bundle during `next build`, so a runtime env var arrives too
            // late and has zero effect on the browser. They are passed as Docker
            // build-args in .github/workflows/deploy-dev.yml instead.
          ]
        }
      ]
      scale: {
        // Section 4.3: scale to zero when idle (marketing site, bursty traffic).
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

output fqdn string = websiteApp.properties.configuration.ingress.fqdn
