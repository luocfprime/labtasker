# Development Guide

## Development Setup

### Pre-commit hooks

```bash
# Install pre-commit hooks for code formatting
pip install pre-commit
pre-commit install
```

### Install development dependencies

```bash
pip install -e ".[dev]"
```

## Development utilities

### Format code

```bash
just format
```

### Run linters

```bash
just lint
```

## Tests

### Test setups

Tests are divided into unit tests, integration tests, and end-to-end tests.
Some test cases are shared between unit tests, integration tests and end-to-end tests.

!!! note "Test settings"

    Testcases are marked with `pytest.mark.unit`, `pytest.mark.integration`, and `pytest.mark.e2e`.

    Different tests adopts the following setting:

    | Test type         | Database               | Server & Client                                   |
    |-------------------|------------------------|---------------------------------------------------|
    | Unit tests        | MongoMock              | TestClient & ASGITransport, patched httpx client  |
    | Integration tests | docker mongodb service | TestClient & ASGITransport, patched httpx client  |
    | End-to-end tests  | docker mongodb service | docker fastapi service, httpx client to localhost |

### Run tests

Unit tests:

```bash
just unit-test
```

!!! danger "Do not run integration and e2e tests in production env"

    Do not run integration and e2e tests in production env, as they will erase the database for testing.

Integration tests:

```bash
just integration-test
```

End-to-end tests (quite time-consuming):

```bash
just e2e-test
```
