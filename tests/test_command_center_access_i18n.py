"""Real API-key handshake and static PL/EN/FR Command Center coverage."""

import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app, current_api_identity
from app.models import ApiKey, Tenant

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_auth_handler_fails_closed_without_a_key():
    with pytest.raises(HTTPException) as exc:
        current_api_identity(Response(), None)
    assert exc.value.status_code == 401


def test_auth_handler_validates_tenant_without_echoing_key():
    key = f"direct-access-{uuid.uuid4()}"
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="ui-direct-auth-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(key)))
        db.commit()
    response = Response()
    result = current_api_identity(response, key)
    assert result == {"status": "authenticated", "tenant_id": tenant_id,
                      "auth_method": "api_key"}
    assert response.headers["cache-control"] == "no-store"
    assert key not in str(result)


def test_api_key_handshake_rejects_unauthenticated_callers():
    client = TestClient(app)
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"X-API-Key": "incorrect"}).status_code == 401


def test_api_key_handshake_returns_scoped_identity_without_secrets():
    key = f"access-{uuid.uuid4()}"
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="ui-auth-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(key)))
        db.commit()
    response = TestClient(app).get("/auth/me", headers={"X-API-Key": key})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "authenticated", "tenant_id": tenant_id,
                               "auth_method": "api_key"}
    assert key not in response.text


def test_key_is_not_accepted_before_validation_and_disconnection_aborts_requests():
    assert 'connectedKey=""' in HTML
    assert 'api("/auth/me",{key:candidate' in HTML
    assert 'if(!connectedKey)throw new Error' in HTML
    assert 'activeRequests.forEach(request=>request.abort())' in HTML
    assert 'generation!==accessGeneration' in HTML
    assert 'response.status===401&&path!=="/auth/me"' in HTML
    assert '$("api-key").value=""' in HTML
    assert 'credentials:"omit"' in HTML
    assert "localStorage" in HTML  # explanatory text only
    assert "localStorage.setItem" not in HTML
    assert "sessionStorage.setItem" not in HTML


class StaticTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.labels = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.skip_depth += 1
        if not self.skip_depth:
            for name, value in attrs:
                if name in {"placeholder", "aria-label", "title"} and value:
                    self.labels.add(value.strip())

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.labels.add(data.strip())


def test_polish_interface_strings_have_both_translations():
    parser = StaticTextParser()
    parser.feed(HTML)
    # These are static user-facing strings, not API output or user-supplied text.
    missing = [label for label in parser.labels
               if re.search("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", label)
               and f'"{label}":[' not in HTML]
    assert not missing, f"Untranslated static Polish strings: {missing}"
    assert 'const localeIndex={en:0,fr:1}' in HTML
    assert 'document.documentElement.lang=currentLocale' in HTML
    assert 'tr(titles[name][0])' in HTML
