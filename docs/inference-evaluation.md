# Inference and evaluation

Labtasker is most useful when work is naturally split into independent model
calls or evaluation units. The Queue provides durable progress and retries, while
a long-lived Worker keeps expensive runtime state warm.

## Reuse one loaded inference model

Submit prompts as ordinary Tasks:

```python
import labtasker

for seed, prompt in enumerate(prompts):
    labtasker.submit_task(
        {"prompt": prompt, "seed": seed},
        name=f"prompt-{seed:04d}",
        routes=["sdxl-diffusers"],
    )
```

Load the pipeline once, then let Labtasker supply only per-image values:

```python
import torch

import labtasker


@labtasker.loop(route="sdxl-diffusers")
def generate(
    pipeline,
    prompt: str = labtasker.TaskArg(),
    seed: int = labtasker.TaskArg(),
) -> None:
    generator = torch.Generator(device="cuda").manual_seed(seed)
    image = pipeline(prompt, generator=generator).images[0]
    path = labtasker.task_info().run_dir / "image.png"
    image.save(path)
    labtasker.finish({"image": str(path)})


generate(load_sdxl_pipeline())
```

Start several copies on already allocated GPUs to scale horizontally. Labtasker
does not need to know how each GPU was allocated.

## Dispatch an existing evaluator

Evaluation code often already has a command interface. Keep it unchanged apart
from an optional `finish()` call that records structured metrics:

```bash
labtasker loop --route clip-score -- \
  python evaluate.py \
    --image '%{image}' \
    --caption '%{caption}'
```

Each Task can represent one sample, shard, checkpoint, or benchmark. Query the
completed set without maintaining a separate progress spreadsheet:

```bash
labtasker task count --status pending
labtasker task list \
  --filter 'status == "succeeded" and result.score < 0.2' \
  --order-by finished_at
```

## Compare or roll out implementations

Routes keep implementation choice explicit. A Task that either codebase can
evaluate may list both:

```python
labtasker.submit_task(
    {"image": "outputs/001.png", "caption": "a red panda"},
    routes=["clip-openai", "clip-openclip"],
)
```

If a new Worker should also process an existing backlog, update those pending
Tasks explicitly. Merely starting the new Worker never redirects old work.

## Keep large outputs outside the Server

Task args, metadata, and results are compact JSON control data. Save images,
embeddings, predictions, and detailed reports in the run directory or external
artifact storage, then return a path, URL, checksum, or summary through
`finish()`. This keeps the task database small without hiding where an output
came from.
