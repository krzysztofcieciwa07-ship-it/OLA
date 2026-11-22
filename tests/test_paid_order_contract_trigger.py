"""Regression contract: the paid-order PostgreSQL producer is present on every PR to main."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/paid-order-postgres.yml"


class PaidOrderPostgresTriggerContractTest(unittest.TestCase):
    def test_pull_request_producer_runs_for_every_main_targeted_pr(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        pull_request = content.split("  pull_request:", 1)[1].split("  push:", 1)[0]
        self.assertIn("branches: [main]", pull_request)
        self.assertNotIn("paths:", pull_request)

    def test_main_push_producer_remains_path_scoped(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        push = content.split("  push:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("branches: [main]", push)
        self.assertIn("paths:", push)
        self.assertIn('"app/**"', push)
        self.assertIn('"tests/test_postgres_integration.py"', push)


if __name__ == "__main__":
    unittest.main()
