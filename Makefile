# FHIR-to-SULO pilot - one documented entry point per acceptance matrix row
# "Deployability": one documented command runs CLI/API and CI tests with pinned versions.

SHELL := /bin/bash
PY    := python3
SRC   := src

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: contracts
contracts: ## Gate 0 - shared interface guard tests
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/contracts -p 'test_*.py' -v

.PHONY: integration
integration: ## Source-to-target and update tests
	@if compgen -G "tests/integration/test_*.py" > /dev/null; then \
	  PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/integration -p 'test_*.py' -v; \
	else echo "no integration tests yet (Gate 2+)"; fi

.PHONY: engine
engine: ## Gate 1 - pinned ShEx.js engine probes (Docker)
	@if [ -x tools/engine/run-probes.sh ]; then tools/engine/run-probes.sh; \
	else echo "engine probes not yet pinned (Gate 1, Agent 4)"; fi

.PHONY: gate0
gate0: contracts ## Gate 0 pass check
	@$(PY) tools/gate-check.py 0

.PHONY: gate1
gate1: contracts engine ## Gate 1 pass check
	@$(PY) tools/gate-check.py 1

.PHONY: test
test: contracts integration ## Everything runnable today

.PHONY: clean
clean: ## Remove build artifacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
