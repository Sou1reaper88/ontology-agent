from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from ontology_core import semantic_parser
from ontology_core.errors import OntologyValidationError
from ontology_core.semantic_models import LocalizedText, RuleOperator
from ontology_core.semantic_parser import parse_catalog
from ontology_core.vocabulary import ARGUMENT, CONDITION, LEFT_PROPERTY, OA, VALUE, VALUES


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


@pytest.mark.parametrize(
    ("declaration", "expected_type"),
    (
        (
            'ex:Marked a oa:Concept ; oa:shortName "Marked" ; rdfs:label "Marked" .',
            "http://www.w3.org/2002/07/owl#Class",
        ),
        (
            'ex:Marked a owl:ObjectProperty, oa:Property ; oa:shortName "Marked" ; '
            'rdfs:label "Marked" ; rdfs:domain ex:Record ; rdfs:range xsd:string .',
            "http://www.w3.org/2002/07/owl#DatatypeProperty",
        ),
        (
            'ex:Marked a owl:DatatypeProperty, oa:Relation ; oa:shortName "Marked" ; '
            'rdfs:label "Marked" ; rdfs:domain ex:Record ; rdfs:range ex:Record .',
            "http://www.w3.org/2002/07/owl#ObjectProperty",
        ),
    ),
)
def test_parse_catalog_requires_paired_standard_owl_types(
    declaration: str,
    expected_type: str,
) -> None:
    graph = _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        {declaration}
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert caught.value.details["violations"] == [
        {
            "code": "missing_standard_type",
            "uri": "https://example.invalid/ontology/Marked",
            "path": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "message": f"Marked semantic element requires RDF type {expected_type}",
        }
    ]


def test_parse_catalog_requires_xsd_datatype_property_range() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range ex:CustomDatatype .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert caught.value.details["violations"] == [
        {
            "code": "invalid_datatype_range",
            "uri": "https://example.invalid/ontology/Metric",
            "path": "http://www.w3.org/2000/01/rdf-schema#range",
            "message": "Property range must be an XSD datatype URI",
        }
    ]


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


@pytest.mark.parametrize("second_short_name", ("alpha", "Ａlpha"))
def test_parse_catalog_rejects_normalized_short_name_collisions(
    second_short_name: str,
) -> None:
    graph = _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:First a owl:Class, oa:Concept ; oa:shortName "Alpha" ; rdfs:label "First" .
        ex:Second a owl:Class, oa:Concept ; oa:shortName "{second_short_name}" ;
            rdfs:label "Second" .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    duplicate_uris = [
        item["uri"]
        for item in caught.value.details["violations"]
        if item["code"] == "duplicate_short_name"
    ]
    assert duplicate_uris == [
        "https://example.invalid/ontology/First",
        "https://example.invalid/ontology/Second",
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


def test_parse_catalog_prefers_labels_by_normalized_value_within_tier() -> None:
    catalog = parse_catalog(_graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ;
            rdfs:label "Ａ"@zh-CN, "B"@zh .
        """))

    assert catalog.concepts[0].label == "Ａ"


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
        ("invalid_ontology_reference", "http://www.w3.org/2000/01/rdf-schema#subClassOf"),
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
        ("invalid_ontology_reference", "Semantic reference object must be an IRI"),
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


def test_parse_catalog_builds_recursive_rules_and_mappings(valid_package_dir: Path) -> None:
    catalog = parse_catalog(_catalog_graph(valid_package_dir))

    rule = catalog.rules[0]
    mapping = catalog.mappings[0]
    assert rule.applies_to_uri == "https://example.invalid/ontology/Record"
    assert rule.property_uris == ("https://example.invalid/ontology/Metric",)
    assert rule.relation_uris == ("https://example.invalid/ontology/relatesTo",)
    assert rule.condition is not None
    assert rule.condition.operator is RuleOperator.ALL_OF
    assert tuple(child.operator for child in rule.condition.children) == (
        RuleOperator.EQ,
        RuleOperator.IS_NULL,
    )
    assert rule.condition.children[0].values[0].lexical_form == "42"
    assert (
        rule.condition.children[0].values[0].datatype_uri
        == "http://www.w3.org/2001/XMLSchema#integer"
    )
    assert mapping.semantic_element_uri == "https://example.invalid/ontology/Metric"
    assert mapping.data_source_uri == "https://example.invalid/ontology/NeutralSource"


def test_parse_catalog_preserves_literal_language_in_rule_expressions() -> None:
    catalog = parse_catalog(_graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:string .
        ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;
            oa:appliesTo ex:Record ; oa:condition [
                a oa:Eq ; oa:leftProperty ex:Metric ; oa:value "标记"@zh-CN
            ] .
        """))

    literal = catalog.rules[0].condition.values[0]  # type: ignore[union-attr]
    assert literal.lexical_form == "标记"
    assert literal.datatype_uri is None
    assert literal.language == "zh-CN"


