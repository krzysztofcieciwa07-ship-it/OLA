"""Public OLA site: HTTP routing and truthful operational boundaries."""
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "product", "architecture", "agents", "evidence", "security",
    "integrations", "use-cases", "pricing", "pilot", "contact",
    "docs", "privacy", "terms",
)


class FrontendTests(unittest.TestCase):
    def test_public_pages_exist(self):
        self.assertTrue((ROOT / "web/site/index.html").is_file())
        for page in PAGES:
            with self.subTest(page=page):
                self.assertTrue((ROOT / "web/site" / page / "index.html").is_file())

    def test_same_origin_pages_are_really_served(self):
        with TestClient(app) as client:
            for route in ("/site/",) + tuple(f"/site/{page}/" for page in PAGES):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200, route)
                    self.assertIn("text/html", response.headers.get("content-type", ""))
                    self.assertIn("OLA", response.text)
            for asset, marker in (
                ("/site/assets/site.js", "OLA_PILOT_ENDPOINT"),
                ("/site/assets/site.css", "."),
                ("/site/assets/ola-orb.svg", "<svg"),
            ):
                with self.subTest(asset=asset):
                    response = client.get(asset)
                    self.assertEqual(response.status_code, 200, asset)
                    self.assertIn(marker, response.text)

    def test_command_center_is_not_reimplemented(self):
        self.assertFalse((ROOT / "web/site/app").exists())
        code = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("command-center-theme.css", code)
        with TestClient(app) as client:
            page = client.get("/app")
            self.assertEqual(page.status_code, 200)
            self.assertIn("NINA", page.text)
            self.assertIn("IGOR", page.text)
            self.assertIn("UNVERIFIED", page.text)

    def test_no_fabricated_pilot_submission_or_operational_status(self):
        script = (ROOT / "web/site/assets/site.js").read_text(encoding="utf-8")
        self.assertIn("NIE ZOSTAŁO wysłane", script)
        self.assertIn("window.OLA_PILOT_ENDPOINT", script)
        self.assertIn('credentials:"omit"', script)
        self.assertIn('fetch("/health"', script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
