from streamlit.testing.v1 import AppTest
from test_final_review_ux import review_app  # noqa: F401
from test_public_interactive_preview import preview_app  # noqa: F401


def test_run_button_is_primary_and_no_key_browse_does_not_execute(preview_app,monkeypatch):  # noqa: F811
    from app.services import public_run
    calls=[]
    monkeypatch.setattr(public_run.sf,'is_configured',lambda:False)
    monkeypatch.setattr(public_run,'run_public_evaluation',lambda *a,**k:calls.append(a))
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    assert not at.exception
    assert at.button(key='public_prepare_evaluation').disabled
    assert at.button(key='public_prepare_evaluation').proto.type=='primary'
    assert not [b for b in at.button if b.key=='public_start_evaluation']
    at.multiselect(key='preview_cases').set_value(['TEST-1','TEST-2']).run()
    assert not calls


def test_explicit_click_submits_multiple_samples_and_models_once(preview_app,monkeypatch):  # noqa: F811
    from app.services import public_run
    monkeypatch.setattr(public_run.sf,'is_configured',lambda:True)
    calls=[]
    def execute(base,cases,models,**kwargs):
        calls.append((cases,models,kwargs.get('temperature'),kwargs.get('max_tokens')))
        raise PermissionError('今日全站评测额度已不足')
    monkeypatch.setattr(public_run,'run_public_evaluation',execute)
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    assert not calls
    at.multiselect(key='preview_cases').set_value(['TEST-1','TEST-2']).run()
    at.number_input(key='preview_temperature').set_value(0.4).run()
    at.number_input(key='preview_max_tokens').set_value(2048).run()
    assert not calls
    at.button(key='public_prepare_evaluation').click().run()
    assert not calls
    assert at.button(key='public_start_evaluation').label=='确认并开始评测'
    at.button(key='public_start_evaluation').click().run()
    assert not at.exception
    assert calls==[(['TEST-1','TEST-2'],['model-a','model-b'],0.4,2048)]
    assert any('额度已不足' in e.value for e in at.warning)


def test_forged_job_ticket_never_executes(monkeypatch):
    from app.services import public_run
    monkeypatch.setattr(public_run,'read_public_job',lambda *a: (_ for _ in ()).throw(PermissionError('任务不属于当前会话')))
    at=AppTest.from_string('from src.ui.public_run import render_owned_job\nrender_owned_job(None)').run()
    at.query_params.update(public_job='old-history',public_ticket='fake')
    at.run()
    assert not at.exception
    assert any('不属于' in e.value for e in at.warning)
    assert not [b for b in at.button if b.key=='public_continue_evaluation']


def test_confirmation_cancel_and_refresh_never_execute(preview_app,monkeypatch):  # noqa: F811
    from app.services import public_run
    monkeypatch.setattr(public_run.sf,'is_configured',lambda:True)
    calls=[]
    monkeypatch.setattr(public_run,'run_public_evaluation',lambda *a,**k:calls.append(a))
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.run()
    at.button(key='public_prepare_evaluation').click().run()
    at.run()
    assert not calls
    at.button(key='public_cancel_confirmation').click().run()
    at.run()
    assert not calls and not at.exception
    assert not [b for b in at.button if b.key=='public_start_evaluation']
    at.button(key='public_prepare_evaluation').click().run()
    at.number_input(key='preview_temperature').set_value(0.2).run()
    assert not calls and not at.exception
    assert not [b for b in at.button if b.key=='public_start_evaluation']


def test_legacy_preview_token_limit_migrates_without_execution(preview_app,monkeypatch):  # noqa: F811
    from app.services import public_run
    calls=[]
    monkeypatch.setattr(public_run,'run_public_evaluation',lambda *a,**k:calls.append(a))
    at,_=preview_app
    at.query_params['page']='evaluation_preview'
    at.session_state.public_preview_config={'max_tokens':32768}
    at.session_state.preview_max_tokens=32768
    at.run()
    assert not at.exception
    assert at.number_input(key='preview_max_tokens').value==4096
    assert not calls
    at.number_input(key='preview_temperature').set_value(0.4).run()
    assert not any('default value' in warning.value or 'Session State API' in warning.value for warning in at.warning)
