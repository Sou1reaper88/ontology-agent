from pathlib import Path

from rdflib import Graph

from ontology_core.validator import OntologyValidator


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
    data = Graph().parse(
        data=(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "ex:Unlabelled a owl:Class .\n"
        ),
        format="turtle",
    )
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is False
    assert len(report.violations) == 1
    assert report.violations[0].focus_node.endswith("Unlabelled")
    assert report.violations[0].message == "OWL class requires a label"
