# Manage Tasks

Use Task operations to inspect or change an experiment without restarting its
Workers. Submission adds work; updates change non-running work; lifecycle
actions make cancellation, requeue, and deletion explicit.

## Submit

```python
import labtasker

task = labtasker.submit_task(
    {"prompt": "a red panda astronaut", "seed": 7},
    name="prompt-007",
    metadata={"benchmark": "prompt-set-a"},
    priority=10,
    max_attempts=3,
    routes=["sdxl-diffusers-v1", "sdxl-diffusers-v2"],
)
```

The CLI accepts the same JSON data without guessing scalar types:

```bash
labtasker task submit \
  --args '{"prompt":"a red panda astronaut","seed":7}' \
  --metadata '{"benchmark":"prompt-set-a"}' \
  --priority 10 \
  --route sdxl-diffusers-v1 \
  --route sdxl-diffusers-v2
```

Routes default to `default`. Supplying a Task ID makes creation idempotent only
when every submitted field is the same. Reusing the ID with different data is
an error.

## Experimental Task dependencies

To run an evaluation after preparation succeeds, list the preparation Task ID:

```python
with labtasker.Client() as client:
    prepared = client.submit_task({"dataset": "samples"}, routes=["prepare"])
    evaluation = client.submit_task(
        {"input_task_id": prepared.id},
        routes=["evaluate"],
        dependencies=[prepared.id],
    )
```

The CLI uses repeatable `--dependency TASK_ID`:

```bash
labtasker task submit --route evaluate \
  --dependency t_ABCDEFGHIJKL --dependency t_MNOPQRSTUVWX
labtasker task update t_0123456789-_ --changes '{"dependencies":[]}'
```

The default is `[]`. Every ID resolves in the Task's own Queue and must exist
with status `succeeded` before a Worker can claim the Task. Lists preserve order
and duplicates, but neither controls execution order. You may submit predecessors
later. Replace or clear the list through ordinary non-running Task updates;
requeue retains it. This feature is experimental and its interface may evolve.

The Server accepts missing IDs, self references, and cycles. Unsatisfied
dependencies simply keep a Task pending without consuming attempts. Failed or
cancelled predecessors do not automatically fail or cancel dependent Tasks.
Users own graph correctness, recovery, Worker startup/lifetime, and diagnosis of
waiting work. Existing Worker idle timeouts still apply. The Server does not
validate graphs, diagnose pending reasons, or transfer results.

Read IDs from the Task's `dependencies` or Python `task_info().dependencies`.
Fetch predecessor results yourself with `client.get_task(id, queue=task.queue)`;
use your files or artifact store for large outputs. The example's `input_task_id`
is an ordinary application argument, not automatic result injection. To inspect
waiting work, query each predecessor's current state; a missing record is an
unsatisfied reference. If your script traverses the graph, track visited IDs to
handle cycles. A network error does not establish that a predecessor is absent.

Dependencies are checked only when a new run is claimed. Later predecessor
deletion or result edits do not interrupt that run or guarantee a result snapshot.
Deleting a non-running Task requires no dependency order and does not alter other
Tasks' lists. Those references wait if the ID disappears and refer to the new Task
if that ID is reused. Users are responsible for retaining data they still need.

## Inspect

For a browser view of Queue progress, Task details, and result columns, use
[Labtasker WebUI](webui.md). To inspect Tasks from the CLI:

```bash
labtasker task get t_ABCDEFGHIJKL
labtasker task list --status pending --limit 100
labtasker task count --filter 'metadata.group == "paper"'
```

List output is one page. Pass the returned `next_cursor` to request the next
page. Do not inspect or modify a cursor; it is tied to the original query and
ordering.

Running Workers may publish a latest progress snapshot for dashboards and
external early-stop controllers:

```python
labtasker.report_progress(
    {
        "completed": 1200,
        "total": 5000,
        "metrics": {"val_loss": 0.8, "best_val_loss": 0.75},
        "steps_without_improvement": 300,
    }
)
```

