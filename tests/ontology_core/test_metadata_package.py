from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Literal
from rdflib.namespace import RDFS

from ontology_core.errors import OntologyImportError, OntologyValidationError
from ontology_core.inspection import inspect_package
from ontology_core.metadata_package import (
    PackageGenerationOptions,
    generate_metadata_package,
)
from ontology_core.repository import OntologyRepository
from ontology_core.resolver import OntologyResolver
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain
from ontology_core.tabular_metadata import (
    MetadataOverrides,
    TemporalPolicyOverride,
    apply_metadata_overrides,
    parse_tabular_metadata,
)

SYNTHETIC_TSV = (
    "对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述\n"
    "DEMO_ENTITY_M\t演示实体月表\t用于集成测试的合成实体\tENTITY_ID\t实体编码\tstring\t稳定编码\n"
    "DEMO_ENTITY_M\t\t\tTOTAL_VALUE\t累计值\tdecimal\t用于测试的累计数值\n"
)


def _options() -> PackageGenerationOptions:
    return PackageGenerationOptions(
        package_id="tests.metadata-demo",
        base_uri="https://example.invalid/tests/metadata-demo/",
        version="1.0.0",
        physical_namespace="demo_warehouse",
        platform_type="synthetic",
        dialect="generic",
    )


def test_generate_metadata_package_builds_publishable_semantics(tmp_path: Path) -> None:
    target = tmp_path / "package"

    result = generate_metadata_package(
        parse_tabular_metadata(SYNTHETIC_TSV),
        target,
        _options(),
    )

    assert result.target == target
    assert result.inspection.package.package_id == "tests.metadata-demo"
    assert result.inspection.counts.model_dump() == {
        "concepts": 1,
        "properties": 2,
        "relations": 0,
        "rules": 0,
        "data_sources": 1,
        "mappings": 3,
        "temporal_policies": 0,
    }

    repository = OntologyRepository()
    repository.publish(target)
    resolver = OntologyResolver(repository.current())
    concept = resolver.get_concept("DEMO_ENTITY_M")
    assert concept.label == "演示实体月表"
    assert concept.description == "用于集成测试的合成实体"

    properties = resolver.list_properties(concept.uri)
    assert [item.short_name for item in properties] == ["ENTITY_ID", "TOTAL_VALUE"]
    assert properties[0].description == "稳定编码"
    assert properties[1].datatype_uri == "http://www.w3.org/2001/XMLSchema#decimal"

    source = resolver.list_data_sources()[0]
    assert source.platform_type == "synthetic"
    assert source.dialect == "generic"
    object_mapping = resolver.list_mappings(concept.uri, source.uri)[0]
    assert object_mapping.physical_namespace == "demo_warehouse"
    assert object_mapping.object_name == "DEMO_ENTITY_M"
    field_mappings = {
        property_.short_name: resolver.list_mappings(property_.uri, source.uri)[0].field_name
        for property_ in properties
    }
    assert field_mappings == {"ENTITY_ID": "ENTITY_ID", "TOTAL_VALUE": "TOTAL_VALUE"}


def test_generate_metadata_package_publishes_confirmed_temporal_policy(
    tmp_path: Path,
) -> None:
    draft = parse_tabular_metadata(
        SYNTHETIC_TSV.replace("TOTAL_VALUE\t累计值\tdecimal", "ACCOUNTING_MONTH\t账期\tstring")
    )
    draft = apply_metadata_overrides(
        draft,
        MetadataOverrides(
            temporal_policy=TemporalPolicyOverride(
                field="ACCOUNTING_MONTH",
                grain=TemporalGrain.MONTH,
                default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
            )
        ),
    )
    target = tmp_path / "package"

    result = generate_metadata_package(draft, target, _options())

    assert result.inspection.counts.temporal_policies == 1
    repository = OntologyRepository()
    repository.publish(target)
    resolver = OntologyResolver(repository.current())
    concept = resolver.get_concept("DEMO_ENTITY_M")
    policy = resolver.get_temporal_policy(concept.uri)
    assert policy is not None
    assert policy.partition_property_uri.endswith("/property/ACCOUNTING_MONTH")


