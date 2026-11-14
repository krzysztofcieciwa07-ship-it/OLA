"""Narrow, source-bound policy for explicitly justified CodeQL suppressions."""
from pathlib import Path, PurePosixPath
import io
import re
import tokenize

_SUPPRESSION = re.compile(r"^#\s*codeql\[([A-Za-z0-9_./-]+)\]\s+(.+?)\s*$")


def source_suppression_reason(repository_root, path, line, rule):
    """Return a directly-adjacent, rule-exact suppression rationale or None.

    The source path must be a repository-relative POSIX path. The marker must
    be a real Python COMMENT token on the immediately preceding line and
    include a non-empty rationale.
    """
    if type(line) is not int or line < 2:
        return None
    if not isinstance(path, str) or not path or "\\" in path:
        return None
    if not isinstance(rule, str) or not rule:
        return None

    relative = PurePosixPath(path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        return None

    try:
        root = Path(repository_root).resolve(strict=True)
        target = (root / Path(*relative.parts)).resolve(strict=True)
        target.relative_to(root)
        if not target.is_file():
            return None
        source = target.read_text(encoding="utf-8")
        lines = source.splitlines()
        comment = next((
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT and token.start[0] == line - 1
        ), None)
    except (OSError, RuntimeError, ValueError, UnicodeError, tokenize.TokenError, IndentationError, SyntaxError):
        return None

    if line > len(lines) or comment is None:
        return None
    match = _SUPPRESSION.fullmatch(comment)
    if match is None or match.group(1) != rule:
        return None
    reason = match.group(2).strip()
    return reason or None
