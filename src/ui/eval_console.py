"""评测控制台兼容层（已拆分至 eval_run_page / data_resolver / eval_state）。

保留本文件是为了兼容既有测试与旧会话状态键。新代码应直接使用：
  - src.ui.eval_run_page.render_eval_run_page  渲染评测向导页面
  - app.services.data_resolver.resolve_active_data  解析运行时数据
  - app.services.eval_state  读写会话状态
"""

from __future__ import annotations

import warnings

from app.services.data_resolver import resolve_active_data
from src.ui.eval_run_page import render_eval_run_page


def render_eval_console(base) -> None:
    """兼容旧入口：渲染评测控制台页面（现等价于「发起评测」页面）。"""
    warnings.warn(
        "render_eval_console is deprecated; use src.ui.eval_run_page.render_eval_run_page",
        DeprecationWarning,
        stacklevel=2,
    )
    render_eval_run_page({"base": base})


__all__ = ["render_eval_console", "resolve_active_data"]
