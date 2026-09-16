# Workers and workload design

## Lead a pipeline migration

For an existing pipeline, learn the workload before naming Labtasker
abstractions. Inspect the current entry point and configuration when the project
is available. Treat the questions below as a decision ladder, not an intake
checklist. Ask at most one or two unanswered questions that can change the next
recommendation:

- What command or function performs one run, and which input values change?
- What work can fail and be retried independently without corrupting outputs?
- Which model, dataset, simulator, or other expensive state could stay loaded
  across runs?
- Then ask how resources are launched, whether stages depend on one another,
  where outputs live, or how retries should behave only when the described
  workflow makes that fact relevant to the immediate decision.

Treat facts stated by the user or visible in the repository as answered. When
risk is low, state a reasonable assumption and give a conditional recommendation
instead of waiting for a complete questionnaire. Do not ask about stage
dependencies for a single-stage program or ask about machine scope when the
launcher already answers it. Do not ask a newcomer “Which Worker type?”,
“What route?”, “How many Queues?”, or “Which Labtasker deployment?” Translate the
facts into a recommendation:

| Project fact | Recommended mapping |
| --- | --- |
| One independently retryable run | One Task |
| Values that change the execution | `args` |
| Searchable experiment or batch labels | `metadata` |
| Small metrics and artifact references | `result` |
| Existing executable with acceptable per-run startup | Command Worker |
| Expensive reusable in-process state | Python Worker |
| Equivalent executors for the same work | One shared route |
| A separately managed body of work | One Queue |
| GPU, node, Pod, or process allocation | Existing launcher or scheduler |
| Stage dependencies and barriers | Existing workflow controller |
| Large or durable outputs | Existing shared or object storage |

When a fact leaves a real trade-off, ask about the consequence rather than the
Labtasker mechanism. For example, ask whether avoiding repeated model loading is
worth a small Python refactor; do not ask the user to choose between a Command
Worker and Python Worker.

Before editing code, summarize the proposed migration in project terms first:

1. the current entry point and independent work item;
2. what code, launcher, and storage remain unchanged;
3. what Labtasker will submit, distribute, retry, and record;
4. what stays owned by the resource scheduler, workflow system, or artifact
   store; and
5. the concrete Task, Worker, route, Queue, and deployment mapping, with reasons.

## Map an experiment

Submit each independently retryable case as a Task. In AIGC this may be one
prompt/seed/checkpoint/ablation combination. In embodied-AI evaluation it may be
one benchmark suite or subtask. Avoid fixed GPU shards when runtimes vary: start
one Worker process on each already allocated resource, and let each process take
another Task when it finishes.

Use:

- `args` for values the implementation executes;
- `metadata` for searchable grouping such as benchmark, checkpoint, or sweep;
- `result` for compact JSON metrics and external artifact references;
- `priority` to choose urgent pending work first; and
- `max_attempts` for charged execution attempts.

Use one Queue for one independently managed body of work. Do not create a Queue
per GPU, Worker, model, or implementation.

## Design routes explicitly

A Worker declares exactly one route. A Task declares one or more routes and is
eligible only when the Worker's exact route is in that list. Matching is
case-sensitive; `SDXL` and `sdxl` differ. The default route on both sides is
`default`.

Routes have no wildcard, regular expression, negation, priority, or fallback
syntax. They are not registered resources and do not prove that an implementation
is online. Prefer human-readable implementation or workload names such as
`robotwin`, `clip-openai`, and `clip-openclip`; avoid names consisting only of a
hash or random string so people can recognize what work a route accepts.

For a rollout, run separate Workers for the old and new routes. A Task may list
both when either implementation is acceptable:

```python
labtasker.submit_task(
    {"image": "outputs/001.png"},
    routes=["clip-openai", "clip-openclip"],
)
```

Starting a new Worker never changes old Tasks. To let a new implementation help
with a pending backlog, explicitly replace the selected Tasks' complete routes
list. Running Tasks cannot be updated.

### Record route settings and confirm reuse before submission

Keep a durable route record in the experiment project's existing route document,
or use `experiments/labtasker-routes.md` when none exists. Reuse that same document across
agent sessions. This is a project convention, not a Server-side registry.

For each route, record:

- its exact name, purpose, and Server/project and Queue scope, without credentials;
- the first confirmed submission date, including timezone; leave it unknown for
  historical routes when evidence is unavailable;
