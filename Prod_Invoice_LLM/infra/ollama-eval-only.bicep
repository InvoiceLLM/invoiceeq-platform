targetScope = 'resourceGroup'

// Narrow, standalone deployment for ONE resource (plus its one supporting
// file share): a CPU-only `ollama/ollama` Container App in the EXISTING
// `cae-invoicellm-dev` environment, for Feature 23's 3-model comparison
// exercise (baseline gpt-5-mini vs. GPT-4o vs. Ollama llama3.2:latest).
// Founder-approved 2026-08-24 as "Option A" from the prior research pass
// (see `.claude/tasklists/infra-devops-feature23-gpt4o-ollama-research.md`
// and `feature_23_ai_control_tower.md`'s "Ollama candidate" section for the
// costed options this was chosen from). Not routed through 08-apps.bicep,
// same reason as gpt4o-deployment.bicep/benchmark-eval-job-only.bicep: this
// repo's `params.dev.json` naming/image drift makes a full stage deploy
// risky, and this file only touches resources no other stage owns (one new
// Container App, one new CAE-linked file share on the EXISTING storage
// account).
//
// ============ Region/SKU constraint (confirmed live, 2026-08-23) ============
// `cae-invoicellm-dev` is a Consumption-only environment in eastus2, which
// has NO GPU workload profiles (`az containerapp env workload-profile
// list-supported -l eastus2` -- confirmed empty for GPU SKUs; eastus,
// westus3, northeurope, swedencentral, australiaeast, uksouth do have them).
// Standing up a second, GPU-capable environment just for this was rejected
// as disproportionate to a periodic comparison tool -- CPU-only, in the
// existing environment, is the approved shape. Sizing was originally
// approved as 4 vCPU / 8 GiB (the ceiling for a workload-profile-enabled
// Consumption plan) but `az deployment group what-if` against the live
// environment 2026-08-24 rejected that combination: `cae-invoicellm-dev`
// has `workloadProfiles: null` (`az containerapp env show`), i.e. it is the
// CLASSIC Consumption-only plan, not the newer workload-profile-enabled
// one -- a distinction the prior research pass's "no GPU workload profiles
// in eastus2" finding did not surface. This environment's real per-
// container-app ceiling is 2.0 vCPU / 4.0 GiB; see the `cpu`/`memory`
// params below for the corrected values actually deployed.
//
// ============ Why minReplicas=0 (true scale-to-zero) ============
// This is a comparison tool invoked on demand (`scripts/run_agent_eval.py
// --provider ollama --model llama3.2:latest`), not a standing service --
// estimated ~8 active hours/month. Azure Retail Prices API confirmed
// (2026-08-23): Consumption plan is billed per-second while a replica is
// allocated and $0 while scaled to zero, so idle time costs nothing. The
// tradeoff is every cold start re-activates a fresh container instance.
//
// ============ Why a persistent Azure Files volume ============
// Ollama's default model store is `$HOME/.ollama` (`/root/.ollama` in this
// image, root by default). Without a persistent volume, EVERY scale-to-zero
// cold start would need to re-pull the ~2GB llama3.2:latest image layer from
// Ollama's registry before it could serve a single request -- slow, and a
// repeated (if small) egress cost on every activation. Mounting the same
// storage account's Azure Files pattern already used for ChromaDB
// (`modules/data/chromadb.bicep`) at `/root/.ollama` means the model is
// pulled ONCE (this deployment's startup command) and every subsequent
// cold start finds it already on disk.
//
// ============ Why the container command pulls the model itself ============
// The official `ollama/ollama` image's default CMD is `ollama serve` with
// no model preloaded -- `docker pull ollama/ollama` ships the *server*, not
// any model weights (Ollama Hub docs, checked 2026-08-23). Ollama's HTTP
// `/api/generate`/`/api/chat` endpoints do NOT silently auto-pull a missing
// model on first request in the way `ollama run <model>` (the CLI) does --
// calling either endpoint for a model that isn't present returns a
// "model not found" error, so the model must be pulled explicitly before
// this app can serve a real request. The command below overrides the
// default CMD to start the server in the background, poll `ollama list`
// (the ollama binary itself -- no dependency on curl/wget being present in
// this image) until the server is actually accepting requests, pull
// `llama3.2:latest` (a no-op if the persistent volume already has it from a
// prior cold start), then `wait` on the backgrounded server process so the
// container keeps running. This was verified live against the real image
// behavior as part of this deployment (see the tasklist / feature doc for
// the actual curl/API verification evidence), not assumed from docs alone.
//
// ============ Why external ingress, not internal ============
// `run_agent_eval.py` (and this founder/session's actual invocations of it,
// including the GPT-4o comparison run recorded in feature_23_ai_control_
// tower.md's "GPT-4o candidate" section) runs from a LOCAL DEV MACHINE, not
// from inside the CAE's network -- it reached the (publicly-reachable, since
// this environment has networkIsolation=false) Azure OpenAI endpoint the
// same way. `ca-chromadb-dev` and `ca-invoice-be-dev` can afford internal-
// only ingress because their only callers are other apps/jobs INSIDE this
// CAE; Ollama's only caller (this eval script) is not. External ingress is
// therefore required, matching `ca-invoice-website-dev`'s existing external
// ingress in this same environment (confirmed live via `az containerapp
// list`, 2026-08-24) -- not a new networking posture for this environment.
//
// Because Ollama's API has no built-in authentication and this app would
// otherwise be a free, unauthenticated LLM inference endpoint reachable by
// anyone who discovers the FQDN, `ipAllowlist` below locks inbound access to
// specific caller IPs (default: the dev machine's public IP at deploy time,
// confirmed via ifconfig.me/ipify.org 2026-08-24). This needs to be updated
// (redeploy with a new `ipAllowlist` value, or `az containerapp ingress
// access-restriction set`) if the calling machine's public IP changes --
// a real, documented operational cost of locking this down, accepted
// deliberately rather than leaving the endpoint open to the internet.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region. Must match the existing CAE region (eastus2).')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm` -- the prefix this environment was ACTUALLY built with (see benchmark-eval-job-only.bicep\'s header for the same params.dev.json drift this avoids).')
param namingPrefix string = 'invoicellm'

