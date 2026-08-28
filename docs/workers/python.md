# Python Workers

Use a Python Worker when one inference or evaluation job is a Python function.
It can initialize a model, pipeline, dataset, or judge once and reuse it across
many Tasks.

```python
import labtasker


@labtasker.loop(route="embed", idle_timeout=300)
def embed(
    model,
    text: str = labtasker.TaskArg(),
    normalize: bool = labtasker.TaskArg(default=True),
) -> None:
    vector = model.encode(text, normalize=normalize)
    labtasker.finish({"embedding": vector.tolist()})


# TODO: Replace this with your actual model initialization.
embed(load_embedding_model_once())
```

Pass `model` when calling the decorated function. Only parameters whose default
is `TaskArg(...)` are read from each Task.

## Binding rules

- A required `TaskArg()` fails the claimed Task when its key is absent.
- `TaskArg(default=value)` supplies that value when the key is absent.
- A `resolver` can transform one JSON value before annotation validation.
- Type checking is strict: `int` does not accept a float, string, or Boolean.
- Extra Task args are ignored by named binding.
- Code that needs every Task argument can read `task_info().args`; there is no
  second full-dictionary binding mode.

Use `path` to select a nested object field without renaming the Python
parameter:

```python
@labtasker.loop(route="evaluate")
def evaluate(threshold: float = labtasker.TaskArg(path="metric.threshold")) -> None: ...
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

Normal return succeeds with `{}`. Call `finish(result)` to record a structured
result before local cleanup continues:

```python
labtasker.finish({"score": 0.94})
release_engine_resources()
```

Calling `finish()` twice is an error. Outside Labtasker, it raises unless
`skip_if_no_labtasker=True` is explicitly requested.

## Cooperative cancellation

`cancellation_requested()` tells Python code that the Server cancelled or
recovered its current run. By default, Labtasker waits for the function to
return. Set a process-wide deadline only when forced termination is safe:

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
the Server already accepted `finish()`, a later exception does not change the
Task from succeeded.