def test_parse_catalog_rejects_recursive_rule_conditions() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:string .
        ex:Loop a oa:AllOf ; oa:argument ex:Loop, [ a oa:IsNull ; oa:leftProperty ex:Metric ] .
        ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;
            oa:appliesTo ex:Record ; oa:condition ex:Loop .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_rule_expression"
    ]


@pytest.mark.parametrize(
    ("statement", "expected_code"),
    [
        ("oa:usesProperty ex:MissingProperty", "invalid_ontology_reference"),
        ("oa:usesRelation ex:MissingRelation", "invalid_ontology_reference"),
    ],
)
def test_parse_catalog_rejects_unknown_rule_references(
    statement: str,
    expected_code: str,
) -> None:
    graph = _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;
            oa:appliesTo ex:Record ; {statement} .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [expected_code]


@pytest.mark.parametrize(
    "statement",
    [
        "oa:semanticElement ex:MissingElement ; oa:dataSource ex:Source",
        "oa:semanticElement ex:Record ; oa:dataSource ex:MissingSource",
    ],
)
def test_parse_catalog_rejects_unknown_mapping_references(statement: str) -> None:
    graph = _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Source a oa:DataSource ; oa:shortName "Source" ; rdfs:label "Source" ;
            oa:platformType "generic" .
        ex:Mapping a oa:PhysicalMapping ; oa:shortName "Mapping" ; rdfs:label "Mapping" ;
            {statement} .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_ontology_reference"
    ]


@pytest.mark.parametrize(
    "declaration",
    (
        'a owl:Class, oa:Concept ; oa:shortName "Marked" ; rdfs:label "Marked"',
        'a owl:DatatypeProperty, oa:Property ; oa:shortName "Marked" ; '
        'rdfs:label "Marked" ; rdfs:domain ex:Record ; rdfs:range xsd:string',
        'a owl:ObjectProperty, oa:Relation ; oa:shortName "Marked" ; '
        'rdfs:label "Marked" ; rdfs:domain ex:Record ; rdfs:range ex:Record',
        'a oa:BusinessRule ; oa:shortName "Marked" ; rdfs:label "Marked" ; '
        "oa:appliesTo ex:Record",
        'a oa:DataSource ; oa:shortName "Marked" ; rdfs:label "Marked" ; '
        'oa:platformType "generic"',
        'a oa:PhysicalMapping ; oa:shortName "Marked" ; rdfs:label "Marked" ; '
        "oa:semanticElement ex:Record ; oa:dataSource ex:Source",
    ),
)
def test_parse_catalog_rejects_file_derived_marked_subjects(declaration: str) -> None:
    graph = Graph().parse(
        data=f"""
            @prefix ex: <https://example.invalid/ontology/> .
            @prefix oa: <urn:ontology-agent:core#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
            ex:Source a oa:DataSource ; oa:shortName "Source" ; rdfs:label "Source" ;
                oa:platformType "generic" .
            <Relative> {declaration} .
            """,
        format="turtle",
        publicID="file://example.invalid/ontology/domain.ttl",
    )

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert any(
        item["code"] == "invalid_semantic_uri" and item["uri"].startswith("file:")
        for item in caught.value.details["violations"]
    )


