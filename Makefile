PY ?= python3
DC = docker compose -f deploy-compose.yml -f compose.onprem.yml

.PHONY: test compose-check audit-check

# Configuration rules and connector tests
test:
	$(PY) -m pytest

# Run inside the LibreChat folder: renders the merged compose file or fails
compose-check:
	$(DC) config --quiet

# Verifies the connector audit log has not been edited
audit-check:
	$(DC) exec outlook-drafts python -m outlook_drafts.audit /audit/outlook-actions.jsonl
