import concurrent.futures
import sys
import time

import pytest

from labtasker.client.core.logging import log_to_file, logger

pytestmark = [pytest.mark.unit]


@pytest.fixture
def temp_log_file(tmp_path):
    """Create a temporary log file for testing."""
    return tmp_path / "test_log.log"


def test_log_to_file(temp_log_file):
    """
    Test that logger, stdout and stderr are redirected into a log file.
    Notes:     Do not use capsys or capture_output
    """
    with log_to_file(temp_log_file):
        print("Test stdout w.")
        print("Test stderr w.", file=sys.stderr)
        logger.info("Test logger w.")

    # Check the log file
    with open(temp_log_file, "r") as f:
        log_content = f.read()
        assert "Test stdout w." in log_content
        assert "Test stderr w." in log_content
        assert "Test logger w." in log_content

    # Check that without the ctx manager, the output goes to the console only
    print("Test stdout wo.")
    print("Test stderr wo.", file=sys.stderr)
    logger.info("Test logger wo.")

    with open(temp_log_file, "r") as f:
        log_content = f.read()
        assert "Test stdout wo." not in log_content
        assert "Test stderr wo." not in log_content
        assert "Test logger wo." not in log_content


def test_concurrent_log_to_file(tmp_path):
    """
    Test that log_to_file works correctly in a concurrent environment.
    Each thread gets its own context ID and we verify isolation.
    """
    # Create a temp log file for each thread
    log_files = [tmp_path / f"log_thread_{i}.txt" for i in range(5)]

    # Function that each thread will run
    def thread_task(thread_id, log_file):
        context_id = f"CTX-{thread_id}"

        # With context manager (should log to file)
        with log_to_file(log_file):
            print(f"{context_id}: Test stdout with context")
            print(f"{context_id}: Test stderr with context", file=sys.stderr)
            logger.info(f"{context_id}: Test logger with context")
            time.sleep(0.1)  # Simulate some work

        # Without context manager (should not log to file)
        print(f"{context_id}: Test stdout without context")
        print(f"{context_id}: Test stderr without context", file=sys.stderr)
        logger.info(f"{context_id}: Test logger without context")

        return thread_id, log_file

    # Run tasks concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(thread_task, i, log_file)
            for i, log_file in enumerate(log_files)
        ]

        # Wait for all tasks to complete
        for future in concurrent.futures.as_completed(futures):
            thread_id, log_file = future.result()

            # Verify log file contents
            with open(log_file, "r") as f:
                log_content = f.read()

                # Context ID for this thread
                context_id = f"CTX-{thread_id}"

                # Should contain "with context" messages
                assert f"{context_id}: Test stdout with context" in log_content
                assert f"{context_id}: Test stderr with context" in log_content
                assert f"{context_id}: Test logger with context" in log_content

                # Should NOT contain "without context" messages
                assert f"{context_id}: Test stdout without context" not in log_content
                assert f"{context_id}: Test stderr without context" not in log_content
                assert f"{context_id}: Test logger without context" not in log_content

                # Should NOT contain other threads' context IDs
                for other_id in range(5):
                    if other_id != thread_id:
                        other_context_id = f"CTX-{other_id}"
                        assert other_context_id not in log_content


def test_nested_log_to_file(tmp_path):
    """
    Test that nested log_to_file contexts work correctly.
    Each level should get its own unique context ID.
    """
    outer_log_file = tmp_path / "outer.log"
    inner_log_file = tmp_path / "inner.log"

    # Use nested context managers
    with log_to_file(outer_log_file):
        print("OUTER: Test stdout outer")
        print("OUTER: Test stderr outer", file=sys.stderr)
        logger.info("OUTER: Test logger outer")

        # Nested context
        with log_to_file(inner_log_file):
            print("INNER: Test stdout inner")
            print("INNER: Test stderr inner", file=sys.stderr)
            logger.info("INNER: Test logger inner")

        # Back to outer context
        print("OUTER: Test stdout outer again")
        logger.info("OUTER: Test logger outer again")

    # Verify outer log file
    with open(outer_log_file, "r") as f:
        outer_content = f.read()
        # Should contain outer context messages
        assert "OUTER: Test stdout outer" in outer_content
        assert "OUTER: Test stderr outer" in outer_content
        assert "OUTER: Test logger outer" in outer_content
        assert "OUTER: Test stdout outer again" in outer_content
        assert "OUTER: Test logger outer again" in outer_content

        # Should also contain inner context messages (outer was active)
        assert "INNER: Test stdout inner" in outer_content
        assert "INNER: Test stderr inner" in outer_content
        assert "INNER: Test logger inner" in outer_content

    # Verify inner log file
    with open(inner_log_file, "r") as f:
        inner_content = f.read()
        # Should contain inner context messages
        assert "INNER: Test stdout inner" in inner_content
        assert "INNER: Test stderr inner" in inner_content
        assert "INNER: Test logger inner" in inner_content

        # Should NOT contain outer-only messages
        assert "OUTER: Test stdout outer again" not in inner_content
        assert "OUTER: Test logger outer again" not in inner_content


