"""Public previews are interactive projections, never workflows or persistence."""
import json

import pytest
from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app, visible  # noqa: F401


@pytest.fixture
def preview_app(review_app, monkeypatch):  # noqa: F811
    _, report = review_app
    monkeypatch.delenv('FINDUEVAL_MODE', raising=False)
    monkeypatch.setattr('app.services.dataset_service.get_testable_rubric_dimensions',lambda: [
        dict(field='accuracy_score',name='准确性',full_mark=30,full_mark_standard='判断准确',deduction_rules='错误扣分')])
    def forbidden(*a, **k):
        raise AssertionError('Preview attempted a model call or persistence')
    for name in ('generate_response','list_models','check_connectivity'):
        monkeypatch.setattr('app.models.siliconflow.SiliconFlowProvider.'+name,forbidden)
    monkeypatch.setattr('app.services.sample_repository.load_samples',forbidden)
    at = AppTest.from_string('''
import pandas as pd
from types import SimpleNamespace
from src.ui.navigation import PAGES, render_sidebar_navigation
base = SimpleNamespace(tasks=pd.DataFrame([
 dict(case_id='TEST-1',title='收入任务',domain='Financial',scenario='收入核查',question='核对收入',context='已有材料',status='active'),
 dict(case_id='TEST-2',title='法律任务',domain='Legal',scenario='合同核查',question='核对合同',context='已有条款',status='active')]),
 gold_answer_map={c:dict(core_conclusion='当前标准 '+c,must_have_points=['核对材料'],unacceptable_errors=['编造'],boundary_conditions='仅限材料') for c in ['TEST-1','TEST-2']})
PAGES[render_sidebar_navigation()]({'base':base,'data':base})
''')
    return at, report


def test_home_exposes_product_operations_without_dashboard(preview_app):
    at,_=preview_app
    at.run()
    assert not at.exception
    assert {'评测结果','评测流程','样本库'} <= {b.label for b in at.button}
    assert not {'体验评测流程','查看样本库'} & {b.label for b in at.button}
    assert not at.metric and not at.dataframe
    at.button(key='public_nav_evaluation_preview').click().run()
    assert not at.exception
    assert at.query_params['page'] == ['evaluation_preview']
    assert {'配置评测','历史运行','查看结果'} == set(at.radio(key='preview_stage').options)
    assert not [b for b in at.button if b.key=='preview_home']
    at.button(key='public_nav_sample_preview').click().run()
    assert at.query_params['page']==['sample_preview']
    assert not [b for b in at.button if b.key=='sample_preview_home']


def test_public_navigation_preserves_each_pages_record_and_refresh(preview_app):
    at,_=preview_app
    at.run()
    at.selectbox(key='portfolio_home_case').set_value('TEST-2').run()
    at.selectbox(key='portfolio_home_record').set_value(('test-r1','model-b','s4')).run()
    at.button(key='public_nav_evaluation_preview').click().run()
    at.radio(key='preview_stage').set_value('查看结果').run()
    at.selectbox(key='preview_history_run').set_value('test-r2').run()
    at.selectbox(key='preview_history_record').set_value(('test-r2','model-a','s5','TEST-1')).run()
    at.button(key='public_nav_sample_preview').click().run()
    at.button(key='public_nav_conclusions').click().run()
    assert not at.exception
    assert at.query_params['score']==['s4']
    assert '原始回答 s4' in visible(at)
    fresh=AppTest.from_file(at._script_path)
    fresh.query_params.update(dict(at.query_params))
    fresh.run()
    assert '原始回答 s4' in visible(fresh)
    at.button(key='public_nav_evaluation_preview').click().run()
    assert at.radio(key='preview_stage').value=='查看结果'
    assert at.selectbox(key='preview_history_run').value=='test-r2'
    assert at.selectbox(key='preview_history_record').value==('test-r2','model-a','s5','TEST-1')


def test_case_detail_stays_in_parent_navigation_and_returns_exact_record(preview_app):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results',history='test-r2')
    at.run()
    at.button(key='preview_review_record').click().run()
    assert at.button(key='public_nav_evaluation_preview').proto.type=='secondary'
    at.button(key='public_nav_evaluation_preview').click().run()
    assert not at.exception
    assert at.query_params['score']==['s5']
    assert at.selectbox(key='preview_history_record').value==('test-r2','model-a','s5','TEST-1')


def test_navigation_does_not_erase_invalid_result_link(preview_app):
    at,_=preview_app
    at.query_params.update(page='conclusions',case='TEST-1',run='test-r2',model='model-a',score='missing')
    at.run()
    at.button(key='public_nav_sample_preview').click().run()
    at.button(key='public_nav_conclusions').click().run()
    assert any('无法定位' in e.value for e in at.error)
    assert '原始回答' not in visible(at)


