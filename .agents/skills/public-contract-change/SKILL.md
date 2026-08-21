---
name: public-contract-change
description: Change Labtasker's public Task lifecycle, HTTP API, Python API, CLI, configuration, query language, or persisted schema while keeping every public surface and invariant aligned. Do not use for internal refactors with no observable behavior change.
---

# Change the public contract

Read the relevant section of `docs/reference/specification.md` before editing.
State the current contract, the requested change, and any unresolved behavioral
choice. If the request intentionally changes a decided behavior, update the
specification rather than treating the old text as an implementation obstacle.

Trace the complete affected slice before editing:

- persistence model and Alembic migration, when stored data changes;
- Server validation, service transaction, endpoint, error envelope, and OpenAPI;
- Client boundary model, transport, public method/function, and retry behavior;
- CLI command, stdout/stderr shape, help, and exit behavior;
- Worker runtime, journal, fencing, or concurrency behavior when applicable;
- user guides, references, examples, and tests.

Keep the Client and Server distributions independent; duplicate small boundary
models when necessary instead of creating a shared runtime package. Preserve
explicit lifecycle actions and `run_id` fencing. Define idempotency, concurrent
state changes, uncertain transport outcomes, validation errors, and migration
behavior instead of relying only on the happy path.

Add focused tests at the lowest useful layer plus at least one real boundary test
for each changed public surface. Use independent SQLite connections for race or
transaction claims. Verify generated OpenAPI whenever endpoint schemas or errors
change.

Finish by checking the specification, implementation, tests, and user docs for
the old term or behavior. Run targeted tests during development and the relevant
validation matrix from `AGENTS.md` before handoff.
