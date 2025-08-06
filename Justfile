# Variable definitions

ANTLR := "antlr"
ANTLR_GRAMMAR_DIR := "labtasker/client/core/cmd_parser/"
ANTLR_OUT_DIR := "labtasker/client/core/cmd_parser/generated"
COVERAGE_DIR := "coverage"

# List available commands
default:
    @echo "Available commands:"
    @just --list

# Update version number across project files and create a version commit/tag
update-version VERSION:
    #!/usr/bin/env python3
    import re
    import subprocess

    # Get the old version from __init__.py
    with open("labtasker/__init__.py", "r") as f:
        init_content = f.read()

    old_version = re.search(r'__version__ = "([^"]+)"', init_content).group(1)

    # Update version in __init__.py
    with open("labtasker/__init__.py", "w") as f:
        f.write(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{{ VERSION }}"', init_content))

    # Update version in pyproject.toml
    with open("pyproject.toml", "r") as f:
        toml_content = f.read()

    with open("pyproject.toml", "w") as f:
        f.write(re.sub(r'version = "[^"]+"', f'version = "{{ VERSION }}"', toml_content))

    # Commit the changes
    subprocess.run(["git", "add", "labtasker/__init__.py", "pyproject.toml"])
    subprocess.run(["git", "commit", "-m", f"chore: Version {old_version} -> {{ VERSION }}"])

    # Create a tag
    subprocess.run(["git", "tag", f"v{{ VERSION }}"])

    print(f"Updated version from {old_version} to {{ VERSION }} and created tag v{{ VERSION }}")

# Create coverage directory
coverage-dir:
    mkdir -p {{ COVERAGE_DIR }}

# Format code with black and isort
format:
    black .
    isort .

# Run linting checks
lint:
    flake8
    mypy --ignore-missing-imports

# Run unit tests
unit-test: coverage-dir
    pytest -m "unit" --cov=labtasker --cov-report=term-missing --cov-report=xml
    mv .coverage {{ COVERAGE_DIR }}/.coverage.unit

# Start Docker containers for testing
pytest-docker-up:
    docker compose --env-file server.example.env -p pytest-labtasker up --build -d

# Stop Docker containers for testing
pytest-docker-down:
    docker compose --env-file server.example.env -p pytest-labtasker down --remove-orphans --volumes

# Run integration tests
integration-test: coverage-dir
    pytest -m "integration" --cov=labtasker --cov-report=term-missing --cov-report=xml
    mv .coverage {{ COVERAGE_DIR }}/.coverage.integration

# Run end-to-end tests
e2e-test: coverage-dir
    pytest -m "e2e" --cov=labtasker --cov-report=term-missing --cov-report=xml
    mv .coverage {{ COVERAGE_DIR }}/.coverage.e2e

# Run unit tests with tox
tox-unit-test:
    tox -e py310-unit,py311-unit,py312-unit,py313-unit

# Run integration tests with tox
tox-integration-test:
    tox -e py310-integration,py311-integration,py312-integration,py313-integration

# Run end-to-end tests with tox
tox-e2e-test:
    tox -e py310-e2e,py311-e2e,py312-e2e,py313-e2e

# Merge coverage reports
merge-coverage: coverage-dir
    coverage combine {{ COVERAGE_DIR }}/
    coverage report
    coverage xml -o coverage.xml

# Generate command grammar
cmd-grammar:
    cp -r {{ ANTLR_GRAMMAR_DIR }}/*.g4 {{ ANTLR_OUT_DIR }}
    {{ ANTLR }} -Dlanguage=Python3 {{ ANTLR_OUT_DIR }}/*.g4
    rm {{ ANTLR_OUT_DIR }}/*.g4

# Clean project files
clean:
    #!/usr/bin/env bash
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