The next report replaces this object. The object remains unrestricted.
`completed` and `total` are an optional display convention: Labtasker WebUI
shows a determinate indicator only when both are finite numbers and
`0 <= completed <= total` with `total > 0`. Other keys retain only the meaning
assigned by the workload or controller.

An external controller can inspect Tasks, compare progress within an experiment
group, apply the experiment's explicit early-stop policy, and call
`cancel_task(task.id)` only for the selected running Tasks.
Cancellation uses the existing cooperative/forced-stop contract; Labtasker does
not choose an early-stop policy. The last snapshot remains visible after cancel
for diagnosis and is cleared if a later claim starts a new attempt.

## Update

Update one non-running Task:

```bash
labtasker task update t_ABCDEFGHIJKL \
  --changes '{"priority":20,"routes":["sdxl-diffusers-v2"]}'
```

Or explicitly update all matching non-running Tasks:

```bash
labtasker task update \
  --filter 'status == "pending" and "sdxl-diffusers-v1" in routes' \
  --changes '{"routes":["sdxl-diffusers-v1","sdxl-diffusers-v2"]}'
```

The bulk operation updates every matching Task or changes nothing if one update
fails. It reports `matched` and `updated`. Routes are updated through the same
Task operation as other fields.

## Lifecycle actions

```bash
labtasker task cancel t_ABCDEFGHIJKL
labtasker task requeue t_ABCDEFGHIJKL
labtasker task delete t_ABCDEFGHIJKL
```

- cancel accepts pending or running Tasks and produces a terminal cancelled
  Task; repeating it on an already cancelled Task is safe;
- requeue accepts pending, failed, or cancelled Tasks, returns the Task to
  pending, and resets `attempt`;
- delete permanently removes a non-running Task.

A running Task cannot be updated, requeued, or deleted. Cancellation is allowed:
the Server immediately rejects further updates from that run, while local code
follows the Worker's configured cooperative or forced-stop behavior. Succeeded
and failed Tasks cannot be cancelled, and a succeeded Task cannot be requeued;
submit a new Task to rerun a successful experiment.

## Archive finished Tasks

Keep old results without including them in daily lists, counts or batch updates:

```bash
labtasker task update --filter 'status in ["succeeded", "failed", "cancelled"]' \
  --changes '{"archived":true}'
labtasker task list --include-archived --filter 'archived == True'
labtasker task update --include-archived --filter 'archived == True' \
  --changes '{"archived":false}'
```

Archival preserves status and results. Only terminal Tasks can be archived;
including a pending Task in a batch archive causes the entire batch to fail.
ID-based get, update and delete still work. Requeue restores visibility, and
archived successful predecessors continue to satisfy dependencies. To export all
history, include archives explicitly. A Queue containing only archived Tasks is
still non-empty and requires `--cascade` for deletion.

## Queues

```bash
labtasker queue create experiments
labtasker queue list
labtasker queue delete experiments
labtasker queue delete experiments --cascade
```

Deleting a non-empty Queue requires explicit `--cascade`. The `default` Queue is
created when a fresh database is initialized, not recreated after an explicit
deletion.

## Diagnose pending routes

Pending counts include Tasks waiting for dependencies. Inspect their dependency
IDs yourself when needed; route presence alone does not establish claimability.

Inspect all routes referenced by pending Tasks, then compare observed Workers:

```bash
labtasker task count --status pending --group-by routes
labtasker worker count --group-by route,status
labtasker worker list --filter 'route == "sdxl"'
```

These commands return one page; follow `next_cursor` with `--cursor` before
interpreting an absent group as zero. A Task compatible with multiple routes
counts in every route group. The top-level Task count counts each Task once.

Worker `idle` means awaiting work; `busy` includes execution, reporting and
cleanup after `finish()`. An active route has at least one unexpired observation,
whether idle or busy. Reporting is periodic and may be delayed, so zero observed
Workers is a diagnostic clue rather than proof that no process exists. Task state
and leases remain authoritative. See [Worker observations](../reference/http-api.md#worker-observations)
for freshness and [grouped counts](../reference/python-api.md#grouped-counts) for Python use.
