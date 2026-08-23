param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
param backendApiUrl string

// Gap 172: also set as a runtime env var below, in addition to the Docker
// build-arg deploy-dev.yml passes. The build-arg covers the browser bundle
// (NEXT_PUBLIC_* is inlined by `next build`); Clerk's server-side SDK
// (auth()/getToken(), used in Route Handlers) separately reads this same
// variable name from process.env AT RUNTIME, independent of the client
// bundle. A fresh environment that only had the build-arg had auth()
// return no userId at all until this was patched live -- see be_features_tracker.md.
@description('Clerk SSO Publishable Client Key -- baked into the client bundle via Docker build-arg AND set as a runtime env var for the server-side Clerk SDK (Gap 172).')
param nextPublicClerkPublishableKey string = ''

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Application Insights Connection String for OpenTelemetry APM tracing')
param appInsightsConnectionString string = ''

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
              // Gap 172: Container Apps ingress enforces HTTPS (allowInsecure:
              // false) even for internal, same-VNet traffic — a plain http://
              // call gets a 301 to https:// on the identical host, and
              // fetch()/undici strips the Authorization header on that
              // scheme-change redirect per the Fetch spec's cross-origin rule.
              // Must be https:// even though this backend is internal-only.
              name: 'BACKEND_API_URL'
              value: 'https://${backendApiUrl}'
            }
            {
              // Gap 172: Clerk's server-side SDK (auth()/getToken()) reads
              // this same variable name from process.env at runtime -- the
              // Docker build-arg only covers the browser bundle, not this.
              name: 'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY'
              value: nextPublicClerkPublishableKey
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
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 15
              periodSeconds: 20
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              failureThreshold: 12
              timeoutSeconds: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            // HTTP concurrent-request trigger: frontend is Next.js SSR — lighter
            // than the backend (no AI/DB heavy work), so it can handle 30
            // concurrent connections before needing a second replica. Without a
            // rule Azure had no trigger to scale the frontend even if 100+ users
            // loaded the dashboard simultaneously.
            // Gap 290 (2026-08-23): this rule existed only in source until
            // now — the live resource had `rules: null` (`az containerapp
            // show`), so Azure was silently on its platform default (~10
            // concurrent req/replica) despite this reasoning being written
            // down. CPU/memory rules added below per founder decision.
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '30'
              }
            }
          }
          {
            name: 'cpu-scaling'
            custom: {
              type: 'cpu'
              metadata: {
                type: 'Utilization'
                value: '85'
              }
            }
          }
          {
            name: 'memory-scaling'
            custom: {
              type: 'memory'
              metadata: {
                type: 'Utilization'
                value: '85'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = frontendApp.properties.configuration.ingress.fqdn
