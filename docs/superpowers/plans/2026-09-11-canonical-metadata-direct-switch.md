# Canonical Metadata Pipeline Direct Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route metadata-grounded generation through the canonical relational plan and compiler as the default production path, with dynamic relationship evidence and no automatic fallback.

**Architecture:** Reuse the existing metadata candidate catalog, validated inference contracts, canonical relational nodes, and Hive compiler. Add one small relationship-evidence model and one adapter from validated metadata inference to `CanonicalRelationalPlan`; keep legacy generation behind one explicit configuration value and never run both paths for one request.

**Tech Stack:** Python 3.11+, Pydantic v2, existing DeepSeek-compatible HTTP client, existing ontology runtime, existing `sqlglot` validation, pytest.

## Global Constraints

- Generate SQL programs only; never connect to or execute against the business Hive database.
- The production default is `canonical`; `legacy` is an explicit whole-request rollback mode, not an automatic fallback.
- Do not run a shadow pipeline or return two SQL programs.
- A missing confirmed ontology relationship does not block generation when the model proposes a real, type-compatible relationship with evidence.
- Physical tables and fields must bind to one immutable published ontology snapshot.
- Do not add LangChain, NetworkX, a graph database, or a new persistence layer.
- Reuse `ProgramDiagnostic`, `MetadataCandidateCatalog`, `CanonicalRelationalPlan`, and `HiveRelationalCompiler`.
- Write the failing focused test before production code; run the focused suite before each commit.
- Commit and push every independently passing task to `origin`.

---

### Task 1: Dynamic relationship evidence

**Files:**
- Create: `ontology_core/relation_evidence.py`
- Modify: `ontology_core/inference_models.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_relation_evidence.py`
- Test: `tests/ontology_core/test_inference_models.py`

**Interfaces:**
- Consumes: `CandidateContext`, `InferredJoinDraft`, `MetadataCandidateCatalog`.
- Produces: `RelationEvidenceSource`, `RelationEvidenceEdge`, `RelationEvidenceGraph`, and `build_relation_evidence_graph(...)`.

- [x] **Step 1: Write failing relationship-evidence tests**

Cover these behaviors in `tests/ontology_core/test_relation_evidence.py`:

```python
def test_graph_contains_confirmed_ontology_relation() -> None:
    graph = build_relation_evidence_graph(_candidates(), _catalog_with_relation())
    assert graph.edges[0].source == RelationEvidenceSource.ONTOLOGY
    assert graph.edges[0].confidence == Confidence.HIGH


def test_graph_accepts_model_relation_without_confirmed_ontology_edge() -> None:
    graph = build_relation_evidence_graph(
        _candidates(),
        _catalog_without_relations(),
        proposed_joins=(_model_join(),),
    )
    assert graph.edges[0].source == RelationEvidenceSource.MODEL
    assert graph.edges[0].confidence == Confidence.MEDIUM


def test_graph_rejects_unknown_or_incompatible_proposed_fields() -> None:
    with pytest.raises(ValueError, match="关联字段"):
        build_relation_evidence_graph(
            _candidates(),
            _catalog_without_relations(),
            proposed_joins=(_unknown_join(),),
        )
```

Add an inference-model test proving that `relation_source` defaults to `model` and accepts `user`:

```python
assert InferredJoinDraft(**payload).relation_source == "model"
assert InferredJoinDraft(**payload, relation_source="user").relation_source == "user"
```

- [x] **Step 2: Run the tests and verify the missing API failure**

Run:

```powershell
pytest tests/ontology_core/test_relation_evidence.py tests/ontology_core/test_inference_models.py -q
```

Expected: collection or import failure because `ontology_core.relation_evidence` and `relation_source` do not exist.

- [x] **Step 3: Implement the minimal immutable graph**

Add to `ontology_core/inference_models.py`:

```python
class InferredJoinDraft(FrozenModel):
    relation_source: Literal["user", "model"] = "model"
    join_type: Literal["inner", "left", "anti"] = "inner"
    anti_strategy: Literal["left_join", "not_exists"] = "left_join"
    left_object_ref: SemanticRef
    left_field_ref: SemanticRef
    right_object_ref: SemanticRef
    right_field_ref: SemanticRef
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)
```

Implement `ontology_core/relation_evidence.py` with these public contracts:

