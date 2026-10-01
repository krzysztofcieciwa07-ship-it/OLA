import json, subprocess, sys

def test_supply_chain_verifier_blocks_missing_evidence(tmp_path):
    result = subprocess.run([sys.executable,"scripts/verify_supply_chain_evidence.py","--root",str(tmp_path),"--commit","abc"],capture_output=True,text=True)
    assert result.returncode == 1
    payload=json.loads(result.stdout)
    assert payload["status"]=="BLOCK"
    assert payload["missing"]
