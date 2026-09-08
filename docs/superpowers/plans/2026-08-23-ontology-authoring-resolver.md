# Ontology Authoring and Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standards-first external ontology authoring workflow and a deterministic Python `OntologyResolver` for concepts, properties, relations, rules, data sources, and physical mappings.

**Architecture:** Extend the existing immutable ontology snapshot with a parsed `SemanticCatalog`. RDF/OWL and SHACL remain the source format; a semantic parser converts marked domain elements into frozen Pydantic DTOs, and `OntologyResolver` builds snapshot-bound read-only indexes over those DTOs. A standard-library CLI initializes blank external packages, validates them through `OntologyRepository`, and emits safe inspection summaries.

**Tech Stack:** Python 3.11+, Pydantic 2.6+, RDFLib 7.6–7.x, pySHACL 0.40.x, PyYAML 6+, pytest 8+, Ruff, Black, build 1.2+, `argparse`, setuptools package data.

## Global Constraints

- Use Python only; do not add Java, Jena, a graph database, an LLM, a vector database, or a CLI framework.
- Use `urn:ontology-agent:core#` as the fixed project vocabulary namespace.
- Treat RDF/OWL plus SHACL as the canonical ontology format.
- Generate only blank package structure and generic vocabulary; do not generate built-in business examples.
- Keep real ontology packages outside the application repository and access them by explicit filesystem path.
- Do not store database hosts, ports, usernames, passwords, tokens, secrets, or connection strings in RDF mappings.
- Do not modify the existing Agent, SQL compiler, executor, REST behavior, or frontend behavior in this milestone.
- Return frozen Pydantic DTOs and tuples; never expose a mutable shared RDFLib graph.
- Keep search deterministic and independent of LLMs, tokenizers, embeddings, and external services.
- Use neutral `example.invalid` test data only; do not add real tables, fields, users, credentials, or business definitions.
- Write a failing test before each behavior change, verify the intended failure, implement the minimum behavior, rerun the focused test, and commit each logical task.
- Preserve unrelated user changes and stage only the files listed by the current task.
- Do not push or merge the branch without separate user authorization.

## Planned File Structure

### New production files

- `ontology_core/vocabulary.py`: fixed RDF namespace and term constants.
- `ontology_core/semantic_models.py`: frozen semantic DTOs and catalog.
- `ontology_core/semantic_parser.py`: RDF-to-DTO parsing, reference checks, condition-tree checks, and deterministic violation aggregation.
- `ontology_core/resolver.py`: snapshot-bound identifier indexes and deterministic concept search.
- `ontology_core/authoring.py`: blank external package initialization.
- `ontology_core/inspection.py`: safe package summary DTO and inspection service.
- `ontology_core/cli.py`: testable `argparse` command dispatcher.
- `ontology_core/__main__.py`: `python -m ontology_core` entry point.
- `ontology_core/resources/core.ttl`: generic project vocabulary copied by `init`.
- `ontology_core/resources/shapes.ttl`: generic SHACL constraints copied by `init`.
- `ontology_core/resources/__init__.py`: importlib resource package marker.
- `docs/ontology-authoring.md`: Protégé and CLI workflow.

### New test files

- `tests/ontology_core/test_semantic_models.py`
- `tests/ontology_core/test_semantic_parser.py`
- `tests/ontology_core/test_resolver.py`
- `tests/ontology_core/test_authoring.py`
- `tests/ontology_core/test_cli.py`

### Modified files

- `tests/test_ontology_relations.py`: remove dependence on a historical database seed.
- `ontology_core/errors.py`: add stable semantic lookup and validation error classes.
- `ontology_core/repository.py`: publish a public immutable snapshot containing `SemanticCatalog`.
- `ontology_core/__init__.py`: export the supported public API.
- `tests/fixtures/ontology_core/valid/*.ttl`: use the approved semantic markers and neutral complete graph.
- `tests/ontology_core/test_repository.py`: verify catalog publication and failed semantic reload rollback.
- `pyproject.toml`: include vocabulary resources and expose the optional `ontology-core` console command.
- `docs/project-journal/2026-08.md`: record verified implementation difficulties and decisions.
- `docs/career/project-story.md`: add only delivered and measured outcomes.

---

### Task 1: Restore a Self-Contained Green Test Baseline

**Files:**
- Modify: `tests/test_ontology_relations.py`

**Interfaces:**
- Consumes: `DbOntologyClient.get_ontology_definition(user_query: str, additional_context: str | None = None, ontology_id: str | None = None) -> dict[str, Any]`.
- Produces: a deterministic assembly test that does not depend on rows left in `ontology_meta.ontology_logical_defs`.

- [ ] **Step 1: Reproduce the existing failure**

Run:

```powershell
python -m pytest tests/test_ontology_relations.py::test_retrieval_returns_relations_and_defs -vv
```

Expected: FAIL because the assertion requires a historical logical-definition seed that is absent from the current metadata database.

- [ ] **Step 2: Confirm the root cause without printing database credentials**

Run:

```powershell
python -c "from tools.ontology_client import DbOntologyClient,clear_ontology_cache; clear_ontology_cache(); d=DbOntologyClient()._load_logical_defs(); print(ascii(sorted(d))); print('legacy_seed_present=', '\u6c89\u9ed8\u7528\u6237' in d)"
```

Expected: `legacy_seed_present= False`. Existing names may be rendered with Unicode escapes; this confirms valid Python strings while avoiding terminal encoding ambiguity.

