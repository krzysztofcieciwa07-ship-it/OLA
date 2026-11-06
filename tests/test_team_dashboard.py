"""Owner Command Center must call the current OLA API without fake status or unsafe DOM."""
from html.parser import HTMLParser
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app


class DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)


def test_dashboard_is_the_existing_ola_surface_and_starts_unverified():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    html = response.text
    assert "OLA di-OS | Centrum dowodzenia" in html
    assert "PRODUKCJA NIEPOTWIERDZONA" in html
    assert "Niezależna weryfikacja" in html
    assert 'id="runtime-status" class="status">NOT_RUN<' in html
    assert 'id="igor-status" class="status">UNKNOWN<' in html
    assert 'id="gate-status" class="status warn">NOT_APPROVED<' in html


def test_dashboard_uses_current_authenticated_api_and_reads_evidence():
    html = TestClient(app).get("/").text
    parsed = DashboardParser()
    parsed.feed(html)
    script = "\n".join(parsed.scripts)
    assert {"key", "input", "run-button", "chat-button", "evidence-button",
            "runtime-status", "igor-status", "gate-status", "run-id"} <= parsed.ids
    assert 'fetch("/chat"' in script
    assert 'fetch("/nina-run"' in script
    assert 'fetch(`/evidence/' in script
    assert '"X-API-Key":data.key' in script
    assert "decision_report?.evidence_ids" in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "/nina-workflow" not in script
    assert "/nina-autogpt" not in script
    assert "/approve" not in script


def test_dashboard_keeps_human_gate_as_review_not_automatic_approval():
    html = TestClient(app).get("/").text
    assert 'id="evidence-button"' in html
    assert "wymaga tożsamości operatora i MFA" in html
    assert "APPROVED_FOR_REVIEW_ONLY" not in html


def test_inline_dashboard_javascript_parses_with_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; browser syntax check is delegated to CI runtime")
    html = TestClient(app).get("/").text
    parsed = DashboardParser()
    parsed.feed(html)
    script = "\\n".join(parsed.scripts)
    result = subprocess.run([node, "--check", "-"], input=script,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
