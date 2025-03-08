import labtasker

if __name__ == "__main__":
    for arg1 in range(3):
        for arg2 in range(3, 6):
            print(f"Submitting with arg1={arg1}, arg2={arg2}")
            labtasker.submit_task(
                args={"arg1": arg1, "arg2": arg2},
            )