def test_generate_metadata_package_serializes_untrusted_text_as_literals(tmp_path: Path) -> None:
    malicious_label = '演示" ; oa:password "secret'
    draft = parse_tabular_metadata(
        "对象英文名称\t对象中文名称\t属性英文名\t属性中文名\t属性类型\t属性描述\n"
        f"SAFE_TABLE\t{malicious_label}\tSAFE_FIELD\t安全字段\tstring\t安全说明\n"
    )
    target = tmp_path / "package"

    generate_metadata_package(draft, target, _options())

    repository = OntologyRepository()
    repository.publish(target)
    graph = repository.current().copy_data_graph()
    assert Literal(malicious_label, lang="zh-CN") in set(graph.objects(None, RDFS.label))
    assert not any(
        str(predicate).casefold().endswith("password") for predicate in graph.predicates()
    )


def test_generate_metadata_package_does_not_write_target_for_blocking_diagnostics(
    tmp_path: Path,
) -> None:
    draft = parse_tabular_metadata(
        "对象英文名称\t属性英文名\t属性中文名\n" "SAFE_TABLE\tBAD-NAME\t非法字段\n"
    )
    target = tmp_path / "package"

    with pytest.raises(OntologyImportError, match="阻断问题"):
        generate_metadata_package(draft, target, _options())

    assert not target.exists()
    assert not tuple(tmp_path.glob(".*.import-staging-*"))


def test_generate_metadata_package_refuses_existing_target_without_replace(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    generate_metadata_package(parse_tabular_metadata(SYNTHETIC_TSV), target, _options())
    original_sha = inspect_package(target).package.sha256

    with pytest.raises(OntologyImportError, match="目标本体包已存在"):
        generate_metadata_package(parse_tabular_metadata(SYNTHETIC_TSV), target, _options())

    assert inspect_package(target).package.sha256 == original_sha


def test_generate_metadata_package_preserves_existing_target_when_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "package"
    generate_metadata_package(parse_tabular_metadata(SYNTHETIC_TSV), target, _options())
    original_sha = inspect_package(target).package.sha256
    original_publish = OntologyRepository.publish

    def fail_staging(self: OntologyRepository, package_dir: str | Path):
        if ".import-staging-" in Path(package_dir).name:
            raise OntologyValidationError("synthetic validation failure")
        return original_publish(self, package_dir)

    monkeypatch.setattr(OntologyRepository, "publish", fail_staging)

    with pytest.raises(OntologyValidationError, match="synthetic validation failure"):
        generate_metadata_package(
            parse_tabular_metadata(SYNTHETIC_TSV),
            target,
            _options(),
            replace=True,
        )

    assert inspect_package(target).package.sha256 == original_sha
    assert not tuple(tmp_path.glob(".*.import-staging-*"))
    assert not tuple(tmp_path.glob(".*.import-backup-*"))


def test_generate_metadata_package_replaces_existing_target_after_validation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "package"
    generate_metadata_package(parse_tabular_metadata(SYNTHETIC_TSV), target, _options())
    replacement_tsv = SYNTHETIC_TSV.replace("TOTAL_VALUE", "CURRENT_VALUE").replace(
        "累计值", "当前值"
    )
    replacement_options = _options().model_copy(update={"version": "1.1.0"})

    result = generate_metadata_package(
        parse_tabular_metadata(replacement_tsv),
        target,
        replacement_options,
        replace=True,
    )

    assert result.inspection.package.version == "1.1.0"
    repository = OntologyRepository()
    repository.publish(target)
    resolver = OntologyResolver(repository.current())
    concept = resolver.get_concept("DEMO_ENTITY_M")
    assert [item.short_name for item in resolver.list_properties(concept.uri)] == [
        "CURRENT_VALUE",
        "ENTITY_ID",
    ]
    assert not tuple(tmp_path.glob(".*.import-staging-*"))
    assert not tuple(tmp_path.glob(".*.import-backup-*"))
