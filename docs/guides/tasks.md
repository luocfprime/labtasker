# Task operations

## Submit

```python
import labtasker

task = labtasker.submit_task(
    {"seed": 7, "lr": 0.001},
    name="baseline",
    metadata={"group": "paper"},
    priority=10,
    max_attempts=3,
    routes=["train-v1", "train-v2"],
)
```

The CLI accepts the same JSON data without guessing scalar types:

```bash
labtasker task submit \
  --args '{"seed":7,"lr":0.001}' \
  --metadata '{"group":"paper"}' \
  --priority 10 \
  --route train-v1 \
  --route train-v2
```

Routes default to `default`. Supplying a Task ID makes creation idempotent only
when the complete submitted representation is identical; conflicting reuse is
an error.

## Inspect

```bash
labtasker task get t_ABCDEFGHIJKL
labtasker task list --status pending --limit 100
labtasker task count --filter 'metadata.group == "paper"'
```

List output is one page. Use the returned `next_cursor` explicitly for the next
page; cursors are opaque and bound to the query and ordering.

## Update

Update one non-running Task:

```bash
labtasker task update t_ABCDEFGHIJKL \
  --changes '{"priority":20,"routes":["train-v2"]}'
```

Or explicitly update all matching non-running Tasks:

```bash
labtasker task update \
  --filter 'status == "pending" and "train-v1" in routes' \
  --changes '{"routes":["train-v1","train-v2"]}'
```

The bulk operation is atomic. It reports `matched` and `updated`. There is no
separate route-mutation command because routes are ordinary explicit Task data.

## Lifecycle actions

```bash
labtasker task cancel t_ABCDEFGHIJKL
labtasker task requeue t_ABCDEFGHIJKL
labtasker task delete t_ABCDEFGHIJKL
```

- cancel produces a terminal cancelled Task;
- requeue returns a non-running Task to pending and resets `attempt`;
- delete permanently removes a non-running Task.

A running Task cannot be updated, requeued, or deleted. Cancellation is allowed:
the run is fenced immediately, while local code follows the Worker's configured
cooperative or forced-stop behavior.

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
