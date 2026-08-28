# Labtasker

<p align="center">
  <img src="assets/logo.png" alt="Labtasker" width="520">
</p>

<p align="center"><em>Labtasker is a small, Python-native task queue for running independent ML inference, evaluation, and experiment jobs in parallel.</em></p>

<p align="center">
  <a href="https://github.com/luocfprime/labtasker/actions/workflows/ci.yml"><img src="https://github.com/luocfprime/labtasker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/luocfprime/labtasker/actions/workflows/docs.yml"><img src="https://github.com/luocfprime/labtasker/actions/workflows/docs.yml/badge.svg" alt="Documentation"></a>
  <a href="https://pypi.org/project/labtasker/"><img src="https://img.shields.io/pypi/v/labtasker" alt="PyPI version"></a>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.11-blue" alt="Python 3.11 or newer">
</p>

---

**Documentation:** <https://luocfprime.github.io/labtasker/>

**LLM Documentation:** <https://luocfprime.github.io/labtasker/latest/llms.txt>

**Source Code:** <https://github.com/luocfprime/labtasker>

---

Labtasker distributes independent ML jobs across multiple processes and
machines. It adds dynamic control, failure recovery, and structured Task
records without requiring each project to build its own task system.

The key features are:

- **Effortless and flexible parallelism:** Run the same Task queue with multiple
  Workers. Submit new Tasks, change priorities, or cancel Tasks without
  interrupting the Workers.
- **Resumable and failure-resistant experiments:** Retry failed Tasks
  automatically and recover work when a Worker stops. Restart Workers without
  rerunning completed Tasks. These lifecycle behaviors are covered by unit and
  end-to-end tests.
- **Structured task records:** Keep each Task's arguments, metadata, status,
  errors, and structured result in one place for inspection.
- **Easy to adopt and use:** Add Labtasker to existing Python code in fewer than
  10 lines, or wrap an existing command with no code changes. The API,
  non-interactive CLI, [Agent Skill](guides/agent-skill.md), and
  [agent-readable documentation](llms.txt) allow an agent to operate Labtasker
  end to end.

## When to use Labtasker

Labtasker is designed for independent ML work such as:

- model inference over prompts, samples, or dataset shards;
- evaluation across checkpoints, benchmark cases, and random seeds;
- generation and ablation experiments across parameter combinations;
- independent data-processing or analysis jobs.

Labtasker becomes useful when several processes share the work, you need to
resume after an interruption without rerunning completed jobs, or you need to
add, cancel, or reprioritize jobs during a run.

## When NOT to use Labtasker

- A simple loop can be sufficient for a small experiment with a few short jobs
  that can be rerun in full.
- Use a workflow or DAG system when jobs depend on outputs from earlier jobs.
- Use a cluster or resource scheduler when you need to allocate GPUs, start
  machines, or manage compute capacity.
- Use an artifact store for model checkpoints, generated media, and other large
  outputs. Labtasker records their paths or URLs, not the files themselves.

Labtasker is deliberately designed to be conceptually simple and easy to hand
over to agents.

Read [Why Labtasker?](why-labtasker.md) for a fuller comparison with
project-specific experiment scripts and the design decisions behind v2.

## How it works

Submit every independent experiment case as a **Task**. Then start one or more
**Workers** on the CPUs, GPUs, or machines where the jobs should run. Each
Worker claims one compatible Task, executes it, records the outcome, and asks
for another.

The **Server** stores Task state and coordinates claims. A **route** labels
which Worker implementation can run a Task. A **Queue** groups Tasks that should
be managed together.

Read [How Labtasker works](concepts.md) for retries, recovery, routes, Queues,
and the boundary between the Server and Worker processes.

## Choose a starting point

| What you want to do | Start here |
| --- | --- |
| Run several cases through one Queue | [Run your first experiment](getting-started.md) |
| Run checked-in code used by the test suite | [Run the tested demo](demo.md) |
| Decide whether Labtasker fits your workflow | [Why Labtasker?](why-labtasker.md) |
| Understand Tasks, Workers, routes, and Queues | [How Labtasker works](concepts.md) |
| Reuse a loaded model or an existing evaluator | [Inference and evaluation patterns](inference-evaluation.md) |
| Choose how Tasks execute | [Python Workers](workers/python.md), [command Workers](workers/command.md), or [distributed launchers](workers/distributed.md) |
| Submit, inspect, or change Tasks | [Manage Tasks](guides/tasks.md) and [query Tasks](guides/query.md) |
| Recover interrupted or failed work | [Failure and recovery](guides/failure-recovery.md) |
| Let a coding agent operate Labtasker | [Agent Skill](guides/agent-skill.md) |
| Configure local or shared use | [Configuration](reference/configuration.md) |
| Check an exact interface | [Python API](reference/python-api.md), [CLI](reference/cli.md), or [HTTP API](reference/http-api.md) |
| Verify the product contract | [Specification](reference/specification.md) |
