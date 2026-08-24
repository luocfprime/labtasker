# Labtasker

<p align="center">
  <img src="docs/assets/logo.png" alt="Labtasker" width="520">
</p>

**Run many independent ML experiments in parallel without writing and debugging
your own task distribution, retry, and result-collection scripts.**

If you only have a few jobs and can safely rerun everything, a simple script may
be all you need. Now suppose you have 100 evaluations and 8 GPUs. How do you keep
every GPU busy when some evaluations take much longer than others? What happens
when one fails halfway, the run is interrupted, or a new high-priority case
arrives?

Most projects gradually add GPU-assignment logic, status files, retries, locks,
and result parsing to answer those questions. Even if an agent writes the code,
you still have to explain those requirements and debug another project-specific
task system.

Compared with one-off task scripts, Labtasker provides a cleaner, better-tested,
and more reliable solution with less project-specific code. Its standardized,
explicit workflow is easy to automate and agent-friendly by design. With the
bundled Agent Skill, task dispatch can be as simple as telling your agent: “Run
these jobs in parallel across 8 GPUs with Labtasker.”

| Without Labtasker :cry: | With Labtasker :smiley: |
| --- | --- |
| **Assign jobs to GPUs before starting.** This works while runtimes are predictable; otherwise some GPUs finish early and sit idle. | **Jobs are picked up as GPUs become free.** Work stays balanced even when runtimes vary. |
| **Use logs and output files to remember progress.** This works while every run finishes cleanly; after an interruption, it becomes unclear what is safe to rerun. | **Labtasker remembers what finished.** Restart and continue the unfinished jobs without repeating completed work. |
| **Ask an agent to add retries, locks, and failure rules.** This one-off code is rarely tested thoroughly, so subtle bugs may appear only after a large experiment is underway. | **Use built-in retry and recovery behavior.** The same tested implementation is reused across experiments, and an old process cannot overwrite a newer result. |
| **Parse logs and directories to collect results.** Every project develops another output format and collection script. | **Report every job in a consistent format.** Agents and automation can inspect results directly, while large files remain in project-owned storage. |
| **Rewrite or restart scripts when the plan changes.** Adding urgent jobs or cancelling unnecessary ones can disturb unrelated work. | **Change the plan while the experiment is running.** Add, cancel, or prioritize jobs without stopping unrelated work. |
| **Hide program compatibility in arguments and launcher conditions.** After an implementation changes, it is hard to tell which version should run which job. | **Label compatible implementations explicitly.** Old and new versions can run side by side without silently redirecting existing jobs. |
| **Reload an expensive model for every case, or build another custom loop.** The first option wastes startup time; the second adds more coordination code. | **Keep expensive state loaded across many jobs.** Each process can reuse its model or evaluator while Labtasker supplies new inputs. |
| **Explain scheduling and recovery behavior to an agent for every project.** The agent ends up inventing and debugging another task system. | **Tell the agent to use Labtasker.** The bundled skill supplies the same tested workflow for submission, execution, inspection, and recovery. |

Labtasker schedules work on resources that you already control. It does not
allocate GPUs, launch a cluster, build a workflow DAG, or store large artifacts.

## Contents

