"""Source observer regression tests; stdlib + Git, with no application startup.

Run directly, independently of pytest/conftest/database fixtures:
    python -m unittest discover -s tests -p test_capture_source_portable.py -v

The same real checkout cases run on Windows. The path serialization case also
exercises Windows-style relative paths when this suite runs on a POSIX host.
"""
import importlib.util
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE_FILE = Path(__file__).resolve().parents[1] / "app" / "execution_binding.py"
SPEC = importlib.util.spec_from_file_location("source_observer_under_test", SOURCE_FILE)
eb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eb)


class WindowsRelativePath(type(Path())):
    """Use real host I/O but Windows serialization for relative path results."""

    def relative_to(self, *args):
        return PureWindowsPath(super().relative_to(*args))


@unittest.skipUnless(shutil.which("git"), "Git is required for a real source checkout")
class CaptureSourcePortableTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="ola-source-observer-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.files = {
            "app/main.py": b"# Source fixture, never executed.\n",
            "app/nested/worker.py": b"WORKER = 'fixture'\n",
            "app/nested/settings.json": b'{"enabled":false}\n',
            "policies/nina-review-v1.json": b'{"fixture":"source-boundary"}\n',
            "policies/nested/notes.txt": b"All files in the boundary are observed.\n",
        }
        for name, content in self.files.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.safecrlf", "false")
        self.git("config", "core.hooksPath", str(self.root / ".git" / "no-hooks"))
        self.git("add", "--", "app", "policies")
        self.git("-c", "user.name=Source observer test", "-c",
                 "user.email=source-observer@example.invalid", "-c",
                 "commit.gpgsign=false", "commit", "-q", "-m", "Source fixture")
        environment = patch.dict(os.environ, {"OLA_SOURCE_MODE": "git"})
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("OLA_RUNTIME_COMMIT", None)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL,
            timeout=10,
        )

    def assert_local(self):
        observed = eb.capture_source(self.root)
        self.assertEqual(observed["status"], "LOCAL", observed)
        self.assertEqual(observed["sha"], self.git("rev-parse", "HEAD").decode().strip())
        self.assertEqual(observed["boundary"], "git-app-and-policies-on-disk-v1")
        return observed

    def test_clean_checkout_with_complete_nested_boundary_is_local(self):
        self.assert_local()

    def test_windows_relative_paths_match_git_names(self):
        # Git keeps '/' on every OS; pathlib's native str() uses '\\' on Windows.
        # All reads, the Git tree and byte comparisons still use this real repo.
        sample = WindowsRelativePath(self.root / "app/main.py").relative_to(self.root)
        self.assertEqual(str(sample), "app\\main.py")
        self.assertEqual(sample.as_posix(), "app/main.py")
        expected = self.assert_local()
        with patch.object(eb, "Path", WindowsRelativePath):
            self.assertEqual(eb.capture_source(self.root), expected)

    def test_changed_byte_in_each_boundary_file_is_unknown(self):
        for name, original in self.files.items():
            with self.subTest(path=name):
                target = self.root / name
                target.write_bytes(original + b"!")
                try:
                    observed = eb.capture_source(self.root)
                    self.assertEqual(observed["status"], "UNKNOWN", observed)
                    self.assertEqual(observed["reason"], "source bytes differ from committed tree")
                finally:
                    target.write_bytes(original)
                self.assert_local()

    def test_extra_file_inside_either_boundary_is_unknown(self):
        for name in ("app/nested/extra.txt", "policies/nested/extra.json"):
            with self.subTest(path=name):
                target = self.root / name
                target.write_bytes(b"untracked")
                try:
                    observed = eb.capture_source(self.root)
                    self.assertEqual(observed["status"], "UNKNOWN", observed)
                    self.assertEqual(observed["reason"], "untracked file in source boundary")
                finally:
                    target.unlink()
                self.assert_local()

    def test_tracked_and_untracked_symlinks_are_unknown_when_supported(self):
        target = self.root / "outside-boundary.txt"
        target.write_bytes(self.files["app/main.py"])
        probe = self.root / "symlink-probe"
        try:
            probe.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("This host cannot create symlinks: " + str(exc))
        probe.unlink()
        tracked = self.root / "app/main.py"
        tracked.unlink()
        tracked.symlink_to(target)
        observed = eb.capture_source(self.root)
        self.assertEqual(observed["status"], "UNKNOWN", observed)
        self.assertEqual(observed["reason"], "source file missing or symlinked")
        tracked.unlink()
        tracked.write_bytes(self.files["app/main.py"])
        self.assert_local()
        untracked = self.root / "policies/nested/link.txt"
        untracked.symlink_to(target)
        observed = eb.capture_source(self.root)
        self.assertEqual(observed["status"], "UNKNOWN", observed)
        self.assertEqual(observed["reason"], "symlink in source boundary")


if __name__ == "__main__":
    unittest.main()
