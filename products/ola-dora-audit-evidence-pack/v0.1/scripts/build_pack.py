from __future__ import annotations
import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist"}


def build_archive(output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if path.is_file() and not any(part in EXCLUDED for part in rel.parts) and path.suffix not in {".pyc", ".pyo"} and path.name != ".DS_Store":
            files.append((path, rel.as_posix()))
    if not files:
        raise ValueError("refusing to build an empty pack")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, rel in files:
            info = zipfile.ZipInfo(f"ola-dora-audit-evidence-pack/{rel}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = build_archive(args.output)
    print(f"PACK={args.output}\nSHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
