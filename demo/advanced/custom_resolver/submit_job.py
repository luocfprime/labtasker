import labtasker

if __name__ == "__main__":
    for i in range(5):
        print(f"Submitting i={i}")
        labtasker.submit_task(
            args={
                "args_a": {"a": i, "b": "boy"},
                "args_b": {"foo": 2 * i, "bar": "baz"},
            }
        )
