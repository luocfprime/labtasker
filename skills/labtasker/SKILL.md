---
name: labtasker
description: Use when helping users distribute ML experiment tasks, convert for-loop scripts into task queues, manage parallel GPU workers, handle failures/retries, or query/filter/update/delete experiment results with Labtasker
---

# Labtasker

## Overview

Labtasker replaces `for` loops in ML experiment scripts with a task queue, enabling parallelization, failure handling, and task management with minimal code changes.

**Links**: [GitHub](https://github.com/luocfprime/labtasker) | [Docs](https://luocfprime.github.io/labtasker/)

## Core Concepts

- **Queue**: Named task bucket; all tasks belong to one queue; workers pull from it.
- **Task fields**: `task_id`, `task_name`, `status` (pending/running/success/failed/cancelled), `args` (dict), `metadata` (dict), `summary` (dict, always a dict — never None — even if no metrics written), `priority`, `max_retries`, `retries`, `created_at`, `last_modified`, `start_time` (None until task starts running), `worker_id` (None until a worker claims the task).
- **Loop**: Continuously fetches pending tasks in descending priority order (highest `priority` value first); exits automatically when no more pending tasks match.
- **Retries**: `retries` starts at `0` on the first attempt. The loop auto-increments it on each task failure. When `retries` reaches `max_retries`, the task is permanently marked `failed`. Use `reset_pending=True` to reset both status and retries when re-queuing.
- **No More, No Less**: Submitted `args` keys must EXACTLY match what the run script/function declares as required. Extra = inconsistent records. Missing = fetch failure. Exception: with `pass_args_dict=True` + `required_fields`, only the listed keys are required — extra keys in `args` are accessible via `args.get(key, default)` for variable-arg tasks.

## Setup

```bash
pip install labtasker
labtasker-server serve &    # start server
labtasker init              # interactive config — creates .labtasker/config.toml
labtasker queue create-from-config
```

---

## 1. Submitting Tasks

### CLI

```bash
# Basic
labtasker task submit -- --lr=0.001 --model=resnet

# With name, metadata, priority, max-retries
labtasker task submit \
    --name grid_search \
    --metadata '{"tags": ["v1", "experimental"], "note": "baseline run"}' \
    --priority 10 \
    --max-retries 5 \
    -- --lr=0.001 --model=resnet

# Batch submit in a loop
for lr in 0.001 0.01 0.1; do
    for model in resnet vit; do
        labtasker task submit \
            --name grid_search \
            --metadata '{"tags": ["v1"]}' \
            -- --lr=$lr --model=$model
    done
done

# Alternative: pass args as JSON dict string
labtasker task submit --args '{"arg1": 0, "arg2": 3}'

# Nested args via dot-notation — --foo.bar=1 becomes args["foo"]["bar"] = 1
labtasker task submit -- --optimizer.lr=0.01 --optimizer.momentum=0.9
```

Special characters in args — always use `--key=value` form:
```bash
labtasker task submit -- --value=-1 --label="" --desc="hello world"
```

### Python

```python
import labtasker

for lr in [0.001, 0.01, 0.1]:
    for model in ["resnet", "vit"]:
        labtasker.submit_task(
            task_name="grid_search",           # optional
            args={"arg1": lr, "arg2": model},
            metadata={                          # optional — use for filtering/tagging
                "tags": ["v1", "experimental"],
                "note": "baseline run",
            },
            max_retries=3,                      # optional, default 3
            priority=0,                         # optional, default 0 (medium)
        )

# Nested args as dict (use Python loop to access nested values)
labtasker.submit_task(
    args={
        "args_a": {"a": 1, "b": "boy"},
        "args_b": {"foo": 2, "bar": "baz"},
    },
    metadata={"tags": ["sweep-v2"]},
)
```

---

## 2. Running Tasks (Loop)

### CLI

```bash
# Basic — %(key) interpolates TOP-LEVEL task args at runtime
labtasker loop -- python train.py --lr '%(lr)' --model '%(model)'

# With metadata filter (only run tasks tagged "v1")
labtasker loop \
    --extra-filter '"v1" in list(metadata.tags)' \
    -- python train.py --lr '%(lr)' --model '%(model)'

# Env vars MUST go outside the loop command
CUDA_VISIBLE_DEVICES=0 labtasker loop -- python train.py --lr '%(lr)'

# Multiple parallel GPU workers — run the same command in the background per GPU
CUDA_VISIBLE_DEVICES=0 labtasker loop -- python train.py --lr '%(lr)' --model '%(model)' &
CUDA_VISIBLE_DEVICES=1 labtasker loop -- python train.py --lr '%(lr)' --model '%(model)' &
CUDA_VISIBLE_DEVICES=2 labtasker loop -- python train.py --lr '%(lr)' --model '%(model)' &
CUDA_VISIBLE_DEVICES=3 labtasker loop -- python train.py --lr '%(lr)' --model '%(model)' &
wait

# Complex scripts where %(var) appears inside multi-line logic — use --script-path
LABTASKER_TASK_SCRIPT=$(mktemp)
cat <<'EOF' > "$LABTASKER_TASK_SCRIPT"
LOG_DIR=/logs/%(dataset)/%(model)
python train.py --dataset %(dataset) --model %(model) --log-dir $LOG_DIR
EOF
labtasker loop --script-path $LABTASKER_TASK_SCRIPT
```

**`%(key)` accesses top-level args keys only.** If args has a nested dict (e.g., `{"optimizer": {"lr": 0.01}}`), use the Python loop instead — CLI cannot interpolate nested values.

### Python

```python
import labtasker
from labtasker import Required

# Required() fields are auto-filled from task args; types are cast automatically.
# Parameter name MUST match the args key exactly.
@labtasker.loop()
def main(arg1: int = Required(), arg2: int = Required()):
    result = arg1 + arg2
    print(f"The result is {result}")

if __name__ == "__main__":
    main()

# With extra_filter (Python query string)
@labtasker.loop(
    extra_filter='"v1" in list(metadata.tags)'
)
def main(lr: float = Required(), model: str = Required()):
    train(lr=lr, model=model)

# Access args as dict instead of keyword args
@labtasker.loop(required_fields=["lr", "model"], pass_args_dict=True)
def main(args):
    train(lr=args["lr"], model=args["model"])

# Nested args — param name must match the args key; resolver receives args[param_name]
from typing import Any, Dict
from typing_extensions import Annotated
from dataclasses import dataclass

@dataclass
class ArgsGroupA:
    a: int
    b: str

@dataclass
class ArgsGroupB:
    foo: int
    bar: str

@labtasker.loop()
def main(
    args_a: Annotated[Dict[str, Any], Required(resolver=lambda a: ArgsGroupA(**a))],
    args_b=Required(resolver=lambda b: ArgsGroupB(**b)),
):
    print(f"got args_a: {args_a}")
    print(f"got args_b: {args_b}")

# Simple nested dict access — use identity resolver to receive the raw dict
# (no dataclass needed; resolver receives args[param_name])
@labtasker.loop()
def main(optimizer=Required(resolver=lambda x: x)):
    # optimizer is the raw dict: {"lr": 0.001, "momentum": 0.9}
    lr = optimizer["lr"]
    momentum = optimizer.get("momentum", 0.9)
```

The loop exits automatically when no more pending tasks match the filter.

**Dot-separated keys are nested**: `--foo.bar=1` in CLI becomes `args["foo"]["bar"] = 1` in Python. Access nested args correctly: `task_info().args["foo"]["bar"]`, not `task_info().args["foo.bar"]`.

---

## 3. Querying (Listing) Tasks

### CLI

```bash
# By status
labtasker task ls -s pending
labtasker task ls -s running
labtasker task ls -s failed
labtasker task ls -s success

# Python-native filter syntax
labtasker task ls -f 'args.lr > 0.01' -q --no-pager
labtasker task ls -f 'task_name == "grid_search"' -q --no-pager
labtasker task ls -f '"v1" in list(metadata.tags)' -q --no-pager
labtasker task ls -f 'created_at >= date("3 hours ago")' -q --no-pager
labtasker task ls -f 'args.lr > 0.01 and "v1" in list(metadata.tags)' -q --no-pager
labtasker task ls -f 'regex(task_name, "^grid-.*")' -q --no-pager

# Filter by summary fields — same dot-notation works on any field
labtasker task ls -s success -f 'summary.acc > 0.9' --no-pager

# Filter with OR
labtasker task ls -f 'status == "failed" or status == "pending"' --no-pager

# Sort results (CLI only — Python requires manual sorting)
labtasker task ls -s success -S 'created_at:desc' --no-pager
labtasker task ls -s success -S 'summary.acc:desc' --no-pager

# -q prints only task IDs (useful for piping); --no-pager disables pager
```

**Filter operators** — Python syntax: `==`, `>`, `<`, `>=`, `<=`, `in`, `and`, `or`, `regex()`, `date()`
**NOT supported**: `!=`, `not`, `not in` (three-valued logic). Workaround for status: use `-s STATUS` flag. For string negation: use `regex()`.
**`-s` and `-f` are ANDed**: using both narrows results to tasks matching both conditions.
**Default `--limit` is 100.** For batch operations (cancel/delete/update all matching tasks), always pass `--limit 10000` or a large value to avoid silently missing tasks beyond 100.

### Python

```python
import labtasker

# List by status
response = labtasker.ls_tasks(status="failed")
tasks = response.content  # List[Task]

# With filter (Python query string)
response = labtasker.ls_tasks(
    extra_filter='args.lr > 0.01 and "v1" in list(metadata.tags)',
    limit=100,
)

# Filter by summary field (same dot-notation)
response = labtasker.ls_tasks(
    status="success",
    extra_filter='summary.acc > 0.9',
    limit=1000,
)

# ls_tasks() has NO sort parameter — sort results manually in Python
tasks_sorted = sorted(
    response.content,
    key=lambda t: t.summary.get("acc") or 0,
    reverse=True,
)

# Access task fields
for task in response.content:
    print(task.task_id, task.status, task.args, task.metadata, task.summary)
    print(task.created_at, task.worker_id, task.retries)
```

---

## 4. Task Summary (Write and Read)

`task.summary` is a dict stored per-task. Jobs write metrics into it; you read it back after tasks complete.

### Writing summary inside the loop

Use `labtasker.report_task_status()` to persist metrics. **This call is optional** — if you simply return from the function without calling it, the loop auto-marks the task `success` with no summary. Call it when you want to record metrics.

```python
import labtasker
from labtasker import Required

@labtasker.loop()
def main(lr: float = Required(), model: str = Required()):
    acc, loss = train(lr=lr, model=model)

    # Optional: write metrics into the task summary; status="running" keeps the task alive
    # Loop auto-marks "success" on normal return (after this call completes)
    labtasker.report_task_status(
        task_id=labtasker.task_info().task_id,
        status="running",      # loop marks success on normal return
        summary={"acc": acc, "loss": loss},
    )
```

To finish a task early with a final status from deep inside your code — use `labtasker.finish()`. It stops the heartbeat, writes `summary.json` to the local log directory, and reports to the server. The loop will not overwrite a status already set by `finish()`. Only accepts `"success"` or `"failed"`.

**Retry behavior**: `finish(status="failed")` behaves like an exception — the server increments `retries` and resets the task to `pending` if `retries < max_retries` (so it WILL be retried). To permanently stop retries without marking as failed, use `report_task_status(status="cancelled")` instead.

**Idempotent**: calling `finish()` twice is safe — the second call is silently skipped.

```python
@labtasker.loop()
def main(lr: float = Required(), model: str = Required()):
    acc = train(lr=lr, model=model)
    if acc < 0.01:
        # Marks as failed — will be retried if retries < max_retries
        labtasker.finish(status="failed", summary={"acc": acc, "reason": "too_low"})
        return
    labtasker.finish(status="success", summary={"acc": acc})
```

To cancel a task mid-run (e.g., on NaN loss) — use `report_task_status(status="cancelled")` then `return`. The loop preserves the cancelled status and will NOT retry it:

```python
@labtasker.loop()
def main(lr: float = Required(), model: str = Required()):
    task = labtasker.task_info()
    if task.retries == 0:
        data = expensive_preprocess()  # only on first attempt
    else:
        data = load_cached_data()      # skip on retries

    loss = train_step(data)
    if math.isnan(loss):
        labtasker.report_task_status(
            task_id=task.task_id,
            status="cancelled",  # preserves cancelled — loop will not overwrite
        )
        return  # stop this task; loop moves to next pending task
```

### Reading summaries after tasks complete

```python
import labtasker

# Fetch all successful tasks and print their summaries
response = labtasker.ls_tasks(status="success", limit=1000)
for task in response.content:
    print(
        f"task_id={task.task_id} "
        f"args={task.args} "
        f"summary={task.summary}"
    )

# Aggregate: collect metric from summary and rank
results = [
    {"lr": t.args["lr"], "model": t.args["model"], "acc": t.summary.get("acc")}
    for t in response.content
]
results.sort(key=lambda x: x["acc"] or 0, reverse=True)
for r in results:
    print(r)
```

---

## 5. Updating Tasks

### Update semantics

**CLI `-u 'field=value'`** patches individual dot-nested fields: `-u 'args.lr=0.005'` sets only `args.lr`, all other args untouched.

**Python `TaskUpdateRequest`** merges by default: only the keys you include inside a dict field are written; other existing keys inside that dict are preserved. Unspecified top-level optional fields (`args`, `metadata`, `summary`, `priority`, etc.) are not touched. To **replace** a dict field entirely (overwrite, not merge), add it to `replace_fields`: `TaskUpdateRequest(**{"_id": id, "args": {...}, "replace_fields": ["args"]})`.

**`reset_pending=True`** sets `status → pending` AND resets `retries → 0`. Setting `"status": "pending"` in `TaskUpdateRequest` alone changes status but does **not** reset the retry counter. Always prefer `reset_pending=True` when re-queuing failed tasks.

### CLI

```bash
# Update a specific task's args (patches only args.lr; other args unchanged)
labtasker task update --id <task_id> -u 'args.lr=0.005'

# Update multiple fields
labtasker task update --id <task_id> -u 'args.lr=0.005' -u 'metadata.tags=["v2"]'

# Batch update: fix args and reset to pending (also resets retries)
# NOTE: add --limit 10000 to avoid silently missing tasks beyond the default 100
labtasker task ls -f 'status == "failed" and args.model == "resnet"' -q --limit 10000 \
    | xargs -I{} labtasker task update --id {} -u 'args.lr=0.005' --reset-pending --quiet

# Alternative: task update supports filter flags directly (no pipe needed)
labtasker task update -s failed -f 'args.model == "resnet"' -u 'args.lr=0.005' --reset-pending --quiet

# Cancel pending tasks (keep records, mark as cancelled)
labtasker task ls -s pending -f 'args.lr > 0.05' -q --limit 10000 \
    | xargs -I{} labtasker task update --id {} -u 'status=cancelled' --quiet

# Bump priority on urgent pending tasks
labtasker task ls -f '"urgent" in list(metadata.tags)' -s pending -q --limit 10000 \
    | xargs -I{} labtasker task update --id {} -u 'priority=100' --quiet
```

### Python

```python
import labtasker
from labtasker.api_models import TaskUpdateRequest

# Update a single task — only specified keys are merged/updated
labtasker.update_tasks([
    TaskUpdateRequest(**{"_id": task_id, "args": {"lr": 0.005}})
])

# Batch: fix lr and reset to pending (also resets retries=0)
response = labtasker.ls_tasks(status="failed")
updates = [
    TaskUpdateRequest(**{
        "_id": task.task_id,
        "args": {"lr": 0.005},   # merges into existing args; other keys preserved
    })
    for task in response.content
]
if updates:
    labtasker.update_tasks(updates, reset_pending=True)

# Cancel pending tasks matching a filter
response = labtasker.ls_tasks(
    status="pending",
    extra_filter='args.lr > 0.05',
)
updates = [
    TaskUpdateRequest(**{"_id": task.task_id, "status": "cancelled"})
    for task in response.content
]
if updates:
    labtasker.update_tasks(updates)

# Update metadata from inside a loop (merges new field without losing existing ones)
@labtasker.loop()
def main(lr: float = Required(), model: str = Required()):
    train(lr=lr, model=model)
    task = labtasker.task_info()
    labtasker.update_tasks([
        TaskUpdateRequest(**{"_id": task.task_id, "metadata": {"run_note": "done"}})
    ])  # merges "run_note" into existing metadata; other metadata keys preserved
```

---

## 6. Deleting Tasks

### CLI

```bash
# Delete by id (positional argument)
labtasker task delete <task_id>

# Batch delete via pipe: -q prints only ids, -y skips confirmation
# NOTE: add --limit 10000 to avoid silently missing tasks beyond the default 100
labtasker task ls -f 'created_at < date("10 minutes ago")' -q --limit 10000 | labtasker task delete -y

# Delete all failed tasks
labtasker task ls -s failed -q --limit 10000 | labtasker task delete -y

# Delete by task name pattern
labtasker task ls -f 'regex(task_name, "^debug-.*")' -q --limit 10000 | labtasker task delete -y
```

### Python

```python
import labtasker

# Delete a single task
labtasker.delete_task(task_id="<task_id>")

# Batch delete matching a filter
response = labtasker.ls_tasks(
    extra_filter='created_at < date("10 minutes ago")'
)
for task in response.content:
    labtasker.delete_task(task_id=task.task_id)
```

---

## Quick Reference

| Operation | CLI | Python |
|-----------|-----|--------|
| Submit | `labtasker task submit -- --k=v` | `labtasker.submit_task(args={...}, metadata={...})` |
| Submit with tags | `--metadata '{"tags": ["v1"]}'` | `metadata={"tags": ["v1"]}` |
| Run loop | `labtasker loop -- cmd '%(arg)'` | `@labtasker.loop()` + `Required()` |
| Run with filter | `--extra-filter 'filter'` | `@labtasker.loop(extra_filter='...')` |
| Parallel workers | `CUDA_VISIBLE_DEVICES=N labtasker loop ... &` | run multiple processes |
| List by status | `labtasker task ls -s failed` | `labtasker.ls_tasks(status="failed")` |
| List with filter | `labtasker task ls -f 'expr'` | `labtasker.ls_tasks(extra_filter='expr')` |
| Sort | `labtasker task ls -S created_at:desc` | `sorted(response.content, key=lambda t: ...)` |
| Write intermediate summary | — | `labtasker.report_task_status(task_id=..., status="running", summary={...})` |
| Finish task (final status) | — | `labtasker.finish(status="success"\|"failed", summary={...})` |
| Update | `labtasker task update --id X -u 'args.k=v'` | `labtasker.update_tasks([TaskUpdateRequest(...)])` |
| Cancel | `... -q \| xargs ... -u 'status=cancelled'` | `TaskUpdateRequest(**{"_id": id, "status": "cancelled"})` |
| Retry failed | `--reset-pending` | `update_tasks(updates, reset_pending=True)` |
| Delete | `labtasker task ls -s failed -q \| labtasker task delete -y` | `labtasker.delete_task(task_id=...)` |
| Current task | — | `labtasker.task_info()` |

---

## API Signatures

For queue and worker management, see the [full documentation](https://luocfprime.github.io/labtasker/latest/).

### CLI

```
labtasker task submit
    [ARGS...]                     # task args as CLI flags after --  e.g. -- --lr=0.01 --model=vit
    [--args JSON_STR]             # alternative: pass args as JSON dict string
    [--name NAME]                 # task name for identification
    [--metadata JSON_STR]         # e.g. '{"tags": ["v1"], "note": "baseline"}'
    [--max-retries INT]           # retry attempts on failure (default: 3)
    [--priority INT]              # higher = higher priority (default: 0)

labtasker loop
    [-- CMD ARGS]                 # command with %(key) placeholders; %(key) = top-level args only
    [--script-path FILE]          # path to script file with %(key) placeholders (for multi-line logic)
    [-f / --extra-filter EXPR]    # Python query string to filter which tasks to run
    # For nested dict args, use the Python @labtasker.loop() instead of CLI loop

labtasker task ls
    [--id TASK_ID]                # filter by task ID
    [--name TASK_NAME]            # filter by task name
    [-s / --status STATUS]        # pending|running|success|failed|cancelled
    [-f / --extra-filter EXPR]    # Python query string (supports args.field, metadata.field, summary.field)
    [-q / --quiet]                # print task IDs only (for piping)
    [--no-pager]                  # disable pager output
    [--limit INT]                 # max results (default: 100)
    [-S / --sort FIELD:asc|desc]  # e.g. -S created_at:desc  or  -S summary.acc:desc

labtasker task update
    [--id TASK_ID]                # filter by task ID
    [--name TASK_NAME]            # filter by task name
    [-s / --status STATUS]        # filter by status
    [-f / --extra-filter EXPR]    # filter by Python query
    [-u / --update 'field=value'] # patch a field (repeatable); dot-notation for nested: -u args.lr=0.01
    [-- field=value ...]          # positional update syntax (alternative to -u)
    [--reset-pending]             # set status=pending AND reset retries=0
    [-q / --quiet]                # skip confirmations (for scripts/pipes)

labtasker task delete
    [TASK_IDS...]                 # task IDs to delete (positional, or piped from stdin)
    [-y / --yes]                  # skip confirmation prompt
```

### Python

```python
labtasker.submit_task(
    task_name: str = None,
    args: Dict = None,            # task args — keys must match Required() params exactly
    metadata: Dict = None,        # e.g. {"tags": ["v1"], "note": "baseline"}
    max_retries: int = 3,
    priority: int = 0,            # higher = higher priority
) -> TaskSubmitResponse           # .task_id: str

@labtasker.loop(
    extra_filter: str = None,          # Python query string
    required_fields: List[str] = None, # explicit field list (auto-inferred from Required() if unset)
    pass_args_dict: bool = False,      # pass args as dict instead of keyword args
)
def main(
    param: Type = Required(),          # param name must match args key; type-cast automatically
    param: Annotated[T, Required(resolver=fn)] = ...,  # resolver receives args[param_name]
    param=Required(resolver=fn),       # shorthand form without Annotated
):
    ...
# Loop exits automatically when no more pending tasks match.

labtasker.task_info() -> Task     # available inside @labtasker.loop() only
    # .task_id  .task_name  .args  .metadata  .summary
    # .status   .retries    .priority  .max_retries
    # .created_at  .last_modified  .start_time  .worker_id

labtasker.finish(
    status: str,                      # "success"|"failed" only
    summary: Dict = None,             # merges into existing summary; None = no change
    skip_if_no_labtasker: bool = True,# silently skip if not running inside a loop
) -> None
# Terminal call from inside the loop — stops heartbeat, writes summary.json to local log dir,
# reports final status to server. Loop will NOT overwrite a status already set by finish().
# Use when you want to early-exit with a final status from deep inside your function.
# NOTE: only "success"/"failed" — use report_task_status for "cancelled"/"running".
# RETRY: finish(status="failed") behaves like an exception — server increments retries and
#   resets to pending if retries < max_retries (task WILL be retried). For permanent no-retry,
#   use report_task_status(status="cancelled").
# IDEMPOTENT: calling finish() twice is safe — second call is silently skipped.

labtasker.report_task_status(
    task_id: str,
    status: str,           # "running"|"success"|"failed"|"cancelled"
    summary: Dict = None,  # merges into existing summary; None = no change
) -> None
# Inside loop: status="running" writes metrics (loop auto-marks success/failed on return/exception,
#   UNLESS you already called this with "cancelled" — that terminal status is preserved).
# status="cancelled" inside loop: cancels task, will not be retried. Return immediately after.
# Outside loop (post-processing): call with the task's current status to update summary only,
#   e.g. report_task_status(task_id=t.task_id, status="success", summary={"rank": 1})

labtasker.ls_tasks(
    task_id: str = None,
    task_name: str = None,
    status: str = None,           # pending|running|success|failed|cancelled
    extra_filter: str = None,     # Python query string; dot-notation on any field
    limit: int = 100,             # WARNING: default 100 — set limit=10000 for batch ops to avoid silent truncation
) -> TaskLsResponse               # .content: List[Task]
# NOTE: no sort parameter — sort in Python: sorted(response.content, key=lambda t: ...)
# NOTE: summary is always a dict (never None) — t.summary.get("key") is always safe

# Task fields (on objects from ls_tasks and task_info):
#   task_id, task_name, status, args, metadata, summary
#   priority, max_retries, retries
#   created_at, last_modified, start_time, worker_id

labtasker.update_tasks(
    task_updates: List[TaskUpdateRequest],
    reset_pending: bool = False,  # sets status=pending AND resets retries=0
) -> TaskLsResponse
# Default: MERGE semantics — only keys you include in args/metadata/summary are changed;
# other existing keys inside those dicts are preserved.

TaskUpdateRequest(**{
    "_id": str,                  # task_id — use "_id" alias key (or keyword: task_id=...)
    "status": str,               # optional — "cancelled", "pending", etc.
    "args": Dict,                # optional — merged by default; add to replace_fields to overwrite entirely
    "metadata": Dict,            # optional — merged by default
    "summary": Dict,             # optional — merged by default; use to update summary from outside loop
    "priority": int,             # optional
    "max_retries": int,          # optional
    "replace_fields": List[str], # optional — fields to REPLACE entirely instead of merge
                                 # e.g. replace_fields=["args"] replaces whole args dict (not merge)
})

labtasker.delete_task(task_id: str) -> None

# To force-cancel a running task from OUTSIDE the loop (e.g., hung job detection):
labtasker.update_tasks([
    TaskUpdateRequest(**{"_id": task_id, "status": "cancelled"})
])
```

### Filter Query Syntax

```
# Comparison
field == value    field > value    field >= value
field < value     field <= value

# Membership (array field)
"val" in list(field)

# Logic
expr and expr    expr or expr

# Functions
date("3 hours ago")          # datetime: "X ago" means X before now
regex(field, "^pattern.*")   # regex match on string field

# Dot-notation works on any field:
args.lr > 0.01
metadata.group == "A"
summary.acc > 0.9
created_at >= date("7 days ago")

# NOT supported: !=  not  not in
# Workaround for status negation: use -s STATUS flag (CLI) or status= param (Python)
# Workaround for OR over statuses: use  status == "pending" or status == "failed"
```

> **Event system (SSE)**: For real-time task lifecycle events and workflow automation,
> see [Advanced Features](https://luocfprime.github.io/labtasker/latest/guide/advanced/).

---

## Workflow

1. Identify the serial loop in the user's script; choose CLI or Python based on their code style.
2. **Submit script**: iterate parameter grid, call `submit_task`/`labtasker task submit` with matching `args` and any `metadata` tags needed.
3. **Run script**: declare exactly the same keys as `Required()` params or `%(key)` placeholders — no more, no less.
4. For parallel runs: each worker independently executes the run script; all pull from the same queue.
5. Env vars must go outside the `labtasker loop` command (CLI).
6. To retry failures: use `update_tasks(updates, reset_pending=True)` (resets status AND retries); or `--reset-pending` in CLI.
7. To review results: `ls_tasks(status="success")` and inspect `.summary` and `.args` on each task.
