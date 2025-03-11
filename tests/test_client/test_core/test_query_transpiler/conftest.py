import sys
from io import StringIO

import pytest


@pytest.fixture(autouse=True)
def test_suppress_stderr():
    """Suppress the stderr produced by parser format print."""
    original_stderr = sys.stderr
    sys.stderr = StringIO()
    try:
        yield
    finally:
        sys.stderr = original_stderr
