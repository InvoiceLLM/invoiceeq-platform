# ==============================================================================
# INVOICELLM ALERT & NOTIFICATION GOVERNANCE MAKEFILE
# ==============================================================================

.PHONY: help alerts-status alerts-quiet alerts-digest alerts-prod

help:
	@echo "InvoiceLLM Alert Governance Commands:"
	@echo "  make alerts-status   - Check active alert channels, thresholds and email toggles"
	@echo "  make alerts-quiet    - Mute routine staff emails during local dev/testing"
	@echo "  make alerts-digest   - Route routine completed invoices to dashboard, emails to audit only"
	@echo "  make alerts-prod     - Enforce production alert governance"

alerts-status:
	@powershell -ExecutionPolicy Bypass -File ./make.ps1 alerts-status

alerts-quiet:
	@powershell -ExecutionPolicy Bypass -File ./make.ps1 alerts-quiet

alerts-digest:
	@powershell -ExecutionPolicy Bypass -File ./make.ps1 alerts-digest

alerts-prod:
	@powershell -ExecutionPolicy Bypass -File ./make.ps1 alerts-prod
