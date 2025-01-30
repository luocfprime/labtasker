.PHONY: format lint unit-test integration-test performance-test cmd-grammar clean

ANTLR=antlr

format:
	black .
	isort .

lint:
	flake8 .
	mypy .

unit-test:
	pytest -m "unit" --cov=labtasker --cov-report=term-missing --cov-report=xml:cov.xml

integration-test:
	pytest -m "integration" --cov=labtasker --cov-report=term-missing --cov-report=xml:cov.xml

performance-test:
	pytest -m "integration and benchmark" --benchmark-columns="rounds, iterations, min, mean, max"

cmd-grammar:
	$(ANTLR) -Dlanguage=Python3 labtasker/client/core/cmd_parser/LabCmdLexer.g4
	$(ANTLR) -Dlanguage=Python3 labtasker/client/core/cmd_parser/LabCmd.g4

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
