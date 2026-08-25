"""Deterministic RDF package construction from managed workspace drafts."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_core.authoring import initialize_package
from ontology_core.management.models import (
    DraftField,
    DraftObject,
    WorkspaceDraft,
)
from ontology_core.management.validation import DraftValidator
from ontology_core.metadata_package import (
    _add_element_text,
    _datatype,
    _semantic_short_name,
    _uri,
    _write_graph,
)
from ontology_core.repository import OntologyRepository, OntologySnapshot
from ontology_core.vocabulary import OA


def _graph(base_uri: str) -> Graph:
    graph = Graph()
    graph.bind("oa", OA)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.add((URIRef(base_uri), RDF.type, OWL.Ontology))
    return graph


def _short_name(kind: str, stable_id: str) -> str:
    return _semantic_short_name(f"{kind}_{stable_id}", kind)


def _concept_uri(draft: WorkspaceDraft, object_: DraftObject) -> URIRef:
    return _uri(draft.base_uri, "concept", object_.id)


def _property_uri(draft: WorkspaceDraft, field: DraftField) -> URIRef:
    return _uri(draft.base_uri, "property", field.id)


def _add_physical_label(graph: Graph, subject: URIRef, physical_name: str) -> None:
    graph.add((subject, RDFS.label, Literal(physical_name)))


class PackageBuilder:
    """Build one validated workspace draft into a caller-owned staging directory."""

    def __init__(self, validator: DraftValidator | None = None) -> None:
        self._validator = validator or DraftValidator()

    def build(self, draft: WorkspaceDraft, target: Path, version: str) -> OntologySnapshot:
        """Create and validate a fixed six-file package without replacing target data."""
        self._validator.assert_publishable(draft)
        target = Path(target)
        initialize_package(
            target,
            package_id=draft.package_id,
            base_uri=draft.base_uri,
            version=version,
        )
        _write_graph(target / "domain.ttl", self._domain_graph(draft))
        _write_graph(target / "mappings.ttl", self._mappings_graph(draft))
        _write_graph(target / "rules.ttl", self._rules_graph(draft))
        repository = OntologyRepository()
        repository.publish(target)
        return repository.current()

    @staticmethod
    def _domain_graph(draft: WorkspaceDraft) -> Graph:
        graph = _graph(draft.base_uri)
        objects_by_id = {object_.id: object_ for object_ in draft.objects}
        fields_by_id = {field.id: field for object_ in draft.objects for field in object_.fields}

        for object_ in sorted(draft.objects, key=lambda item: item.id):
            concept_uri = _concept_uri(draft, object_)
            graph.add((concept_uri, RDF.type, OWL.Class))
            graph.add((concept_uri, RDF.type, OA.Concept))
            _add_element_text(
                graph,
                concept_uri,
                short_name=_short_name("Concept", object_.id),
                label=object_.label,
                description=object_.description,
            )
            _add_physical_label(graph, concept_uri, object_.physical_name)

            for field in sorted(object_.fields, key=lambda item: item.id):
                property_uri = _property_uri(draft, field)
                graph.add((property_uri, RDF.type, OWL.DatatypeProperty))
                graph.add((property_uri, RDF.type, OA.Property))
                graph.add((property_uri, RDFS.domain, concept_uri))
                graph.add((property_uri, RDFS.range, _datatype(field.xsd_type)))
                _add_element_text(
                    graph,
                    property_uri,
                    short_name=_short_name("Property", field.id),
                    label=field.label,
                    description=field.description,
                )
                _add_physical_label(graph, property_uri, field.physical_name)
                for alias in sorted(set(field.aliases)):
                    graph.add((property_uri, RDFS.label, Literal(alias, lang="zh-CN")))

        for relation in sorted(draft.relations, key=lambda item: item.id):
            relation_uri = _uri(draft.base_uri, "relation", relation.id)
            source_object = objects_by_id[relation.source_object_id]
            target_object = objects_by_id[relation.target_object_id]
            graph.add((relation_uri, RDF.type, OWL.ObjectProperty))
            graph.add((relation_uri, RDF.type, OA.Relation))
            graph.add((relation_uri, RDFS.domain, _concept_uri(draft, source_object)))
            graph.add((relation_uri, RDFS.range, _concept_uri(draft, target_object)))
            _add_element_text(
                graph,
                relation_uri,
                short_name=_short_name("Relation", relation.id),
                label=relation.label or None,
            )
            graph.add(
                (
                    relation_uri,
                    OA.sourceProperty,
                    _property_uri(draft, fields_by_id[relation.source_field_id]),
                )
            )
            graph.add(
                (
                    relation_uri,
                    OA.targetProperty,
                    _property_uri(draft, fields_by_id[relation.target_field_id]),
                )
            )
            graph.add((relation_uri, OA.cardinality, Literal(relation.cardinality)))
            graph.add((relation_uri, OA.status, Literal(relation.status)))
            graph.add((relation_uri, OA.priority, Literal(relation.priority, datatype=XSD.integer)))
            graph.add((relation_uri, OA.confirmed, Literal(relation.confirmed)))
        return graph

    @staticmethod
    def _mappings_graph(draft: WorkspaceDraft) -> Graph:
        graph = _graph(draft.base_uri)
        source = draft.data_source
        source_uri = _uri(draft.base_uri, "source", source.id)
        graph.add((source_uri, RDF.type, OA.DataSource))
        _add_element_text(
            graph,
            source_uri,
            short_name=_short_name("DataSource", source.id),
            label=source.label,
        )
        graph.add((source_uri, OA.platformType, Literal(source.platform_type)))
        if source.dialect is not None:
            graph.add((source_uri, OA.dialect, Literal(source.dialect)))

        for object_ in sorted(draft.objects, key=lambda item: item.id):
            object_mapping_uri = _uri(draft.base_uri, "mapping", f"object/{object_.id}")
            graph.add((object_mapping_uri, RDF.type, OA.PhysicalMapping))
            _add_element_text(
                graph,
                object_mapping_uri,
                short_name=_short_name("ObjectMapping", object_.id),
                label=f"{object_.label or object_.physical_name} mapping",
            )
            graph.add((object_mapping_uri, OA.semanticElement, _concept_uri(draft, object_)))
            graph.add((object_mapping_uri, OA.dataSource, source_uri))
            graph.add(
                (object_mapping_uri, OA.physicalNamespace, Literal(source.physical_namespace))
            )
            graph.add((object_mapping_uri, OA.objectName, Literal(object_.physical_name)))
            graph.add(
                (object_mapping_uri, OA.priority, Literal(object_.priority, datatype=XSD.integer))
            )
            graph.add((object_mapping_uri, OA.enabled, Literal(object_.status == "active")))

            for field in sorted(object_.fields, key=lambda item: item.id):
                field_mapping_uri = _uri(draft.base_uri, "mapping", f"field/{field.id}")
                graph.add((field_mapping_uri, RDF.type, OA.PhysicalMapping))
                _add_element_text(
                    graph,
                    field_mapping_uri,
                    short_name=_short_name("FieldMapping", field.id),
                    label=f"{field.label or field.physical_name} mapping",
                )
                graph.add((field_mapping_uri, OA.semanticElement, _property_uri(draft, field)))
                graph.add((field_mapping_uri, OA.dataSource, source_uri))
                graph.add((field_mapping_uri, OA.fieldName, Literal(field.physical_name)))
                graph.add(
                    (field_mapping_uri, OA.priority, Literal(field.priority, datatype=XSD.integer))
                )
                graph.add((field_mapping_uri, OA.enabled, Literal(field.status == "active")))
        return graph

    @staticmethod
    def _rules_graph(draft: WorkspaceDraft) -> Graph:
        graph = _graph(draft.base_uri)
        objects_by_id = {object_.id: object_ for object_ in draft.objects}
        fields_by_id = {field.id: field for object_ in draft.objects for field in object_.fields}
        policies = sorted(
            draft.temporal_policies,
            key=lambda item: (item.object_id, item.partition_field_id, item.status),
        )
        for policy in policies:
            object_ = objects_by_id[policy.object_id]
            field = fields_by_id[policy.partition_field_id]
            policy_id = f"{policy.object_id}/{policy.partition_field_id}"
            policy_uri = _uri(draft.base_uri, "policy", policy_id)
            graph.add((policy_uri, RDF.type, OA.TemporalPartitionPolicy))
            _add_element_text(
                graph,
                policy_uri,
                short_name=_short_name("TemporalPolicy", policy_id),
                label=f"{object_.label or object_.physical_name} temporal policy",
            )
            graph.add((policy_uri, OA.appliesTo, _concept_uri(draft, object_)))
            graph.add((policy_uri, OA.partitionProperty, _property_uri(draft, field)))
            graph.add((policy_uri, OA.partitionGrain, Literal(policy.grain.value)))
            graph.add((policy_uri, OA.defaultStrategy, Literal(policy.default_strategy.value)))
            graph.add((policy_uri, OA.allowQueryOverride, Literal(policy.allow_query_override)))
            graph.add((policy_uri, OA.status, Literal(policy.status)))
            graph.add((policy_uri, OA.priority, Literal(policy.priority, datatype=XSD.integer)))
        return graph
