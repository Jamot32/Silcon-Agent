.PHONY: setup dev demo down test test-unit test-e2e record-repair eda-setup eda-check eda-tools-check golden-check golden-flow-check llm-smoke meta-smoke logs eval eval-compare eval-test eval-validate eval-selfcheck reliability-export reliability-ci

SET ?= dev
TIER ?= 1,2,3,4
N ?= 1
EVAL_JOBS ?= 1

export SILICON_UID := $(shell id -u)
export SILICON_GID := $(shell id -g)

setup:
	@test -f .env || cp .env.example .env
	python3 scripts/setup_env.py
	@mkdir -p runs

dev: setup
	python3 scripts/manage_worker.py stop
	docker compose up --build -d --wait
	python3 scripts/manage_worker.py start $(if $(CODEX_POLICY),--codex-policy "$(CODEX_POLICY)")
	@echo "Silicon Agent: http://localhost:3000 | API: http://localhost:8000/api/health"

demo: dev
	@echo "Authentic replays are on the home page; playback makes no model or EDA calls."

down:
	python3 scripts/manage_worker.py stop
	docker compose down

test: test-unit test-e2e

test-unit:
	docker compose run --build --quiet-build --rm --no-deps api python -m pytest -q -m 'not integration' -o cache_dir=/tmp/pytest-cache tests
	docker compose run --build --quiet-build --rm --no-deps web npm run typecheck
	npm --prefix frontend run test:unit

frontend/node_modules/.package-lock.json: frontend/package.json frontend/package-lock.json
	npm --prefix frontend ci

test-e2e: frontend/node_modules/.package-lock.json
	cd frontend && npx playwright install chromium
	cd frontend && npm run test:e2e -- e2e/replay.spec.ts e2e/run-failure.spec.ts

record-repair:
	uv run --python 3.12 --with-requirements backend/requirements.txt python scripts/start_repair_demo.py

eda-setup:
	./eda/prepare.sh

eda-check:
	./eda/check.sh

eda-tools-check:
	uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt python -m pytest -q -m integration backend/tests/integration

golden-check:
	uv run --python 3.12 --with-requirements backend/requirements.txt python scripts/check_golden.py

golden-flow-check:
	uv run --python 3.12 --with-requirements backend/requirements.txt python scripts/check_golden.py --flow

llm-smoke: setup
	PYTHONPATH=backend $(if $(CODEX_POLICY),SILICON_CODEX_BOUNDARY_CONFIG="$(CODEX_POLICY)") uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt python scripts/provider_smoke_test.py

meta-smoke: setup
	uv run --env-file .env --python 3.11 --with-requirements scripts/requirements-smoke.txt python scripts/llm_smoke_test.py

logs:
	docker compose logs -f --tail=100

eval:
	uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt python -m eval run --set "$(SET)" --tiers "$(TIER)" --repeat "$(N)" --jobs "$(EVAL_JOBS)"

eval-compare:
	uv run --python 3.12 --with-requirements backend/requirements.txt python -m eval compare "$(A)" "$(B)" $(if $(BRIDGE),--scope-bridge "$(BRIDGE)")

eval-test:
	uv run --python 3.12 --with-requirements backend/requirements.txt python -m pytest -q eval/tests scripts/tests

eval-validate:
	uv run --python 3.12 --with-requirements backend/requirements.txt python -m eval validate --set "$(SET)"

eval-selfcheck:
	PYTHONPATH=backend uv run --python 3.12 --with-requirements backend/requirements.txt python -m eval selfcheck --set "$(SET)"

# Publication verifies the sealed cohort; this never runs model or EDA calls.
reliability-export:
	uv run --python 3.12 --with-requirements backend/requirements.txt python scripts/reliability_export.py "$(RID)" --sealer "$(or $(SEALER),base)"

# Explicit opt-in: starts a new real DEV T1/T2, N=1, jobs=4 evaluation.
reliability-ci:
	uv run --python 3.12 --with-requirements backend/requirements.txt python scripts/reliability_ci.py --run
