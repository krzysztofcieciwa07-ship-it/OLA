import tempfile
import unittest
from pathlib import Path

from scripts.codeql_alert_policy import source_suppression_reason


class CodeQLAlertPolicyTest(unittest.TestCase):
    def make_repo(self, source: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        target = root / "app" / "hashchain.py"
        target.parent.mkdir(parents=True)
        target.write_text(source, encoding="utf-8")
        return root

    def test_exact_adjacent_rule_and_reason_suppresses_only_that_alert(self):
        root = self.make_repo(
            "def compute():\\n"
            "    # codeql[py/weak-sensitive-data-hashing] HMAC-SHA-256 is keyed with a server-side pepper.\\n"
            "    return hmac.new(key, material, hashlib.sha256).hexdigest()\\n"
        )
        self.assertEqual(
            source_suppression_reason(root, "app/hashchain.py", 3, "py/weak-sensitive-data-hashing"),
            "HMAC-SHA-256 is keyed with a server-side pepper.",
        )

    def test_wrong_rule_does_not_suppress(self):
        root = self.make_repo("# codeql[py/other-rule] justified\\nvalue = digest()\\n")
        self.assertIsNone(source_suppression_reason(root, "app/hashchain.py", 2, "py/weak-sensitive-data-hashing"))

    def test_missing_reason_does_not_suppress(self):
        root = self.make_repo("# codeql[py/weak-sensitive-data-hashing]\\nvalue = digest()\\n")
        self.assertIsNone(source_suppression_reason(root, "app/hashchain.py", 2, "py/weak-sensitive-data-hashing"))

    def test_non_adjacent_comment_does_not_suppress(self):
        root = self.make_repo("# codeql[py/weak-sensitive-data-hashing] justified\\n\\nvalue = digest()\\n")
        self.assertIsNone(source_suppression_reason(root, "app/hashchain.py", 3, "py/weak-sensitive-data-hashing"))

    def test_path_traversal_and_absolute_paths_are_rejected(self):
        root = self.make_repo("# codeql[py/weak-sensitive-data-hashing] justified\\nvalue = digest()\\n")
        self.assertIsNone(source_suppression_reason(root, "../outside.py", 2, "py/weak-sensitive-data-hashing"))
        self.assertIsNone(source_suppression_reason(root, str(root / "app/hashchain.py"), 2, "py/weak-sensitive-data-hashing"))

    def test_invalid_line_is_rejected(self):
        root = self.make_repo("# codeql[py/weak-sensitive-data-hashing] justified\\nvalue = digest()\\n")
        for line in (0, 1, 3, True, "2"):
            with self.subTest(line=line):
                self.assertIsNone(source_suppression_reason(root, "app/hashchain.py", line, "py/weak-sensitive-data-hashing"))


if __name__ == "__main__":
    unittest.main()
