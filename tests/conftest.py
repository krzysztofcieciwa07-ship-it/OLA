import os
import tempfile

TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="ola_pytest_"), "pytest.db")
os.environ["OLA_EG_DB_PATH"] = TEST_DB_PATH

# Import the application database only after the test DB path is fixed.
from app.database import Base, engine
from app import models  # noqa: F401

Base.metadata.create_all(bind=engine)
