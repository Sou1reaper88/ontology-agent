# LLM SQL Authoring Implementation Plan

> **For agentic workers:** Use executing-plans inline; execute the already approved design without another approval round.

**Goal:** Switch production SQL generation from Python rendering to model-authored scripts with static validation.

**Architecture:** Reuse the natural conversation host and metadata lookup loop. A SQL author service returns the existing program response without a relational plan. sqlglot validates a copy; original SQL is preserved.

**Tech Stack:** Python, existing httpx/pydantic/sqlglot, existing pytest.

## Global Constraints

- No new dependency, no shadow SQL, no SQL execution, no trailing cleanup.
- Default partitions: day T-2, previous calendar month; explicit request dates take priority.
- No required pre-registered JOIN relation; retain model assumptions.
- NULL-or-zero is valid when business semantics justify it, not a universal rule.
- Focused simulated checks only; commit/push and restart backend after verification.

### Task 1: Script validation and author service

Files: `agent/sql_authoring.py`, `ontology_core/authored_sql.py`, `tools/metadata_lookup.py`, `tests/test_sql_authoring.py`.

- [ ] Add focused tests for unchanged SQL, CTE policy, invented fields, unsafe DDL, unbounded partitions, JOIN inference and one repair.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_sql_authoring.py -q`; observe missing new functionality.
- [ ] Implement `validate_authored_program(sql, *, program_id, catalog, request, allow_cte, assumptions)` and `SqlAuthoringService.generate(query, *, request_id, system_time, conversation_context, allow_cte)`.
- [ ] Extend existing metadata tool loop with optional `validate_sql_program` callback; keep old callers unchanged.
- [ ] Re-run targeted checks until passing; do not execute SQL.

### Task 2: Default integration

Files: `agent/program_generation.py`, `agent/orchestrator.py`, `agent/conversation_agent.py`, `config/settings.py`, `config/settings.yaml`.

- [ ] Add a default-factory check proving author service is selected rather than a compiler.
- [ ] Select `llm` as default pipeline, retain explicit legacy configuration only.
- [ ] Pass model-interpreted CTE constraint through host and generation call; expose package, assumptions and authored-program label using current frontend contract.
- [ ] Run author, lookup, conversation, program generation and orchestrator checks.
- [ ] Record actual results/boundaries in journal; commit/push main integration and restart backend.
