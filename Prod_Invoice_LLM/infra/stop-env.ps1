# Stop the PostgreSQL Database (Stops Compute Billing)
az postgres flexible-server stop --name psql-invoice-llm-dev --resource-group invoice-llm-dev

# Force Containers to Zero (Just to be safe)
az containerapp update --name ca-invoice-be-dev --resource-group invoice-llm-dev --min-replicas 0
az containerapp update --name ca-queue-worker-dev --resource-group invoice-llm-dev --min-replicas 0
az containerapp update --name ca-invoice-fe-dev --resource-group invoice-llm-dev --min-replicas 0
az containerapp update --name ca-invoice-website-dev --resource-group invoice-llm-dev --min-replicas 0

Write-Host "Environment Frozen. You are now saving money!"
