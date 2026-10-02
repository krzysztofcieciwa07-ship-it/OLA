import json
from pathlib import Path

def load_module(tmp_path,monkeypatch):
    monkeypatch.setenv('EVIDENCE_DIR',str(tmp_path))
    import importlib.util
    p=Path(__file__).parents[1]/'ci/evidence_vault.py'
    spec=importlib.util.spec_from_file_location('vault',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_genesis_and_append(tmp_path,monkeypatch):
    m=load_module(tmp_path,monkeypatch)
    assert m.verify_chain()['valid'] is False
    m.append('session_start',{'seed':'test'})
    m.append('probe',{'status':'ok'})
    assert m.verify_chain()['valid'] is True

def test_content_tamper_fails(tmp_path,monkeypatch):
    m=load_module(tmp_path,monkeypatch); m.append('probe',{'status':'ok'})
    p=tmp_path/'.chain.jsonl'; e=json.loads(p.read_text()); e['payload']['status']='fail'; p.write_text(json.dumps(e)+'\n')
    r=m.verify_chain(); assert r['valid'] is False and r['broken_at']==0

def test_reorder_fails(tmp_path,monkeypatch):
    m=load_module(tmp_path,monkeypatch); m.append('a',{'n':1}); m.append('b',{'n':2})
    p=tmp_path/'.chain.jsonl'; lines=p.read_text().splitlines(); p.write_text('\n'.join(reversed(lines))+'\n')
    assert m.verify_chain()['valid'] is False
