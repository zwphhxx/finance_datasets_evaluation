"""Server-owned policy: public browsing is read-only; budgeted runs are scoped.

Management remains opt-in deployment separation, not a login system. Never
enable admin mode on an unrestricted deployment. Frontend flags cannot grant it.
"""
from __future__ import annotations

import os
from functools import wraps

MODE_ENV = "FINDUEVAL_MODE"
READ_ONLY_MESSAGE = "当前为公开只读展示，管理操作仅在独立受控环境中开放。"


class PublicReadOnlyError(PermissionError):
    """An operation is unavailable on the public deployment."""


def management_enabled() -> bool:
    return os.environ.get(MODE_ENV, "").strip().lower() == "admin"


def require_management() -> None:
    if not management_enabled():
        raise PublicReadOnlyError(READ_ONLY_MESSAGE)


def management_operation(function):
    """Reject before validation, network requests, filesystem or database writes."""
    @wraps(function)
    def guarded(*args, **kwargs):
        require_management()
        return function(*args, **kwargs)
    return guarded


def evaluation_writes_enabled() -> bool:
    from app.services.public_execution import current_execution
    return management_enabled() or current_execution() is not None


def evaluation_operation(function):
    """Allow only a server-reserved public job, never general management."""
    @wraps(function)
    def guarded(*args, **kwargs):
        if management_enabled():
            return function(*args, **kwargs)
        from app.services.public_execution import authorized_operation
        with authorized_operation(function, args, kwargs):
            return function(*args, **kwargs)
    return guarded
