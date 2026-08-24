# Labtasker

<p align="center">
  <img src="assets/logo.png" alt="Labtasker" width="520">
</p>

**Run many independent ML jobs in parallel without writing your own scripts to
split the work, retry failures, and collect results.**

A simple loop is fine for a handful of short jobs. Now imagine running 100
evaluations on 8 GPUs. Some finish in minutes; others take hours. If you divide
the list before starting, some GPUs will sit idle behind the slowest jobs. If the
script crashes, you must inspect logs and output folders to decide what to run
again.

Labtasker keeps one list of jobs and hands them out one at a time. Start one
evaluation process on each GPU; whenever it finishes a job, it gets another.
Labtasker remembers what is waiting, running, finished, or failed, so you can
continue after an interruption without repeating completed work.

Labtasker deliberately stops there. You still choose the machines and GPUs,
start the processes that use them, and decide where large outputs are saved. If
you need a system to allocate hardware or run a pipeline in which one job depends
on another, Labtasker is not that system.

## How it works

Labtasker uses two names in its commands and documentation: a **Task** is one
job, and a **Worker** is a process that runs jobs.

1. Add all the jobs you want to run.
2. Start one Worker on each GPU or other resource you want to use.
3. Each Worker runs one job, reports the result, and asks for another.

You do not need to divide the list among GPUs beforehand. You can inspect the
jobs or change their priority while the processes keep running. The
[Core model](concepts.md) introduces routes and Queues only when you need to
separate different implementations or bodies of work.

## Where it fits

- **AIGC and ablations:** distribute prompts, seeds, checkpoints, and settings
  across available GPUs, then inspect or prioritize the useful results.
- **Embodied-AI benchmarks:** dispatch suites and subtasks with unpredictable
  runtimes instead of leaving GPUs idle behind a slow fixed shard. The
  [RoboTwin case study](case-studies/starvla-robotwin.md) shows a real 50-task
  StarVLA evaluation workflow.
- **Inference, evaluation, and data processing:** coordinate any collection of
  independent parameterized work on user-started Workers.

[Why Labtasker?](why-labtasker.md) compares this workflow with project-specific
scripts and explains when another kind of tool is a better fit.

## Why v2 is different

V2 favors one explicit, complete way to perform each operation. Routes replace
argument-based scheduling guesses; named lifecycle actions replace implicit
status changes; attempts, leases, and `run_id` fencing define recovery. The
default Python installation manages a local SQLite Server automatically on
POSIX systems, so ordinary local use needs no MongoDB, port, or configuration
file. Windows uses an explicitly configured HTTP Server instead.

The same design makes Labtasker predictable for agents: the CLI is
non-interactive, requested data and diagnostics stay separate, and the bundled
Agent Skill describes the standard workflow. [From v1 to v2](why-labtasker.md#from-v1-to-v2)
explains the design decisions in detail.

## Choose a starting point

| Goal | Start here |
| --- | --- |
| Run the first Task | [Get started](getting-started.md) |
| Decide whether Labtasker fits | [Why Labtasker?](why-labtasker.md) |
| Understand Tasks, Workers, routes, and recovery | [Core model](concepts.md) |
| See worked ML examples | [Inference and evaluation](inference-evaluation.md) and the [RoboTwin case study](case-studies/starvla-robotwin.md) |
| Choose a Worker style | [Python](workers/python.md), [command](workers/command.md), or [distributed launcher](workers/distributed.md) |
| Inspect, update, or recover work | [Task operations](guides/tasks.md), [queries](guides/query.md), and [failure recovery](guides/failure-recovery.md) |
| Let an agent operate Labtasker | [Agent Skill](guides/agent-skill.md) or [llms.txt](llms.txt) |
| Configure a shared Server | [Configuration](reference/configuration.md) and [HTTP API](reference/http-api.md) |
| Check exact public behavior | [Python API](reference/python-api.md), [CLI](reference/cli.md), and the authoritative [specification](reference/specification.md) |
