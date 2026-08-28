# Architectural excerpt, not a drop-in StarVLA integration.
from itertools import product

import labtasker

# TODO: Replace these placeholders with values from your StarVLA configuration.
ROBOTWIN_TASKS = [...]
CHECKPOINT = ...
SEED = ...
MODES = ["demo_clean", "demo_randomized"]

for task, mode in product(ROBOTWIN_TASKS, MODES):
    labtasker.submit_task(
        {
            "checkpoint": CHECKPOINT,
            "task": task,
            "mode": mode,
            "seed": SEED,
        },
        name=f"{task}-{mode}",
        routes=["robotwin"],
        max_attempts=3,
    )
