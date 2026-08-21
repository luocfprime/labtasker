---
name: labtasker
description: Use Labtasker v2 to queue and run independent ML inference, evaluation, or experiment Tasks; design routes and Workers; inspect or recover Tasks; and convert serial experiment loops into parallel work. Do not use it as a GPU allocator, cluster scheduler, workflow DAG, or artifact store.
---

# Labtasker

Use Labtasker as a deliberately small Task queue. Keep resource allocation and
process supervision in the user's existing launcher, scheduler, or shell.

Documentation: <https://luocfprime.github.io/labtasker/>

## Model the workload

- Use a **Queue** as the only server-side namespace and scheduling pool.
- Use exact, case-sensitive **routes** for code, model, or hardware
  compatibility. A Task may name several routes; one Worker claims through one
  route.
- Put executable inputs in `args`, searchable grouping data in `metadata`, and
  compact JSON outputs in `result`. Store large artifacts elsewhere and return
  paths or URLs.
- Start multiple Worker processes for parallelism. Each Worker runs at most one
  Task at a time; Labtasker does not allocate GPUs or register Worker resources.

Prefer one Queue with descriptive routes over creating a Queue per Worker or
GPU. Create another Queue only for a body of work that needs an independently
managed namespace.

## Establish configuration

For a local setup, start one Server and use its default Queue:

```bash
labtasker-server serve
labtasker config show
```

Use environment variables or a project-local `.labtasker/config.toml` for a
different target:

```toml
url = "http://127.0.0.1:8000"
queue = "default"
# token = "secret"
```

The corresponding environment variables are `LABTASKER_URL`,
`LABTASKER_QUEUE`, and `LABTASKER_TOKEN`. A non-loopback Server bind requires
`LABTASKER_SERVER_TOKEN`. Do not put secrets in commands, logs, Task data, or
committed configuration.

Do not silently launch, stop, or reconfigure a shared Server. Confirm the
deployment scope when it is not already clear from the user's environment.

## Submit explicit JSON Tasks

The CLI accepts one strict JSON object; it does not infer types from repeated
shell flags:

```bash
labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"cat","reference":"cat","seed":7}' \
  --metadata '{"benchmark":"paper-a"}' \
  --priority 10 \
  --max-attempts 3 \
  --route exact-match
```

For generated submission scripts, prefer the typed Python API:

```python
import labtasker

for seed in range(10):
    labtasker.submit_task(
        {"prompt": "a ceramic fox", "seed": seed},
        name=f"sample-{seed}",
        metadata={"sweep": "baseline"},
        routes=["sdxl-v2"],
        max_attempts=3,
    )
```

Use a caller-chosen Task ID when submission must be safely repeatable. Reusing
that ID is idempotent only for an identical submitted representation.

## Choose a Worker style

Use a command Worker for an existing executable and a Python Worker when
expensive process state should be loaded once and reused.

### Command Worker

```bash
CUDA_VISIBLE_DEVICES=0 labtasker loop --route evaluate -- \
  python evaluate.py --prediction '%{prediction}' --reference '%{reference}'
```

The `--` separator is required. Each `%{path}` expands into exactly one argv
element; Labtasker never invokes a shell or re-splits the result. A zero exit
code succeeds with `{}` and a nonzero exit code is a charged Task failure. The
child can call `labtasker.finish({...}, skip_if_no_labtasker=True)` to store a
result.

### Python Worker

```python
import labtasker


@labtasker.loop(route="embed", idle_timeout=300)
def embed(
    model,
    text: str = labtasker.TaskArg(),
    normalize: bool = labtasker.TaskArg(default=True),
) -> None:
    vector = model.encode(text, normalize=normalize)
    labtasker.finish({"embedding": vector.tolist()})


embed(load_model_once())
```

Only `TaskArg(...)` parameters come from the Task. Other arguments are fixed
Worker inputs. Binding is strict, extra Task args remain available from
`labtasker.task_info().args`, and `TaskArg(path="metric.threshold")` selects a
nested object field.

A normal return succeeds with `{}`. Use `finish(result)` when the result must be
accepted before cleanup continues. Only JSON-compatible objects belong in Task
data.

## Inspect and mutate deliberately

Finite CLI operations return formatted JSON on stdout:

```bash
labtasker task count --status pending
labtasker task list \
  --filter 'status == "failed" and metadata.sweep == "baseline"' \
  --limit 100
labtasker task get t_ABCDEFGHIJKL
```

`task list` returns one page. Follow `next_cursor` explicitly with the same
selectors and ordering; do not assume the first 100 Tasks are the complete set.
Use `exists(path)` or `missing(path)` when a queried JSON path may be absent.

Inspect before mutating, then use the narrow lifecycle action:

```bash
labtasker task update t_ABCDEFGHIJKL --changes '{"priority":20}'
labtasker task update \
  --filter 'status == "pending" and "old-route" in routes' \
  --changes '{"routes":["new-route"]}'
labtasker task cancel t_ABCDEFGHIJKL
labtasker task requeue t_ABCDEFGHIJKL
labtasker task delete t_ABCDEFGHIJKL
```

Bulk update is atomic. Running Tasks cannot be updated, requeued, or deleted;
cancel is the supported way to revoke one. Requeue resets `attempt` to zero.
Deletion is permanent and requires the user's intent to be clear.

## Handle failures at the right level

In Python Workers:

- raise `TransientError` for an uncharged incident that should return to pending;
- raise `TaskError` for a charged Task-specific failure and continue the Worker;
- raise `FatalWorkerError` for a charged failure that should also stop the Worker.

Ordinary exceptions behave like `TaskError`. Charged failures retry while
`attempt < max_attempts`, then become `failed`. A healthy long Task has no
execution timeout; heartbeat lease recovery fences stale runs with a private
`run_id`.

For cooperative cancellation, poll `cancellation_requested()`. Configure a
finite force-stop timeout only when the code can tolerate forced termination.
Use the local `.labtasker/runs/` journal for diagnostics, but treat the Server as
authoritative.

## Preserve the v2 contract

Check `labtasker ... --help` when the installed version may differ. Do not invent
v1 compatibility spellings: v2 uses `succeeded`, `result`, `attempt`,
`max_attempts`, `TaskArg`, `%{path}`, and full command names such as `task list`.

For single-node `torchrun` or Accelerate, keep one Labtasker command Worker
outside the launcher and let only the framework's main rank call `finish()`.
Multi-node resource allocation remains the external scheduler's job.
