from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "OLA_WATCHDOG_OPERATIONS.md"


def test_watchdog_runbook_separates_control_success_from_evidence_health():
    source = RUNBOOK.read_text(encoding="utf-8")

    assert "Control success is not runtime health" in source
    assert "must not increase the verified-evidence numerator" in source
    assert "workflow conclusion alone" in source


def test_watchdog_runbook_covers_all_non_equivalent_lifecycle_states():
    source = RUNBOOK.read_text(encoding="utf-8")

    required_states = (
        "`CONTINUE` | `WAIT` | `UNKNOWN`",
        "`CONTINUE` | `WAIT` | `BLOCKED`",
        "`CONTINUE` | `DISPATCHED` | `UNKNOWN`",
        "`CONTINUE` | `DISPATCHED` | `VERIFIED`",
        "`CONTINUE` | `NONE` | `VERIFIED`",
        "`HUMAN_GATE` or `STOP`",
    )
    for state in required_states:
        assert state in source


def test_watchdog_runbook_requires_exact_sha_and_twelve_hour_freshness():
    source = RUNBOOK.read_text(encoding="utf-8")

    assert "source_sha == current_main_sha" in source
    assert "flow_sha" in source
    assert "12 hours" in source
    assert "A main SHA change invalidates freshness" in source