- the concrete execution settings: implementation and entry point, fixed Worker
  configuration, model/checkpoint revision, relevant dependencies or environment,
  and any resource requirements that affect compatibility;
- the code repository and commit, plus any uncommitted changes that affect
  execution; a branch name alone is not a reproducible version;
- the accepted Task args and their allowed variation, expected outputs, and
  compatibility conditions; link to durable configuration files where useful;
- the parameter combinations the Worker needs: record concrete fixed startup
  arguments and the required per-Task args, their types, defaults, and supported
  combinations or constraints. Include a reusable command or configuration
  example, distinguishing fixed values from values that may vary per Task;
- dated compatibility decisions or revisions, preserving earlier settings
  rather than silently overwriting them. Representative Task IDs are not needed.

Before submitting a batch:

1. Read the route record and inspect all pages of online Worker observations
   and running Tasks in the target Server and Queue. Summarize observed Worker
   routes/activity, Task `routes`, and relevant recorded settings. Read
   [observations-and-counts.md](observations-and-counts.md) for presence limits;
   follow the pagination guidance in [operations-and-recovery.md](operations-and-recovery.md).
   A running Task's routes list describes acceptable implementations, not which
   route its current Worker actually uses, and is not an inventory of Workers.
2. Compare the proposed workload with those routes and the recorded historical
   routes. Never decide compatibility-based reuse on the user's behalf. Present
   the candidate route, matching settings, and any differences, then explicitly
   ask: "你提交的实验似乎和 `xxx` route 类似，可能是同一组实验，是否复用？"
   Adapt the wording to the user's language and replace `xxx` with the actual
   route. Wait for explicit approval of that route for the proposed batch before
   submitting with it. Similar settings, historical reuse, a route record, or a
   general request to submit experiments is not consent to reuse. A shared
   experiment name or broad task category is also insufficient. Ask once for
   the batch, not per Task; an explicit approval already given for this exact
   batch and route remains valid while the relevant settings are unchanged.
3. If there are no running Tasks, say so and check the document for reusable
   routes; absence of running Tasks does not imply a route is obsolete or has no
   available Worker. If inspection fails or settings are unknown, disclose the
   gap and ask the user to resolve it before submission rather than assuming a
   match or treating failure as an empty result.
4. Reuse a route only with the user's explicit approval and when its executors
   can accept the new Task inputs and
   produce acceptable outputs under the documented settings. Changes to ordinary
   per-Task values within that contract do not require a new route. Incompatible
   implementation, configuration, or output changes need a distinct readable
   route; never silently redefine an old route that existing Workers still use.
5. Prepare the route entry before submission, marking an unsubmitted entry as
   planned. After the first confirmed successful submission, record its date.
   On reuse, preserve the original first-submission date and record any
   newly confirmed compatible settings. Do not invent missing revisions or
   dates. Keep this record available to subsequent agent sessions.

## Wrap an existing command

Use the required `--` separator followed by one argv template:

```bash
CUDA_VISIBLE_DEVICES=0 labtasker loop \
  --route robotwin \
  --metadata '{"node":"node-a","gpu_ids":["0"]}' \
  -- \
  python evaluate.py \
    --task '%{task}' \
    --checkpoint '%{checkpoint}'
```

Labtasker executes argv directly. It does not invoke a shell, join or split
arguments, expand `$VARS`, or interpret pipes and redirections. Each `%{path}`
resolves to exactly one argv element, even when it contains spaces.

A selected JSON string is inserted directly. Other JSON values, including
numbers, Booleans, null, arrays, and objects, become compact deterministic JSON
inside that one argv element; object keys are sorted. An empty string remains an
empty argv element, while NUL cannot be represented and fails binding.

Prefer direct argv. If the workload deliberately requires shell syntax, make
the shell visible and pass resolved Task values as positional arguments rather
than interpolating them into the shell program text:

```bash
labtasker loop --route preprocess -- \
  bash -lc 'python preprocess.py --input "$1" > "$2"' \
    labtasker-shell '%{input}' '%{output}'
```

For `bash -c`, the first argument after the program text supplies `$0`; later
arguments supply `$1`, `$2`, and so on. Shell quoting, expansion, pipeline exit
behavior, and redirection are then the user's responsibility. Do not add a
wrapper merely to reproduce output capture: Labtasker forwards child output
live and writes the raw combined output to the run's `run.log`.

