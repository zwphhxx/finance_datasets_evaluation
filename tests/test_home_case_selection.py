"""Homepage selectors use isolated formal history; no providers or writes."""
import copy
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app, visible  # noqa: F401


@pytest.fixture
def home_app(review_app, monkeypatch):  # noqa: F811
    monkeypatch.delenv('FINDUEVAL_MODE', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Homepage attempted provider access or persistence')
    for name in ('generate_response','list_models','check_connectivity'):
        monkeypatch.setattr('app.models.siliconflow.SiliconFlowProvider.'+name,forbidden)
    return review_app


def test_home_selects_only_scored_cases_and_preserves_default_policy(home_app):
    at,_=home_app
    at.run()
    assert not at.exception
    assert at.selectbox(key='portfolio_home_case').value=='TEST-1'
    assert len(at.selectbox(key='portfolio_home_case').options)==2
    assert all('UNSCORED' not in label for label in at.selectbox(key='portfolio_home_case').options)
    assert '合同履行核查 · TEST-2' in at.selectbox(key='portfolio_home_case').options
    assert at.selectbox(key='portfolio_home_record').value==('test-r1','model-a','s1')
    assert len(set(at.selectbox(key='portfolio_home_record').options))==3
    assert all('2026-10-01' in label for label in at.selectbox(key='portfolio_home_record').options)
    assert not at.metric and not at.dataframe


def test_case_and_model_switch_keep_exact_record_on_return_and_reload(home_app):
    at,_=home_app
    at.run()
    at.selectbox(key='portfolio_home_case').set_value('TEST-2').run()
    assert '原始回答 s2' in visible(at) and '遗漏合同条件' in visible(at)
    assert len(at.selectbox(key='portfolio_home_record').options)==2
    at.selectbox(key='portfolio_home_record').set_value(('test-r1','model-b','s4')).run()
    assert '原始回答 s4' in visible(at) and '尚缺时间边界' in visible(at)
    at.button(key='portfolio_open_case').click().run()
    assert at.query_params['origin']==['portfolio_home']
    assert at.query_params['case']==['TEST-2'] and at.query_params['score']==['s4']
    assert '原始回答 s4' in visible(at)
    at.button(key='portfolio_return_home').click().run()
    assert not at.exception
    assert at.selectbox(key='portfolio_home_case').value=='TEST-2'
    assert at.selectbox(key='portfolio_home_record').value==('test-r1','model-b','s4')
    fresh=AppTest.from_file(at._script_path)
    fresh.query_params.update(dict(at.query_params))
    fresh.run()
    assert not fresh.exception
    assert fresh.selectbox(key='portfolio_home_record').value==('test-r1','model-b','s4')
    assert '原始回答 s4' in visible(fresh)


@pytest.mark.parametrize('change',[{'case':'missing'},{'model':'missing'},{'run':'missing'},{'score':'missing'}])
def test_invalid_home_link_never_shows_an_unrelated_answer(home_app,change):
    at,_=home_app
    at.query_params.update(page='conclusions',case='TEST-1',run='test-r2',model='model-a',score='s5')
    at.query_params.update(change)
    at.run()
    assert not at.exception
    assert any('无法定位' in e.value for e in at.error)
    assert '原始回答' not in visible(at)
    at.button(key='portfolio_reset_selection').click().run()
    assert not at.exception
    assert at.selectbox(key='portfolio_home_case').value=='TEST-1'
    assert '原始回答 s1' in visible(at)


def test_home_mock_only_case_is_excluded(home_app,monkeypatch):
    at,report=home_app
    tables=copy.deepcopy(report.runtime_tables)
    tables['live_run_scores'].append(dict(run_id='test-r1',case_id='MOCK-ONLY',eval_model='model-a',score_run_id='mock',
        total_score=100,judge_status='success',judge_mode='mock'))
    tables['live_run_responses'].append(dict(run_id='test-r1',case_id='MOCK-ONLY',model_name='model-a',
        run_status='success',answer_text='Mock回答',run_mode='mock'))
    from src.ui import workbench
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(True,replace(report,runtime_tables=tables)))
    at.run()
    assert not at.exception
    assert all('MOCK-ONLY' not in label for label in at.selectbox(key='portfolio_home_case').options)
    assert 'Mock回答' not in visible(at)


