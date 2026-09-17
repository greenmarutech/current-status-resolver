"""Read-only filesystem bridge for Hermes Agent OS status consumption.

The bridge is deliberately narrower than a runtime integration: it discovers or
accepts receipt JSON files, converts only explicit authoritative decisions, groups
them by ``(task_id, stage)``, and returns JSON-serialisable current-status records.
It never mutates receipts, runtime mirrors, queues, or Agent OS state.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from current_status_resolver import Evidence, Resolver, Verdict, VerdictKind
from current_status_resolver.hermes_adapter import evidence_from_hermes_receipt

ACCEPTANCE_PASS_VERDICTS = frozenset(
    {
        VerdictKind.PASS,
        VerdictKind.PROVEN,
        VerdictKind.PROVEN_NATIVE_E2E,
    }
)


@dataclass(frozen=True)
class RejectedReceipt:
    path: str
    reason: str


@dataclass(frozen=True)
class DuplicateSnapshot:
    evidence_id: str
    kept_path: str
    duplicate_path: str


@dataclass(frozen=True)
class ConflictingDuplicate:
    evidence_id: str
    first_path: str
    conflicting_path: str


@dataclass(frozen=True)
class StreamStatus:
    stream_id: str
    task_id: str
    stage: str
    verdict: Verdict
    safe_to_consume: bool
    acceptance_passed: bool
    conflicts: tuple[ConflictingDuplicate, ...] = ()


@dataclass(frozen=True)
class BridgeResult:
    streams: tuple[StreamStatus, ...]
    rejected: tuple[RejectedReceipt, ...]
    duplicate_snapshots: tuple[DuplicateSnapshot, ...]
    safe_to_consume: bool
    acceptance_passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return stable JSON-compatible output for a Boss/runtime consumer."""
        value = asdict(self)
        for stream in value["streams"]:
            stream["verdict"]["kind"] = str(stream["verdict"]["kind"])
        return value


@dataclass(frozen=True)
class _LoadedEvidence:
    task_id: str
    stage: str
    evidence: Evidence


def _required_receipt_field(receipt: Mapping[str, object], key: str) -> str:
    value = receipt.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"receipt.{key} must be a non-empty string")
    return value


def _semantic_identity(evidence: Evidence) -> tuple[object, ...]:
    """Compare logical receipt content while ignoring snapshot file location."""
    return (
        evidence.id,
        evidence.verdict,
        evidence.timestamp,
        evidence.source,
        evidence.supersedes,
        evidence.notes,
    )


