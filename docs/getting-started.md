# Get started

Labtasker requires Python 3.11 or newer. For the default POSIX local workflow,
there is no database service to install, Server command to run, or configuration
file to write. On Windows, configure an explicitly operated HTTP Server; the
automatic local Server and the command Worker used below are unsupported.

## Installation

=== "with pip"

    ```bash
    python -m pip install labtasker
    ```

=== "with uv"

    Add Labtasker to the experiment project so its Python API is importable by
    Worker code and the matching local Server is available:

    ```bash
    uv add labtasker
    ```

    With the uv project installation, prefix Client commands with `uv run`, such
    as `uv run labtasker config show` or `uv run labtasker loop ...`. The
    launched Python child inherits that project environment. The examples below
    omit the prefix so their Labtasker syntax stays easy to compare.

    For split deployment, install `labtasker-client` directly in Client-only
    environments and `labtasker-server` in the Server environment.

## 1. Submit an evaluation Task

CLI values are strict JSON, so numbers and Booleans retain their types:

```bash
cd my-experiment

labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"red panda","reference":"red panda"}' \
  --route text-eval
```

On POSIX systems, the command starts the project-local Server when needed and
prints the created Task as formatted JSON. A fresh project uses Queue `default`
automatically.

`text-eval` is the name of the evaluator in this example. Use a route name that
identifies the workload or implementation, such as `libero`, `robotwin`, or
`text-eval`. The Task and the Worker that may run it use the same name.

## 2. Run a Worker

Create a small evaluator. A real evaluator might run a benchmark, judge model
output, or compute an embedding metric; this deterministic example needs no ML
dependency:

```python
# evaluate.py
import argparse

import labtasker

parser = argparse.ArgumentParser()
parser.add_argument("--prediction", required=True)
parser.add_argument("--reference", required=True)
args = parser.parse_args()
score = float(args.prediction.strip() == args.reference.strip())
labtasker.finish({"score": score}, skip_if_no_labtasker=True)
```

Then run it once for each compatible Task:

```bash
labtasker loop --route text-eval -- \
  python evaluate.py \
    --prediction '%{prediction}' \
    --reference '%{reference}'
```

The `--` separator is required. Labtasker builds argv directly and never invokes
a shell. The Worker waits up to five minutes for more eligible Tasks before it
exits normally.

## 3. Inspect the result

```bash
labtasker task list --status succeeded
labtasker task get t_ABCDEFGHIJKL
```

Replace the example ID with the ID printed by submission. This Task succeeds with
result `{"score": 1.0}`. A command that does not call `finish(...)` still
succeeds with `{}` when it exits zero; see [Command Workers](workers/command.md).

## What Labtasker started

The first Task or Queue operation starts a detached local daemon bound to the
current project directory. It keeps durable state in `.labtasker/server.db` and
logs in `.labtasker/server.log`; `.labtasker/.gitignore` excludes this local state
without overwriting an existing ignore file. The daemon survives terminal and
SSH disconnection.

Inspect the selected endpoint without starting anything, or manage the daemon
explicitly:

```bash
labtasker config show
labtasker-server status
labtasker-server logs
labtasker-server stop
```

Configuration is only needed to select another Queue or connect to an explicitly
managed HTTP Server. See [Configuration](reference/configuration.md) for those
cases.
