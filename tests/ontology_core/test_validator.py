import json
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph

from ontology_core.errors import OntologyParseError
from ontology_core.validator import OntologyValidator

_UNLABELLED_TTL = (
    "@prefix ex: <https://example.invalid/ontology/> .\n"
    "@prefix oa: <urn:ontology-agent:core#> .\n"
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    'ex:Unlabelled a owl:Class, oa:Concept ; oa:shortName "Unlabelled" .\n'
)

_MULTI_MESSAGE_SHAPES_TTL = (
    "@prefix ex: <https://example.invalid/ontology/> .\n"
    "@prefix oa: <urn:ontology-agent:core#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
    "ex:Shape a sh:NodeShape ;\n"
    "  sh:targetClass oa:Concept ;\n"
    "  sh:property [\n"
    "    sh:path rdfs:label ;\n"
    "    sh:minCount 1 ;\n"
    '    sh:message "fictional-secret-shacl-message" ;\n'
    '    sh:message "another-authored-message"\n'
    "  ] .\n"
)


def _graph(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


def _shape_paths(valid_package_dir: Path) -> tuple[Path, Path]:
    return (
        valid_package_dir / "shapes.ttl",
        Path(__file__).parents[2] / "ontology_core" / "resources" / "shapes.ttl",
    )


def test_valid_graph_conforms(valid_package_dir: Path) -> None:
    data = _graph(valid_package_dir / "core.ttl")
    data += _graph(valid_package_dir / "domain.ttl")
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is True
    assert report.violations == ()


def test_shacl_contract_requires_paired_standard_owl_types(
    valid_package_dir: Path,
) -> None:
    data = Graph().parse(
        data=(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix oa: <urn:ontology-agent:core#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            'ex:Marked a oa:Concept ; oa:shortName "Marked" ; rdfs:label "Marked" .\n'
        ),
        format="turtle",
    )

    for shapes_path in _shape_paths(valid_package_dir):
        report = OntologyValidator().validate(data, _graph(shapes_path))
        assert report.conforms is False
        assert any(
            violation.path == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
            for violation in report.violations
        )


def test_shacl_contract_requires_xsd_property_range(valid_package_dir: Path) -> None:
    data = Graph().parse(
        data=(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix oa: <urn:ontology-agent:core#> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            'ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; '
            'rdfs:label "Record" .\n'
            'ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ; '
            'rdfs:label "Metric" ; rdfs:domain ex:Record ; '
            "rdfs:range ex:CustomDatatype .\n"
        ),
        format="turtle",
    )

    for shapes_path in _shape_paths(valid_package_dir):
        report = OntologyValidator().validate(data, _graph(shapes_path))
        assert report.conforms is False
        assert any(
            violation.path == "http://www.w3.org/2000/01/rdf-schema#range"
            for violation in report.violations
        )


def test_shacl_contract_rejects_unknown_datatype_in_xsd_namespace(
    valid_package_dir: Path,
) -> None:
    data = Graph().parse(
        data=(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix oa: <urn:ontology-agent:core#> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
            'ex:Record a owl:Class, oa:Concept ; oa:shortName "Record" ; '
            'rdfs:label "Record" .\n'
            'ex:Metric a owl:DatatypeProperty, oa:Property ; oa:shortName "Metric" ; '
            'rdfs:label "Metric" ; rdfs:domain ex:Record ; '
            "rdfs:range xsd:DefinitelyNotAnXsdDatatype .\n"
        ),
        format="turtle",
    )

    for shapes_path in _shape_paths(valid_package_dir):
        report = OntologyValidator().validate(data, _graph(shapes_path))
        assert report.conforms is False
        assert any(
            violation.path == "http://www.w3.org/2000/01/rdf-schema#range"
            for violation in report.violations
        )


def test_missing_label_returns_structured_violation(valid_package_dir: Path) -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is False
    assert len(report.violations) == 1
    assert report.violations[0].focus_node.endswith("Unlabelled")
    assert report.violations[0].message == "Ontology constraint violation"


def test_violation_report_is_stable_for_fresh_graphs(valid_package_dir: Path) -> None:
    reports = []
    for _ in range(2):
        data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
        shapes = _graph(valid_package_dir / "shapes.ttl")
        reports.append(OntologyValidator().validate(data, shapes))

    assert reports[0].model_dump() == reports[1].model_dump()


def test_authored_result_messages_do_not_affect_safe_violation_message() -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = Graph().parse(data=_MULTI_MESSAGE_SHAPES_TTL, format="turtle")

    report = OntologyValidator().validate(data, shapes)

    assert len(report.violations) == 1
    assert report.violations[0].message == "Ontology constraint violation"
    assert "fictional-secret-shacl-message" not in str(report.model_dump())


def test_multi_message_report_is_stable_across_processes() -> None:
    script = (
        "import json\n"
        "from rdflib import Graph\n"
        "from ontology_core.validator import OntologyValidator\n"
        f"data = Graph().parse(data={_UNLABELLED_TTL!r}, format='turtle')\n"
        f"shapes = Graph().parse(data={_MULTI_MESSAGE_SHAPES_TTL!r}, format='turtle')\n"
        "report = OntologyValidator().validate(data, shapes)\n"
        "print(json.dumps(report.model_dump(mode='json'), sort_keys=True))\n"
    )

    outputs = [
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for _ in range(3)
    ]

    assert len(set(outputs)) == 1
    assert json.loads(outputs[0])["violations"][0]["message"] == "Ontology constraint violation"
    assert "fictional-secret-shacl-message" not in outputs[0]


def test_report_conversion_failure_raises_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = Graph().parse(data=_MULTI_MESSAGE_SHAPES_TTL, format="turtle")

    secret = "fictional-secret-report"

    def fail_canonicalization(_graph: Graph):
        raise RuntimeError(secret)

    monkeypatch.setattr("ontology_core.validator.to_canonical_graph", fail_canonicalization)

    with pytest.raises(OntologyParseError) as caught:
        OntologyValidator().validate(data, shapes)
    assert caught.value.details == {
        "error_type": "shacl_report_error",
        "role": "shapes",
    }
    assert secret not in str(caught.value.details)


def test_shacl_execution_failure_does_not_expose_underlying_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = Graph().parse(data=_MULTI_MESSAGE_SHAPES_TTL, format="turtle")
    secret = "fictional-secret-validation"

    def fail_validation(**_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("ontology_core.validator.validate", fail_validation)

    with pytest.raises(OntologyParseError) as caught:
        OntologyValidator().validate(data, shapes)
    assert caught.value.details == {
        "error_type": "shacl_execution_error",
        "role": "shapes",
    }
    assert secret not in str(caught.value.details)
