# Labtasker v2

Labtasker is a small task queue for running parallel machine-learning experiments.
It keeps scheduling explicit: a Task names one or more compatible routes, and a
Worker claims through exactly one route. The Server stores no Worker registry and
does not allocate GPUs or other resources.

V2 consists of two independent Python distributions:

- `labtasker`: synchronous Python Client, Worker API, and `labtasker` CLI.
- `labtasker-server`: FastAPI/SQLite Server and `labtasker-server` CLI.

Python 3.11 or newer is required. Linux is the fully release-gated Worker
platform; ordinary Client, Server, and pipe-mode Worker use is portable on a
best-effort basis.

## Install

Install the Server on the machine that owns the SQLite database:

```bash
python -m pip install labtasker-server
```

Install the Client wherever Tasks are submitted or executed:

```bash
python -m pip install labtasker
```

For a checkout of this repository, `uv sync --all-packages --group dev` installs
both workspace packages and the development tools.

## End-to-end quick start

Start one Server. The default bind is loopback-only, the database is
`.labtasker/server.db`, and a fresh database contains Queue `default`:

```bash
labtasker-server serve
```

A non-loopback bind requires a server-wide token supplied through the environment:

```bash
LABTASKER_SERVER_TOKEN=secret \
  labtasker-server serve --host 0.0.0.0 --database /data/labtasker.db
```

Configure a Client with environment variables:

```bash
export LABTASKER_URL=http://127.0.0.1:8000
export LABTASKER_QUEUE=default
# Only when the Server has authentication enabled:
export LABTASKER_TOKEN=secret
```

The equivalent project-local `.labtasker/config.toml` is:

```toml
url = "http://127.0.0.1:8000"
queue = "default"
# token = "secret"
```

Inspect the effective non-secret configuration:

```bash
labtasker config show
```

Submit two Tasks. JSON values retain their JSON types; the CLI does not guess
types from text:

```bash
labtasker task submit \
  --name seed-1 \
  --args '{"seed":1,"lr":0.001}' \
  --route train

labtasker task submit \
  --name seed-2 \
  --args '{"seed":2,"lr":0.001}' \
  --route train
```

Run as many command Workers as the externally allocated hardware permits. The
`--` separator is required, and each `%{path}` is resolved into one argv element
without invoking a shell:

```bash
labtasker loop --route train -- \
  python train.py --seed '%{seed}' --lr '%{lr}'
```

Each Worker executes one Task at a time and exits normally after five minutes
without eligible work. Use `--idle-timeout 0` when an immediate empty-queue exit
is desired.

Inspect the backlog and results with one-page, formatted JSON output:

```bash
labtasker task count --status pending
labtasker task list --status succeeded --limit 100
labtasker task get t_ABCDEFGHIJKL
```

## Python Worker

`TaskArg` marks only the parameters supplied from each Task. Other parameters are
ordinary fixed values loaded once for the Worker process:

```python
import labtasker


@labtasker.loop(route="train", idle_timeout=300)
def train(
    model,
    seed: int = labtasker.TaskArg(),
    lr: float = labtasker.TaskArg(default=0.001),
) -> None:
    accuracy = model.fit(seed=seed, learning_rate=lr)
    labtasker.finish({"accuracy": accuracy})


train(load_model_once())
```

Binding is strict: an `int` annotation rejects a float, string, or Boolean.
Missing required values and resolver failures become normal Task failures after
claim. Extra Task args are ignored by named binding and remain available through
`labtasker.task_info().args`.

A normal return succeeds with result `{}`. `finish(result)` immediately and
reliably stores an explicit result, while code after it may continue local cleanup.
The Worker does not claim another Task until the function returns.

## Routing and rolling changes

Routes are exact, case-sensitive compatibility labels. Starting a new Worker does
not implicitly redirect old Tasks:

```text
old Worker route: train-v1
new Worker route: train-v2
```

Submit a new-only Task with `routes=["train-v2"]`, or explicitly let a Task run
on either implementation with `routes=["train-v1", "train-v2"]`. Pending Tasks
can be migrated in one explicit batch update:

```bash
labtasker task update \
  --filter 'status == "pending" and "train-v1" in routes' \
  --changes '{"routes":["train-v1","train-v2"]}'
```

Worker claims never inspect Task argument shape. Once Queue, pending state, and
route match, argument handling is the Worker's responsibility.

## Query language

Task list, count, and batch update share one small expression language. Examples:

```text
priority >= 10 and metadata.group == "ablation"
"baseline" in metadata.tags
status == "failed" and last_error.type == "ValueError"
missing(result.accuracy) or result.accuracy < 0.9
```

All ordinary comparisons require the referenced path to exist. Use
`missing(path) or ...` explicitly to include absent values. Query filters never
participate in Worker routing.

## Failure and recovery

- An ordinary exception consumes the current attempt and the Worker continues.
- `TransientError` unclaims without charging that incident.
- `TaskError` reports a charged failure.
- `FatalWorkerError` reports the same Task failure, then stops the Worker.
- Every run is fenced by a private `run_id` and recovered after heartbeat loss.
- `cancel`, `requeue`, and explicit Task updates are separate operations.

Useful recovery commands are non-interactive:

```bash
labtasker task cancel t_ABCDEFGHIJKL
labtasker task requeue t_ABCDEFGHIJKL
labtasker task update t_ABCDEFGHIJKL --changes '{"priority":20}'
labtasker task delete t_ABCDEFGHIJKL
```

Each claimed run also receives a semantic local journal below
`.labtasker/runs/{queue}/...`. It contains the claimed Task snapshot, run state,
stdout/stderr log, and any locally prepared terminal payload. The Server remains
authoritative; local files never bypass run fencing.

## Distributed launchers

Keep Labtasker outside a single-node launcher so one Task owns one launcher and
one heartbeat source:

```bash
labtasker loop --route train -- \
  torchrun --nproc-per-node=8 train.py --lr '%{lr}'

labtasker loop --route train -- \
  accelerate launch --num_processes 8 train.py --lr '%{lr}'
```

Only one rank should call `finish()`, selected through the framework's main-rank
API. Starting a Labtasker loop independently inside every distributed rank is
rejected before claim.

## HTTP and complete contract

The application API is rooted at `/api/v2`. Deployment discovery is available at
unauthenticated `/health` and `/openapi.json`; interactive docs are intentionally
not shipped. Every API error uses a stable `error.code`, readable message, and
structured details.

[`LABTASKER_V2_SPEC.md`](LABTASKER_V2_SPEC.md) is the authoritative standalone
contract, including exact lifecycle, concurrency, query, journal, and API
semantics.

## Development

```bash
uv sync --all-packages --group dev --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/labtasker-client/src packages/labtasker-server/src
uv run pytest
uv build --all-packages
```

The full user guide is built with Zensical:

```bash
uv run zensical serve
uv run zensical build --clean
```

Start with [`docs/getting-started.md`](docs/getting-started.md), or use the local
preview for navigation and search.

The separately marked launcher suite requires PyTorch and Accelerate:

```bash
uv run pytest -m distributed_integration
```

## License

Apache-2.0.
