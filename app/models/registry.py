"""模型供应商注册表（registry，PR-33）。

页面层只通过本模块按名称获取 provider，不直接依赖任何具体实现，便于后续扩展
其他 OpenAI 兼容供应商。provider 以工厂函数注册并按名缓存为单例。
"""

from __future__ import annotations

from typing import Callable

from app.models.base import ModelProvider
from app.models.mock import MockProvider, PROVIDER_NAME as MOCK_NAME
from app.models.siliconflow import (
    PROVIDER_NAME as SILICONFLOW_NAME,
    SiliconFlowProvider,
    is_configured as siliconflow_configured,
)

ProviderFactory = Callable[[], ModelProvider]

_FACTORIES: dict[str, ProviderFactory] = {}
_INSTANCES: dict[str, ModelProvider] = {}


def register_provider(name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    """注册一个供应商工厂。name 重复时默认报错，replace=True 可覆盖。"""
    key = str(name).strip().lower()
    if not key:
        raise ValueError("provider name 不能为空。")
    if key in _FACTORIES and not replace:
        raise ValueError(f"provider 已注册：{key}。")
    _FACTORIES[key] = factory
    _INSTANCES.pop(key, None)


def available_providers() -> list[str]:
    return sorted(_FACTORIES)


def get_provider(name: str) -> ModelProvider:
    """按名称获取 provider 单例。未注册时抛 KeyError。"""
    key = str(name).strip().lower()
    if key not in _FACTORIES:
        raise KeyError(f"未注册的 provider：{name}。")
    if key not in _INSTANCES:
        _INSTANCES[key] = _FACTORIES[key]()
    return _INSTANCES[key]


def get_text_provider(prefer: str = SILICONFLOW_NAME) -> ModelProvider:
    """返回文本对话 provider：优先供应商已配置 API Key 时用真实供应商，否则回退 mock。

    无密钥不报错崩溃，统一回退 MockProvider，由其返回 status=mock 供页面标识。
    """
    key = str(prefer).strip().lower()
    if key == SILICONFLOW_NAME and not siliconflow_configured():
        return get_provider(MOCK_NAME)
    return get_provider(key)


def reset_for_testing() -> None:
    """清空已缓存的 provider 单例（仅供测试在切换配置后重建实例）。"""
    _INSTANCES.clear()


# 内置供应商注册：SiliconFlow（真实）与 Mock（回退）。
register_provider(SILICONFLOW_NAME, SiliconFlowProvider, replace=True)
register_provider(MOCK_NAME, MockProvider, replace=True)
