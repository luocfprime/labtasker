# Labtasker [WIP]

A easy-to-use task management tool for lab environments.

## Development Setup

### Pre-commit hooks

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install
```

### Install development dependencies

```bash
pip install -e ".[dev]"
```

### Format code

```bash
make format
```

### Run linters

```bash
make lint
```

### Run tests

Unit tests (no extra dependencies)

```bash
make unit-test
```

Integration tests (requires a docker environment)

```bash
make integration-test
```
