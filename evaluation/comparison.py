"""Deterministic six-dimension comparison and scoring."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from evaluation.contracts import (
    CandidateEvaluation,
    CandidateSummary,
    DimensionResult,
    JoinSignature,
    MetricCount,
    PredicateSignature,
    SqlStructure,
)

DIMENSION_WEIGHTS = {
    "tables": 20,
    "fields": 20,
    "predicates": 20,
    "joins": 15,
    "partition": 15,
    "shape": 10,
}

DIAGNOSIS_PRIORITY = (
    "reference_parse_failed",
    "candidate_parse_failed",
    "table_mismatch",
    "join_mismatch",
    "partition_mismatch",
    "predicate_mismatch",
    "field_mismatch",
    "query_shape_mismatch",
    "manual_review_required",
)


def _metric(numerator: int, denominator: int) -> MetricCount:
    rate = round(numerator / denominator * 100, 1) if denominator else None
    return MetricCount(numerator=numerator, denominator=denominator, rate=rate)


def _set_dimension(
    reference: Iterable[str],
    candidate: Iterable[str],
    weight: int,
) -> DimensionResult:
    expected = set(reference)
    actual = set(candidate)
    if not expected and not actual:
        return DimensionResult(status="not_applicable", score=weight)
    missing = tuple(sorted(expected - actual))
    extra = tuple(sorted(actual - expected))
    if not missing and not extra:
        return DimensionResult(status="matched", score=weight)
    overlap = len(expected & actual)
    if overlap:
        similarity = (2 * overlap) / (len(expected) + len(actual))
        return DimensionResult(
            status="partial",
            score=round(weight * similarity),
            missing=missing,
            extra=extra,
        )
    return DimensionResult(
        status="mismatched",
        score=0,
        missing=missing,
        extra=extra,
    )


def _predicate_key(item: PredicateSignature) -> tuple[str, str]:
    return item.field, item.operator


def _predicate_text(item: PredicateSignature) -> str:
    values = ", ".join(item.values)
    return f"{item.field} {item.operator} [{values}]"


def _predicate_dimension(
    reference: Iterable[PredicateSignature],
    candidate: Iterable[PredicateSignature],
    weight: int,
) -> DimensionResult:
    expected = {_predicate_key(item): item for item in reference}
    actual = {_predicate_key(item): item for item in candidate}
    if not expected and not actual:
        return DimensionResult(status="not_applicable", score=weight)

    expected_keys = set(expected)
    actual_keys = set(actual)
    missing = tuple(_predicate_text(expected[key]) for key in sorted(expected_keys - actual_keys))
    extra = tuple(_predicate_text(actual[key]) for key in sorted(actual_keys - expected_keys))
    conflicts = tuple(
        f"{expected[key].field} {expected[key].operator} "
        f"[{', '.join(expected[key].values)}] -> [{', '.join(actual[key].values)}]"
        for key in sorted(expected_keys & actual_keys)
        if expected[key].values != actual[key].values
    )
    matched = sum(
        expected[key].values == actual[key].values for key in expected_keys & actual_keys
    )
    if not missing and not extra and not conflicts:
        return DimensionResult(status="matched", score=weight)
    if matched:
        similarity = (2 * matched) / (len(expected) + len(actual))
        return DimensionResult(
            status="partial",
            score=round(weight * similarity),
            missing=missing,
            extra=extra,
            conflicts=conflicts,
        )
    return DimensionResult(
        status="mismatched",
        score=0,
        missing=missing,
        extra=extra,
        conflicts=conflicts,
    )


def _join_text(item: JoinSignature) -> str:
    conditions = " and ".join(item.conditions) or "no_condition"
    return f"{item.left} {item.join_type} {item.right} on {conditions}"


def _shape(structure: SqlStructure) -> tuple[str, ...]:
    values = {
        *(f"aggregate:{item}" for item in structure.aggregates),
        *(f"group_by:{item}" for item in structure.group_by),
        *(f"order_by:{item}" for item in structure.order_by),
    }
    if structure.distinct:
        values.add("distinct:true")
    if structure.has_star:
        values.add("star:true")
    if structure.limit is not None:
        values.add(f"limit:{structure.limit}")
    return tuple(sorted(values))


def _short_field(field: str) -> str:
    return field.rsplit(".", 1)[-1].casefold()


def _partitioned_predicates(
    structure: SqlStructure,
    partition_fields: Collection[str],
) -> tuple[tuple[PredicateSignature, ...], tuple[PredicateSignature, ...]]:
    names = {_short_field(item) for item in partition_fields}
    regular: list[PredicateSignature] = []
    partition: list[PredicateSignature] = []
    for item in (*structure.predicates, *structure.having):
        (partition if _short_field(item.field) in names else regular).append(item)
    return tuple(regular), tuple(partition)


def _unscorable(code: str) -> CandidateEvaluation:
    dimensions = {
        name: DimensionResult(status="unscorable", score=None)
        for name in DIMENSION_WEIGHTS
    }
    return CandidateEvaluation(
        score=None,
        strict_pass=False,
        manual_review=True,
        dimensions=dimensions,
        diagnosis_codes=(code, "manual_review_required"),
    )


def compare_sql_structures(
    reference: SqlStructure,
    candidate: SqlStructure,
    *,
    partition_fields: Collection[str] = (),
) -> CandidateEvaluation:
    """Compare one candidate with a trusted SQL structural reference."""

    if reference.status != "parsed" or not reference.is_read_only:
        return _unscorable("reference_parse_failed")
    if candidate.status != "parsed" or not candidate.is_read_only:
        return _unscorable("candidate_parse_failed")
    if reference.warnings or candidate.warnings:
        return _unscorable("manual_review_required")

    reference_predicates, reference_partition = _partitioned_predicates(
        reference, partition_fields
    )
    candidate_predicates, candidate_partition = _partitioned_predicates(
        candidate, partition_fields
    )
    dimensions = {
        "tables": _set_dimension(
            reference.tables,
            candidate.tables,
            DIMENSION_WEIGHTS["tables"],
        ),
        "fields": _set_dimension(
            reference.projections,
            candidate.projections,
            DIMENSION_WEIGHTS["fields"],
        ),
        "predicates": _predicate_dimension(
            reference_predicates,
            candidate_predicates,
            DIMENSION_WEIGHTS["predicates"],
        ),
        "joins": _set_dimension(
            (_join_text(item) for item in reference.joins),
            (_join_text(item) for item in candidate.joins),
            DIMENSION_WEIGHTS["joins"],
        ),
        "partition": _predicate_dimension(
            reference_partition,
            candidate_partition,
            DIMENSION_WEIGHTS["partition"],
        ),
        "shape": _set_dimension(
            _shape(reference),
            _shape(candidate),
            DIMENSION_WEIGHTS["shape"],
        ),
    }
    diagnosis_by_dimension = {
        "tables": "table_mismatch",
        "joins": "join_mismatch",
        "partition": "partition_mismatch",
        "predicates": "predicate_mismatch",
        "fields": "field_mismatch",
        "shape": "query_shape_mismatch",
    }
    found = {
        diagnosis_by_dimension[name]
        for name, result in dimensions.items()
        if result.status not in {"matched", "not_applicable"}
    }
    diagnoses = tuple(code for code in DIAGNOSIS_PRIORITY if code in found)
    strict_pass = not diagnoses
    return CandidateEvaluation(
        score=sum(result.score or 0 for result in dimensions.values()),
        strict_pass=strict_pass,
        manual_review=False,
        dimensions=dimensions,
        diagnosis_codes=diagnoses,
    )


def summarize_candidate_results(
    results: Sequence[CandidateEvaluation],
) -> CandidateSummary:
    """Aggregate results without treating unscorable cases as zero."""

    scorable = tuple(item for item in results if item.score is not None)
    strict = sum(item.strict_pass for item in scorable)
    manual = sum(item.manual_review for item in results)
    dimensions: dict[str, MetricCount] = {}
    for name in DIMENSION_WEIGHTS:
        applicable = tuple(
            item.dimensions[name]
            for item in results
            if item.dimensions[name].status not in {"not_applicable", "unscorable"}
        )
        dimensions[name] = _metric(
            sum(item.status == "matched" for item in applicable),
            len(applicable),
        )
    average = (
        round(sum(item.score for item in scorable if item.score is not None) / len(scorable), 1)
        if scorable
        else None
    )
    return CandidateSummary(
        total=len(results),
        scorable=len(scorable),
        strict_pass=_metric(strict, len(scorable)),
        manual_review=_metric(manual, len(results)),
        average_score=average,
        dimensions=dimensions,
    )