- [ ] **Step 3: Replace the seed-dependent assertion with an isolated assembler contract**

Change the test to:

```python
def test_retrieval_returns_relations_and_defs(monkeypatch: pytest.MonkeyPatch) -> None:
    """检索器组装结果包含关系与逻辑定义，不依赖数据库历史种子。"""
    client = DbOntologyClient()
    monkeypatch.setattr(
        client,
        "_load_tables",
        lambda: [
            {
                "table_name": "EXAMPLE_ENTITY",
                "table_comment": "",
                "table_desc": "",
                "columns": [],
            }
        ],
    )
    monkeypatch.setattr(
        client,
        "_load_logical_defs",
        lambda: {"example_rule": "neutral contract description"},
    )
    monkeypatch.setattr(client, "_load_relations", lambda: [])
    monkeypatch.setattr(client, "_load_field_meta", lambda: {})

    definition = client.get_ontology_definition("查询数据")

    assert definition["relations"] == []
    assert definition["logical_definitions"] == {
        "example_rule": "neutral contract description"
    }
```

Add `import pytest` beside the existing test imports.

- [ ] **Step 4: Verify the focused and full baseline tests**

Run:

```powershell
python -m pytest tests/test_ontology_relations.py::test_retrieval_returns_relations_and_defs -vv
python -m pytest -q
```

Expected: focused test PASS; full suite exits `0` with no failures.

- [ ] **Step 5: Commit the isolated baseline fix**

```powershell
git add -- tests/test_ontology_relations.py
git commit -m "test: 移除本体检索的历史种子依赖"
```

---

### Task 2: Define the Generic Vocabulary and Frozen Semantic DTOs

**Files:**
- Create: `ontology_core/vocabulary.py`
- Create: `ontology_core/semantic_models.py`
- Create: `tests/ontology_core/test_semantic_models.py`
- Modify: `ontology_core/errors.py`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: `FrozenModel` from `ontology_core.models`.
- Produces: `OA`, semantic marker constants, `LocalizedText`, `RdfLiteral`, `RuleExpression`, `Concept`, `Property`, `Relation`, `BusinessRule`, `DataSource`, `PhysicalMapping`, and `SemanticCatalog`.

- [ ] **Step 1: Write failing DTO and error contract tests**

Create tests covering immutability, tuple coercion, recursive rule expressions, stable ordering inputs, and stable error codes. Core assertions:

```python
from pydantic import ValidationError

from ontology_core.errors import AmbiguousIdentifierError, ConceptNotFoundError
from ontology_core.semantic_models import (
    Concept,
    LocalizedText,
    RuleExpression,
    RuleOperator,
    SemanticCatalog,
)


def test_concept_and_catalog_are_immutable() -> None:
    concept = Concept(
        uri="https://example.invalid/domain/Record",
        short_name="Record",
        label="Record",
        labels=(LocalizedText(value="Record", language="en"),),
        parent_uris=(),
        child_uris=(),
    )
    catalog = SemanticCatalog(concepts=(concept,))

    with pytest.raises(ValidationError):
        concept.short_name = "Changed"
    with pytest.raises(ValidationError):
        catalog.concepts = ()


def test_rule_expression_uses_typed_recursive_children() -> None:
    expression = RuleExpression(
        operator=RuleOperator.ALL_OF,
        children=(RuleExpression(operator=RuleOperator.IS_NULL, property_uri="urn:p"),),
    )
    assert expression.children[0].operator is RuleOperator.IS_NULL


def test_semantic_lookup_errors_have_stable_codes() -> None:
    assert ConceptNotFoundError.code == "concept_not_found"
    assert AmbiguousIdentifierError.code == "ambiguous_identifier"
```

- [ ] **Step 2: Run the tests and verify missing imports**

Run:

```powershell
python -m pytest tests/ontology_core/test_semantic_models.py -vv
```

Expected: FAIL during collection because the new modules and classes do not exist.

- [ ] **Step 3: Add the fixed vocabulary constants**

Create `ontology_core/vocabulary.py` with the exact namespace and terms used by parser, resources, and tests:

```python
from rdflib import Namespace

OA = Namespace("urn:ontology-agent:core#")

CONCEPT = OA.Concept
PROPERTY = OA.Property
RELATION = OA.Relation
BUSINESS_RULE = OA.BusinessRule
DATA_SOURCE = OA.DataSource
PHYSICAL_MAPPING = OA.PhysicalMapping

SHORT_NAME = OA.shortName
APPLIES_TO = OA.appliesTo
USES_PROPERTY = OA.usesProperty
USES_RELATION = OA.usesRelation
CONDITION = OA.condition
STATUS = OA.status
PRIORITY = OA.priority
PLATFORM_TYPE = OA.platformType
DIALECT = OA.dialect
CAPABILITY = OA.capability
SEMANTIC_ELEMENT = OA.semanticElement
DATA_SOURCE_REF = OA.dataSource
PHYSICAL_NAMESPACE = OA.physicalNamespace
OBJECT_NAME = OA.objectName
FIELD_NAME = OA.fieldName
JOIN_PATH = OA.joinPath
ENABLED = OA.enabled
ARGUMENT = OA.argument
LEFT_PROPERTY = OA.leftProperty
VALUE = OA.value
VALUES = OA.values
PARAMETER = OA.parameter
```

- [ ] **Step 4: Implement semantic DTOs**

Use these exact public shapes in `ontology_core/semantic_models.py`:

