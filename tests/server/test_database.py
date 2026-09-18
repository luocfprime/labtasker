from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import event, inspect, text

from labtasker_server.config import ServerSettings
from labtasker_server.database import Database, DatabaseOwnershipError
from labtasker_server.errors import DomainError
from labtasker_server.ownership import lock_database
from labtasker_server.services.queues import QueueService


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


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX advisory locks")
def test_legacy_inode_owner_blocks_local_start_with_deprecation_warning(tmp_path: Path) -> None:
    path = tmp_path / "server.db"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    lock_database(descriptor)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(DatabaseOwnershipError, match=r"legacy v2\.5 or current"):
                Database(path, filesystem="local")
        assert [item.category for item in caught] == [DeprecationWarning]
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX advisory locks")
@pytest.mark.parametrize("crash", [False, True])
def test_database_sidecar_ownership_survives_exec_and_sqlite_connection_close(
    tmp_path: Path, crash: bool
) -> None:
    path = tmp_path / "server.db"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from labtasker_server.database import Database
database = Database(Path(sys.argv[1]))
database.initialize()
print('ready', flush=True)
sys.stdin.readline()
database.dispose()
""",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        # Ordinary SQLite handles may open/close without releasing ownership.
        connection = sqlite3.connect(path)
        assert connection.execute("SELECT name FROM queues").fetchall() == [("default",)]
        connection.close()
        with pytest.raises(DatabaseOwnershipError):
            Database(path)
        symlink = tmp_path / "alias.db"
        symlink.symlink_to(path)
        with pytest.raises(DatabaseOwnershipError):
            Database(symlink)
        if crash:
            process.kill()
        else:
            assert process.stdin is not None
            process.stdin.write("exit\n")
            process.stdin.flush()
        process.communicate(timeout=5)
        replacement = Database(path)
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

    def fail(*_: object, **__: object) -> None:
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


@pytest.mark.parametrize("relative_path", ["queue?one.db", "project?run=1/server.db"])
def test_database_path_is_not_parsed_as_a_url(tmp_path: Path, relative_path: str) -> None:
    path = tmp_path / relative_path
    database = Database(path)
    try:
        database.initialize()
        with database.read_session() as session:
            files = session.execute(text("PRAGMA database_list")).all()
            assert Path(next(row[2] for row in files if row[1] == "main")) == path.resolve()
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("SELECT name FROM queues").fetchall() == [("default",)]
        finally:
            connection.close()
        with pytest.raises(DatabaseOwnershipError):
            Database(path)
    finally:
        database.dispose()


def test_server_package_installed_under_percent_path_can_initialize_and_restart(
    tmp_path: Path,
) -> None:
    import labtasker_server

    package_directory = tmp_path / "100%-environment"
    shutil.copytree(
        Path(labtasker_server.__file__).parent,
        package_directory / "labtasker_server",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    script = """
from pathlib import Path
import labtasker_server
from labtasker_server.database import Database
from labtasker_server.services.queues import QueueService
assert '100%-environment' in labtasker_server.__file__
database = Database(Path('server.db'))
try:
    database.initialize()
    service = QueueService(database)
    if Path('initialized').exists():
        assert [queue.name for queue in service.list()] == ['default', 'persisted']
    else:
        assert [queue.name for queue in service.list()] == ['default']
        service.create('persisted')
        Path('initialized').touch()
finally:
    database.dispose()
