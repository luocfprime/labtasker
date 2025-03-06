import os
import threading
import time
from contextvars import ContextVar
from typing import Optional

from labtasker.client.core.api import refresh_task_heartbeat
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.logging import logger
from labtasker.client.core.paths import get_labtasker_log_dir

__all__ = [
    "start_heartbeat",
    "end_heartbeat",
]


class Heartbeat:

    def __init__(self, task_id, heartbeat_interval):
        self.task_id = task_id
        self.heartbeat_interval = heartbeat_interval

        self._thread = None
        self._stop_event = threading.Event()

        # the heartbeat.lock file is useful for stopping heartbeat in the scheduler process from the actual job process
        self._lockfile = get_labtasker_log_dir() / f"heartbeat.lock"

    def start(self):
        """Start the heartbeat thread."""
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)

        # create a heartbeat lock file
        fd = os.open(self._lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)

        self._thread.start()

    def delay(self, interval: float) -> bool:
        spin_interval = 0.01
        cycles = int(interval // spin_interval)
        for _ in range(cycles):
            time.sleep(spin_interval)
            # check if heartbeat should stop
            if self._stop_event.is_set() or not os.path.exists(self._lockfile):
                return False
        return True

    def _heartbeat(self):
        """Refresh heartbeat periodically"""
        while True:
            try:
                refresh_task_heartbeat(task_id=self.task_id)
            except Exception as e:
                logger.error(f"Heartbeat failed for task {self.task_id}: {e}")

            # check if heartbeat should stop
            if not self.delay(self.heartbeat_interval):
                break

    def stop(self):
        """Stop the heartbeat thread."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=self.heartbeat_interval * 10)
            try:  # try to remove heartbeat lock file
                os.unlink(self._lockfile)
            except FileNotFoundError:
                pass


_current_heartbeat: ContextVar[Optional[Heartbeat]] = ContextVar(
    "heartbeat", default=None
)


def start_heartbeat(
    task_id, heartbeat_interval: Optional[float] = None, raise_error=True
):
    logger.debug("Try starting heartbeat.")
    if _current_heartbeat.get() is not None:
        if raise_error:
            raise LabtaskerRuntimeError("Heartbeat already started.")
        return

    heartbeat_manager = Heartbeat(
        task_id=task_id,
        heartbeat_interval=heartbeat_interval
        or get_client_config().task.heartbeat_interval,
    )
    heartbeat_manager.start()
    _current_heartbeat.set(heartbeat_manager)
    logger.debug("Heartbeat started.")


def end_heartbeat(raise_error=True):
    logger.debug("Try ending heartbeat.")
    heartbeat_manager = _current_heartbeat.get()
    if heartbeat_manager is None:
        if raise_error:
            raise LabtaskerRuntimeError("Heartbeat not started properly.")
        return
    heartbeat_manager.stop()
    _current_heartbeat.set(None)
    logger.debug("Heartbeat ended.")
