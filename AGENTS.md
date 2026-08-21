# Labtasker agent guide

## Project context

Labtasker is a deliberately small task queue for parallel model inference,
evaluation, and other independent machine-learning experiments. Its main use
case is a long-lived Worker that loads expensive process state once and executes
many parameterized Tasks. Labtasker schedules work; it does not allocate GPUs,
manage a cluster, build workflow DAGs, or store artifacts.

The repository contains two independent runtime distributions and one code-free
convenience metapackage:

- `packages/labtasker-client`: synchronous Client, Python and command Workers,
  public Python API, and `labtasker` CLI.
- `packages/labtasker-server`: FastAPI/SQLite Server, migrations, and
  `labtasker-server` CLI.
- `packages/labtasker`: full installation depending on matching Client and
  Server releases.

Neither package may depend on the other. Keep FastAPI, SQLAlchemy, Alembic, and
Uvicorn out of the Client dependency tree.

## Sources of truth

- `docs/reference/specification.md` is the authoritative product and protocol
  contract. When implementing an existing decision, follow it over historical
  v1 behavior.
- `README.md` and `docs/` are the maintained user-facing explanation. Update
  them when observable behavior changes.
- Tests record executable invariants but do not silently redefine the public
  contract. If a requested design change disagrees with the specification,
  update the specification, implementation, tests, and relevant guide together.
- Branch `v1` and `.worktree/v1` are historical references only. Do not edit the
  v1 worktree as part of v2 work and do not assume v1 compatibility.

Do not recreate parallel planning or comparison documents. Put durable public
decisions in the specification, user guidance in `docs/`, and implementation
rationale close to the code or in a focused architectural note only when it will
remain useful after the change ships.

## Core design invariants

- Minimalism is a product requirement. Add a public concept only for a concrete
  experiment workflow and implement its complete HTTP/Python/CLI slice.
- Queue is the only server-side namespace and scheduling pool. Routes are exact,
  case-sensitive compatibility labels, not resource records.
- The Server stores Tasks, not Worker processes. Each Worker process executes at
  most one Task at a time and claims with a fresh private `run_id`.
- Preserve `run_id` fencing for heartbeat, completion, failure, cancellation,
  unclaim, lease expiry, and retry races. Never weaken a guard to make a stale
  request appear successful.
- Keep one synchronous SQLAlchemy transaction per service command. Mutations use
  `BEGIN IMMEDIATE`; atomic claim remains explicit SQL. Schema changes require an
  Alembic migration and real-file SQLite tests.
- One Server process owns one SQLite file. Do not introduce multi-process claims,
  background ownership, SSE, or an in-memory event source of truth implicitly.
- The public Task states remain `pending`, `running`, `succeeded`, `failed`, and
  `cancelled`. Use explicit lifecycle actions instead of a generic status patch.
- Keep API errors in the stable Labtasker envelope with a fixed code, readable
  message, and structured details. Do not expose FastAPI/Pydantic native errors.
- Keep Client and Server boundary models independent. OpenAPI is the
  machine-readable HTTP contract; do not add a shared runtime model package.
- Preserve deterministic, non-interactive, agent-friendly CLI output: requested
  data on stdout, diagnostics on stderr, and no TTY-dependent behavior.
- Treat platform support as an explicit capability boundary. A feature documented
  as unsupported on the detected platform must fail before network access, Task
  claim, journal creation, or process startup; do not silently degrade it or wait
  for a platform primitive to fail. Lack of release gating alone is not an
  unsupported feature, and a documented portable fallback remains allowed.

## Repository map

- `packages/labtasker-client/src/labtasker/`: Client transport, models, binding,
  Worker runtimes, journals, and CLI.
- `packages/labtasker-server/src/labtasker_server/`: app routes, services,
  persistence models, validation, filtering, and migrations.
- `tests/client`, `tests/server`, `tests/e2e`: ordinary release-gated tests.
- `tests/distributed`: real launcher tests marked `distributed_integration`.
- `docs/reference`: exact public interfaces and full specification.
- `.agents/skills`: repository-scoped workflows loaded only when relevant.

## Working agreements

- Inspect `git status` and the relevant diff before editing. Preserve unrelated
  user changes in a dirty worktree.
- Use `uv` from the repository root. Do not introduce another environment,
  package manager, build frontend, formatter, or test runner.
- Prefer the smallest change that satisfies the contract. Do not leave aliases,
  compatibility switches, unused abstractions, or speculative extension points.
- Keep public documentation and code terminology as `Task`, `Queue`, `Worker`,
  `Client`, and `Server` when referring to Labtasker concepts.
- A public contract change normally requires checking Server schema/service/app,
  Client model/transport/API/CLI, OpenAPI, docs, and tests. Use the
  `public-contract-change` skill for that workflow.
- Do not add or update production dependencies without explaining the concrete
  need and verifying the Client/Server package boundary.
- Never hand-edit generated `site/`, `dist/`, caches, local `.labtasker/` data, or
  `uv.lock` package records. Regenerate them with their owning tool.
- Do not commit, tag, push, create a GitHub release, or publish packages unless
  the user explicitly authorizes that external action. Use the `release` skill
  for release preparation or publication.

## Validation

Run focused tests while iterating, then choose final checks proportional to the
change. The complete ordinary gate is:

```bash
uv sync --all-packages --group dev --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/labtasker-client/src packages/labtasker-server/src
uv run pytest
uv run zensical build --clean
uv build --all-packages
```

Also run `uv run pytest -m distributed_integration` when changing launcher,
fork, process-group, rank, or distributed-worker behavior and the required ML
dependencies are installed. A documentation-only change needs the documentation
build and relevant link checks, not unrelated runtime tests.
