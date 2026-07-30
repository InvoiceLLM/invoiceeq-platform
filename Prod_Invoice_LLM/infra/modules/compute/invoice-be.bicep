param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
param chromaHost string
param azureOpenAiEndpoint string
param azureOpenAiDeploymentName string
param azureDocIntelEndpoint string

// Gap 8: required for Clerk JWT verification. Without CLERK_JWKS_URL,
// dependencies.py -> get_jwk() raises HTTP 500 on every real token. Without
// CLERK_JWT_ISSUER, issuer validation is silently skipped and a correctly signed
// token from ANY Clerk tenant would be accepted.
//
// Not secrets: the JWKS endpoint is public and unauthenticated by design, and the
// issuer is a public URL present in every token's `iss` claim.
@description('Clerk JWT issuer URL (public, no trailing slash)')
param clerkJwtIssuer string = ''

@description('Clerk JWKS endpoint URL (public)')
param clerkJwksUrl string = ''

// config.py's ALLOWED_ORIGINS default is localhost-only (dev fallback) --
// nothing previously set a real value here, so CORS would silently reject
// every real deployed frontend origin. Not currently exploitable (ingress
// below is external:false, so a browser can never reach this app directly),
// but wrong-by-default is worth fixing before anyone flips that to true.
@description('Comma-separated allowed CORS origins (real FE/website FQDNs, computed by the orchestrator)')
param allowedOrigins string = ''

// Connectors (Feature 9): one shared platform-level OAuth app per provider
// (our company's), not per-tenant -- see routers/connectors.py. Client IDs
// and redirect URIs are public (visible in the browser's OAuth redirect),
// so they're plain params here; only the client secrets come from Key Vault.
@description('Our company Google Cloud OAuth Client ID (connectors: Drive)')
param googleClientId string = ''

@description('OAuth redirect URI registered with Google for this environment')
param googleRedirectUri string = ''

@description('Our company Salesforce Connected App Consumer Key (connectors)')
param salesforceClientId string = ''

@description('OAuth redirect URI registered with Salesforce for this environment')
param salesforceRedirectUri string = ''

@description('Real FE origin (https://...) -- oauth_callback() redirects the browser here once a connector OAuth flow completes, since Google/Salesforce hit this backend directly')
param frontendUrl string = ''

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
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
        external: false // Accessible only internally (VNet/Frontend)
        targetPort: 8000
        transport: 'http'
      }
      secrets: [
        {
          name: 'db-url-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/DATABASE-URL'
          identity: userAssignedIdentityId
        }
        {
          name: 'redis-url-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/REDIS-URL'
          identity: userAssignedIdentityId
        }
        {
          name: 'clerk-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/CLERK-SECRET-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'token-encryption-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/TOKEN-ENCRYPTION-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'openai-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-OPENAI-API-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'docintel-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'storage-conn-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-STORAGE-CONNECTION-STRING'
          identity: userAssignedIdentityId
        }
        {
          name: 'google-client-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/GOOGLE-CLIENT-SECRET'
          identity: userAssignedIdentityId
        }
        {
          name: 'salesforce-client-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/SALESFORCE-CLIENT-SECRET'
          identity: userAssignedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'invoice-be'
          image: image
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'db-url-secret'
            }
            {
              name: 'REDIS_URL'
              secretRef: 'redis-url-secret'
            }
            {
              name: 'CHROMA_HOST'
              value: chromaHost
            }
            {
              name: 'CHROMA_PORT'
              value: '8000'
            }
            {
              name: 'CLERK_SECRET_KEY'
              secretRef: 'clerk-secret-secret'
            }
            {
              name: 'CLERK_JWT_ISSUER'
              value: clerkJwtIssuer
            }
            {
              name: 'CLERK_JWKS_URL'
              value: clerkJwksUrl
            }
            {
              name: 'ALLOWED_ORIGINS'
              value: allowedOrigins
            }
            {
              name: 'TOKEN_ENCRYPTION_KEY'
              secretRef: 'token-encryption-secret'
            }
            {
              name: 'LLM_PROVIDER'
              value: 'azure'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'openai-key-secret'
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: '2024-02-15-preview'
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
              value: azureOpenAiDeploymentName
            }
            {
              name: 'AZURE_DOC_INTEL_ENDPOINT'
              value: azureDocIntelEndpoint
            }
            {
              name: 'AZURE_DOC_INTEL_KEY'
              secretRef: 'docintel-key-secret'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            {
              name: 'AZURE_STORAGE_CONNECTION_STRING'
              secretRef: 'storage-conn-secret'
            }
            {
              name: 'GOOGLE_CLIENT_ID'
              value: googleClientId
            }
            {
              name: 'GOOGLE_CLIENT_SECRET'
              secretRef: 'google-client-secret-secret'
            }
            {
              name: 'GOOGLE_REDIRECT_URI'
              value: googleRedirectUri
            }
            {
              name: 'SALESFORCE_CLIENT_ID'
              value: salesforceClientId
            }
            {
              name: 'SALESFORCE_CLIENT_SECRET'
              secretRef: 'salesforce-client-secret-secret'
            }
            {
              name: 'SALESFORCE_REDIRECT_URI'
              value: salesforceRedirectUri
            }
            {
              name: 'FRONTEND_URL'
              value: frontendUrl
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
      }
    }
  }
}

output fqdn string = backendApp.properties.configuration.ingress.fqdn
