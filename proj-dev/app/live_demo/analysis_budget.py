"""A shared wait budget for interactive tests; live ingestion keeps its own pacing."""

from contextlib import contextmanager
from contextvars import ContextVar
import time


_deadline = ContextVar('analysis_deadline', default=None)


class AnalysisTimeout(RuntimeError):
    """The interactive request cannot finish within its wait budget."""


def remaining_time():
    deadline = _deadline.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AnalysisTimeout('Analysis time budget exhausted.')
    return remaining


@contextmanager
def analysis_deadline(seconds):
    previous = _deadline.get()
    deadline = time.monotonic() + seconds
    token = _deadline.set(min(previous, deadline) if previous is not None else deadline)
    try:
        yield
        remaining_time()
    finally:
        _deadline.reset(token)


def http_timeout(default):
    remaining = remaining_time()
    if remaining is None:
        return default
    connect, read = default if isinstance(default, tuple) else (default, default)
    connect = min(connect, remaining / 3)
    return connect, min(read, remaining - connect)


@contextmanager
def request_slot(semaphore):
    if not semaphore.acquire(timeout=remaining_time()):
        raise AnalysisTimeout('Analysis workers are busy.')
    try:
        remaining_time()
        yield
    finally:
        semaphore.release()
