"""
Suppose this is the given script to run certain job.
You would normally run this with ` python demo/bash_demo/job_main.py --arg1 1 --arg2 2`
"""

import argparse
import time


def job(arg1: int, arg2: int):
    """Simulate a long-running job"""
    time.sleep(3)  # simulate a long-running job
    return arg1 + arg2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arg1", type=int)
    parser.add_argument("--arg2", type=int)

    args = parser.parse_args()
    result = job(args.arg1, args.arg2)
    print(f"The result is {result}")