def test_navigation_keeps_evaluation_config_when_visiting_library(preview_app):
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    at.multiselect(key='preview_models').set_value(['model-b']).run()
    at.multiselect(key='preview_cases').set_value(['TEST-2']).run()
    at.number_input(key='preview_temperature').set_value(0.4).run()
    at.button(key='public_nav_sample_preview').click().run()
    at.button(key='public_nav_evaluation_preview').click().run()
    assert not at.exception
    assert at.multiselect(key='preview_models').value==['model-b']
    assert at.multiselect(key='preview_cases').value==['TEST-2']
    assert at.number_input(key='preview_temperature').value==0.4
    assert at.button(key='preview_real_start').disabled


def test_result_detail_navigation_retains_selected_score(preview_app):
    at,_=preview_app
    at.query_params.update(page='conclusions',case='TEST-2',run='test-r1',model='model-b',score='s4')
    at.run()
    at.button(key='portfolio_open_case').click().run()
    assert at.button(key='public_nav_conclusions').proto.type=='secondary'
    at.button(key='public_nav_conclusions').click().run()
    assert not at.exception
    assert at.query_params['score']==['s4']
    assert '原始回答 s4' in visible(at)


def test_config_plan_changes_without_calling_model_or_saving(preview_app):
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    assert not at.exception
    at.multiselect(key='preview_models').set_value(['model-a','model-b'])
    at.multiselect(key='preview_cases').set_value(['TEST-1','TEST-2']).run()
    assert '2个样本 × 2个模型 = 4个回答任务' in visible(at)
    assert all(label.startswith(('TEST-1 · ', 'TEST-2 · ')) for label in at.multiselect(key='preview_cases').options)
    assert at.button(key='preview_real_start').disabled
    assert '不会发起模型调用' in visible(at)
    at.number_input(key='preview_temperature').set_value(0.3).run()
    at.radio(key='preview_stage').set_value('历史运行').run()
    at.radio(key='preview_stage').set_value('配置评测').run()
    assert at.multiselect(key='preview_models').value == ['model-a','model-b']
    assert at.number_input(key='preview_temperature').value == 0.3


def test_results_are_original_history_and_open_exact_record(preview_app):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results')
    at.run()
    assert not at.exception
    at.selectbox(key='preview_history_run').set_value('test-r2').run()
    assert len(at.selectbox(key='preview_history_record').options)==1
    assert '40' in str(at.dataframe[0].value)
    at.button(key='preview_review_record').click().run()
    assert at.query_params['score']==['s5'] and at.query_params['run']==['test-r2']
    assert '原始回答 s5' in visible(at)
    assert '不得冒充历史' not in visible(at)


def test_samples_show_current_standard_without_historical_claim(preview_app):
    at,_=preview_app
    at.query_params['page']='sample_preview'
    at.run()
    assert not at.exception
    at.selectbox(key='preview_sample_domain').set_value('Legal').run()
    assert at.selectbox(key='preview_sample_case').value == 'TEST-2'
    assert '核对合同' in visible(at) and '当前标准 TEST-2' in visible(at)
    assert '法律任务' in visible(at)
    assert '当前题库' in visible(at)


def test_new_sample_form_preview_has_no_persistence(preview_app):
    at,_=preview_app
    at.query_params['page']='sample_preview'
    at.run()
    at.radio(key='preview_sample_mode').set_value('新增样本预览').run()
    assert not at.exception
    assert at.button(key='preview_save_sample').disabled
    for key,value in {'id':'DRAFT-X','title':'自填标题','question':'自填任务','context':'自填材料','core':'自填标准','must':'核对材料','forbidden':'编造','boundary':'仅限所填材料'}.items():
        fields = at.text_input if key in {'id','title'} else at.text_area
        fields(key='preview_draft_'+key).set_value(value)
    at.button(key='preview_draft_submit').click().run()
    assert not at.exception
    assert '自填任务' in visible(at) and '自填标准' in visible(at)
    assert '自填标题' in visible(at)
    assert '未保存' in visible(at)
    payload=at.session_state['public_sample_draft']
    assert payload['task']['case_id']=='DRAFT-X'
    assert json.loads(payload['gold'])['core_conclusion']=='自填标准'
    at.radio(key='preview_sample_mode').set_value('浏览样本').run()
    assert 'DRAFT-X' not in at.selectbox(key='preview_sample_case').options


def test_empty_history_does_not_invent_progress_or_results(preview_app,monkeypatch):
    from src.ui import workbench
    at,_=preview_app
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(False,None,message='不可用'))
    at.query_params.update(page='evaluation_preview',stage='results')
    at.run()
    assert not at.exception
    assert '暂无可读取的正式历史运行' in visible(at)
    assert not at.dataframe