def test_exception_in_log_to_file(tmp_path):
    """
    Test that log_to_file correctly handles exceptions and cleans up resources.
    """
    log_file = tmp_path / "exception.log"
    exception_raised = False

    try:
        with log_to_file(log_file):
            print("EXCEPTION: Before exception")
            logger.info("EXCEPTION: Logger before exception")
            # Raise an exception
            raise ValueError("Intentional test exception")
    except ValueError:
        exception_raised = True

        # Check that normal logging still works after exception
        print("EXCEPTION: After exception")
        logger.info("EXCEPTION: Logger after exception")

    assert exception_raised, "Exception should have been raised and caught"

    # Verify log file
    with open(log_file, "r") as f:
        log_content = f.read()
        # Should contain pre-exception messages
        assert "EXCEPTION: Before exception" in log_content
        assert "EXCEPTION: Logger before exception" in log_content

        # Should NOT contain post-exception messages
        assert "EXCEPTION: After exception" not in log_content
        assert "EXCEPTION: Logger after exception" not in log_content


def test_concurrent_mixed_contexts(tmp_path):
    """
    Test multiple threads using different log files and contexts at different times.
    """
    shared_log = tmp_path / "shared.log"
    individual_logs = [tmp_path / f"individual_{i}.log" for i in range(3)]

    def thread_worker(thread_id):
        # Each thread has a unique prefix
        prefix = f"T{thread_id}"

        # First use thread-specific log
        with log_to_file(individual_logs[thread_id]):
            print(f"{prefix}: Individual log entry 1")
            logger.info(f"{prefix}: Individual logger entry 1")
            time.sleep(0.05)

        # Then use shared log
        with log_to_file(shared_log):
            print(f"{prefix}: Shared log entry 1")
            logger.info(f"{prefix}: Shared logger entry 1")
            time.sleep(0.05)

        # Back to individual log
        with log_to_file(individual_logs[thread_id]):
            print(f"{prefix}: Individual log entry 2")
            logger.info(f"{prefix}: Individual logger entry 2")

        # One more shared log entry
        with log_to_file(shared_log):
            print(f"{prefix}: Shared log entry 2")
            logger.info(f"{prefix}: Shared logger entry 2")

        return thread_id

    # Use ThreadPoolExecutor instead of manual thread management
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        # Submit tasks and get futures
        futures = [executor.submit(thread_worker, i) for i in range(3)]

        # Wait for all tasks to complete
        for future in concurrent.futures.as_completed(futures):
            # Get result (thread_id) but we don't need to use it here
            _ = future.result()

    # Verify individual log files
    for i, log_file in enumerate(individual_logs):
        prefix = f"T{i}"
        with open(log_file, "r") as f:
            content = f.read()

            # Should contain this thread's entries
            assert f"{prefix}: Individual log entry 1" in content
            assert f"{prefix}: Individual logger entry 1" in content
            assert f"{prefix}: Individual log entry 2" in content
            assert f"{prefix}: Individual logger entry 2" in content

            # Should NOT contain shared log entries
            assert f"{prefix}: Shared log entry 1" not in content
            assert f"{prefix}: Shared logger entry 1" not in content
            assert f"{prefix}: Shared log entry 2" not in content
            assert f"{prefix}: Shared logger entry 2" not in content

            # Should NOT contain other threads' entries
            for j in range(3):
                if j != i:
                    other_prefix = f"T{j}"
                    assert other_prefix not in content

    # Verify shared log file
    with open(shared_log, "r") as f:
        content = f.read()

        # Should contain all threads' shared entries
        for i in range(3):
            prefix = f"T{i}"
            assert f"{prefix}: Shared log entry 1" in content
            assert f"{prefix}: Shared logger entry 1" in content
            assert f"{prefix}: Shared log entry 2" in content
            assert f"{prefix}: Shared logger entry 2" in content

            # Should NOT contain individual log entries
            assert f"{prefix}: Individual log entry 1" not in content
            assert f"{prefix}: Individual logger entry 1" not in content
            assert f"{prefix}: Individual log entry 2" not in content
            assert f"{prefix}: Individual logger entry 2" not in content
