"""Regression guards for the existing AURORA UI reliability contract."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_file_preview_warns_without_calling_relative_api():
    assert 'id="runtimeGuidance"' in HTML
    assert "const filePreview=location.protocol==='file:'" in HTML
    assert "if(filePreview)throw new Error(" in HTML
    assert "if(filePreview){applyHealth(false);" in HTML
    assert "http://127.0.0.1:18080/" in HTML


def test_chat_history_is_bounded_to_server_contract():
    # Server allows at most 20 messages: 18 prior + new user + next response.
    assert "session.messages.slice(-18)" in HTML
    assert "const next=[...session.messages,{role:'user'" not in HTML


def test_local_executor_connection_revoked_on_any_token_edit():
    assert "const before=epoch, tokenAtStart=token" in HTML
    assert "if(before!==epoch || $('localToken').value.trim()!==tokenAtStart)" in HTML
    assert "for(const controller of inflight)controller.abort()" in HTML
    assert "actions.clear()" in HTML
    assert 'id="localRun" disabled' in HTML


def test_mobile_status_is_not_hidden_and_navigation_has_keyboard_semantics():
    assert ".cc-agents{display:flex;flex-wrap:wrap;grid-column:auto}" in HTML
    assert "btn.setAttribute('aria-current','page')" in HTML
    assert "prefers-reduced-motion: reduce" in HTML