- Understand Labtasker: [where it fits](#where-labtasker-fits),
  [why v2](#why-v2), and the
  [Embodied AI: RoboTwin evaluation case study](docs/case-studies/starvla-robotwin.md)
- Start using it: [install](#install),
  [LLM-readable documentation](#llm-readable-documentation),
  [end-to-end quick start](#end-to-end-quick-start), and
  [Python Worker](#python-worker)
- Operate Tasks: [routing and rolling changes](#routing-and-rolling-changes),
  [query language](#query-language), and
  [failure and recovery](#failure-and-recovery)
- Go further: [optional distributed launchers](#optional-distributed-launchers),
  [HTTP and complete contract](#http-and-complete-contract),
  [development](#development), and [license](#license)

## Where Labtasker fits

### AIGC experiments and ablations

Image, video, and generative-model experiments often evaluate many prompts,
seeds, checkpoints, or ablation settings before selecting the useful outputs.
Submit each case as a Task, start one Worker on each available GPU, and let all
Workers consume the same backlog. New cases can be added or reprioritized
without repartitioning a running experiment.

### Embodied-AI evaluation

An embodied benchmark may contain many suites and subtasks whose runtimes differ
substantially. Dividing them evenly by count does not divide the runtime evenly:
some GPUs finish early and sit idle while another is stuck on a slow suite.
Dynamic claiming keeps free Workers busy, while Task records keep progress,
failures, and structured result references together instead of scattering that
state across launcher scripts and output directories.

The [Embodied AI: RoboTwin evaluation (StarVLA codebase)](docs/case-studies/starvla-robotwin.md)
case study shows this pattern in a real project. Evaluating one VLA checkpoint
across 50 robot-manipulation tasks requires dynamic GPU scheduling, process and
port management, failure tracking, cleanup, and result collection.

The same model applies to evaluation, benchmarking, data processing, and other
collections of independent parameterized work. See
[Why Labtasker?](docs/why-labtasker.md) for the full motivation and product
boundary.

## Why v2

V2 keeps Labtasker's original purpose and makes the system smaller, more
explicit, and more reliable:

- **One obvious way:** overlapping shortcuts and implicit interactions were
  removed in favor of a small set of complete, composable operations.
- **Explicit routing:** Tasks name compatible routes and each Worker claims
  through one route; scheduling never guesses compatibility from Task arguments.
- **Explicit lifecycle:** claim, heartbeat, completion, failure, cancellation,
  requeue, and retry have defined behavior, with `run_id` fencing against stale
  Workers.
- **Agent-first operation:** the Agent Skill, deterministic CLI output, and
  explicit state-changing commands let coding agents operate Labtasker without
  guessing hidden state or answering interactive prompts.
- **Python-native setup:** Labtasker no longer requires MongoDB or uses Mongomock
  as a substitute for an embedded database. The default local Server and SQLite
  database are managed automatically.
- **Works out of the box:** install the package and use it from the experiment
  directory. Server deployment and configuration are only needed when sharing
  work across machines.

The [v1 to v2 design notes](docs/why-labtasker.md#from-v1-to-v2) explain these
changes as product decisions rather than a list of renamed options.

V2 has two independent runtime distributions and one convenience metapackage:

- `labtasker-client`: synchronous Python Client, Worker API, and `labtasker` CLI.
- `labtasker-server`: FastAPI/SQLite Server and `labtasker-server` CLI.
- `labtasker`: code-free full installation that installs matching Client and
  Server distributions.

Python 3.11 or newer is required. Linux is the fully release-gated platform.
Client, Server, and Python Worker use is portable on macOS and Windows on a
best-effort basis; Command Workers are additionally best effort on macOS but are
rejected on Windows because the current implementation cannot guarantee
process-tree cancellation there. Best effort means a documented path is not
release-gated on that platform. It does not mean Labtasker attempts a feature
explicitly documented as unsupported: such a feature is rejected before
Labtasker claims a Task or starts local work.

## Install

### With pip

For ordinary single-project use, install the complete package:

```bash
python -m pip install labtasker
```

Install `labtasker-client` directly for a slim environment that only connects to
an explicitly managed HTTP Server. Install `labtasker-server` directly for a
Server-only deployment.

### With uv

Add the complete installation to the experiment project:

```bash
uv add labtasker
```

Run Client commands through the project environment, for example
`uv run labtasker config show`. For split deployment, add `labtasker-client` in
Client environments and install `labtasker-server` in the Server environment.

For a checkout of this repository, `uv sync --all-packages --group dev` installs
all workspace distributions and the development tools.

### Install the agent skill

Labtasker includes an agent skill for turning inference, evaluation, and other
independent experiment loops into Tasks and Workers.

Claude Code users can install it from this repository's marketplace:

```text
/plugin marketplace add luocfprime/labtasker@v2
/plugin install labtasker-skill@labtasker
```

Codex, Claude Code, OpenCode, Cursor, and other Agent Skills-compatible tools can
install the same canonical skill with:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/v2/skills/labtasker
```

See the [agent skill guide](docs/guides/agent-skill.md) for explicit agent and
scope selection.

### LLM-readable documentation

The documentation site publishes a standard [`llms.txt`](docs/llms.txt) entry
point. It gives agents a concise map of Labtasker and links directly to the raw
Markdown for the getting-started guide, workflows, API references, and
specification, so they can load only the material needed for a task.

## End-to-end quick start

Change to the project directory. No Server command or port configuration is
needed for the default local workflow:

```bash
cd my-experiment
labtasker queue list
```

The first real Client operation visibly starts a detached local daemon and
connects through an owner-only Unix socket. Its database and log live at
`.labtasker/server.db` and `.labtasker/server.log`; a fresh database contains
Queue `default`. The daemon stays alive across terminal or SSH disconnection.
`labtasker config show` is read-only and shows the selected paths without
starting it.

Manage that CWD-bound daemon explicitly when needed:

```bash
labtasker-server status
labtasker-server logs
labtasker-server stop
```

For a separately operated HTTP Server, start the foreground process explicitly:

```bash
labtasker-server serve
export LABTASKER_URL=http://127.0.0.1:8000
```

A non-loopback bind requires a server-wide token supplied through the environment:

```bash
LABTASKER_SERVER_TOKEN=secret \
  labtasker-server serve --host 0.0.0.0 --database /data/labtasker.db
```

An explicit URL disables local daemon management. Configure a remote Client with:

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

Submit two evaluation Tasks. JSON values retain their JSON types; the CLI does
not guess types from text:

```bash
labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"cat","reference":"cat"}' \
  --route exact-match

labtasker task submit \
  --name sample-2 \
  --args '{"prediction":"dog","reference":"cat"}' \
  --route exact-match
```

Create a minimal `evaluate.py`:

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

Run as many evaluation Workers as the externally allocated hardware permits. The
`--` separator is required, and each `%{path}` is resolved into one argv element
without invoking a shell:

```bash
labtasker loop --route exact-match -- \
  python evaluate.py --prediction '%{prediction}' --reference '%{reference}'
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

`TaskArg` marks only the parameters supplied from each inference Task. Other
parameters—such as a model or pipeline—are ordinary fixed values loaded once for
the Worker process:

```python
import labtasker


@labtasker.loop(route="sdxl", idle_timeout=300)
def infer(
    pipeline,
    prompt: str = labtasker.TaskArg(),
    seed: int = labtasker.TaskArg(),
) -> None:
    output = pipeline(prompt, seed=seed)
    path = labtasker.task_info().run_dir / "image.png"
    output.save(path)
    labtasker.finish({"image": str(path)})


infer(load_pipeline_once())
```

Binding is strict: an `int` annotation rejects a float, string, or Boolean.
Missing required values and resolver failures become normal Task failures after
claim. Extra Task args are ignored by named binding and remain available through
`labtasker.task_info().args`.

A normal return succeeds with result `{}`. `finish(result)` immediately and
reliably stores an explicit result, while code after it may continue local cleanup.
The Worker does not claim another Task until the function returns.

See [Inference and evaluation](docs/inference-evaluation.md) for complete
patterns covering a warm SDXL pipeline, existing evaluators, implementation
rollouts, and artifact paths.

## Routing and rolling changes

Routes are exact, case-sensitive compatibility labels. Starting a new Worker does
not implicitly redirect old Tasks:

```text
old Worker route: sdxl-diffusers-v1
new Worker route: sdxl-diffusers-v2
```

Submit a new-only Task with `routes=["sdxl-diffusers-v2"]`, or explicitly let a
Task run on either implementation. Pending Tasks can be migrated in one explicit
batch update:

```bash
labtasker task update \
  --filter 'status == "pending" and "sdxl-diffusers-v1" in routes' \
  --changes '{"routes":["sdxl-diffusers-v1","sdxl-diffusers-v2"]}'
```

Worker claims never inspect Task argument shape. Once Queue, pending state, and
route match, argument handling is the Worker's responsibility.

## Query language

Task list, count, and batch update share one small expression language. Examples:

```text
priority >= 10 and metadata.group == "ablation"
"baseline" in metadata.tags
status == "failed" and last_error.type == "ValueError"
missing(result.score) or result.score < 0.9
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

## Optional distributed launchers

For the less common case where one Task launches a single-node distributed
training job, keep Labtasker outside the launcher so the Task owns one launcher
and one heartbeat source:

```bash
labtasker loop --route evaluate-distributed -- \
  torchrun --nproc-per-node=8 evaluate_distributed.py --benchmark '%{benchmark}'

labtasker loop --route evaluate-distributed -- \
  accelerate launch --num_processes 8 evaluate_distributed.py --benchmark '%{benchmark}'
```

Only one rank should call `finish()`, selected through the framework's main-rank
API. Starting a Labtasker loop independently inside every distributed rank is
rejected before claim.

## HTTP and complete contract

The application API is rooted at `/api/v2`. Deployment discovery is available at
unauthenticated `/health` and `/openapi.json`; interactive docs are intentionally
not shipped. Every API error uses a stable `error.code`, readable message, and
structured details.

The [full specification](docs/reference/specification.md) is the authoritative
standalone contract, including exact lifecycle, concurrency, query, journal, and
API semantics.

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
