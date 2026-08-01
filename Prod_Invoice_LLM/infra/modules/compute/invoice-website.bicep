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

@description('Frontend (invoice-fe) Container App FQDN. Used server-side only (internal ingress) to reverse-proxy FE pages -- Gap 12 Multi-Zone fix.')
param frontendApiUrl string

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('vCPU allocation, e.g. \'0.5\'.')
param cpu string = '0.5'

@description('Memory allocation, e.g. \'1.0Gi\'.')
param memory string = '1.0Gi'

@description('Minimum replica count. Dev default is 0 (scale-to-zero, per section 4.3). Prod should be >=1 -- this is the public marketing/login entry point, and scale-from-zero cold starts are user-visible there in a way they are not for internal-only apps.')
param minReplicas int = 0

@description('Maximum replica count.')
param maxReplicas int = 3

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
            cpu: json(cpu)
            memory: memory
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
            {
              // Gap 12: turns on next.config.js's rewrites() so invoice-website
              // transparently reverse-proxies FE's pages server-side, avoiding the
              // cross-subdomain Clerk cookie handshake (PSL rejects
              // Set-Cookie Domain=azurecontainerapps.io).
              name: 'ENABLE_FE_PROXY'
              value: 'true'
            }
            {
              // Server-side only, read by next.config.js's rewrites(). Must be
              // http:// -- internal Container Apps traffic is not TLS.
              name: 'FE_INTERNAL_URL'
              value: 'http://${frontendApiUrl}'
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
        // Section 4.3: scale to zero when idle (marketing site, bursty
        // traffic) -- dev default only; prod overrides minReplicas to >=1.
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output fqdn string = websiteApp.properties.configuration.ingress.fqdn
