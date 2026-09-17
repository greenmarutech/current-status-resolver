"""Operational compatibility tests for the read-only Hermes receipt adapter."""

from __future__ import annotations

import pytest

from current_status_resolver import Resolver, VerdictKind
from current_status_resolver.hermes_adapter import evidence_from_hermes_receipt


def _receipt(
    *,
    decision: str = "PASS",
    status: str = "SUCCEEDED",
    completed_at: str = "2026-09-10T19:58:35+09:00",
    attempt: int = 1,
) -> dict[str, object]:
    # Sanitized shape observed in Frozen Legacy jobs/running/*/receipts/REVIEWER.json.
    return {
        "task_id": "NMT-TEST-001",
        "stage": "REVIEWER",
        "status": status,
        "started_at": "2026-09-10T19:55:47+09:00",
        "completed_at": completed_at,
        "attempt": attempt,
        "max_attempts": 3,
        "actual_publish_performed": False,
        "validation": {
            "decision": decision,
            "total_score": 93,
            "hard_fail_count": 0,
        },
    }


def test_real_legacy_receipt_shape_maps_explicit_validation_decision() -> None:
    evidence = evidence_from_hermes_receipt(
        _receipt(),
        evidence_path="jobs/running/NMT-TEST-001/receipts/REVIEWER.json",
    )

    assert evidence.id == "hermes-receipt/NMT-TEST-001/REVIEWER/attempt/1"
    assert evidence.verdict == VerdictKind.PASS
    assert evidence.timestamp == "2026-09-10T19:58:35+09:00"
    assert evidence.source == "hermes-receipt:REVIEWER"
    assert evidence.evidence_path.endswith("receipts/REVIEWER.json")
    assert evidence.supersedes == ()


def test_proven_native_e2e_is_supported_when_receipt_states_it_explicitly() -> None:
    evidence = evidence_from_hermes_receipt(
        _receipt(decision="PROVEN_NATIVE_E2E"),
        evidence_path="evidence/reviewer.json",
    )
    assert evidence.verdict == VerdictKind.PROVEN_NATIVE_E2E


def test_succeeded_without_validation_decision_does_not_become_pass() -> None:
    receipt = _receipt()
    receipt.pop("validation")

    with pytest.raises(ValueError, match="validation is required"):
        evidence_from_hermes_receipt(receipt, evidence_path="receipt.json")


def test_runtime_mirror_shape_is_not_guessed_into_a_verdict() -> None:
    runtime_mirror: dict[str, object] = {
        "plan_id": "WP-TEST",
        "native_state": "pending",
        "blueprint_state": "PENDING",
        "native_dry_run": True,
        "schema_version": "G2-RT-1.0",
        "updated_at": "2026-09-13T15:34:36+09:00",
    }

    with pytest.raises(ValueError, match="task_id"):
        evidence_from_hermes_receipt(runtime_mirror, evidence_path="runtime_mirror.json")


def test_failed_execution_cannot_publish_stale_pass_as_authoritative() -> None:
    with pytest.raises(ValueError, match="status is not SUCCEEDED"):
        evidence_from_hermes_receipt(
            _receipt(status="FAILED"),
            evidence_path="receipts/REVIEWER.json",
        )


def test_unknown_validation_decision_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported authoritative verdict"):
        evidence_from_hermes_receipt(
            _receipt(decision="MAYBE"),
            evidence_path="receipts/REVIEWER.json",
        )


def test_supersession_is_explicit_and_resolver_preserves_both_attempts() -> None:
    first = evidence_from_hermes_receipt(
        _receipt(decision="FAIL", completed_at="2026-09-10T19:58:35+09:00", attempt=1),
        evidence_path="receipts/history/REVIEWER_attempt_1.json",
    )
    second = evidence_from_hermes_receipt(
        _receipt(decision="PROVEN", completed_at="2026-09-10T20:05:00+09:00", attempt=2),
        evidence_path="receipts/history/REVIEWER_attempt_2.json",
        supersedes=(first.id,),
    )

    resolver = Resolver()
    resolver.append(first)
    resolver.append(second)
    verdict = resolver.current()

    assert verdict.kind == VerdictKind.PROVEN
    assert verdict.current_id == second.id
    assert first.id in verdict.history_ids
    assert first.id in verdict.superseded_ids
    assert verdict.supersession_chain == ((first.id, second.id),)


def test_adapter_reuses_resolver_timestamp_validation() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evidence_from_hermes_receipt(
            _receipt(completed_at="2026-09-10T19:58:35"),
            evidence_path="receipts/REVIEWER.json",
        )


def test_attempt_must_be_positive_integer() -> None:
    receipt = _receipt()
    receipt["attempt"] = 0
    with pytest.raises(ValueError, match="positive integer"):
        evidence_from_hermes_receipt(receipt, evidence_path="receipts/REVIEWER.json")


def test_adapter_does_not_mutate_input_receipt() -> None:
    receipt = _receipt()
    before = repr(receipt)
    evidence_from_hermes_receipt(receipt, evidence_path="receipts/REVIEWER.json")
    assert repr(receipt) == before
