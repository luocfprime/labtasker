# Workers and workload design

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
is online. Use descriptive implementation or workload names such as `robotwin`,
`clip-openai`, and `clip-openclip`.

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

## Wrap an existing command

Use the required `--` separator followed by one argv template:

```bash
CUDA_VISIBLE_DEVICES=0 labtasker loop --route robotwin -- \
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
the shell visible, for example `bash -lc '...'`, and accept responsibility for
its quoting and interpolation. Do not add a wrapper merely to reproduce output
capture: Labtasker forwards child output live and writes the raw combined output
to the run's `run.log`.

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
outer Worker's exit code; after resolving that Task, the Worker continues.
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

## Reuse loaded Python state

Use a Python Worker when setup should happen once:

```python
import labtasker


@labtasker.loop(route="sdxl-diffusers")
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

An invalid static handler definition, unusable annotation, or non-callable
resolver fails before the first claim. A particular Task's missing value, type
mismatch, or resolver failure happens after claim and is a normal charged Task
failure. Argument shape never affects Server eligibility; Queue, pending state,
and route decide the claim. A normal return succeeds with `{}`.

## Use single-node distributed launchers

Keep one Labtasker Command Worker outside a single-node launcher:

```bash
labtasker loop --route robotwin -- \
  torchrun --nproc-per-node=8 evaluate.py --task '%{task}'
```

The launcher owns its ranks. Only its main rank calls `finish()`. Do not start a
Labtasker Worker inside every rank. Multi-node allocation and rendezvous remain
the external scheduler's responsibility.
