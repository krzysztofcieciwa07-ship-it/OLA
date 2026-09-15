import os
import tempfile
import uuid

os.environ["OLA_EG_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="ola_real_task_"), "real_task.db"
)

from app.agent_runtime import run_agent_task
from app.database import Base, SessionLocal, engine
from app.models import Tenant
from scripts.verify_agent_runtime import verify

Base.metadata.create_all(bind=engine)

REAL_TASK = "Calculate 17 * 23 and return the verified result."
EXPECTED_RESULT = "391"


def _tenant():
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="real-task-test"))
        db.commit()
    return tenant_id


def test_six_agents_produce_verified_final_result():
    tenant_id = _tenant()
    result = run_agent_task(tenant_id, REAL_TASK)

    assert result["status"] == "VERIFIED", result
    assert result["task"] == REAL_TASK
    assert result["final_result"] == EXPECTED_RESULT
    assert len(result["execution"]) == 6
    assert result["execution"][0]["tool_output"] == EXPECTED_RESULT
    assert result["execution"][-1]["final_result"] == EXPECTED_RESULT

    proof = verify(
        tenant_id,
        result["run_id"],
        "TEST_COMMIT",
        expected_task=REAL_TASK,
        expected_result=EXPECTED_RESULT,
    )
    assert proof["status"] == "VERIFIED", proof
    assert proof["task"] == REAL_TASK
    assert proof["final_result"] == EXPECTED_RESULT
    assert proof["evidence_count"] == 6
    assert proof["independent_instance_count"] == 6
    assert proof["independent_context_count"] == 6
