from __future__ import annotations

from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import RDF, SH

from ontology_core.errors import OntologyParseError
from ontology_core.models import OntologyViolation, ValidationReport


def _text(graph: Graph, subject, predicate) -> str | None:
    value = graph.value(subject, predicate)
    return str(value) if value is not None else None


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
                details={"reason": str(exc)},
            ) from exc

        if not isinstance(result_graph, Graph):
            raise OntologyParseError("SHACL 校验未返回 RDF 报告图")

        violations = []
        for result in result_graph.subjects(RDF.type, SH.ValidationResult):
            violations.append(
                OntologyViolation(
                    focus_node=_text(result_graph, result, SH.focusNode),
                    path=_text(result_graph, result, SH.resultPath),
                    message=_text(result_graph, result, SH.resultMessage)
                    or "Ontology constraint violation",
                    severity=_text(result_graph, result, SH.resultSeverity),
                    source_shape=_text(result_graph, result, SH.sourceShape),
                )
            )
        violations.sort(
            key=lambda item: (
                item.focus_node or "",
                item.path or "",
                item.message,
            )
        )
        return ValidationReport(conforms=bool(conforms), violations=tuple(violations))
