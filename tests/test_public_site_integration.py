from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class FrontendTests(unittest.TestCase):
 def test_site(self):
  assert (ROOT/'web/site/index.html').is_file()
  for p in ["product","architecture","agents","evidence","security","integrations","use-cases","pricing","pilot","contact","docs","privacy","terms"]:
   assert (ROOT/'web/site'/p/'index.html').is_file(), p
 def test_safe_form(self):
  text=(ROOT/'web/site/assets/site.js').read_text('utf-8')
  assert 'NIE ZOSTAŁO wysłane' in text
  assert 'window.OLA_PILOT_ENDPOINT' in text
 def test_single_command_center(self):
  assert not (ROOT/'web/site/app').exists()
  assert 'command-center-theme.css' in (ROOT/'web/index.html').read_text('utf8')
if __name__=='__main__': unittest.main()
