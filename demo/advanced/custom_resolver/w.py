import time
from dataclasses import dataclass
from typing import Any, Dict

from typing_extensions import Annotated

import labtasker
from labtasker import Required


@dataclass
class ArgsGroupA:
    a: int
    b: str


@dataclass
class ArgsGroupB:
    foo: int
    bar: str


@labtasker.loop()
def main(
    # use type annotation/default values to automatically resolve the required_fields
    # use the self-defined resolver to convert the task args into custom types
    args_a: Annotated[
        Dict[str, Any], Required(resolver=lambda a: ArgsGroupA(**a))
    ],  # option1. use Annotated
    args_b=Required(resolver=lambda b: ArgsGroupB(**b)),  # option2. use default kwarg
):
    print(f"got args_a: {args_a}")
    print(f"got args_b: {args_b}")
    time.sleep(0.5)


if __name__ == "__main__":
    main()