```python
class RuleOperator(StrEnum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"
    NOT = "not"
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    BETWEEN = "between"
    IS_NULL = "is_null"


class LocalizedText(FrozenModel):
    value: str = Field(min_length=1)
    language: str | None = None


class RdfLiteral(FrozenModel):
    lexical_form: str
    datatype_uri: str | None = None
    language: str | None = None


class SemanticElement(FrozenModel):
    uri: str = Field(min_length=1)
    short_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")
    label: str = Field(min_length=1)
    labels: tuple[LocalizedText, ...]
    description: str | None = None


class Concept(SemanticElement):
    parent_uris: tuple[str, ...] = ()
    child_uris: tuple[str, ...] = ()


class Property(SemanticElement):
    concept_uri: str
    datatype_uri: str


class Relation(SemanticElement):
    source_concept_uri: str
    target_concept_uri: str


class RuleExpression(FrozenModel):
    operator: RuleOperator
    children: tuple["RuleExpression", ...] = ()
    property_uri: str | None = None
    values: tuple[RdfLiteral, ...] = ()
    parameter: str | None = None


class BusinessRule(SemanticElement):
    applies_to_uri: str
    property_uris: tuple[str, ...] = ()
    relation_uris: tuple[str, ...] = ()
    condition: RuleExpression | None = None
    status: str = "active"
    priority: int = 0


class DataSource(SemanticElement):
    platform_type: str
    dialect: str | None = None
    capabilities: tuple[str, ...] = ()


class PhysicalMapping(SemanticElement):
    semantic_element_uri: str
    data_source_uri: str
    physical_namespace: str | None = None
    object_name: str | None = None
    field_name: str | None = None
    join_path: tuple[str, ...] = ()
    priority: int = 0
    enabled: bool = True


class SemanticCatalog(FrozenModel):
    concepts: tuple[Concept, ...] = ()
    properties: tuple[Property, ...] = ()
    relations: tuple[Relation, ...] = ()
    rules: tuple[BusinessRule, ...] = ()
    data_sources: tuple[DataSource, ...] = ()
    mappings: tuple[PhysicalMapping, ...] = ()
```

- [ ] **Step 5: Add semantic errors and public exports**

Add subclasses of `OntologyError` with these codes:

```python
class ConceptNotFoundError(OntologyError):
    code = "concept_not_found"


class PropertyNotFoundError(OntologyError):
    code = "property_not_found"


class AmbiguousIdentifierError(OntologyError):
    code = "ambiguous_identifier"


class InvalidRuleExpressionError(OntologyError):
    code = "invalid_rule_expression"


class InvalidOntologyReferenceError(OntologyError):
    code = "invalid_ontology_reference"
```

Export supported classes from `ontology_core/__init__.py`; do not export vocabulary implementation helpers.

- [ ] **Step 6: Verify models, formatting, and lint**

Run:

```powershell
python -m pytest tests/ontology_core/test_models.py tests/ontology_core/test_semantic_models.py -vv
python -m ruff check ontology_core/models.py ontology_core/semantic_models.py ontology_core/vocabulary.py ontology_core/errors.py tests/ontology_core/test_semantic_models.py
python -m black --check ontology_core/models.py ontology_core/semantic_models.py ontology_core/vocabulary.py ontology_core/errors.py tests/ontology_core/test_semantic_models.py
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit the vocabulary and DTO contracts**

```powershell
git add -- ontology_core/vocabulary.py ontology_core/semantic_models.py ontology_core/errors.py ontology_core/__init__.py tests/ontology_core/test_semantic_models.py
git commit -m "feat: 定义本体语义模型契约"
```

---

### Task 3: Parse Marked Concepts, Properties, and Relations into a Catalog

**Files:**
- Create: `ontology_core/semantic_parser.py`
- Create: `tests/ontology_core/test_semantic_parser.py`
- Modify: `tests/fixtures/ontology_core/valid/core.ttl`
- Modify: `tests/fixtures/ontology_core/valid/domain.ttl`
- Modify: `tests/fixtures/ontology_core/valid/rules.ttl`
- Modify: `tests/fixtures/ontology_core/valid/mappings.ttl`
- Modify: `tests/fixtures/ontology_core/valid/shapes.ttl`

**Interfaces:**
- Consumes: `parse_catalog(graph: rdflib.Graph) -> SemanticCatalog`, vocabulary constants, and DTOs from Task 2.
- Produces: a complete neutral graph fixture and deterministic RDF parsing for `oa:Concept`, `oa:Property`, and `oa:Relation`.

- [ ] **Step 1: Replace the neutral fixture with marked semantic elements**

Use `urn:ontology-agent:core#` for `oa:` and `https://example.invalid/ontology/` for `ex:`. The valid fixture must contain exactly:

- concepts `ex:Record` and `ex:RelatedRecord`, both typed `owl:Class, oa:Concept`;
- property `ex:Metric`, typed `owl:DatatypeProperty, oa:Property`, with domain `ex:Record` and range `xsd:integer`;
- relation `ex:relatesTo`, typed `owl:ObjectProperty, oa:Relation`, from `ex:Record` to `ex:RelatedRecord`;
- one active neutral rule, one logical data source, and one enabled mapping for later parser tests;
- `oa:shortName` and `rdfs:label` on every marked semantic element;
- SHACL target classes for each `oa:` marker rather than `owl:Class` globally.

The domain declaration pattern must be:

