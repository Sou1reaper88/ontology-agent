from __future__ import annotations

from pathlib import Path

import pytest

from ontology_core.errors import (
    AmbiguousIdentifierError,
    ConceptNotFoundError,
    PropertyNotFoundError,
)
from ontology_core.repository import OntologyRepository
from ontology_core.resolver import OntologyResolver


def _resolver(valid_package_dir: Path) -> OntologyResolver:
    repository = OntologyRepository()
    repository.publish(valid_package_dir)
    return OntologyResolver(repository.current())


def _copy_package(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir()
    for source in source_dir.iterdir():
        target_dir.joinpath(source.name).write_bytes(source.read_bytes())


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