"""
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(package_directory)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr


def test_database_does_not_manage_parent_gitignore(
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
        assert {
            "progress_json",
            "progress_updated_at_us",
            "progress_attempt",
        } <= {column["name"] for column in inspect(database.engine).get_columns("tasks")}
        assert {
            "metadata_json",
            "telemetry_json",
            "telemetry_updated_at_us",
        } <= {column["name"] for column in inspect(database.engine).get_columns("workers")}
        assert {
            constraint["name"]
            for constraint in inspect(database.engine).get_check_constraints("tasks")
        } >= {
            "ck_progress_json",
            "ck_tasks_progress_state",
        }
        with database.read_session() as session:
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0004_worker_observability"
            )
            assert session.scalars(text("SELECT name FROM queues")).all() == ["default"]
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
            assert session.scalar(text("PRAGMA journal_mode")) == "wal"
            assert session.scalar(text("PRAGMA synchronous")) == 2
            assert session.scalar(text("PRAGMA busy_timeout")) == 5000
    finally:
        database.dispose()


def test_shared_database_uses_rollback_journal_extra_and_one_connection(
    database_path: Path,
) -> None:
    database = Database(database_path, filesystem="shared")
    database.initialize()
    try:
        with database.read_session() as session:
            assert session.scalar(text("PRAGMA journal_mode")) == "delete"
            assert session.scalar(text("PRAGMA synchronous")) == 3
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
            assert session.scalar(text("PRAGMA busy_timeout")) == 5000
        assert database.engine.pool.size() == 1  # type: ignore[attr-defined]
        assert database.engine.pool._max_overflow == 0  # type: ignore[attr-defined]
        snapshot = database.metrics.snapshot()
        assert snapshot["db_connection_wait_seconds"]
        assert snapshot["db_transaction_seconds"]
    finally:
        database.dispose()


def test_shared_connection_wait_is_bounded_and_reported(database_path: Path) -> None:
    database = Database(database_path, filesystem="shared")
    database.initialize()
    database.engine.pool._timeout = 0.01  # type: ignore[attr-defined]
    held = database.engine.connect()
    try:
        with pytest.raises(DomainError) as raised, database.read_session():
            pass
        assert raised.value.status_code == 503
        assert raised.value.code == "database_busy"
        assert database.metrics.snapshot()["db_pool_timeouts"] == {"read": 1}
    finally:
        held.close()
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


@pytest.mark.parametrize("failure_stage", ["migration_ddl", "verify", "default_insert"])
def test_failed_fresh_initialization_rolls_back_schema_and_can_retry(
    database_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    database = Database(database_path)

    def fail_after_statement(
        _connection: object, _cursor: object, statement: str, *_: object
    ) -> None:
        normalized = statement.strip().lower()
        if (failure_stage == "migration_ddl" and normalized.startswith("create table tasks")) or (
            failure_stage == "default_insert" and normalized.startswith("insert into queues")
        ):
            raise RuntimeError("injected initialization failure")

    def fail_verification(*_: object) -> None:
        raise RuntimeError("injected initialization failure")

    event.listen(database.engine, "after_cursor_execute", fail_after_statement)
    try:
        with monkeypatch.context() as patch:
            if failure_stage == "verify":
                patch.setattr(
                    "labtasker_server.database._verify_sqlite_settings", fail_verification
                )
            with pytest.raises(RuntimeError, match="injected initialization failure"):
                database.initialize()
    finally:
        database.dispose()

    # Read through an independent connection after closing the failed Server.
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )
    replacement = Database(database_path)
    try:
        replacement.initialize()
        assert [queue.name for queue in QueueService(replacement).list()] == ["default"]
        assert "workers" in inspect(replacement.engine).get_table_names()
    finally:
        replacement.dispose()


def test_failed_forward_migration_preserves_revision_and_task_data(database_path: Path) -> None:
    from labtasker_server.schemas import TaskCreate
    from labtasker_server.services.tasks import TaskService

    database = Database(database_path)
    try:
        database.initialize()
        original, _ = TaskService(database).create(
            "default", "t_ABCDEFGHIJKL", TaskCreate(args={"seed": 17}, routes=["a", "b"])
        )
        config = Config()
        config.set_main_option(
            "script_location",
            str(
                Path(__file__).parents[2]
                / "packages/labtasker-server/src/labtasker_server/migrations"
            ),
        )
        with database.engine.begin() as connection:
            connection.execute(text("BEGIN IMMEDIATE"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0001_initial")
    finally:
        database.dispose()

    def fail_after_worker_table(
        _connection: object, _cursor: object, statement: str, *_: object
    ) -> None:
        if statement.strip().lower().startswith("create table workers"):
            raise RuntimeError("injected upgrade failure")

    upgrading = Database(database_path)
    event.listen(upgrading.engine, "after_cursor_execute", fail_after_worker_table)
    try:
        with pytest.raises(RuntimeError, match="injected upgrade failure"):
            upgrading.initialize()
    finally:
        upgrading.dispose()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_initial",
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workers'"
            ).fetchall()
            == []
        )
        assert connection.execute("SELECT args_json FROM tasks").fetchone() == ('{"seed":17}',)
    replacement = Database(database_path)
    try:
        replacement.initialize()
        assert TaskService(replacement).get("default", original.id) == original
        with replacement.read_session() as session:
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0004_worker_observability"
            )
    finally:
        replacement.dispose()


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