```turtle
ex:Record a owl:Class, oa:Concept ;
    oa:shortName "Record" ;
    rdfs:label "记录"@zh-CN, "Record"@en ;
    rdfs:comment "Neutral record used only by tests." .

ex:RelatedRecord a owl:Class, oa:Concept ;
    oa:shortName "RelatedRecord" ;
    rdfs:label "Related record"@en ;
    rdfs:subClassOf ex:Record .

ex:Metric a owl:DatatypeProperty, oa:Property ;
    oa:shortName "Metric" ;
    rdfs:label "Metric"@en ;
    rdfs:domain ex:Record ;
    rdfs:range xsd:integer .

ex:relatesTo a owl:ObjectProperty, oa:Relation ;
    oa:shortName "relatesTo" ;
    rdfs:label "Relates to"@en ;
    rdfs:domain ex:Record ;
    rdfs:range ex:RelatedRecord .
```

- [ ] **Step 2: Write failing parser tests**

Cover preferred Chinese labels, language preservation, child/parent links, exact datatype URI, relation direction, stable URI sorting, missing short names, duplicate short names, missing domains, and dangling concept references. Core success assertion:

```python
def test_parse_catalog_builds_marked_domain_elements(valid_package_dir: Path) -> None:
    graph = Graph()
    for name in ("core.ttl", "domain.ttl", "rules.ttl", "mappings.ttl"):
        graph.parse(valid_package_dir / name, format="turtle")
    catalog = parse_catalog(graph)

    assert [item.short_name for item in catalog.concepts] == ["Record", "RelatedRecord"]
    record = next(item for item in catalog.concepts if item.short_name == "Record")
    related = next(item for item in catalog.concepts if item.short_name == "RelatedRecord")
    assert record.label == "记录"
    assert related.parent_uris == ("https://example.invalid/ontology/Record",)
    assert record.child_uris == ("https://example.invalid/ontology/RelatedRecord",)
```

Import `Graph` from RDFLib and `parse_catalog` from the new parser module. Call `parse_catalog(graph)` directly in this task because Repository integration belongs to Task 4.

- [ ] **Step 3: Verify the parser tests fail**

Run:

```powershell
python -m pytest tests/ontology_core/test_semantic_parser.py -vv
```

Expected: FAIL during import because `ontology_core.semantic_parser` does not exist.

- [ ] **Step 4: Implement deterministic RDF helpers**

Implement these private helpers in `semantic_parser.py`: `_uris(Graph, Identifier, URIRef) -> tuple[str, ...]`, `_single_uri(Graph, Identifier, URIRef, field: str) -> str`, `_texts(Graph, Identifier, URIRef) -> tuple[LocalizedText, ...]`, `_preferred_text(tuple[LocalizedText, ...]) -> str`, `_single_short_name(Graph, Identifier) -> str`, and `_description(Graph, Identifier) -> str | None`.

Required behavior:

- accept URI subjects only for marked semantic elements;
- sort URI strings lexicographically;
- deduplicate localized text by `(language or "", value)`;
- choose `zh` or `zh-*`, then no-language, then lexicographically first remaining label;
- collect violations instead of returning arbitrary first values;
- sort all emitted DTO tuples by `(short_name.casefold(), uri)`.

- [ ] **Step 5: Implement concept, property, and relation parsing**

Expose:

```python
def parse_catalog(graph: Graph) -> SemanticCatalog:
    """Parse marked semantic elements or raise one aggregated validation error."""
```

Parse only subjects carrying `oa:Concept`, `oa:Property`, or `oa:Relation`. Build concepts first, then validate domains and ranges against concept URIs. Compute child URIs after all parent links are known. Reject duplicate short names across every marked semantic element with `OntologyValidationError.details["violations"]` sorted by code, URI, path, and message.

- [ ] **Step 6: Verify parser tests and prior package tests**

Run:

```powershell
python -m pytest tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py tests/ontology_core/test_validator.py -vv
python -m ruff check ontology_core/semantic_parser.py tests/ontology_core/test_semantic_parser.py
python -m black --check ontology_core/semantic_parser.py tests/ontology_core/test_semantic_parser.py
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit marked semantic parsing**

```powershell
git add -- ontology_core/semantic_parser.py tests/ontology_core/test_semantic_parser.py tests/fixtures/ontology_core/valid/core.ttl tests/fixtures/ontology_core/valid/domain.ttl tests/fixtures/ontology_core/valid/rules.ttl tests/fixtures/ontology_core/valid/mappings.ttl tests/fixtures/ontology_core/valid/shapes.ttl
git commit -m "feat: 解析本体概念属性与关系"
```

---

### Task 4: Parse Rules and Mappings and Publish the Semantic Catalog Atomically

**Files:**
- Modify: `ontology_core/semantic_parser.py`
- Modify: `ontology_core/repository.py`
- Modify: `tests/ontology_core/test_semantic_parser.py`
- Modify: `tests/ontology_core/test_repository.py`

**Interfaces:**
- Consumes: Task 2 DTOs and Task 3 `parse_catalog(graph)`.
- Produces: `OntologySnapshot.info`, `OntologySnapshot.catalog`, copied RDF graphs, recursive rule parsing, and atomic rollback on semantic failure.

- [ ] **Step 1: Write failing rule, mapping, and rollback tests**

Tests must cover:

- an `AllOf` condition containing `Eq` and `IsNull` children;
- RDF literal lexical form, datatype URI, and language preservation;
- recursive condition cycle rejection;
- unknown property and relation references;
- mapping target and data-source references;
- forbidden credential predicates found on `oa:DataSource` or `oa:PhysicalMapping`;
- invalid semantic reload preserving the previous snapshot and catalog.

Repository success assertion:

```python
def test_publish_exposes_immutable_semantic_catalog(valid_package_dir: Path) -> None:
    repository = OntologyRepository()
    info = repository.publish(valid_package_dir)
    snapshot = repository.current()

    assert snapshot.info == info
    assert snapshot.catalog.concepts
    assert snapshot.catalog.rules[0].condition is not None
    assert snapshot.catalog.data_sources[0].platform_type == "generic"
