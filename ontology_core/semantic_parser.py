from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib.term import Identifier

from ontology_core.errors import OntologyValidationError
from ontology_core.semantic_models import (
    Concept,
    LocalizedText,
    Property,
    Relation,
    SemanticCatalog,
)
from ontology_core.vocabulary import CONCEPT, PROPERTY, RELATION, SHORT_NAME

_Element = TypeVar("_Element")
_MARKERS = (CONCEPT, PROPERTY, RELATION)


def _uris(graph: Graph, subject: Identifier, predicate: URIRef) -> tuple[str, ...]:
    """Return sorted, distinct URI object values for a statement."""
    objects = graph.objects(subject, predicate)
    values = {str(value) for value in objects if isinstance(value, URIRef)}
    return tuple(sorted(values))


def _single_uri(graph: Graph, subject: Identifier, predicate: URIRef, field: str) -> str:
    """Return one URI object or raise a deterministic cardinality error."""
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise ValueError(f"Marked semantic element requires exactly one {field}")
    return str(values[0])


def _texts(graph: Graph, subject: Identifier, predicate: URIRef) -> tuple[LocalizedText, ...]:
    """Return sorted, distinct literal values with their language tags."""
    texts = {
        (value.language or "", str(value)): LocalizedText(
            value=str(value), language=value.language or None
        )
        for value in graph.objects(subject, predicate)
        if isinstance(value, Literal) and str(value)
    }
    return tuple(texts[key] for key in sorted(texts))


def _preferred_text(texts: tuple[LocalizedText, ...]) -> str:
    """Prefer Chinese, then untagged, then lexicographically first text."""
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
    """Return one literal short name or raise a deterministic cardinality error."""
    values = tuple(graph.objects(subject, SHORT_NAME))
    if len(values) != 1 or not isinstance(values[0], Literal) or not str(values[0]):
        raise ValueError("Marked semantic element requires exactly one short name")
    return str(values[0])


def _description(graph: Graph, subject: Identifier) -> str | None:
    """Return the preferred optional description."""
    texts = _texts(graph, subject, RDFS.comment)
    return _preferred_text(texts) if texts else None


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
    graph: Graph,
    subject: URIRef,
    violations: list[dict[str, str]],
) -> tuple[str, ...]:
    uri = str(subject)
    parent_uris = []
    for value in graph.objects(subject, RDFS.subClassOf):
        if isinstance(value, URIRef):
            parent_uris.append(str(value))
        else:
            violations.append(
                _violation(
                    "invalid_parent_reference",
                    uri,
                    RDFS.subClassOf,
                    f"Concept parent must be a URI: {value}",
                )
            )
    return tuple(sorted(set(parent_uris)))


def _raise_if_invalid(violations: list[dict[str, str]]) -> None:
    if not violations:
        return
    violations.sort(key=lambda item: (item["code"], item["uri"], item["path"], item["message"]))
    raise OntologyValidationError(
        "Semantic catalog validation failed",
        details={"violations": violations},
    )


def _sort_key(item: Concept | Property | Relation) -> tuple[str, str]:
    return item.short_name.casefold(), item.uri


