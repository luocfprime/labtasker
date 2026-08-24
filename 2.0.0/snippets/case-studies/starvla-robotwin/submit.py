# Architectural excerpt, not a drop-in StarVLA integration.
from itertools import product

import labtasker

ROBOTWIN_TASKS = [...]  # StarVLA's 50 task names
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
