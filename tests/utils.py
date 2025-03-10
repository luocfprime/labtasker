import time


def high_precision_sleep(duration):
    start_time = time.perf_counter()
    while True:
        elapsed_time = time.perf_counter() - start_time
        remaining_time = duration - elapsed_time
        if remaining_time <= 0:
            break
        if remaining_time > 0.02:  # Sleep for 5ms if remaining time is greater
            time.sleep(
                max(remaining_time / 2, 0.0001)
            )  # Sleep for the remaining time or minimum sleep interval
        else:
            pass