def parse_catalog(graph: Graph) -> SemanticCatalog:
    """Parse marked semantic elements or raise one aggregated validation error."""
    subjects, violations = _invalid_subject_violations(graph)
    concept_subjects = sorted(
        (subject for subject in subjects if (subject, RDF.type, CONCEPT) in graph), key=str
    )
    property_subjects = sorted(
        (subject for subject in subjects if (subject, RDF.type, PROPERTY) in graph), key=str
    )
    relation_subjects = sorted(
        (subject for subject in subjects if (subject, RDF.type, RELATION) in graph), key=str
    )

    marked_concept_uris = {str(subject) for subject in concept_subjects}
    short_names = _valid_short_names(graph, subjects)
    concept_data: list[
        tuple[
            str,
            str,
            str,
            tuple[LocalizedText, ...],
            str | None,
            tuple[str, ...],
        ]
    ] = []
    for subject in concept_subjects:
        fields = _element_fields(graph, subject, violations)
        if fields is None:
            continue
        short_name, label, labels, description = fields
        uri = str(subject)
        if not _validate_short_name(short_name=short_name, uri=uri, violations=violations):
            continue
        parent_uris = _parent_uris(graph, subject, violations)
        concept_data.append((uri, short_name, label, labels, description, parent_uris))

    for uri, _, _, _, _, parent_uris in concept_data:
        for parent_uri in parent_uris:
            if parent_uri not in marked_concept_uris:
                violations.append(
                    _violation(
                        "dangling_concept_reference",
                        uri,
                        RDFS.subClassOf,
                        f"Referenced concept does not exist: {parent_uri}",
                    )
                )

    property_data: list[tuple[str, str, str, tuple[LocalizedText, ...], str | None, str, str]] = []
    for subject in property_subjects:
        fields = _element_fields(graph, subject, violations)
        uri = str(subject)
        domain_uri = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.domain, "domain"),
            violations=violations,
            code="missing_domain",
            uri=uri,
            path=RDFS.domain,
        )
        range_uri = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.range, "range"),
            violations=violations,
            code="missing_range",
            uri=uri,
            path=RDFS.range,
        )
        if fields is None or domain_uri is None or range_uri is None:
            continue
        short_name, label, labels, description = fields
        if not _validate_short_name(short_name=short_name, uri=uri, violations=violations):
            continue
        property_data.append((uri, short_name, label, labels, description, domain_uri, range_uri))

    relation_data: list[tuple[str, str, str, tuple[LocalizedText, ...], str | None, str, str]] = []
    for subject in relation_subjects:
        fields = _element_fields(graph, subject, violations)
        uri = str(subject)
        source_uri = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.domain, "domain"),
            violations=violations,
            code="missing_domain",
            uri=uri,
            path=RDFS.domain,
        )
        target_uri = _capture(
            lambda subject=subject: _single_uri(graph, subject, RDFS.range, "range"),
            violations=violations,
            code="missing_range",
            uri=uri,
            path=RDFS.range,
        )
        if fields is None or source_uri is None or target_uri is None:
            continue
        short_name, label, labels, description = fields
        if not _validate_short_name(short_name=short_name, uri=uri, violations=violations):
            continue
        relation_data.append((uri, short_name, label, labels, description, source_uri, target_uri))

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

    for uri, _, _, _, _, domain_uri, _ in property_data:
        if domain_uri not in marked_concept_uris:
            violations.append(
                _violation(
                    "dangling_concept_reference",
                    uri,
                    RDFS.domain,
                    f"Referenced concept does not exist: {domain_uri}",
                )
            )
    for uri, _, _, _, _, source_uri, target_uri in relation_data:
        for path, concept_uri in ((RDFS.domain, source_uri), (RDFS.range, target_uri)):
            if concept_uri not in marked_concept_uris:
                violations.append(
                    _violation(
                        "dangling_concept_reference",
                        uri,
                        path,
                        f"Referenced concept does not exist: {concept_uri}",
                    )
                )

    _raise_if_invalid(violations)

    children: dict[str, list[str]] = defaultdict(list)
    for uri, _, _, _, _, parent_uris in concept_data:
        for parent_uri in parent_uris:
            children[parent_uri].append(uri)

    concepts = tuple(
        Concept(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            parent_uris=parent_uris,
            child_uris=tuple(sorted(children[uri])),
        )
        for uri, short_name, label, labels, description, parent_uris in concept_data
    )
    properties = tuple(
        Property(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            concept_uri=domain_uri,
            datatype_uri=range_uri,
        )
        for uri, short_name, label, labels, description, domain_uri, range_uri in property_data
    )
    relations = tuple(
        Relation(
            uri=uri,
            short_name=short_name,
            label=label,
            labels=labels,
            description=description,
            source_concept_uri=source_uri,
            target_concept_uri=target_uri,
        )
        for uri, short_name, label, labels, description, source_uri, target_uri in relation_data
    )

    return SemanticCatalog(
        concepts=tuple(sorted(concepts, key=_sort_key)),
        properties=tuple(sorted(properties, key=_sort_key)),
        relations=tuple(sorted(relations, key=_sort_key)),
    )
