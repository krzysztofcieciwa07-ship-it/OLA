import argparse
import hashlib
import hmac
import json
import os
import sqlite3

ROLES = ["codeact", "react", "agentic_rag", "mcp_tool_use", "self_reflection", "multi_agent"]
CAPABILITIES = {
    "codeact": "validated_invoice_math",
    "react": "reason_act_observe",
    "agentic_rag": "retrieved_controlled_policy",
    "mcp_tool_use": "invoked_tool",
    "self_reflection": "checked_previous_output",
    "multi_agent": "aggregated_agent_outputs",
}
EXPECTED_INVOCATION = {
    "provider": "local",
    "model": "deterministic-business-runtime-v1",
    "invocation_type": "local_deterministic_model",
}
GENESIS = "0" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fail(reason):
    raise SystemExit(json.dumps({"status": "BLOCK", "reason": reason}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--invoice-json", required=True)
    args = parser.parse_args()

    invoice = json.loads(args.invoice_json)
    expected_net = round(float(invoice["net"]), 2)
    expected_vat = round(expected_net * float(invoice["vat_rate"]), 2)
    expected_gross = round(expected_net + expected_vat, 2)

    db = sqlite3.connect(args.db)
    rows = db.execute(
        "SELECT tenant_id, seq, record_type, payload_json, prev_hash, record_hash "
        "FROM evidence_records WHERE tenant_id=? ORDER BY seq",
        (args.tenant_id,),
    ).fetchall()
    db.close()

    if len(rows) != 6:
        fail(f"expected 6 evidence records, got {len(rows)}")

    expected_types = [f"agent.{role}" for role in ROLES]
    if [row[2] for row in rows] != expected_types:
        fail("agent evidence order/type mismatch")

    expected_prev = GENESIS
    instances = set()
    contexts = set()
    payloads = []
    for expected_seq, row in enumerate(rows):
        tenant_id, seq, record_type, payload_json, prev_hash, record_hash = row
        if tenant_id != args.tenant_id or seq != expected_seq:
            fail("tenant or sequence mismatch")
        if prev_hash != expected_prev:
            fail("hash-chain predecessor mismatch")
        payload = json.loads(payload_json)
        # Independent V2/V3 verification binds producer and record type.
        metadata = payload.get("__ola_evidence_v2__")
        if (not isinstance(metadata, dict)
                or set(metadata) != {"version", "record_type", "producer"}
                or metadata.get("version") not in (2, 3)
                or metadata.get("record_type") != record_type
                or metadata.get("producer") != "ola_runtime"):
            fail("legacy or unauthenticated agent evidence")
        domain = "OLA-EVIDENCE-CHAIN-V3" if metadata["version"] == 3 else "OLA-EVIDENCE-CHAIN-V2"
        material = canonical({
            "domain": domain, "tenant_id": tenant_id,
            "seq": seq, "prev_hash": prev_hash, "record_type": record_type,
            "producer": "ola_runtime", "payload_json": payload_json,
        }).encode("utf-8")
        if metadata["version"] == 3:
            master = os.environ.get("OLA_API_KEY_PEPPER", "").encode("utf-8")
            if len(master) < 32:
                fail("evidence chain key is not configured")
            key = hmac.new(master, b"OLA-EVIDENCE-CHAIN-KEY-V3", hashlib.sha256).digest()
            expected_hash = hmac.new(key, material, hashlib.sha256).hexdigest()
        else:
            expected_hash = hashlib.sha256(material).hexdigest()
        if record_hash != expected_hash:
            fail("hash-chain record hash mismatch")
        expected_prev = record_hash
        payloads.append(payload)
        agent = payload.get("agent")
        if agent != ROLES[expected_seq]:
            fail("agent identity/order mismatch")
        if payload.get("run_id") != args.run_id:
            fail("run_id mismatch")
        if payload.get("task") != "INVOICE_JSON:" + canonical(invoice):
            fail("task mismatch")
        if payload.get("status") != "RECORDED":
            fail("agent evidence is not producer-recorded")
        if payload.get("capability") != CAPABILITIES[agent]:
            fail(f"capability mismatch for {agent}")
        if payload.get("execution_boundary") != "in_process":
            fail("unexpected agent execution boundary")
        invocation = {
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "invocation_type": payload.get("invocation_type"),
        }
        if invocation != EXPECTED_INVOCATION:
            fail(f"invocation metadata mismatch for {agent}")
        instances.add(payload.get("agent_instance_id"))
        contexts.add(payload.get("context_digest"))

    if len(instances) != 6 or len(contexts) != 6:
        fail("agent identities or contexts are not unique")

    first = payloads[0]
    last = payloads[-1]
    if first.get("tool_output") != {"net": expected_net, "vat": expected_vat, "gross": expected_gross}:
        fail("invoice calculation does not match independent recomputation")
    final = last.get("final_result")
    expected_final = {
        "invoice_id": invoice["invoice_id"],
        "supplier": invoice["supplier"],
        "currency": invoice["currency"],
        "net": expected_net,
        "vat": expected_vat,
        "gross": expected_gross,
        "payment_decision": "APPROVE_FOR_TEST_TRANSFER",
        "transfer_amount": expected_gross,
        "transfer_status": "READY_NOT_SENT",
    }
    if final != expected_final:
        fail("final business result mismatch")

    print(json.dumps({
        "status": "VERIFIED",
        "run_id": args.run_id,
        "invoice_id": invoice["invoice_id"],
        "net": expected_net,
        "vat": expected_vat,
        "gross": expected_gross,
        "evidence_count": 6,
        "agent_instance_count": len(instances),
        "unique_context_count": len(contexts),
        "execution_boundary": "in_process",
        "verifier_boundary": "separate_process",
        "verification_scope": [
            "tenant_evidence_hash_chain_integrity",
            "record_producer_binding",
            "invoice_arithmetic_recomputed",
            "controlled_policy_match",
            "final_business_result_match",
            "unique_agent_instance_and_context_labels",
        ],
        "not_established": [
            "isolated_or_independent_agent_processes",
            "real_llm_invocation",
            "live_payment_or_transfer_execution",
        ],
        "payment_decision": final["payment_decision"],
        "transfer_status": final["transfer_status"],
        "reason": "separate-process verifier independently recomputed invoice arithmetic, policy, roles, capabilities, invocation metadata, result and hash chain; agent process isolation is not claimed",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
