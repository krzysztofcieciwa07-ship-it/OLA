"""AURORA operational health indicators must never rely on stale measurements."""
from fastapi.testclient import TestClient

from app.main import app


def test_frontend_serves_existing_aurora_with_automated_live_health():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    ui = response.text
    assert "OLA di-OS • AURORA" in ui
    assert "setInterval(()=>{if(!document.hidden)refreshHealth({silent:true})},15000)" in ui
    assert "document.addEventListener('visibilitychange'" in ui
    assert "healthGeneration++" in ui
    assert "if(generation!==healthGeneration || document.hidden)return" in ui
    assert "applyHealth(false)" in ui
    assert "Brak aktualnego pomiaru (karta nieaktywna)." in ui
    assert "(tylko API)" in ui


def test_frontend_health_probe_matches_public_backend_contract():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
