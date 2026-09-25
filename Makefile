.PHONY: help install test lint format check run

help:            ## show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

install:         ## install dependencies (Python 3.13) including the deploy tooling
	uv sync --group deploy

test:            ## run the offline test suite (no AWS access needed)
	uv run pytest -q

lint:            ## lint
	uv run ruff check .

format:          ## format the code
	uv run ruff format .

check: lint test ## what CI runs
	uv run ruff format --check .

run:             ## serve the agent locally (POST /invocations on :8080) - needs your own AWS resources
	uv run python main.py
