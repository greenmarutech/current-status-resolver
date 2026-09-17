# current-status-resolver

Hermes Agent OS module that derives the **authoritative current verdict** from an append-only canonical evidence stream while preserving full historical provenance.

## Why

Hermes keeps historical PASS / FAIL / PARTIAL / HOLD evidence for audit and recovery. Later evidence may explicitly supersede an earlier verdict. The resolver must therefore answer "what is current now?" without deleting the old record or accidentally treating stale evidence as current.

Core rules:

- historical evidence is never deleted;
- only an explicit supersession edge can mark older evidence superseded;
- a superseding entry must be **strictly later in absolute time** than its target;
- ISO-8601 timestamps must be timezone-aware;
- current status is selected from non-superseded evidence by absolute timestamp;
- conflicting latest verdicts at the same instant return `AMBIGUOUS` rather than guessing;
- an empty stream returns `HOLD`;
- missing or chronologically invalid supersession claims remain visible in the result;
- supersession edges are returned as an auditable chain.

## Public API

```python
from current_status_resolver import Evidence, Resolver, VerdictKind

resolver = Resolver()
resolver.append(Evidence(
    id="E_FAIL",
    verdict=VerdictKind.FAIL,
    timestamp="2026-09-16T10:00:00+00:00",
    source="run/2026-09-16/final.md",
    evidence_path="run/2026-09-16/acceptance.json",
))
resolver.append(Evidence(
    id="E_FIX",
    verdict=VerdictKind.PASS,
    timestamp="2026-09-17T18:00:00+00:00",
    source="run/2026-09-17/final.md",
    evidence_path="run/2026-09-17/acceptance.json",
    supersedes=("E_FAIL",),
))

verdict = resolver.current()
assert verdict.kind == VerdictKind.PASS
assert verdict.current_id == "E_FIX"
assert verdict.superseded_ids == ("E_FAIL",)
assert verdict.supersession_chain == (("E_FAIL", "E_FIX"),)
```

## Verdict provenance

`Verdict` exposes:

- `kind`: PASS / FAIL / PARTIAL / HOLD / AMBIGUOUS
- `current_id`: evidence id carrying the current verdict
- `history_ids`: every appended evidence id in append order
- `superseded_ids`: evidence ids invalidated by valid later supersession edges
- `ambiguous_ids`: conflicting latest evidence ids when status is AMBIGUOUS
- `invalid_supersede_ids`: missing supersession targets
- `invalid_supersede_relations`: `(target, superseder)` edges rejected because the superseder is not later
- `supersession_chain`: valid `(target, superseder)` edges for reconstruction/audit
- `current_source`, `current_evidence_path`, `current_timestamp`: provenance of the current evidence

## Run gates

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/
mypy src/current_status_resolver/
```

The feature branch includes acceptance coverage for historical preservation, explicit supersession, current-status selection, ambiguity, provenance paths, missing targets, empty-stream HOLD, chain traceability, timezone offset ordering, invalid timestamp rejection, duplicate ids, self-supersession, and chronologically invalid supersession edges.
