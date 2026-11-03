"""Real HTTP acceptance for local OLA operator -> NINA -> IGOR -> Evidence -> UI.

Runs only on disposable loopback staging, uses synthetic tenant and fresh keys.
No external Vantage, Codex, NOVA, payments or production operations.
"""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
import uuid


SEED_IDENTITIES = r"""
import json
import os
import uuid
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.models import ApiKey, Tenant

tenant = os.environ["STAGING_TENANT_ID"]
foreign = os.environ["STAGING_FOREIGN_TENANT_ID"]
requester_id = str(uuid.uuid4())
reviewer_id = str(uuid.uuid4())
with SessionLocal() as db:
    db.add(Tenant(id=tenant, name="staging operator workflow"))
    db.add(Tenant(id=foreign, name="staging isolated outsider"))
    db.flush()
    for owner, key_id, token in (
        (tenant, requester_id, os.environ["STAGING_REQUESTER_TOKEN"]),
        (tenant, reviewer_id, os.environ["STAGING_REVIEWER_TOKEN"]),
        (foreign, str(uuid.uuid4()), os.environ["STAGING_OUTSIDER_TOKEN"]),
    ):
        db.add(ApiKey(id=key_id, tenant_id=owner,
                      key_hash=api_key_fingerprint(token)))
    db.commit()
print("STAGING_RECORD=" + json.dumps({
    "tenant": tenant,
    "requester_id": requester_id,
    "reviewer_id": reviewer_id,
}))
"""


def _json(base, path, *, method="GET", key=None, bearer=False, body=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization" if bearer else "X-API-Key"] = (
            "Bearer " + key if bearer else key
        )
    request = urllib.request.Request(
        base + path, method=method, headers=headers,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print sensitive server payloads or request headers.
        return exc.code, {}


def run_operator_http_rehearsal(*, base, project, env, exec_python):
    tenant = str(uuid.uuid4())
    foreign = str(uuid.uuid4())
    requester = secrets.token_urlsafe(36)
    reviewer = secrets.token_urlsafe(36)
    outsider = secrets.token_urlsafe(36)
    source = exec_python(
        project, env, SEED_IDENTITIES, tenant=tenant,
        variables={
            "STAGING_FOREIGN_TENANT_ID": foreign,
            "STAGING_REQUESTER_TOKEN": requester,
            "STAGING_REVIEWER_TOKEN": reviewer,
            "STAGING_OUTSIDER_TOKEN": outsider,
        },
    )
    if source.get("tenant") != tenant:
        raise RuntimeError("operator identity fixture was not persisted")

    tests = {}
    status, run = _json(
        base, "/nina-run", method="POST", key=requester,
        body={
            "task": "Calculate 17 * 23 and return the verified result.",
            "requested_tools": ["safe_expression"],
        },
    )
    tests["operator_http_nina_execution"] = (
        status == 200 and run.get("status") == "REVIEW"
        and run.get("igor", {}).get("status") == "VERIFIED"
        and run.get("replay_verification", {}).get("status") == "VERIFIED"
    )
    if not tests["operator_http_nina_execution"]:
        raise RuntimeError("real HTTP NINA/IGOR execution failed")
    run_id = run["run_id"]
    endpoint = "/operator/operations/" + run_id

    code, receipt = _json(base, endpoint, key=requester, bearer=True)
    tests["operator_http_real_evidence_receipt"] = (
        code == 200
        and receipt.get("schema") == "ola.operation.v1"
        and receipt.get("tenant_id") == tenant
        and receipt.get("actor", {}).get("subject_id") == source["requester_id"]
        and receipt.get("evidence", {}).get("chain_tip") == run["tip_hash"]
        and receipt.get("stages", {}).get("igor", {}).get("status")
        == "VERIFIED_LOCAL_EVIDENCE"
        and receipt.get("status") == "REVIEW_REQUIRED"
    )
    tests["operator_http_vantage_fail_closed"] = (
        receipt.get("stages", {}).get("vantage", {}).get("status")
        == "NOT_CONNECTED"
        and receipt.get("production_authorized") is False
        and receipt.get("system_acceptance") == "NOT_VERIFIED"
    )

    foreign_code, _ = _json(base, endpoint, key=outsider, bearer=True)
    missing_code, _ = _json(base, endpoint)
    tests["operator_http_cross_tenant_isolation"] = (
        foreign_code == 404 and missing_code == 401
    )

    self_code, _ = _json(
        base, "/nina-run/" + run_id + "/approve",
        method="POST", key=requester, bearer=True,
        body={"tip_hash": run["tip_hash"], "reason": "self-approval must fail"},
    )
    tests["operator_http_self_approval_rejected"] = self_code == 403

    approval_code, approval = _json(
        base, "/nina-run/" + run_id + "/approve",
        method="POST", key=reviewer, bearer=True,
        body={"tip_hash": run["tip_hash"], "reason": "independent local review"},
    )
    tests["operator_http_second_identity_approval"] = (
        approval_code == 200
        and approval.get("status") == "VERIFIED"
        and approval.get("production_authorized") is False
    )

    read_code, after = _json(base, endpoint, key=reviewer, bearer=True)
    tests["operator_http_readback_after_review"] = (
        read_code == 200
        and after.get("status") == "APPROVED_FOR_REVIEW_ONLY"
        and after.get("reviewer_id") == source["reviewer_id"]
        and after.get("evidence", {}).get("chain_tip") == approval.get("tip_hash")
        and after.get("evidence", {}).get("chain_tip") != run["tip_hash"]
    )
    replay_code, _ = _json(
        base, "/nina-run/" + run_id + "/approve", method="POST",
        key=reviewer, bearer=True,
        body={"tip_hash": approval.get("tip_hash"), "reason": "duplicate review"},
    )
    tests["operator_http_duplicate_review_rejected"] = replay_code == 409

    req = urllib.request.Request(base + "/operator", method="GET")
    with urllib.request.urlopen(req, timeout=10) as response:
        page = response.read(300_000).decode("utf-8", "strict")
        tests["operator_http_real_ui_served"] = (
            response.status == 200 and "/operator/operations/" in page
            and "localStorage" not in page
        )
    if not all(tests.values()):
        raise RuntimeError("one or more real HTTP operator flow checks failed")
    return tests
