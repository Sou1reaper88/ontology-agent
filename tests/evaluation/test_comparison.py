from __future__ import annotations

from evaluation.comparison import compare_sql_structures, summarize_candidate_results
from evaluation.sql_structure import extract_sql_structure


def structure(sql: str):
    return extract_sql_structure(sql, "hive")


def test_equivalent_sql_is_strict_pass_with_full_score() -> None:
    result = compare_sql_structures(
        structure("SELECT USER_ID FROM DM.D_USER WHERE STATUS='A'"),
        structure("select u.user_id from dm.d_user u where u.status = 'A'"),
    )

    assert result.score == 100
    assert result.strict_pass is True
    assert result.manual_review is False
    assert result.diagnosis_codes == ()


def test_partition_mismatch_is_separate_from_business_predicates() -> None:
    result = compare_sql_structures(
        reference=structure(
            "SELECT USER_ID FROM D_USER WHERE P_MON='202607' AND STATUS='A'"
        ),
        candidate=structure(
            "SELECT USER_ID FROM D_USER WHERE P_MON='202606' AND STATUS='A'"
        ),
        partition_fields={"p_mon"},
    )

    assert result.dimensions["predicates"].status == "matched"
    assert result.dimensions["partition"].status == "mismatched"
    assert result.dimensions["partition"].conflicts == (
        "d_user.p_mon = [202607] -> [202606]",
    )
    assert result.score == 85
    assert result.strict_pass is False
    assert "partition_mismatch" in result.diagnosis_codes


def test_partial_field_match_reports_missing_and_extra() -> None:
    result = compare_sql_structures(
        structure("SELECT USER_ID, USER_NAME FROM D_USER"),
        structure("SELECT USER_ID, STATUS FROM D_USER"),
    )

    fields = result.dimensions["fields"]
    assert fields.status == "partial"
    assert fields.score == 10
    assert fields.missing == ("d_user.user_name",)
    assert fields.extra == ("d_user.status",)
    assert result.score == 90
    assert result.diagnosis_codes == ("field_mismatch",)


def test_join_key_mismatch_is_actionable() -> None:
    result = compare_sql_structures(
        structure(
            "SELECT u.USER_ID FROM D_USER u JOIN F_ORDER o ON u.USER_ID=o.USER_ID"
        ),
        structure(
            "SELECT u.USER_ID FROM D_USER u JOIN F_ORDER o ON u.USER_ID=o.ORDER_ID"
        ),
    )

    joins = result.dimensions["joins"]
    assert joins.status == "mismatched"
    assert joins.missing
    assert joins.extra
    assert "join_mismatch" in result.diagnosis_codes


def test_reference_parse_failure_requires_manual_review_without_score() -> None:
    result = compare_sql_structures(
        structure("SELECT FROM confidential_reference WHERE"),
        structure("SELECT USER_ID FROM D_USER"),
    )

    assert result.score is None
    assert result.strict_pass is False
    assert result.manual_review is True
    assert result.diagnosis_codes == (
        "reference_parse_failed",
        "manual_review_required",
    )


def test_unresolved_source_warning_is_not_silently_scored() -> None:
    result = compare_sql_structures(
        structure("SELECT USER_ID"),
        structure("SELECT USER_ID"),
    )

    assert result.score is None
    assert result.manual_review is True
    assert "manual_review_required" in result.diagnosis_codes


def test_summary_excludes_unscorable_cases_from_average_and_denominators() -> None:
    passing = compare_sql_structures(
        structure("SELECT USER_ID FROM D_USER"),
        structure("SELECT USER_ID FROM D_USER"),
    )
    failing = compare_sql_structures(
        structure("SELECT USER_ID FROM D_USER"),
        structure("SELECT STATUS FROM D_USER"),
    )
    unscorable = compare_sql_structures(
        structure("SELECT FROM secret_reference WHERE"),
        structure("SELECT USER_ID FROM D_USER"),
    )

    summary = summarize_candidate_results((passing, failing, unscorable))

    assert summary.total == 3
    assert summary.scorable == 2
    assert summary.strict_pass.numerator == 1
    assert summary.strict_pass.denominator == 2
    assert summary.manual_review.numerator == 1
    assert summary.manual_review.denominator == 3
    assert summary.average_score == 90.0
    assert summary.dimensions["tables"].numerator == 2
    assert summary.dimensions["tables"].denominator == 2


def test_empty_summary_uses_none_instead_of_false_zero_percent() -> None:
    summary = summarize_candidate_results(())

    assert summary.average_score is None
    assert summary.strict_pass.rate is None
    assert summary.manual_review.rate is None
