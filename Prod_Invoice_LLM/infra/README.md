# Invoice AI — Infrastructure as Code (`/infra`)

## Purpose
All Azure cloud infrastructure provisioned via IaC (Azure Bicep / Terraform).  
Zero manual portal configuration. Full environment parity across Dev, UAT, and Production.

## Design Principles
1. **No Manual Configuration** — Everything is code-defined and version-controlled
2. **Environment Parity** — Same templates for Dev, UAT, and Prod (parameterized)
3. **Private by Default** — All services behind Azure Private Endpoints
4. **Zero-Touch Deployment** — Full stack deployable in < 15 minutes
5. **Full Auditability** — Every change tracked in Git

## Directory Structure
```
infra/
├── main.bicep                    # Orchestrator — deploys all modules
├── params.dev.json               # Dev environment parameters
├── params.uat.json               # UAT environment parameters
├── params.prod.json              # Production environment parameters
│
├── modules/
│   ├── network/
│   │   ├── vnet.bicep            # VNet + Subnet definitions
│   │   ├── nsg.bicep             # Network Security Groups
│   │   └── private-endpoints.bicep
│   │
│   ├── compute/
│   │   ├── container-env.bicep   # Container Apps Environment
│   │   ├── invoice-website.bicep # Website Container App
│   │   ├── invoice-fe.bicep      # Frontend Container App
│   │   ├── invoice-be.bicep      # Backend Container App
│   │   └── celery-worker.bicep   # Worker Container App
│   │
│   ├── data/
│   │   ├── postgresql.bicep      # PostgreSQL Flexible Server
│   │   ├── redis.bicep           # Azure Cache for Redis
│   │   ├── storage.bicep         # Blob Storage Account
│   │   └── chromadb.bicep        # ChromaDB Container App
│   │
│   ├── ai/
│   │   ├── openai.bicep          # Azure OpenAI + model deployments
│   │   └── doc-intelligence.bicep
│   │
│   ├── security/
│   │   ├── keyvault.bicep        # Key Vault + secrets
│   │   ├── managed-identities.bicep
│   │   └── rbac-assignments.bicep
│   │
│   └── monitoring/
│       ├── log-analytics.bicep   # Log Analytics Workspace
│       ├── app-insights.bicep    # Application Insights
│       ├── alerts.bicep          # Alert rules
│       └── dashboard.bicep       # Azure Dashboard
│
└── scripts/
    ├── deploy.sh                 # Deployment helper script
    └── seed-keyvault.sh          # Initial secret seeding
```

## Azure Resource Naming Convention
| Resource Type      | Pattern                    | Example                 |
|--------------------|----------------------------|-------------------------|
| Resource Group     | `rg-invoiceai-{env}`       | `rg-invoiceai-prod`     |
| VNet               | `vnet-invoiceai-{env}`     | `vnet-invoiceai-prod`   |
| Container App      | `ca-{service}-{env}`       | `ca-invoice-be-prod`    |
| PostgreSQL         | `psql-invoiceai-{env}`     | `psql-invoiceai-prod`   |
| Key Vault          | `kv-invoiceai-{env}`       | `kv-invoiceai-prod`     |
| Storage Account    | `stinvoiceai{env}`         | `stinvoiceaiprod`       |

## Deployment
```bash
# Deploy to a specific environment
az deployment group create \
  --resource-group rg-invoiceai-{env} \
  --template-file main.bicep \
  --parameters params.{env}.json
```