```

- [ ] **Step 2: Run focused tests and verify missing behavior**

Run:

```powershell
python -m pytest tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py -vv
```

Expected: new tests FAIL because rules, mappings, and snapshot catalogs are not implemented.

- [ ] **Step 3: Implement recursive condition parsing**

Map RDF types to `RuleOperator` exactly:

```python
_OPERATOR_TYPES = {
    OA.AllOf: RuleOperator.ALL_OF,
    OA.AnyOf: RuleOperator.ANY_OF,
    OA.Not: RuleOperator.NOT,
    OA.Eq: RuleOperator.EQ,
    OA.Ne: RuleOperator.NE,
    OA.Gt: RuleOperator.GT,
    OA.Gte: RuleOperator.GTE,
    OA.Lt: RuleOperator.LT,
    OA.Lte: RuleOperator.LTE,
    OA.In: RuleOperator.IN,
    OA.Between: RuleOperator.BETWEEN,
    OA.IsNull: RuleOperator.IS_NULL,
}
```

Use a recursion stack of RDF identifiers. `AllOf` and `AnyOf` require at least two `oa:argument` nodes; `Not` requires exactly one. Comparison nodes require one `oa:leftProperty`; `IsNull` accepts no value; `Between` requires an `oa:values` RDF Collection with exactly two ordered literals; `In` requires an `oa:values` RDF Collection with at least one literal; the remaining comparison operators require exactly one `oa:value` or one `oa:parameter`. Traverse RDF Collections through `rdf:first` and `rdf:rest`, reject cycles and malformed tails, and preserve collection order in `RuleExpression.values`.

- [ ] **Step 4: Parse rules, data sources, and physical mappings**

Parse only marker-typed subjects. Resolve all referenced URIs against the complete concept/property/relation/data-source sets. Preserve mapping names as values but never interpret them as SQL. Reject predicates whose local names normalize to `host`, `port`, `username`, `password`, `token`, `secret`, or `connectionstring` on data-source and mapping subjects.

- [ ] **Step 5: Publish a public immutable snapshot with catalog**

Rename the private dataclass to the public boundary and include the catalog:

```python
@dataclass(frozen=True)
class OntologySnapshot:
    info: PackageInfo
    catalog: SemanticCatalog
    _data_nt: str
    _shapes_nt: str

    def copy_data_graph(self) -> Graph:
        return _copy_graph(self._data_nt)

    def copy_shapes_graph(self) -> Graph:
        return _copy_graph(self._shapes_nt)
```

In `OntologyRepository.publish`, call `parse_catalog(data_graph)` after SHACL succeeds but before taking the lock. Construct the complete candidate snapshot, then replace `_current` inside the lock. Change `publish` to keep returning `PackageInfo`; change `current()` to return `OntologySnapshot`.

- [ ] **Step 6: Verify semantic publication and rollback**

Run:

```powershell
python -m pytest tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py -vv
python -m ruff check ontology_core/semantic_parser.py ontology_core/repository.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py
python -m black --check ontology_core/semantic_parser.py ontology_core/repository.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py
```

Expected: all commands exit `0`; invalid semantic candidates leave the previous digest and catalog unchanged.

- [ ] **Step 7: Commit semantic catalog publication**

```powershell
git add -- ontology_core/semantic_parser.py ontology_core/repository.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_repository.py
git commit -m "feat: 原子发布本体语义目录"
```

---

### Task 5: Implement the Snapshot-Bound OntologyResolver

**Files:**
- Create: `ontology_core/resolver.py`
- Create: `tests/ontology_core/test_resolver.py`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: `OntologyResolver(snapshot: OntologySnapshot)` and `snapshot.catalog` from Task 4.
- Produces: tuple-returning read-only concept, property, relation, rule, and search methods.

- [ ] **Step 1: Write failing lookup and search tests**

Cover URI, short-name, and preferred-label lookup; ambiguous labels; missing concepts and properties; direct concept properties; outgoing relations; applicable rules; NFKC normalization; case-insensitive Latin search; deterministic rank; and snapshot isolation.

Required public assertions:

```python
repository = OntologyRepository()
repository.publish(valid_package_dir)
resolver = OntologyResolver(repository.current())
assert resolver.get_concept("Record").uri.endswith("/Record")
assert resolver.get_concept("记录").short_name == "Record"
assert tuple(item.short_name for item in resolver.list_properties("Record")) == ("Metric",)
assert tuple(item.short_name for item in resolver.list_relations("Record")) == ("relatesTo",)
assert resolver.search_concepts("rec")[0].short_name == "Record"
```

Construct and publish the repository before creating the resolver; do not instantiate a Resolver over a mutable graph.

- [ ] **Step 2: Verify tests fail because Resolver is absent**

Run:

```powershell
python -m pytest tests/ontology_core/test_resolver.py -vv
```

Expected: FAIL during import.

- [ ] **Step 3: Implement immutable indexes and normalization**

Use:

```python
def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()
```

Build private mappings from URI, normalized short name, and normalized preferred label to tuples of DTOs. Store mappings in `MappingProxyType` and values as tuples. Never mutate the catalog or snapshot.

- [ ] **Step 4: Implement the exact Resolver API**

The exact public methods are `__init__(snapshot: OntologySnapshot) -> None`, `list_concepts() -> tuple[Concept, ...]`, `get_concept(identifier: str) -> Concept`, `search_concepts(text: str) -> tuple[Concept, ...]`, `list_properties(concept_id: str) -> tuple[Property, ...]`, `resolve_property(concept_id: str, property_id: str) -> Property`, `list_relations(concept_id: str) -> tuple[Relation, ...]`, and `list_rules(concept_id: str) -> tuple[BusinessRule, ...]`.

`get_concept` checks URI, short name, then label. Zero matches raise `ConceptNotFoundError`; multiple label matches raise `AmbiguousIdentifierError` with sorted candidate URIs. `resolve_property` accepts a URI or short name only among properties returned for the resolved concept. List methods sort by normalized short name and URI.

`search_concepts` computes one best rank per concept: exact URI/short name `0`, exact label `1`, short-name prefix `2`, label contains `3`, description contains `4`. Return each concept once, sorted by rank, normalized short name, and URI. Empty normalized text returns an empty tuple.

- [ ] **Step 5: Verify Resolver behavior and determinism**

Run:

```powershell
python -m pytest tests/ontology_core/test_resolver.py -vv
python -m pytest tests/ontology_core -q
python -m ruff check ontology_core/resolver.py ontology_core/__init__.py tests/ontology_core/test_resolver.py
python -m black --check ontology_core/resolver.py ontology_core/__init__.py tests/ontology_core/test_resolver.py
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit OntologyResolver**

