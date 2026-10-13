"""Synthetic, isolated UX regressions; never load production data or call providers."""
import copy
import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.services.comparison import comparison_for_runs
from app.services.conclusion_read_model import build_conclusion_report


@pytest.fixture
def review_app(monkeypatch):
    from dataclasses import replace

    from src.ui import management, workbench

    tasks = [dict(case_id=c, title=t, domain=d, task='核对材料后作初步判断', business_background='历史背景')
             for c, t, d in [('TEST-1', '收入真实性与回款异常', 'finance'), ('TEST-2', '合同履行核查', 'law')]]
    context = dict(samples=[dict(case_id=t['case_id'], task=t) for t in tasks],
                   gold=[dict(case_id='TEST-1', record={'core_conclusion':'历史参考判断',
                         'must_have_points':['核对回款'], 'unacceptable_errors':['直接认定正常'],
                         'boundary_conditions':'历史材料适用边界'})],
                   dimensions=[{'field':'accuracy_score','name':'准确性','full_mark':30}])
    runs = [dict(run_id=r, created_at='2026-10-01T10:00:00', provider='test-live',
                 service_endpoint=e, model_ids_json='["model-a","model-b"]' if r == 'test-r1' else '["model-a"]',
                 dataset_version='v', dataset_hash='hash', prompt_hash='prompt',
                 generation_parameters_json='{}', judge_parameters_json='{}',
                 evaluation_context_json=json.dumps(context, ensure_ascii=False))
            for r,e in [('test-r1','https://one.example'),('test-r2','https://two.example')]]
    scores = [dict(run_id=r, case_id=c, eval_model=m, score_run_id=s, total_score=n,
                   judge_status='success', accuracy_score=20, review_note=note)
              for r,c,m,s,n,note in [
                  ('test-r1','TEST-1','model-a','s1',80,'遗漏回款条件。'),
                  ('test-r1','TEST-2','model-a','s2',75,'遗漏合同条件。'),
                  ('test-r1','TEST-1','model-b','s3',90,'覆盖较完整。'),
                  ('test-r1','TEST-2','model-b','s4',85,'尚缺时间边界。'),
                  ('test-r2','TEST-1','model-a','s5',40,'错误认定回款正常。')]]
    responses = [dict(run_id=s['run_id'], case_id=s['case_id'], model_name=s['eval_model'],
                      run_status='success', answer_text='原始回答 '+s['score_run_id']) for s in scores]
    report = build_conclusion_report(scores_df=pd.DataFrame(scores), responses_df=pd.DataFrame(responses),
                                     tasks_df=pd.DataFrame(tasks), gold_map={}, dimensions=[])
    report = replace(report, comparison=comparison_for_runs(report.formal_scores, runs),
                     runtime_tables={'live_evaluation_runs':runs, 'live_run_scores':scores,
                                     'live_run_responses':responses})
    before = copy.deepcopy(report.runtime_tables)
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _: workbench.cd.ConclusionSource(True,report))
    def forbidden(*a, **k):
        raise AssertionError('Public review attempted a paid call or database operation')
    monkeypatch.setattr('app.models.registry.get_text_provider',forbidden)
    monkeypatch.setattr('app.persistence.get_result_store',forbidden)
    monkeypatch.setattr(management,'get_result_store',forbidden)
    app = AppTest.from_string('''
import pandas as pd
from types import SimpleNamespace
from src.ui.navigation import PAGES, render_sidebar_navigation
base = SimpleNamespace(tasks=pd.DataFrame([
 {'case_id':'UNSCORED','title':'当前未评测任务','domain':'finance'},
 {'case_id':'TEST-1','title':'当前题库已改标题','domain':'finance'}]),
 gold_answer_map={'TEST-1':{'core_conclusion':'不得冒充历史的当前标准'}})
PAGES[render_sidebar_navigation()]({'base':base,'data':base})
''')
    yield app, report
    assert before == report.runtime_tables


def visible(at):
    return '\n'.join(str(e.value) for kind in ('text','caption','markdown','subheader','info','warning','error') for e in getattr(at,kind))


def test_result_statistics_follow_filters_and_exclude_library_total(review_app):
    at, _ = review_app
    at.run()
    text = visible(at)
    assert '可比任务</dt><dd>1' in text
    assert '有效AI评分记录</dt><dd>5' in text
    assert '题库总量' not in text
    at.selectbox(key='comparison_task').set_value('TEST-2').run()
    text = visible(at)
    assert '有效AI评分记录</dt><dd>2' in text
    assert '当前筛选' in text


def test_each_feedback_targets_exact_run_model_case_and_score(review_app):
    at, _ = review_app
    at.run()
    assert '低分案例与评价依据' in visible(at)
    links = [b for b in at.button if b.label == '查看该案例']
    assert len(links) == 3  # model-a at two endpoints, model-b at one endpoint
    for button in links:
        fresh = AppTest.from_file(at._script_path)
        fresh.run()
        fresh.button(key=button.key).click().run()
        assert not fresh.exception
        score_id = fresh.query_params['score'][0]
        assert '原始回答 '+score_id in visible(fresh)
        assert fresh.selectbox(key='review_record').value[2] == score_id


