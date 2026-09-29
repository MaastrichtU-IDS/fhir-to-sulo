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

.PHONY: engine-image
engine-image: ## Build the pinned ShExMap engine image from the committed lockfile
	docker build -t fhir-sulo/shexmap:1.0.0-alpha.33 tools/engine

.PHONY: engine-tests
engine-tests: ## Gate 1 - linter and driver tests (no Docker; recorded engine output)
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -p 'test_mapcode.py' -v
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -p 'test_linter.py' -v
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -p 'test_driver.py' -v

.PHONY: engine-live
engine-live: engine-image ## Gate 1 - live-engine tests: fixture drift, linter-vs-engine, driver end to end
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -p 'test_engine_live.py' -v

.PHONY: engine-probes
engine-probes: ## Gate 1 - the original capability probes behind DR-301 (Docker, slow)
	tools/engine/run.sh

.PHONY: engine
engine: engine-tests ## Gate 1 - engine checks that need no Docker

.PHONY: lint-schemas
lint-schemas: ## CD-1 - static analysis of every committed ShExMap pair; FAILS the build
	@if [ -d maps ]; then tools/shexmap-lint --dir maps; \
	else echo "no maps/ yet (Gate 2, Agent 3). The linter itself is covered by"; \
	     echo "'make engine-tests'; it becomes a build gate when maps/ exists."; fi

.PHONY: gate0
gate0: contracts ## Gate 0 pass check
	@$(PY) tools/gate-check.py 0

.PHONY: gate1
gate1: contracts engine ## Gate 1 pass check
	@$(PY) tools/gate-check.py 1

.PHONY: test
test: contracts engine-tests integration ## Everything runnable without Docker

.PHONY: test-all
test-all: test engine-live ## Everything, including the live engine (needs Docker)

.PHONY: clean
clean: ## Remove build artifacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
