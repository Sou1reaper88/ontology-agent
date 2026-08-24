from __future__ import annotations

from typing import Any, ClassVar


class OntologyError(Exception):
    code: ClassVar[str] = "ontology_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PackageNotFoundError(OntologyError):
    code = "package_not_found"


class OntologyParseError(OntologyError):
    code = "ontology_parse_error"


class OntologyValidationError(OntologyError):
    code = "ontology_validation_error"


class ConceptNotFoundError(OntologyError):
    code = "concept_not_found"


class PropertyNotFoundError(OntologyError):
    code = "property_not_found"


class AmbiguousIdentifierError(OntologyError):
    code = "ambiguous_identifier"


class InvalidRuleExpressionError(OntologyError):
    code = "invalid_rule_expression"


class InvalidOntologyReferenceError(OntologyError):
    code = "invalid_ontology_reference"


class QueryPlanningError(OntologyError):
    code = "query_planning_error"


class NoMatchingConceptError(QueryPlanningError):
    code = "no_matching_concept"


class AmbiguousQueryConceptError(QueryPlanningError):
    code = "ambiguous_query_concept"


class UnsupportedQueryPlanError(QueryPlanningError):
    code = "unsupported_query_plan"


class OntologyCompileError(OntologyError):
    code = "ontology_compile_error"
