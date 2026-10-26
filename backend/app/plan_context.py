"""Explicit request/task scope. Never use a process-wide active-plan variable."""
from contextvars import ContextVar
from contextlib import contextmanager

current_plan: ContextVar[str | None] = ContextVar("plan_id", default=None)


@contextmanager
def scope(plan_id: str | None):
    token = current_plan.set(plan_id)
    try:
        yield
    finally:
        current_plan.reset(token)
