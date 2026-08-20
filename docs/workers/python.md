# Python Workers

Use a Python Worker when the experiment is naturally a function call or when a
large object should be initialized once and reused across Tasks.

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

`model` is supplied normally when the Worker starts. Only parameters whose
default is `TaskArg(...)` are taken from each Task.

## Binding rules

- A required `TaskArg()` fails the claimed Task when its key is absent.
- `TaskArg(default=value)` supplies that value when the key is absent.
- A `resolver` can transform one JSON value before annotation validation.
- Type checking is strict: `int` does not accept a float, string, or Boolean.
- Extra Task args are ignored by named binding.
- Dynamic code can read the complete object through `task_info().args`; there is
  no second full-dictionary binding mode.

Use `path` to select a nested object field without renaming the Python
parameter:

```python
@labtasker.loop(route="train")
def train(lr: float = labtasker.TaskArg(path="optimizer.lr")) -> None: ...
```

A resolver receives the selected value, not the complete args object:

```python
from pathlib import Path

import labtasker


@labtasker.loop(route="evaluate")
def evaluate(
    output: Path = labtasker.TaskArg(resolver=Path),
) -> None: ...
```

Binding and resolver errors happen after claim and are normal Task failures.

## Execution context

Inside an active call, `labtasker.task_info()` provides the Task snapshot plus
the private `run_id` and absolute local `run_dir`.

Normal return succeeds with `{}`. Call `finish(result)` when a structured result
must be durably accepted before local cleanup continues:

```python
labtasker.finish({"accuracy": 0.94})
release_engine_resources()
```

Calling `finish()` twice is an error. Outside Labtasker, it raises unless
`skip_if_no_labtasker=True` is explicitly requested.

## Cooperative cancellation

`cancellation_requested()` tells Python code that its run was revoked. The
default is to wait indefinitely for the function to return. Set a process-wide
deadline only when the codebase can safely tolerate forced termination:

```python
if labtasker.cancellation_requested():
    save_checkpoint()
    return

labtasker.set_force_stop_timeout(30)
```

`set_force_stop_timeout()` changes the current run's deadline; `None` restores
indefinite waiting.

## Failure levels

```python
raise labtasker.TransientError("temporary storage outage")
raise labtasker.TaskError("invalid sample")
raise labtasker.FatalWorkerError("model runtime is corrupted")
```

`FatalWorkerError` reports a charged Task failure and then stops the Worker. If
the Task already succeeded through `finish()`, a later exception never changes
that stable succeeded state.
