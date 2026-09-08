from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path
from urllib.parse import quote

from pydantic import Field
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyImportError
from ontology_core.inspection import inspection_from_snapshot
from ontology_core.models import FrozenModel
from ontology_core.repository import OntologyRepository
from ontology_core.semantic_models import PackageInspection
from ontology_core.tabular_metadata import (
    ImportDiagnostic,
    TabularMetadataDraft,
    analyze_metadata,
    raise_for_blocking_diagnostics,
)
from ontology_core.vocabulary import OA

_SHORT_NAME_CHARACTER = re.compile(r"[^A-Za-z0-9._-]")
_TYPE_MAP = {
    "bigint": XSD.integer,
    "bool": XSD.boolean,
    "boolean": XSD.boolean,
    "date": XSD.date,
    "datetime": XSD.dateTime,
    "decimal": XSD.decimal,
    "double": XSD.double,
    "float": XSD.float,
    "int": XSD.integer,
    "integer": XSD.integer,
    "long": XSD.integer,
    "number": XSD.decimal,
    "short": XSD.integer,
    "string": XSD.string,
    "timestamp": XSD.dateTime,
}


class PackageGenerationOptions(FrozenModel):
    package_id: str = Field(min_length=1)
    base_uri: str = Field(min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    physical_namespace: str = Field(min_length=1)
    platform_type: str = Field(default="generic", min_length=1)
    dialect: str = Field(default="generic", min_length=1)


class MetadataImportResult(FrozenModel):
    target: Path
    diagnostics: tuple[ImportDiagnostic, ...]
    inspection: PackageInspection


def _semantic_short_name(value: str, prefix: str) -> str:
    cleaned = _SHORT_NAME_CHARACTER.sub("_", value)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned


def _uri(base_uri: str, category: str, value: str) -> URIRef:
    separator = "" if base_uri.endswith(("/", "#", ":")) else "/"
    return URIRef(f"{base_uri}{separator}{category}/{quote(value, safe='._-')}")


def _add_element_text(
    graph: Graph,
    subject: URIRef,
    *,
    short_name: str,
    label: str | None,
    description: str | None = None,
) -> None:
    graph.add((subject, OA.shortName, Literal(short_name)))
    graph.add((subject, RDFS.label, Literal(short_name)))
    if label and label != short_name:
        graph.add((subject, RDFS.label, Literal(label, lang="zh-CN")))
    if description:
        graph.add((subject, RDFS.comment, Literal(description, lang="zh-CN")))


def _datatype(source_type: str | None) -> URIRef:
    return _TYPE_MAP.get((source_type or "string").casefold(), XSD.string)


def _domain_graph(draft: TabularMetadataDraft, options: PackageGenerationOptions) -> Graph:
    graph = Graph()
    graph.bind("oa", OA)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.add((URIRef(options.base_uri), RDF.type, OWL.Ontology))

    concept_short_name = _semantic_short_name(draft.table.physical_name, "Concept")
    concept_uri = _uri(options.base_uri, "concept", concept_short_name)
    graph.add((concept_uri, RDF.type, OWL.Class))
    graph.add((concept_uri, RDF.type, OA.Concept))
    _add_element_text(
        graph,
        concept_uri,
        short_name=concept_short_name,
        label=draft.table.label,
        description=draft.table.description,
    )

    for field in draft.fields:
        short_name = _semantic_short_name(field.physical_name, "Property")
        property_uri = _uri(options.base_uri, "property", short_name)
        graph.add((property_uri, RDF.type, OWL.DatatypeProperty))
        graph.add((property_uri, RDF.type, OA.Property))
        graph.add((property_uri, RDFS.domain, concept_uri))
        graph.add((property_uri, RDFS.range, _datatype(field.source_type)))
        _add_element_text(
            graph,
            property_uri,
            short_name=short_name,
            label=field.label,
            description=field.description,
        )
        for alias in field.aliases:
            graph.add((property_uri, RDFS.label, Literal(alias, lang="zh-CN")))
    return graph


def _mappings_graph(draft: TabularMetadataDraft, options: PackageGenerationOptions) -> Graph:
    graph = Graph()
    graph.bind("oa", OA)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.add((URIRef(options.base_uri), RDF.type, OWL.Ontology))

    concept_short_name = _semantic_short_name(draft.table.physical_name, "Concept")
    concept_uri = _uri(options.base_uri, "concept", concept_short_name)
    source_uri = _uri(options.base_uri, "source", "ImportedDataSource")
    graph.add((source_uri, RDF.type, OA.DataSource))
    _add_element_text(
        graph,
        source_uri,
        short_name="ImportedDataSource",
        label="Imported data source",
    )
    graph.add((source_uri, OA.platformType, Literal(options.platform_type)))
    graph.add((source_uri, OA.dialect, Literal(options.dialect)))

    object_mapping_uri = _uri(options.base_uri, "mapping", "ImportedObjectMapping")
    graph.add((object_mapping_uri, RDF.type, OA.PhysicalMapping))
    _add_element_text(
        graph,
        object_mapping_uri,
        short_name="ImportedObjectMapping",
        label="Imported object mapping",
    )
    graph.add((object_mapping_uri, OA.semanticElement, concept_uri))
    graph.add((object_mapping_uri, OA.dataSource, source_uri))
    graph.add((object_mapping_uri, OA.physicalNamespace, Literal(options.physical_namespace)))
    graph.add((object_mapping_uri, OA.objectName, Literal(draft.table.physical_name)))
    graph.add((object_mapping_uri, OA.priority, Literal(100, datatype=XSD.integer)))
    graph.add((object_mapping_uri, OA.enabled, Literal(True)))

    for field in draft.fields:
        property_short_name = _semantic_short_name(field.physical_name, "Property")
        property_uri = _uri(options.base_uri, "property", property_short_name)
        mapping_short_name = _semantic_short_name(f"{field.physical_name}Mapping", "Mapping")
        mapping_uri = _uri(options.base_uri, "mapping", mapping_short_name)
        graph.add((mapping_uri, RDF.type, OA.PhysicalMapping))
        _add_element_text(
            graph,
            mapping_uri,
            short_name=mapping_short_name,
            label=f"{field.label or field.physical_name} mapping",
        )
        graph.add((mapping_uri, OA.semanticElement, property_uri))
        graph.add((mapping_uri, OA.dataSource, source_uri))
        graph.add((mapping_uri, OA.fieldName, Literal(field.physical_name)))
        graph.add((mapping_uri, OA.priority, Literal(100, datatype=XSD.integer)))
        graph.add((mapping_uri, OA.enabled, Literal(True)))
    return graph


def _rules_graph(draft: TabularMetadataDraft, options: PackageGenerationOptions) -> Graph:
    graph = Graph()
    graph.bind("oa", OA)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.add((URIRef(options.base_uri), RDF.type, OWL.Ontology))
    policy = draft.temporal_policy
    if policy is None:
        return graph

    concept_short_name = _semantic_short_name(draft.table.physical_name, "Concept")
    concept_uri = _uri(options.base_uri, "concept", concept_short_name)
    property_short_name = _semantic_short_name(policy.field, "Property")
    property_uri = _uri(options.base_uri, "property", property_short_name)
    policy_short_name = _semantic_short_name(
        f"{concept_short_name}TemporalPolicy", "TemporalPolicy"
    )
    policy_uri = _uri(options.base_uri, "policy", policy_short_name)
    graph.add((policy_uri, RDF.type, OA.TemporalPartitionPolicy))
    _add_element_text(
        graph,
        policy_uri,
        short_name=policy_short_name,
        label="默认时间分区策略",
    )
    graph.add((policy_uri, OA.appliesTo, concept_uri))
    graph.add((policy_uri, OA.partitionProperty, property_uri))
    graph.add((policy_uri, OA.partitionGrain, Literal(policy.grain.value)))
    graph.add((policy_uri, OA.defaultStrategy, Literal(policy.default_strategy.value)))
    graph.add((policy_uri, OA.allowQueryOverride, Literal(policy.allow_query_override)))
    graph.add((policy_uri, OA.status, Literal("active")))
    graph.add((policy_uri, OA.priority, Literal(100, datatype=XSD.integer)))
    return graph


def _write_graph(path: Path, graph: Graph) -> None:
    content = graph.serialize(format="turtle")
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def _is_link_or_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _require_real_target_directory(target: Path) -> None:
    if not target.is_dir() or _is_link_or_reparse_point(target):
        raise OntologyImportError(
            "目标本体包必须是普通目录",
            details={"path": str(target)},
        )


def _activate_staging(staging: Path, target: Path, *, replace: bool) -> None:
    target_exists = target.exists()
    if target_exists:
        _require_real_target_directory(target)
        if not replace:
            raise OntologyImportError(
                "目标本体包已存在",
                details={"path": str(target)},
            )

    backup = target.parent / f".{target.name}.import-backup-{secrets.token_hex(16)}"
    captured = False
    activated = False
    try:
        if target_exists:
            target.rename(backup)
            captured = True
        staging.rename(target)
        activated = True
        repository = OntologyRepository()
        repository.publish(target)
    except Exception:
        if activated and target.exists():
            target.rename(staging)
        if captured and backup.exists():
            backup.rename(target)
        raise
    else:
        if captured:
            shutil.rmtree(backup)


def generate_metadata_package(
    draft: TabularMetadataDraft,
    target: Path,
    options: PackageGenerationOptions,
    *,
    replace: bool = False,
) -> MetadataImportResult:
    diagnostics = analyze_metadata(draft)
    raise_for_blocking_diagnostics(diagnostics)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not replace:
        _require_real_target_directory(target)
        raise OntologyImportError(
            "目标本体包已存在",
            details={"path": str(target)},
        )

    staging = target.parent / f".{target.name}.import-staging-{secrets.token_hex(16)}"
    try:
        initialize_package(
            staging,
            package_id=options.package_id,
            base_uri=options.base_uri,
            version=options.version,
        )
        _write_graph(staging / "domain.ttl", _domain_graph(draft, options))
        _write_graph(staging / "mappings.ttl", _mappings_graph(draft, options))
        _write_graph(staging / "rules.ttl", _rules_graph(draft, options))
        repository = OntologyRepository()
        repository.publish(staging)
        _activate_staging(staging, target, replace=replace)
        active_repository = OntologyRepository()
        active_repository.publish(target)
        inspection = inspection_from_snapshot(active_repository.current())
        return MetadataImportResult(
            target=target,
            diagnostics=diagnostics,
            inspection=inspection,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
