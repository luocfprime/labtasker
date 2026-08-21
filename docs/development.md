# Development

The repository is a uv workspace containing two independent distributions.

```bash
uv sync --all-packages --group dev --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/labtasker-client/src packages/labtasker-server/src
uv run pytest
uv build --all-packages
```

Build and preview the documentation with the pinned Zensical development
dependency:

```bash
uv run zensical serve
uv run zensical build --clean
```

The generated `site/` directory is ignored. CI builds the site from scratch but
does not publish it.

## Agent workflows

Repository-aware coding agents should start with the root `AGENTS.md`. It records
the product boundary, architectural invariants, source-of-truth order, and
validation expectations without loading the full specification into every task.

Repeatable, task-specific workflows live under `.agents/skills/`. Use the
`release` skill for versioning and release readiness, and the
`public-contract-change` skill when changing behavior across HTTP, Python, CLI,
persistence, and documentation surfaces.

## Package boundary

- `labtasker` contains the Client, Worker runtime, public Python API, and CLI. It
  does not depend on FastAPI, SQLAlchemy, or the Server package.
- `labtasker-server` contains the FastAPI/SQLite service and Server CLI. It does
  not depend on the Client package.

Build artifacts must preserve that independence and include the Apache-2.0
license.

## Test suites

Ordinary unit and integration tests run without ML frameworks. The explicitly
marked launcher suite exercises real `torchrun` and Accelerate installations:

```bash
uv run pytest -m distributed_integration
```

Launcher coverage includes the supported outer-wrapper topology, environment
propagation, one completion reporter, at-fork context clearing, and rejection of
an inner per-rank Worker loop.

The checked-in v1 implementation remains available on branch `v1` and in the
local `.worktree/v1` reference during development. V2 intentionally provides no
protocol, database, configuration, or import compatibility with v1.
