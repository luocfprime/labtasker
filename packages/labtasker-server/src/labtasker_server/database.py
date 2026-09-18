from __future__ import annotations

import logging
import os
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, Engine, create_engine, event, insert, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from labtasker_server.errors import DomainError
from labtasker_server.filesystem import (
    DatabaseFilesystem,
    EffectiveDatabaseFilesystem,
    ResolvedDatabaseFilesystem,
    resolve_database_filesystem,
)
from labtasker_server.models import QueueRow
from labtasker_server.name_search import name_matches_fuzzy
from labtasker_server.ownership import OwnershipLock, acquire_sidecar_lock, lock_database

logger = logging.getLogger(__name__)
OperationKind = Literal["read", "write", "health", "startup", "expiry"]


class DatabaseOwnershipError(RuntimeError):
    pass


@dataclass(slots=True)
class TimingMetric:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0

    def observe(self, seconds: float) -> None:
        self.count += 1
        self.total_seconds += seconds
        self.max_seconds = max(self.max_seconds, seconds)


@dataclass(slots=True)
class DatabaseMetrics:
    connection_wait_seconds: dict[str, TimingMetric] = field(default_factory=dict)
    transaction_seconds: dict[str, TimingMetric] = field(default_factory=dict)
    pool_timeouts: dict[str, int] = field(default_factory=dict)
    sqlite_busy_failures: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_wait(self, operation: OperationKind, seconds: float) -> None:
        with self._lock:
            self.connection_wait_seconds.setdefault(operation, TimingMetric()).observe(seconds)

    def record_transaction(self, operation: OperationKind, seconds: float) -> None:
        with self._lock:
            self.transaction_seconds.setdefault(operation, TimingMetric()).observe(seconds)
        if seconds >= 1.0:
            logger.warning(
                "slow database transaction operation=%s seconds=%.3f", operation, seconds
            )

    def record_pool_timeout(self, operation: OperationKind) -> None:
        with self._lock:
            self.pool_timeouts[operation] = self.pool_timeouts.get(operation, 0) + 1

    def record_sqlite_busy(self, operation: OperationKind) -> None:
        with self._lock:
            self.sqlite_busy_failures[operation] = self.sqlite_busy_failures.get(operation, 0) + 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "db_connection_wait_seconds": {
                    operation: asdict(metric)
                    for operation, metric in self.connection_wait_seconds.items()
                },
                "db_transaction_seconds": {
                    operation: asdict(metric)
                    for operation, metric in self.transaction_seconds.items()
                },
                "db_pool_timeouts": dict(self.pool_timeouts),
                "db_sqlite_busy_failures": dict(self.sqlite_busy_failures),
            }


class Database:
    def __init__(
        self,
        path: Path,
        *,
        filesystem: DatabaseFilesystem = "auto",
    ) -> None:
        self.path = path.resolve()
        self.filesystem: ResolvedDatabaseFilesystem = resolve_database_filesystem(
            self.path, filesystem
        )
        self.metrics = DatabaseMetrics()
        self._database_lock: OwnershipLock | None = None
        self._legacy_ownership_fd: int | None = None
        try:
            self._database_lock = acquire_sidecar_lock("db", self.path)
        except BlockingIOError as error:
            raise DatabaseOwnershipError(
                f"Another Server process already owns database {self.path}."
            ) from error
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.filesystem.effective == "local":
                self._legacy_ownership_fd = _acquire_legacy_database_ownership(self.path)
            self.engine = _create_sqlite_engine(self.path, self.filesystem.effective)
            self._session_factory = sessionmaker(self.engine, expire_on_commit=False)
        except BaseException:
            if self._legacy_ownership_fd is not None:
                os.close(self._legacy_ownership_fd)
                self._legacy_ownership_fd = None
            if self._database_lock is not None:
                self._database_lock.close()
                self._database_lock = None
            raise

    def initialize(self) -> None:
        alembic_config = Config()
        alembic_config.set_main_option(
            "script_location",
            # Alembic's ConfigParser interpolates percent signs in option values.
            str(Path(__file__).resolve().parent / "migrations").replace("%", "%%"),
        )
        with self.engine.begin() as connection:
            # sqlite3's legacy mode does not begin a transaction for DDL.
            # Commit schema changes and initial Queue together, including when
            # startup fails or is interrupted between migration operations.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            existing_tables = set(inspect(connection).get_table_names())
            if existing_tables and "alembic_version" not in existing_tables:
                raise RuntimeError(
                    "Database has tables but is not a recognized Labtasker v2 schema."
                )
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
            _verify_sqlite_settings(connection, self.filesystem.effective)
            if not existing_tables:
                connection.execute(insert(QueueRow).values(name="default"))

    @contextmanager
    def read_session(self, operation: OperationKind = "read") -> Iterator[Session]:
        with self._session_factory() as session:
            transaction_started: float | None = None
            try:
                transaction_started = self._checkout(session, operation)
                # sqlite3's legacy transaction mode does not begin on SELECT.
                session.execute(text("BEGIN"))
                yield session
                session.rollback()
            except PoolTimeout as error:
                self.metrics.record_pool_timeout(operation)
                raise _database_busy() from error
            except OperationalError as error:
                session.rollback()
                if _is_sqlite_busy(error):
                    self.metrics.record_sqlite_busy(operation)
                    raise _database_busy() from error
                raise
            except BaseException:
                session.rollback()
                raise
            finally:
                if transaction_started is not None:
                    self.metrics.record_transaction(
                        operation, time.monotonic() - transaction_started
                    )

    @contextmanager
    def write_session(self, operation: OperationKind = "write") -> Iterator[Session]:
        with self._session_factory() as session:
            transaction_started: float | None = None
            try:
                transaction_started = self._checkout(session, operation)
                session.execute(text("BEGIN IMMEDIATE"))
                yield session
                session.commit()
            except PoolTimeout as error:
                self.metrics.record_pool_timeout(operation)
                session.rollback()
                raise _database_busy() from error
            except OperationalError as error:
                session.rollback()
                if _is_sqlite_busy(error):
                    self.metrics.record_sqlite_busy(operation)
                    raise _database_busy() from error
                raise
            except BaseException:
                session.rollback()
                raise
            finally:
                if transaction_started is not None:
                    self.metrics.record_transaction(
                        operation, time.monotonic() - transaction_started
                    )

    def _checkout(self, session: Session, operation: OperationKind) -> float:
        started = time.monotonic()
        session.connection()
        checked_out = time.monotonic()
        self.metrics.record_wait(operation, checked_out - started)
        return checked_out

    def dispose(self) -> None:
        try:
            self.engine.dispose()
        finally:
            if self._legacy_ownership_fd is not None:
                os.close(self._legacy_ownership_fd)
                self._legacy_ownership_fd = None
            if self._database_lock is not None:
                self._database_lock.close()
                self._database_lock = None


