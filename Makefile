.PHONY: install mock modeling agents contract contract-check test check smoke-live demo-check demo-check-readiness

# Optional installed native-library path, assigned inside the recipe for macOS make.
PDF_LIBRARY_PATH ?=
DEMO_CHECK_ARGS ?=

install:            ## Install both Python services into one virtualenv
	uv sync --all-packages

modeling:           ## Modeling (physics/ML) mock API on :8000, docs at /docs
	uv run --all-packages uvicorn modeling_api.main:app --reload --port 8000 --reload-dir modeling

agents:             ## Agents mock API on :8001 (calls modeling on :8000)
	MODELING_API_URL=http://localhost:8000/api/v1 $(if $(PDF_LIBRARY_PATH),DYLD_FALLBACK_LIBRARY_PATH="$(PDF_LIBRARY_PATH)") uv run --all-packages uvicorn mooring_agents.api.main:app --reload --port 8001 --reload-dir agents

mock:               ## Both services; Ctrl-C stops both
	$(MAKE) -j2 modeling agents

contract:           ## Regenerate contract/*.openapi.yaml and examples from the schemas
	uv run --all-packages python scripts/export_contract.py

contract-check:     ## Fail if contract/ is out of date
	uv run --all-packages python scripts/export_contract.py --check

test:               ## Run all Python tests (includes the contract check)
	uv run --all-packages pytest -q

check: test

smoke-live:           ## Opt-in live provider checks (never part of CI)
	@if test "$${MOORING_LIVE_SMOKE:-}" = 1; then \
		uv run --all-packages python scripts/smoke_coops.py; \
	else \
		echo "skipped: set MOORING_LIVE_SMOKE=1"; \
	fi

demo-check:         ## Check the browser and API demonstration (see scripts/demo_check.py)
	uv run --all-packages python scripts/demo_check.py --profile baseline $(DEMO_CHECK_ARGS)

demo-check-readiness: ## Fail on outstanding master-plan demo acceptance requirements
	uv run --all-packages python scripts/demo_check.py $(DEMO_CHECK_ARGS) --profile readiness
