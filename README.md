# current-status-resolver

Hermes Agent OS module that derives the **authoritative current verdict** from an append-only canonical evidence stream while preserving full historical provenance.

## Why

Hermes keeps historical PASS / FAIL / PARTIAL / HOLD evidence for audit and recovery. Later evidence may explicitly supersede an earlier verdict. The resolver must answer "what is current now?" without deleting the old record or accidentally treating stale evidence as current.

Core rules:

- historical evidence is never deleted;
- only an explicit supersession edge can mark older evidence superseded;
- a superseding entry must be **strictly later in absolute time** than its target;
- ISO-8601 timestamps must be timezone-aware;
- current status is selected from non-superseded evidence by absolute timestamp;
- conflicting latest verdicts at the same instant return `AMBIGUOUS` rather than guessing;
- an empty stream returns `HOLD`;
- missing or chronologically invalid supersession claims remain visible in the result;
- supersession edges are returned as an auditable chain;
- canonical success states used by Hermes are supported directly: `PASS`, `PROVEN`, and `PROVEN_NATIVE_E2E`.

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
    verdict=VerdictKind.PROVEN_NATIVE_E2E,
    timestamp="2026-09-17T18:00:00+00:00",
    source="run/2026-09-17/final.md",
    evidence_path="run/2026-09-17/acceptance.json",
    supersedes=("E_FAIL",),
))

verdict = resolver.current()
assert verdict.kind == VerdictKind.PROVEN_NATIVE_E2E
assert verdict.current_id == "E_FIX"
assert verdict.superseded_ids == ("E_FAIL",)
assert verdict.supersession_chain == (("E_FAIL", "E_FIX"),)
```

## Verdict provenance

`Verdict` exposes:

- `kind`: PASS / PROVEN / PROVEN_NATIVE_E2E / FAIL / PARTIAL / HOLD / AMBIGUOUS
- `current_id`: evidence id carrying the current verdict
- `history_ids`: every appended evidence id in append order
- `superseded_ids`: evidence ids invalidated by valid later supersession edges
- `ambiguous_ids`: conflicting latest evidence ids when status is AMBIGUOUS
- `invalid_supersede_ids`: missing supersession targets
- `invalid_supersede_relations`: `(target, superseder)` edges rejected because the superseder is not later
- `supersession_chain`: valid `(target, superseder)` edges for reconstruction/audit
- `current_source`, `current_evidence_path`, `current_timestamp`: provenance of the current evidence

## Hermes receipt adapter

`current_status_resolver.hermes_adapter` provides a read-only compatibility adapter for Hermes receipt JSON objects. The integration contract is intentionally fail-closed.

Observed Hermes artifacts have different meanings:

- runtime mirrors expose execution fields such as `native_state`, `blueprint_state`, `plan_id`, and `updated_at`; these are **not** treated as verdicts;
- successful stage receipts may have `status=SUCCEEDED` while their `validation` block contains only stage-specific checks; `SUCCEEDED` alone is **not** treated as PASS;
- an authoritative receipt must contain both `status=SUCCEEDED` and an explicit supported `validation.decision`;
- `completed_at` becomes the evidence timestamp and must be timezone-aware;
- `(task_id, stage, attempt)` forms the logical evidence identity;
- supersession is never inferred from attempt number; callers must provide explicit `supersedes` evidence ids;
- if both a current receipt snapshot and its history copy are ingested, they resolve to the same evidence id so the resolver rejects double counting instead of silently duplicating evidence.

```python
from current_status_resolver.hermes_adapter import evidence_from_hermes_receipt

evidence = evidence_from_hermes_receipt(
    reviewer_receipt,
    evidence_path="jobs/running/<task>/receipts/REVIEWER.json",
)
```

The adapter performs no file or runtime writes and does not mutate its input mapping. It only converts an already-read receipt object into validated `Evidence`.

### Operational validation scope

The adapter contract was derived from read-only inspection of Frozen Legacy Hermes artifacts at its pinned Git HEAD. Tests use sanitized structures matching the observed runtime-mirror, reviewer receipt, non-verdict successful receipt, and receipt-history shapes.

This validates **format compatibility and fail-closed behavior**. It does not mean the module has been wired into the separate Hermes Agent OS runtime. Runtime wiring remains a distinct integration step and must occur in the Agent OS workspace/repository without modifying Frozen Legacy.

## Read-only runtime bridge

The package includes a narrow filesystem bridge for the Agent OS consumption
boundary. It scans only JSON files below `receipts` directories, groups evidence
by `(task_id, stage)`, de-duplicates identical current/history snapshots, and
returns a JSON current-status record. It does not write to Hermes state, queues,
receipts, runtime mirrors, or Production.

```bash
hermes-current-status \
  --receipt-root H:\\Aiwork\\Hermes-Agent-OS \
  --task-id <TASK_ID> \
  --stage REVIEWER
```

The task/stage selectors are the safe operational mode when the root also contains
successful non-verdict receipts from stages such as Publisher or Fact Guardian.
Without selectors, every discovered receipt is evaluated; any malformed or
non-authoritative receipt is reported in `rejected` and makes the overall
`safe_to_consume` value false. This prevents a stale accepted verdict from being
consumed when a newer candidate receipt could not be parsed or validated.

Explicit supersession remains mandatory. A JSON manifest may map a later evidence
id to the older ids it supersedes:

```json
{
  "hermes-receipt/TASK-1/REVIEWER/attempt/2": [
    "hermes-receipt/TASK-1/REVIEWER/attempt/1"
  ]
}
```

Pass it with `--supersession-manifest <path>`. The command exits with code `2`
when there is no authoritative stream, a rejected selected receipt, a same-id
content conflict, an ambiguous latest verdict, or an invalid supersession
relation. Exit code `0` means the evidence is safe to consume **and** every
selected stream has an acceptance-passing verdict (`PASS`, `PROVEN`, or
`PROVEN_NATIVE_E2E`). Exit code `1` means the evidence is safe to consume but at
least one selected stream is authoritatively `FAIL` or `PARTIAL`.

JSON output keeps these meanings separate as `safe_to_consume` and
`acceptance_passed`. Boss/Dev Factory consumers must never use
`safe_to_consume=true` as a synonym for acceptance success.

## Run gates

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/
mypy src/current_status_resolver/
```

The acceptance/regression suite covers historical preservation, explicit supersession, current-status selection, ambiguity, provenance paths, missing targets, empty-stream HOLD, chain traceability, timezone offset ordering, invalid timestamp rejection, duplicate ids, self-supersession, chronologically invalid supersession edges, Hermes `PROVEN` / `PROVEN_NATIVE_E2E` success states, and fail-closed compatibility with observed Hermes receipt/runtime-mirror shapes.
