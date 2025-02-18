import time

import labtasker


def job(arg1: int, arg2: int):
    """Simulate a long-running job"""
    time.sleep(3)  # simulate a long-running job
    return arg1 + arg2


@labtasker.loop(required_fields=["arg1", "arg2"])
def main():
    args = labtasker.task_info().args
    result = job(args["arg1"], args["arg2"])
    print(f"The result is {result}")


if __name__ == "__main__":
    main()
