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

VENV  := .venv
PYTEST := $(VENV)/bin/python -m pytest

.PHONY: venv
venv: ## Create the pinned virtualenv (dev AND runtime)
	$(PY) -m venv $(VENV)
	@# Both files. Installing only requirements-dev.txt left rdflib/pyshacl
	@# missing, so 20 validation tests skipped locally while CI (which installs
	@# both) ran them. A skip is not a pass, and a local run that silently
	@# covers less than CI is worse than one that fails.
	$(VENV)/bin/pip install -q -r requirements-dev.txt -r requirements-runtime.txt

.PHONY: contracts
contracts: ## Gate 0 - shared interface + service contract tests
	@# unittest discover does NOT descend into non-package subdirectories, so the
	@# per-service suites under tests/contracts/*/ are invisible to it. pytest is
	@# therefore the authoritative runner; the unittest path is a stdlib-only
	@# fallback that covers the headline invariants and must stay passing.
	@if [ -x "$(VENV)/bin/python" ]; then \
	  echo "== pytest (authoritative) =="; \
	  PYTHONPATH=$(SRC) $(PYTEST) tests -q; \
	else \
	  echo "== pytest unavailable; stdlib fallback only (run 'make venv' for full coverage) =="; \
	  PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/contracts -p 'test_*.py'; \
	fi

.PHONY: contracts-stdlib
contracts-stdlib: ## Stdlib-only subset (no venv needed)
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/contracts -p 'test_*.py' -v

.PHONY: integration
integration: ## Source-to-target and update tests (venv: no silent skips)
	@if ! compgen -G "tests/integration/test_*.py" > /dev/null; then \
	  echo "no integration tests yet (Gate 2+)"; exit 0; fi; \
	if [ -x "$(VENV)/bin/python" ]; then \
	  PYTHONPATH=$(SRC) $(VENV)/bin/python -m pytest tests/integration -q; \
	else \
	  echo "WARNING: no venv -- rdflib/pyshacl tests will SKIP. Run 'make venv' for real coverage."; \
	  PYTHONPATH=$(SRC) $(PY) -m pytest tests/integration -q 2>/dev/null \
	    || PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/integration -p 'test_*.py'; \
	fi

.PHONY: engine-image
engine-image: ## Build the pinned ShExMap engine image from the committed lockfile
	@# The tag carries a hash of the build context: several agent worktrees
	@# share one Docker daemon, so a bare version tag is mutable shared state
	@# and whoever builds last silently wins.
	PYTHONPATH=$(SRC) $(PY) -c "from fhir_sulo.engine.docker import EngineImage; \
	  i = EngineImage(); i.ensure_built(); print('built', i.tag)"

.PHONY: engine-tests
engine-tests: ## Gate 1 - linter and driver tests (live ones skip without Docker)
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -t . -p 'test_*.py' -v

.PHONY: engine-live
engine-live: engine-image ## Gate 1 - the same tests with the live engine REQUIRED, not skipped
	FHIR_SULO_REQUIRE_ENGINE=1 PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests/engine -t . -p 'test_*.py' -v

.PHONY: engine-probes
engine-probes: ## Gate 1 - the original capability probes behind DR-301 (Docker, slow)
	tools/engine/run.sh

.PHONY: engine
engine: engine-tests ## Gate 1 - engine checks that need no Docker

.PHONY: lint-schemas
lint-schemas: ## CD-1 - static analysis of every committed ShExMap pair; FAILS the build
	@if [ -n "$$(find maps -name '*.shex' 2>/dev/null | head -1)" ]; then \
	  tools/shexmap-lint --dir maps --require-pairs; \
	else echo "no schemas under maps/ yet. The linter itself is covered by"; \
	     echo "'make engine-tests'. Once any .shex lands, this target requires a"; \
	     echo "discoverable family (<family>-source.v1.shex + -target.v1.shex, or a"; \
	     echo "bare source.shex/target.shex pair) and fails without one."; fi

.PHONY: gate0
gate0: contracts ## Gate 0 pass check
	@$(PY) tools/gate-check.py 0

.PHONY: gate1
gate1: contracts engine-live lint-schemas ## Gate 1 pass check (requires Docker: the evidence is the engine)
	@$(PY) tools/gate-check.py 1

.PHONY: test
test: contracts engine-tests integration ## Everything runnable without Docker

.PHONY: test-all
test-all: test engine-live ## Everything, including the live engine (needs Docker)

.PHONY: verify-clean-clone
verify-clean-clone: ## Acceptance row "Deployability": clone and run from nothing
	tools/verify-clean-clone.sh

.PHONY: clean
clean: ## Remove build artifacts, including out-of-tree bytecode caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -not -path './.venv/*' -delete 2>/dev/null || true
	@# On this machine (and any with PYTHONPYCACHEPREFIX or a platform default,
	@# e.g. macOS sets sys.pycache_prefix to ~/Library/Caches/com.apple.python)
	@# bytecode lives OUTSIDE the tree, so the find above cannot reach it. A
	@# stale entry there survived an edit during integration and produced a
	@# module whose behaviour contradicted its own source. Clear it explicitly.
	@prefix=$$($(PY) -c 'import sys; print(sys.pycache_prefix or "")'); \
	if [ -n "$$prefix" ]; then \
	  target="$$prefix$$(pwd)"; \
	  if [ -d "$$target" ]; then rm -rf "$$target" && echo "cleared bytecode cache: $$target"; \
	  else echo "no out-of-tree cache for this directory under $$prefix"; fi; \
	else echo "no pycache_prefix set; in-tree __pycache__ only"; fi
