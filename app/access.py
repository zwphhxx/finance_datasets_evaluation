"""Server-owned deployment policy. Public is read-only; management is opt-in.

This is deployment separation, not a login system. Never enable admin mode on an
unrestricted public deployment. Query parameters and session state are ignored.
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