```python
class RelationEvidenceSource(StrEnum):
    ONTOLOGY = "ontology"
    USER = "user"
    MODEL = "model"


class RelationEvidenceEdge(FrozenModel):
    left_object_ref: SemanticRef
    left_field_ref: SemanticRef
    right_object_ref: SemanticRef
    right_field_ref: SemanticRef
    join_type: Literal["inner", "left", "anti"]
    source: RelationEvidenceSource
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)


class RelationEvidenceGraph(FrozenModel):
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_refs: tuple[SemanticRef, ...]
    edges: tuple[RelationEvidenceEdge, ...] = ()

    def matching(self, left_field_ref: str, right_field_ref: str) -> RelationEvidenceEdge | None:
        return next(
            (
                edge
                for edge in self.edges
                if (edge.left_field_ref, edge.right_field_ref)
                in {(left_field_ref, right_field_ref), (right_field_ref, left_field_ref)}
            ),
            None,
        )


def build_relation_evidence_graph(
    candidates: CandidateContext,
    catalog: MetadataCandidateCatalog,
    *,
    proposed_joins: tuple[InferredJoinDraft, ...] = (),
) -> RelationEvidenceGraph:
    """Bind confirmed ontology edges and model/user proposals to real candidate fields."""
```

The implementation must map ontology concept/property URIs to candidate short-name refs, ignore inactive or unconfirmed ontology relations, validate every proposed field and its owner, reject incompatible datatype groups, deduplicate identical edges, and cap model confidence at `medium`. Do not generate all possible field pairs.

Export the four public names from `ontology_core/__init__.py`.

- [x] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/ontology_core/test_relation_evidence.py tests/ontology_core/test_inference_models.py -q
```

Expected: all selected tests pass.

- [x] **Step 5: Commit and push**

```powershell
git add ontology_core/relation_evidence.py ontology_core/inference_models.py ontology_core/__init__.py tests/ontology_core/test_relation_evidence.py tests/ontology_core/test_inference_models.py
git commit -m "feat: add dynamic relation evidence graph"
git push origin HEAD
```

---

### Task 2: Preserve aggregation semantics in metadata inference

**Files:**
- Modify: `ontology_core/inference_models.py`
- Modify: `ontology_core/inference_validation.py`
- Modify: `ontology_core/__init__.py`
- Modify: `tools/llm_client.py`
- Test: `tests/ontology_core/test_inference_models.py`
- Test: `tests/ontology_core/test_inference_validation.py`
- Test: `tests/test_metadata_inference_llm.py`

**Interfaces:**
- Consumes: semantic field refs already present in `CandidateContext`.
- Produces: `InferredAggregationDraft`, `ValidatedInferredAggregation`, `group_by_field_refs`, and `aggregations` on validated inference output.

- [x] **Step 1: Write failing aggregation contract tests**

Add tests for a grouped distinct count and for rejection of a missing source on `sum`:

```python
draft = InferredAggregationDraft(
    name="user_count",
    function="count",
    source_field_ref="User.user_id",
    distinct=True,
)
assert draft.function == "count"

with pytest.raises(ValidationError, match="数值聚合"):
    InferredAggregationDraft(name="amount", function="sum")
