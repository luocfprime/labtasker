import re
from typing import Callable, List, Tuple, Union

import pytest
import typer


@pytest.fixture
def mock_editor():
    """
    Create a mock editor fixture that supports multiple editing modes:
    - string: directly return the content
    - (pattern, repl): single regex replacement
    - [(pattern1, repl1), ...]: multiple regex replacements
    - callable: custom edit function
    """

    class EditorMock:
        def __init__(self):
            self.edit_operations: Union[
                str, Tuple[str, str], List[Tuple[str, str]], Callable
            ] = ""
            self.call_count = 0

        def configure(self, operations):
            """Configure edit operations"""
            self.edit_operations = operations
            self.call_count = 0

        def edit(self, filename=None, editor=None) -> None:
            """Simulate edit operation"""
            self.call_count += 1

            if filename:
                with open(filename, "r") as f:
                    content = f.read()
            else:
                content = ""

            if isinstance(self.edit_operations, str):
                result = self.edit_operations
            elif isinstance(self.edit_operations, tuple):
                pattern, repl = self.edit_operations
                result = re.sub(pattern, repl, content)
            elif isinstance(self.edit_operations, list):
                result = content
                for pattern, repl in self.edit_operations:
                    result = re.sub(pattern, repl, result)
                result = result
            elif callable(self.edit_operations):
                result = self.edit_operations(content, filename, editor)
            else:
                raise RuntimeError(f"Invalid edit_operations: {self.edit_operations}")

            if filename:
                with open(filename, "w") as f:
                    f.write(result)

    return EditorMock()


@pytest.fixture
def setup_editor(mock_editor, monkeypatch):
    """Setup mock editor by patching click.edit"""
    monkeypatch.setattr("click.edit", mock_editor.edit)
    return mock_editor


@pytest.fixture
def mock_confirm():
    """
    Create a mock confirm fixture that supports:
    - List[bool]: handle multiple confirms in sequence

    Usage:
        mock_confirm([True, False])
    """

    class ConfirmMock:
        def __init__(self):
            self.inputs: List[bool] = []
            self.call_count: int = 0

        def configure(self, inputs: Union[bool, List[bool]], call_count: int = 0):
            """Configure confirm responses"""
            self.inputs = [inputs] if isinstance(inputs, bool) else inputs
            self.call_count = call_count

        def confirm(self, text: str = "y", abort: bool = False, **kwargs) -> bool:
            """
            Mock typer.confirm with sequence of responses

            Args:
                text: Message
                abort: Whether to abort on cancel
            """
            typer.echo(text)
            if self.call_count >= len(self.inputs):
                raise IndexError(
                    f"Not enough confirm inputs configured. "
                    f"Called {self.call_count + 1} times but only {len(self.inputs)} inputs provided."
                )

            confirm = self.inputs[self.call_count]
            self.call_count += 1

            if abort and not confirm:
                raise typer.Abort()

            return confirm

    return ConfirmMock()


@pytest.fixture
def setup_confirm(mock_confirm, monkeypatch):
    """Setup mock confirm by patching typer.confirm"""
    monkeypatch.setattr("typer.confirm", mock_confirm.confirm)
    return mock_confirm
