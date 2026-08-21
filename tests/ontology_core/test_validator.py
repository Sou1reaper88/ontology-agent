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
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "ex:Unlabelled a owl:Class .\n"
)

_MULTI_MESSAGE_SHAPES_TTL = (
    "@prefix ex: <https://example.invalid/ontology/> .\n"
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
    "ex:Shape a sh:NodeShape ;\n"
    "  sh:targetClass owl:Class ;\n"
    "  sh:property [\n"
    "    sh:path rdfs:label ;\n"
    "    sh:minCount 1 ;\n"
    '    sh:message "B" ;\n'
    '    sh:message "A"\n'
    "  ] .\n"
)


def _graph(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


def test_valid_graph_conforms(valid_package_dir: Path) -> None:
    data = _graph(valid_package_dir / "core.ttl")
    data += _graph(valid_package_dir / "domain.ttl")
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is True
    assert report.violations == ()


def test_missing_label_returns_structured_violation(valid_package_dir: Path) -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is False
    assert len(report.violations) == 1
    assert report.violations[0].focus_node.endswith("Unlabelled")
    assert report.violations[0].message == "OWL class requires a label"


def test_violation_report_is_stable_for_fresh_graphs(valid_package_dir: Path) -> None:
    reports = []
    for _ in range(2):
        data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
        shapes = _graph(valid_package_dir / "shapes.ttl")
        reports.append(OntologyValidator().validate(data, shapes))

    assert reports[0].model_dump() == reports[1].model_dump()


def test_multiple_messages_are_combined_deterministically() -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = Graph().parse(data=_MULTI_MESSAGE_SHAPES_TTL, format="turtle")

    report = OntologyValidator().validate(data, shapes)

    assert len(report.violations) == 1
    assert report.violations[0].message == "A | B"


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
    assert json.loads(outputs[0])["violations"][0]["message"] == "A | B"


def test_report_conversion_failure_raises_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Graph().parse(data=_UNLABELLED_TTL, format="turtle")
    shapes = Graph().parse(data=_MULTI_MESSAGE_SHAPES_TTL, format="turtle")

    def fail_canonicalization(_graph: Graph):
        raise RuntimeError("canonicalization failed")

    monkeypatch.setattr("ontology_core.validator.to_canonical_graph", fail_canonicalization)

    with pytest.raises(OntologyParseError) as caught:
        OntologyValidator().validate(data, shapes)
    assert caught.value.details["reason"] == "canonicalization failed"
