from __future__ import annotations

from hashlib import sha256

from pyshacl import validate
from rdflib import Graph
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF, SH

from ontology_core.errors import OntologyParseError
from ontology_core.models import OntologyViolation, ValidationReport
from ontology_core.parse_diagnostics import safe_parse_details

_SAFE_CONSTRAINT_MESSAGE = "Ontology constraint violation"


def _opaque_term(field: str, value) -> str:
    digest = sha256(value.n3().encode("utf-8")).hexdigest()
    return f"urn:ontology-agent:diagnostic:{field}:{digest}"


def _opaque_terms(graph: Graph, subject, predicate, field: str) -> tuple[str, ...]:
    return tuple(
        sorted({_opaque_term(field, value) for value in graph.objects(subject, predicate)})
    )


def _opaque_text(graph: Graph, subject, predicate, field: str) -> str | None:
    values = _opaque_terms(graph, subject, predicate, field)
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
                        focus_node=_opaque_text(
                            canonical_graph, result, SH.focusNode, "focus_node"
                        ),
                        path=_opaque_text(canonical_graph, result, SH.resultPath, "path"),
                        message=_SAFE_CONSTRAINT_MESSAGE,
                        severity=_opaque_text(
                            canonical_graph, result, SH.resultSeverity, "severity"
                        ),
                        source_shape=_opaque_text(
                            canonical_graph, result, SH.sourceShape, "source_shape"
                        ),
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
