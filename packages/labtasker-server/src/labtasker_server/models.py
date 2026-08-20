from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class QueueRow(Base):
    __tablename__ = "queues"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(["queue_name"], ["queues.name"], ondelete="CASCADE"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','cancelled')",
            name="ck_tasks_status",
        ),
        CheckConstraint("attempt >= 0", name="ck_tasks_attempt_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_tasks_max_attempts_positive"),
        CheckConstraint(
            "json_valid(args_json) AND json_type(args_json) = 'object'",
            name="ck_args_json",
        ),
        CheckConstraint(
            "json_valid(metadata_json) AND json_type(metadata_json) = 'object'",
            name="ck_metadata_json",
        ),
        CheckConstraint(
            "json_valid(result_json) AND json_type(result_json) = 'object'",
            name="ck_result_json",
        ),
        CheckConstraint(
            "(status = 'pending' AND pending_at_us IS NOT NULL "
            "AND active_run_id IS NULL AND lease_expires_at_us IS NULL "
            "AND attempt < max_attempts) OR status != 'pending'",
            name="ck_tasks_pending_state",
        ),
        CheckConstraint(
            "(status = 'running' AND pending_at_us IS NULL "
            "AND active_run_id IS NOT NULL AND lease_expires_at_us IS NOT NULL) "
            "OR status != 'running'",
            name="ck_tasks_running_state",
        ),
        CheckConstraint(
            "(status IN ('succeeded','failed','cancelled') AND pending_at_us IS NULL "
            "AND active_run_id IS NULL AND lease_expires_at_us IS NULL) "
            "OR status NOT IN ('succeeded','failed','cancelled')",
            name="ck_tasks_terminal_state",
        ),
        Index(
            "ix_tasks_claim",
            "queue_name",
            "status",
            "priority",
            "pending_at_us",
            "task_id",
        ),
        Index("ix_tasks_expiry", "status", "lease_expires_at_us"),
        Index("ix_tasks_default_list", "queue_name", "created_at_us", "task_id"),
        Index("ix_tasks_status_list", "queue_name", "status", "created_at_us", "task_id"),
        Index(
            "uq_tasks_active_run_id",
            "active_run_id",
            unique=True,
            sqlite_where=text("active_run_id IS NOT NULL"),
        ),
        Index(
            "ix_tasks_terminal_run_id",
            "last_terminal_run_id",
            sqlite_where=text("last_terminal_run_id IS NOT NULL"),
        ),
    )

    queue_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(14), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(256))
    args_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at_us: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_us: Mapped[int] = mapped_column(Integer, nullable=False)
    last_route: Mapped[str | None] = mapped_column(String(128))
    started_at_us: Mapped[int | None] = mapped_column(Integer)
    finished_at_us: Mapped[int | None] = mapped_column(Integer)
    last_error_json: Mapped[str | None] = mapped_column(Text)
    creation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active_run_id: Mapped[str | None] = mapped_column(String(14))
    lease_expires_at_us: Mapped[int | None] = mapped_column(Integer)
    last_terminal_run_id: Mapped[str | None] = mapped_column(String(14))
    last_terminal_action: Mapped[str | None] = mapped_column(String(32))
    pending_at_us: Mapped[int | None] = mapped_column(Integer)

    routes: Mapped[list[TaskRouteRow]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TaskRouteRow(Base):
    __tablename__ = "task_routes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["queue_name", "task_id"],
            ["tasks.queue_name", "tasks.task_id"],
            ondelete="CASCADE",
        ),
        Index("ix_task_routes_route", "queue_name", "route", "task_id"),
    )

    queue_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(14), primary_key=True)
    route: Mapped[str] = mapped_column(String(128), primary_key=True)

    task: Mapped[TaskRow] = relationship(back_populates="routes")
