"""Concise public copy and preserved evidence, using isolated synthetic records."""
import json
from dataclasses import replace

from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app, visible  # noqa: F401 - shared pytest fixture


def test_public_results_use_plain_copy_and_keep_exact_case_path(review_app,monkeypatch):  # noqa: F811
    monkeypatch.delenv('FINDUEVAL_MODE',raising=False)
    at,_=review_app
    at.run()
    text=visible(at)
    for term in ['专业场景大模型评测','本次比较对象','可比任务','有效AI评分记录','低分案例与评价依据']:
        assert term in text
    assert '管理' not in [b.label for b in at.button]
    at.button(key='results_review_case').click().run()
    assert not at.exception
    assert '案例分析' in visible(at)
    assert '评价结果' in visible(at)
    assert '技术与溯源信息' in [e.label for e in at.expander]
    assert '参考答案与评价标准' in [e.label for e in at.expander]
    assert '原始回答 '+at.query_params['score'][0] in visible(at)


def test_method_has_three_short_sections_and_dynamic_sample_count(monkeypatch):
    monkeypatch.delenv('FINDUEVAL_MODE',raising=False)
    at=AppTest.from_string('''
from types import SimpleNamespace
import pandas as pd
from src.ui.case_study import render_case_study_page
render_case_study_page({'base':SimpleNamespace(tasks=pd.DataFrame([{'case_id':str(i),'domain':'Financial'} for i in range(2)]))})
''').run()
    assert not at.exception
    text=visible(at)
    for section in ['专业样本设计','模型评测流程','方法局限']:
        assert section in text
    assert '当前样本库包含 2 条' in text
    assert text.count('方法局限') == 1
    assert '商业采购建议' in text
    assert '运行评测' not in [b.label for b in at.button]


def test_all_recorded_critical_errors_remain_visible_even_above_summary_limit():
    checks=[dict(kind='forbidden',status='not_met',requirement=f'重大错误{i}',quote='证据',reason='已有理由') for i in range(4)]
    at=AppTest.from_string(f'''
from src.ui.trust_details import render_score_detail
render_score_detail(task={{}},answer='证据',score={{'checks_json':{json.dumps(json.dumps(checks,ensure_ascii=False))}}},dimensions=[],key='critical')
''').run()
    assert not at.exception
    # Each must be shown in the summary as well as in the folded inspector.
    for i in range(4):
        assert sum(f'重大错误{i}' in e.value for e in at.warning) >= 2


def test_results_empty_state_has_public_case_entry(review_app,monkeypatch):  # noqa: F811
    from src.ui import workbench
    at,report=review_app
    empty=replace(report,scope=replace(report.scope,formal_score_count=0))
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(True,empty))
    at.run()
    assert '暂未发布评测结果' in visible(at)
    assert at.button(key='results_view_tasks').label == '查看专业案例'


def test_failed_history_source_still_allows_current_task_reading(review_app,monkeypatch):  # noqa: F811
    from src.ui import workbench
    at,_=review_app
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(False,None,'历史结果暂不可读取。'))
    at.query_params['page']='review'
    at.query_params['case']='UNSCORED'
    at.run()
    assert not at.exception
    assert '当前未评测任务' in visible(at)
    assert any('历史结果暂不可读取' in e.value for e in at.warning)
    assert '原始回答' not in visible(at)


def test_failures_are_summarized_and_full_runtime_details_are_folded():
    at=AppTest.from_string('''
from types import SimpleNamespace
from src.ui.history_view import render_runtime_details
render_runtime_details(SimpleNamespace(runtime_tables={'live_run_responses':[dict(run_id='r',case_id='x',model_name='m',run_status='failed',error_message='已保存错误')]},comparison={}),compact=True)
''').run()
    assert not at.exception
    assert any('失败' in c.value for c in at.warning)
    details=next(e for e in at.expander if e.label=='运行状态与测试条件')
    assert not details.proto.expanded
    assert any('已保存错误' in str(d.value) for d in at.dataframe)
