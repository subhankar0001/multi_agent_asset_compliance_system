.PHONY: install install-dev test lint typecheck format local-api sam-local sam-build \
        deploy-staging deploy-prod ssm-bootstrap clean env-to-json

# ─────────────────────────────────────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

# ─────────────────────────────────────────────────────────────────────────────
# Code Quality
# ─────────────────────────────────────────────────────────────────────────────

lint:
	ruff check app/ tests/

format:
	ruff format app/ tests/

format-check:
	ruff format --check app/ tests/

typecheck:
	mypy app/

# ─────────────────────────────────────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────────────────────────────────────

test:
	pytest

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-cov:
	pytest --cov=app --cov-report=html
	@echo "Coverage report written to htmlcov/index.html"

# ─────────────────────────────────────────────────────────────────────────────
# Local Development
# ─────────────────────────────────────────────────────────────────────────────

local-api:
	uvicorn app.main:app --reload --port 8000 --host 0.0.0.0

env-to-json:
	python scripts/local_invoke.py --mode env-to-json

sam-local: env-to-json
	sam local start-api --env-vars .env.json --port 3000

# ─────────────────────────────────────────────────────────────────────────────
# AWS SAM
# ─────────────────────────────────────────────────────────────────────────────

sam-build:
	sam build --use-container

deploy-staging:
	sam deploy --config-env staging --no-confirm-changeset

deploy-prod:
	sam deploy --config-env default

# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

ssm-bootstrap:
	bash infra/ssm_bootstrap.sh

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage .aws-sam/ .env.json
