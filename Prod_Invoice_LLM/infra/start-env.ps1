# Wake up the Database
az postgres flexible-server start --name psql-invoice-llm-dev --resource-group invoice-llm-dev

Write-Host "Database Online! The containers will automatically wake up when you visit the website."