def _acquire_legacy_database_ownership(path: Path) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_database(fd)
    except BlockingIOError as error:
        os.close(fd)
        warnings.warn(
            "A legacy v2.5 database owner was detected; stop the old Server "
            "before starting this release.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise DatabaseOwnershipError(
            f"A legacy v2.5 or current Server process already owns database {path}; "
            "stop it before retrying."
        ) from error
    except BaseException:
        os.close(fd)
        raise

    descriptor_stat = os.fstat(fd)
    try:
        path_stat = path.stat()
    except OSError:
        os.close(fd)
        raise
    if (descriptor_stat.st_dev, descriptor_stat.st_ino) != (
        path_stat.st_dev,
        path_stat.st_ino,
    ):
        os.close(fd)
        raise DatabaseOwnershipError(
            f"Database descriptor does not identify configured path {path}."
        )
    return fd


def _create_sqlite_engine(path: Path, filesystem: EffectiveDatabaseFilesystem) -> Engine:
    options: dict[str, object] = {}
    if filesystem == "shared":
        options.update(
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=5.0,
        )
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(path)),
        connect_args={"check_same_thread": False, "timeout": 5.0},
        **options,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: object, _: object) -> None:
        dbapi_connection.create_function(  # type: ignore[attr-defined]
            "labtasker_name_fuzzy", 2, name_matches_fuzzy, deterministic=True
        )
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(f"PRAGMA journal_mode={'WAL' if filesystem == 'local' else 'DELETE'}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute(f"PRAGMA synchronous={'FULL' if filesystem == 'local' else 'EXTRA'}")
        finally:
            cursor.close()

    return engine


def _is_sqlite_busy(error: OperationalError) -> bool:
    code = getattr(error.orig, "sqlite_errorcode", None)
    return code in {5, 6} or "database is locked" in str(error.orig).lower()


def _database_busy() -> DomainError:
    return DomainError(
        503,
        "database_busy",
        "The database is busy; retry the operation.",
        {},
    )


def _verify_sqlite_settings(
    connection: Connection, filesystem: EffectiveDatabaseFilesystem
) -> None:
    actual = {
        "journal_mode": connection.scalar(text("PRAGMA journal_mode")),
        "foreign_keys": connection.scalar(text("PRAGMA foreign_keys")),
        "busy_timeout": connection.scalar(text("PRAGMA busy_timeout")),
        "synchronous": connection.scalar(text("PRAGMA synchronous")),
    }
    expected = {
        "journal_mode": "wal" if filesystem == "local" else "delete",
        "foreign_keys": 1,
        "busy_timeout": 5000,
        "synchronous": 2 if filesystem == "local" else 3,
    }
    if actual != expected:
        raise RuntimeError(f"Required SQLite settings were not applied: {actual!r}")
