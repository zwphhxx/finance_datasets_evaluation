"""Model display helpers for seed examples and live model runs.

Seed model ids are kept as provenance in data files. UI display maps them to
example labels, while live model ids keep their real identity and use a short
name only for compact table/selectbox labels.
"""

from __future__ import annotations

from typing import Any, Mapping

SEED_SOURCE = "seed"
LIVE_SOURCE = "live"
CONFIRMED_LIVE_SOURCE = "confirmed_live"

SEED_MODEL_LABELS: dict[str, str] = {
    "Model_A_baseline": "示例基线回答",
    "Model_B_rag": "示例检索增强回答",
    "Model_C_prompt_v2": "示例提示词优化回答",
}

SOURCE_LABELS: dict[str, str] = {
    SEED_SOURCE: "示例历史评价",
    LIVE_SOURCE: "本次运行结果",
    "pending_live": "本次运行结果",
    "draft": "本次运行结果",
    CONFIRMED_LIVE_SOURCE: "已复核归档",
}


def model_short_name(model_id: Any) -> str:
    """Return a compact model name without changing provenance."""
    value = _clean(model_id)
    if not value:
        return "未标注模型"
    return value.rstrip("/").rsplit("/", 1)[-1] or value


def is_seed_model(model_id: Any) -> bool:
    """Whether a model id belongs to bundled seed examples."""
    return _clean(model_id) in SEED_MODEL_LABELS


def display_model_name(
    model_id: Any,
    source: str | None = None,
    mapping: Mapping[str, str] | None = None,
) -> str:
    """Return reader-facing model name without rewriting underlying data.

    - Known seed ids become example labels.
    - Unknown seed-sourced ids are explicitly prefixed as historical examples.
    - Live ids are displayed by short name; details can still show the full id.
    - Optional mapping is kept for tests or caller-specific aliases, but never
      changes the original model id stored in data.
    """
    key = _clean(model_id)
    if not key:
        return "未标注模型"
    if mapping and key in mapping:
        return str(mapping[key])
    normalized_source = normalize_source(source)
    if key in SEED_MODEL_LABELS:
        return SEED_MODEL_LABELS[key]
    if normalized_source == SEED_SOURCE:
        return f"示例历史评价：{model_short_name(key)}"
    return model_short_name(key)


def display_model_detail(model_id: Any) -> str:
    """Return full model id for secondary detail rows."""
    return _clean(model_id) or "未标注模型"


def source_label(source: str | None) -> str:
    """Return a restrained source label used in pages."""
    normalized = normalize_source(source)
    return SOURCE_LABELS.get(normalized, "当前数据")


def normalize_source(source: str | None) -> str:
    value = _clean(source).lower()
    if value in {"confirmed", "confirmed_live", "archived_live"}:
        return CONFIRMED_LIVE_SOURCE
    if value in {"live", "pending_live", "draft", "session", "current"}:
        return LIVE_SOURCE if value in {"live", "session", "current"} else value
    if value in {"seed", "sample", "historical", "history"}:
        return SEED_SOURCE
    return value


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text
