# Labtasker

<p align="center">
  <img src="docs/assets/logo.png" alt="Labtasker" width="520">
</p>

**Run many independent ML jobs in parallel without writing your own scripts to
split the work, retry failures, and collect results.**

A simple loop is fine when you have a handful of short jobs and do not mind
rerunning all of them. Now imagine running 100 evaluations on 8 GPUs. Some finish
in minutes; others take hours. If you divide the list before starting, some GPUs
will sit idle while the slowest jobs are still running. If the script crashes,
you must work out what finished and what is safe to run again.

Labtasker keeps one list of jobs and hands them out one at a time. Start one
evaluation process on each GPU; whenever it finishes a job, it gets another.
Labtasker remembers what is waiting, running, finished, or failed, so an
interrupted experiment can continue instead of starting over.

| Without Labtasker :cry: | With Labtasker :smiley: |
| --- | --- |
| Divide jobs among GPUs before starting; a slow group leaves other GPUs idle. | When one GPU finishes a job, its process picks up the next one. |
| Infer progress from logs and output directories, then decide what is safe to rerun. | Finished jobs stay recorded; waiting and failed jobs remain visible. |
| Add project-specific locks, retries, and failure rules that are rarely tested against races. | Reuse tested recovery rules; a late result from an old process cannot replace a newer one. |
| Parse scattered outputs and rewrite the launcher when priorities change. | Inspect results in one format, then add, cancel, or prioritize jobs without restarting the rest. |
| Ask an agent to invent and debug that coordination code for every codebase. | Give the agent the Labtasker skill and the same predictable commands in every project. |

Labtasker deliberately stops at coordinating the jobs. You still choose the
machines and GPUs, start the processes that use them, and decide where large
outputs are saved. It does not allocate hardware or run pipelines in which one
job depends on another.

## Contents

- [Where Labtasker fits](#where-labtasker-fits)
- [Why v2](#why-v2)
- [Install and run the first Task](#install-and-run-the-first-task)
- [Use Labtasker with an agent](#use-labtasker-with-an-agent)
- [Documentation](#documentation)
- [Development](#development)

## Where Labtasker fits

Labtasker calls each job a **Task** and each process that runs jobs a **Worker**.

### AIGC experiments and ablations

Generation and evaluation often span many prompts, seeds, checkpoints, and
ablation settings. Submit each case as a Task and start one Worker on each
available GPU. Faster Workers process more cases; new comparisons can be added
or prioritized without repartitioning the run. A Python Worker can also keep a
model loaded while Labtasker supplies new inputs.

### Embodied-AI evaluation

Benchmark suites and subtasks can differ greatly in runtime. Static splitting
leaves some GPUs idle behind the slowest shard, and progress becomes scattered
across launcher logs and result directories. Labtasker distributes cases as
resources become free and keeps their state together.

The [RoboTwin evaluation case study](docs/case-studies/starvla-robotwin.md)
examines this problem in the StarVLA codebase: evaluating one checkpoint across
50 manipulation tasks requires enough scheduling and process-management logic
to produce a 548-line Bash launcher.

The same model applies to independent inference, evaluation, benchmarking, and
data-processing work. [Why Labtasker?](docs/why-labtasker.md) gives the complete
comparison and product boundary.

## Why v2

V2 keeps Labtasker's original purpose while reducing the number of concepts and
making behavior explicit:

- **One obvious way:** a small set of complete operations replaces overlapping
  shortcuts and implicit interactions.
- **Explicit routing:** Tasks name compatible routes; Workers never infer
  eligibility from Task arguments.
- **Defined recovery:** lifecycle actions, attempts, leases, and `run_id`
  fencing prevent an old process from overwriting a newer result.
- **Agent-first interfaces:** commands are deterministic and non-interactive,
  with explicit state-changing actions and stable structured output.
- **Python-native local use:** an automatically managed SQLite Server replaces
  the MongoDB or Mongomock setup required by v1.

See [From v1 to v2](docs/why-labtasker.md#from-v1-to-v2) for the design rationale.

## Install and run the first Task

Labtasker requires Python 3.11 or newer. Install the complete local package:

```bash
python -m pip install labtasker
# or, inside a uv project:
uv add labtasker
```

Submit one evaluation case. On POSIX systems, the first Task operation starts
the project-local Server automatically; no database service, port, or
configuration file is needed.

```bash
cd my-experiment

labtasker task submit \
  --name sample-1 \
  --args '{"prediction":"red panda","reference":"red panda"}' \
  --route text-eval
```

`text-eval` names the evaluation program for this example. The submitted job and
the process that runs it use the same name.

Create the evaluator that runs one case:

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

Start a Worker. Start more copies on resources you already control to run Tasks
in parallel.

```bash
labtasker loop --route text-eval -- \
  python evaluate.py \
    --prediction '%{prediction}' \
    --reference '%{reference}'
```

Inspect the result:

```bash
labtasker task list --status succeeded
```

The [getting-started guide](docs/getting-started.md) explains the local Server
and configuration after completing this same workflow. Use a
[Python Worker](docs/workers/python.md) when a model or evaluator should remain
loaded across Tasks.

## Use Labtasker with an agent

Labtasker includes an Agent Skill for submission, Worker design, inspection,
updates, and recovery. A request such as “run these cases in parallel across 8
GPUs with Labtasker” gives a coding agent a standard workflow instead of asking
it to invent another scheduler.

Claude Code users can install the repository plugin:

```text
/plugin marketplace add luocfprime/labtasker@v2
/plugin install labtasker-skill@labtasker
```

Agent Skills-compatible tools can install the canonical skill directly:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/v2/skills/labtasker
```

See the [Agent Skill guide](docs/guides/agent-skill.md) for tool and scope
selection. The documentation build also exposes [`/llms.txt`](docs/llms.txt), a
concise map from an agent to the raw Markdown guides and references.

## Documentation

- [Get started](docs/getting-started.md): install, submit, run, and inspect.
- [Core model](docs/concepts.md): Task, Worker, Queue, route, and recovery model.
- Examples: [inference and evaluation](docs/inference-evaluation.md) and the
  [RoboTwin case study](docs/case-studies/starvla-robotwin.md).
- [Task operations](docs/guides/tasks.md): inspect or change a running plan.
- [Failure and recovery](docs/guides/failure-recovery.md): retries,
  interruption, cancellation, and journals.
- [Configuration](docs/reference/configuration.md): local and shared HTTP use.
- [CLI](docs/reference/cli.md) and [Python API](docs/reference/python-api.md):
  exact public interfaces.
- [Specification](docs/reference/specification.md): authoritative product and
  protocol contract.

V2 ships separate `labtasker-client` and `labtasker-server` runtime
distributions plus the `labtasker` convenience package. Linux is release-gated.
Ordinary Client, Server, and Python Worker use is best effort on macOS and
Windows; the automatic local Server requires POSIX, and Command or distributed
Workers are unsupported on Windows. Windows users connect the Client to an
explicitly started HTTP Server.

## Development

```bash
uv sync --all-packages --group dev --frozen
uv run pytest
uv run zensical build --clean
```

See [Development](docs/development.md) for the complete validation and package
boundaries.

## License

Apache-2.0.
