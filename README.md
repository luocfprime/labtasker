# Labtasker [WIP]

![unit-test-matrix](https://github.com/fkcptlst/labtasker/actions/workflows/unit-test-matrix.yml/badge.svg)
[![codecov](https://codecov.io/gh/fkcptlst/labtasker/graph/badge.svg?token=KQFBV3QRPY)](https://codecov.io/gh/fkcptlst/labtasker)
![Python version](https://img.shields.io/badge/Python-3.8%20|%203.9%20|%203.10%20|%203.11%20|%203.12%20|%203.13-blue)

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
