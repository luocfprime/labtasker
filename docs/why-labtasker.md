# Why Labtasker?

Labtasker runs many independent ML experiments in parallel without making every
project invent its own task distribution, retry, and result-collection system.

## Why not write the scripts yourself?

A few experiment cases fit naturally in one script:

```python
for case in cases:
    run(case)
```

There is nothing wrong with this approach when there are only a few jobs and it
is safe to rerun everything. Now suppose there are 100 evaluations and 8 GPUs.
How should the jobs be divided when their runtimes are unknown? What happens when
one fails halfway, the run is interrupted, or a new high-priority case arrives?

Most projects gradually add GPU-assignment logic, status files, retries, locks,
and result parsing. Without Labtasker, the same request turns into a long
back-and-forth about implementation details: how to keep GPUs busy, remember what
finished after a crash, retry safely, and collect results without parsing logs.
Even when an agent writes the code, it still has to invent and debug another
project-specific task system.

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

Compared with one-off task scripts, Labtasker provides a cleaner, better-tested,
and more reliable solution with less project-specific code. Its standardized,
explicit workflow is easy to automate and agent-friendly by design. With the
bundled Agent Skill, task dispatch can be as simple as telling your agent: “Run
these jobs in parallel across 8 GPUs with Labtasker.” The experiment still owns
its model code, processes, GPUs, machines, and artifact storage.

## The working model

Using Labtasker requires three actions:

1. Submit each independent piece of work as a Task.
2. Start a Worker on each resource that should execute that kind of work.
3. Inspect or change the Tasks while Workers consume the backlog.

A Worker handles one Task at a time and asks for another when it finishes. There
is no need to divide the backlog into equal-looking chunks first. Adding a Worker
increases parallelism; stopping one reduces parallelism without changing the
remaining Tasks.

Tasks and Workers use explicit route labels to declare compatibility. Labtasker
does not inspect a Task's arguments and guess which implementation should run it.
This makes dispatch understandable before execution and safe during implementation
rollouts.

## AIGC experiments and ablations

AIGC work often means generating or evaluating a large matrix of prompts, seeds,
samplers, checkpoints, and ablation settings, then selecting a small number of
useful results.

Manually assigning that matrix to GPUs creates fixed shards. A slow sample, a
failed process, or a new high-priority comparison makes those shards obsolete.
With Labtasker, every case is a Task and all compatible GPU Workers draw from the
same backlog. Fast Workers naturally process more cases, failed cases remain
visible, and new or higher-priority cases can enter the run immediately.

A Worker may also load an expensive model once and reuse it across many Tasks.
That is an important optimization for inference, but it is a consequence of the
Worker model rather than Labtasker's reason for existing.

## Embodied-AI benchmarks

Embodied evaluation commonly contains many suites or subtasks with very different
runtimes. Splitting 100 subtasks evenly across four GPUs does not imply four equal
jobs: one suite may take minutes while another takes hours. GPUs assigned shorter
shards finish early and starve even though work remains elsewhere.

Labtasker schedules at the Task boundary instead. A free Worker claims the next
compatible subtask, so the allocation adapts to actual runtime rather than an
estimate made before the benchmark starts. The Server records progress, attempts,
errors, and small structured results in one place. Large videos, trajectories,
checkpoints, and other artifacts remain in project-owned storage, with their paths
or identifiers returned as Task results.

The [Embodied AI: RoboTwin evaluation (StarVLA codebase)](case-studies/starvla-robotwin.md)
case study shows the boundary in a real project. Evaluating one VLA checkpoint
across 50 robot-manipulation tasks requires dynamic GPU scheduling, process and
port management, failure tracking, cleanup, and result collection. StarVLA
implements that coordination in a substantial Bash launcher; the case study
shows which parts Labtasker can standardize without taking over the policy or
simulator.

## What Labtasker deliberately does not do

Labtasker is the coordination layer between a collection of Tasks and the Worker
processes that execute them. It does not:

- allocate GPUs or decide which machine should run a Worker;
- replace SLURM, Kubernetes, or another cluster scheduler;
- express dependencies between Tasks as a workflow DAG;
- act as an artifact store;
- keep an AI agent in the execution loop.

Use the existing environment to start Workers on the desired resources, and use
Labtasker to distribute and track the work they perform. If the problem is mainly
resource allocation, dependent pipelines, or artifact management, another tool
is likely a better fit.

## From v1 to v2

V2 is not mainly a collection of new features. It is a redesign around fewer
concepts, explicit behavior, and one complete path for each operation.

### One obvious way

V1 accumulated conveniences that could make a simple interaction look shorter
while adding overlapping abstractions, special cases, and behavior that was hard
to predict. V2 follows the principle that there should be one—and preferably only
one—obvious way to perform an operation.

This does not mean removing useful extensibility. It means that the built-in
workflow has a small number of complete operations that compose cleanly. A
convenience is not worthwhile when it merely hides a decision, duplicates another
interface, or leaves failure behavior undefined.

### Explicit instead of inferred

V1 could decide whether a Worker should consume a Task by inspecting its
arguments. That made scheduling depend on implicit knowledge of Worker code. V2
uses exact route labels: a Task declares its compatible routes and a Worker claims
through exactly one route.

The same preference applies to lifecycle changes. Cancellation, requeue, retry,
completion, failure, and pending-Task updates are distinct actions rather than
ambiguous status edits or interactive choices.

### Reliable execution semantics

V2 defines the complete Task lifecycle, including claims, heartbeats, leases,
attempts, retries, cancellation, and recovery after Worker loss. Every claim has
a private `run_id`; a late heartbeat or completion from an expired Worker cannot
overwrite the result of a newer run.

This reliability belongs in Labtasker rather than in a different collection of
launcher scripts for every experiment.

### Designed for agents and humans

Agents work best with explicit operations, stable schemas, deterministic output,
and errors that say exactly what failed. They work poorly when a tool requires
interactive choices, infers intent from hidden state, or offers several subtly
different ways to perform the same action.

V2 therefore provides an Agent Skill and makes the ordinary interfaces
agent-friendly by design: commands are non-interactive, requested data goes to
stdout, diagnostics go to stderr, JSON retains its types, and state changes use
named lifecycle actions. An agent can submit, inspect, update, and recover Tasks;
Task execution remains deterministic after a Worker starts and does not require
the agent to stay online.

### Python-native and ready locally

V1 required MongoDB for its real Server and used Mongomock to approximate an
embedded local experience. V2 needs neither. The default installation includes
the Python Client and Server, and on POSIX systems the first real operation
automatically starts a project-local Server backed by SQLite. There is no
database service, TCP port, or configuration to prepare for that local path.

The automatic local Server is not available on Windows. Windows Clients connect
to an explicitly operated HTTP Server instead; ordinary Client, Server, and
Python Worker use remains best effort there.

An explicitly managed HTTP Server remains available when several machines need
to share a Queue. This is a separate deployment choice, not setup that every new
project must perform.

| v1 | v2 |
| --- | --- |
| MongoDB, or Mongomock as a local substitute | Automatically managed local SQLite Server |
| Several conveniences with overlapping or implicit behavior | A small set of explicit, composable operations |
| Worker eligibility inferred from Task arguments | Compatibility declared with exact routes |
| Human-oriented interactions | Deterministic interfaces for humans and agents |
| Looser execution and recovery behavior | Defined lifecycle, leases, attempts, and `run_id` fencing |

Continue with [Get started](getting-started.md) for the local workflow or
[Core model](concepts.md) for the exact Task, Queue, route, and Worker concepts.
