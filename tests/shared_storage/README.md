# Shared-storage integration tests

These opt-in tests exercise Labtasker against a real writable NFS, WekaFS,
Lustre, or comparable distributed-filesystem mount. Ordinary `pytest` runs skip
them when `LABTASKER_SHARED_STORAGE_TEST_DIR` is unset.

Run the suite from one cluster node:

```bash
LABTASKER_SHARED_STORAGE_TEST_DIR=/path/on/shared/storage \
  uv run pytest -m shared_storage_integration tests/shared_storage -vv
```

The directory must already exist and be writable. Each test creates and removes
only its own uniquely named child directory. The suite refuses a path detected
as a known-local filesystem. An unknown filesystem type is accepted because the
production `auto` policy must conservatively select the shared strategy.

The default concurrency probe uses 32 Tasks. Increase it for a longer stability
run:

```bash
LABTASKER_SHARED_STORAGE_TEST_DIR=/path/on/shared/storage \
LABTASKER_SHARED_STORAGE_STRESS_TASKS=200 \
  uv run pytest -m shared_storage_integration tests/shared_storage -vv
```

Coverage includes:

- real filesystem detection and the `auto` fallback;
- `DELETE` journal, `EXTRA` synchronous durability, foreign keys, busy timeout,
  one pooled connection, commit, rollback, close and reopen;
- authenticated HTTP Queue, Task, claim, heartbeat, progress, completion,
  failure, Worker observation and restart persistence;
- concurrent HTTP submissions, updates, reads, claims and completions;
- same-host database-owner exclusion;
- refusal to auto-start a managed-local daemon on shared or unknown storage;
- explicit shared-storage socket daemon startup, idempotent reuse, status and
  stop.

The suite deliberately does not start two Servers on different nodes. Labtasker
uses host-local ownership locks and requires the deployment to provide exactly
one Server owner across nodes. These tests validate the supported topology: one
explicit Server with clients and Workers from the cluster.