For a per-Task environment value on POSIX, an explicit external `env` command is
simpler than a shell:

```bash
labtasker loop --route train -- \
  env 'LR=%{lr}' python train.py --seed '%{seed}'
```

Static environment values belong on the Worker process itself.

Command placeholder paths traverse JSON objects using dot-separated ASCII
identifier segments, such as `%{seed}` or `%{judge.threshold}`. They do not
support array indices, hyphenated or Unicode keys, quoted segments, defaults,
wildcards, or expressions. Reshape the args or use a Python Worker with
`task_info().args` when arbitrary JSON access is required.

Use `%{{` when the child must receive a literal `%{` opener. For example,
`%{{name}` resolves to the literal text `%{name}` rather than reading a Task
argument. Ordinary percent signs and stray closing braces are otherwise
literal.

Static template syntax errors stop the Worker before it claims anything. A
missing key or non-object intermediate belongs to a claimed Task, prevents child
startup, and is a normal charged Task failure.

Terminal handling is automatic and has no public `--pty` or `--no-pty` option.
When the Worker's stdin, stdout, and stderr are attached to an interactive POSIX
terminal, Labtasker uses an internal PTY and relays input, output, and terminal
size. In a scheduler, pipeline, or redirected run it uses ordinary pipes, drains
stdout and stderr concurrently, and connects child stdin to `/dev/null`.

Both modes forward output live and append the raw bytes to the current run's
`run.log`. Pipe mode preserves separate stdout and stderr destinations for the
caller even though the journal contains both. Do not add `tee` merely to obtain
the Labtasker run log.

Without `finish()`, exit code zero succeeds with `{}` and nonzero is a charged
failure. Existing child code may report a structured result:

```python
labtasker.finish({"score": 0.94}, skip_if_no_labtasker=True)
```

`finish()` accepts one JSON-compatible object. Convert values such as `Path` to
strings and keep NumPy arrays, tensors, and other large data in external storage
rather than passing arbitrary Python objects or top-level scalars.

Once accepted, `finish()` is stable: later cleanup failure or nonzero process
exit cannot rewrite the succeeded Task.

Command Workers have no reserved child exit codes or output-text protocol.
Every nonzero exit code or signal is the same charged Task failure, while stdout
and stderr are only relayed and logged. A child exit code does not become the
outer Worker's exit code; after resolving that Task, the Worker normally
continues subject to the consecutive-failure guard below.
Use a Python Worker when the workload must deliberately choose
`TransientError`, `TaskError`, or `FatalWorkerError`.

## Choose Worker lifetime deliberately

Both Worker styles wait for newly eligible Tasks after an empty claim. The
public `idle_timeout` defaults to 300 seconds, resets after each successful
claim, and then ends the Worker normally if no work appears. Set
`idle_timeout=0` or CLI `--idle-timeout 0` to exit on the first empty claim; this
does not mean “run exactly one Task” when the Queue remains non-empty.

There is no infinite-wait value, daemon mode, `once`, `max_tasks`, or automatic
Worker restart. Use an external process supervisor when a Worker must be kept
available indefinitely or restarted after process failure.

Each loop has `max_consecutive_failures=5`; Python `loop()` accepts this keyword
and CLI `labtasker loop` exposes `--max-consecutive-failures`. It must be a positive non-Boolean integer, with no
disable value or environment setting. Accepted ordinary failures (including
binding errors, child startup failures and nonzero exits) and accepted
`TransientError` unclaims increment it. Successful completion resets it,
including accepted `finish()` followed by ordinary cleanup failure. Empty polls,
cancellation and ownership loss leave it unchanged; transport retries and
observation failures do not increment it. After reporting and cleanup, reaching
the limit raises `FatalWorkerError` before another claim; CLI exits `1`. Explicit
`FatalWorkerError` still exits immediately, even after `finish()`. This local
guard changes neither Task retry accounting nor fencing. Each invocation starts
at zero: configure supervisor restart backoff and frequency limits externally.

## Reuse loaded Python state

Use a Python Worker when setup should happen once:

