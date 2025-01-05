# Development Guide

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

```bash
make test
```


## Documentation

```bash
cd docs
mike serve
# or use mkdocs to live-reload
mkdocs serve
```

Check list of versions:

```bash
make list
```

Check other utilities in `Makefile`.