def _read_supersession_manifest(path: Path | None) -> dict[str, tuple[str, ...]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("supersession manifest must be a JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for evidence_id, targets in raw.items():
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("supersession manifest keys must be non-empty strings")
        if not isinstance(targets, list) or any(
            not isinstance(target, str) or not target.strip() for target in targets
        ):
            raise ValueError(
                f"supersession targets for {evidence_id!r} must be non-empty strings"
            )
        result[evidence_id] = tuple(targets)
    return result


def discover_receipt_files(root: Path) -> tuple[Path, ...]:
    """Discover JSON receipt candidates without following or writing anything."""
    if not root.exists():
        raise FileNotFoundError(f"receipt root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"receipt root is not a directory: {root}")
    pattern = "**/*.json" if root.name == "receipts" else "**/receipts/**/*.json"
    return tuple(sorted(path for path in root.glob(pattern) if path.is_file()))


def resolve_receipt_files(
    receipt_paths: Sequence[Path],
    *,
    supersedes_by_id: Mapping[str, tuple[str, ...]] | None = None,
    task_id: str | None = None,
    stage: str | None = None,
) -> BridgeResult:
    """Resolve authoritative current status from receipt files, fail closed.

    Non-authoritative or malformed receipts are reported and make the overall
    result unsafe. Callers scanning a heterogeneous receipt root should select the
    intended task/stage explicitly; receipts outside that selection are ignored
    before authoritative-verdict validation. Identical current/history snapshots
    are de-duplicated by logical evidence id. Conflicting content for one logical
    id makes that stream ``AMBIGUOUS`` and unsafe.
    """
    supersession = dict(supersedes_by_id or {})
    loaded: list[_LoadedEvidence] = []
    rejected: list[RejectedReceipt] = []

    for path in sorted(receipt_paths):
        display_path = str(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("receipt JSON must be an object")
            receipt_task_id = _required_receipt_field(raw, "task_id")
            receipt_stage = _required_receipt_field(raw, "stage")
            if task_id is not None and receipt_task_id != task_id:
                continue
            if stage is not None and receipt_stage != stage:
                continue
            probe = evidence_from_hermes_receipt(raw, evidence_path=display_path)
            evidence = replace(
                probe,
                supersedes=supersession.get(probe.id, ()),
            )
            validator = Resolver()
            validator.append(evidence)
            loaded.append(_LoadedEvidence(receipt_task_id, receipt_stage, evidence))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            rejected.append(RejectedReceipt(display_path, str(exc)))

    groups: dict[tuple[str, str], list[Evidence]] = {}
    for item in loaded:
        groups.setdefault((item.task_id, item.stage), []).append(item.evidence)

    stream_results: list[StreamStatus] = []
    duplicate_snapshots: list[DuplicateSnapshot] = []
    for (task_id, stage), entries in sorted(groups.items()):
        unique: dict[str, Evidence] = {}
        conflicts: list[ConflictingDuplicate] = []
        for evidence in entries:
            existing = unique.get(evidence.id)
            if existing is None:
                unique[evidence.id] = evidence
                continue
            if _semantic_identity(existing) == _semantic_identity(evidence):
                duplicate_snapshots.append(
                    DuplicateSnapshot(
                        evidence.id,
                        existing.evidence_path,
                        evidence.evidence_path,
                    )
                )
            else:
                conflicts.append(
                    ConflictingDuplicate(
                        evidence.id,
                        existing.evidence_path,
                        evidence.evidence_path,
                    )
                )

        resolver = Resolver()
        for evidence in unique.values():
            resolver.append(evidence)
        verdict = resolver.current()
        if conflicts:
            verdict = replace(
                verdict,
                kind=VerdictKind.AMBIGUOUS,
                current_id=None,
                ambiguous_ids=tuple(sorted(conflict.evidence_id for conflict in conflicts)),
                current_source="",
                current_evidence_path="",
                current_timestamp="",
            )
        safe = (
            not conflicts
            and verdict.kind not in (VerdictKind.HOLD, VerdictKind.AMBIGUOUS)
            and not verdict.invalid_supersede_ids
            and not verdict.invalid_supersede_relations
        )
        stream_results.append(
            StreamStatus(
                stream_id=f"{task_id}::{stage}",
                task_id=task_id,
                stage=stage,
                verdict=verdict,
                safe_to_consume=safe,
                acceptance_passed=safe and verdict.kind in ACCEPTANCE_PASS_VERDICTS,
                conflicts=tuple(conflicts),
            )
        )

    overall_safe = not rejected and bool(stream_results) and all(
        stream.safe_to_consume for stream in stream_results
    )
    acceptance_passed = overall_safe and all(
        stream.acceptance_passed for stream in stream_results
    )
    return BridgeResult(
        streams=tuple(stream_results),
        rejected=tuple(rejected),
        duplicate_snapshots=tuple(duplicate_snapshots),
        safe_to_consume=overall_safe,
        acceptance_passed=acceptance_passed,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve authoritative Hermes current status without runtime writes."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--receipt-root",
        type=Path,
        help="Hermes root or a receipts directory to scan read-only.",
    )
    source.add_argument(
        "--receipt",
        action="append",
        type=Path,
        help="Explicit receipt JSON path; repeat for multiple files.",
    )
    parser.add_argument(
        "--supersession-manifest",
        type=Path,
        help="Optional JSON object mapping evidence ids to explicitly superseded ids.",
    )
    parser.add_argument(
        "--task-id",
        help="Only consume receipts whose receipt.task_id exactly matches this value.",
    )
    parser.add_argument(
        "--stage",
        help="Only consume receipts whose receipt.stage exactly matches this value.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        paths = (
            discover_receipt_files(args.receipt_root)
            if args.receipt_root is not None
            else tuple(args.receipt or ())
        )
        supersession = _read_supersession_manifest(args.supersession_manifest)
        result = resolve_receipt_files(
            paths,
            supersedes_by_id=supersession,
            task_id=args.task_id,
            stage=args.stage,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "safe_to_consume": False,
                    "acceptance_passed": False,
                    "error": str(exc),
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if not result.safe_to_consume:
        return 2
    return 0 if result.acceptance_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTANCE_PASS_VERDICTS",
    "BridgeResult",
    "ConflictingDuplicate",
    "DuplicateSnapshot",
    "RejectedReceipt",
    "StreamStatus",
    "discover_receipt_files",
    "resolve_receipt_files",
    "main",
]