```python
import labtasker


@labtasker.loop(
    route="sdxl-diffusers",
    metadata={"node": "node-a", "gpu_ids": ["0"]},
)
def generate(
    pipeline,
    prompt: str = labtasker.TaskArg(),
    seed: int = labtasker.TaskArg(),
    steps: int = labtasker.TaskArg(default=30),
) -> None:
    image = pipeline(prompt, seed=seed, steps=steps)
    path = labtasker.task_info().run_dir / "image.png"
    image.save(path)
    labtasker.finish({"image": str(path)})


generate(load_pipeline_once())
```

Only parameters whose default is `TaskArg(...)` bind from Task args. Other
arguments are fixed when the Worker starts. Binding uses the annotation's strict
schema: an `int` does not accept a string, float, or Boolean, and Labtasker does
not add casts. A `TaskArg(default=value)` default passes through the same
resolver and annotation validation as a submitted value.

`TaskArg(path="judge.threshold")` selects a nested object field. A resolver
receives that selected raw JSON value, returns a value, and the annotation then
validates the return. Extra Task args are ignored by named binding, including
when the handler declares `**kwargs`; that parameter receives only ordinary
keyword arguments supplied when the Worker starts. Read the complete object
through `task_info().args`.

Python Worker handlers and `TaskArg` resolvers must be synchronous. An
`async def` handler, an object with an asynchronous `__call__`, an `async def`
resolver, an object with an asynchronous resolver `__call__`, an otherwise
invalid static handler definition, an unusable annotation, or a non-callable
resolver fails before the first claim. A particular Task's missing value, type
mismatch, or resolver failure happens after claim and is a normal charged Task
failure.
Argument shape never affects Server eligibility; Queue, pending state, and route
decide the claim. A normal return succeeds with `{}`.

## Report current progress separately from the result

An active Python program may publish one compact latest snapshot without
completing its Task:

```python
labtasker.report_progress(
    {
        "completed": completed_cases,
        "total": total_cases,
        "metrics": {"validation_loss": validation_loss},
    },
    skip_if_no_labtasker=True,
)
```

This works inside a Python Worker and inside Python launched by a Command
Worker. A non-Python child can use the inherited execution context:

```bash
labtasker progress \
  --data '{"completed":42,"total":100,"metrics":{"validation_loss":0.82}}'
```

Each report replaces the complete previous `progress` object. It does not merge,
complete the Task, renew the lease, or create a history series. Keep the final
successful summary in `finish(result)` and keep metric history, artifacts, and
checkpoints in their existing external systems. Report at useful evaluation or
checkpoint boundaries rather than every inner-loop step.

The object has no required business keys. For a determinate Labtasker WebUI
indicator, use top-level `completed` and `total` only when both are finite
numbers, `0 <= completed <= total`, and `total > 0`. Metrics, best-so-far values,
and early-stop diagnostics may use any other JSON keys. The Server records the
report time and attempt. It retains the last snapshot after success, failure,
unclaim, expiry, or cancellation for diagnosis, then clears it when a new claim
starts.

Reporting is supplementary and best effort. The Python helper returns `True`
when accepted and `False` for an isolated transport or Server rejection; such a
failure must not fail the workload. Invalid data or missing execution context is
a programming error unless `skip_if_no_labtasker=True` handles the latter.

Use Worker telemetry, not Task progress, for a latest resource/load snapshot
shared across the Worker's successive Tasks:

```python
labtasker.report_worker_telemetry(
    {"gpu_util_pct": gpu_utilization, "memory_used_gb": memory_used_gb}
)
```

The synchronous call completely replaces the previous Worker telemetry object
and returns whether the Server accepted it. It does not renew Worker presence or
affect the Task. Labtasker does not detect resource fields, sample periodically,
retry, merge, or keep history. If periodic sampling is needed, user code owns
the thread or schedule. A Command child can run `labtasker worker telemetry
--data JSON`; all distributed ranks inherit one Worker ID and replace the same
snapshot.

## Use single-node distributed launchers

Keep one Labtasker Command Worker outside a single-node launcher:

```bash
labtasker loop --route robotwin -- \
  torchrun --nproc-per-node=8 evaluate.py --task '%{task}'
```

The launcher owns its ranks. Only its main rank calls `finish()`. Do not start a
Labtasker Worker inside every rank. Multi-node allocation and rendezvous remain
the external scheduler's responsibility. Labtasker's documented launcher
integration stops at the single-node pattern above; it does not define the
ownership topology for one Task spanning several machines. Do not present a
custom multi-node outer-Worker arrangement as a supported Labtasker interface.
