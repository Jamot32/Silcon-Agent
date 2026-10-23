.PHONY: setup dev demo down test eda-setup eda-check eda-tools-check llm-smoke meta-smoke logs

export SILICON_UID := $(shell id -u)
export SILICON_GID := $(shell id -g)

setup:
	@test -f .env || cp .env.example .env
	@mkdir -p runs

dev: setup
	python3 scripts/manage_worker.py stop
	docker compose up --build -d --wait
	python3 scripts/manage_worker.py start
	@echo "Silicon Agent: http://localhost:3000 | API: http://localhost:8000/api/health"

demo: dev
	@echo "Bootstrap: recorded playback appears after real EDA recordings exist."

down:
	python3 scripts/manage_worker.py stop
	docker compose down

test:
	docker compose run --rm --no-deps api python -m pytest -q -m 'not integration' -o cache_dir=/tmp/pytest-cache tests
	docker compose run --rm --no-deps web npm run typecheck

eda-setup:
	./eda/prepare.sh

eda-check:
	./eda/check.sh

eda-tools-check:
	uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt python -m pytest -q -m integration backend/tests/integration

llm-smoke: setup
	uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt python scripts/provider_smoke_test.py

meta-smoke: setup
	uv run --env-file .env --python 3.11 --with-requirements scripts/requirements-smoke.txt python scripts/llm_smoke_test.py

logs:
	docker compose logs -f --tail=100
