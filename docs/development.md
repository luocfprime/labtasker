# Development

The repository is a uv workspace containing two independent runtime
distributions and one code-free convenience metapackage.

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

The generated `site/` directory is ignored. CI builds the site from scratch.
Pushes that change documentation on `main` publish the `dev` version to
GitHub Pages. A `vVERSION` tag publishes `VERSION`, moves the `latest` alias, and
updates the site's default redirect. Versioning uses Zensical's temporary Mike
integration until native Zensical versioning is available.

Configure GitHub Pages to deploy from the root of the `gh-pages` branch. The
documentation workflow retains older versions on that branch, so it deliberately
does not use the single-artifact Pages deployment flow.

## Dependency and release automation

Dependabot checks the uv workspace and GitHub Actions each week. GitHub reads
`.github/dependabot.yml` from the repository's default branch.

Publishing a GitHub Release runs the complete ordinary gate, the real Linux
distributed suite, clean-wheel smoke tests, and then publishes all three
distributions through PyPI Trusted Publishing. Before the first run:

1. Create a protected GitHub environment named `pypi`, preferably with required
   reviewers.
2. Register `luocfprime/labtasker`, workflow `release.yml`, and environment
   `pypi` as a Trusted Publisher for each PyPI project: `labtasker`,
   `labtasker-client`, and `labtasker-server`. Use a
   [pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
   for a project that does not exist yet.

The publishing workflow has no manual trigger. It accepts only a published
GitHub Release whose `vVERSION` tag exactly matches every maintained version
field.

## Agent workflows

Repository-aware coding agents should start with the root `AGENTS.md`. It records
the product boundary, architectural invariants, source-of-truth order, and
validation expectations without loading the full specification into every task.

Repeatable, task-specific workflows live under `.agents/skills/`. Use the
`release` skill for versioning and release readiness, and the
`public-contract-change` skill when changing behavior across HTTP, Python, CLI,
persistence, and documentation surfaces. Use `documentation` for maintained
user guidance. Use `skill-development` when changing the public Agent Skill: it
tests realistic questions with a full-repository Question Agent and fresh Answer
Agents restricted to `skills/`, then revises the skill until a new holdout
converges.

## Package boundary

- `labtasker-client` contains the Client, Worker runtime, public Python API, and CLI. It
  does not depend on FastAPI, SQLAlchemy, or the Server package.
- `labtasker-server` contains the FastAPI/SQLite service and Server CLI. It does
  not depend on the Client package.
- `labtasker` is a code-free convenience metapackage that installs matching
  Client and Server releases.

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

The historical implementation remains available on branch `v1`. A maintainer
may keep a separate v1 worktree for comparison, but contributors should not
assume that local worktree exists or edit it as part of v2 work. V2 intentionally
provides no protocol, database, configuration, or import compatibility with v1.
