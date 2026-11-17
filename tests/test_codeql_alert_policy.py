import unittest
from pathlib import Path

from scripts.codeql_alert_policy import source_suppression_reason


class CodeQLAlertPolicyTest(unittest.TestCase):
    def test_valid_looking_inline_marker_does_not_suppress(self):
        self.assertIsNone(
            source_suppression_reason(
                Path("/repo"),
                "app/hashchain.py",
                115,
                "py/weak-sensitive-data-hashing",
            )
        )

    def test_rationale_is_not_authorization(self):
        cases = [
            (Path("/repo"), "app/hashchain.py", 115, "py/weak-sensitive-data-hashing"),
            (Path("/repo"), "app/other.py", 10, "py/sql-injection"),
            (Path("/repo"), "../outside.py", 2, "py/weak-sensitive-data-hashing"),
            (Path("/repo"), "/etc/passwd", 2, "py/weak-sensitive-data-hashing"),
            (Path("/repo"), "app/hashchain.py", True, "py/weak-sensitive-data-hashing"),
            (Path("/repo"), "app/hashchain.py", 115, ""),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertIsNone(source_suppression_reason(*args))

    def test_no_inline_comment_can_authorize_a_high_severity_exception(self):
        # The HMAC/SHA-256 case requires independent human review; an inline
        # source marker is not accepted as a substitute for that review.
        self.assertIsNone(
            source_suppression_reason(
                Path("/repo"),
                "app/hashchain.py",
                115,
                "py/weak-sensitive-data-hashing",
            )
        )


if __name__ == "__main__":
    unittest.main()
