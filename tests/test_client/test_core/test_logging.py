import sys
from io import StringIO

import pytest
from loguru import logger

from labtasker.client.core.logging import log_to_file

pytestmark = [pytest.mark.unit]


@pytest.fixture
def temp_log_file(tmp_path):
    """Create a temporary log file for testing."""
    return tmp_path / "test_log.log"


def test_log_to_file(temp_log_file):
    # Prepare a StringIO to capture restored stdout
    restored_stdout = StringIO()
    restored_stderr = StringIO()

    # Save the original stdout and stderr for later
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Redirect restored stdout and stderr to StringIO for testing
    sys.stdout = restored_stdout
    sys.stderr = restored_stderr

    try:
        # Use the log_to_file context manager
        with log_to_file(temp_log_file, capture_stdout=True, capture_stderr=True):
            # Generate some output to stdout, stderr, and loguru logger
            print("This is a message to stdout.")
            sys.stderr.write("This is a message to stderr.\n")
            logger.info("This is a loguru log message.")

        # Check the contents of the log file
        with open(temp_log_file, "r") as log_file:
            log_contents = log_file.read()

        assert "This is a message to stdout." in log_contents
        assert "This is a message to stderr." in log_contents
        assert "This is a loguru log message." in log_contents

        # Check that stdout and stderr are restored
        print("stdout is working again.")
        sys.stderr.write("stderr is working again.\n")

        assert "stdout is working again." in restored_stdout.getvalue()
        assert "stderr is working again." in restored_stderr.getvalue()

    finally:
        # Restore original stdout and stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
