# Inference and evaluation patterns

These examples show how to use Labtasker for common ML work: reuse one loaded
model across many inputs, run an existing evaluation command many times, switch
between implementations explicitly, and save large output files separately.

## Reuse one loaded inference model

Submit prompts as ordinary Tasks:

```python
import labtasker

# TODO: Replace this with the prompts and seeds for your experiment.
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


# TODO: Replace this with your actual model initialization.
generate(load_sdxl_pipeline())
```

Start one copy on each assigned GPU to process more Tasks at the same time.
Labtasker does not allocate the GPUs.

## Run an existing evaluator

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

If a new Worker should also process existing Tasks, update those pending
Tasks explicitly. Merely starting the new Worker never redirects old work.

## Keep large outputs outside the Server

Keep Task args, metadata, and results small. Save images, embeddings,
predictions, and detailed reports in the run directory or external artifact
storage. Return a path, URL, checksum, or summary through `finish()` so the Task
record identifies the output.
