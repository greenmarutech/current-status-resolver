"""Derive the authoritative current verdict from append-only evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class VerdictKind(StrEnum):
    PASS = "PASS"
    PROVEN = "PROVEN"
    PROVEN_NATIVE_E2E = "PROVEN_NATIVE_E2E"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    HOLD = "HOLD"
    AMBIGUOUS = "AMBIGUOUS"


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid evidence timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"evidence timestamp must be timezone-aware: {value}")
    return parsed


@dataclass(frozen=True)
class Evidence:
    """One immutable append-only entry in the canonical evidence stream."""

    id: str
    verdict: VerdictKind
    timestamp: str
    source: str = ""
    evidence_path: str = ""
    supersedes: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class Verdict:
    """Resolved current status plus provenance needed for audit and recovery."""

    kind: VerdictKind
    current_id: str | None
    history_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    ambiguous_ids: tuple[str, ...]
    invalid_supersede_ids: tuple[str, ...]
    current_source: str = ""
    current_evidence_path: str = ""
    current_timestamp: str = ""
    supersession_chain: tuple[tuple[str, str], ...] = ()
    invalid_supersede_relations: tuple[tuple[str, str], ...] = ()


@dataclass
class Resolver:
    """Append-only stream with explicit, chronological supersession semantics.

    Historical evidence is never deleted. A supersession edge is authoritative only
    when the superseding entry is strictly later in absolute time than its target.
    Invalid/missing supersession claims remain visible in the returned provenance.
    """

    _entries: list[Evidence] = field(default_factory=list)

    def append(self, entry: Evidence) -> None:
        if not entry.id.strip():
            raise ValueError("evidence id must not be empty")
        if any(existing.id == entry.id for existing in self._entries):
            raise ValueError(f"duplicate evidence id: {entry.id}")
        if entry.id in entry.supersedes:
            raise ValueError(f"evidence cannot supersede itself: {entry.id}")
        _parse_timestamp(entry.timestamp)
        self._entries.append(entry)

    def current(self) -> Verdict:
        if not self._entries:
            return Verdict(
                kind=VerdictKind.HOLD,
                current_id=None,
                history_ids=(),
                superseded_ids=(),
                ambiguous_ids=(),
                invalid_supersede_ids=(),
            )

        history = tuple(entry.id for entry in self._entries)
        by_id = {entry.id: entry for entry in self._entries}
        parsed = {entry.id: _parse_timestamp(entry.timestamp) for entry in self._entries}

        superseded: set[str] = set()
        invalid_targets: set[str] = set()
        invalid_relations: list[tuple[str, str]] = []
        chain: list[tuple[str, str]] = []

        for superseder in self._entries:
            for target_id in superseder.supersedes:
                target = by_id.get(target_id)
                if target is None:
                    invalid_targets.add(target_id)
                    continue
                if parsed[superseder.id] <= parsed[target.id]:
                    invalid_relations.append((target.id, superseder.id))
                    continue
                superseded.add(target.id)
                chain.append((target.id, superseder.id))

        live = [entry for entry in self._entries if entry.id not in superseded]
        latest_instant = max(parsed[entry.id] for entry in live)
        latest = [entry for entry in live if parsed[entry.id] == latest_instant]

        kinds = {entry.verdict for entry in latest}
        if len(kinds) > 1:
            return Verdict(
                kind=VerdictKind.AMBIGUOUS,
                current_id=None,
                history_ids=history,
                superseded_ids=tuple(sorted(superseded)),
                ambiguous_ids=tuple(entry.id for entry in latest),
                invalid_supersede_ids=tuple(sorted(invalid_targets)),
                supersession_chain=tuple(chain),
                invalid_supersede_relations=tuple(invalid_relations),
            )

        winner = latest[-1]
        return Verdict(
            kind=winner.verdict,
            current_id=winner.id,
            history_ids=history,
            superseded_ids=tuple(sorted(superseded)),
            ambiguous_ids=(),
            invalid_supersede_ids=tuple(sorted(invalid_targets)),
            current_source=winner.source,
            current_evidence_path=winner.evidence_path,
            current_timestamp=winner.timestamp,
            supersession_chain=tuple(chain),
            invalid_supersede_relations=tuple(invalid_relations),
        )


__all__ = ["VerdictKind", "Evidence", "Verdict", "Resolver"]
