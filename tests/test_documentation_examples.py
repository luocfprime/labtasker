from __future__ import annotations

import ast
import re
import shlex
import shutil
import subprocess
import textwrap
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labtasker.cli import app as client_app
from labtasker_server.cli import app as server_app

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MARKDOWN = (
    ROOT / "README.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "skills/labtasker").rglob("*.md")),
)
SHELL_LANGUAGES = {"bash", "sh", "shell"}
ZENSICAL = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))
SNIPPET_BASE_PATHS = tuple(
    ROOT / path
    for path in ZENSICAL["project"]["markdown_extensions"]["pymdownx"]["snippets"]["base_path"]
)


@dataclass(frozen=True)
class Fence:
    path: Path
    line: int
    language: str
    body: str


def fences(path: Path) -> list[Fence]:
    result: list[Fence] = []
    opening: tuple[int, str] | None = None
    body: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        if opening is None:
            if stripped.startswith("```"):
                info = stripped[3:].strip()
                language = info.split(maxsplit=1)[0] if info else ""
                opening = (line_number, language)
                body = []
            continue
        if stripped == "```":
            result.append(
                Fence(
                    path=path,
                    line=opening[0],
                    language=opening[1],
                    body=textwrap.dedent("\n".join(body)) + "\n",
                )
            )
            opening = None
            body = []
        else:
            body.append(line)
    assert opening is None, f"Unclosed code fence in {path}:{opening[0]}"
    return result


def test_public_python_and_shell_blocks_have_valid_syntax() -> None:
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required to validate documented shell examples."
    checked_python = 0
    checked_shell = 0
    for path in PUBLIC_MARKDOWN:
        for fence in fences(path):
            if "--8<--" in fence.body:
                continue
            location = f"{fence.path.relative_to(ROOT)}:{fence.line}"
            if fence.language == "python":
                try:
                    ast.parse(fence.body, filename=location)
                except SyntaxError as error:
                    pytest.fail(f"Invalid documented Python at {location}: {error}")
                checked_python += 1
            elif fence.language in SHELL_LANGUAGES:
                result = subprocess.run(
                    [bash, "-n"],
                    input=fence.body,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                assert result.returncode == 0, f"Invalid shell at {location}: {result.stderr}"
                checked_shell += 1
    assert checked_python >= 35
    assert checked_shell >= 50


def test_document_snippets_and_relative_links_resolve() -> None:
    markdown_link = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
    snippet = re.compile(r'--8<--\s+"([^"]+)"')
    for path in PUBLIC_MARKDOWN:
        text = path.read_text(encoding="utf-8")
        for target in markdown_link.findall(text):
            target = target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#", "/")):
                continue
            relative = target.split("#", 1)[0]
            if relative:
                resolved = (path.parent / relative).resolve()
                assert resolved.exists(), f"Broken link in {path.relative_to(ROOT)}: {target}"
        for target in snippet.findall(text):
            resolved = next(
                (base / target for base in SNIPPET_BASE_PATHS if (base / target).is_file()),
                None,
            )
            assert resolved is not None, f"Broken snippet in {path.relative_to(ROOT)}: {target}"

    for path in sorted((ROOT / "docs/snippets").rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bash = shutil.which("bash")
    assert bash is not None
    for path in sorted((ROOT / "docs/snippets").rglob("*.sh")):
        result = subprocess.run([bash, "-n", path], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"Invalid shell snippet {path}: {result.stderr}"


def logical_lines(body: str) -> list[str]:
    result: list[str] = []
    pending = ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pending += line[:-1].rstrip() + " " if line.endswith("\\") else line
        if not line.endswith("\\"):
            result.append(pending.strip())
            pending = ""
    if pending:
        result.append(pending.strip())
    return result


def documented_labtasker_commands() -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    for path in PUBLIC_MARKDOWN:
        for fence in fences(path):
            if fence.language not in SHELL_LANGUAGES | {"text"} or "--8<--" in fence.body:
                continue
            location = f"{path.relative_to(ROOT)}:{fence.line}"
            for line in logical_lines(fence.body):
                if "labtasker" in line:
                    commands.append((location, line))

    for source_root in (
        ROOT / "packages/labtasker-client/src",
        ROOT / "packages/labtasker-server/src",
    ):
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                docstring = ast.get_docstring(node)
                if docstring is None:
                    continue
                location = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 1)}"
                for line in logical_lines(docstring.replace("\x08", "")):
                    if "labtasker" in line:
                        commands.append((location, line))
    return commands


@lru_cache
def command_help(executable: str, command_path: tuple[str, ...]) -> str:
    app = client_app if executable == "labtasker" else server_app
    result = CliRunner().invoke(app, [*command_path, "--help"])
    assert result.exit_code == 0, result.stderr
    return result.stdout


def test_documented_cli_options_exist_on_the_real_commands() -> None:
    checked = 0
    for location, line in documented_labtasker_commands():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as error:
            pytest.fail(f"Invalid documented command at {location}: {error}")
        while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
            tokens.pop(0)
        if tokens[:2] == ["uv", "run"]:
            tokens = tokens[2:]
        if not tokens or tokens[0] not in {"labtasker", "labtasker-server"}:
            continue
        executable = tokens.pop(0)
        if not tokens:
            continue
        valid_top_level = (
            {"loop", "task", "queue", "config"}
            if executable == "labtasker"
            else {"serve", "start", "status", "stop", "logs"}
        )
        if tokens[0] not in valid_top_level:
            continue
        depth = 2 if executable == "labtasker" and tokens[0] in {"task", "queue", "config"} else 1
        if len(tokens) < depth:
            continue
        leaves = {
            "task": {"submit", "get", "list", "count", "update", "cancel", "requeue", "delete"},
            "queue": {"create", "list", "delete"},
            "config": {"show"},
        }
        if depth == 2 and tokens[1] not in leaves[tokens[0]]:
            continue
        command_path = tuple(tokens[:depth])
        arguments = tokens[depth:]
        if "--" in arguments:
            arguments = arguments[: arguments.index("--")]
        help_text = command_help(executable, command_path)
        documented_options = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", help_text))
        for argument in arguments:
            if not argument.startswith("--"):
                continue
            option = argument.split("=", 1)[0]
            assert option in documented_options, f"Unknown option {option} at {location}: {line}"
        checked += 1
    assert checked >= 35