```powershell
git add -- ontology_core/resolver.py ontology_core/__init__.py tests/ontology_core/test_resolver.py
git commit -m "feat: 提供确定性本体解析接口"
```

---

### Task 6: Initialize Blank External Ontology Packages

**Files:**
- Create: `ontology_core/resources/core.ttl`
- Create: `ontology_core/resources/shapes.ttl`
- Create: `ontology_core/resources/__init__.py`
- Create: `ontology_core/authoring.py`
- Create: `tests/ontology_core/test_authoring.py`
- Modify: `pyproject.toml`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: `PackageManifest`, `PackageFileRole`, generic vocabulary, and generic SHACL constraints.
- Produces: `initialize_package(package_dir, package_id, base_uri, version="0.1.0") -> PackageManifest`.

- [ ] **Step 1: Write failing blank-package tests**

Tests must assert:

- all six files are created in an empty target directory;
- `manifest.yaml` is stable and contains every role;
- the generated package publishes successfully and has an empty semantic catalog;
- package ID, base URI, and version are validated;
- a non-empty target directory is rejected without changing its files;
- no generated file contains `Record`, `Example`, a physical object name, a credential predicate, or a domain instance.

Core test:

```python
manifest = initialize_package(
    tmp_path / "package",
    package_id="neutral.package",
    base_uri="https://example.invalid/private/",
)
repository = OntologyRepository()
repository.publish(tmp_path / "package")
snapshot = repository.current()
assert manifest.version == "0.1.0"
assert snapshot.catalog == SemanticCatalog()
```

- [ ] **Step 2: Verify authoring tests fail**

Run:

```powershell
python -m pytest tests/ontology_core/test_authoring.py -vv
```

Expected: FAIL during import because `initialize_package` does not exist.

- [ ] **Step 3: Add generic package resources**

`core.ttl` must declare the marker classes, rule operator classes, and predicates named in `vocabulary.py` under `urn:ontology-agent:core#`. It may contain English labels describing the generic vocabulary but no domain instances.

`shapes.ttl` must target `oa:Concept`, `oa:Property`, `oa:Relation`, `oa:BusinessRule`, `oa:DataSource`, and `oa:PhysicalMapping`. It must require one IRI focus node, one `oa:shortName`, at least one `rdfs:label`, and the type-specific required references. Credential-like predicates remain forbidden by Python semantic validation so the stable denylist has one implementation.

- [ ] **Step 4: Implement deterministic package initialization**

Expose `initialize_package(package_dir: str | Path, *, package_id: str, base_uri: str, version: str = "0.1.0") -> PackageManifest`.

Validate `package_id` and version as non-empty strings and `base_uri` as an absolute `http`, `https`, or `urn` URI. Create the target directory only if it is absent or empty. Read `core.ttl` and `shapes.ttl` with `importlib.resources.files("ontology_core.resources")`; generate empty `domain.ttl`, `rules.ttl`, and `mappings.ttl` containing only prefixes and an `owl:Ontology` declaration based on `base_uri`. Write UTF-8 with `\n` line endings and a trailing newline. Write `manifest.yaml` last so interrupted initialization is never mistaken for a complete package.

- [ ] **Step 5: Package resources and add the wheel-build test dependency**

Add:

```toml
[tool.setuptools.package-data]
ontology_core = ["resources/*.ttl"]
```

Add `"build>=1.2"` to `[project.optional-dependencies].dev`. Create an empty `ontology_core/resources/__init__.py` so `importlib.resources` resolves the resource package consistently from source and wheels.

- [ ] **Step 6: Verify initialization from source and installed package metadata**

