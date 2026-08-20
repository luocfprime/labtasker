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
creates the `default` Queue in a fresh database.

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

## 3. Submit a Task

CLI values are strict JSON, so numbers and Booleans retain their types:

```bash
labtasker task submit \
  --name first-run \
  --args '{"seed":7,"lr":0.001}' \
  --route train
```

The command prints the created Task as formatted JSON.

## 4. Run a Worker

Create a simple program:

```python
# train.py
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--lr", type=float, required=True)
args = parser.parse_args()
print(f"training seed={args.seed} lr={args.lr}")
```

Then run it once for each compatible Task:

```bash
labtasker loop --route train -- \
  python train.py --seed '%{seed}' --lr '%{lr}'
```

The `--` separator is required. Labtasker builds argv directly and never invokes
a shell. The Worker waits up to five minutes for more eligible Tasks before it
exits normally.

## 5. Inspect the result

```bash
labtasker task list --status succeeded
labtasker task get t_ABCDEFGHIJKL
```

Replace the example ID with the ID printed by submission. A successful command
returns result `{}` unless the command calls `labtasker.finish(...)`; see
[Command Workers](workers/command.md).
