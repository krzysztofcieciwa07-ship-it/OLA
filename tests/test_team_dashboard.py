"""The owner dashboard presents existing OLA/NINA/IGOR roles without fake proof."""
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.main import app


class _DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.labels = set()
        self.scripts = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "label" and attributes.get("for"):
            self.labels.add(attributes["for"])
        if tag == "script":
            self._in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts.append(data)


def test_owner_dashboard_displays_real_roles_and_unverified_initial_state():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    html = response.text
    for name in ("OLA", "NINA", "IGOR"):
        assert f">{name}<" in html
    assert "Niezależna weryfikacja" in html
    assert "PRODUKCJA NIEPOTWIERDZONA" in html
    assert 'id="runtime-status" class="status">NOT_RUN<' in html
    assert 'id="igor-status" class="status">UNKNOWN<' in html
    assert 'id="gate-status" class="status warn">NOT_APPROVED<' in html


def test_dashboard_uses_separate_authenticated_conversation_and_workflow():
    html = TestClient(app).get("/").text
    parsed = _DashboardParser()
    parsed.feed(html)
    script = "\n".join(parsed.scripts)
    assert {"key", "input"} <= parsed.labels
    assert {"run-button", "chat-button", "report-button", "result",
            "autogpt-button", "autogpt-poll-button"} <= parsed.ids
    assert 'fetch("/chat"' in script
    assert 'fetch("/nina-workflow"' in script
    assert 'fetch("/nina-autogpt"' in script
    assert 'window.confirm("Zlecić zadanie przez AutoGPT?' in script
    assert 'crypto.randomUUID()' in script
    assert 'pendingExternalOperation' in script
    assert 'requested_tools:["llm_agent"]' in script
    assert "Object.entries(body.results)" in script
    assert 'Authorization:`Bearer ${keyInput.value.trim()}`' in script
    assert '"X-API-Key":data.key' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert '/approve' not in script  # Human Gate remains a separate authorized action.


def test_parallel_workflow_remains_disabled_without_feature_gate(monkeypatch):
    monkeypatch.delenv("OLA_PARALLEL_WORKFLOWS_ENABLED", raising=False)
    response = TestClient(app).post("/nina-workflow", json={"task": "research"})
    assert response.status_code == 401