Run:

```powershell
python -m pytest tests/ontology_core/test_authoring.py -vv
python -m build --wheel
python -c "import zipfile,glob; p=glob.glob('dist/*.whl')[-1]; z=zipfile.ZipFile(p); assert 'ontology_core/resources/core.ttl' in z.namelist(); assert 'ontology_core/resources/shapes.ttl' in z.namelist()"
python -m ruff check ontology_core/authoring.py tests/ontology_core/test_authoring.py
python -m black --check ontology_core/authoring.py tests/ontology_core/test_authoring.py
```

Expected: all commands exit `0`; `dist/` remains ignored by Git.

- [ ] **Step 7: Commit blank package authoring**

```powershell
git add -- ontology_core/resources/core.ttl ontology_core/resources/shapes.ttl ontology_core/resources/__init__.py ontology_core/authoring.py ontology_core/__init__.py tests/ontology_core/test_authoring.py pyproject.toml
git commit -m "feat: 初始化外部空白本体包"
```

---

### Task 7: Add Safe Validate and Inspect CLI Commands

**Files:**
- Create: `ontology_core/inspection.py`
- Create: `ontology_core/cli.py`
- Create: `ontology_core/__main__.py`
- Create: `tests/ontology_core/test_cli.py`
- Modify: `ontology_core/semantic_models.py`
- Modify: `ontology_core/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `initialize_package`, `OntologyRepository.publish`, `OntologyRepository.current`, and `SemanticCatalog`.
- Produces: `PackageInspection`, `inspect_package(path)`, `main(argv: Sequence[str] | None = None) -> int`, and commands `init`, `validate`, `inspect`.

- [ ] **Step 1: Write failing inspection and CLI contract tests**

Use `capsys` and temporary directories. Cover:

- `init` success and refusal to overwrite;
- `validate` text and JSON success;
- malformed package JSON error with stable `code`, `message`, and `details`;
- `inspect` default counts without element identifiers;
- `inspect --list-identifiers` with stable sorted URIs;
- no source path in successful JSON inspection;
- exit `0` for success, `1` for ontology/domain errors, and argparse exit `2` for invalid arguments.

JSON success shape:

```json
{
  "status": "valid",
  "package": {
    "package_id": "example.neutral",
    "version": "1.0.0",
    "sha256": "<64 lowercase hex characters>"
  },
  "counts": {
    "concepts": 2,
    "properties": 1,
    "relations": 1,
    "rules": 1,
    "data_sources": 1,
    "mappings": 1
  }
}
```

- [ ] **Step 2: Verify CLI tests fail**

Run:

```powershell
python -m pytest tests/ontology_core/test_cli.py -vv
```

Expected: FAIL during import because inspection and CLI modules do not exist.

- [ ] **Step 3: Add the inspection DTO and service**

Add frozen DTOs with fields matching the JSON contract:

```python
class SemanticCounts(FrozenModel):
    concepts: int = 0
    properties: int = 0
    relations: int = 0
    rules: int = 0
    data_sources: int = 0
    mappings: int = 0


class InspectedPackage(FrozenModel):
    package_id: str
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PackageInspection(FrozenModel):
    status: Literal["valid"] = "valid"
    package: InspectedPackage
    counts: SemanticCounts
    identifiers: tuple[str, ...] | None = None
```

`inspect_package(path, *, list_identifiers=False)` publishes through a fresh repository, reads the snapshot, constructs `InspectedPackage` from package ID, version, and digest only, and includes identifiers only when requested. The inspection DTO therefore cannot serialize source paths or load timestamps by accident.

- [ ] **Step 4: Implement a testable standard-library CLI**

Implement:

```python
def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except OntologyError as exc:
        _write_error(exc, as_json=getattr(args, "json", False))
        return 1
```

Handlers call only `initialize_package`, a fresh `OntologyRepository`, or `inspect_package`. Text errors go to stderr. JSON uses `json.dumps(payload, ensure_ascii=False, sort_keys=True)` and contains no traceback. `ontology_core/__main__.py` must contain:

```python
from ontology_core.cli import main

raise SystemExit(main())
```

Add the console alias only after `ontology_core.cli` exists:

```toml
[project.scripts]
ontology-core = "ontology_core.cli:main"
```

- [ ] **Step 5: Verify source and module entry points**

Run:

```powershell
python -m pytest tests/ontology_core/test_cli.py -vv
python -m ontology_core --help
python -m ontology_core validate tests/fixtures/ontology_core/valid --json
python -m ontology_core inspect tests/fixtures/ontology_core/valid --json
python -m ruff check ontology_core/inspection.py ontology_core/cli.py ontology_core/__main__.py tests/ontology_core/test_cli.py
python -m black --check ontology_core/inspection.py ontology_core/cli.py ontology_core/__main__.py tests/ontology_core/test_cli.py
```

Expected: tests and checks exit `0`; both JSON commands emit one parseable JSON object.

- [ ] **Step 6: Commit CLI and inspection**

```powershell
git add -- ontology_core/inspection.py ontology_core/cli.py ontology_core/__main__.py ontology_core/semantic_models.py ontology_core/__init__.py tests/ontology_core/test_cli.py pyproject.toml
git commit -m "feat: 提供本体校验与检查命令"
```

---

### Task 8: Document Protégé Authoring and Record Engineering Evidence

**Files:**
- Create: `docs/ontology-authoring.md`
- Modify: `README.md`
- Modify: `docs/project-journal/2026-08.md`
- Modify: `docs/career/project-story.md`

**Interfaces:**
- Consumes: the exact commands and RDF markers implemented in Tasks 2–7.
- Produces: user-facing editing instructions and evidence-backed project/career records.

- [ ] **Step 1: Write the authoring guide**

Document these exact sections:

1. prerequisites and installing/opening Protégé;
2. creating an external private package with `python -m ontology_core init`;
3. opening `domain.ttl` and preserving module files;
4. creating a concept with both `owl:Class` and `oa:Concept` types;
5. creating data properties and object relations with marker types, domains, and ranges;
6. creating rules, data sources, and mappings as individuals;
7. stable URI, short-name, language-label, and version rules;
8. local `validate` and `inspect` commands;
9. Git review and deployment workflow;
10. prohibited credentials, SQL fragments, real data, and application-repository storage.

Use only neutral RDF fragments under `https://example.invalid/` and explicitly label them as documentation examples, not production defaults.

