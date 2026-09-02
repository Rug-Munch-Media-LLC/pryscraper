SHELL := /bin/bash
PYTHON := python3

.PHONY: help install dev lint format typecheck test security check clean precommit ci actor-build docs-sync

help:
	@echo "Pry Makefile"
	@echo ""
	@echo "  install       Install dependencies"
	@echo "  dev           Start dev server"
	@echo "  lint          Run ruff check"
	@echo "  format        Run ruff format"
	@echo "  typecheck     Run mypy"
	@echo "  test          Run pytest"
	@echo "  security      Run bandit + safety"
	@echo "  check         Full audit (lint + typecheck + test)"
	@echo "  clean         Remove build artifacts"
	@echo "  precommit     Run ruff + mypy + bandit"
	@echo "  actor-build   Regenerate .actor/input_schema.json from apify_schema.py"
	@echo "  docs-sync     Sync doc counts (tools/categories/tiers/tests) from source"

install:
	pip install -e ".[dev]"

dev:
	uvicorn api:app --reload --host 0.0.0.0 --port 8005

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy .

test:
	pytest tests/ -v --cov=. --cov-report=term-missing

security:
	bandit -r . -x tests/,.venv,__pycache__

check: lint typecheck test

clean:
	rm -rf __pycache__ .ruff_cache .mypy_cache .pytest_cache *.egg-info build dist

precommit: lint format typecheck security

test-contract: ## Run Pact contract tests (consumer)
	python -m pytest tests/contract/ -v --tb=short

pact-publish: ## Publish contracts to Pact Broker
	pact-broker publish tests/contract/pacts/ \
		--consumer-app-version $$(git rev-parse --short HEAD) \
		--branch $$(git rev-parse --abbrev-ref HEAD) \
		--broker-base-url $$PACT_BROKER_URL

deps-freshness:
	pip install pip-tools libyear 2>/dev/null || true
	libyear --file requirements.txt || true

ci: precommit test

# Regenerate .actor/input_schema.json from the ApifySchemaBuilder fluent API.
# Pin schema version + title so Apify Console recognises the file.
actor-build:
	$(PYTHON) -c "from apify_schema import ApifySchemaBuilder, StringField, IntegerField, BooleanField, EnumField; b = ApifySchemaBuilder('Pry Scraper', 'Scrape any website with Pry\\'s 12-tier fallback chain.'); b.add_array('urls', 'URLs to scrape', {'type': 'string', 'pattern': '^https?://'}, required=True).add_integer('max_pages', 'Max pages', default=10, minimum=1, maximum=1000).add_integer('timeout', 'Timeout (seconds)', default=30, minimum=5, maximum=120).add_enum('output_format', 'Output format', ['markdown','html','text'], default='markdown').add_boolean('crawl', 'Crawl linked pages', default=False); import json, pathlib; pathlib.Path('.actor').mkdir(exist_ok=True); pathlib.Path('.actor/input_schema.json').write_text(json.dumps(b.build_input_schema(), indent=2))"
	@echo "wrote .actor/input_schema.json"

docs-sync:
	.venv/bin/python scripts/docs_sync.py
