# Conversation-Aligned SQL Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New evaluation runs use the current conversation agent and compare safe multistep CTAS programs without awarding misleading scores.

**Architecture:** Keep the existing import, runner, case persistence, comparison dimensions and API. Replace only the generation adapter, add a program-aware SQL-structure extraction path, and mark ambiguous lineage unscorable. Store an engine marker in the existing summary JSON so old runs remain distinguishable without migration.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Pydantic, sqlglot, pytest; React, TypeScript, Ant Design.

## Global Constraints

- No business SQL execution, no evaluation-created conversation or query record, and no automatic seven-case DeepSeek run.
- One current-agent invocation per case; no extra model judge or retry layer in the evaluator.
- Preserve old run records and API paths. New runs use `summary.engine = "conversation-v1"`; missing marker denotes a historical run.
- Only trustworthy structures can receive six-dimension scores. Unknown CTAS lineage, unsupported SQL and failed delivery return `score = null` with `manual_review_required`.
- Do not stage the pre-existing `frontend/tsconfig.tsbuildinfo`, `.codex-artifacts/`, or `docs/prompts/` changes from the main checkout.

---

### Task 1: Generate with the current conversation agent

**Files:**
- Modify: `evaluation/generation.py`
- Modify: `evaluation/runner.py`
- Modify: `api/routes/evaluations.py` to mark newly imported runs
- Test: `tests/evaluation/test_runner.py`
- Test: `tests/evaluation/test_generation.py` (new)
- Test: `tests/test_evaluations.py`

**Interfaces:** `AgentEvaluationAdapter.generate(requirement: str, *, system_time: str) -> GenerationSnapshot` stays stable. `run_conversation_agent` returns `success`, `sql`, `generation_mode`, `diagnostics`, `trace`, and `markdown`. The runner keeps its existing serial per-case entry point.

- [ ] **Step 1: Write failing adapter tests.** Inject a fake callable into `AgentEvaluationAdapter`. Assert it receives `history=[]`, `system_time`, and a bounded first-turn `assembled_context`; successful `authored_program` preserves SQL and package information from the `program_generation` trace; `authored_draft` preserves the SQL but reports a non-generated status; provider failures keep the specific diagnostic code. Assert the fake does not create `Conversation` or `QueryHistory` rows.

  ```python
  def fake_agent(requirement, **kwargs):
      assert requirement == "统计用户"
      assert kwargs["history"] == []
      assert kwargs["system_time"] == "2026-08-24"
      return {"success": True, "sql": "SELECT ID FROM T", "generation_mode": "authored_query",
              "markdown": "已生成", "trace": [{"node": "program_generation", "payload":
              {"package": {"package_id": "p", "version": "1", "sha256": "a" * 64}}}]}
  assert AgentEvaluationAdapter(run_agent_fn=fake_agent).generate(
      "统计用户", system_time="2026-08-24").ontology_status == "generated"
  ```
- [ ] **Step 2: Verify red.** Run `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/evaluation/test_generation.py -q` and confirm failures identify the old `run_agent` adapter behavior.
- [ ] **Step 3: Implement the adapter.** Replace the import of `agent.orchestrator.run_agent` with `agent.conversation_agent.run_conversation_agent`; assemble empty-history context using `get_context_assembler().assemble((), current_input=requirement).render()`. Pass a deterministic evaluation request id, `history=[]`, and fixed `system_time`. Extract package from the last trace step carrying a package, falling back to current runtime health only when needed. Map `authored_program`/`authored_query` success to `generated`, `authored_draft` to `draft`, no-SQL conversation answer to `no_match`, and provider failures to `unavailable`; preserve `sql` for drafts. Keep the existing elapsed-time measurement.
- [ ] **Step 4: Guard score eligibility and preserve engine identity.** In `EvaluationRunner._evaluate_case`, parse drafts only for display but set their comparison to an unscorable `draft_not_deliverable`; never count them as generated. Put `"engine": "conversation-v1"` in new-run summary from creation onward and preserve it in `_summary`. Keep historical `summary` dicts untouched. Extend the status-to-diagnosis map with `draft`.
- [ ] **Step 5: Verify green and commit.** Run the focused generation/runner/API tests; stage only these files and commit `feat: evaluate current conversation agent`.

### Task 2: Extract final-result semantics from CTAS programs

**Files:**
- Modify: `evaluation/sql_structure.py`
- Modify: `evaluation/comparison.py` only if a new unscorable diagnosis is needed
- Modify: `evaluation/runner.py` to call the new extraction entry point
- Test: `tests/evaluation/test_sql_structure.py`
- Test: `tests/evaluation/test_comparison.py`

**Interfaces:** Keep `extract_sql_structure(sql, dialect)` for legacy single-query callers. Add `extract_evaluable_structure(sql: str, dialect: str) -> SqlStructure`, returning the same serializable contract. Parsed CTAS structures represent the SELECT semantics of the final result and its reachable dependencies; an unsupported or ambiguous graph has `warnings`, causing existing comparison to return `score=None` and `manual_review_required`.