def test_home_prefers_scored_fd001_even_when_not_in_current_library(home_app,monkeypatch):
    at,report=home_app
    tables=copy.deepcopy(report.runtime_tables)
    for row in tables['live_run_scores']+tables['live_run_responses']:
        if row['case_id']=='TEST-2':
            row['case_id']='FD-001'
    from src.ui import workbench
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(True,replace(report,runtime_tables=tables)))
    at.run()
    assert not at.exception
    assert at.selectbox(key='portfolio_home_case').value=='FD-001'
    assert '原始回答 s2' in visible(at)
    assert '完整评价证据' in visible(at)


def test_empty_formal_history_retains_task_intro_without_score(home_app,monkeypatch):
    at,report=home_app
    tables=copy.deepcopy(report.runtime_tables)
    tables['live_run_scores']=[]
    tables['live_run_responses']=[]
    from src.ui import workbench
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(True,replace(report,runtime_tables=tables)))
    at.run()
    assert not at.exception
    assert not at.selectbox
    assert '尚无完整实测记录' in visible(at)
    assert '历史回答节选' not in visible(at)
    assert '原始回答' not in visible(at)


def test_repeated_model_scores_have_unique_labels_and_link_identity(home_app,monkeypatch):
    at,report=home_app
    tables=copy.deepcopy(report.runtime_tables)
    extra=dict(tables['live_run_scores'][0],score_run_id='s6',total_score=70,review_note='第二次评分反馈。')
    tables['live_run_scores'].append(extra)
    from src.ui import workbench
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _:workbench.cd.ConclusionSource(True,replace(report,runtime_tables=tables)))
    at.run()
    labels=at.selectbox(key='portfolio_home_record').options
    assert len(labels)==4 and len(set(labels))==4
    at.selectbox(key='portfolio_home_record').set_value(('test-r1','model-a','s6')).run()
    assert '第二次评分反馈' in visible(at)
    at.button(key='portfolio_open_case').click().run()
    assert at.query_params['score']==['s6']


def test_home_url_overrides_previous_selection(home_app):
    at,_=home_app
    at.run()
    at.query_params.update(page='conclusions',case='TEST-1',run='test-r2',model='model-a',score='s5')
    at.run()
    assert not at.exception
    assert at.selectbox(key='portfolio_home_record').value==('test-r2','model-a','s5')
    assert '原始回答 s5' in visible(at) and '错误认定回款正常' in visible(at)


def test_home_open_action_uses_current_widget_identity(monkeypatch):
    from src.ui import portfolio
    calls=[]
    monkeypatch.setattr(portfolio,'open_case_review',lambda *args:calls.append(args))
    at=AppTest.from_string('''
import streamlit as st
from src.ui.portfolio import _open_home_case
st.session_state.portfolio_home_case='latest-case'
st.session_state.portfolio_home_record=('latest-run','latest-model','latest-score')
_open_home_case(('old-case','old-run','old-model','old-score'))
''').run()
    assert not at.exception
    assert calls==[('latest-case','latest-model','latest-run','latest-score')]


def test_home_open_during_case_change_does_not_open_previous_record(monkeypatch):
    from src.ui import portfolio
    calls=[]
    monkeypatch.setattr(portfolio,'open_case_review',lambda *args:calls.append(args))
    at=AppTest.from_string('''
import streamlit as st
from src.ui.portfolio import _open_home_case
st.session_state.portfolio_home_case='new-case'
_open_home_case(('previous-case','previous-run','previous-model','previous-score'))
''').run()
    assert not at.exception
    assert calls==[]
    assert any('案例正在切换' in e.value for e in at.warning)


