import time
from dataclasses import dataclass

import labtasker


@dataclass
class ArgsGroupA:
    a: int
    b: str


@dataclass
class ArgsGroupB:
    foo: int
    bar: str


@labtasker.loop(required_fields=["args_a", "args_b"], pass_args_dict=True)
def main(args):
    args_a = ArgsGroupA(**args["args_a"])
    args_b = ArgsGroupB(**args["args_b"])
    print(f"got args_a: {args_a}")
    print(f"got args_b: {args_b}")
    time.sleep(0.5)


if __name__ == "__main__":
    main()
