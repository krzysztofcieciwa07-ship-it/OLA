import unittest
from crypto_payment_monitor.bitcoin import Esplora

class FakeEsplora(Esplora):
    def __init__(self):
        super().__init__("https://example.invalid")
        self.calls=[]
    def _get(self,path):
        self.calls.append(path)
        if path.endswith("/txs"): return [{"txid":f"tx{i}"} for i in range(25)]
        if "/txs/chain/" in path: return [{"txid":"tx25"},{"txid":"tx26"}]
        if path=="/blocks/tip/height": return 900
        return {}

class BitcoinAdapterTests(unittest.TestCase):
    def test_paginated_history(self):
        api=FakeEsplora()
        rows=api.address_transactions_paginated("address")
        self.assertEqual(len(rows),27)
        self.assertEqual(len(api.calls),2)
    def test_tip_height(self):
        self.assertEqual(FakeEsplora().tip_height(),900)
    def test_requires_https(self):
        with self.assertRaises(ValueError): Esplora("http://invalid")
if __name__=="__main__": unittest.main()
