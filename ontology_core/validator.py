from __future__ import annotations

from pyshacl import validate
from rdflib import BNode, Graph
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF, SH

from ontology_core.errors import OntologyParseError
from ontology_core.models import OntologyViolation, ValidationReport
from ontology_core.parse_diagnostics import safe_parse_details

_SAFE_CONSTRAINT_MESSAGE = "Ontology constraint violation"


def _node_text(value) -> str:
    if isinstance(value, BNode):
        return f"_:{value}"
    return str(value)


def _texts(graph: Graph, subject, predicate) -> tuple[str, ...]:
    return tuple(sorted({_node_text(value) for value in graph.objects(subject, predicate)}))


def _text(graph: Graph, subject, predicate) -> str | None:
    values = _texts(graph, subject, predicate)
    return values[0] if values else None


class OntologyValidator:
    def validate(self, data_graph: Graph, shapes_graph: Graph) -> ValidationReport:
        try:
            conforms, result_graph, _ = validate(
                data_graph=data_graph,
                shacl_graph=shapes_graph,
                inference="rdfs",
                abort_on_first=False,
                allow_infos=False,
                allow_warnings=False,
            )
        except Exception as exc:
            raise OntologyParseError(
                "SHACL 校验执行失败",
                details=safe_parse_details("shacl_execution_error", "shapes"),
            ) from exc

        if not isinstance(result_graph, Graph):
            raise OntologyParseError("SHACL 校验未返回 RDF 报告图")

        try:
            canonical_graph = to_canonical_graph(result_graph)
            violations = []
            for result in canonical_graph.subjects(RDF.type, SH.ValidationResult):
                violations.append(
                    OntologyViolation(
                        focus_node=_text(canonical_graph, result, SH.focusNode),
                        path=_text(canonical_graph, result, SH.resultPath),
                        message=_SAFE_CONSTRAINT_MESSAGE,
                        severity=_text(canonical_graph, result, SH.resultSeverity),
                        source_shape=_text(canonical_graph, result, SH.sourceShape),
                    )
                )
            violations.sort(
                key=lambda item: (
                    item.focus_node or "",
                    item.path or "",
                    item.message,
                    item.severity or "",
                    item.source_shape or "",
                )
            )
            return ValidationReport(conforms=bool(conforms), violations=tuple(violations))
        except Exception as exc:
            raise OntologyParseError(
                "SHACL 校验报告解析失败",
                details=safe_parse_details("shacl_report_error", "shapes"),
            ) from exc
