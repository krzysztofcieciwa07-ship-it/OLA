import tempfile, unittest, os
from pathlib import Path
from crypto_payment_monitor.monitor import Ledger, Monitor, _address_topic, _topic_address
from crypto_payment_monitor.config import Config

class MonitorTests(unittest.TestCase):
    def test_address_normalization(self):
        self.assertEqual(_topic_address("0x"+"A"*40),"0x"+"a"*40)
    def test_reject_invalid_address(self):
        for bad in ("0x"+"g"*40,"0x"+"a"*39,"a"*40):
            with self.assertRaises(ValueError): _topic_address(bad)
    def test_address_topic_padding(self):
        self.assertEqual(_address_topic("0x"+"a"*40),"0x"+"0"*24+"a"*40)
    def test_ledger_idempotency_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/"events.jsonl"))
            event={"event_id":"x","amount_base_units":1}
            self.assertTrue(ledger.append_once(event)); self.assertFalse(ledger.append_once(event))
            self.assertFalse(Ledger(str(Path(d)/"events.jsonl")).append_once(event))
    def test_state_transitions_append(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(str(Path(d)/"events.jsonl"))
            e={"event_id":"btc:tx:0","status":"confirming","observed_at":1}
            l.append_transition(e); l.append_transition(e)
            rows=Path(d,"events.jsonl").read_text().splitlines()
            self.assertEqual(len(rows),1)
    def test_config_reject_http_and_embedded_credentials(self):
        for url in ("http://provider.invalid","https://user:pass@provider.invalid"):
            with self.assertRaises(ValueError):
                Config(ethereum_rpc_url=url,bitcoin_esplora_url=None).validate()
    def test_evm_cursor_rescans_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/"events.jsonl"))
            m=Monitor(Config(ethereum_rpc_url=None,bitcoin_esplora_url=None),ledger,state_path=str(Path(d)/"state.json"))
            m.watch_evm=["0x"+"a"*40]
            m.state={"evm_cursor":100}
            class RPC:
                def call(self,method,params): return "0x6d"
            m.rpc=RPC()
            ranges=[]
            m._evm_scan_range=lambda start,end: ranges.append((start,end)) or []
            old_overlap=os.environ.get("EVM_RESCAN_OVERLAP")
            old_chunk=os.environ.get("EVM_SCAN_CHUNK")
            try:
                os.environ["EVM_RESCAN_OVERLAP"]="10"
                os.environ["EVM_SCAN_CHUNK"]="100"
                m.scan_evm()
                # 0x6d is block 109; the default confirmations exclude
                # unconfirmed blocks, so the confirmed scan head is 98.
                self.assertEqual(ranges,[(90,98)])
            finally:
                if old_overlap is None: os.environ.pop("EVM_RESCAN_OVERLAP",None)
                else: os.environ["EVM_RESCAN_OVERLAP"]=old_overlap
                if old_chunk is None: os.environ.pop("EVM_SCAN_CHUNK",None)
                else: os.environ["EVM_SCAN_CHUNK"]=old_chunk
    def test_config_defaults(self):
        Config().validate()
if __name__=="__main__": unittest.main()
