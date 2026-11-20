import unittest
from crypto_payment_monitor.config import Config

class ConfigTests(unittest.TestCase):
    def test_config_validation_defaults(self):
        Config().validate()
    def test_reject_non_https(self):
        c=Config(ethereum_rpc_url="http://unsafe", bitcoin_esplora_url=None)
        with self.assertRaises(ValueError): c.validate()
if __name__=="__main__": unittest.main()
