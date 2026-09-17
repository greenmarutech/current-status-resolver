"""Acceptance tests for the current-status resolver.

Each acceptance bullet from the user's spec is enforced here.
"""

from __future__ import annotations

from current_status_resolver import Evidence, Resolver, Verdict, VerdictKind


def _ev(
    *,
    eid: str,
    verdict: str,
    timestamp: str,
    source: str = "test/source",
    evidence_path: str = "test/evidence.json",
    supersedes: tuple[str, ...] = (),
    supersedes_invalid: tuple[str, ...] = (),
    notes: str = "",
) -> Evidence:
    return Evidence(
        id=eid,
        verdict=VerdictKind(verdict),
        timestamp=timestamp,
        source=source,
        evidence_path=evidence_path,
        supersedes=supersedes,
        supersedes_invalid=supersedes_invalid,
        notes=notes,
    )


def test_acceptance_01_historical_verdict_preserved_in_stream() -> None:
    """Historical PASS verdict stays in the chronological stream."""
    res = Resolver()
    res.append(
        _ev(
            eid="E1",
            verdict="PASS",
            timestamp="2026-09-16T10:00:00+00:00",
            notes="first run",
        )
    )
    res.append(
        _ev(
            eid="E2",
            verdict="FAIL",
            timestamp="2026-09-17T10:00:00+00:00",
            notes="regression on second run",
        )
    )
    res.append(
        _ev(
            eid="E3",
            verdict="PASS",
            timestamp="2026-09-17T18:00:00+00:00",
            notes="re-test passed",
        )
    )
    verdict: Verdict = res.current()
    assert "E1" in verdict.history_ids
    assert "E2" in verdict.history_ids
    assert "E3" in verdict.history_ids


def test_acceptance_02_later_superseding_evidence_recognized() -> None:
    """A later evidence entry explicitly supersedes an earlier FAIL."""
    res = Resolver()
    res.append(
        _ev(
            eid="E_FAIL",
            verdict="FAIL",
            timestamp="2026-09-16T10:00:00+00:00",
        )
    )
    res.append(
        _ev(
            eid="E_FIX",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E_FAIL",),
            notes="later fix supersedes earlier FAIL",
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.superseded_ids == ("E_FAIL",)
    assert "E_FIX" in verdict.history_ids


def test_acceptance_03_current_verdict_is_latest_non_superseded() -> None:
    """Without explicit supersedes, the latest evidence by timestamp wins."""
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(_ev(eid="E2", verdict="PARTIAL", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(_ev(eid="E3", verdict="PASS", timestamp="2026-09-17T18:00:00+00:00"))
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.current_id == "E3"
    assert verdict.superseded_ids == ()


def test_acceptance_04_superseded_records_distinguished_from_current() -> None:
    """A verdict can report both current_id and superseded_ids."""
    res = Resolver()
    res.append(_ev(eid="E_FAIL", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E_PASS",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E_FAIL",),
        )
    )
    verdict = res.current()
    assert verdict.current_id == "E_PASS"
    assert verdict.superseded_ids == ("E_FAIL",)
    assert "E_FAIL" in verdict.history_ids  # preserved, not deleted


def test_acceptance_05_conflicting_evidence_yields_ambiguous_hold() -> None:
    """Two non-superseding conflicting latest verdicts at the same timestamp = AMBIGUOUS."""
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PASS", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E2",
            verdict="FAIL",
            timestamp="2026-09-17T10:00:00+00:00",
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.AMBIGUOUS
    assert verdict.current_id is None
    assert verdict.ambiguous_ids == ("E1", "E2")


def test_acceptance_06_hold_returns_hold_not_arbitrary() -> None:
    """PARTIAL alone does not become PASS; only matching supersede updates promote it."""
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PARTIAL", timestamp="2026-09-17T10:00:00+00:00"))
    verdict = res.current()
    assert verdict.kind == VerdictKind.PARTIAL
    # A newer FAIL does NOT implicitly supersede PARTIAL (no explicit link).
    res.append(_ev(eid="E2", verdict="FAIL", timestamp="2026-09-17T11:00:00+00:00"))
    verdict = res.current()
    # Latest non-superseded still wins → FAIL because no supersede link.
    assert verdict.kind == VerdictKind.FAIL
    assert verdict.superseded_ids == ()


def test_acceptance_07_includes_source_evidence_path_and_timestamp() -> None:
    """Result carries source/evidence_path/timestamp of the current entry."""
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E2",
            verdict="PASS",
            timestamp="2026-09-17T18:30:00+00:00",
            source="stage3/pilot1/final_verdict.md",
            evidence_path="stage3/pilot1/acceptance.json",
            supersedes=("E1",),
        )
    )
    verdict = res.current()
    assert verdict.current_id == "E2"
    assert verdict.current_source == "stage3/pilot1/final_verdict.md"
    assert verdict.current_evidence_path == "stage3/pilot1/acceptance.json"
    assert verdict.current_timestamp == "2026-09-17T18:30:00+00:00"


def test_acceptance_08_invalid_supersede_target_marked_invalid() -> None:
    """Supersede targeting a non-existent entry is recorded as invalid, not silently dropped."""
    res = Resolver()
    res.append(_ev(eid="E_REAL", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E_FIX",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E_REAL", "E_GHOST"),
            supersedes_invalid=("E_GHOST",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.current_id == "E_FIX"
    assert "E_GHOST" in verdict.invalid_supersede_ids


def test_acceptance_09_empty_stream_yields_hold() -> None:
    """No evidence at all = HOLD, not random."""
    res = Resolver()
    verdict = res.current()
    assert verdict.kind == VerdictKind.HOLD
    assert verdict.current_id is None
    assert verdict.history_ids == ()


def test_acceptance_10_chain_supersede_propagates() -> None:
    """E1 FAIL → E2 PASS (supersedes E1) → E3 FAIL (supersedes E2) → final current is FAIL."""
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E2",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E1",),
        )
    )
    res.append(
        _ev(
            eid="E3",
            verdict="FAIL",
            timestamp="2026-09-17T18:00:00+00:00",
            supersedes=("E2",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.FAIL
    assert verdict.current_id == "E3"
    # E1 is transitively superseded through E2; record it.
    assert "E1" in verdict.superseded_ids
    assert "E2" in verdict.superseded_ids
