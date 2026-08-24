from __future__ import annotations

import time

import labtasker


@labtasker.loop(route="addition-python", idle_timeout=0)
def add(
    left: int = labtasker.TaskArg(),
    right: int = labtasker.TaskArg(),
) -> None:
    time.sleep(0.1)  # Stand in for inference, evaluation, or another expensive job.
    total = left + right
    labtasker.finish({"total": total})
    print(f"completed expression={left}+{right} total={total}")


if __name__ == "__main__":
    add()
