from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

from labtasker.models import ClaimResponse
from labtasker.types import JSONValue
from labtasker.validation import (
    validate_identifier,
    validate_int64,
    validate_run_id,
    validate_task_id,
)

JournalPhase = Literal["running", "reporting", "acknowledged", "revoked"]
TerminalAction = Literal["complete", "fail", "unclaim"]
LOCAL_GITIGNORE = "*\n!.gitignore\n"


class RunRecord(TypedDict):
    schema_version: int
    server_url: str
    queue: str
    task_id: str
    run_id: str
    route: str
    attempt: int
    started_at: str
    finished_at: str | None
    phase: JournalPhase
    terminal_action: TerminalAction | None
    acknowledged_at: str | None


class LocalRunJournal:
    def __init__(self, run_dir: Path, record: RunRecord) -> None:
        self.run_dir = run_dir
        self._record = record
        self._lock = threading.Lock()

    @classmethod
    def create(
        cls,
        *,
        claim: ClaimResponse,
        server_url: str,
        queue: str,
        route: str,
        cwd: Path | None = None,
    ) -> LocalRunJournal:
        started_at = claim.task.started_at
        if started_at is None:
            raise ValueError("claimed Task is missing started_at")
        root = (Path.cwd() if cwd is None else cwd).resolve()
        task_group = f"{_task_slug(claim.task.name)}__{claim.task.id}"
        run_name = (
            f"{started_at.astimezone(UTC):%Y%m%dT%H%M%SZ}"
            f"__attempt-{claim.task.attempt}__{claim.run_id}"
        )
        labtasker_dir = root / ".labtasker"
        labtasker_dir.mkdir(parents=True, exist_ok=True)
        _ensure_local_gitignore(labtasker_dir)
        run_dir = labtasker_dir / "runs" / queue / task_group / run_name
        run_dir.mkdir(parents=True, exist_ok=False)
        record: RunRecord = {
            "schema_version": 1,
            "server_url": server_url,
            "queue": queue,
            "task_id": claim.task.id,
            "run_id": claim.run_id,
            "route": route,
            "attempt": claim.task.attempt,
            "started_at": _timestamp(started_at),
            "finished_at": None,
            "phase": "running",
            "terminal_action": None,
            "acknowledged_at": None,
        }
        journal = cls(run_dir.resolve(), record)
        _atomic_json(journal.task_path, claim.task.model_dump(mode="json"))
        _atomic_json(journal.run_path, record)
        journal.log_path.touch(exist_ok=False)
        return journal

    @classmethod
    def open(cls, run_dir: Path) -> LocalRunJournal:
        resolved = run_dir.resolve()
        parsed = json.loads((resolved / "run.json").read_text(encoding="utf-8"))
        return cls(resolved, _validate_record(parsed))

    @property
    def server_url(self) -> str:
        return self._record["server_url"]

    @property
    def queue(self) -> str:
        return self._record["queue"]

    @property
    def task_id(self) -> str:
        return self._record["task_id"]

    @property
    def run_id(self) -> str:
        return self._record["run_id"]

    @property
    def route(self) -> str:
        return self._record["route"]

    @property
    def task_path(self) -> Path:
        return self.run_dir / "task.json"

    @property
    def run_path(self) -> Path:
        return self.run_dir / "run.json"

    @property
    def result_path(self) -> Path:
        return self.run_dir / "result.json"

    @property
    def error_path(self) -> Path:
        return self.run_dir / "error.json"

    @property
    def log_path(self) -> Path:
        return self.run_dir / "run.log"

    @property
    def phase(self) -> JournalPhase:
        return self._record["phase"]

    @property
    def terminal_action(self) -> TerminalAction | None:
        return self._record["terminal_action"]

    def read_result(self) -> dict[str, JSONValue]:
        parsed = json.loads(self.result_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("result.json must be an object")
        return cast(dict[str, JSONValue], parsed)

    def reporting(
        self,
        action: TerminalAction,
        payload: dict[str, JSONValue] | None = None,
    ) -> None:
        with self._lock:
            if action == "complete":
                if payload is None:
                    raise ValueError("complete journal entry requires a result")
                _atomic_json_once(self.result_path, payload)
            elif action == "fail":
                if payload is None:
                    raise ValueError("fail journal entry requires an error")
                _atomic_json_once(self.error_path, payload)
            elif payload is not None:
                raise ValueError("unclaim journal entry cannot have a payload")
            self._record["phase"] = "reporting"
            self._record["terminal_action"] = action
            self._record["finished_at"] = None
            self._record["acknowledged_at"] = None
            _atomic_json(self.run_path, self._record)

    def acknowledged(self) -> None:
        now = _timestamp(datetime.now(UTC))
        with self._lock:
            self._record["phase"] = "acknowledged"
            self._record["finished_at"] = now
            self._record["acknowledged_at"] = now
            _atomic_json(self.run_path, self._record)

    def revoked(self) -> None:
        with self._lock:
            self._record["phase"] = "revoked"
            self._record["finished_at"] = _timestamp(datetime.now(UTC))
            self._record["acknowledged_at"] = None
            _atomic_json(self.run_path, self._record)


def _ensure_local_gitignore(labtasker_dir: Path) -> None:
    try:
        with (labtasker_dir / ".gitignore").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(LOCAL_GITIGNORE)
    except FileExistsError:
        pass


def _task_slug(name: str | None) -> str:
    source = name if name else "unnamed"
    characters: list[str] = []
    for character in source:
        if character.isalnum():
            characters.append(character)
        elif characters and characters[-1] != "-":
            characters.append("-")
    slug = "".join(characters).strip("-") or "unnamed"
    encoded = slug.encode("utf-8")
    if len(encoded) <= 80:
        return slug
    prefix = encoded[:80]
    while True:
        try:
            slug = prefix.decode("utf-8").rstrip("-")
            break
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return slug or "unnamed"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_json_once(path: Path, value: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != value:
                raise ValueError(
                    f"{path.name} already contains a different terminal payload"
                ) from None
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_record(value: object) -> RunRecord:
    fields = {
        "schema_version",
        "server_url",
        "queue",
        "task_id",
        "run_id",
        "route",
        "attempt",
        "started_at",
        "finished_at",
        "phase",
        "terminal_action",
        "acknowledged_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("run.json does not match journal schema version 1")
    if value["schema_version"] != 1:
        raise ValueError("run.json uses an unsupported journal schema")
    if not isinstance(value["server_url"], str) or not value["server_url"]:
        raise ValueError("run.json server_url must be a non-empty string")
    validate_identifier(value["queue"], field="queue")
    validate_task_id(value["task_id"])
    validate_run_id(value["run_id"])
    validate_identifier(value["route"], field="route")
    validate_int64(value["attempt"], field="attempt", positive=True)
    for field in ("started_at", "finished_at", "acknowledged_at"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError(f"run.json {field} must be a timestamp string or null")
    if value["phase"] not in {"running", "reporting", "acknowledged", "revoked"}:
        raise ValueError("run.json phase is invalid")
    if value["terminal_action"] not in {None, "complete", "fail", "unclaim"}:
        raise ValueError("run.json terminal_action is invalid")
    return cast(RunRecord, value)
