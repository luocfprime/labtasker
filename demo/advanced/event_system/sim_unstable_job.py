"""
Simulate running an unstable job.
"""

import random
import time

import labtasker
from labtasker import Required


def job(arg1: int, arg2: int):
    """Simulate a long-running job"""
    time.sleep(1.5)  # simulate a long-running job
    if random.uniform(0, 1) < 0.5:  # simulate unstable events
        raise Exception("Random exception")
    return arg1 + arg2


@labtasker.loop()
def main(arg1: int = Required(), arg2: int = Required()):
    result = job(arg1, arg2)
    print(f"The result is {result}")


if __name__ == "__main__":
    main()