def _reference_graph(case: str, object_term: str) -> Graph:
    declarations = {
        "parent": (
            'ex:Subject a owl:Class, oa:Concept ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; rdfs:subClassOf {object_term} .'
        ),
        "property_domain": (
            'ex:Subject a owl:DatatypeProperty, oa:Property ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; rdfs:domain {object_term} ; rdfs:range xsd:string .'
        ),
        "property_range": (
            'ex:Subject a owl:DatatypeProperty, oa:Property ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; rdfs:domain ex:Record ; rdfs:range {object_term} .'
        ),
        "relation_domain": (
            'ex:Subject a owl:ObjectProperty, oa:Relation ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; rdfs:domain {object_term} ; rdfs:range ex:Record .'
        ),
        "relation_range": (
            'ex:Subject a owl:ObjectProperty, oa:Relation ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; rdfs:domain ex:Record ; rdfs:range {object_term} .'
        ),
        "applies_to": (
            'ex:Subject a oa:BusinessRule ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; oa:appliesTo {object_term} .'
        ),
        "uses_property": (
            'ex:Subject a oa:BusinessRule ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; oa:appliesTo ex:Record ; oa:usesProperty {object_term} .'
        ),
        "uses_relation": (
            'ex:Subject a oa:BusinessRule ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; oa:appliesTo ex:Record ; oa:usesRelation {object_term} .'
        ),
        "semantic_element": (
            'ex:Subject a oa:PhysicalMapping ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; oa:semanticElement {object_term} ; oa:dataSource ex:Source .'
        ),
        "data_source": (
            'ex:Subject a oa:PhysicalMapping ; oa:shortName "Subject" ; '
            f'rdfs:label "Subject" ; oa:semanticElement ex:Record ; oa:dataSource {object_term} .'
        ),
        "left_property": (
            'ex:Subject a oa:BusinessRule ; oa:shortName "Subject" ; '
            'rdfs:label "Subject" ; oa:appliesTo ex:Record ; oa:condition '
            f'[ a oa:Eq ; oa:leftProperty {object_term} ; oa:value "value" ] .'
        ),
    }
    return _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:string .
        ex:relatesTo a owl:ObjectProperty, oa:Relation ; oa:shortName "relatesTo" ;
            rdfs:label "Relates to" ; rdfs:domain ex:Record ; rdfs:range ex:Record .
        ex:Source a oa:DataSource ; oa:shortName "Source" ; rdfs:label "Source" ;
            oa:platformType "generic" .
        {declarations[case]}
        """)


@pytest.mark.parametrize(
    "case",
    (
        "parent",
        "property_domain",
        "property_range",
        "relation_domain",
        "relation_range",
        "applies_to",
        "uses_property",
        "uses_relation",
        "semantic_element",
        "data_source",
        "left_property",
    ),
)
@pytest.mark.parametrize(
    "object_term",
    ('"not-an-iri"', "[]", "<file://example.invalid/ontology/Target>"),
)
def test_parse_catalog_rejects_non_iri_or_unstable_reference_objects(
    case: str,
    object_term: str,
) -> None:
    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_reference_graph(case, object_term))

    assert "invalid_ontology_reference" in [
        item["code"] for item in caught.value.details["violations"]
    ]


def test_parse_catalog_reports_every_invalid_object_on_single_reference_predicate() -> None:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain "not-an-iri", [] ; rdfs:range xsd:string .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_ontology_reference",
        "invalid_ontology_reference",
    ]


@pytest.mark.parametrize("marker", ("oa:DataSource", "oa:PhysicalMapping"))
def test_parse_catalog_rejects_credential_predicates(marker: str) -> None:
    mapping_support = ""
    mapping_references = ""
    if marker == "oa:PhysicalMapping":
        mapping_support = """
            ex:Record a owl:Class, oa:Concept ; oa:shortName \"Record\" ; rdfs:label \"Record\" .
            ex:Source a oa:DataSource ; oa:shortName \"Source\" ; rdfs:label \"Source\" ;
                oa:platformType \"generic\" .
        """
        mapping_references = "oa:semanticElement ex:Record ; oa:dataSource ex:Source ;"
    graph = _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        {mapping_support}
        ex:Sensitive a {marker} ; oa:shortName "Sensitive" ; rdfs:label "Sensitive" ;
            oa:platformType "generic" ; {mapping_references} oa:token "not-permitted" .
        """)

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "forbidden_credential_predicate"
    ]


