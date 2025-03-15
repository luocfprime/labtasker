"""
Tests for the datetime_now_checker.py script.

These tests verify that the script correctly detects various patterns of
datetime.now() usage while allowing legitimate datetime usages.
"""

import ast
import subprocess
import sys
from pathlib import Path

# Add the scripts directory to the Python path
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
sys.path.append(str(scripts_dir))

import datetime_now_checker  # noqa


class TestBanDatetimeNow:
    """Test cases for the datetime_now_checker.py script."""

    # Paths to test files
    SCRIPT_PATH = scripts_dir / "datetime_now_checker.py"
    TEST_DIR = Path(__file__).parent
    DISALLOWED_FILE = TEST_DIR / "disallowed.py"
    ALLOWED_FILE = TEST_DIR / "allowed.py"

    def test_script_exists(self):
        """Test that the script file exists."""
        assert self.SCRIPT_PATH.exists(), f"Script not found at {self.SCRIPT_PATH}"

    def test_command_line_execution(self):
        """Test running the script via command line on the disallowed file."""
        # This should detect prohibited calls and return non-zero exit code
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), str(self.DISALLOWED_FILE)],
            capture_output=True,
            text=True,
        )
        # The script should fail (return code > 0) when it finds prohibited calls
        assert result.returncode != 0, "Script should fail when finding banned calls"
        # Check that the output mentions datetime.now
        assert "now()" in result.stdout, "Output should mention datetime.now()"
        # Check that it detects utcnow as well
        assert "utcnow()" in result.stdout, "Output should mention utcnow()"

    def test_command_line_allowed_file(self):
        """Test running the script on the file with allowed uses."""
        # This should not detect any prohibited calls
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), str(self.ALLOWED_FILE)],
            capture_output=True,
            text=True,
        )
        # The script should pass (return code 0) when no prohibited calls are found
        assert result.returncode == 0, "Script should pass with allowed calls"
        assert "Check passed" in result.stdout, "Output should indicate success"

    def test_exclude_option(self):
        """Test the --exclude option."""
        # Exclude the disallowed file and verify it passes
        result = subprocess.run(
            [
                sys.executable,
                str(self.SCRIPT_PATH),
                "--exclude",
                "disallowed.py",
                str(self.DISALLOWED_FILE),
            ],
            capture_output=True,
            text=True,
        )
        # Should pass because we're excluding the file with violations
        assert (
            result.returncode == 0
        ), "Script should pass when excluding violating file"

    def test_direct_api_detect_now(self):
        """Test direct API usage detecting now() calls."""
        # Create a checker and check the disallowed file
        banned_methods = {
            "now": "Please use utils.time_util.get_current_time() instead",
            "utcnow": "Please use utils.time_util.get_current_utc_time() instead",
        }
        checker = datetime_now_checker.DatetimeNowChecker(banned_methods, [])
        result = checker.check_file(str(self.DISALLOWED_FILE))
        # Should detect banned calls and return False
        assert result is False, "Checker should detect banned calls in disallowed file"

    def test_should_exclude(self):
        """Test the should_exclude method."""
        checker = datetime_now_checker.DatetimeNowChecker({}, ["disallowed"])
        # Should exclude paths containing "disallowed"
        assert checker.should_exclude(str(self.DISALLOWED_FILE)) is True
        # Should not exclude other paths
        assert checker.should_exclude(str(self.ALLOWED_FILE)) is False

    def test_check_directory_with_exclusion(self):
        """Test checking a directory with exclusions."""
        banned_methods = {
            "now": "Please use utils.time_util.get_current_time() instead",
            "utcnow": "Please use utils.time_util.get_current_utc_time() instead",
        }
        # Exclude the disallowed.py file
        checker = datetime_now_checker.DatetimeNowChecker(
            banned_methods, ["disallowed.py"]
        )
        result = checker.check_directory(str(self.TEST_DIR))
        # Should not detect any banned calls after exclusion
        assert result is True, "Directory check with exclusion should pass"

    def test_all_patterns_detected(self):
        """Test that all patterns in disallowed.py are detected."""
        # This test ensures all our patterns are actually caught
        banned_methods = {
            "now": "Please use utils.time_util.get_current_time() instead",
            "utcnow": "Please use utils.time_util.get_current_utc_time() instead",
        }
        checker = datetime_now_checker.DatetimeNowChecker(banned_methods, [])

        # Parse the file to get all function names
        with open(str(self.DISALLOWED_FILE), "r") as f:
            tree = ast.parse(f.read())

        # Get all function definitions
        function_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("pattern")
        ]

        # Check that we have at least 10 patterns to test
        assert len(function_names) >= 10, "Not enough test patterns defined"

        # Check that the checker detects violations
        result = checker.check_file(str(self.DISALLOWED_FILE))
        assert result is False, "Checker should detect banned calls in all patterns"
