from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text

from labtasker_server.config import ServerSettings
from labtasker_server.database import Database, DatabaseOwnershipError
from labtasker_server.errors import DomainError
from labtasker_server.local import local_paths, try_acquire_database
from labtasker_server.services.queues import QueueService


def test_database_creates_gitignore_for_labtasker_state_directory(tmp_path: Path) -> None:
    database = Database(tmp_path / ".labtasker/data/server.db")
    try:
        assert (tmp_path / ".labtasker/.gitignore").read_text() == "*\n!.gitignore\n"
    finally:
        database.dispose()


def test_database_has_one_process_owner_and_releases_on_dispose(tmp_path: Path) -> None:
    path = tmp_path / "server.db"
    first = Database(path)
    try:
        with pytest.raises(DatabaseOwnershipError, match="already owns database"):
            Database(path)
    finally:
        first.dispose()

    replacement = Database(path)
    replacement.dispose()


@pytest.mark.skipif(os.name != "posix", reason="Requires descriptor inheritance")
@pytest.mark.parametrize("crash", [False, True])
def test_database_ownership_survives_exec_and_sqlite_connection_close(
    tmp_path: Path, crash: bool
) -> None:
    paths = local_paths(tmp_path)
    fd = try_acquire_database(paths)
    assert fd is not None
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import os, sys
from pathlib import Path
from labtasker_server.database import Database
fd = int(sys.argv[2])
database = Database(Path(sys.argv[1]), ownership_fd=fd)
os.close(fd)
database.initialize()
print('ready', flush=True)
sys.stdin.readline()
database.dispose()
""",
            str(paths.database),
            str(fd),
        ],
        pass_fds=(fd,),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(fd)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        # Ordinary SQLite handles may open/close without releasing ownership.
        connection = sqlite3.connect(paths.database)
        assert connection.execute("SELECT name FROM queues").fetchall() == [("default",)]
        connection.close()
        alias = tmp_path / "alias.db"
        os.link(paths.database, alias)
        for path in (paths.database, alias):
            with pytest.raises(DatabaseOwnershipError):
                Database(path)
        assert try_acquire_database(paths) is None
        if crash:
            process.kill()
        else:
            assert process.stdin is not None
            process.stdin.write("exit\n")
            process.stdin.flush()
        process.communicate(timeout=5)
        replacement = Database(paths.database)
        replacement.dispose()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("service", ["TaskService", "WorkerService"])
def test_failed_startup_scan_releases_database_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    from labtasker_server.app import create_app

    def fail(*_: object) -> None:
        raise RuntimeError("injected scan failure")

    method = "expire_leases" if service == "TaskService" else "expire"
    settings = ServerSettings(database=tmp_path / "server.db")
    with monkeypatch.context() as patch:
        patch.setattr(f"labtasker_server.app.{service}.{method}", fail)
        with pytest.raises(RuntimeError, match="injected scan failure"):
            create_app(settings)
    app = create_app(settings)
    app.state.database.dispose()


def test_engine_construction_failure_releases_database_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise RuntimeError("injected engine failure")

    path = tmp_path / "server.db"
    with monkeypatch.context() as patch:
        patch.setattr("labtasker_server.database._create_sqlite_engine", fail)
        with pytest.raises(RuntimeError, match="injected engine failure"):
            Database(path)
    replacement = Database(path)
    replacement.dispose()


def test_engine_disposal_failure_still_releases_database_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> None:
        raise RuntimeError("injected disposal failure")

    path = tmp_path / "server.db"
    database = Database(path)
    monkeypatch.setattr(database.engine, "dispose", fail)
    with pytest.raises(RuntimeError, match="injected disposal failure"):
        database.dispose()
    replacement = Database(path)
    replacement.dispose()


def test_database_preserves_existing_gitignore_and_ignores_other_parents(
    tmp_path: Path,
) -> None:
    labtasker_dir = tmp_path / ".labtasker"
    labtasker_dir.mkdir()
    gitignore = labtasker_dir / ".gitignore"
    gitignore.write_text("server.db*\n")

    local_database = Database(labtasker_dir / "server.db")
    custom_database = Database(tmp_path / "custom/server.db")
    try:
        assert gitignore.read_text() == "server.db*\n"
        assert not (tmp_path / "custom/.gitignore").exists()
    finally:
        local_database.dispose()
        custom_database.dispose()


def test_fresh_database_has_migrated_schema_default_queue_and_pragmas(
    database_path: Path,
) -> None:
    database = Database(database_path)
    database.initialize()
    try:
        assert set(inspect(database.engine).get_table_names()) == {
            "alembic_version",
            "queues",
            "task_routes",
            "tasks",
            "workers",
        }
        assert {index["name"] for index in inspect(database.engine).get_indexes("tasks")} == {
            "ix_tasks_claim",
            "ix_tasks_default_list",
            "ix_tasks_expiry",
            "ix_tasks_status_list",
            "ix_tasks_terminal_run_id",
            "uq_tasks_active_run_id",
        }
        with database.read_session() as session:
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0002_worker_observations"
            )
            assert session.scalars(text("SELECT name FROM queues")).all() == ["default"]
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
            assert session.scalar(text("PRAGMA journal_mode")) == "wal"
            assert session.scalar(text("PRAGMA synchronous")) == 2
            assert session.scalar(text("PRAGMA busy_timeout")) == 5000
    finally:
        database.dispose()


def test_deleted_default_queue_is_not_recreated_on_restart(database_path: Path) -> None:
    first = Database(database_path)
    first.initialize()
    QueueService(first).delete("default", cascade=False)
    first.dispose()

    second = Database(database_path)
    second.initialize()
    try:
        assert QueueService(second).list() == []
    finally:
        second.dispose()


def test_existing_unknown_schema_is_rejected(database_path: Path) -> None:
    database = Database(database_path)
    with database.engine.begin() as connection:
        connection.execute(text("CREATE TABLE unrelated (value INTEGER)"))

    with pytest.raises(RuntimeError, match="not a recognized Labtasker v2 schema"):
        database.initialize()
    database.dispose()


def test_unknown_newer_alembic_revision_is_rejected(database_path: Path) -> None:
    first = Database(database_path)
    first.initialize()
    with first.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999_newer'"))
    first.dispose()

    second = Database(database_path)
    with pytest.raises(CommandError, match="9999_newer"):
        second.initialize()
    second.dispose()


def test_migration_failure_aborts_initialization(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(database_path)

    def fail_upgrade(*_: object, **__: object) -> None:
        raise RuntimeError("migration failed")

    monkeypatch.setattr("labtasker_server.database.command.upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="migration failed"):
        database.initialize()
    assert "queues" not in inspect(database.engine).get_table_names()
    database.dispose()


def test_write_lock_timeout_maps_to_database_busy(database_path: Path) -> None:
    database = Database(database_path)
    database.initialize()
    with database.engine.connect() as connection:
        connection.execute(text("PRAGMA busy_timeout=1"))

    lock = sqlite3.connect(database_path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DomainError) as raised:
            QueueService(database).create("blocked")
        assert raised.value.status_code == 503
        assert raised.value.code == "database_busy"
    finally:
        lock.rollback()
        lock.close()
        database.dispose()


@pytest.mark.parametrize("host", ["127.0.0.1", "127.3.2.1", "::1", "LOCALHOST"])
def test_tokenless_server_allows_only_loopback_hosts(host: str, tmp_path: Path) -> None:
    settings = ServerSettings.from_values(host=host, database=tmp_path / "db")
    assert settings.token is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "example.test", "192.168.1.2"])
def test_tokenless_server_rejects_non_loopback_hosts(host: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="token is required"):
        ServerSettings.from_values(host=host, database=tmp_path / "db")


def test_server_token_is_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LABTASKER_SERVER_TOKEN", "secret")
    settings = ServerSettings.from_values(host="0.0.0.0", database=tmp_path / "db")
    assert settings.token == "secret"


def test_empty_server_token_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LABTASKER_SERVER_TOKEN", "")
    with pytest.raises(ValueError, match="must not be empty"):
        ServerSettings.from_values(database=tmp_path / "db")


@pytest.mark.parametrize("token", ["秘密", " leading", "trailing ", "line\nbreak", "tab\tvalue"])
def test_server_token_must_be_safe_for_an_http_bearer_header(token: str) -> None:
    with pytest.raises(ValueError, match="visible ASCII"):
        ServerSettings(token=token)
