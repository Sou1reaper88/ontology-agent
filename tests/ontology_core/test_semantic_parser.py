from pathlib import Path

import pytest
from rdflib import Graph

from ontology_core.errors import OntologyValidationError
from ontology_core.semantic_models import LocalizedText, RuleOperator
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

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range ex:TextValue .
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

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range ex:TextValue .
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
def test_parse_catalog_allows_non_credential_predicate_with_similar_name(marker: str) -> None:
    catalog = parse_catalog(_marker_graph(marker, "urn:example:tokenized"))

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

        ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; rdfs:label "Record" .
        ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ;
            rdfs:label "Metric" ; rdfs:domain ex:Record ; rdfs:range ex:TextValue .
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
