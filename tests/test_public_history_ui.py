"""AppTest renders must not contact providers or require an API key."""

from streamlit.testing.v1 import AppTest


def test_comparison_keeps_full_service_identity_and_content_sized_model_column():
    import json

    at = AppTest.from_string('''
from types import SimpleNamespace
from src.ui.history_view import render_comparison_and_runtime
report = SimpleNamespace(comparison={
    'common_count': 13, 'sufficient': True,
    'models': [{'model_id': 'Qwen/Qwen3.6-35B-A3B | siliconflow | 端点未记录',
                'common_count': 13, 'avg_total': 84.76923076923077}],
})
render_comparison_and_runtime(report, include_runtime=False)
''').run()
    assert not at.exception
    table = at.dataframe[0]
    assert table.value.iloc[0]['模型及服务配置'] == 'Qwen3.6-35B-A3B | siliconflow | 端点未记录'
    assert table.value.iloc[0]['AI平均评分'] == 84.76923076923077
    config = json.loads(table.proto.columns)
    assert config['模型及服务配置'].get('width') is None, 'Fixed widths clip service identities inside the cell'
    assert config['AI平均评分']['type_config']['format'] == '%.1f'


def test_public_empty_state_and_selftest_entry_work_without_api_key(isolated_app_database, monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    from app.models.siliconflow import SiliconFlowProvider

    monkeypatch.setattr(
        SiliconFlowProvider,
        "generate_response",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected API")),
    )
    at = AppTest.from_file("app.py").run(timeout=30)
    assert not at.exception
    visible = " ".join(str(x.value) for x in at.info) + " ".join(str(x.value) for x in at.caption)
    assert "暂未发布评测结果" in visible
    at.button(key="manage_samples").click().run(timeout=30)
    at.radio(key="management_section").set_value("评测结果与快照").run(timeout=30)
    assert not at.exception
    assert any("自测" in e.label for e in at.expander)
    assert any("完整评测快照" in e.label for e in at.get("file_uploader"))


def test_score_details_display_checkpoint_and_raw_response():
    script = """
import json
from src.ui.trust_details import render_score_evidence
render_score_evidence({'evidence_status':'verified_quotes', 'checks_json':json.dumps([
 {'point_id':'must:1','requirement':'识别风险','status':'not_met','quote':'回款正常','quote_verified':True,
  'dimension':'accuracy_score','error_type':'professional','reason':'重大误判'}]),
 'raw_responses_json':json.dumps(['原始评分文本']), 'numeric_checks_json':'[]'}, '本回答说回款正常。')
"""
    at = AppTest.from_string(script).run()
    assert not at.exception
    assert any("评分依据" in e.label for e in at.expander)
    assert any("原始" in e.label for e in at.expander)


def test_snapshot_view_skips_live_database_and_provider_calls(monkeypatch):
    import json

    from test_evaluation_snapshots import ReadOnlyStore

    from app.services.snapshot import export_snapshot

    payload = json.dumps(export_snapshot(ReadOnlyStore()), ensure_ascii=False)
    script = f"""
import streamlit as st
import pandas as pd
from types import SimpleNamespace
from app.services.snapshot import load_snapshot
from src.ui import conclusions as ui
from app.models.siliconflow import SiliconFlowProvider
from unittest.mock import patch
from contextlib import ExitStack
st.session_state['readonly_evaluation_snapshot']=load_snapshot({payload!r})
def prohibited(*a,**k):
    raise AssertionError('snapshot replay contacted live database or provider')
with ExitStack() as stack:
    stack.enter_context(patch.object(ui.cd,'load_conclusion_source',prohibited))
    stack.enter_context(patch('app.persistence.get_result_store',prohibited))
    stack.enter_context(patch.object(ui.sc,'export_score_payload',prohibited))
    stack.enter_context(patch.object(SiliconFlowProvider,'generate_response',prohibited))
    from src.ui.review import render_review_page
    if st.query_params.get('page') == 'review':
        render_review_page({{'base':SimpleNamespace(tasks=pd.DataFrame(),gold_answer_map={{}})}})
    else:
        ui.render_conclusions_page({{'base':SimpleNamespace(tasks=pd.DataFrame(),gold_answer_map={{}})}})

"""
    at = AppTest.from_string(script).run(timeout=30)
    assert not at.exception
    assert any("只读历史快照" in str(c.value) for c in at.caption)
    button = at.button(key="results_review_case")
    button.click().run(timeout=30)
    assert not at.exception
    assert any("历史记录未保存任务正文；不使用当前题库补造运行时材料" in str(c.value) for c in at.caption)