@pytest.mark.parametrize('key',['portfolio_home_case','portfolio_home_record'])
def test_clearing_a_home_selector_is_safe_and_does_not_show_an_unrelated_answer(home_app,key):
    at,_=home_app
    at.run()
    at.selectbox(key=key).set_value(None).run()
    assert not at.exception
    assert '原始回答' not in visible(at)
    assert any('请选择' in e.value for e in at.caption)


def test_home_score_follows_case_and_model_without_adding_rankings(home_app):
    at,_=home_app
    at.run()
    assert 'AI评分：80' in visible(at)
    at.selectbox(key='portfolio_home_case').set_value('TEST-2').run()
    assert 'AI评分：75' in visible(at)
    at.selectbox(key='portfolio_home_record').set_value(('test-r1','model-b','s4')).run()
    assert 'AI评分：85' in visible(at)
    assert '尚缺时间边界' in visible(at)
    assert not at.dataframe and not at.metric
    assert '排名' not in '\n'.join(e.value for e in at.subheader)


def _rating_app(score,dimensions=None,answer='原文'):
    return AppTest.from_string(f'''
from src.ui.portfolio import _render_home_rating
_render_home_rating({score!r}, {dimensions or []!r}, {answer!r})
''').run()


def test_home_rating_prioritizes_saved_deduction_dimensions():
    import json
    at=_rating_app(dict(total_score=45,accuracy_score=30,coverage_score=15,
        rationale=json.dumps(dict(accuracy_score='数据计算准确。',coverage_score='未覆盖第三方回款核查。'),ensure_ascii=False)),
        [dict(field='accuracy_score',name='准确性',full_mark=30),dict(field='coverage_score',name='覆盖度',full_mark=20)])
    assert not at.exception
    assert '关键扣分理由' in visible(at)
    assert '覆盖度：未覆盖第三方回款核查' in visible(at)
    assert '数据计算准确' not in visible(at)
    assert '满分 50' in visible(at)


def test_home_rating_keeps_every_saved_critical_error_and_quote_gap():
    import json
    checks=[dict(kind='forbidden',status='not_met',requirement=f'重大错误{i}',reason=f'原始影响{i}',quote='不匹配') for i in range(4)]
    at=_rating_app(dict(total_score=12,review_note='总评较好但有错误',checks_json=json.dumps(checks,ensure_ascii=False)))
    assert not at.exception
    for i in range(4):
        assert f'重大错误{i}' in visible(at) and f'原始影响{i}' in visible(at)
    assert any('引用不在模型回答原文' in e.value for e in at.warning)
    assert '历史满分未记录' in visible(at)


def test_legacy_rating_shows_original_feedback_without_inventing_deductions():
    import json
    at=_rating_app(dict(total_score=93,review_note='结论方向正确，但遗漏独立财务顾问核查。',
        rationale=json.dumps(dict(reasoning_score='初步结论表述过于绝对。',coverage_score='未提及详式权益变动报告书。'),ensure_ascii=False)))
    assert not at.exception
    text=visible(at)
    assert 'AI评分：93' in text and '历史满分未记录' in text
    assert '原始评分反馈' in text and '未保存逐项扣分对应关系' in text
    assert '遗漏独立财务顾问核查' in text and '未提及详式权益变动报告书' in text
    assert '扣7分' not in text and '未见突出问题' not in text


@pytest.mark.parametrize('rationale',[None,'裁判原始文本：遗漏核查时间边界。'])
def test_home_rating_retains_missing_reason_or_raw_rationale(rationale):
    at=_rating_app(dict(total_score=40,rationale=rationale))
    assert not at.exception
    text=visible(at)
    assert 'AI评分：40' in text
    assert ('裁判原始文本：遗漏核查时间边界' if rationale else '历史记录未保存评分理由') in text


def test_saved_full_score_is_feedback_not_a_missing_deduction_mapping():
    at=_rating_app(dict(total_score=30,accuracy_score=30,rationale={'accuracy_score':'关键数据引用准确。'}),
                   [dict(field='accuracy_score',name='准确性',full_mark=30)])
    assert not at.exception
    assert '满分 30' in visible(at)
    assert '未保存逐项扣分对应关系' not in visible(at)
    assert '关键数据引用准确' in visible(at)
