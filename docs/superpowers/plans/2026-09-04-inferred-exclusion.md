# Inferred exclusion implementation plan

**Goal:** Correctly exclude users matching either related table without changing source data.

**Architecture:** Plans declare inner, left or anti join semantics. Anti joins choose left_join or not_exists rendering; the compiler places matching filters and right-side partitions inside ON/subquery and never reverses directed edges. Critical unsupported requirements block generation, while ordinary ontology suggestions remain non-blocking.

**Tech Stack:** Python, Pydantic, existing Hive compiler, pytest, SQLite synthetic verification.

## Constraints

No production SQL execution. No failed-plan retries. No real metadata in Git. Preserve pre-existing date modifications. Both anti renderings supported; default left_join, model may choose not_exists. Anti right sides must be leaves and cannot supply result fields. Left/anti graphs whose preserved root cannot be resolved are rejected rather than reversed. Join-right matching filters are separate from post-join WHERE filters. Single equality keys only in this increment.

## Steps

- [x] Add red tests: anti join returns only unmatched synthetic users for both renderings, including duplicates, null keys and two exclusion tables; right partitions remain in matching scope; ordinary left preserves unmatched rows; unresolved critical requirements block validation.
- [x] Extend inference models with join_type, anti_strategy, filter scope and blocking_issues; validate references, directed topology and unsafe anti output/dependencies.
- [x] Compile directed joins with scoped predicates; emit IS NULL or NOT EXISTS; reject unsupported graph shapes rather than silently dropping edges.
- [x] Explain semantics and blocking_issues in planner prompt; run targeted compiler/validation/LLM tests.
- [ ] Record results, commit only this change, restart backend and check readiness. Real model retest limited to one case if needed.

Verification: 47 targeted tests passed. One real model rerun generated two anti/not_exists operations. Backend restart not executed: permission review timed out twice.
