"""Reading-order and public-demo contracts on isolated historical records."""
from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app, visible  # noqa: F401
from test_home_case_selection import home_app  # noqa: F401
from test_public_interactive_preview import preview_app  # noqa: F401


def test_home_problem_then_answer_then_rating_and_collapsed_selection(home_app):  # noqa: F811
    at,_=home_app
    at.run()
    assert not at.exception
    assert at.title[0].value=='专业场景大模型评测'
    drawer=next(e for e in at.expander if e.label=='切换案例')
    assert not drawer.proto.expanded
    assert at.selectbox(key='portfolio_home_case').value=='TEST-1'
    assert at.selectbox(key='portfolio_home_record').value==('test-r1','model-a','s1')
    positions={}
    for i,node in enumerate(at.main):
        value=str(getattr(node,'value',''))
        for key,phrase in [('task','当次任务材料'),('answer','原始回答 s1'),('rating','AI评分：80')]:
            if phrase in value:
                positions.setdefault(key,i)
    assert positions['task']<positions['answer']<positions['rating']
    assert '不得冒充历史的当前标准' not in visible(at)
    assert at.button(key='portfolio_open_case').label=='查看完整案例 →'


def test_demo_has_real_history_action_and_no_disabled_run(preview_app):  # noqa: F811
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.session_state['preview_stage']='配置评测'  # old bookmarked session
    at.run()
    assert not at.exception
    assert at.title[0].value=='评测流程演示'
    assert at.radio(key='preview_stage').value=='配置示例'
    assert not [b for b in at.button if b.key=='preview_real_start']
    assert at.button(key='preview_to_history').proto.type=='primary'
    assert '不会生成新回答或重新计算历史评分' in visible(at)
    at.number_input(key='preview_temperature').set_value(0.4).run()
    at.button(key='preview_to_history').click().run()
    assert at.radio(key='preview_stage').value=='历史运行'


def test_public_library_no_draft_and_secondary_standard_collapsed(preview_app):  # noqa: F811
    at,_=preview_app
    at.query_params['page']='sample_preview'
    at.session_state['preview_sample_mode']='新增样本预览'
    at.run()
    assert not at.exception
    assert len(at.selectbox)==2 and not at.text_input and not at.text_area
    assert not [b for b in at.button if str(b.key).startswith('preview_draft') or b.key=='preview_save_sample']
    assert not [r for r in at.radio if r.key=='preview_sample_mode']
    assert '当前标准 TEST-1' in visible(at)
    assert '核对材料' in visible(at) and '编造' in visible(at)
    assert [e.label for e in at.expander]==['依据与适用边界']
    assert not at.expander[0].proto.expanded


def test_public_cannot_directly_render_draft(monkeypatch):
    monkeypatch.delenv('FINDUEVAL_MODE',raising=False)
    at=AppTest.from_string('from src.ui.public_preview import _render_draft\n_render_draft()').run()
    assert not at.exception and not at.text_input and not at.text_area
    assert any('仅在受控管理环境' in e.value for e in at.info)


def test_legacy_feedback_is_concise_and_full_reason_stays_in_case(home_app):  # noqa: F811
    at,_=home_app
    at.run()
    assert 'accuracy_score' not in visible(at)
    at.button(key='portfolio_open_case').click().run()
    assert not at.exception
    assert '各维度评分' in visible(at)
    assert [e.label for e in at.expander]==['查看完整评价依据','原始技术记录']


def test_missing_saved_answer_does_not_invent_excerpt(home_app,monkeypatch):  # noqa: F811
    monkeypatch.setattr('src.ui.portfolio._formal_response_for_score',lambda *_:{})
    at,_=home_app
    at.run()
    assert not at.exception
    assert '历史回答未保存，无法展示回答节选。' in visible(at)
    assert '原始回答' not in visible(at)


def test_library_selection_survives_navigation_and_refresh(preview_app):  # noqa: F811
    at,_=preview_app
    at.query_params['page']='sample_preview'
    at.run()
    at.selectbox(key='preview_sample_domain').set_value('Legal').run()
    assert at.selectbox(key='preview_sample_case').value=='TEST-2'
    at.button(key='public_nav_conclusions').click().run()
    at.button(key='public_nav_sample_preview').click().run()
    assert at.selectbox(key='preview_sample_case').value=='TEST-2'
    fresh=AppTest.from_file(at._script_path)
    fresh.query_params.update(dict(at.query_params))
    fresh.run()
    assert not fresh.exception
    assert fresh.selectbox(key='preview_sample_domain').value=='Legal'
    assert fresh.selectbox(key='preview_sample_case').value=='TEST-2'
