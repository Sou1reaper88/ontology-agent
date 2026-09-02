# Dynamic Context Budget Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add low-frequency token-budget compaction while preserving complete raw conversation history and sharing one assembled context across every LLM call in a turn.

**Architecture:** A focused `agent.context_engineering` module estimates provider-neutral token usage and returns a bounded context snapshot. The conversation route persists only summary state and passes the snapshot into the existing orchestrator; planners and legacy generation render that same snapshot without owning persistence.

**Tech Stack:** Python 3.11, Pydantic Settings, SQLAlchemy/Alembic, pytest, existing OpenAI-compatible LLM client.

## Global Constraints

- Compression is token-budget-driven only; there is no periodic or turn-count trigger.
- Default trigger and target are 80% and 60% of effective history budget.
- Keep the latest six turns verbatim and never modify raw stored messages.
- Compression failure must not block SQL/program generation.

---

### Task 1: Context budget and assembler

**Files:**
- Create: `agent/context_engineering.py`
- Modify: `config/settings.py`
- Test: `tests/test_context_engineering.py`

**Interfaces:**
- Produces: `ContextAssembler.assemble(...) -> AssembledContext`
- Produces: `estimate_tokens(text: str) -> int`

- [ ] Write failing tests proving short history stays verbatim, long history compacts only the old prefix, prior summary boundaries are respected, and summarizer failure uses deterministic fallback.
- [ ] Run `pytest tests/test_context_engineering.py -q` and confirm failures are caused by the missing module.
- [ ] Implement the estimator, budget calculation, structured summary prompt, and bounded fallback.
- [ ] Run `pytest tests/test_context_engineering.py -q` and confirm all tests pass.

### Task 2: Persistence and all-call integration

**Files:**
- Modify: `models/conversation.py`
- Create: `alembic/versions/*_add_context_summary_state.py`
- Modify: `api/routes/conversation.py`
- Modify: `agent/orchestrator.py`
- Modify: `agent/program_generation.py`
- Modify: `agent/program_planner.py`
- Modify: `tools/llm_client.py`
- Test: `tests/test_conversation.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_program_planner.py`

**Interfaces:**
- Consumes: `AssembledContext.messages`, `summary`, and `compacted_through_message_id`.
- Produces: a single rendered context supplied to planning, repair, rule derivation, and legacy SQL generation.

- [ ] Write failing tests for summary persistence and context visibility in all model-call paths.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Add database fields and route integration, then thread the assembled context through planner and legacy paths.
- [ ] Run focused tests, followed by the relevant backend suite.
- [ ] Commit the verified implementation and start the existing local services for user review.

