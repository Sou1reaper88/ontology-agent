from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar
from unicodedata import category, normalize
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import ValidationError
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.term import Identifier

from ontology_core.errors import OntologyValidationError
from ontology_core.normalization import normalize_text
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    RdfLiteral,
    Relation,
    RuleExpression,
    RuleOperator,
    SemanticCatalog,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)
from ontology_core.vocabulary import (
    ALLOW_QUERY_OVERRIDE,
    APPLIES_TO,
    ARGUMENT,
    BUSINESS_RULE,
    CAPABILITY,
    CONCEPT,
    CONDITION,
    CONFIGURATION,
    DATA_SOURCE,
    DATA_SOURCE_REF,
    DEFAULT_STRATEGY,
    DIALECT,
    ENABLED,
    FIELD_NAME,
    JOIN_PATH,
    LEFT_PROPERTY,
    OA,
    OBJECT_NAME,
    PARAMETER,
    PARTITION_GRAIN,
    PARTITION_PROPERTY,
    PHYSICAL_MAPPING,
    PHYSICAL_NAMESPACE,
    PLATFORM_TYPE,
    PRIORITY,
    PROPERTY,
    RELATION,
    SEMANTIC_ELEMENT,
    SHORT_NAME,
    STATUS,
    TEMPORAL_PARTITION_POLICY,
    USES_PROPERTY,
    USES_RELATION,
    VALUE,
    VALUES,
)

_Element = TypeVar("_Element")
_MARKERS = (
    CONCEPT,
    PROPERTY,
    RELATION,
    BUSINESS_RULE,
    DATA_SOURCE,
    PHYSICAL_MAPPING,
    TEMPORAL_PARTITION_POLICY,
)
_STANDARD_TYPES = {
    CONCEPT: OWL.Class,
    PROPERTY: OWL.DatatypeProperty,
    RELATION: OWL.ObjectProperty,
}
_OPERATOR_TYPES = {
    OA.AllOf: RuleOperator.ALL_OF,
    OA.AnyOf: RuleOperator.ANY_OF,
    OA.Not: RuleOperator.NOT,
    OA.Eq: RuleOperator.EQ,
    OA.Ne: RuleOperator.NE,
    OA.Gt: RuleOperator.GT,
    OA.Gte: RuleOperator.GTE,
    OA.Lt: RuleOperator.LT,
    OA.Lte: RuleOperator.LTE,
    OA.In: RuleOperator.IN,
    OA.Between: RuleOperator.BETWEEN,
    OA.IsNull: RuleOperator.IS_NULL,
}
_STRUCTURAL_PREDICATES = frozenset({ARGUMENT, LEFT_PROPERTY, VALUE, VALUES, PARAMETER})
_LOGICAL_OPERATORS = frozenset({RuleOperator.ALL_OF, RuleOperator.ANY_OF, RuleOperator.NOT})
_COLLECTION_OPERATORS = frozenset({RuleOperator.IN, RuleOperator.BETWEEN})
_XSD_BUILTIN_LOCAL_NAMES = frozenset(
    {
        "ENTITIES",
        "ENTITY",
        "ID",
        "IDREF",
        "IDREFS",
        "NCName",
        "NMTOKEN",
        "NMTOKENS",
        "NOTATION",
        "Name",
        "QName",
        "anyURI",
        "base64Binary",
        "boolean",
        "byte",
        "date",
        "dateTime",
        "dateTimeStamp",
        "dayTimeDuration",
        "decimal",
        "double",
        "duration",
        "float",
        "gDay",
        "gMonth",
        "gMonthDay",
        "gYear",
        "gYearMonth",
        "hexBinary",
        "int",
        "integer",
        "language",
        "long",
        "negativeInteger",
        "nonNegativeInteger",
        "nonPositiveInteger",
        "normalizedString",
        "positiveInteger",
        "short",
        "string",
        "time",
        "token",
        "unsignedByte",
        "unsignedInt",
        "unsignedLong",
        "unsignedShort",
        "yearMonthDuration",
    }
)
_XSD_BUILTIN_DATATYPE_URIS = frozenset(
    f"{XSD}{local_name}" for local_name in _XSD_BUILTIN_LOCAL_NAMES
)
_CREDENTIAL_NAMES = {
    "host",
    "port",
    "username",
    "password",
    "token",
    "secret",
    "connectionstring",
}
_URI_SEGMENT_SEPARATOR = re.compile(r"[/#:]+")
_URN_NID_AND_NSS = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{1,31}:.+")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_INVALID_SEMANTIC_ELEMENT_URI = "urn:ontology-agent:invalid-semantic-element"
_CREDENTIAL_DIAGNOSTIC_URI = "urn:ontology-agent:diagnostic:credential-configuration"

MAX_RULE_EXPRESSION_DEPTH = 64
MAX_RULE_EXPRESSION_NODES = 1024
MAX_RULE_COLLECTION_ITEMS = 1024
MAX_RULE_LOGICAL_ARGUMENT_EDGES = 4096
MAX_CREDENTIAL_SCAN_NODES = 1024
MAX_CREDENTIAL_SCAN_EDGES = 4096
MAX_CREDENTIAL_PERCENT_DECODE_ROUNDS = 4


@dataclass
class _ExpressionParseContext:
    property_uris: set[str]
    active: set[Identifier] = field(default_factory=set)
    completed: dict[Identifier, RuleExpression] = field(default_factory=dict)
    canonical_keys: dict[Identifier, tuple[object, ...]] = field(default_factory=dict)
    nodes: set[Identifier] = field(default_factory=set)
    logical_argument_edges: int = 0


class _InvalidReferenceError(ValueError):
    def __init__(self, message: str, path: URIRef) -> None:
        super().__init__(message)
        self.path = path


class _InvalidReferencesError(ValueError):
    def __init__(self, errors: tuple[_InvalidReferenceError, ...]) -> None:
        super().__init__("Invalid semantic references")
        self.errors = errors


