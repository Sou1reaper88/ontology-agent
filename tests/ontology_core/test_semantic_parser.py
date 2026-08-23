from pathlib import Path

import pytest
from rdflib import Graph

from ontology_core.errors import OntologyValidationError
from ontology_core.semantic_models import LocalizedText
from ontology_core.semantic_parser import parse_catalog


def _catalog_graph(valid_package_dir: Path) -> Graph:
    graph = Graph()
    for name in ("core.ttl", "domain.ttl", "rules.ttl", "mappings.ttl"):
        graph.parse(valid_package_dir / name, format="turtle")
    return graph


def _graph(data: str) -> Graph:
    return Graph().parse(data=data, format="turtle")


def test_parse_catalog_builds_marked_domain_elements(valid_package_dir: Path) -> None:
    catalog = parse_catalog(_catalog_graph(valid_package_dir))

    assert [item.short_name for item in catalog.concepts] == ["Record", "RelatedRecord"]
    record = next(item for item in catalog.concepts if item.short_name == "Record")
    related = next(item for item in catalog.concepts if item.short_name == "RelatedRecord")
    assert record.label == "记录"
    assert record.labels == (
        LocalizedText(value="Record", language="en"),
        LocalizedText(value="记录", language="zh-CN"),
    )
    assert record.description == "Neutral record used only by tests."
    assert related.parent_uris == ("https://example.invalid/ontology/Record",)
    assert record.child_uris == ("https://example.invalid/ontology/RelatedRecord",)


def test_parse_catalog_preserves_property_datatype_and_relation_direction(
    valid_package_dir: Path,
) -> None:
    catalog = parse_catalog(_catalog_graph(valid_package_dir))

    property_values = [
        (item.short_name, item.concept_uri, item.datatype_uri) for item in catalog.properties
    ]
    assert property_values == [
        (
            "Metric",
            "https://example.invalid/ontology/Record",
            "http://www.w3.org/2001/XMLSchema#integer",
        ),
    ]
    relation_values = [
        (item.short_name, item.source_concept_uri, item.target_concept_uri)
        for item in catalog.relations
    ]
    assert relation_values == [
        (
            "relatesTo",
            "https://example.invalid/ontology/Record",
            "https://example.invalid/ontology/RelatedRecord",
        ),
    ]


def test_parse_catalog_ignores_unmarked_owl_elements(valid_package_dir: Path) -> None:
    graph = _catalog_graph(valid_package_dir)
    graph.parse(
        data="""
            @prefix ex: <https://example.invalid/ontology/> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            ex:Ignored a owl:Class .
        """,
        format="turtle",
    )

    catalog = parse_catalog(graph)

    assert [item.short_name for item in catalog.concepts] == ["Record", "RelatedRecord"]


def test_parse_catalog_sorts_elements_and_uri_links_deterministically() -> None:
    catalog = parse_catalog(_graph("""
            @prefix ex: <https://example.invalid/ontology/> .
            @prefix oa: <urn:ontology-agent:core#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            ex:Zeta a owl:Class, oa:Concept ; oa:shortName "zeta" ; rdfs:label "Zeta" .
            ex:Alpha a owl:Class, oa:Concept ; oa:shortName "Alpha" ; rdfs:label "Alpha" .
            ex:Child a owl:Class, oa:Concept ; oa:shortName "Child" ; rdfs:label "Child" ;
                rdfs:subClassOf ex:Zeta, ex:Alpha .
            """))

    child = next(item for item in catalog.concepts if item.short_name == "Child")
    assert [item.short_name for item in catalog.concepts] == ["Alpha", "Child", "zeta"]
    assert child.parent_uris == (
        "https://example.invalid/ontology/Alpha",
        "https://example.invalid/ontology/Zeta",
    )


def test_parse_catalog_rejects_missing_short_name() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        ex:Record a owl:Class, oa:Concept ; rdfs:label "Record" .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert caught.value.details["violations"] == [
        {
            "code": "missing_short_name",
            "uri": "https://example.invalid/ontology/Record",
            "path": "urn:ontology-agent:core#shortName",
            "message": "Marked semantic element requires exactly one short name",
        },
    ]


def test_parse_catalog_rejects_duplicate_short_names_across_markers() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        ex:Record a owl:Class, oa:Concept ; oa:shortName "Repeated" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Repeated" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:integer .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "duplicate_short_name",
        "duplicate_short_name",
    ]
    assert [item["uri"] for item in caught.value.details["violations"]] == [
        "https://example.invalid/ontology/Metric",
        "https://example.invalid/ontology/Record",
    ]