@pytest.mark.parametrize('changes',[{'case':'missing'},{'model':'missing'},{'run':'missing'},{'score':'missing'}])
def test_invalid_deep_link_never_silently_opens_other_record(review_app,changes):
    at, _ = review_app
    at.query_params.update(page='review',case='TEST-1',model='model-a',run='test-r2',score='s5')
    at.query_params.update(changes)
    at.run()
    assert not at.exception
    assert any('无法定位' in e.value for e in at.error)
    assert '原始回答' not in visible(at)


def test_deep_link_overrides_previous_selection_and_round_trip_preserves_record(review_app):
    at, _ = review_app
    at.query_params.update(page='review',case='TEST-1',model='model-a',run='test-r1',score='s1')
    at.run()
    at.query_params.update(run='test-r2',score='s5')
    at.run()
    assert '原始回答 s5' in visible(at)
    at.button(key='top_nav_case_study').click().run()
    at.button(key='top_nav_review').click().run()
    assert at.selectbox(key='review_record').value == ('test-r2','model-a','s5')
    assert '原始回答 s5' in visible(at)


def test_scored_cases_first_friendly_labels_and_historical_standard(review_app):
    at, _ = review_app
    at.query_params['page'] = 'review'
    at.run()
    assert at.selectbox(key='review_case').value != 'UNSCORED'
    assert '收入真实性与回款异常 · TEST-1' in at.selectbox(key='review_case').options
    assert all('2026-10-01' in v for v in at.selectbox(key='review_record').options)
    assert len(set(at.selectbox(key='review_record').options)) == len(at.selectbox(key='review_record').options)
    text = visible(at)
    assert '历史参考判断' in text and '历史材料适用边界' in text
    assert '不得冒充历史的当前标准' not in text
    assert all(not e.proto.expanded for e in at.expander)


def test_ambiguous_link_requires_score_identity(review_app):
    at, report = review_app
    report.runtime_tables['live_run_scores'].append(dict(report.runtime_tables['live_run_scores'][0],score_run_id='another'))
    at.query_params.update(page='review',case='TEST-1',model='model-a',run='test-r1')
    try:
        at.run()
        assert any('无法定位' in e.value for e in at.error)
    finally:
        # Restore synthetic fixture; original production data is never loaded.
        report.runtime_tables['live_run_scores'].pop()


def test_major_error_prioritized_and_details_collapsed():
    checks = [dict(status='met',kind='must',requirement='正常评价点',quote='实际回答'),
              dict(status='partial',kind='must',requirement='一般遗漏'),
              dict(status='not_met',kind='forbidden',requirement='重大专业错误',quote='不存在的引文',reason='影响结论'),
              dict(status='not_met',kind='must',requirement='核对边界')]
    at = AppTest.from_string(f'''
from src.ui.trust_details import render_score_detail
render_score_detail(task={{'title':'案例','task':'任务','business_background':'背景'}},
 answer='实际回答', score={{'total_score':50,'checks_json':{json.dumps(checks,ensure_ascii=False)!r},
 'rationale':'{{"accuracy_score":"完整评分理由"}}'}},
 dimensions=[{{'field':'accuracy_score','name':'准确性','full_mark':30}}],key='priority')
''').run()
    assert not at.exception
    assert at.metric[0].label == 'AI评分'
    assert any('重大专业错误' in w.value for w in at.warning)
    assert any('引用不在' in w.value for w in at.warning)
    assert any('全部检查要点' in e.label for e in at.expander)
    assert all(not e.proto.expanded for e in at.expander)
    assert '完整评分理由' in visible(at)


def test_result_filter_survives_review_round_trip(review_app):
    at, _ = review_app
    at.run()
    at.selectbox(key='comparison_task').set_value('TEST-2').run()
    at.button(key='results_review_case').click().run()
    at.button(key='top_nav_conclusions').click().run()
    assert at.selectbox(key='comparison_task').value == 'TEST-2'
    assert '有效AI评分记录</dt><dd>2' in visible(at)


def test_very_long_answer_retained_in_normal_expander():
    answer = '超长历史回答。' * 600 + '末尾原始证据'
    at = AppTest.from_string(f'''
from src.ui.trust_details import render_score_detail
render_score_detail(task={{}}, answer={answer!r}, score={{}},dimensions=[],key='long')
''').run()
    assert any(e.label == '完整模型回答' and not e.proto.expanded for e in at.expander)
    assert any(t.value == answer for t in at.text)


def test_model_record_date_is_generation_run_date():
    from src.ui.review import _record_labels
    row = {'run_id':'r','eval_model':'m','score_run_id':'s','created_at':'2026-10-03'}
    assert _record_labels([row],{'r':{'created_at':'2026-10-01'}})[('r','m','s')] == 'm · 2026-10-01'


def test_empty_results_offer_public_tasks_without_import_requirement(monkeypatch):
    from src.ui import workbench
    monkeypatch.setattr(workbench,'load_workbench_source',lambda _: workbench.cd.ConclusionSource(True,None))
    at = AppTest.from_string('''
from types import SimpleNamespace
import pandas as pd
from src.ui.navigation import PAGES, render_sidebar_navigation
base=SimpleNamespace(tasks=pd.DataFrame([{'case_id':'TASK','title':'专业任务','domain':'finance'}]),gold_answer_map={})
PAGES[render_sidebar_navigation()]({'base':base})
''').run()
    assert any('暂未发布评测结果' in i.value for i in at.info)
    at.button(key='results_view_tasks').click().run()
    assert not at.exception
    assert at.session_state['current_page'] == 'review'
    assert not at.get('file_uploader')