@dataclass(frozen=True)
class _RuleExpressionIssue:
    code: str
    path: URIRef
    message: str


class _RuleExpressionIssuesError(ValueError):
    def __init__(self, issues: tuple[_RuleExpressionIssue, ...]) -> None:
        super().__init__("Invalid rule expression children")
        self.issues = tuple(
            sorted(issues, key=lambda item: (item.code, str(item.path), item.message))
        )


class _CredentialDecodeBudgetError(ValueError):
    pass


def _is_stable_semantic_uri(value: URIRef) -> bool:
    text = str(value)
    if any(character.isspace() or category(character).startswith("C") for character in text):
        return False
    if _INVALID_PERCENT_ESCAPE.search(text):
        return False
    if "?" in text.partition("#")[0]:
        return False
    try:
        parts = urlsplit(text)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        return False
    scheme = parts.scheme.casefold()
    if not scheme or scheme == "file":
        return False
    if scheme in {"http", "https"}:
        return bool(parts.netloc and hostname and parts.username is None and parts.password is None)
    if scheme == "urn":
        return bool(_URN_NID_AND_NSS.fullmatch(parts.path))
    scheme_specific = text.partition(":")[2].partition("#")[0]
    return bool(scheme_specific)


def _reference_text(value: Identifier, predicate: URIRef) -> str:
    if not isinstance(value, URIRef):
        raise _InvalidReferenceError("Semantic reference object must be an IRI", predicate)
    if not _is_stable_semantic_uri(value):
        raise _InvalidReferenceError(
            "Semantic reference must use an absolute non-file URI",
            predicate,
        )
    return str(value)


def _uris(
    graph: Graph,
    subject: Identifier,
    predicate: URIRef,
    *,
    uri: str,
    violations: list[dict[str, str]],
) -> tuple[str, ...]:
    references: set[str] = set()
    for value in graph.objects(subject, predicate):
        try:
            references.add(_reference_text(value, predicate))
        except _InvalidReferenceError as exc:
            violations.append(_violation("invalid_ontology_reference", uri, exc.path, str(exc)))
    return tuple(sorted(references))


def _single_uri(graph: Graph, subject: Identifier, predicate: URIRef, field: str) -> str:
    values = tuple(graph.objects(subject, predicate))
    references: list[str] = []
    errors: list[_InvalidReferenceError] = []
    for value in values:
        try:
            references.append(_reference_text(value, predicate))
        except _InvalidReferenceError as exc:
            errors.append(exc)
    if errors:
        raise _InvalidReferencesError(tuple(errors))
    if len(values) != 1:
        raise ValueError(f"Marked semantic element requires exactly one {field}")
    return references[0]


def _single_literal(graph: Graph, subject: Identifier, predicate: URIRef, field: str) -> Literal:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], Literal):
        raise ValueError(f"Marked semantic element requires exactly one literal {field}")
    return values[0]


def _optional_literal(
    graph: Graph, subject: Identifier, predicate: URIRef, field: str
) -> str | None:
    values = tuple(graph.objects(subject, predicate))
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], Literal):
        raise ValueError(f"Marked semantic element requires at most one literal {field}")
    return str(values[0])


def _texts(graph: Graph, subject: Identifier, predicate: URIRef) -> tuple[LocalizedText, ...]:
    texts = {
        (value.language or "", str(value)): LocalizedText(
            value=str(value), language=value.language or None
        )
        for value in graph.objects(subject, predicate)
        if isinstance(value, Literal) and str(value)
    }
    return tuple(texts[key] for key in sorted(texts))


def _preferred_text(texts: tuple[LocalizedText, ...]) -> str:
    if not texts:
        raise ValueError("Marked semantic element requires at least one label")
    chinese = [
        text for text in texts if text.language and text.language.casefold().startswith("zh")
    ]

    def stable_key(text: LocalizedText) -> tuple[str, str, str, str]:
        language = text.language or ""
        return normalize_text(text.value), text.value, normalize_text(language), language

    if chinese:
        return min(chinese, key=stable_key).value
    untagged = [text for text in texts if text.language is None]
    if untagged:
        return min(untagged, key=stable_key).value
    return min(texts, key=stable_key).value


def _single_short_name(graph: Graph, subject: Identifier) -> str:
    values = tuple(graph.objects(subject, SHORT_NAME))
    if len(values) != 1 or not isinstance(values[0], Literal) or not str(values[0]):
        raise ValueError("Marked semantic element requires exactly one short name")
    return str(values[0])


def _description(graph: Graph, subject: Identifier) -> str | None:
    texts = _texts(graph, subject, RDFS.comment)
    return _preferred_text(texts) if texts else None


def _literal(value: Literal) -> RdfLiteral:
    return RdfLiteral(
        lexical_form=str(value),
        datatype_uri=str(value.datatype) if value.datatype else None,
        language=value.language or None,
    )


def _violation(code: str, uri: str, path: URIRef, message: str) -> dict[str, str]:
    return {"code": code, "uri": uri, "path": str(path), "message": message}


def _invalid_subject_violations(graph: Graph) -> tuple[set[URIRef], list[dict[str, str]]]:
    subjects: set[URIRef] = set()
    violations: list[dict[str, str]] = []
    for marker in _MARKERS:
        for subject in graph.subjects(RDF.type, marker):
            if isinstance(subject, URIRef):
                if _is_stable_semantic_uri(subject):
                    subjects.add(subject)
                else:
                    violations.append(
                        _violation(
                            "invalid_semantic_uri",
                            _INVALID_SEMANTIC_ELEMENT_URI,
                            RDF.type,
                            "Marked semantic element requires an absolute non-file URI",
                        )
                    )
            else:
                violations.append(
                    _violation(
                        "invalid_subject",
                        str(subject),
                        RDF.type,
                        "Marked semantic element subject must be a URI",
                    )
                )
    return subjects, violations


