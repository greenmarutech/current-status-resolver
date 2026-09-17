"""Acceptance and regression tests for the current-status resolver."""

from __future__ import annotations

import pytest

from current_status_resolver import Evidence, Resolver, Verdict, VerdictKind


def _ev(
    *,
    eid: str,
    verdict: str,
    timestamp: str,
    source: str = "test/source",
    evidence_path: str = "test/evidence.json",
    supersedes: tuple[str, ...] = (),
    notes: str = "",
) -> Evidence:
    return Evidence(
        id=eid,
        verdict=VerdictKind(verdict),
        timestamp=timestamp,
        source=source,
        evidence_path=evidence_path,
        supersedes=supersedes,
        notes=notes,
    )


def test_acceptance_01_historical_verdict_preserved_in_stream() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PASS", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(_ev(eid="E2", verdict="FAIL", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(_ev(eid="E3", verdict="PASS", timestamp="2026-09-17T18:00:00+00:00"))
    verdict: Verdict = res.current()
    assert verdict.history_ids == ("E1", "E2", "E3")


def test_acceptance_02_later_superseding_evidence_recognized() -> None:
    res = Resolver()
    res.append(_ev(eid="E_FAIL", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E_FIX",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E_FAIL",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.superseded_ids == ("E_FAIL",)
    assert verdict.supersession_chain == (("E_FAIL", "E_FIX"),)


def test_acceptance_03_current_verdict_is_latest_non_superseded() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-16T10:00:00+00:00"))
    res.append(_ev(eid="E2", verdict="PARTIAL", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(_ev(eid="E3", verdict="PASS", timestamp="2026-09-17T18:00:00+00:00"))
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.current_id == "E3"
    assert verdict.superseded_ids == ()


def test_acceptance_04_superseded_records_distinguished_from_current() -> None:
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
    assert "E_FAIL" in verdict.history_ids


def test_acceptance_05_conflicting_latest_evidence_yields_ambiguous() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PASS", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(_ev(eid="E2", verdict="FAIL", timestamp="2026-09-17T10:00:00+00:00"))
    verdict = res.current()
    assert verdict.kind == VerdictKind.AMBIGUOUS
    assert verdict.current_id is None
    assert verdict.ambiguous_ids == ("E1", "E2")


def test_acceptance_06_partial_or_fail_is_not_promoted_to_pass() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PARTIAL", timestamp="2026-09-17T10:00:00+00:00"))
    assert res.current().kind == VerdictKind.PARTIAL
    res.append(_ev(eid="E2", verdict="FAIL", timestamp="2026-09-17T11:00:00+00:00"))
    assert res.current().kind == VerdictKind.FAIL


def test_acceptance_07_result_includes_source_path_and_timestamp() -> None:
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
    assert verdict.current_source == "stage3/pilot1/final_verdict.md"
    assert verdict.current_evidence_path == "stage3/pilot1/acceptance.json"
    assert verdict.current_timestamp == "2026-09-17T18:30:00+00:00"


def test_acceptance_08_invalid_supersede_target_is_reported() -> None:
    res = Resolver()
    res.append(
        _ev(
            eid="E_FIX",
            verdict="PASS",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E_GHOST",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.PASS
    assert verdict.invalid_supersede_ids == ("E_GHOST",)


def test_acceptance_09_empty_stream_yields_hold() -> None:
    verdict = Resolver().current()
    assert verdict.kind == VerdictKind.HOLD
    assert verdict.current_id is None
    assert verdict.history_ids == ()


def test_acceptance_10_supersession_chain_is_traceable() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-15T10:00:00+00:00"))
    res.append(
        _ev(
            eid="E2",
            verdict="PASS",
            timestamp="2026-09-16T10:00:00+00:00",
            supersedes=("E1",),
        )
    )
    res.append(
        _ev(
            eid="E3",
            verdict="FAIL",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("E2",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.FAIL
    assert verdict.current_id == "E3"
    assert verdict.superseded_ids == ("E1", "E2")
    assert verdict.supersession_chain == (("E1", "E2"), ("E2", "E3"))


def test_regression_timezone_offsets_compare_absolute_instants() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-17T10:00:00+09:00"))
    res.append(_ev(eid="E2", verdict="PASS", timestamp="2026-09-17T02:00:00+00:00"))
    assert res.current().current_id == "E2"


def test_regression_older_entry_cannot_supersede_newer_evidence() -> None:
    res = Resolver()
    res.append(_ev(eid="NEW", verdict="PASS", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(
        _ev(
            eid="OLD",
            verdict="FAIL",
            timestamp="2026-09-16T10:00:00+00:00",
            supersedes=("NEW",),
        )
    )
    verdict = res.current()
    assert verdict.current_id == "NEW"
    assert verdict.superseded_ids == ()
    assert verdict.invalid_supersede_relations == (("NEW", "OLD"),)


def test_regression_equal_time_supersede_is_not_authoritative() -> None:
    res = Resolver()
    res.append(_ev(eid="A", verdict="PASS", timestamp="2026-09-17T10:00:00+00:00"))
    res.append(
        _ev(
            eid="B",
            verdict="FAIL",
            timestamp="2026-09-17T10:00:00+00:00",
            supersedes=("A",),
        )
    )
    verdict = res.current()
    assert verdict.kind == VerdictKind.AMBIGUOUS
    assert verdict.invalid_supersede_relations == (("A", "B"),)


def test_regression_naive_timestamp_is_rejected() -> None:
    res = Resolver()
    with pytest.raises(ValueError, match="timezone-aware"):
        res.append(_ev(eid="E1", verdict="PASS", timestamp="2026-09-17T10:00:00"))


def test_regression_malformed_timestamp_is_rejected() -> None:
    res = Resolver()
    with pytest.raises(ValueError, match="invalid evidence timestamp"):
        res.append(_ev(eid="E1", verdict="PASS", timestamp="not-a-timestamp"))


def test_regression_duplicate_id_is_rejected() -> None:
    res = Resolver()
    res.append(_ev(eid="E1", verdict="PASS", timestamp="2026-09-17T10:00:00Z"))
    with pytest.raises(ValueError, match="duplicate evidence id"):
        res.append(_ev(eid="E1", verdict="FAIL", timestamp="2026-09-18T10:00:00Z"))


def test_regression_self_supersede_is_rejected() -> None:
    res = Resolver()
    with pytest.raises(ValueError, match="cannot supersede itself"):
        res.append(
            _ev(
                eid="E1",
                verdict="PASS",
                timestamp="2026-09-17T10:00:00Z",
                supersedes=("E1",),
            )
        )
