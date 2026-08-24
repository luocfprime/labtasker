---
name: labtasker
description: Use Labtasker v2 to queue and run independent ML inference, evaluation, or experiment Tasks; design routes and Workers; inspect or recover Tasks; and convert serial experiment loops into parallel work. Do not use it as a GPU allocator, cluster scheduler, workflow DAG, or artifact store.
---

# Labtasker

Use Labtasker when many independent ML jobs should be distributed across
processes the user already controls, with progress, retries, and small structured
results kept in one place. Keep GPU allocation, process launching, cluster
management, dependent workflows, and artifact storage outside Labtasker.

Prefer the documented public path even when a custom workaround is technically
possible. Do not add a Server, shell wrapper, Queue, or compatibility mechanism
unless the workload needs it.

Documentation map: <https://raw.githubusercontent.com/luocfprime/labtasker/refs/heads/v2/docs/llms.txt>

## Read the relevant reference

- Read [deployment-and-capabilities.md](references/deployment-and-capabilities.md)
  for installation, local versus shared operation, HTTP authentication,
  Windows, Unix-socket requests, package selection, or “does it support this?”
  questions.
- Read [workers-and-workloads.md](references/workers-and-workloads.md) when
  converting an experiment, choosing routes or Queues, binding Task args,
  wrapping a command, reusing a loaded model, or using a distributed launcher.
- Read [operations-and-recovery.md](references/operations-and-recovery.md) for
  idempotent submission, priority, filtering, pagination, updates, cancellation,
  retries, interruption, and rerunning work.

Read every reference relevant to the request before proposing commands. If an
installed version may differ, confirm exact options with `labtasker ... --help`.

## Use the default local path first

Labtasker requires Python 3.11 or newer. In an ordinary POSIX experiment
project, install the complete package:

```bash
python -m pip install labtasker
# or in a uv project
uv add labtasker
```

No MongoDB, configuration file, port, or manual Server start is needed. The
first real Task or Queue operation starts the current directory's local Server
when needed and uses Queue `default`.

Submit one Task:

```bash
labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"cat","reference":"cat"}' \
  --route text-eval
```

Run an existing program once for every compatible Task:

```bash
CUDA_VISIBLE_DEVICES=0 labtasker loop --route text-eval -- \
  python evaluate.py \
    --prediction '%{prediction}' \
    --reference '%{reference}'
```

Start another Worker process on each additional resource already allocated by
the user. Each Worker executes one Task at a time and asks for another when it
finishes. Labtasker does not select the GPU.

Inspect the recorded state and result:

```bash
labtasker task list --status succeeded
labtasker task get t_ABCDEFGHIJKL
```

With a uv project, run these commands through `uv run`. Use
`labtasker config show` to inspect the selected endpoint without starting or
contacting a Server.

## Keep the working model small

- A **Task** is one independent job plus its JSON inputs, state, retry count,
  metadata, and small result.
- A **Worker** is one user-started process that repeatedly executes compatible
  Tasks. The Server stores Tasks, not Worker processes or GPU capacity.
- A **route** is an exact, case-sensitive compatibility label shared by a Task
  and the implementation allowed to run it.
- A **Queue** is an independently managed body of Tasks, not a Worker, GPU,
  model, or route.

Put executable inputs in `args`, searchable grouping data in `metadata`, and
compact JSON outputs in `result`. Save images, videos, checkpoints, trajectories,
and detailed reports outside Labtasker and return their paths, URLs, checksums,
or summaries.

Use a command Worker for an existing executable. Use a Python Worker when a
model, dataset, simulator, or evaluator should be initialized once and reused.

## Preserve explicit behavior

- Do not infer Worker eligibility from Task args; use routes.
- Do not invent v1 aliases or implicit coercion. CLI objects are strict JSON.
- Inspect before mutating. Use `cancel`, `requeue`, and `delete` rather than
  patching status.
- Do not silently start, stop, or reconfigure a shared HTTP Server. Confirm its
  ownership and deployment scope first.
- Do not treat the internal Unix socket as a configurable public endpoint. Use
  automatic local mode or an explicit HTTP Server. Prefer direct argv; add a
  wrapper only when the workload itself needs shell or multi-step logic.
- Treat the Server as authoritative. Local run journals are diagnostic records,
  not a second source of Task state.