def _capture(
    action: Callable[[], _Element],
    *,
    violations: list[dict[str, str]],
    code: str,
    uri: str,
    path: URIRef,
) -> _Element | None:
    try:
        return action()
    except _InvalidReferencesError as exc:
        for error in exc.errors:
            violations.append(_violation("invalid_ontology_reference", uri, error.path, str(error)))
        return None
    except _InvalidReferenceError as exc:
        violations.append(_violation("invalid_ontology_reference", uri, exc.path, str(exc)))
        return None
    except ValueError as exc:
        violations.append(_violation(code, uri, path, str(exc)))
        return None


def _element_fields(
    graph: Graph, subject: URIRef, violations: list[dict[str, str]]
) -> tuple[str, str, tuple[LocalizedText, ...], str | None] | None:
    uri = str(subject)
    short_name = _capture(
        lambda: _single_short_name(graph, subject),
        violations=violations,
        code="missing_short_name",
        uri=uri,
        path=SHORT_NAME,
    )
    labels = _texts(graph, subject, RDFS.label)
    label = _capture(
        lambda: _preferred_text(labels),
        violations=violations,
        code="missing_label",
        uri=uri,
        path=RDFS.label,
    )
    if short_name is None or label is None:
        return None
    return short_name, label, labels, _description(graph, subject)


def _validate_short_name(*, short_name: str, uri: str, violations: list[dict[str, str]]) -> bool:
    try:
        Concept(uri=uri, short_name=short_name, label="Valid", labels=())
    except ValidationError as exc:
        violations.append(_violation("invalid_short_name", uri, SHORT_NAME, exc.errors()[0]["msg"]))
        return False
    return True


def _valid_short_names(graph: Graph, subjects: set[URIRef]) -> dict[str, list[str]]:
    short_names: dict[str, list[str]] = defaultdict(list)
    for subject in sorted(subjects, key=str):
        uri = str(subject)
        try:
            short_name = _single_short_name(graph, subject)
        except ValueError:
            continue
        short_names[normalize_text(short_name)].append(uri)
    return short_names


def _validate_standard_types(
    graph: Graph,
    by_marker: dict[URIRef, list[URIRef]],
    violations: list[dict[str, str]],
) -> None:
    for marker, required_type in _STANDARD_TYPES.items():
        for subject in by_marker[marker]:
            if (subject, RDF.type, required_type) not in graph:
                violations.append(
                    _violation(
                        "missing_standard_type",
                        str(subject),
                        RDF.type,
                        f"Marked semantic element requires RDF type {required_type}",
                    )
                )


def _parent_uris(
    graph: Graph, subject: URIRef, violations: list[dict[str, str]]
) -> tuple[str, ...]:
    uri = str(subject)
    parents: list[str] = []
    for value in graph.objects(subject, RDFS.subClassOf):
        try:
            parents.append(_reference_text(value, RDFS.subClassOf))
        except _InvalidReferenceError as exc:
            violations.append(
                _violation(
                    "invalid_ontology_reference",
                    uri,
                    exc.path,
                    str(exc),
                )
            )
    return tuple(sorted(set(parents)))


def _validate_reference(
    *,
    uri: str,
    reference: str | None,
    path: URIRef,
    known: set[str],
    violations: list[dict[str, str]],
) -> None:
    if reference is None or reference in known:
        return
    violations.append(
        _violation(
            "invalid_ontology_reference",
            uri,
            path,
            f"Referenced semantic element does not exist: {reference}",
        )
    )


def _validate_concept_reference(
    *,
    uri: str,
    concept_uri: str | None,
    path: URIRef,
    marked_concept_uris: set[str],
    violations: list[dict[str, str]],
) -> None:
    if concept_uri is None or concept_uri in marked_concept_uris:
        return
    violations.append(
        _violation(
            "dangling_concept_reference",
            uri,
            path,
            f"Referenced concept does not exist: {concept_uri}",
        )
    )


def _raise_if_invalid(violations: list[dict[str, str]]) -> None:
    if not violations:
        return
    violations.sort(key=lambda item: (item["code"], item["uri"], item["path"], item["message"]))
    raise OntologyValidationError(
        "Semantic catalog validation failed", details={"violations": violations}
    )


def _sort_key(
    item: Concept | Property | Relation | BusinessRule | DataSource | PhysicalMapping,
) -> tuple[str, str]:
    return normalize_text(item.short_name), item.uri


def _collection_literals(
    graph: Graph,
    head: Identifier,
    *,
    minimum: int,
    exact: int | None = None,
) -> tuple[RdfLiteral, ...]:
    values: list[RdfLiteral] = []
    seen: set[Identifier] = set()
    current = head
    while current != RDF.nil:
        if len(values) >= MAX_RULE_COLLECTION_ITEMS:
            raise ValueError(
                f"RDF Collection exceeds maximum item count of {MAX_RULE_COLLECTION_ITEMS}"
            )
        if not isinstance(current, (URIRef, BNode)) or current in seen:
            raise ValueError("RDF Collection contains a cycle or malformed tail")
        seen.add(current)
        first_values = tuple(graph.objects(current, RDF.first))
        rest_values = tuple(graph.objects(current, RDF.rest))
        if (
            len(first_values) != 1
            or len(rest_values) != 1
            or not isinstance(first_values[0], Literal)
        ):
            raise ValueError("RDF Collection requires one literal rdf:first and one rdf:rest")
        values.append(_literal(first_values[0]))
        current = rest_values[0]
    if len(values) < minimum or (exact is not None and len(values) != exact):
        if exact is not None:
            raise ValueError(f"RDF Collection requires exactly {exact} literals")
        raise ValueError(f"RDF Collection requires at least {minimum} literals")
    return tuple(values)


def _validate_expression_structure(
    graph: Graph,
    node: Identifier,
    operator: RuleOperator,
) -> None:
    if operator in _LOGICAL_OPERATORS:
        allowed = {ARGUMENT}
    elif operator is RuleOperator.IS_NULL:
        allowed = {LEFT_PROPERTY}
    elif operator in _COLLECTION_OPERATORS:
        allowed = {LEFT_PROPERTY, VALUES}
    else:
        allowed = {LEFT_PROPERTY, VALUE, PARAMETER}
    supplied = {
        predicate
        for predicate in _STRUCTURAL_PREDICATES
        if next(graph.objects(node, predicate), None) is not None
    }
    extras = sorted(str(predicate) for predicate in supplied - allowed)
    if extras:
        raise ValueError(
            f"{operator.value} does not allow structural predicates: {', '.join(extras)}"
        )