```

Add validator coverage proving group fields and aggregation sources must belong to selected objects and `sum`/`avg` require numeric datatype groups.

- [x] **Step 2: Run tests and verify schema failures**

```powershell
pytest tests/ontology_core/test_inference_models.py tests/ontology_core/test_inference_validation.py tests/test_metadata_inference_llm.py -q
```

Expected: failures because the aggregation contracts are absent.

- [x] **Step 3: Add the minimal aggregation fields**

Implement:

```python
class InferredAggregationDraft(FrozenModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    function: Literal["count", "sum", "avg", "min", "max"]
    source_field_ref: SemanticRef | None = None
    distinct: bool = False


class ValidatedInferredAggregation(FrozenModel):
    name: str
    function: Literal["count", "sum", "avg", "min", "max"]
    source_field: CandidateField | None = None
    distinct: bool = False
```

Extend `InferredProgramDraft` with:

```python
group_by_field_refs: tuple[SemanticRef, ...] = ()
aggregations: tuple[InferredAggregationDraft, ...] = ()
```

Extend `ValidatedInferredProgram` with bound `group_by_fields` and `aggregations`. Keep `requested_field_refs` required for this phase; a pure aggregate without a business output field remains unsupported.

Update `MetadataInferenceValidator.validate(...)` to bind fields, reject unknown ownership, and require numeric fields for `sum` and `avg`. Update the model prompt to say aggregation belongs in these fields and SQL expressions remain forbidden.

Export both aggregation contracts from `ontology_core/__init__.py`.

- [x] **Step 4: Run focused tests**

```powershell
pytest tests/ontology_core/test_inference_models.py tests/ontology_core/test_inference_validation.py tests/test_metadata_inference_llm.py -q
```

Expected: all selected tests pass.

- [x] **Step 5: Commit and push**

```powershell
git add ontology_core/inference_models.py ontology_core/inference_validation.py ontology_core/__init__.py tools/llm_client.py tests/ontology_core/test_inference_models.py tests/ontology_core/test_inference_validation.py tests/test_metadata_inference_llm.py
git commit -m "feat: preserve inferred aggregation semantics"
git push origin HEAD
```

---

### Task 3: Convert validated inference to the canonical relational plan

**Files:**
- Create: `ontology_core/inference_to_relational.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_inference_to_relational.py`

**Interfaces:**
- Consumes: `ValidatedInferredProgram` and `RelationEvidenceGraph` from Tasks 1–2.
- Produces: `InferenceRelationalAdapter.convert(plan, relation_graph) -> CanonicalRelationalPlan`.

- [ ] **Step 1: Write failing adapter tests**

Cover four plans:

```python
def test_converts_single_table_filters_and_default_time_to_result_ctas_plan(): ...
def test_converts_family_to_union_then_materializes_before_join(): ...
def test_normalizes_reversible_inner_join_direction(): ...
def test_preserves_left_and_anti_join_direction(): ...
def test_converts_grouped_aggregation(): ...
def test_rejects_disconnected_or_unsupported_relation_evidence(): ...
```

Assert node order and types, not rendered SQL. In the family case assert `scan → union_all → intermediate materialize → join → result materialize`. In the anti case assert the requested right-side output is rejected.

- [ ] **Step 2: Run tests and verify the adapter import failure**

```powershell
pytest tests/ontology_core/test_inference_to_relational.py -q
```

Expected: collection failure because `InferenceRelationalAdapter` does not exist.

- [ ] **Step 3: Implement one deterministic adapter**

Create:

```python
class InferenceRelationalAdapter:
    def convert(
        self,
        plan: ValidatedInferredProgram,
        relation_graph: RelationEvidenceGraph,
    ) -> CanonicalRelationalPlan:
        ...
```

The adapter must:

1. Scan every selected object once and include only requested, join, filter, group, aggregation, and partition fields.
2. Convert each selected family to member scans plus `UnionAllNode`; insert an intermediate `MaterializeNode` and use it as the family source.
3. Start from the object or family providing requested output fields.
4. Reorder only `inner` joins when needed to connect a new source; never reverse `left` or `anti`.
5. Apply source-local `where` and temporal predicates in a `FilterNode` immediately after that source. Put a directed join's right-side `match` and temporal predicates in `JoinNode.match_filters`. A post-join predicate must reference a column explicitly propagated by the `JoinNode`; do not let a downstream filter refer back to a scan node.
6. Add `AggregateNode` when grouping or aggregations exist, then `ProjectNode` only when needed to preserve requested output order.
7. End with exactly one `MaterializeNode(step_kind=RESULT)`.
8. Reject disconnected sources, unknown relation evidence, ambiguous duplicate output names, and cross-snapshot graphs with `OntologyCompileError`.

Use stable node IDs derived from ordered object refs (`scan_01`, `union_01`, `join_01`, `filter_01`, `aggregate_01`, `project_01`, `result`) rather than introducing a naming service.

- [ ] **Step 4: Run adapter and existing canonical tests**

```powershell
pytest tests/ontology_core/test_inference_to_relational.py tests/ontology_core/test_relational_plan.py tests/ontology_core/test_relational_compiler.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit and push**

```powershell
git add ontology_core/inference_to_relational.py ontology_core/__init__.py tests/ontology_core/test_inference_to_relational.py
git commit -m "feat: bind metadata inference to canonical plans"
git push origin HEAD
```

---

### Task 4: Compile metadata inference only through the canonical compiler

**Files:**
- Modify: `agent/metadata_inference.py`
- Modify: `agent/program_generation.py`
- Modify: `tools/llm_client.py`
- Test: `tests/test_metadata_inference.py`
- Test: `tests/test_metadata_inference_llm.py`

**Interfaces:**
- Consumes: `build_relation_evidence_graph`, `InferenceRelationalAdapter`, `RelationalCompilerRegistry`.
- Produces: `MetadataInferenceOutcome.plan: CanonicalRelationalPlan | None`, `MetadataInferenceOutcome.relation_graph: RelationEvidenceGraph | None`, matching fields on `ProgramGenerationResult`, and canonical `CompiledProgram`.

- [ ] **Step 1: Write failing orchestration tests**

Update the inference-service fakes and assert this order:

```python
assert calls == [
    "snapshot",
    "retrieve",
    "build_initial_relation_graph",
    "llm",
    "build_complete_relation_graph",
    "validate",
    "adapt",
    "snapshot",
    "compile",
]
```

Add tests that confirmed relationships are sent to the LLM, model-proposed relationships can compile without ontology relations, and provider failures remain `inferred_plan_provider_unavailable` rather than plan errors.

- [ ] **Step 2: Run tests and verify they fail on the old compiler path**

```powershell
pytest tests/test_metadata_inference.py tests/test_metadata_inference_llm.py -q
```

Expected: assertions fail because the service still invokes `HiveInferenceCompiler` directly.

- [ ] **Step 3: Replace only the inference compile seam**

Change `MetadataInferenceService` defaults to:

```python
self._adapter = adapter or InferenceRelationalAdapter()
self._registry = registry or RelationalCompilerRegistry.default()
```

The service flow becomes:

```python
initial_graph = build_relation_evidence_graph(candidates, catalog)
draft = self._client.infer_metadata_program(
    request=request,
    candidates=candidates,
    relation_evidence=initial_graph,
    lookup_fields=lookup,
    **context_kwargs,
)
complete_graph = build_relation_evidence_graph(
    lookup.enriched(),
    catalog,
    proposed_joins=draft.joins,
)
validated = self._validator.validate(
    draft,
    candidates=lookup.enriched(),
    catalog=catalog,
    relation_graph=complete_graph,
    system_time=system_time,
    request=request,
)
canonical = self._adapter.convert(validated.plan, complete_graph)
program = self._registry.get(canonical.dialect).compile(
    canonical,
    program_id=program_id,
)
```

Change the outcome `plan` type and `ProgramGenerationResult.inferred_plan` type to `CanonicalRelationalPlan | None`, and add:

```python
relation_graph: RelationEvidenceGraph | None = None
```

to both result models. Extend the inference client protocol and `LLMClient.infer_metadata_program(...)` with `relation_evidence: RelationEvidenceGraph`; serialize it beside the candidate context. Keep snapshot-hash verification immediately before compilation. Do not catch provider/network failures as validation or compilation failures. Return the complete relation graph for the later LangGraph state and diagnostic tool; do not persist a second copy elsewhere.

- [ ] **Step 4: Run focused inference tests**

```powershell
pytest tests/test_metadata_inference.py tests/test_metadata_inference_llm.py tests/ontology_core/test_inference_to_relational.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit and push**

```powershell
git add agent/metadata_inference.py agent/program_generation.py tools/llm_client.py tests/test_metadata_inference.py tests/test_metadata_inference_llm.py
git commit -m "feat: compile inference through canonical pipeline"
git push origin HEAD
```

---

### Task 5: Directly switch production generation with explicit rollback

**Files:**
- Modify: `config/settings.py`
- Modify: `config/settings.yaml`
- Modify: `agent/program_generation.py`
- Modify: `agent/orchestrator.py`
- Modify: `evaluation/generation.py`
- Test: `tests/test_program_generation.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/evaluation/test_runner.py`

**Interfaces:**
- Consumes: canonical `MetadataInferenceService` from Task 4.
- Produces: `settings.sql_pipeline: Literal["canonical", "legacy"]`, defaulting to `canonical`.

- [ ] **Step 1: Write failing direct-switch tests**

Add tests proving:

```python
assert Settings().sql_pipeline == "canonical"

def test_canonical_failure_never_calls_old_planner_or_legacy_graph(): ...
def test_canonical_success_is_the_only_sql_returned(): ...
def test_explicit_legacy_mode_runs_only_legacy_graph(): ...
def test_evaluation_reads_the_single_canonical_result(): ...
```

The canonical failure assertion must check the original diagnostic and missing information survive unchanged.

- [ ] **Step 2: Run tests and verify automatic planner fallback is still observable**

```powershell
pytest tests/test_program_generation.py tests/test_orchestrator.py tests/evaluation/test_runner.py -q
```

Expected: direct-switch tests fail because `ProgramGenerationService` still calls `AdaptiveProgramPlanner` after inference failure and no `sql_pipeline` setting exists.

- [ ] **Step 3: Remove automatic fallback from the canonical path**

Add to `Settings` and YAML:

```python
sql_pipeline: Literal["canonical", "legacy"] = "canonical"
```

Import `Literal` in `config/settings.py` and import `settings` in `agent/orchestrator.py`; do not add a new settings class for one value.

Simplify `ProgramGenerationService.generate(...)` to:

```python
def generate(
    self,
    query: str,
    *,
    request_id: str,
    system_time: datetime,
    conversation_context: str | None = None,
) -> ProgramGenerationResult:
    result = self._infer(
        query,
        program_id=derive_program_id(request_id),
        system_time=system_time,
        conversation_context=conversation_context,
        origin_diagnostics=(),
        failure_mode=ProgramGenerationMode.UNSUPPORTED,
    )
    assert result is not None
    return result
```

Remove `AdaptiveProgramPlanner`, `legacy_sql_factory`, `allow_legacy_compatibility`, `_fallback`, and `_wrap_legacy` from the canonical service and factory. In `run_agent(...)`, select exactly one whole-request path:

```python
if settings.sql_pipeline == "legacy":
    return _run_legacy_agent(...)
return _run_canonical_agent(...)
```

Delete ontology-shadow appending from canonical output. Update the evaluation adapter to map `output["sql"]` to `ontology_sql`, leave `legacy_sql=None`, and never invoke `OntologyShadowService`; the existing comparison-column redesign is deferred with the evaluation-center upgrade.

- [ ] **Step 4: Run affected generation tests**

```powershell
pytest tests/test_program_generation.py tests/test_orchestrator.py tests/evaluation/test_runner.py -q
```

Expected: all selected tests pass and no assertion observes a second generation path.

- [ ] **Step 5: Commit and push**

```powershell
git add config/settings.py config/settings.yaml agent/program_generation.py agent/orchestrator.py evaluation/generation.py tests/test_program_generation.py tests/test_orchestrator.py tests/evaluation/test_runner.py
git commit -m "feat: switch generation to canonical pipeline"
git push origin HEAD
```

---

### Task 6: Focused production-path verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/project-journal/2026-09.md`
- Test: existing affected Python suites

**Interfaces:**
- Consumes: the production canonical path from Tasks 1–5.
- Produces: one documented generation architecture and a recorded verification result.

- [ ] **Step 1: Run the focused regression suite**

```powershell
pytest tests/ontology_core/test_relation_evidence.py tests/ontology_core/test_inference_models.py tests/ontology_core/test_inference_validation.py tests/ontology_core/test_inference_to_relational.py tests/ontology_core/test_relational_plan.py tests/ontology_core/test_relational_compiler.py tests/test_metadata_inference.py tests/test_metadata_inference_llm.py tests/test_program_generation.py tests/test_orchestrator.py tests/evaluation/test_runner.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run one complete Python regression**

```powershell
pytest -q
```

Expected: no failures. Record the exact pass/skip counts; do not claim success from an earlier run.

- [ ] **Step 3: Update only stale architecture documentation**

Update `README.md` to say:

```text
The default SQL path is metadata retrieval → dynamic relation evidence → canonical relational plan → deterministic Hive compilation. The system generates scripts only and does not execute them. `sql_pipeline: legacy` is an operator-only rollback mode; failures never trigger automatic fallback.
```

Add one dated journal entry containing the direct-switch decision, files changed, focused/full test counts, known limitations, and the next phase: LangGraph top-level orchestration with `search_ontology`, `generate_sql_program`, and `analyze_generation`.

- [ ] **Step 4: Commit and push**

```powershell
git add README.md docs/project-journal/2026-09.md
git commit -m "docs: record canonical pipeline switch"
git push origin HEAD
```

---

## Deferred to the next implementation plan

- Replace `conversation_agent.py`'s hand-written two-turn loop with a request-scoped LangGraph state machine.
- Add the read-only `search_ontology` and `analyze_generation` top-level tools; keep `generate_sql_program` as the only generation tool.
- Persist the existing public trace, not LangGraph checkpoints or internal reasoning.
- Upgrade the evaluation center for canonical multi-step plan comparison.
- Add explicit ontology-managed source groups only after the current inferred table-family behavior is measured against the seven real cases.
