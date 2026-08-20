from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from labtasker_server.errors import DomainError
from labtasker_server.models import QueueRow


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
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


def _is_sqlite_busy(error: OperationalError) -> bool:
    code = getattr(error.orig, "sqlite_errorcode", None)
    return code in {5, 6} or "database is locked" in str(error.orig).lower()
