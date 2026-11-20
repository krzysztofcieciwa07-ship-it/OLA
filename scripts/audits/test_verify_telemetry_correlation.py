import json, subprocess, sys, tempfile, unittest
from pathlib import Path
SCRIPT=Path(__file__).with_name('verify_telemetry_correlation.py')
def row(i):
 return {'event_id':i,'tenant_id':'t','record_id':'r-'+i,'sequence':1,'record_hash':'h','producer_id':'p','outcome':'committed','timestamp':100.0}
class VerifierTests(unittest.TestCase):
 def run_case(self,db,logs,extra=()):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); (d/'db').write_text('\n'.join(json.dumps(x) for x in db)); (d/'logs').write_text('\n'.join(json.dumps(x) for x in logs)); cmd=[sys.executable,str(SCRIPT),'--db-jsonl',str(d/'db'),'--logs-jsonl',str(d/'logs'),'--manifest',str(d/'manifest'),'--sample-size','0',*extra]; return subprocess.run(cmd,capture_output=True,text=True)
 def test_match_pass(self): self.assertEqual(self.run_case([row('1')],[row('1')]).returncode,0)
 def test_missing_orphan_fail(self): self.assertEqual(self.run_case([row('1')],[row('2')]).returncode,2)
 def test_field_mismatch_fail(self):
  r=row('1'); l=row('1'); l['record_hash']='bad'; self.assertEqual(self.run_case([r],[l]).returncode,2)
 def test_timestamp_delta_fail(self):
  r=row('1'); l=row('1'); l['timestamp']=106; self.assertEqual(self.run_case([r],[l]).returncode,2)
 def test_duplicate_fail(self): self.assertNotEqual(self.run_case([row('1'),row('1')],[row('1')]).returncode,0)
 def test_required_field_fail(self):
  r=row('1'); del r['producer_id']; self.assertNotEqual(self.run_case([r],[row('1')]).returncode,0)
 def test_nan_fail(self):
  r=row('1'); r['timestamp']=float('nan'); self.assertNotEqual(self.run_case([r],[row('1')]).returncode,0)
 def test_negative_tolerance_fail(self): self.assertNotEqual(self.run_case([row('1')],[row('1')],('--timestamp-tolerance-seconds','-1')).returncode,0)
if __name__=='__main__': unittest.main()
