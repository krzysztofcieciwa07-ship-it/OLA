import json
import os
import sys
import tempfile
from pathlib import Path

# Make the repository root explicit on sys.path so CI and local pytest use
# the same application import boundary regardless of pytest import mode.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="ola_pytest_"), "pytest.db")
os.environ["OLA_EG_DB_PATH"] = TEST_DB_PATH
# Test fixtures only; never use this pepper in production.
os.environ.setdefault("OLA_API_KEY_PEPPER", "test-only-api-key-pepper-not-for-production")
# Public deterministic test key only; production secrets are never used by pytest.
os.environ["OLA_EVIDENCE_V4_KEYRING_JSON"] = json.dumps({"pytest-v4-2026": "cHl0ZXN0LW9ubHktdjQta2V5LW1hdGVyaWFsLTMyYnl0ZXMhIQ=="})
os.environ["OLA_EVIDENCE_V4_ACTIVE_KEY_ID"] = "pytest-v4-2026"
os.environ.setdefault("OLA_PUBLIC_BASE_URL", "http://localhost:8000")

# Import the application database only after the test DB path is fixed.
from app.database import Base, engine
from app import models  # noqa: F401

Base.metadata.create_all(bind=engine)
