"""
Ban datetime.now() Checker - Detects and prohibits datetime.now() method calls in Python code

This script checks Python files for calls to datetime.now() and related methods,
while excluding specified paths.

Usage:
    ./datetime_now_checker.py [options] <file_or_directory_paths>...
"""

import argparse
import ast
import os
import sys
from typing import Dict, List, Optional, Set


class DatetimeNowChecker:
    def __init__(self, banned_methods: Dict[str, str], excluded_paths: List[str]):
        """
        Initialize the checker

        Args:
            banned_methods: Dictionary with method names as keys and replacement suggestions as values
            excluded_paths: List of path fragments to exclude from checking
        """
        self.banned_methods = banned_methods
        self.excluded_paths = excluded_paths

    def should_exclude(self, file_path: str) -> bool:
        """Check if a file path should be excluded from analysis"""
        normalized_path = os.path.normpath(file_path).replace("\\", "/")
        return any(excluded in normalized_path for excluded in self.excluded_paths)

    def check_file(self, file_path: str) -> bool:
        """Check a single file, returns True if passes check"""
        if not file_path.endswith(".py"):
            return True

        if self.should_exclude(file_path):
            return True

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            visitor = DatetimeMethodVisitor(self.banned_methods)
            visitor.visit(tree)

            if visitor.violations:
                print(f"\nFile: {file_path}")
                for line, method, message in visitor.violations:
                    print(f"  Line {line}: Use of '{method}' is prohibited - {message}")
                return False
            return True

        except SyntaxError as e:
            print(f"Syntax error in {file_path}: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Error checking file {file_path}: {e}", file=sys.stderr)
            return False

    def check_directory(
        self, directory: str, exclude_dirs: Optional[Set[str]] = None
    ) -> bool:
        """Recursively check all Python files in a directory"""
        if exclude_dirs is None:
            exclude_dirs = {
                ".git",
                ".venv",
                "venv",
                ".tox",
                "__pycache__",
                "node_modules",
            }

        all_passing = True
        for root, dirs, files in os.walk(directory):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    if not self.check_file(file_path):
                        all_passing = False

        return all_passing

    def check_paths(self, paths: List[str]) -> bool:
        """Check a list of file or directory paths"""
        all_passing = True

        for path in paths:
            if os.path.isfile(path):
                if not self.check_file(path):
                    all_passing = False
            elif os.path.isdir(path):
                if not self.check_directory(path):
                    all_passing = False
            else:
                print(f"Warning: Path does not exist {path}", file=sys.stderr)

        return all_passing


class DatetimeMethodVisitor(ast.NodeVisitor):
    """AST visitor to find datetime method calls by focusing on the methods themselves"""

    def __init__(self, banned_methods: Dict[str, str]):
        self.banned_methods = banned_methods
        self.violations = []  # [(line_number, method_name, error_message)]

        # Track datetime related imports
        self.datetime_imports = (
            set()
        )  # Names that directly refer to the datetime module
        self.datetime_class_imports = (
            set()
        )  # Names that refer to the datetime.datetime class

    def visit_Import(self, node):
        """Process import statements to track datetime imports"""
        for name in node.names:
            module_name = name.name
            alias = name.asname or module_name

            # Track imports of datetime module
            if module_name == "datetime" or module_name.startswith("datetime."):
                self.datetime_imports.add(alias)

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Process from-import statements to track datetime imports"""
        if node.module == "datetime":
            for name in node.names:
                import_name = name.name
                alias = name.asname or import_name

                # Track imports of datetime.datetime class
                if import_name == "datetime":
                    self.datetime_class_imports.add(alias)

        self.generic_visit(node)

    def is_datetime_attribute_access(self, node):
        """Determine if node represents accessing a datetime attribute"""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            # Check direct datetime module usage: datetime.method()
            if node.value.id in self.datetime_imports:
                return True

            # Check datetime class usage: dt.method()
            if node.value.id in self.datetime_class_imports:
                return True

        # Check nested access: datetime.datetime.method()
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in self.datetime_imports
            and node.value.attr == "datetime"
        ):
            return True

        return False

    def visit_Call(self, node):
        """Check for calls to banned datetime methods"""
        if isinstance(node.func, ast.Attribute) and self.is_datetime_attribute_access(
            node.func
        ):
            method_name = node.func.attr

            if method_name in self.banned_methods:
                self.violations.append(
                    (
                        node.lineno,
                        f"datetime.{method_name}()",
                        self.banned_methods[method_name],
                    )
                )

        self.generic_visit(node)


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Check Python files for prohibited datetime.now() calls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./datetime_now_checker.py file.py
  ./datetime_now_checker.py src/ tests/
  ./datetime_now_checker.py --exclude "vendor,third_party" .
  ./datetime_now_checker.py --exclude-dirs "node_modules,build" --verbose .
""",
    )

    parser.add_argument("paths", nargs="+", help="Files or directories to check")
    parser.add_argument(
        "--exclude",
        default="labtasker/utils.py",
        help="Comma-separated list of path fragments to exclude (default: labtasker/utils.py)",
    )
    parser.add_argument(
        "--exclude-dirs",
        default=".git,.venv,venv,.tox,__pycache__,node_modules",
        help="Comma-separated list of directories to exclude when walking directories",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show more detailed output"
    )

    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()

    # Define banned methods directly - no redundancy
    banned_methods = {
        "now": "Please use utils.time_util.get_current_time() instead",
        "utcnow": "Please use utils.time_util.get_current_utc_time() instead",
    }

    # Process excluded paths
    excluded_paths = [path.strip() for path in args.exclude.split(",") if path.strip()]
    exclude_dirs = {dir.strip() for dir in args.exclude_dirs.split(",") if dir.strip()}

    if args.verbose:
        print("Checking for banned datetime methods:")
        for method, replacement in banned_methods.items():
            print(f"  - datetime.{method}() - {replacement}")
        print(f"Excluded paths: {excluded_paths}")
        print(f"Excluded directories: {exclude_dirs}")
        print(f"Checking paths: {args.paths}")

    # Create and run the checker
    checker = DatetimeNowChecker(banned_methods, excluded_paths)
    all_passing = True

    for path in args.paths:
        if os.path.isfile(path):
            if not checker.check_file(path):
                all_passing = False
        elif os.path.isdir(path):
            if not checker.check_directory(path, exclude_dirs):
                all_passing = False
        else:
            print(f"Warning: Path does not exist {path}", file=sys.stderr)

    if all_passing:
        print("\n✅ Check passed: No prohibited datetime method calls found")
        sys.exit(0)
    else:
        print("\n❌ Check failed: Prohibited datetime method calls found")
        sys.exit(1)


if __name__ == "__main__":
    main()
