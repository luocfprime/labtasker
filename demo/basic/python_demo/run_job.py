import time

import labtasker
from labtasker import Required


def job(arg1: int, arg2: int):
    """Simulate a long-running job"""
    time.sleep(3)  # simulate a long-running job
    return arg1 + arg2


@labtasker.loop()
def main(arg1: int = Required(), arg2: int = Required()):
    # The labtasker autofills the parameter specified by Required()
    # or Annotated[Any, Required()]
    # Alternatively, you can fill in the required fields
    # in loop(required_fields=["arg1", "arg2"]
    # and access it via labtasker.task_info().args
    result = job(arg1, arg2)
    print(f"The result is {result}")


if __name__ == "__main__":
    main()
