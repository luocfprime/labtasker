from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - explicit HTTP remains best effort off POSIX
    fcntl = None  # type: ignore[assignment]

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from labtasker_server.errors import DomainError
from labtasker_server.models import QueueRow

LOCAL_GITIGNORE = "*\n!.gitignore\n"


class DatabaseOwnershipError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path, *, ownership_fd: int | None = None) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        labtasker_dir = next(
            (parent for parent in self.path.parents if parent.name == ".labtasker"),
            None,
        )
        if labtasker_dir is not None:
            _ensure_local_gitignore(labtasker_dir)
        self._ownership_fd: int | None = _acquire_database_ownership(self.path, ownership_fd)
        self.engine = _create_sqlite_engine(self.path)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        existing_tables = set(inspect(self.engine).get_table_names())
        is_fresh = not existing_tables
        if existing_tables and "alembic_version" not in existing_tables:
            raise RuntimeError("Database has tables but is not a recognized Labtasker v2 schema.")

        alembic_config = Config()
        alembic_config.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parent / "migrations"),
        )
        with self.engine.begin() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
        _verify_sqlite_settings(self.engine)

        if is_fresh:
            with self.write_session() as session:
                session.add(QueueRow(name="default"))

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            yield session

    @contextmanager
    def write_session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            try:
                session.execute(text("BEGIN IMMEDIATE"))
                yield session
                session.commit()
            except OperationalError as error:
                session.rollback()
                if _is_sqlite_busy(error):
                    raise DomainError(
                        503,
                        "database_busy",
                        "The database is busy; retry the operation.",
                        {},
                    ) from error
                raise
            except BaseException:
                session.rollback()
                raise

    def dispose(self) -> None:
        self.engine.dispose()
        if self._ownership_fd is not None:
            os.close(self._ownership_fd)
            self._ownership_fd = None


def _acquire_database_ownership(path: Path, inherited_fd: int | None) -> int:
    if inherited_fd is None:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                os.close(fd)
                raise DatabaseOwnershipError(
                    f"Another Server process already owns database {path}."
                ) from error
    else:
        fd = os.dup(inherited_fd)
        os.set_inheritable(fd, False)

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


def _create_sqlite_engine(path: Path) -> Engine:
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def _ensure_local_gitignore(labtasker_dir: Path) -> None:
    try:
        with (labtasker_dir / ".gitignore").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(LOCAL_GITIGNORE)
    except FileExistsError:
        pass


def _is_sqlite_busy(error: OperationalError) -> bool:
    code = getattr(error.orig, "sqlite_errorcode", None)
    return code in {5, 6} or "database is locked" in str(error.orig).lower()


def _verify_sqlite_settings(engine: Engine) -> None:
    with engine.connect() as connection:
        actual = {
            "journal_mode": connection.scalar(text("PRAGMA journal_mode")),
            "foreign_keys": connection.scalar(text("PRAGMA foreign_keys")),
            "busy_timeout": connection.scalar(text("PRAGMA busy_timeout")),
            "synchronous": connection.scalar(text("PRAGMA synchronous")),
        }
    expected = {
        "journal_mode": "wal",
        "foreign_keys": 1,
        "busy_timeout": 5000,
        "synchronous": 2,
    }
    if actual != expected:
        raise RuntimeError(f"Required SQLite settings were not applied: {actual!r}")
