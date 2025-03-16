.PHONY: format lint unit-test integration-test performance-test cmd-grammar clean coverage-dir pytest-docker-up pytest-docker-down e2e-test merge-coverage tox-unit-test tox-integration-test tox-e2e-test

ANTLR=antlr

ANTLR_GRAMMAR_DIR=labtasker/client/core/cmd_parser/
ANTLR_OUT_DIR=labtasker/client/core/cmd_parser/generated

COVERAGE_DIR=coverage

coverage-dir:
	mkdir -p $(COVERAGE_DIR)

format:
	black .
	isort .

lint:
	flake8
	mypy --ignore-missing-imports

unit-test: coverage-dir
	pytest -m "unit" --cov=labtasker --cov-report=term-missing --cov-report=xml
	mv .coverage coverage/.coverage.unit

pytest-docker-up:
	docker compose --env-file server.example.env -p pytest-labtasker up --build -d

pytest-docker-down:
	docker compose --env-file server.example.env -p pytest-labtasker down --remove-orphans --volumes

integration-test: coverage-dir
	pytest -m "integration" --cov=labtasker --cov-report=term-missing --cov-report=xml
	mv .coverage coverage/.coverage.integration

e2e-test: coverage-dir
	pytest -m "e2e" --cov=labtasker --cov-report=term-missing --cov-report=xml
	mv .coverage coverage/.coverage.e2e

tox-unit-test:
	tox -e py38-unit,py39-unit,py310-unit,py311-unit,py312-unit,py313-unit

tox-integration-test:
	tox -e py38-integration,py39-integration,py310-integration,py311-integration,py312-integration,py313-integration

tox-e2e-test:
	tox -e py38-e2e,py39-e2e,py310-e2e,py311-e2e,py312-e2e,py313-e2e

merge-coverage: coverage-dir
	coverage combine coverage/
	coverage report
	coverage xml -o coverage.xml

cmd-grammar:
	cp -r $(ANTLR_GRAMMAR_DIR)/*.g4 $(ANTLR_OUT_DIR)
	$(ANTLR) -Dlanguage=Python3 $(ANTLR_OUT_DIR)/*.g4
	rm $(ANTLR_OUT_DIR)/*.g4

clean:
	# Python cache files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name "*.pyd" -delete

	# Test and coverage files
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage coverage.xml cov.xml .coverage.* 2>/dev/null || true

	# Build and distribution files
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true

	# Cache directories
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".hypothesis" -exec rm -rf {} + 2>/dev/null || true

	# Documentation build
	rm -rf docs/site/ 2>/dev/null || true
