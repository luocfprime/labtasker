# Get started

Labtasker requires Python 3.11 or newer. Install the Server where the SQLite
database will live, and install the Client wherever Tasks are submitted or run.

```bash
python -m pip install labtasker-server
python -m pip install labtasker
```

## 1. Start the Server

```bash
labtasker-server serve
```

This listens on `127.0.0.1:8000`, stores data in `.labtasker/server.db`, and
creates the `default` Queue in a fresh database. Labtasker also creates
`.labtasker/.gitignore`, so the local database, configuration, and Worker run
journals are ignored by Git by default; an existing ignore file is left intact.

## 2. Configure the Client

For this local setup the defaults already work. A project configuration makes
the target explicit:

```toml
# .labtasker/config.toml
url = "http://127.0.0.1:8000"
queue = "default"
```

Check what the Client will use:

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