def _expression_key(
    expression: RuleExpression,
    child_keys: tuple[tuple[object, ...], ...] = (),
) -> tuple[object, ...]:
    literal_keys = tuple(
        (
            value.lexical_form,
            value.datatype_uri or "",
            value.language or "",
        )
        for value in expression.values
    )
    return (
        expression.operator.value,
        expression.property_uri or "",
        literal_keys,
        expression.parameter or "",
        child_keys,
    )


def _parse_expression(
    graph: Graph,
    node: Identifier,
    context: _ExpressionParseContext,
    *,
    depth: int,
) -> RuleExpression:
    if depth > MAX_RULE_EXPRESSION_DEPTH:
        raise ValueError(f"Rule expression exceeds maximum depth of {MAX_RULE_EXPRESSION_DEPTH}")
    if node in context.active:
        raise ValueError("Rule expression contains a recursive condition cycle")
    completed = context.completed.get(node)
    if completed is not None:
        return completed
    if node not in context.nodes:
        if len(context.nodes) >= MAX_RULE_EXPRESSION_NODES:
            raise ValueError(
                f"Rule expression exceeds maximum node count of {MAX_RULE_EXPRESSION_NODES}"
            )
        context.nodes.add(node)
    operators = [
        operator
        for rdf_type, operator in _OPERATOR_TYPES.items()
        if (node, RDF.type, rdf_type) in graph
    ]
    if len(operators) != 1:
        raise ValueError("Rule expression requires exactly one operator type")
    operator = operators[0]
    _validate_expression_structure(graph, node, operator)
    context.active.add(node)
    child_keys: tuple[tuple[object, ...], ...] = ()
    try:
        if operator in (RuleOperator.ALL_OF, RuleOperator.ANY_OF, RuleOperator.NOT):
            arguments = tuple(graph.objects(node, ARGUMENT))
            if operator is RuleOperator.NOT:
                valid_count = len(arguments) == 1
                count_text = "exactly one"
            else:
                valid_count = len(arguments) >= 2
                count_text = "at least two"
            if not valid_count:
                raise ValueError(f"{operator.value} requires {count_text} arguments")
            if context.logical_argument_edges + len(arguments) > MAX_RULE_LOGICAL_ARGUMENT_EDGES:
                raise ValueError(
                    "Rule expression exceeds maximum logical argument edge count of "
                    f"{MAX_RULE_LOGICAL_ARGUMENT_EDGES}"
                )
            context.logical_argument_edges += len(arguments)
            child_entries: list[tuple[Identifier, RuleExpression]] = []
            child_issues: list[_RuleExpressionIssue] = []
            for argument in arguments:
                try:
                    child_entries.append(
                        (
                            argument,
                            _parse_expression(graph, argument, context, depth=depth + 1),
                        )
                    )
                except _RuleExpressionIssuesError as exc:
                    child_issues.extend(exc.issues)
                except _InvalidReferencesError as exc:
                    child_issues.extend(
                        _RuleExpressionIssue(
                            "invalid_ontology_reference",
                            error.path,
                            str(error),
                        )
                        for error in exc.errors
                    )
                except _InvalidReferenceError as exc:
                    child_issues.append(
                        _RuleExpressionIssue(
                            "invalid_ontology_reference",
                            exc.path,
                            str(exc),
                        )
                    )
                except ValueError as exc:
                    child_issues.append(
                        _RuleExpressionIssue(
                            "invalid_rule_expression",
                            CONDITION,
                            str(exc),
                        )
                    )
            if child_issues:
                raise _RuleExpressionIssuesError(tuple(child_issues))
            if operator is not RuleOperator.NOT:
                child_entries.sort(key=lambda item: context.canonical_keys[item[0]])
            children = tuple(expression for _, expression in child_entries)
            child_keys = tuple(context.canonical_keys[argument] for argument, _ in child_entries)
            expression = RuleExpression(operator=operator, children=children)
        else:
            property_uri = _single_uri(graph, node, LEFT_PROPERTY, "left property")
            if property_uri not in context.property_uris:
                raise ValueError(f"Referenced property does not exist: {property_uri}")
            if operator is RuleOperator.IS_NULL:
                if any(
                    tuple(graph.objects(node, predicate))
                    for predicate in (VALUE, VALUES, PARAMETER)
                ):
                    raise ValueError("is_null does not accept a value or parameter")
                expression = RuleExpression(operator=operator, property_uri=property_uri)
            elif operator in (RuleOperator.BETWEEN, RuleOperator.IN):
                heads = tuple(graph.objects(node, VALUES))
                if len(heads) != 1:
                    raise ValueError("Rule expression requires exactly one RDF Collection values")
                expression = RuleExpression(
                    operator=operator,
                    property_uri=property_uri,
                    values=_collection_literals(
                        graph,
                        heads[0],
                        minimum=1 if operator is RuleOperator.IN else 2,
                        exact=2 if operator is RuleOperator.BETWEEN else None,
                    ),
                )
            else:
                literal_values = tuple(graph.objects(node, VALUE))
                parameters = tuple(graph.objects(node, PARAMETER))
                if (
                    len(literal_values) == 1
                    and isinstance(literal_values[0], Literal)
                    and not parameters
                ):
                    expression = RuleExpression(
                        operator=operator,
                        property_uri=property_uri,
                        values=(_literal(literal_values[0]),),
                    )
                elif (
                    len(parameters) == 1
                    and isinstance(parameters[0], Literal)
                    and not literal_values
                ):
                    expression = RuleExpression(
                        operator=operator,
                        property_uri=property_uri,
                        parameter=str(parameters[0]),
                    )
                else:
                    raise ValueError("Comparison requires exactly one literal value or parameter")
    finally:
        context.active.remove(node)
    context.completed[node] = expression
    context.canonical_keys[node] = _expression_key(expression, child_keys)
    return expression


