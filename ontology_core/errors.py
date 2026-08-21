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
