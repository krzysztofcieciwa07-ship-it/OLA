import tempfile, unittest
from pathlib import Path
from crypto_payment_monitor.monitor import Ledger, _address_topic, _topic_address

class Tests(unittest.TestCase):
    def test_evm_address_normalization(self):
        self.assertEqual(_topic_address("0x"+"A"*40),"0x"+"a"*40)
    def test_address_topic_padding(self):
        self.assertEqual(_address_topic("0x"+"a"*40),"0x"+"0"*24+"a"*40)
    def test_ledger_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/"events.jsonl"))
            event={"event_id":"x","amount_base_units":1}
            self.assertTrue(ledger.append_once(event)); self.assertFalse(ledger.append_once(event))
            ledger2=Ledger(str(Path(d)/"events.jsonl")); self.assertFalse(ledger2.append_once(event))
if __name__=="__main__": unittest.main()
