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

## Inspect

```bash
labtasker task get t_ABCDEFGHIJKL
labtasker task list --status pending --limit 100
labtasker task count --filter 'metadata.group == "paper"'
```

List output is one page. Pass the returned `next_cursor` to request the next
page. Do not inspect or modify a cursor; it is tied to the original query and
ordering.

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
