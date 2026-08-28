# Run your first experiment

This tutorial submits three evaluation cases, processes them from one Queue,
and reads their recorded results. The evaluator has no ML dependencies, so you
can complete the workflow before adapting it to your own model or benchmark.

## Requirements

You need Python 3.11 or newer and a POSIX system such as Linux or macOS. The
automatic local Server and command Worker used in this tutorial are not
supported on Windows. Windows Clients must connect to an HTTP Server and use a
Python Worker. See [Configuration](reference/configuration.md) for details.

To use checked-in source files instead, follow the [tested demo](demo.md). Its
submission and Worker files run in the end-to-end test suite.

## 1. Install Labtasker

Install the complete package in a virtual environment:

=== "pip"

    ```bash
    python -m pip install labtasker
    ```

=== "uv"

    ```bash
    uv add labtasker
    ```

    Prefix later commands with `uv run`, for example
    `uv run labtasker task list`. The commands below omit this prefix for
    readability.

## 2. Create an experiment directory

```bash
mkdir my-evaluation
cd my-evaluation
```

Labtasker uses the current directory to select its local Server and Task
database. Run the remaining commands from `my-evaluation` so they use the same
data.

## 3. Submit three evaluation cases

```bash
labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"red panda","reference":"red panda"}' \
  --route text-eval

labtasker task submit \
  --name sample-2 \
  --args '{"prediction":"snow leopard","reference":"leopard"}' \
  --route text-eval

labtasker task submit \
  --name sample-3 \
  --args '{"prediction":"sea otter","reference":"sea otter"}' \
  --route text-eval
```

Each command prints the created Task as JSON. Confirm that:

- `status` is `"pending"`;
- `routes` contains `"text-eval"`;
- `args` contains that case's prediction and reference;
- `id` contains the generated Task ID.

CLI values use strict JSON, so numbers, Booleans, arrays, objects, and `null`
keep their JSON types.

On POSIX systems, the first Task operation starts a local Server when needed.
All three Tasks enter Queue `default`, so the tutorial needs no Server command
or configuration file.

## 4. Create the evaluator

Create `evaluate.py`:

```python
import argparse

import labtasker

parser = argparse.ArgumentParser()
parser.add_argument("--prediction", required=True)
parser.add_argument("--reference", required=True)
args = parser.parse_args()

score = float(args.prediction.strip() == args.reference.strip())
labtasker.finish({"score": score}, skip_if_no_labtasker=True)
```

The script reads one evaluation case at a time and reports a structured result
with `labtasker.finish()`. The `skip_if_no_labtasker=True` option lets you run
the same script directly while developing it.

## 5. Run a command Worker

Start a Worker whose route matches the Tasks:

```bash
labtasker loop --route text-eval --idle-timeout 0 -- \
  python evaluate.py \
    --prediction '%{prediction}' \
    --reference '%{reference}'
```

The `--` separator is required. Everything after it is the child command.
Labtasker replaces `%{prediction}` and `%{reference}` with values from the
claimed Task, then starts the command without invoking a shell.

The Worker processes all three Tasks, one at a time. If you start more Workers
with the same route, they claim from the same Queue instead of requiring a fixed
split of the cases.

`--idle-timeout 0` makes this tutorial Worker exit when it first finds no
matching Task. Long-lived Workers normally use the five-minute default so they
can wait for newly submitted work.

## 6. Inspect the results

```bash
labtasker task list --status succeeded
```

The response contains all three Tasks. Their recorded results are:

| Task | Result |
| --- | --- |
| `sample-1` | `{"score": 1.0}` |
| `sample-2` | `{"score": 0.0}` |
| `sample-3` | `{"score": 1.0}` |

Each Task record also includes its ID, arguments, routes, attempts, and
timestamps. Copy an `id` to retrieve that Task directly:

```bash
labtasker task get TASK_ID
```

You have submitted several cases, processed them from one Queue, and inspected
the recorded results.

## What Labtasker created

The local Server runs as a detached process. It keeps running when you close the
terminal or lose the SSH connection. It stores local state under `.labtasker/`:

| Path | Contents |
| --- | --- |
| `.labtasker/server.db` | SQLite Task and Queue data |
| `.labtasker/server.log` | Server process logs |
| `.labtasker/.gitignore` | Keeps local Labtasker state out of version control |

See which Server and Queue the Client will use, or manage the current
directory's Server directly:

```bash
labtasker config show
labtasker-server status
labtasker-server logs
labtasker-server stop
```

## Next steps

- Read [How Labtasker works](concepts.md) before designing routes, Queues, or
  recovery behavior.
- Use a [Python Worker](workers/python.md) to keep a model loaded across Tasks.
- Read [Command Workers](workers/command.md) for argv template and subprocess
  behavior.
- Follow [Manage Tasks](guides/tasks.md) to submit batches, change priorities,
  cancel work, and retry failures.
- Use [Configuration](reference/configuration.md) to connect several machines
  to one HTTP Server.
