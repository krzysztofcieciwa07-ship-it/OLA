#!/usr/bin/env python3
"""Generate a build-time THIRD-PARTY-NOTICES file from installed Python distributions.

The generator uses only Python's standard library. It follows the installed
dependency graph reachable from the packages declared in the supplied
requirements files, records the resolved versions and license metadata, and
copies discoverable license/notice files into the notice document.

It deliberately does not treat UNKNOWN license metadata as clean; UNKNOWN is
reported explicitly so the build evidence cannot silently become a false PASS.
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path


DIST_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
REQ_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
SKIP_DIRECTIVES = ("-", "#", "@", "git+", "http:", "https:")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names(paths: list[Path]) -> list[str]:
    roots: list[str] = []
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(("-r ", "--requirement ")):
                continue
            if line.startswith(SKIP_DIRECTIVES):
                continue
            match = REQ_NAME_RE.match(line)
            if match:
                roots.append(match.group(0))
    return sorted({normalize(name) for name in roots})


def installed_distributions() -> dict[str, metadata.Distribution]:
    result: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            result[normalize(name)] = dist
    return result


def dependency_names(dist: metadata.Distribution) -> list[str]:
    names: list[str] = []
    for raw in dist.metadata.get_all("Requires-Dist") or []:
        match = DIST_NAME_RE.match(raw.strip())
        if match:
            names.append(normalize(match.group(0)))
    return names


def license_value(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression.strip()

    legacy = dist.metadata.get("License")
    if legacy and legacy.strip() and legacy.strip().upper() != "UNKNOWN":
        return legacy.strip()

    classifiers = [
        value.split(" :: ", 1)[1]
        for value in (dist.metadata.get_all("Classifier") or [])
        if value.startswith("License :: ")
    ]
    if classifiers:
        return "; ".join(classifiers)

    return "UNKNOWN"


def license_paths(dist: metadata.Distribution) -> list[Path]:
    raw_names = list(dist.metadata.get_all("License-File") or [])

    for file in dist.files or []:
        text = str(file).replace("\\", "/")
        basename = Path(text).name.lower()
        if basename in {"license", "licence", "copying", "notice"} or (basename.startswith(("license", "licence", "copying", "notice")) and text.lower().endswith((".txt", ".md", ".rst"))):
            raw_names.append(text)

    found: list[Path] = []
    seen: set[str] = set()
    for raw in raw_names:
        key = str(raw)
        if key in seen:
            continue
        seen.add(key)
        try:
            path = dist.locate_file(raw)
        except Exception:
            continue
        if path.is_file():
            found.append(path)
    return found


def build_closure(
    roots: list[str], installed: dict[str, metadata.Distribution]
) -> list[metadata.Distribution]:
    seen: set[str] = set()
    queue = list(roots)
    result: list[metadata.Distribution] = []

    while queue:
        name = normalize(queue.pop(0))
        if name in seen:
            continue
        seen.add(name)

        dist = installed.get(name)
        if dist is None:
            continue

        result.append(dist)
        queue.extend(dependency_names(dist))

    result.sort(key=lambda d: normalize(d.metadata.get("Name", "")))
    return result


def render(
    distributions: list[metadata.Distribution],
    roots: list[str],
    build_commit: str,
) -> str:
    unknown = [d for d in distributions if license_value(d) == "UNKNOWN"]

    lines = [
        "THIRD-PARTY-NOTICES",
        "====================",
        "",
        "Generated at build time from the installed Python dependency graph.",
        f"Build commit: {build_commit}",
        "Generation mode: build-time from installed runtime dependency closure",
        "",
        "Direct dependency roots:",
        *[f"- {root}" for root in roots],
        "",
        f"Resolved third-party distributions: {len(distributions)}",
        f"Distributions with UNKNOWN license metadata: {len(unknown)}",
        "",
        "Each section records the resolved distribution version, license metadata,",
        "and any discoverable license/notice file contents shipped by that package.",
        "",
    ]

    for dist in distributions:
        name = dist.metadata.get("Name", "?")
        version = dist.version
        license_name = license_value(dist)
        lines.extend(
            [
                "=" * 80,
                f"Package: {name}",
                f"Version: {version}",
                f"License: {license_name}",
                f"Home-page: {dist.metadata.get('Home-page') or 'UNKNOWN'}",
                "",
                "License / notice files:",
            ]
        )

        paths = license_paths(dist)
        if not paths:
            lines.append("- NONE DISCOVERED IN INSTALLED DISTRIBUTION")
        else:
            for path in paths:
                lines.append(f"- {path}")

        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                lines.extend(
                    [
                        "",
                        f"[Unable to read license file: {path}: {exc}]",
                    ]
                )
                continue

            lines.extend(
                [
                    "",
                    f"----- BEGIN LICENSE/NOTICE: {path} -----",
                    content,
                    f"----- END LICENSE/NOTICE: {path} -----",
                ]
            )

        lines.append("")

    if unknown:
        lines.extend(
            [
                "=" * 80,
                "LICENSE METADATA WARNING",
                "=" * 80,
                "The following installed distributions did not expose a recognized",
                "License-Expression, License field, or License classifier:",
                *[f"- {d.metadata.get('Name', '?')} {d.version}" for d in unknown],
                "",
                "UNKNOWN is reported as a review state and is not treated as a clean",
                "license result.",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", action="append", required=True, help="Requirements file")
    parser.add_argument("--output", required=True, help="Output notice path")
    parser.add_argument("--build-commit", default="unknown")
    args = parser.parse_args()

    requirements = [Path(item) for item in args.requirements]
    missing = [path for path in requirements if not path.is_file()]
    if missing:
        print("Missing requirements file(s):", ", ".join(map(str, missing)), file=sys.stderr)
        return 2

    roots = requirement_names(requirements)
    installed = installed_distributions()
    distributions = build_closure(roots, installed)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(distributions, roots, args.build_commit), encoding="utf-8")

    print(
        f"Generated {output}: {len(distributions)} distributions, "
        f"{sum(license_value(d) == 'UNKNOWN' for d in distributions)} unknown licenses"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