def _marker_graph(marker: str, predicate: str) -> Graph:
    if marker == "oa:DataSource":
        support = ""
        values = 'oa:platformType "generic" ;'
    else:
        support = """
            ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
            ex:Source a oa:DataSource ; oa:shortName "Source" ; rdfs:label "Source" ;
                oa:platformType "generic" .
        """
        values = "oa:semanticElement ex:Record ; oa:dataSource ex:Source ;"
    return _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        {support}
        ex:Marked a {marker} ; oa:shortName "Marked" ; rdfs:label "Marked" ;
            {values} <{predicate}> "not-permitted" .
        """)


@pytest.mark.parametrize("marker", ("oa:DataSource", "oa:PhysicalMapping"))
@pytest.mark.parametrize(
    "predicate",
    (
        "https://example.invalid/vocabulary#CONNECTION-string",
        "https://example.invalid/vocabulary/USER_name",
        "https://example.invalid/password/",
        "https://example.invalid/password?x=1",
        "https://example.invalid/password%3Fx=1",
        "https://example.invalid/password/?x=1",
        "https://example.invalid/vocabulary/%20User_name%20/",
        "https://example.invalid/vocabulary/%70%61%73%73%77%6f%72%64/",
        "https://example.invalid/vocabulary#%EF%BC%B4%EF%BC%AF%EF%BC%AB%EF%BC%A5%EF%BC%AE",
        "tag:example:password",
        "custom:example%3Asecret",
        "urn:example:connection-string",
        "urn:example:SeCrEt",
    ),
)
def test_parse_catalog_rejects_credential_predicate_uri_variants(
    marker: str,
    predicate: str,
) -> None:
    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_marker_graph(marker, predicate))

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "forbidden_credential_predicate"
    ]


@pytest.mark.parametrize("marker", ("oa:DataSource", "oa:PhysicalMapping"))
@pytest.mark.parametrize(
    "predicate",
    (
        "urn:example:tokenized",
        "https://example.invalid/platformType?field=password",
        "https://example.invalid/platformType?field=%23password",
        "https://example.invalid/platformType?field=%3Asecret",
    ),
)
def test_parse_catalog_allows_non_credential_predicate_with_similar_name(
    marker: str,
    predicate: str,
) -> None:
    catalog = parse_catalog(_marker_graph(marker, predicate))

    if marker == "oa:DataSource":
        assert len(catalog.data_sources) == 1
        assert not catalog.mappings
    else:
        assert len(catalog.data_sources) == 1
        assert len(catalog.mappings) == 1


def _rule_graph(condition: str) -> Graph:
    return _graph(f"""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:string .
        ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;
            oa:appliesTo ex:Record ; oa:condition {condition} .
        """)


@pytest.mark.parametrize(
    ("operator", "values", "expected"),
    (
        ("oa:In", '("first" "second")', ("first", "second")),
        ("oa:Between", '("lower" "upper")', ("lower", "upper")),
    ),
)
def test_parse_catalog_preserves_rdf_collection_order(
    operator: str,
    values: str,
    expected: tuple[str, ...],
) -> None:
    catalog = parse_catalog(
        _rule_graph(f"[ a {operator} ; oa:leftProperty ex:Metric ; oa:values {values} ]")
    )

    condition = catalog.rules[0].condition
    assert condition is not None
    assert tuple(value.lexical_form for value in condition.values) == expected


@pytest.mark.parametrize(
    "collection",
    (
        '_:items rdf:first "only" ; rdf:rest "not-a-list" .',
        '_:items rdf:first "only" ; rdf:rest _:items .',
    ),
)
def test_parse_catalog_rejects_malformed_or_cyclic_rdf_collection(collection: str) -> None:
    graph = _rule_graph("[ a oa:In ; oa:leftProperty ex:Metric ; oa:values _:items ]")
    graph.parse(
        data="@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n" + collection,
        format="turtle",
    )

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(graph)

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_rule_expression"
    ]


def _deep_not_graph(wrapper_count: int) -> Graph:
    graph = _rule_graph("[ a oa:IsNull ; oa:leftProperty ex:Metric ]")
    rule = URIRef("https://example.invalid/ontology/Rule")
    metric = URIRef("https://example.invalid/ontology/Metric")
    graph.remove((rule, CONDITION, None))
    nodes = [
        URIRef(f"https://example.invalid/ontology/condition/{index}")
        for index in range(wrapper_count + 1)
    ]
    for index in range(wrapper_count):
        graph.add((nodes[index], RDF.type, OA.Not))
        graph.add((nodes[index], ARGUMENT, nodes[index + 1]))
    graph.add((nodes[-1], RDF.type, OA.IsNull))
    graph.add((nodes[-1], LEFT_PROPERTY, metric))
    graph.add((rule, CONDITION, nodes[0]))
    return graph


def test_rule_expression_depth_budget_accepts_boundary_and_rejects_next_level() -> None:
    maximum = semantic_parser.MAX_RULE_EXPRESSION_DEPTH
    assert maximum == 64
    assert parse_catalog(_deep_not_graph(maximum - 1)).rules[0].condition is not None

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_deep_not_graph(maximum))

    assert caught.value.details["violations"] == [
        {
            "code": "invalid_rule_expression",
            "uri": "https://example.invalid/ontology/Rule",
            "path": str(CONDITION),
            "message": f"Rule expression exceeds maximum depth of {maximum}",
        }
    ]


def test_very_deep_rule_expression_returns_stable_violation() -> None:
    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_deep_not_graph(1200))

    serialized = str(caught.value.details)
    assert "maximum depth" in serialized
    assert "RecursionError" not in serialized
    assert "_:" not in serialized


def _shared_dag_graph(*, include_extra_leaf: bool) -> Graph:
    graph = _rule_graph("[ a oa:IsNull ; oa:leftProperty ex:Metric ]")
    namespace = "https://example.invalid/ontology/condition/"
    rule = URIRef("https://example.invalid/ontology/Rule")
    metric = URIRef("https://example.invalid/ontology/Metric")
    root = URIRef(namespace + "root")
    left = URIRef(namespace + "left")
    right = URIRef(namespace + "right")
    shared = URIRef(namespace + "shared")
    graph.remove((rule, CONDITION, None))
    graph.add((rule, CONDITION, root))
    graph.add((root, RDF.type, OA.AllOf))
    graph.add((root, ARGUMENT, left))
    graph.add((root, ARGUMENT, right))
    for parent in (left, right):
        graph.add((parent, RDF.type, OA.Not))
        graph.add((parent, ARGUMENT, shared))
    graph.add((shared, RDF.type, OA.IsNull))
    graph.add((shared, LEFT_PROPERTY, metric))
    if include_extra_leaf:
        extra = URIRef(namespace + "extra")
        graph.add((root, ARGUMENT, extra))
        graph.add((extra, RDF.type, OA.IsNull))
        graph.add((extra, LEFT_PROPERTY, metric))
    return graph


def test_rule_expression_node_budget_counts_shared_dag_node_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_parser, "MAX_RULE_EXPRESSION_NODES", 4)
    assert parse_catalog(_shared_dag_graph(include_extra_leaf=False)).rules[0].condition is not None

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_shared_dag_graph(include_extra_leaf=True))
    assert "maximum node count of 4" in str(caught.value.details)


def _collection_graph(item_count: int) -> Graph:
    graph = _rule_graph("[ a oa:IsNull ; oa:leftProperty ex:Metric ]")
    rule = URIRef("https://example.invalid/ontology/Rule")
    metric = URIRef("https://example.invalid/ontology/Metric")
    expression = URIRef("https://example.invalid/ontology/condition/in")
    graph.remove((rule, CONDITION, None))
    graph.add((rule, CONDITION, expression))
    graph.add((expression, RDF.type, OA.In))
    graph.add((expression, LEFT_PROPERTY, metric))
    head = BNode()
    graph.add((expression, VALUES, head))
    current = head
    for index in range(item_count):
        graph.add((current, RDF.first, Literal(f"value-{index}")))
        tail = RDF.nil if index == item_count - 1 else BNode()
        graph.add((current, RDF.rest, tail))
        current = tail
    return graph


def test_rule_collection_item_budget_accepts_boundary_and_rejects_next_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_parser, "MAX_RULE_COLLECTION_ITEMS", 3)
    condition = parse_catalog(_collection_graph(3)).rules[0].condition
    assert condition is not None
    assert len(condition.values) == 3

    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_collection_graph(4))
    assert "maximum item count of 3" in str(caught.value.details)


@pytest.mark.parametrize(
    "condition",
    (
        "[ a oa:AllOf ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        "[ a oa:AnyOf ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        "[ a oa:Not ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ], "
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        "[ a oa:Eq ; oa:leftProperty ex:Metric ]",
        '[ a oa:IsNull ; oa:leftProperty ex:Metric ; oa:value "unexpected" ]',
        "[ a oa:In ; oa:leftProperty ex:Metric ; oa:values () ]",
        '[ a oa:Between ; oa:leftProperty ex:Metric ; oa:values ("one" "two" "three") ]',
    ),
)
def test_parse_catalog_rejects_rule_operator_cardinality_boundaries(condition: str) -> None:
    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_rule_graph(condition))

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_rule_expression"
    ]


@pytest.mark.parametrize(
    "condition",
    (
        "[ a oa:AllOf ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ], "
        '[ a oa:IsNull ; oa:leftProperty ex:Metric ] ; oa:value "extra" ]',
        "[ a oa:AnyOf ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ], "
        '[ a oa:IsNull ; oa:leftProperty ex:Metric ] ; oa:parameter "extra" ]',
        "[ a oa:Not ; oa:argument [ a oa:IsNull ; oa:leftProperty ex:Metric ] ; "
        'oa:values ("extra") ]',
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ; oa:argument "
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        '[ a oa:In ; oa:leftProperty ex:Metric ; oa:values ("one") ; oa:value "extra" ]',
        '[ a oa:Between ; oa:leftProperty ex:Metric ; oa:values ("one" "two") ; '
        'oa:parameter "extra" ]',
        '[ a oa:Eq ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:values ("extra") ]',
        '[ a oa:Ne ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:argument '
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        '[ a oa:Gt ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:values ("extra") ]',
        '[ a oa:Gte ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:argument '
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
        '[ a oa:Lt ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:values ("extra") ]',
        '[ a oa:Lte ; oa:leftProperty ex:Metric ; oa:value "one" ; oa:argument '
        "[ a oa:IsNull ; oa:leftProperty ex:Metric ] ]",
    ),
)
def test_parse_catalog_rejects_extra_structural_predicates_for_every_operator(
    condition: str,
) -> None:
    with pytest.raises(OntologyValidationError) as caught:
        parse_catalog(_rule_graph(condition))

    assert [item["code"] for item in caught.value.details["violations"]] == [
        "invalid_rule_expression"
    ]


def _logical_graph(argument_order: tuple[str, str]) -> Graph:
    graph = _graph("""
        @prefix ex: <https://example.invalid/ontology/> .
        @prefix oa: <urn:ontology-agent:core#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range xsd:string .
        ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;
            oa:appliesTo ex:Record .
        """)
    namespace = "https://example.invalid/ontology/"
    condition = URIRef(namespace + "Condition")
    value_child = URIRef(namespace + "ValueChild")
    null_child = URIRef(namespace + "NullChild")
    metric = URIRef(namespace + "Metric")
    graph.add((URIRef(namespace + "Rule"), CONDITION, condition))
    graph.add((condition, RDF.type, OA.AllOf))
    graph.add((value_child, RDF.type, OA.Eq))
    graph.add((value_child, LEFT_PROPERTY, metric))
    graph.add((value_child, VALUE, Literal("value")))
    graph.add((null_child, RDF.type, OA.IsNull))
    graph.add((null_child, LEFT_PROPERTY, metric))
    children = {"value": value_child, "null": null_child}
    for name in argument_order:
        graph.add((condition, ARGUMENT, children[name]))
    return graph


def test_parse_catalog_canonicalizes_commutative_children_across_insertion_orders() -> None:
    first = parse_catalog(_logical_graph(("value", "null")))
    second = parse_catalog(_logical_graph(("null", "value")))

    assert first == second
    condition = first.rules[0].condition
    assert condition is not None
    assert tuple(child.operator for child in condition.children) == (
        RuleOperator.EQ,
        RuleOperator.IS_NULL,
    )