def _scan_forbidden_credentials(
    graph: Graph,
    roots: tuple[URIRef, ...],
    violations: list[dict[str, str]],
    marked_semantic_nodes: set[Identifier],
) -> None:
    visited: set[Identifier] = set()
    pending = deque(roots)
    queued: set[Identifier] = set(roots)
    edge_count = 0
    credential_found = False
    while pending:
        node = pending.popleft()
        queued.discard(node)
        if node in visited:
            continue
        if len(visited) >= MAX_CREDENTIAL_SCAN_NODES:
            violations.append(
                _violation(
                    "credential_scan_budget_exceeded",
                    _CREDENTIAL_DIAGNOSTIC_URI,
                    CONFIGURATION,
                    "Credential configuration scan exceeded its resource budget",
                )
            )
            return
        visited.add(node)
        edges = sorted(
            graph.predicate_objects(node),
            key=lambda item: (str(item[0]), type(item[1]).__name__, str(item[1])),
        )
        for predicate, value in edges:
            edge_count += 1
            if edge_count > MAX_CREDENTIAL_SCAN_EDGES:
                violations.append(
                    _violation(
                        "credential_scan_budget_exceeded",
                        _CREDENTIAL_DIAGNOSTIC_URI,
                        CONFIGURATION,
                        "Credential configuration scan exceeded its resource budget",
                    )
                )
                return
            try:
                forbidden = _normalized_predicate_local_name(predicate) in _CREDENTIAL_NAMES
            except ValueError:
                forbidden = True
            if forbidden:
                credential_found = True
            if predicate == RDF.type:
                continue
            if predicate != CONFIGURATION and value in marked_semantic_nodes:
                continue
            if (
                (
                    isinstance(value, BNode)
                    or (
                        isinstance(value, URIRef)
                        and next(graph.predicate_objects(value), None) is not None
                    )
                )
                and value not in visited
                and value not in queued
            ):
                pending.append(value)
                queued.add(value)
    if credential_found:
        violations.append(
            _violation(
                "forbidden_credential_predicate",
                _CREDENTIAL_DIAGNOSTIC_URI,
                CONFIGURATION,
                "Credential-like predicates are prohibited",
            )
        )


def _bounded_percent_decode(value: str) -> str:
    current = value
    for _ in range(MAX_CREDENTIAL_PERCENT_DECODE_ROUNDS):
        decoded = unquote(current)
        if decoded == current:
            return current
        current = decoded
    if unquote(current) != current:
        raise _CredentialDecodeBudgetError("Credential predicate decode budget exceeded")
    return current


def _normalized_predicate_local_name(predicate: URIRef) -> str:
    """Return a normalized final non-empty segment for any URI scheme."""
    parsed_uri = urlsplit(str(predicate))
    encoded_source = (
        parsed_uri.fragment
        if parsed_uri.fragment
        else urlunsplit((parsed_uri.scheme, parsed_uri.netloc, parsed_uri.path, "", ""))
    )
    decoded_source = _bounded_percent_decode(encoded_source)
    normalized_source = normalize("NFKC", decoded_source)
    parsed_source = urlsplit(normalized_source)
    local_source = parsed_source.fragment if parsed_source.fragment else parsed_source.path
    segments = [
        segment.strip() for segment in _URI_SEGMENT_SEPARATOR.split(local_source) if segment.strip()
    ]
    local_name = segments[-1] if segments else ""
    return local_name.strip().replace("-", "").replace("_", "").casefold()


