"""Operational tests for the read-only Hermes filesystem bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from current_status_resolver import VerdictKind
from current_status_resolver.runtime_bridge import (
    discover_receipt_files,
    main,
    resolve_receipt_files,
)


def _write_receipt(
    path: Path,
    *,
    task_id: str = "TASK-1",
    stage: str = "REVIEWER",
    attempt: int = 1,
    decision: str = "FAIL",
    completed_at: str = "2026-09-17T09:20:00+09:00",
    status: str = "SUCCEEDED",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "stage": stage,
                "attempt": attempt,
                "status": status,
                "completed_at": completed_at,
                "validation": {"decision": decision},
            }
        ),
        encoding="utf-8",
    )
    return path


def _evidence_id(task_id: str, stage: str, attempt: int) -> str:
    return f"hermes-receipt/{task_id}/{stage}/attempt/{attempt}"


def test_operational_fail_to_proven_native_e2e_supersession(tmp_path: Path) -> None:
    failed = _write_receipt(tmp_path / "receipts" / "history" / "fail.json")
    proven = _write_receipt(
        tmp_path / "receipts" / "history" / "proven.json",
        attempt=2,
        decision="PROVEN_NATIVE_E2E",
        completed_at="2026-09-17T09:48:00+09:00",
    )
    fail_id = _evidence_id("TASK-1", "REVIEWER", 1)
    proven_id = _evidence_id("TASK-1", "REVIEWER", 2)

    result = resolve_receipt_files(
        [failed, proven], supersedes_by_id={proven_id: (fail_id,)}
    )

    stream = result.streams[0]
    assert result.safe_to_consume is True
    assert stream.verdict.kind == VerdictKind.PROVEN_NATIVE_E2E
    assert stream.verdict.current_id == proven_id
    assert stream.verdict.history_ids == (fail_id, proven_id)
    assert stream.verdict.superseded_ids == (fail_id,)


def test_no_supersession_is_inferred_from_attempt_number(tmp_path: Path) -> None:
    first = _write_receipt(tmp_path / "a.json")
    second = _write_receipt(
        tmp_path / "b.json",
        attempt=2,
        decision="PROVEN",
        completed_at="2026-09-17T09:48:00+09:00",
    )
    result = resolve_receipt_files([first, second])
    assert result.streams[0].verdict.kind == VerdictKind.PROVEN
    assert result.streams[0].verdict.superseded_ids == ()


def test_conflicting_latest_receipts_are_ambiguous_and_unsafe(tmp_path: Path) -> None:
    first = _write_receipt(tmp_path / "pass.json", decision="PASS")
    second = _write_receipt(
        tmp_path / "fail.json", attempt=2, decision="FAIL"
    )
    result = resolve_receipt_files([first, second])
    assert result.safe_to_consume is False
    assert result.streams[0].verdict.kind == VerdictKind.AMBIGUOUS


def test_identical_current_and_history_snapshots_are_deduplicated(tmp_path: Path) -> None:
    current = _write_receipt(tmp_path / "receipts" / "REVIEWER.json", decision="PASS")
    history = _write_receipt(
        tmp_path / "receipts" / "history" / "REVIEWER_attempt_1.json",
        decision="PASS",
    )
    result = resolve_receipt_files([current, history])
    assert result.safe_to_consume is True
    assert result.streams[0].verdict.history_ids == (
        _evidence_id("TASK-1", "REVIEWER", 1),
    )
    assert len(result.duplicate_snapshots) == 1


def test_same_evidence_id_with_different_content_fails_closed(tmp_path: Path) -> None:
    first = _write_receipt(tmp_path / "first.json", decision="PASS")
    second = _write_receipt(tmp_path / "second.json", decision="FAIL")
    result = resolve_receipt_files([first, second])
    assert result.safe_to_consume is False
    assert result.streams[0].verdict.kind == VerdictKind.AMBIGUOUS
    assert len(result.streams[0].conflicts) == 1


def test_non_authoritative_receipt_is_rejected_without_promoting_pass(
    tmp_path: Path,
) -> None:
    path = _write_receipt(tmp_path / "failed.json", decision="PASS", status="FAILED")
    result = resolve_receipt_files([path])
    assert result.safe_to_consume is False
    assert result.streams == ()
    assert len(result.rejected) == 1


def test_unrelated_task_streams_are_not_mixed(tmp_path: Path) -> None:
    one = _write_receipt(tmp_path / "one.json", task_id="TASK-1", decision="PASS")
    two = _write_receipt(tmp_path / "two.json", task_id="TASK-2", decision="FAIL")
    result = resolve_receipt_files([one, two])
    assert [stream.stream_id for stream in result.streams] == [
        "TASK-1::REVIEWER",
        "TASK-2::REVIEWER",
    ]
    assert [stream.verdict.kind for stream in result.streams] == [
        VerdictKind.PASS,
        VerdictKind.FAIL,
    ]


def test_invalid_supersession_target_marks_stream_unsafe(tmp_path: Path) -> None:
    current = _write_receipt(tmp_path / "current.json", decision="PASS")
    current_id = _evidence_id("TASK-1", "REVIEWER", 1)
    result = resolve_receipt_files(
        [current], supersedes_by_id={current_id: ("missing-evidence",)}
    )
    assert result.safe_to_consume is False
    assert result.streams[0].verdict.invalid_supersede_ids == ("missing-evidence",)


def test_discovery_only_reads_json_below_receipts_directories(tmp_path: Path) -> None:
    expected = _write_receipt(tmp_path / "jobs" / "x" / "receipts" / "review.json")
    _write_receipt(tmp_path / "runtime_mirror" / "mirror.json")
    (tmp_path / "jobs" / "x" / "receipts" / "notes.txt").write_text(
        "ignored", encoding="utf-8"
    )
    assert discover_receipt_files(tmp_path) == (expected,)


def test_cli_outputs_json_and_nonzero_on_ambiguous(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipts = tmp_path / "receipts"
    _write_receipt(receipts / "pass.json", decision="PASS")
    _write_receipt(receipts / "fail.json", attempt=2, decision="FAIL")
    rc = main(["--receipt-root", str(receipts)])
    assert rc == 2
    output = json.loads(capsys.readouterr().out)
    assert output["safe_to_consume"] is False
    assert output["streams"][0]["verdict"]["kind"] == "AMBIGUOUS"
