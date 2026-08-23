from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import get_type_hints

import pytest
from rdflib import Graph

from ontology_core.errors import (
    AmbiguousIdentifierError,
    ConceptNotFoundError,
    PropertyNotFoundError,
)
from ontology_core.models import PackageInfo
from ontology_core.repository import OntologyRepository, OntologySnapshot
from ontology_core.resolver import OntologyResolver
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    LocalizedText,
    Property,
    Relation,
    SemanticCatalog,
)


def _resolver(valid_package_dir: Path) -> OntologyResolver:
    repository = OntologyRepository()
    repository.publish(valid_package_dir)
    return OntologyResolver(repository.current())


def _copy_package(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir()
    for source in source_dir.iterdir():
        target_dir.joinpath(source.name).write_bytes(source.read_bytes())


def _concept(
    short_name: str,
    *,
    uri: str | None = None,
    label: str | None = None,
    description: str | None = None,
    parent_uris: tuple[str, ...] = (),
) -> Concept:
    display_name = label or short_name
    return Concept(
        uri=uri or f"https://example.invalid/ontology/{short_name}",
        short_name=short_name,
        label=display_name,
        labels=(LocalizedText(value=display_name, language="en"),),
        description=description,
        parent_uris=parent_uris,
    )


def _catalog_resolver(
    *,
    concepts: tuple[Concept, ...],
    properties: tuple[Property, ...] = (),
    relations: tuple[Relation, ...] = (),
    rules: tuple[BusinessRule, ...] = (),
) -> OntologyResolver:
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.resolver",
            version="1.0.0",
            sha256="0" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/packages/resolver",
        ),
        catalog=SemanticCatalog(
            concepts=concepts,
            properties=properties,
            relations=relations,
            rules=rules,
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def test_resolver_looks_up_concepts_by_uri_short_name_and_preferred_label(
    valid_package_dir: Path,
) -> None:
    resolver = _resolver(valid_package_dir)

    assert resolver.get_concept("https://example.invalid/ontology/Record").short_name == "Record"
    assert resolver.get_concept("Record").uri.endswith("/Record")
    assert resolver.get_concept("记录").short_name == "Record"


def test_resolver_rejects_missing_and_ambiguous_concept_identifiers(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "ambiguous-package"
    _copy_package(valid_package_dir, package_dir)
    domain_path = package_dir / "domain.ttl"
    domain_path.write_text(
        domain_path.read_text(encoding="utf-8") + """
ex:DuplicateRecord a owl:Class, oa:Concept ;
    oa:shortName "DuplicateRecord" ;
    rdfs:label "记录"@zh-CN .
""",
        encoding="utf-8",
    )
    resolver = _resolver(package_dir)

    with pytest.raises(ConceptNotFoundError) as missing:
        resolver.get_concept("unknown")
    with pytest.raises(AmbiguousIdentifierError) as ambiguous:
        resolver.get_concept("记录")

    assert missing.value.code == "concept_not_found"
    assert ambiguous.value.details["candidates"] == [
        "https://example.invalid/ontology/DuplicateRecord",
        "https://example.invalid/ontology/Record",
    ]


def test_resolver_lists_concept_members_and_resolves_properties(
    valid_package_dir: Path,
) -> None:
    resolver = _resolver(valid_package_dir)

    assert tuple(item.short_name for item in resolver.list_properties("Record")) == ("Metric",)
    assert tuple(item.short_name for item in resolver.list_relations("Record")) == ("relatesTo",)
    assert tuple(item.short_name for item in resolver.list_rules("Record")) == ("RecordRule",)
    assert resolver.resolve_property("记录", "Metric").uri.endswith("/Metric")
    assert (
        resolver.resolve_property(
            "https://example.invalid/ontology/Record",
            "https://example.invalid/ontology/Metric",
        ).short_name
        == "Metric"
    )

    with pytest.raises(PropertyNotFoundError) as missing:
        resolver.resolve_property("RelatedRecord", "Metric")

    assert missing.value.code == "property_not_found"


def test_resolver_normalizes_identifiers_and_returns_deterministic_search_ranks(
    valid_package_dir: Path,
) -> None:
    resolver = _resolver(valid_package_dir)

    assert resolver.get_concept("  ＲＥＣＯＲＤ  ").short_name == "Record"
    assert resolver.get_concept("　记录　").short_name == "Record"
    assert tuple(item.short_name for item in resolver.search_concepts("rec")) == (
        "Record",
        "RelatedRecord",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("neutral")) == ("Record",)
    assert resolver.search_concepts("   ") == ()


def test_resolver_uses_an_immutable_snapshot_catalog_after_repository_republish(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    repository = OntologyRepository()
    repository.publish(valid_package_dir)
    resolver = OntologyResolver(repository.current())
    package_dir = tmp_path / "updated-package"
    _copy_package(valid_package_dir, package_dir)
    domain_path = package_dir / "domain.ttl"
    domain_path.write_text(
        domain_path.read_text(encoding="utf-8").replace(
            'oa:shortName "Record"', 'oa:shortName "UpdatedRecord"'
        ),
        encoding="utf-8",
    )
    repository.publish(package_dir)

    assert resolver.get_concept("Record").short_name == "Record"
    assert (
        OntologyResolver(repository.current()).get_concept("UpdatedRecord").uri.endswith("/Record")
    )


def test_search_concepts_uses_each_rank_once_and_sorts_same_rank_deterministically() -> None:
    resolver = _catalog_resolver(
        concepts=(
            _concept(
                "UriShort",
                uri="https://example.invalid/ontology/ExactUri",
                label="URI label",
            ),
            _concept("ExactShort", label="Short label"),
            _concept("LabelShort", label="Exact label"),
            _concept(
                "prefixZulu",
                uri="https://example.invalid/ontology/AlphaUri",
                label="Zulu prefix",
            ),
            _concept(
                "PrefixAlpha",
                uri="https://example.invalid/ontology/ZuluUri",
                label="Alpha prefix",
            ),
            _concept("Zed", label="Contains zeta"),
            _concept("Alpha", label="Zeta mention"),
            _concept("DescribeZ", description="details for Z"),
            _concept("describeA", description="details for A"),
            _concept(
                "MultiMatch",
                label="Multi match label",
                description="multi match source",
            ),
        )
    )

    assert tuple(
        item.short_name
        for item in resolver.search_concepts("https://example.invalid/ontology/ExactUri")
    ) == ("UriShort",)
    assert tuple(item.short_name for item in resolver.search_concepts("ExactShort")) == (
        "ExactShort",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("Exact label")) == (
        "LabelShort",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("prefix")) == (
        "PrefixAlpha",
        "prefixZulu",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("zeta")) == (
        "Alpha",
        "Zed",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("details")) == (
        "describeA",
        "DescribeZ",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("multimatch")) == (
        "MultiMatch",
    )
    assert tuple(item.short_name for item in resolver.search_concepts("multi")) == ("MultiMatch",)


def test_resolver_scopes_properties_relations_and_rules_without_inheritance() -> None:
    parent = _concept("Parent")
    child = _concept("Child")
    target = _concept("Target")
    parent_property = Property(
        uri="https://example.invalid/ontology/ParentMetric",
        short_name="ParentMetric",
        label="Parent display metric",
        labels=(LocalizedText(value="Parent display metric", language="en"),),
        concept_uri=parent.uri,
        datatype_uri="https://example.invalid/datatype/Number",
    )
    child_property = Property(
        uri="https://example.invalid/ontology/ChildMetric",
        short_name="ChildMetric",
        label="Child display metric",
        labels=(LocalizedText(value="Child display metric", language="en"),),
        concept_uri=child.uri,
        datatype_uri="https://example.invalid/datatype/Number",
    )
    parent_rule = BusinessRule(
        uri="https://example.invalid/ontology/ParentRule",
        short_name="ParentRule",
        label="Parent rule",
        labels=(LocalizedText(value="Parent rule", language="en"),),
        applies_to_uri=parent.uri,
    )
    child_rule = BusinessRule(
        uri="https://example.invalid/ontology/ChildRule",
        short_name="ChildRule",
        label="Child rule",
        labels=(LocalizedText(value="Child rule", language="en"),),
        applies_to_uri=child.uri,
    )
    resolver = _catalog_resolver(
        concepts=(parent, child, target),
        properties=(parent_property, child_property),
        relations=(
            Relation(
                uri="https://example.invalid/ontology/ParentToTarget",
                short_name="ParentToTarget",
                label="Parent to target",
                labels=(LocalizedText(value="Parent to target", language="en"),),
                source_concept_uri=parent.uri,
                target_concept_uri=target.uri,
            ),
            Relation(
                uri="https://example.invalid/ontology/ChildToParent",
                short_name="ChildToParent",
                label="Child to parent",
                labels=(LocalizedText(value="Child to parent", language="en"),),
                source_concept_uri=child.uri,
                target_concept_uri=parent.uri,
            ),
            Relation(
                uri="https://example.invalid/ontology/ChildToTarget",
                short_name="ChildToTarget",
                label="Child to target",
                labels=(LocalizedText(value="Child to target", language="en"),),
                source_concept_uri=child.uri,
                target_concept_uri=target.uri,
            ),
        ),
        rules=(parent_rule, child_rule),
    )

    assert tuple(item.short_name for item in resolver.list_properties("Parent")) == (
        "ParentMetric",
    )
    assert resolver.resolve_property("Parent", "ParentMetric") == parent_property
    assert tuple(item.short_name for item in resolver.list_relations("Parent")) == (
        "ParentToTarget",
    )
    assert tuple(item.short_name for item in resolver.list_relations("Child")) == (
        "ChildToParent",
        "ChildToTarget",
    )
    assert tuple(item.short_name for item in resolver.list_rules("Parent")) == ("ParentRule",)
    assert tuple(item.short_name for item in resolver.list_rules("Child")) == ("ChildRule",)

    with pytest.raises(PropertyNotFoundError):
        resolver.resolve_property("Parent", "Parent display metric")
    with pytest.raises(PropertyNotFoundError):
        resolver.resolve_property("Parent", "ChildMetric")


def test_resolver_exposes_only_documented_methods_and_read_only_tuple_indexes(
    valid_package_dir: Path,
) -> None:
    resolver = _resolver(valid_package_dir)
    expected_parameters = {
        "__init__": ("self", "snapshot"),
        "list_concepts": ("self",),
        "get_concept": ("self", "identifier"),
        "search_concepts": ("self", "text"),
        "list_properties": ("self", "concept_id"),
        "resolve_property": ("self", "concept_id", "property_id"),
        "list_relations": ("self", "concept_id"),
        "list_rules": ("self", "concept_id"),
    }
    public_methods = {
        name: method
        for name, method in inspect.getmembers(OntologyResolver, inspect.isfunction)
        if not name.startswith("_") or name == "__init__"
    }

    assert set(public_methods) == set(expected_parameters)
    assert {
        name: tuple(inspect.signature(method).parameters) for name, method in public_methods.items()
    } == expected_parameters
    assert {name: get_type_hints(method) for name, method in public_methods.items()} == {
        "__init__": {"snapshot": OntologySnapshot, "return": type(None)},
        "list_concepts": {"return": tuple[Concept, ...]},
        "get_concept": {"identifier": str, "return": Concept},
        "search_concepts": {"text": str, "return": tuple[Concept, ...]},
        "list_properties": {"concept_id": str, "return": tuple[Property, ...]},
        "resolve_property": {
            "concept_id": str,
            "property_id": str,
            "return": Property,
        },
        "list_relations": {"concept_id": str, "return": tuple[Relation, ...]},
        "list_rules": {"concept_id": str, "return": tuple[BusinessRule, ...]},
    }
    assert isinstance(resolver.list_concepts(), tuple)
    assert isinstance(resolver.search_concepts("record"), tuple)
    assert isinstance(resolver.list_properties("Record"), tuple)
    assert isinstance(resolver.list_relations("Record"), tuple)
    assert isinstance(resolver.list_rules("Record"), tuple)

    indexes = (
        resolver._concepts_by_uri,
        resolver._concepts_by_short_name,
        resolver._concepts_by_label,
        resolver._properties_by_concept,
        resolver._relations_by_source,
        resolver._rules_by_concept,
    )
    assert all(isinstance(index, MappingProxyType) for index in indexes)
    assert all(isinstance(value, tuple) for index in indexes for value in index.values())
    assert not isinstance(resolver, Graph)
    assert not any(isinstance(value, Graph) for value in vars(resolver).values())


def test_search_concepts_prefers_rank_over_alphabetical_order_with_competing_matches() -> None:
    query = "rank"
    resolver = _catalog_resolver(
        concepts=(
            _concept("Rank", label="Zero"),
            _concept("AlphaExactLabel", label=query),
            _concept("RankPrefix", label="Prefix"),
            _concept("AlphaContainsLabel", label="contains rank"),
            _concept("AardvarkDescription", label="Description", description="rank narrative"),
        )
    )

    assert tuple(item.short_name for item in resolver.search_concepts(query)) == (
        "Rank",
        "AlphaExactLabel",
        "RankPrefix",
        "AlphaContainsLabel",
        "AardvarkDescription",
    )


def test_search_concepts_prefers_exact_uri_over_exact_label_competitor() -> None:
    query = "https://example.invalid/ontology/RankUri"
    resolver = _catalog_resolver(
        concepts=(
            _concept("ZuluUriWinner", uri=query, label="URI winner"),
            _concept("AlphaLabelCompetitor", label=query),
        )
    )

    assert tuple(item.short_name for item in resolver.search_concepts(query)) == (
        "ZuluUriWinner",
        "AlphaLabelCompetitor",
    )


def test_get_concept_prefers_uri_then_short_name_over_label() -> None:
    uri_identifier = "https://example.invalid/ontology/SharedUri"
    resolver = _catalog_resolver(
        concepts=(
            _concept("UriWinner", uri=uri_identifier, label="URI winner"),
            _concept("UriLabelCompetitor", label=uri_identifier),
            _concept("SharedName", label="Short-name winner"),
            _concept("LabelCompetitor", label="SharedName"),
        )
    )

    assert resolver.get_concept(uri_identifier).short_name == "UriWinner"
    assert resolver.get_concept("SharedName").short_name == "SharedName"


def test_child_does_not_inherit_parent_relations_or_rules_and_excludes_incoming() -> None:
    parent = _concept("Parent")
    child = _concept("Child", parent_uris=(parent.uri,))
    target = _concept("Target")
    parent_relation = Relation(
        uri="https://example.invalid/ontology/ParentToTarget",
        short_name="ParentToTarget",
        label="Parent to target",
        labels=(LocalizedText(value="Parent to target", language="en"),),
        source_concept_uri=parent.uri,
        target_concept_uri=target.uri,
    )
    incoming_relation = Relation(
        uri="https://example.invalid/ontology/TargetToParent",
        short_name="TargetToParent",
        label="Target to parent",
        labels=(LocalizedText(value="Target to parent", language="en"),),
        source_concept_uri=target.uri,
        target_concept_uri=parent.uri,
    )
    parent_rule = BusinessRule(
        uri="https://example.invalid/ontology/ParentRule",
        short_name="ParentRule",
        label="Parent rule",
        labels=(LocalizedText(value="Parent rule", language="en"),),
        applies_to_uri=parent.uri,
    )
    resolver = _catalog_resolver(
        concepts=(child, target, parent),
        relations=(incoming_relation, parent_relation),
        rules=(parent_rule,),
    )

    assert child.parent_uris == (parent.uri,)
    assert tuple(item.short_name for item in resolver.list_relations("Parent")) == (
        "ParentToTarget",
    )
    assert resolver.list_relations("Child") == ()
    assert tuple(item.short_name for item in resolver.list_rules("Parent")) == ("ParentRule",)
    assert resolver.list_rules("Child") == ()


def test_list_methods_sort_unordered_catalog_members_by_normalized_short_name_and_uri() -> None:
    owner = _concept("Owner")
    alpha_upper = _concept(
        "Alpha",
        uri="https://example.invalid/ontology/ZuluAlpha",
    )
    alpha_lower = _concept(
        "alpha",
        uri="https://example.invalid/ontology/AlphaAlpha",
    )
    zeta = _concept("Zeta")
    resolver = _catalog_resolver(
        concepts=(zeta, owner, alpha_upper, alpha_lower),
        properties=(
            Property(
                uri="https://example.invalid/ontology/ZuluAttribute",
                short_name="AlphaAttribute",
                label="Upper attribute",
                labels=(LocalizedText(value="Upper attribute", language="en"),),
                concept_uri=owner.uri,
                datatype_uri="https://example.invalid/datatype/Number",
            ),
            Property(
                uri="https://example.invalid/ontology/AlphaAttribute",
                short_name="alphaAttribute",
                label="Lower attribute",
                labels=(LocalizedText(value="Lower attribute", language="en"),),
                concept_uri=owner.uri,
                datatype_uri="https://example.invalid/datatype/Number",
            ),
            Property(
                uri="https://example.invalid/ontology/ZetaAttribute",
                short_name="ZetaAttribute",
                label="Zeta attribute",
                labels=(LocalizedText(value="Zeta attribute", language="en"),),
                concept_uri=owner.uri,
                datatype_uri="https://example.invalid/datatype/Number",
            ),
        ),
        relations=(
            Relation(
                uri="https://example.invalid/ontology/ZuluRelation",
                short_name="AlphaRelation",
                label="Upper relation",
                labels=(LocalizedText(value="Upper relation", language="en"),),
                source_concept_uri=owner.uri,
                target_concept_uri=zeta.uri,
            ),
            Relation(
                uri="https://example.invalid/ontology/AlphaRelation",
                short_name="alphaRelation",
                label="Lower relation",
                labels=(LocalizedText(value="Lower relation", language="en"),),
                source_concept_uri=owner.uri,
                target_concept_uri=zeta.uri,
            ),
            Relation(
                uri="https://example.invalid/ontology/ZetaRelation",
                short_name="ZetaRelation",
                label="Zeta relation",
                labels=(LocalizedText(value="Zeta relation", language="en"),),
                source_concept_uri=owner.uri,
                target_concept_uri=zeta.uri,
            ),
        ),
        rules=(
            BusinessRule(
                uri="https://example.invalid/ontology/ZuluRule",
                short_name="AlphaRule",
                label="Upper rule",
                labels=(LocalizedText(value="Upper rule", language="en"),),
                applies_to_uri=owner.uri,
            ),
            BusinessRule(
                uri="https://example.invalid/ontology/AlphaRule",
                short_name="alphaRule",
                label="Lower rule",
                labels=(LocalizedText(value="Lower rule", language="en"),),
                applies_to_uri=owner.uri,
            ),
            BusinessRule(
                uri="https://example.invalid/ontology/ZetaRule",
                short_name="ZetaRule",
                label="Zeta rule",
                labels=(LocalizedText(value="Zeta rule", language="en"),),
                applies_to_uri=owner.uri,
            ),
        ),
    )

    assert isinstance(resolver.list_concepts(), tuple)
    assert tuple(item.short_name for item in resolver.list_concepts()) == (
        "alpha",
        "Alpha",
        "Owner",
        "Zeta",
    )
    assert isinstance(resolver.list_properties("Owner"), tuple)
    assert tuple(item.short_name for item in resolver.list_properties("Owner")) == (
        "alphaAttribute",
        "AlphaAttribute",
        "ZetaAttribute",
    )
    assert isinstance(resolver.list_relations("Owner"), tuple)
    assert tuple(item.short_name for item in resolver.list_relations("Owner")) == (
        "alphaRelation",
        "AlphaRelation",
        "ZetaRelation",
    )
    assert isinstance(resolver.list_rules("Owner"), tuple)
    assert tuple(item.short_name for item in resolver.list_rules("Owner")) == (
        "alphaRule",
        "AlphaRule",
        "ZetaRule",
    )
