"""Read-only configuration checks and explicitly requested, free model discovery."""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.persistence import PersistenceConfigurationError, require_durable_live_store, resolve_result_store_settings
from app.persistence.result_store import ResultStore
from app.persistence.schema import RUNTIME_TABLES
from app.services import dataset_service as ds
from app.services import public_run, scorer
from app.services.evaluation_policy import resolve_phase_timeout
from app.services.public_execution import catalogue_scope
from app.services.public_run_quota import PublicRunLedger
from src.ui.evaluation_config import build_sample_options


def ensure_catalogue(provider, models):
    with catalogue_scope():
        result = provider.list_models()
    if not result.ok:
        raise PermissionError(
            "无法确认当前模型目录：" + str(result.error_message or result.error_code or "服务暂不可用")
        )
    available = {m.id for m in result.models}
    missing = set(models) - available
    if missing:
        raise PermissionError("当前账户模型目录未包含：" + "、".join(sorted(missing)))
    return available


def check_run_configuration(
    base,
    case_ids,
    model_ids,
    *,
    temperature=0.0,
    max_tokens=4096,
    check_catalogue=False,
    url=None,
    provider_factory=None,
):
    cases = list(dict.fromkeys(case_ids))
    models = list(dict.fromkeys(model_ids))
    count = len(cases) * len(models)
    report = dict(
        ready=False,
        errors=[],
        task_count=count,
        case_ids=cases,
        model_ids=models,
        judge=scorer.DEFAULT_JUDGE_MODEL,
        max_attempts=5,
        judge_attempts=3,
        quota=None,
        catalogue_checked=False,
    )
    if not public_run.sf.is_configured():
        report["errors"].append("网站未配置模型服务密钥，仍可浏览已有案例。")
    if not public_run.enabled():
        report["errors"].append("公开真实评测暂未开放。")
    if not cases or not models:
        report["errors"].append("请选择专业样本和模型。")
    if (
        type(max_tokens) is not int
        or not 128 <= max_tokens <= 4096
        or type(temperature) not in {int, float}
        or not 0 <= temperature <= 2
    ):
        report["errors"].append("生成参数超出服务端允许范围。")
    if report["errors"]:
        return report
    try:
        settings = (
            public_run._settings()
            if url is None
            else resolve_result_store_settings(None, environ={"DATABASE_URL": url})
        )
        require_durable_live_store("siliconflow", settings)
        store = ResultStore(settings.url)
        try:
            if not store.ping() or set(store.table_names()) != set(RUNTIME_TABLES):
                raise ValueError("结果数据库暂不可用。")
            if "diagnostics_json" not in {c["name"] for c in inspect(store.engine).get_columns("request_attempts")}:
                raise ValueError("请求诊断结构尚未升级，暂不发起真实评测。")
            if store.is_postgresql:
                with store.engine.connect() as connection:
                    for name in RUNTIME_TABLES:
                        for permission in ("INSERT", "UPDATE"):
                            if not connection.execute(
                                text("SELECT has_table_privilege(current_user,:table,:permission)"),
                                {"table": name, "permission": permission},
                            ).scalar():
                                raise ValueError("结果数据库缺少必要保存权限。")
                    tables = set(inspect(connection).get_table_names())
                    for name in ("public_evaluation_budget", "public_evaluation_jobs", "public_evaluation_pair_budget"):
                        if name in tables:
                            for permission in ("INSERT", "UPDATE"):
                                if not connection.execute(
                                    text("SELECT has_table_privilege(current_user,:table,:permission)"),
                                    {"table": name, "permission": permission},
                                ).scalar():
                                    raise ValueError("额度账本缺少必要保存权限。")
                        elif not connection.execute(
                            text("SELECT has_schema_privilege(current_user,'public','CREATE')")
                        ).scalar():
                            raise ValueError("额度账本尚未就绪。")
            options = build_sample_options(
                base.tasks.to_dict("records"), base.gold_answer_map, ds.get_testable_rubric_dimensions()
            )
            allowed_cases = {r["case_id"] for r in options}
            allowed_models = set(public_run.configured_models(store))
            if not set(cases) <= allowed_cases or not set(models) <= allowed_models:
                raise ValueError("所选任务或模型不在服务端允许范围。")
            report["quota"] = PublicRunLedger(store.engine, daily_tasks=public_run.daily_limit()).usage()
            if count > report["quota"]["tasks_remaining"]:
                report["errors"].append("本次任务数超过今日全站剩余任务额度。")
            if report["quota"]["calls_remaining"] < count * 2:
                report["errors"].append("今日剩余请求额度不足以完成回答和评分。")
        finally:
            store.engine.dispose()
        provider = (provider_factory or (lambda: public_run.sf.SiliconFlowProvider(timeout_seconds=15)))()
        endpoint = urlsplit(provider.base_url)
        if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError("模型服务地址未正确配置。")
        report["judge_timeout"], report["judge_timeout_source"] = resolve_phase_timeout("judge")
        if check_catalogue and not report["errors"]:
            ensure_catalogue(provider, [*models, scorer.DEFAULT_JUDGE_MODEL])
            report["catalogue_checked"] = True
        report["ready"] = not report["errors"]
    except (PermissionError, ValueError) as exc:
        report["errors"].append(str(exc))
    except PersistenceConfigurationError:
        report["errors"].append("尚未配置可持久保存结果的数据库，未发起模型调用。")
    except SQLAlchemyError:
        report["errors"].append("结果数据库或额度账本暂不可用，未发起模型调用。")
    return report
