# Get started

Labtasker requires Python 3.11 or newer. The ordinary installation includes both
the Client and local Server while keeping their runtime packages independent.

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

## 1. Select the local project

```bash
cd my-experiment
labtasker config show
```

The default endpoint is bound exactly to the canonical current directory. The
diagnostic above shows its database and Unix socket paths but does not create
files, connect, or start a process. The first Task or Queue operation visibly
starts a detached local daemon. It stores durable state in
`.labtasker/server.db`, logs in `.labtasker/server.log`, and creates Queue
`default` in a fresh database. `.labtasker/.gitignore` excludes local state while
leaving an existing ignore file unchanged.

## 2. Optionally select a Queue

No configuration is required. To change the default Queue without changing the
local endpoint:

```toml
queue = "default"
```

Check the effective non-secret endpoint at any time:

```bash
labtasker config show
```

## 3. Submit an evaluation Task

CLI values are strict JSON, so numbers and Booleans retain their types:

```bash
labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"red panda","reference":"red panda"}' \
  --route exact-match
```

The command prints the created Task as formatted JSON.

## 4. Run a Worker

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
labtasker loop --route exact-match -- \
  python evaluate.py \
    --prediction '%{prediction}' \
    --reference '%{reference}'
```

The `--` separator is required. Labtasker builds argv directly and never invokes
a shell. The Worker waits up to five minutes for more eligible Tasks before it
exits normally.

## 5. Inspect the result

```bash
labtasker task list --status succeeded
labtasker task get t_ABCDEFGHIJKL
```

Replace the example ID with the ID printed by submission. This Task succeeds with
result `{"score": 1.0}`. A command that does not call `finish(...)` still
succeeds with `{}` when it exits zero; see [Command Workers](workers/command.md).
