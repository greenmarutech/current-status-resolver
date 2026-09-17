"""current_status_resolver: derive the authoritative current verdict
from an append-only canonical evidence stream with explicit supersede semantics.

Public API:
    VerdictKind        -- enum: PASS / FAIL / PARTIAL / HOLD / AMBIGUOUS
    Evidence           -- one immutable entry in the stream
    Verdict            -- resolver result with current/superseded/history metadata
    Resolver           -- mutable stream; append() + current()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class VerdictKind(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    HOLD = "HOLD"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class Evidence:
    """One immutable append-only entry in the canonical evidence stream."""

    id: str
    verdict: VerdictKind
    timestamp: str
    source: str = ""
    evidence_path: str = ""
    supersedes: tuple[str, ...] = ()
    supersedes_invalid: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class Verdict:
    """Result of resolving the current authoritative verdict."""

    kind: VerdictKind
    current_id: str | None
    history_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    ambiguous_ids: tuple[str, ...]
    invalid_supersede_ids: tuple[str, ...]
    current_source: str = ""
    current_evidence_path: str = ""
    current_timestamp: str = ""


@dataclass
class Resolver:
    """Append-only stream + current() query.

    No entry is ever deleted; older entries are marked superseded only
    when a later evidence entry explicitly names them in `supersedes`.
    """

    _entries: list[Evidence] = field(default_factory=list)

    def append(self, entry: Evidence) -> None:
        if any(e.id == entry.id for e in self._entries):
            raise ValueError(f"duplicate evidence id: {entry.id}")
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

        history = tuple(e.id for e in self._entries)
        ids = {e.id for e in self._entries}

        superseded: set[str] = set()
        invalid: set[str] = set()
        for entry in self._entries:
            for target in entry.supersedes:
                if target in ids:
                    superseded.add(target)
                else:
                    invalid.add(target)
        # supersede invalid targets are also recorded as invalid even if no id conflict
        for entry in self._entries:
            for target in entry.supersedes_invalid:
                invalid.add(target)

        # latest-by-timestamp of non-superseded entries
        live = [e for e in self._entries if e.id not in superseded]
        latest_ts = max(e.timestamp for e in live)
        latest = [e for e in live if e.timestamp == latest_ts]

        if len(latest) > 1:
            kinds = {e.verdict for e in latest}
            if len(kinds) > 1:
                return Verdict(
                    kind=VerdictKind.AMBIGUOUS,
                    current_id=None,
                    history_ids=history,
                    superseded_ids=tuple(sorted(superseded)),
                    ambiguous_ids=tuple(e.id for e in latest),
                    invalid_supersede_ids=tuple(sorted(invalid)),
                )

        winner = latest[0]
        return Verdict(
            kind=winner.verdict,
            current_id=winner.id,
            history_ids=history,
            superseded_ids=tuple(sorted(superseded)),
            ambiguous_ids=(),
            invalid_supersede_ids=tuple(sorted(invalid)),
            current_source=winner.source,
            current_evidence_path=winner.evidence_path,
            current_timestamp=winner.timestamp,
        )


__all__ = ["VerdictKind", "Evidence", "Verdict", "Resolver"]
