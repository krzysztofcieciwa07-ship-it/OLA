"""Contract checks for the no-build frontend served by FastAPI at GET /."""
from html.parser import HTMLParser
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "web" / "index.html"


class UiParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.forms = []
        self.external_scripts = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            self.ids.append(data["id"])
        if tag == "form":
            self.forms.append(data.get("id"))
        if tag == "script" and "src" in data:
            self.external_scripts.append(data["src"])


def test_navigation_and_forms_have_unique_targets():
    html = SOURCE.read_text(encoding="utf-8")
    parser = UiParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert not parser.external_scripts
    assert {"view-overview", "view-chat", "view-workflow", "view-execution",
            "view-evidence", "view-audit"} <= set(parser.ids)
    assert {"chat-form", "workflow-form", "report-form", "approval-form",
            "execution-form", "evidence-form", "audit-form"} <= set(parser.forms)


def test_api_contract_uses_existing_routes_and_auth_headers():
    html = SOURCE.read_text(encoding="utf-8")
    for route in ("/health", "/chat", "/nina-workflow", "/nina-run", "/evidence/", "/audit"):
        assert route in html
    assert '"X-API-Key"' in html
    assert '"Authorization"' in html
    assert "bearer:true" in html
    assert "report_digest:latestReport.report_digest" in html
    assert "tip_hash:latestReport.tip_hash" in html
    assert "requested_tools" in html


def test_credentials_are_not_persisted_or_rendered_as_html():
    html = SOURCE.read_text(encoding="utf-8")
    assert 'autocomplete="off"' in html
    assert "localStorage.setItem" not in html
    assert "sessionStorage.setItem" not in html
    assert "document.cookie" not in html
    assert "innerHTML" not in html
    assert 'credentials:"omit"' in html
    assert "textContent" in html


def test_ui_never_conflates_health_or_igor_with_production_approval():
    html = SOURCE.read_text(encoding="utf-8")
    assert "API odpowiada" in html
    assert "UNVERIFIED" in html
    assert "nie produkcji" in html
    assert 'latestReport=null' in html