- [ ] **Step 1: Write failing parser tests.** Cover a single SELECT, one DROP/CREATE pair, two dependent CTAS pairs, different temporary target names between reference and candidate, an unused staging step, a missing/cyclic/ambiguous dependency, a non-pass-through output expression, and an INSERT/UPDATE. For a simple two-step script, assert physical source tables and filters from the first step appear while the final output columns come from the final step. For unknown lineage, assert `warnings` and a null score rather than strict pass.

  ```python
  sql = """DROP TABLE IF EXISTS temp_oa_a_base;
  CREATE TABLE temp_oa_a_base AS SELECT ID FROM USER_D WHERE P_DAY='20260822';
  DROP TABLE IF EXISTS temp_oa_a_result_table;
  CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM temp_oa_a_base"""
  structure = extract_evaluable_structure(sql, "hive")
  assert structure.status == "parsed"
  assert structure.tables == ("user_d",)
  assert "temp_oa_a_base" not in structure.tables
  ```
- [ ] **Step 2: Verify red.** Run `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/evaluation/test_sql_structure.py tests/evaluation/test_comparison.py -q`; new tests should fail because `extract_evaluable_structure` is absent.
- [ ] **Step 3: Implement minimal AST-only extraction.** Parse with sqlglot using the requested dialect. If there is one `exp.Query`, delegate to `extract_sql_structure`. Otherwise accept only CTAS `exp.Create` statements, optional matching `exp.Drop`, and optional final `exp.Query`. Index CTAS targets case-insensitively, reject duplicate targets and forward/missing temporary dependencies, and walk backward from the final result to reachable steps. Extract each reachable SELECT with the existing query helper. Union physical base tables, predicates, partitions and joins from reachable steps; use final SELECT projections, aggregates, grouping, ordering and limit. Resolve only direct pass-through column aliases across a temporary table; if an output/condition cannot be attributed safely, add `unresolved_program_lineage` and leave the case unscorable. Never execute or rewrite submitted SQL.
- [ ] **Step 4: Integrate runner and diagnostics.** Use the new extractor for both reference and candidate. Preserve source SQL in case details. Map unsupported program/unknown lineage to distinct displayable diagnosis codes; do not convert parse failure into 0 points. Ensure that successful simple programs can earn scores without comparing random temp-table names.
- [ ] **Step 5: Verify green and commit.** Run the parser, comparison and runner tests. Stage only Task 2 files and commit `feat: compare multistep SQL results`.

### Task 3: Show new and historical evaluation runs honestly

**Files:**
- Modify: `frontend/src/features/evaluation/types.ts`
- Modify: `frontend/src/features/evaluation/EvaluationRunView.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationCenter.tsx`
- Modify: `frontend/src/features/evaluation/viewModel.ts`
- Test: `frontend/tests/evaluation-view-model.test.ts` (new)
- Modify: `docs/project-journal/2026-10.md` (new)

**Interfaces:** `EvaluationSummary.engine?: "conversation-v1"`. Existing records without `engine` keep their Legacy/本体 presentation. New runs show 当前智能取数链路 and no meaningless Legacy card/column. The API shape and historical SQL stay unchanged.

- [ ] **Step 1: Write failing frontend contract tests.** Add pure presentation helpers to `viewModel.ts`: `evaluationEngineLabel(summary)` and `showLegacyComparison(summary)`. Assert new summary gives `当前智能取数链路`/`false`, while null or marker-free summary gives `历史评测`/`true`. Add tests for the new manual-review diagnosis label.

  ```typescript
  if (evaluationEngineLabel({ engine: "conversation-v1" }) !== "当前智能取数链路") throw Error("label");
  if (showLegacyComparison({ engine: "conversation-v1" })) throw Error("legacy must be hidden");
  if (!showLegacyComparison(null)) throw Error("historical legacy must remain visible");
  ```
- [ ] **Step 2: Verify red.** Bundle with `frontend/node_modules/.bin/esbuild.cmd` into a project-local ignored artifact and run it with Node; confirm missing helper fails.
- [ ] **Step 3: Implement minimal UI branching.** Add optional engine to TypeScript summary. In `EvaluationRunView.tsx` conditionally hide Legacy metric, dimension column, case-list score, detail SQL tab and Legacy path filter for new runs. Label new scores `当前智能取数` and old records `历史评测`; preserve navigation and all historical data. Update the import page copy to say the current agent will generate CTAS and ambiguous cases need human review.
- [ ] **Step 4: Verify build, document, commit.** Run the frontend contract test and `npm.cmd run build`; record the real checks and limitations in `docs/project-journal/2026-10.md`. Commit only intended files.

### Task 4: Focused integration and handoff

**Files:** No production file changes unless a focused check exposes a defect, in which case add a failing test before fixing.

- [ ] Run `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/evaluation tests/test_evaluations.py -q` and the frontend contract/build checks. Use only synthetic SQL and fake model responses.
- [ ] Verify `git diff --check`, migration/head status unchanged, and existing user files remain unstaged. Do not run the seven real cases or execute SQL.
- [ ] Start/restart the local app only if needed for page review, check `/ready` and `/evaluation`, then commit any focused repair. Merge/push according to the user's standing repository preference; report the commit, verification evidence, and what still requires human business review.