@description('Container App name.')
param appName string = 'ca-ollama-eval-${environment}'

@description('Model to pull and serve on startup. Must match what scripts/run_agent_eval.py --model is invoked with.')
param ollamaModel string = 'llama3.2:latest'

@description('vCPU allocation. CORRECTED 2026-08-24 from the originally-approved 4.0: `az deployment group what-if` against the live `cae-invoicellm-dev` environment rejected 4.0/8.0Gi with ContainerAppInvalidResourceTotal -- `az containerapp env show` confirms this environment has `workloadProfiles: null`, i.e. it predates/was never opted into the workload-profiles feature (the classic Consumption-only plan), whose real per-container-app ceiling is 2.0 vCPU / 4.0 GiB, not the workload-profile-enabled Consumption plan\'s 4.0/8.0Gi the prior research pass assumed. 2.0/4.0Gi is the actual maximum obtainable in this environment without a separate, out-of-scope environment migration.')
param cpu string = '2.0'

@description('Memory allocation. See `cpu` param -- 4.0Gi is this environment\'s real per-container-app ceiling, paired with 2.0 vCPU.')
param memory string = '4.0Gi'

@description('Minimum replica count. 0 = true scale-to-zero -- this is an on-demand comparison tool, not a standing service.')
param minReplicas int = 0

@description('Maximum replica count. 1 -- single-instance comparison tool, not a scaled service.')
param maxReplicas int = 1

@description('IPv4/IPv6 CIDR ranges allowed to reach this app\'s external ingress. Ollama has no built-in auth, so this is the only access control on an otherwise-open inference endpoint. Update this (redeploy, or `az containerapp ingress access-restriction set`) if the calling machine\'s public IP changes.')
param ipAllowlist array = [
  '122.167.116.167/32'
]

var caeName = 'cae-${namingPrefix}-${environment}'
var storageAccountName = 'st${namingPrefix}${environment}2' // real live name (stinvoicellmdev2) -- see gpt4o-deployment.bicep/benchmark-eval-job-only.bicep headers for the same `2`-suffix drift pattern on this env's storage/ACR names
var fileShareName = 'ollama-models'
var caeStorageLinkName = 'ollama-storage'

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

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
    shareQuota: 15 // GB -- llama3.2:latest is ~2GB; headroom for a second candidate model if ever compared
  }
}

resource caeStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  name: caeStorageLinkName
  parent: cae
  properties: {
    azureFile: {
      accountName: storageAccountName
      accountKey: storageAccount.listKeys().keys[0].value
      shareName: fileShareName
      accessMode: 'ReadWrite'
    }
  }
  dependsOn: [
    fileShare
  ]
}

resource ollamaApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 11434 // Ollama's default API port
        transport: 'http'
        allowInsecure: false
        ipSecurityRestrictions: [
          for (cidr, i) in ipAllowlist: {
            name: 'allow-${i}'
            action: 'Allow'
            ipAddressRange: cidr
            description: 'Feature 23 Ollama comparison-tool caller allowlist entry ${i}'
          }
        ]
      }
    }
    template: {
      volumes: [
        {
          name: 'ollama-volume'
          storageType: 'AzureFile'
          storageName: caeStorageLinkName
        }
      ]
      containers: [
        {
          name: 'ollama'
          image: 'ollama/ollama:latest'
          command: [
            '/bin/sh'
            '-c'
          ]
          args: [
            'ollama serve & until ollama list >/dev/null 2>&1; do sleep 1; done; ollama pull ${ollamaModel}; wait'
          ]
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          volumeMounts: [
            {
              volumeName: 'ollama-volume'
              mountPath: '/root/.ollama'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale-rule'
            http: {
              metadata: {
                concurrentRequests: '5'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    caeStorage
  ]
}

output ollamaAppName string = ollamaApp.name
output ollamaFqdn string = ollamaApp.properties.configuration.ingress.fqdn
output ollamaBaseUrl string = 'https://${ollamaApp.properties.configuration.ingress.fqdn}'
