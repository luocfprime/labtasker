# Labtasker v2

Labtasker is a small task queue for parallel machine-learning experiments. The
v2 implementation is being rebuilt from the reviewed contract in
[`LABTASKER_V2_SPEC.md`](LABTASKER_V2_SPEC.md).

The repository publishes two independent distributions:

- `labtasker`: synchronous Python client, Worker API, and user CLI.
- `labtasker-server`: FastAPI/SQLite server and server CLI.

The v1 implementation is intentionally not part of the v2 history. During the
rewrite it is available only as a reference worktree under `.worktree/v1`.

