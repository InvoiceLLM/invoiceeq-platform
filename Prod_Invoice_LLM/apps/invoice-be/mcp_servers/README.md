# MCP Servers Directory

This directory is reserved for Model Context Protocol (MCP) server modules providing specialized tool endpoints for external agents and workflow integrations.

- Ingestion tools, OCR analysis, and extraction inspectors will be mounted here as standalone MCP servers.
- Currently, standard ingestion and verification endpoints are exposed via FastAPI routers (`routers/invoices.py`, `routers/audit.py`).
- Kept clean to preserve the module namespace.