- [ ] **Step 2: Update README without claiming Agent integration**

Add a short “本体包开发” section linking to `docs/ontology-authoring.md` and showing only:

```powershell
python -m ontology_core init D:\path\to\private-package --package-id private.package --base-uri https://example.invalid/private/
python -m ontology_core validate D:\path\to\private-package
python -m ontology_core inspect D:\path\to\private-package
```

State that the new Resolver is a Python boundary and the existing Agent remains on the legacy path in this milestone.

- [ ] **Step 3: Update journal and career material from actual evidence**

Record:

- the historical seed-dependent test root cause and isolated-test solution;
- the marker-type decision separating OWL meta-vocabulary from domain elements;
- deterministic Unicode label selection and search ranking;
- atomic catalog publication and rollback behavior;
- CLI and wheel-resource verification results;
- exact scoped and full test counts observed during execution.

Career material must separate delivered capabilities from the planned MappingRegistry, QueryPlan, Agent integration, REST, and frontend work.

- [ ] **Step 4: Verify documentation paths, commands, and sensitive patterns**

Run:

```powershell
rg -n "python -m ontology_core|oa:Concept|Protégé|现有 Agent" README.md docs/ontology-authoring.md docs/project-journal/2026-08.md docs/career/project-story.md
rg -n "D_[A-Z0-9_]+|CALL_[A-Z0-9_]+|GPRS_[A-Z0-9_]+|SUBS_[A-Z0-9_]+" ontology_core tests/ontology_core docs/ontology-authoring.md
git diff --check
```

Expected: the first command finds the documented workflow; the sensitive-pattern scan has no matches in the new core, focused tests, or authoring guide; diff check exits `0`.

- [ ] **Step 5: Commit documentation and evidence**

```powershell
git add -- docs/ontology-authoring.md README.md docs/project-journal/2026-08.md docs/career/project-story.md
git commit -m "docs: 记录本体编辑与解析工作流"
```

---

### Task 9: Final Verification and Independent Review

**Files:**
- Modify only files required by verified review findings.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: a clean, reviewed feature branch with reproducible verification evidence.

- [ ] **Step 1: Run focused ontology tests**

```powershell
python -m pytest tests/ontology_core -v
```

Expected: all focused tests PASS.

- [ ] **Step 2: Run the complete project suite**

```powershell
python -m pytest -q
```

Expected: exit `0`, no failures. Do not mark the milestone complete if any test fails.

- [ ] **Step 3: Run scoped quality checks**

```powershell
python -m ruff check ontology_core tests/ontology_core tests/test_ontology_relations.py
python -m black --check ontology_core tests/ontology_core tests/test_ontology_relations.py
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 4: Verify CLI, build artifact, and data constraints**

```powershell
python -m ontology_core validate tests/fixtures/ontology_core/valid --json
python -m ontology_core inspect tests/fixtures/ontology_core/valid --json --list-identifiers
python -m build --wheel
python -c "import zipfile,glob; p=glob.glob('dist/*.whl')[-1]; z=zipfile.ZipFile(p); assert 'ontology_core/resources/core.ttl' in z.namelist(); assert 'ontology_core/resources/shapes.ttl' in z.namelist()"
rg -n "D_[A-Z0-9_]+|CALL_[A-Z0-9_]+|GPRS_[A-Z0-9_]+|SUBS_[A-Z0-9_]+" ontology_core tests/ontology_core docs/ontology-authoring.md
```

Expected: validation, inspection, and wheel checks exit `0`; sensitive-pattern scan has no output.

- [ ] **Step 5: Request independent specification and code-quality reviews**

Use `superpowers:requesting-code-review`. Review against:

- `docs/superpowers/specs/2026-08-23-ontology-authoring-resolver-design.md`;
- this implementation plan;
- the complete branch diff from `6f817d0` through current HEAD.

Require reviewers to classify findings as Critical, Important, or Minor and provide file/line evidence. Address Critical and Important findings with focused tests and separate commits. Evaluate Minor findings explicitly and record deferred ones.

- [ ] **Step 6: Re-run verification after review fixes**

Repeat Steps 1–4 after the final review fix. Update journal and career counts only if outputs changed, then commit those evidence corrections with explicit paths.

- [ ] **Step 7: Confirm clean Git state and report branch status**

```powershell
git status --short --branch
git log --oneline --decorate -15
```

Expected: clean `codex/ontology-package-core` worktree. Report commits, tests, known global lint debt, and the fact that no merge or push occurred.
