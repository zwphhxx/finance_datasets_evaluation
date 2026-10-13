"""Public reading follows results -> one case -> saved evidence without API calls."""

from types import SimpleNamespace

import pandas as pd
from streamlit.testing.v1 import AppTest

from app.services import conclusions as cc
from app.services.conclusion_read_model import ConclusionReport, ReportScope


def public_app(monkeypatch):
    from src.ui import workbench

    scores = pd.DataFrame([dict(run_id='r', case_id='TEST-1', eval_model='test-model',
                               judge_status='success', total_score=70,
                               review_note='遗漏核查条件。', rationale='{"coverage_score":"未核对回款。"}')])
    responses = pd.DataFrame([dict(run_id='r', case_id='TEST-1', model_name='test-model',
                                  answer_text='测试回答，没有回款资料。', run_status='success')])
    report = ConclusionReport(ReportScope(1, 1, 1), scores, responses,
                              tuple(cc.build_model_issue_summaries(scores)), {},
                              runtime_tables={'live_evaluation_runs':[{'run_id':'r'}]})
    def forbidden(*a, **k):
        raise AssertionError('Public reading must not invoke providers or mutate data')
    monkeypatch.setattr('app.models.registry.get_text_provider', forbidden)
    monkeypatch.setattr('app.persistence.get_result_store', forbidden)
    monkeypatch.setattr(workbench, 'load_workbench_source', lambda _: workbench.cd.ConclusionSource(True, report))
    app = AppTest.from_string('''
import streamlit as st
from types import SimpleNamespace
import pandas as pd
from src.ui.navigation import PAGES, render_sidebar_navigation
base = SimpleNamespace(tasks=pd.DataFrame([{'case_id':'TEST-1', 'domain':'finance'}]), gold_answer_map={})
page = render_sidebar_navigation()
PAGES[page]({'base':base, 'data':base})
''')
    return app, scores


def test_three_public_destinations_and_separate_management():
    from src.ui.navigation import PRIMARY_NAV_ITEMS
    from src.ui.page_config import DEFAULT_PAGE_KEY
    assert PRIMARY_NAV_ITEMS == [('评测结果','conclusions'), ('案例审阅','review'), ('评测方法','case_study')]
    assert DEFAULT_PAGE_KEY == 'conclusions'


def test_results_to_case_preserves_feedback_and_missing_evidence(monkeypatch):
    app, scores = public_app(monkeypatch)
    before = scores.copy(deep=True)
    app.run()
    assert not app.exception
    assert app.session_state['current_page'] == 'conclusions'
    assert not app.get('file_uploader')
    app.button(key='results_review_case').click().run()
    assert not app.exception
    assert app.session_state['current_page'] == 'review'
    assert app.selectbox(key='review_case').value == 'TEST-1'
    text = '\n'.join(t.value for t in app.text)
    assert '遗漏核查条件。' in text
    assert '未核对回款。' in text
    assert '测试回答，没有回款资料。' in text
    assert any('未保存结构化要点评价与回答引文' in c.value for c in app.caption)
    assert app.query_params['case'] == ['TEST-1']
    pd.testing.assert_frame_equal(scores, before)


def test_case_route_refresh_retains_case_and_original_record(monkeypatch):
    app, _ = public_app(monkeypatch)
    app.query_params.update(page='review', case='TEST-1', model='test-model', run='r')
    app.run()
    assert not app.exception
    assert app.selectbox(key='review_case').value == 'TEST-1'
    assert app.session_state['current_page'] == 'review'
    assert any('遗漏核查条件。' in t.value for t in app.text)


def test_method_page_has_no_result_or_sample_management_forms(monkeypatch):
    app, _ = public_app(monkeypatch)
    app.query_params['page'] = 'case_study'
    app.run()
    assert not app.exception
    assert not app.selectbox
    assert not app.get('file_uploader')
    assert not app.dataframe
    assert not any('遗漏核查条件。' in t.value for t in app.text)


def test_method_display_does_not_repeat_leads_or_prompt_boundary():
    from src.ui.case_study import CASE_STUDY_SECTIONS, _section_body_html
    base = SimpleNamespace(tasks=pd.DataFrame([{'case_id':'x', 'domain':'finance'}]))
    rendered = [_section_body_html(section, base) for section in CASE_STUDY_SECTIONS]
    assert 'report-method-lead' not in ''.join(rendered)
    assert '被测模型不会看到专业标准答案' not in rendered[2]
    assert '被测模型只看到任务题' in rendered[1]
    assert '当前样本库包含 1 条' in rendered[0]


def test_run_maintenance_route_opens_sample_management():
    app = AppTest.from_string('''
import streamlit as st
from src.ui.test_run import _render_evaluation_maintenance
_render_evaluation_maintenance()
''').run()
    assert not app.exception
    app.button(key='test_run_maintenance_open_samples').click().run()
    assert not app.exception
    assert app.query_params['page'] == ['samples']
    assert app.session_state['management_section'] == '专业样本'
