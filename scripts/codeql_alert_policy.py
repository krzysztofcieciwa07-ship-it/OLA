"""Fail-closed CodeQL alert exception policy.

Automatic in-source suppressions are deliberately disabled. A source comment
must never be sufficient authority to exempt a CodeQL finding. Verified false
positives require an explicit human dismissal in GitHub Code Scanning after
independent review; the CI workflow only reads the resulting open-alert set.
"""


def source_suppression_reason(repository_root, path, line, rule):
    """Compatibility shim: never authorize an automatic CodeQL suppression.

    The former implementation accepted any adjacent comment with a matching
    rule identifier and non-empty rationale. That made an unreviewed source
    edit sufficient to silence a high-severity alert. Keep the function
    temporarily so callers fail closed while migration completes.
    """
    return None
