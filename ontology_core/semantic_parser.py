from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib.term import Identifier

from ontology_core.errors import OntologyValidationError
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
)
from ontology_core.vocabulary import (
    APPLIES_TO,
    ARGUMENT,
    BUSINESS_RULE,
    CAPABILITY,
    CONCEPT,
    CONDITION,
    DATA_SOURCE,
    DATA_SOURCE_REF,
    DIALECT,
    ENABLED,
    FIELD_NAME,
    JOIN_PATH,
    LEFT_PROPERTY,
    OA,
    OBJECT_NAME,
    PARAMETER,
    PHYSICAL_MAPPING,
    PHYSICAL_NAMESPACE,
    PLATFORM_TYPE,
    PRIORITY,
    PROPERTY,
    RELATION,
    SEMANTIC_ELEMENT,
    SHORT_NAME,
    STATUS,
    USES_PROPERTY,
    USES_RELATION,
    VALUE,
    VALUES,
)

_Element = TypeVar("_Element")
_MARKERS = (CONCEPT, PROPERTY, RELATION, BUSINESS_RULE, DATA_SOURCE, PHYSICAL_MAPPING)
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
_CREDENTIAL_NAMES = {
    "host",
    "port",
    "username",
    "password",
    "token",
    "secret",
    "connectionstring",
}


def _uris(graph: Graph, subject: Identifier, predicate: URIRef) -> tuple[str, ...]:
    return tuple(
        sorted(
            {str(value) for value in graph.objects(subject, predicate) if isinstance(value, URIRef)}
        )
    )


def _single_uri(graph: Graph, subject: Identifier, predicate: URIRef, field: str) -> str:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise ValueError(f"Marked semantic element requires exactly one {field}")
    return str(values[0])


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
    if chinese:
        return min(chinese, key=lambda text: (text.value, text.language.casefold())).value
    untagged = [text for text in texts if text.language is None]
    if untagged:
        return min(untagged, key=lambda text: (text.value, text.language or "")).value
    return min(texts, key=lambda text: (text.value, (text.language or "").casefold())).value


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
                subjects.add(subject)
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
            Concept(uri=uri, short_name=short_name, label="Valid", labels=())
        except (ValidationError, ValueError):
            continue
        short_names[short_name].append(uri)
    return short_names


def _parent_uris(
    graph: Graph, subject: URIRef, violations: list[dict[str, str]]
) -> tuple[str, ...]:
    uri = str(subject)
    parents: list[str] = []
    for value in graph.objects(subject, RDFS.subClassOf):
        if isinstance(value, URIRef):
            parents.append(str(value))
        else:
            violations.append(
                _violation(
                    "invalid_parent_reference",
                    uri,
                    RDFS.subClassOf,
                    f"Concept parent must be a URI: {value}",
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
    return item.short_name.casefold(), item.uri


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


def _parse_expression(
    graph: Graph,
    node: Identifier,
    property_uris: set[str],
    stack: set[Identifier],
) -> RuleExpression:
    if node in stack:
        raise ValueError("Rule expression contains a recursive condition cycle")
    operators = [
        operator
        for rdf_type, operator in _OPERATOR_TYPES.items()
        if (node, RDF.type, rdf_type) in graph
    ]
    if len(operators) != 1:
        raise ValueError("Rule expression requires exactly one operator type")
    operator = operators[0]
    next_stack = stack | {node}
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
        return RuleExpression(
            operator=operator,
            children=tuple(
                _parse_expression(graph, argument, property_uris, next_stack)
                for argument in arguments
            ),
        )

    property_uri = _single_uri(graph, node, LEFT_PROPERTY, "left property")
    if property_uri not in property_uris:
        raise ValueError(f"Referenced property does not exist: {property_uri}")
    if operator is RuleOperator.IS_NULL:
        if any(tuple(graph.objects(node, predicate)) for predicate in (VALUE, VALUES, PARAMETER)):
            raise ValueError("is_null does not accept a value or parameter")
        return RuleExpression(operator=operator, property_uri=property_uri)
    if operator in (RuleOperator.BETWEEN, RuleOperator.IN):
        heads = tuple(graph.objects(node, VALUES))
        if len(heads) != 1:
            raise ValueError("Rule expression requires exactly one RDF Collection values")
        return RuleExpression(
            operator=operator,
            property_uri=property_uri,
            values=_collection_literals(
                graph,
                heads[0],
                minimum=1 if operator is RuleOperator.IN else 2,
                exact=2 if operator is RuleOperator.BETWEEN else None,
            ),
        )
    literal_values = tuple(graph.objects(node, VALUE))
    parameters = tuple(graph.objects(node, PARAMETER))
    if len(literal_values) == 1 and isinstance(literal_values[0], Literal) and not parameters:
        return RuleExpression(
            operator=operator,
            property_uri=property_uri,
            values=(_literal(literal_values[0]),),
        )
    if len(parameters) == 1 and isinstance(parameters[0], Literal) and not literal_values:
        return RuleExpression(
            operator=operator, property_uri=property_uri, parameter=str(parameters[0])
        )
    raise ValueError("Comparison requires exactly one literal value or parameter")


def _forbidden_predicates(graph: Graph, subject: URIRef, violations: list[dict[str, str]]) -> None:
    for predicate in graph.predicates(subject):
        local_name = (
            str(predicate)
            .replace("#", "/")
            .rsplit("/", 1)[-1]
            .replace("_", "")
            .replace("-", "")
            .casefold()
        )
        if local_name in _CREDENTIAL_NAMES:
            violations.append(
                _violation(
                    "forbidden_credential_predicate",
                    str(subject),
                    predicate,
                    "Credential-like predicates are prohibited",
                )
            )


def parse_catalog(graph: Graph) -> SemanticCatalog:
    """Parse marked semantic elements or raise one aggregated validation error."""
    subjects, violations = _invalid_subject_violations(graph)
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
        _forbidden_predicates(graph, subject, violations)
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
        property_refs = _uris(graph, subject, USES_PROPERTY)
        relation_refs = _uris(graph, subject, USES_RELATION)
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
                condition = _parse_expression(graph, nodes[0], marked_property_uris, set())
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
        _forbidden_predicates(graph, subject, violations)
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
    return SemanticCatalog(
        concepts=tuple(sorted(concepts, key=_sort_key)),
        properties=tuple(sorted(properties, key=_sort_key)),
        relations=tuple(sorted(relations, key=_sort_key)),
        rules=tuple(sorted(rules, key=_sort_key)),
        data_sources=tuple(sorted(sources, key=_sort_key)),
        mappings=tuple(sorted(mappings, key=_sort_key)),
    )
