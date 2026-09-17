# current-status-resolver

Hermes Agent OS module that derives the **authoritative current verdict** from
an append-only canonical evidence stream.

## Why

Hermes Stage closeouts keep every historical verdict (PASS / FAIL / PARTIAL /
HOLD) on disk as provenance. A later evidence entry may explicitly supersede
an earlier verdict (e.g. "the FAIL was caused by a broken fixture; the
re-run PASSED"). When the agent later asks "what is the current status of
X?", the answer must be the latest non-superseded verdict — **never** the
oldest, **never** the most recent raw entry if it has been invalidated.

If two non-superseding conflicting entries share the latest timestamp the
resolver returns **AMBIGUOUS** rather than guessing. An empty stream returns
**HOLD**.

## Public API

```python
from current_status_resolver import (
    Evidence, Resolver, Verdict, VerdictKind,
)

res = Resolver()
res.append(Evidence(
    id="E_FAIL",
    verdict=VerdictKind.FAIL,
    timestamp="2026-09-16T10:00:00+00:00",
    source="run/2026-09-16/final.md",
    evidence_path="run/2026-09-16/acceptance.json",
))
res.append(Evidence(
    id="E_FIX",
    verdict=VerdictKind.PASS,
    timestamp="2026-09-17T18:00:00+00:00",
    source="run/2026-09-17/final.md",
    evidence_path="run/2026-09-17/acceptance.json",
    supersedes=("E_FAIL",),       # explicitly supersede the earlier FAIL
))

verdict: Verdict = res.current()
assert verdict.kind == VerdictKind.PASS
assert verdict.current_id == "E_FIX"
assert verdict.superseded_ids == ("E_FAIL",)
```

`Verdict` fields:

| field | meaning |
|---|---|
| `kind` | current verdict kind (PASS / FAIL / PARTIAL / HOLD / AMBIGUOUS) |
| `current_id` | id of the entry that decided it (None for HOLD/AMBIGUOUS) |
| `history_ids` | every id ever appended, in order |
| `superseded_ids` | ids invalidated by an explicit `supersedes=` link |
| `ambiguous_ids` | conflicting entries at the latest timestamp (AMBIGUOUS only) |
| `invalid_supersede_ids` | `supersedes=` targets that do not exist in the stream |
| `current_source` | source path of the deciding entry |
| `current_evidence_path` | evidence path of the deciding entry |
| `current_timestamp` | timestamp of the deciding entry |

## Supersede semantics

- A later entry may name zero or more older ids in `supersedes=`. Named ids
  become `superseded_ids`; they are NOT deleted from `history_ids`.
- Targets that do not exist in the stream go to `invalid_supersede_ids` and
  are reported — they are not silently dropped.
- The current verdict is the latest-by-timestamp entry among the
  non-superseded entries. If multiple entries share the latest timestamp
  with **different** kinds, the result is **AMBIGUOUS** (no current_id).
- Without an explicit `supersedes=` link, a newer entry does NOT silently
  invalidate an older one (newer FAIL beside older PASS = FAIL current,
  but the older PASS is still in history).

## Run

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/
mypy src/current_status_resolver/
```