def test_parse_catalog_reports_duplicate_short_names_alongside_other_errors() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Repeated" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Repeated" ;
            rdfs:label "Metric" ; rdfs:range xsd:integer .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [(item["code"], item["uri"]) for item in caught.value.details["violations"]] == [
        ("duplicate_short_name", "https://example.invalid/ontology/Metric"),
        ("duplicate_short_name", "https://example.invalid/ontology/Record"),
        ("missing_domain", "https://example.invalid/ontology/Metric"),
        ("missing_label", "https://example.invalid/ontology/Record"),
    ]


def test_parse_catalog_prefers_chinese_labels_by_value_before_language() -> None:
    catalog = parse_catalog(_graph("""
            @prefix ex: <https://example.invalid/ontology/> .
            @prefix oa: <urn:ontology-agent:core#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ;
                rdfs:label "Zulu"@zh, "Alpha"@zh-CN .
            """))

    assert catalog.concepts[0].label == "Alpha"


def test_parse_catalog_does_not_report_marked_invalid_concept_as_dangling() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:InvalidRecord a owl:Class, oa:Concept ; oa:shortName "InvalidRecord" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:InvalidRecord ; rdfs:range xsd:integer .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == ["missing_label"]


def test_parse_catalog_reports_unknown_property_domain_when_property_is_invalid() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Metric a owl:DatatypeProperty, oa:Property ;
            rdfs:domain ex:Unknown ; rdfs:range xsd:integer .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [(item["code"], item["path"]) for item in caught.value.details["violations"]] == [
        ("dangling_concept_reference", "http://www.w3.org/2000/01/rdf-schema#domain"),
        ("missing_label", "http://www.w3.org/2000/01/rdf-schema#label"),
        ("missing_short_name", "urn:ontology-agent:core#shortName"),
    ]


def test_parse_catalog_reports_unknown_relation_endpoints_when_relation_is_invalid() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:relatesTo a owl:ObjectProperty, oa:Relation ; oa:shortName "relatesTo" ;
            rdfs:domain ex:UnknownSource ; rdfs:range ex:UnknownTarget .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [(item["code"], item["path"]) for item in caught.value.details["violations"]] == [
        ("dangling_concept_reference", "http://www.w3.org/2000/01/rdf-schema#domain"),
        ("dangling_concept_reference", "http://www.w3.org/2000/01/rdf-schema#range"),
        ("missing_label", "http://www.w3.org/2000/01/rdf-schema#label"),
    ]


def test_parse_catalog_reports_invalid_concept_parents_when_concept_is_invalid() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Child a owl:Class, oa:Concept ; oa:shortName "Child" ;
            rdfs:subClassOf ex:Unknown, "not-a-uri" .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [(item["code"], item["path"]) for item in caught.value.details["violations"]] == [
        ("dangling_concept_reference", "http://www.w3.org/2000/01/rdf-schema#subClassOf"),
        ("invalid_parent_reference", "http://www.w3.org/2000/01/rdf-schema#subClassOf"),
        ("missing_label", "http://www.w3.org/2000/01/rdf-schema#label"),
    ]


def test_parse_catalog_rejects_invalid_and_unknown_concept_parents() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Child a owl:Class, oa:Concept ; oa:shortName "Child" ; rdfs:label "Child" ;
            rdfs:subClassOf ex:Unknown, "not-a-uri" .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [(item["code"], item["message"]) for item in caught.value.details["violations"]] == [
        (
            "dangling_concept_reference",
            "Referenced concept does not exist: https://example.invalid/ontology/Unknown",
        ),
        ("invalid_parent_reference", "Concept parent must be a URI: not-a-uri"),
    ]


def test_parse_catalog_aggregates_sorted_missing_and_dangling_concept_references() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:range xsd:integer .
        ex:relatesTo a owl:ObjectProperty, oa:Relation ; oa:shortName "relatesTo" ;
            rdfs:label "Relates to" ; rdfs:domain ex:Missing ; rdfs:range ex:Record .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert caught.value.details["violations"] == [
        {
            "code": "dangling_concept_reference",
            "uri": "https://example.invalid/ontology/relatesTo",
            "path": "http://www.w3.org/2000/01/rdf-schema#domain",
            "message": "Referenced concept does not exist: https://example.invalid/ontology/Missing",
        },
        {
            "code": "missing_domain",
            "uri": "https://example.invalid/ontology/Metric",
            "path": "http://www.w3.org/2000/01/rdf-schema#domain",
            "message": "Marked semantic element requires exactly one domain",
        },
    ]