def parse_catalog(graph: Graph) -> SemanticCatalog:
    """Parse marked semantic elements or raise one aggregated validation error."""
    subjects, violations = _invalid_subject_violations(graph)
    marked_semantic_nodes = {
        subject for marker in _MARKERS for subject in graph.subjects(RDF.type, marker)
    }
    by_marker = {
        marker: sorted(
            (subject for subject in subjects if (subject, RDF.type, marker) in graph), key=str
        )
        for marker in _MARKERS
    }
    concept_subjects = by_marker[CONCEPT]
    property_subjects = by_marker[PROPERTY]
    relation_subjects = by_marker[RELATION]
    rule_subjects = by_marker[BUSINESS_RULE]
    source_subjects = by_marker[DATA_SOURCE]
    mapping_subjects = by_marker[PHYSICAL_MAPPING]
    temporal_policy_subjects = by_marker[TEMPORAL_PARTITION_POLICY]
    credential_roots = tuple(sorted(set(source_subjects) | set(mapping_subjects), key=str))
    _scan_forbidden_credentials(
        graph,
        credential_roots,
        violations,
        marked_semantic_nodes,
    )
    _validate_standard_types(graph, by_marker, violations)
    marked_concept_uris = {str(subject) for subject in concept_subjects}
    marked_property_uris = {str(subject) for subject in property_subjects}
    marked_relation_uris = {str(subject) for subject in relation_subjects}
    marked_source_uris = {str(subject) for subject in source_subjects}
    short_names = _valid_short_names(graph, subjects)

    concept_data: list[
        tuple[str, str, str, tuple[LocalizedText, ...], str | None, tuple[str, ...]]
    ] = []
    for subject in concept_subjects:
        uri = str(subject)
        parents = _parent_uris(graph, subject, violations)
        for parent in parents:
            _validate_concept_reference(
                uri=uri,
                concept_uri=parent,
                path=RDFS.subClassOf,
                marked_concept_uris=marked_concept_uris,
                violations=violations,
            )
        fields = _element_fields(graph, subject, violations)
        if fields and _validate_short_name(short_name=fields[0], uri=uri, violations=violations):
            concept_data.append((uri, *fields, parents))

    property_data: list[tuple[str, str, str, tuple[LocalizedText, ...], str | None, str, str]] = []
    for subject in property_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        domain = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.domain, "domain"),
            violations=violations,
            code="missing_domain",
            uri=uri,
            path=RDFS.domain,
        )
        value_range = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.range, "range"),
            violations=violations,
            code="missing_range",
            uri=uri,
            path=RDFS.range,
        )
        _validate_concept_reference(
            uri=uri,
            concept_uri=domain,
            path=RDFS.domain,
            marked_concept_uris=marked_concept_uris,
            violations=violations,
        )
        if value_range is not None and value_range not in _XSD_BUILTIN_DATATYPE_URIS:
            violations.append(
                _violation(
                    "invalid_datatype_range",
                    uri,
                    RDFS.range,
                    "Property range must be an XSD datatype URI",
                )
            )
        if (
            fields
            and domain
            and value_range
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            property_data.append((uri, *fields, domain, value_range))

    relation_data: list[tuple[str, str, str, tuple[LocalizedText, ...], str | None, str, str]] = []
    for subject in relation_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        source = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.domain, "domain"),
            violations=violations,
            code="missing_domain",
            uri=uri,
            path=RDFS.domain,
        )
        target = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.range, "range"),
            violations=violations,
            code="missing_range",
            uri=uri,
            path=RDFS.range,
        )
        _validate_concept_reference(
            uri=uri,
            concept_uri=source,
            path=RDFS.domain,
            marked_concept_uris=marked_concept_uris,
            violations=violations,
        )
        _validate_concept_reference(
            uri=uri,
            concept_uri=target,
            path=RDFS.range,
            marked_concept_uris=marked_concept_uris,
            violations=violations,
        )
        if (
            fields
            and source
            and target
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            relation_data.append((uri, *fields, source, target))

    source_data: list[
        tuple[
            str, str, str, tuple[LocalizedText, ...], str | None, str, str | None, tuple[str, ...]
        ]
    ] = []
    for subject in source_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        platform_type = _capture(
            lambda subject=subject: str(
                _single_literal(graph, subject, PLATFORM_TYPE, "platform type")
            ),
            violations=violations,
            code="missing_platform_type",
            uri=uri,
            path=PLATFORM_TYPE,
        )
        dialect = _capture(
            lambda subject=subject: _optional_literal(graph, subject, DIALECT, "dialect"),
            violations=violations,
            code="invalid_dialect",
            uri=uri,
            path=DIALECT,
        )
        capabilities = tuple(
            sorted(
                {
                    str(value)
                    for value in graph.objects(subject, CAPABILITY)
                    if isinstance(value, Literal)
                }
            )
        )
        if (
            fields
            and platform_type
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            source_data.append((uri, *fields, platform_type, dialect, capabilities))

    rule_data: list[
        tuple[
            str,
            str,
            str,
            tuple[LocalizedText, ...],
            str | None,
            str,
            tuple[str, ...],
            tuple[str, ...],
            RuleExpression | None,
            str,
            int,
        ]
    ] = []
    for subject in rule_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        applies_to = _capture(
            lambda subject=subject: _single_uri(graph, subject, APPLIES_TO, "applies to"),
            violations=violations,
            code="missing_applies_to",
            uri=uri,
            path=APPLIES_TO,
        )
        _validate_concept_reference(
            uri=uri,
            concept_uri=applies_to,
            path=APPLIES_TO,
            marked_concept_uris=marked_concept_uris,
            violations=violations,
        )
        property_refs = _uris(
            graph,
            subject,
            USES_PROPERTY,
            uri=uri,
            violations=violations,
        )
        relation_refs = _uris(
            graph,
            subject,
            USES_RELATION,
            uri=uri,
            violations=violations,
        )
        for reference in property_refs:
            _validate_reference(
                uri=uri,
                reference=reference,
                path=USES_PROPERTY,
                known=marked_property_uris,
                violations=violations,
            )
        for reference in relation_refs:
            _validate_reference(
                uri=uri,
                reference=reference,
                path=USES_RELATION,
                known=marked_relation_uris,
                violations=violations,
            )
        condition: RuleExpression | None = None
        nodes = tuple(graph.objects(subject, CONDITION))
        if len(nodes) > 1:
            violations.append(
                _violation(
                    "invalid_rule_expression",
                    uri,
                    CONDITION,
                    "Business rule has more than one condition",
                )
            )
        elif nodes:
            try:
                condition = _parse_expression(
                    graph,
                    nodes[0],
                    _ExpressionParseContext(marked_property_uris),
                    depth=1,
                )
            except _RuleExpressionIssuesError as exc:
                for issue in exc.issues:
                    violations.append(
                        _violation(
                            issue.code,
                            uri,
                            issue.path,
                            issue.message,
                        )
                    )
            except _InvalidReferencesError as exc:
                for error in exc.errors:
                    violations.append(
                        _violation(
                            "invalid_ontology_reference",
                            uri,
                            error.path,
                            str(error),
                        )
                    )
            except _InvalidReferenceError as exc:
                violations.append(_violation("invalid_ontology_reference", uri, exc.path, str(exc)))
            except ValueError as exc:
                violations.append(_violation("invalid_rule_expression", uri, CONDITION, str(exc)))
        status = _capture(
            lambda subject=subject: _optional_literal(graph, subject, STATUS, "status") or "active",
            violations=violations,
            code="invalid_status",
            uri=uri,
            path=STATUS,
        )
        priority_text = _capture(
            lambda subject=subject: _optional_literal(graph, subject, PRIORITY, "priority") or "0",
            violations=violations,
            code="invalid_priority",
            uri=uri,
            path=PRIORITY,
        )
        try:
            priority = int(priority_text) if priority_text is not None else 0
        except ValueError:
            violations.append(
                _violation("invalid_priority", uri, PRIORITY, "Priority must be an integer")
            )
            priority = 0
        if (
            fields
            and applies_to
            and status is not None
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            rule_data.append(
                (
                    uri,
                    *fields,
                    applies_to,
                    property_refs,
                    relation_refs,
                    condition,
                    status,
                    priority,
                )
            )

    property_domains = {uri: domain for uri, _, _, _, _, domain, _ in property_data}
    temporal_policy_data: list[
        tuple[
            str,
            str,
            str,
            tuple[LocalizedText, ...],
            str | None,
            str,
            str,
            TemporalGrain,
            TemporalDefaultStrategy,
            bool,
            str,
            int,
        ]
    ] = []
    for subject in temporal_policy_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        applies_to = _capture(
            lambda subject=subject: _single_uri(graph, subject, APPLIES_TO, "applies to"),
            violations=violations,
            code="missing_applies_to",
            uri=uri,
            path=APPLIES_TO,
        )
        partition_property = _capture(
            lambda subject=subject: _single_uri(
                graph, subject, PARTITION_PROPERTY, "partition property"
            ),
            violations=violations,
            code="missing_partition_property",
            uri=uri,
            path=PARTITION_PROPERTY,
        )
        grain_text = _capture(
            lambda subject=subject: str(
                _single_literal(graph, subject, PARTITION_GRAIN, "partition grain")
            ),
            violations=violations,
            code="invalid_partition_grain",
            uri=uri,
            path=PARTITION_GRAIN,
        )
        strategy_text = _capture(
            lambda subject=subject: str(
                _single_literal(graph, subject, DEFAULT_STRATEGY, "default strategy")
            ),
            violations=violations,
            code="invalid_temporal_strategy",
            uri=uri,
            path=DEFAULT_STRATEGY,
        )
        override_text = _capture(
            lambda subject=subject: str(
                _single_literal(graph, subject, ALLOW_QUERY_OVERRIDE, "allow query override")
            ),
            violations=violations,
            code="invalid_query_override",
            uri=uri,
            path=ALLOW_QUERY_OVERRIDE,
        )
        status = _capture(
            lambda subject=subject: _optional_literal(graph, subject, STATUS, "status") or "active",
            violations=violations,
            code="invalid_status",
            uri=uri,
            path=STATUS,
        )
        priority_text = _capture(
            lambda subject=subject: _optional_literal(graph, subject, PRIORITY, "priority") or "0",
            violations=violations,
            code="invalid_priority",
            uri=uri,
            path=PRIORITY,
        )
        _validate_concept_reference(
            uri=uri,
            concept_uri=applies_to,
            path=APPLIES_TO,
            marked_concept_uris=marked_concept_uris,
            violations=violations,
        )
        _validate_reference(
            uri=uri,
            reference=partition_property,
            path=PARTITION_PROPERTY,
            known=marked_property_uris,
            violations=violations,
        )
        if (
            applies_to is not None
            and partition_property is not None
            and property_domains.get(partition_property) != applies_to
        ):
            violations.append(
                _violation(
                    "invalid_temporal_property",
                    uri,
                    PARTITION_PROPERTY,
                    "Partition property must belong to the policy concept",
                )
            )
        try:
            grain = TemporalGrain(grain_text) if grain_text is not None else None
        except ValueError:
            violations.append(
                _violation("invalid_partition_grain", uri, PARTITION_GRAIN, "Invalid grain")
            )
            grain = None
        try:
            strategy = TemporalDefaultStrategy(strategy_text) if strategy_text is not None else None
        except ValueError:
            violations.append(
                _violation("invalid_temporal_strategy", uri, DEFAULT_STRATEGY, "Invalid strategy")
            )
            strategy = None
        valid_pairs = {
            (TemporalGrain.DAY, TemporalDefaultStrategy.T_MINUS_2),
            (TemporalGrain.MONTH, TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH),
        }
        if grain is not None and strategy is not None and (grain, strategy) not in valid_pairs:
            violations.append(
                _violation(
                    "invalid_temporal_strategy",
                    uri,
                    DEFAULT_STRATEGY,
                    "Temporal grain and strategy do not match",
                )
            )
        if override_text is None or override_text.casefold() not in {"true", "false"}:
            violations.append(
                _violation(
                    "invalid_query_override",
                    uri,
                    ALLOW_QUERY_OVERRIDE,
                    "Allow query override must be boolean",
                )
            )
            allow_query_override = True
        else:
            allow_query_override = override_text.casefold() == "true"
        try:
            priority = int(priority_text) if priority_text is not None else 0
        except ValueError:
            violations.append(
                _violation("invalid_priority", uri, PRIORITY, "Priority must be an integer")
            )
            priority = 0
        if (
            fields
            and applies_to
            and partition_property
            and grain is not None
            and strategy is not None
            and status is not None
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            temporal_policy_data.append(
                (
                    uri,
                    *fields,
                    applies_to,
                    partition_property,
                    grain,
                    strategy,
                    allow_query_override,
                    status,
                    priority,
                )
            )

    active_temporal_policies: dict[str, list[str]] = defaultdict(list)
    for uri, _, _, _, _, applies_to, _, _, _, _, status, _ in temporal_policy_data:
        if status == "active":
            active_temporal_policies[applies_to].append(uri)
    for policy_uris in active_temporal_policies.values():
        if len(policy_uris) > 1:
            for uri in policy_uris:
                violations.append(
                    _violation(
                        "duplicate_temporal_policy",
                        uri,
                        APPLIES_TO,
                        "Concept has multiple active temporal policies",
                    )
                )

    mapping_data: list[
        tuple[
            str,
            str,
            str,
            tuple[LocalizedText, ...],
            str | None,
            str,
            str,
            str | None,
            str | None,
            str | None,
            tuple[str, ...],
            int,
            bool,
        ]
    ] = []
    semantic_element_uris = marked_concept_uris | marked_property_uris | marked_relation_uris
    for subject in mapping_subjects:
        uri = str(subject)
        fields = _element_fields(graph, subject, violations)
        element = _capture(
            lambda subject=subject: _single_uri(
                graph, subject, SEMANTIC_ELEMENT, "semantic element"
            ),
            violations=violations,
            code="missing_semantic_element",
            uri=uri,
            path=SEMANTIC_ELEMENT,
        )
        source = _capture(
            lambda subject=subject: _single_uri(graph, subject, DATA_SOURCE_REF, "data source"),
            violations=violations,
            code="missing_data_source",
            uri=uri,
            path=DATA_SOURCE_REF,
        )
        _validate_reference(
            uri=uri,
            reference=element,
            path=SEMANTIC_ELEMENT,
            known=semantic_element_uris,
            violations=violations,
        )
        _validate_reference(
            uri=uri,
            reference=source,
            path=DATA_SOURCE_REF,
            known=marked_source_uris,
            violations=violations,
        )
        namespace = _capture(
            lambda subject=subject: _optional_literal(
                graph, subject, PHYSICAL_NAMESPACE, "physical namespace"
            ),
            violations=violations,
            code="invalid_mapping_value",
            uri=uri,
            path=PHYSICAL_NAMESPACE,
        )
        object_name = _capture(
            lambda subject=subject: _optional_literal(graph, subject, OBJECT_NAME, "object name"),
            violations=violations,
            code="invalid_mapping_value",
            uri=uri,
            path=OBJECT_NAME,
        )
        field_name = _capture(
            lambda subject=subject: _optional_literal(graph, subject, FIELD_NAME, "field name"),
            violations=violations,
            code="invalid_mapping_value",
            uri=uri,
            path=FIELD_NAME,
        )
        join_path = tuple(
            sorted(
                {
                    str(value)
                    for value in graph.objects(subject, JOIN_PATH)
                    if isinstance(value, Literal)
                }
            )
        )
        priority_text = _capture(
            lambda subject=subject: _optional_literal(graph, subject, PRIORITY, "priority") or "0",
            violations=violations,
            code="invalid_priority",
            uri=uri,
            path=PRIORITY,
        )
        enabled_text = _capture(
            lambda subject=subject: _optional_literal(graph, subject, ENABLED, "enabled") or "true",
            violations=violations,
            code="invalid_enabled",
            uri=uri,
            path=ENABLED,
        )
        try:
            priority = int(priority_text) if priority_text is not None else 0
        except ValueError:
            violations.append(
                _violation("invalid_priority", uri, PRIORITY, "Priority must be an integer")
            )
            priority = 0
        if enabled_text is None or enabled_text.casefold() not in {"true", "false"}:
            violations.append(
                _violation("invalid_enabled", uri, ENABLED, "Enabled must be true or false")
            )
            enabled = True
        else:
            enabled = enabled_text.casefold() == "true"
        if (
            fields
            and element
            and source
            and _validate_short_name(short_name=fields[0], uri=uri, violations=violations)
        ):
            mapping_data.append(
                (
                    uri,
                    *fields,
                    element,
                    source,
                    namespace,
                    object_name,
                    field_name,
                    join_path,
                    priority,
                    enabled,
                )
            )

    for short_name, uris in short_names.items():
        if len(uris) > 1:
            for uri in uris:
                violations.append(
                    _violation(
                        "duplicate_short_name",
                        uri,
                        SHORT_NAME,
                        f"Duplicate short name: {short_name}",
                    )
                )
    _raise_if_invalid(violations)

    children: dict[str, list[str]] = defaultdict(list)
    for uri, _, _, _, _, parents in concept_data:
        for parent in parents:
            children[parent].append(uri)
    concepts = tuple(
        Concept(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            parent_uris=parents,
            child_uris=tuple(sorted(children[uri])),
        )
        for uri, short_name, label, labels, description, parents in concept_data
    )
    properties = tuple(
        Property(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            concept_uri=domain,
            datatype_uri=value_range,
        )
        for uri, short_name, label, labels, description, domain, value_range in property_data
    )
    relations = tuple(
        Relation(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            source_concept_uri=source,
            target_concept_uri=target,
        )
        for uri, short_name, label, labels, description, source, target in relation_data
    )
    rules = tuple(
        BusinessRule(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            applies_to_uri=applies_to,
            property_uris=property_refs,
            relation_uris=relation_refs,
            condition=condition,
            status=status,
            priority=priority,
        )
        for (
            uri,
            short_name,
            label,
            labels,
            description,
            applies_to,
            property_refs,
            relation_refs,
            condition,
            status,
            priority,
        ) in rule_data
    )
    sources = tuple(
        DataSource(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            platform_type=platform_type,
            dialect=dialect,
            capabilities=capabilities,
        )
        for (
            uri,
            short_name,
            label,
            labels,
            description,
            platform_type,
            dialect,
            capabilities,
        ) in source_data
    )
    mappings = tuple(
        PhysicalMapping(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            semantic_element_uri=element,
            data_source_uri=source,
            physical_namespace=namespace,
            object_name=object_name,
            field_name=field_name,
            join_path=join_path,
            priority=priority,
            enabled=enabled,
        )
        for (
            uri,
            short_name,
            label,
            labels,
            description,
            element,
            source,
            namespace,
            object_name,
            field_name,
            join_path,
            priority,
            enabled,
        ) in mapping_data
    )
    temporal_policies = tuple(
        TemporalPartitionPolicy(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            applies_to_uri=applies_to,
            partition_property_uri=partition_property,
            grain=grain,
            default_strategy=strategy,
            allow_query_override=allow_query_override,
            status=status,
            priority=priority,
        )
        for (
            uri,
            short_name,
            label,
            labels,
            description,
            applies_to,
            partition_property,
            grain,
            strategy,
            allow_query_override,
            status,
            priority,
        ) in temporal_policy_data
    )
    return SemanticCatalog(
        concepts=tuple(sorted(concepts, key=_sort_key)),
        properties=tuple(sorted(properties, key=_sort_key)),
        relations=tuple(sorted(relations, key=_sort_key)),
        rules=tuple(sorted(rules, key=_sort_key)),
        data_sources=tuple(sorted(sources, key=_sort_key)),
        mappings=tuple(sorted(mappings, key=_sort_key)),
        temporal_policies=tuple(sorted(temporal_policies, key=_sort_key)),
    )
