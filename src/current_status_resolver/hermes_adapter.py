"""Read-only adapter from Hermes receipt JSON objects to resolver evidence."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from current_status_resolver import Evidence, Resolver, VerdictKind


def _required_str(record: Mapping[str, object], key: str, *, scope: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{scope}.{key} must be a non-empty string")
    return value


def _required_attempt(record: Mapping[str, object]) -> int:
    value = record.get("attempt")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("receipt.attempt must be a positive integer")
    return value


def _authoritative_decision(receipt: Mapping[str, object]) -> VerdictKind:
    status = _required_str(receipt, "status", scope="receipt")
    if status != "SUCCEEDED":
        raise ValueError(
            "receipt is not authoritative because receipt.status is not SUCCEEDED"
        )

    validation = receipt.get("validation")
    if not isinstance(validation, Mapping):
        raise ValueError("receipt.validation is required for an authoritative verdict")

    decision = _required_str(validation, "decision", scope="receipt.validation")
    try:
        return VerdictKind(decision)
    except ValueError as exc:
        raise ValueError(f"unsupported authoritative verdict: {decision}") from exc


def evidence_from_hermes_receipt(
    receipt: Mapping[str, object],
    *,
    evidence_path: str,
    supersedes: tuple[str, ...] = (),
) -> Evidence:
    """Convert one Hermes validation receipt into immutable resolver evidence.

    The adapter intentionally does not infer a verdict from execution-only fields such
    as ``status=SUCCEEDED`` or from runtime mirror states. A receipt is authoritative
    only when it completed successfully *and* contains an explicit
    ``validation.decision`` that is supported by ``VerdictKind``.

    Supersession is never inferred from attempt numbers. Callers must pass explicit
    evidence ids in ``supersedes`` when a later authoritative record is known to
    supersede earlier evidence.
    """

    if not evidence_path.strip():
        raise ValueError("evidence_path must not be empty")

    task_id = _required_str(receipt, "task_id", scope="receipt")
    stage = _required_str(receipt, "stage", scope="receipt")
    timestamp = _required_str(receipt, "completed_at", scope="receipt")
    attempt = _required_attempt(receipt)
    verdict = _authoritative_decision(receipt)

    evidence_id = (
        "hermes-receipt/"
        f"{quote(task_id, safe='')}/"
        f"{quote(stage, safe='')}/"
        f"attempt/{attempt}"
    )
    evidence = Evidence(
        id=evidence_id,
        verdict=verdict,
        timestamp=timestamp,
        source=f"hermes-receipt:{stage}",
        evidence_path=evidence_path,
        supersedes=supersedes,
        notes=f"task_id={task_id};stage={stage};attempt={attempt}",
    )

    # Reuse the resolver's invariants so adapter output cannot bypass timestamp,
    # self-supersession, or id validation before entering a real evidence stream.
    probe = Resolver()
    probe.append(evidence)
    return evidence


__all__ = ["evidence_from_hermes_receipt"]
