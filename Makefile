SHELL := /bin/bash
PYTHON := python3

.PHONY: help install dev lint format typecheck test security check clean precommit ci

help:
	@echo "Pry Makefile"
	@echo ""
	@echo "  install     Install dependencies"
	@echo "  dev         Start dev server"
	@echo "  lint        Run ruff check"
	@echo "  format      Run ruff format"
	@echo "  typecheck   Run mypy"
	@echo "  test        Run pytest"
	@echo "  security    Run bandit + safety"
	@echo "  check       Full audit (lint + typecheck + test)"
	@echo "  clean       Remove build artifacts"
	@echo "  precommit   Run ruff + mypy + bandit"

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

ci: precommit test