def test_failed_only_formal_run_is_visible_and_mock_run_is_excluded(preview_app):
    import copy
    at,report=preview_app
    original=copy.deepcopy(report.runtime_tables)
    try:
        report.runtime_tables['live_evaluation_runs'].extend([
            dict(run_id='failed-run',provider='real-service',created_at='2026-10-02'),
            dict(run_id='mock-run',provider='mock',created_at='2026-10-03')])
        report.runtime_tables['live_run_responses'].append(dict(run_id='failed-run',case_id='TEST-1',model_name='model-a',run_status='failed',error_message='保存的超时原因'))
        report.runtime_tables['live_run_queue']=[dict(run_id='failed-run',case_id='TEST-1',model_id='model-a',status='failed')]
        at.query_params.update(page='evaluation_preview',stage='history')
        at.run()
        assert not at.exception
        assert any('2026-10-02' in label for label in at.selectbox(key='preview_history_run').options)
        assert all('2026-10-03' not in label for label in at.selectbox(key='preview_history_run').options)
        at.selectbox(key='preview_history_run').set_value('failed-run').run()
        assert any('失败' in e.value for e in at.warning)
        at.radio(key='preview_stage').set_value('查看结果').run()
        assert not at.exception
        assert '尚无有效评分记录' in visible(at)
        assert not [b for b in at.button if b.key=='preview_review_record']
    finally:
        report.runtime_tables.clear()
        report.runtime_tables.update(original)


def test_history_case_returns_to_the_selected_run(preview_app):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results')
    at.run()
    at.selectbox(key='preview_history_run').set_value('test-r2').run()
    at.button(key='preview_review_record').click().run()
    assert at.button(key='portfolio_return_home').label=='← 返回评测流程'
    at.button(key='portfolio_return_home').click().run()
    assert not at.exception
    assert at.query_params['page']==['evaluation_preview']
    assert at.selectbox(key='preview_history_run').value=='test-r2'
    assert at.radio(key='preview_stage').value=='查看结果'


def test_history_url_preserves_selected_batch_without_session_state(preview_app):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results',history='test-r2')
    at.run()
    assert not at.exception
    assert at.selectbox(key='preview_history_run').value=='test-r2'
    at.selectbox(key='preview_history_run').set_value('test-r1').run()
    assert at.query_params['history']==['test-r1']


def test_invalid_history_url_does_not_silently_display_other_scores(preview_app):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results',history='missing')
    at.run()
    assert not at.exception
    assert any('无法定位' in e.value for e in at.warning)
    assert not at.dataframe


def test_stage_action_buttons_advance_without_session_state_warning(preview_app):
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    at.button(key='preview_to_history').click().run()
    assert not at.exception
    assert at.radio(key='preview_stage').value=='历史运行'
    assert not any('Session State API' in e.value for e in at.warning)
    at.button(key='preview_to_results').click().run()
    assert at.radio(key='preview_stage').value=='查看结果'
    assert not any('Session State API' in e.value for e in at.warning)


@pytest.mark.parametrize('direct_link',[False,True])
def test_return_keeps_the_exact_selected_score_not_the_default_case(preview_app,direct_link):
    at,_=preview_app
    identity=('test-r2','model-a','s5','TEST-1') if direct_link else ('test-r1','model-b','s4','TEST-2')
    if direct_link:
        at.query_params.update(page='review',case='TEST-1',run='test-r2',model='model-a',score='s5',origin='evaluation_preview')
        at.run()
    else:
        at.query_params.update(page='evaluation_preview',stage='results',history='test-r1')
        at.run()
        at.selectbox(key='preview_history_record').set_value(identity).run()
        at.button(key='preview_review_record').click().run()
    assert '原始回答 '+identity[2] in visible(at)
    at.button(key='portfolio_return_home').click().run()
    assert not at.exception
    assert at.selectbox(key='preview_history_record').value==identity


def test_case_action_reads_latest_widget_selection_before_rerender(monkeypatch):
    from src.ui import public_preview
    calls=[]
    monkeypatch.setattr(public_preview,'open_case_review',lambda *args:calls.append(args))
    at=AppTest.from_string('''
import streamlit as st
from src.ui.public_preview import _open_record
st.session_state.preview_history_run='latest-run'
st.session_state.preview_history_record=('latest-run','latest-model','latest-score','latest-case')
_open_record(dict(run_id='previous-run',eval_model='previous-model',score_run_id='previous-score',case_id='previous-case'))
''').run()
    assert not at.exception
    assert calls==[('latest-case','latest-model','latest-run','latest-score')]


@pytest.mark.parametrize('missing',[False,True])
def test_full_reload_locates_exact_score_or_reports_missing(preview_app,missing):
    at,_=preview_app
    at.query_params.update(page='evaluation_preview',stage='results',history='test-r1',
        run='test-r1',model='model-b',score='missing' if missing else 's4',case='TEST-2')
    at.run()
    assert not at.exception
    if missing:
        assert any('无法定位链接中的评分记录' in e.value for e in at.warning)
        assert not any(b.key=='preview_review_record' for b in at.button)
    else:
        assert at.selectbox(key='preview_history_record').value==('test-r1','model-b','s4','TEST-2')
