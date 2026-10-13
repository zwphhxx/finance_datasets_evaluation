"""Public reading contracts on isolated records; provider/store access is forbidden."""
import json

import pytest
from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app, visible  # noqa: F401


@pytest.fixture(autouse=True)
def public_environment(monkeypatch):
    monkeypatch.delenv('FINDUEVAL_MODE', raising=False)


def test_public_home_has_one_reading_path_without_dashboard(review_app):  # noqa: F811
    at, _ = review_app
    at.run()
    assert not at.exception
    assert '评测结果' in [e.value for e in at.title]
    assert '2个专业任务' in visible(at)
    assert not at.metric and not at.multiselect and not at.dataframe
    assert [s.label for s in at.selectbox] == ['专业案例', '模型与测试日期']
    assert not [b for b in at.button if str(b.key).startswith('top_nav_')]
    assert [b.label for b in at.button] == ['评测结果', '评测流程', '样本库', '查看完整案例']
    assert not at.expander
    assert '当前任务设计' in visible(at)
    assert '历史回答节选' in visible(at)
    assert '完整评价证据' in visible(at)


def test_featured_link_retains_exact_identity_and_returns_to_case_anchor(review_app):  # noqa: F811
    at, report = review_app
    at.run()
    at.button(key='portfolio_open_case').click().run()
    assert not at.exception
    score_id = at.query_params['score'][0]
    selected = next(r for r in report.runtime_tables['live_run_scores'] if r['score_run_id'] == score_id)
    assert at.query_params['run'] == [selected['run_id']]
    assert at.query_params['model'] == [selected['eval_model']]
    assert at.query_params['case'] == [selected['case_id']]
    assert '原始回答 '+score_id in visible(at)
    assert not at.selectbox and not at.multiselect
    assert [e.label for e in at.expander] == ['查看完整评价依据', '原始技术记录']
    assert all(not e.proto.expanded for e in at.expander)
    assert '历史参考判断' in visible(at)
    assert '不得冒充历史的当前标准' not in visible(at)
    at.button(key='portfolio_return_home').click().run()
    assert at.query_params['page'] == ['conclusions']
    assert at.query_params['score'] == [score_id]
    assert '_fde_scroll_request_sequence' in at.session_state
    assert at.session_state['_fde_pending_scroll_target']['target'] == '#fde-featured-case'


@pytest.mark.parametrize('page', ['conclusions', 'case_study'])
def test_legacy_public_result_and_method_links_open_the_portfolio(review_app, page):  # noqa: F811
    at, _ = review_app
    at.query_params['page'] = page
    at.run()
    assert not at.exception
    assert at.query_params['page'] == ['conclusions']
    assert [e.value for e in at.title] == ['评测结果']
    assert len(at.selectbox) == 2 and not at.metric


@pytest.mark.parametrize('change', [{'case': 'missing'}, {'model': 'missing'}, {'run': 'missing'}, {'score': 'missing'}])
def test_invalid_legacy_case_link_has_no_unrelated_answer(review_app, change):  # noqa: F811
    at, _ = review_app
    at.query_params.update(page='review', case='TEST-1', model='model-a', run='test-r2', score='s5')
    at.query_params.update(change)
    at.run()
    assert not at.exception
    assert any('无法定位' in e.value for e in at.error)
    assert '原始回答' not in visible(at)
    assert at.button(key='portfolio_return_home').label == '← 返回评测结果'


def test_ambiguous_case_only_link_requires_exact_record(review_app):  # noqa: F811
    at, _ = review_app
    at.query_params.update(page='review', case='TEST-1')
    at.run()
    assert any('无法定位' in e.value for e in at.error)
    assert '原始回答' not in visible(at)


def test_record_link_without_page_still_resolves_the_original_case(review_app):  # noqa: F811
    at, _ = review_app
    at.query_params.update(case='TEST-1',model='model-a',run='test-r2',score='s5')
    at.run()
    assert not at.exception
    assert '原始回答 s5' in visible(at)
    assert at.query_params['page'] == ['review']


def test_public_detail_keeps_all_critical_errors_and_original_long_answer():
    checks = [dict(kind='forbidden', status='not_met', requirement=f'重大错误{i}', quote='原文', reason='已有影响') for i in range(4)]
    at = AppTest.from_string(f'''
from src.ui.trust_details import render_portfolio_evaluation
render_portfolio_evaluation(answer={'原文' * 1800!r}, score={{'total_score': 12, 'checks_json': {json.dumps(checks,ensure_ascii=False)!r}}},
 dimensions=[{{'field':'accuracy_score','name':'准确性','full_mark':30}}], gold={{'core_conclusion':'当次标准'}}, metadata={{}})
''').run()
    assert not at.exception
    assert '原文' * 1800 in visible(at)
    for i in range(4):
        assert sum(f'重大错误{i}' in e.value for e in at.warning) >= 2
    assert [e.label for e in at.expander] == ['展开完整回答', '查看完整评价依据', '原始技术记录']
    assert '满分 30' in visible(at)


def test_selected_case_keeps_its_original_queue_and_excludes_other_records(review_app):  # noqa: F811
    at, report = review_app
    original = report.runtime_tables.copy()
    report.runtime_tables['live_run_queue'] = [
        dict(run_id='test-r1',case_id='TEST-1',model_id='model-a',status='success'),
        dict(run_id='test-r1',case_id='TEST-1',model_id='model-b',status='failed'),
    ]
    try:
        at.query_params.update(page='review',case='TEST-1',model='model-a',run='test-r1',score='s1')
        at.run()
        raw = next(e for e in at.json if '"related"' in e.value)
        payload = json.loads(raw.value)
        assert payload['related']['live_run_queue'] == [dict(run_id='test-r1',case_id='TEST-1',model_id='model-a',status='success')]
    finally:
        report.runtime_tables.clear()
        report.runtime_tables.update(original)


def test_material_and_quote_gaps_are_not_hidden_by_a_single_matching_quote():
    from src.ui.trust_details import evidence_gaps
    checks = [dict(quote='原文'),dict(quote='不存在')]
    gaps = evidence_gaps({'question':'已保存题目'}, {'core_conclusion':'已保存标准'},
                         {'review_note':'原始理由','checks_json':json.dumps(checks)}, '原文')
    assert '业务背景' in gaps
    assert '部分引文无法核对' in gaps


def test_compatibility_placeholder_is_not_reported_as_saved_historical_material():
    from types import SimpleNamespace

    from src.ui.review import historical_task
    report = SimpleNamespace(runtime_tables={'live_evaluation_runs':[dict(run_id='r',evaluation_context_json='{}')]})
    task, gold, dimensions = historical_task(report,'c','r')
    assert task == {}
    assert gold is None and dimensions == []
