from __future__ import annotations

import labtasker

CASES = (
    (1, 2),
    (2, 3),
    (3, 5),
    (5, 8),
    (8, 13),
    (13, 21),
)
ROUTE = "addition-python"


def main() -> None:
    for left, right in CASES:
        task = labtasker.submit_task(
            {"left": left, "right": right},
            name=f"add-{left}-{right}",
            routes=[ROUTE],
        )
        print(f"submitted task_id={task.id} expression={left}+{right}")


if __name__ == "__main__":
    main()
