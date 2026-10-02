from __future__ import annotations

from evaluation.contracts import PredicateSignature
from evaluation import sql_structure
from evaluation.sql_structure import extract_sql_structure


def test_extract_hive_select_normalizes_aliases_and_predicates() -> None:
    structure = extract_sql_structure(
        """
        SELECT u.USER_ID AS id, COUNT(DISTINCT o.ORDER_ID) AS order_count
        FROM DM.D_USER u
        LEFT JOIN DM.F_ORDER o ON u.USER_ID = o.USER_ID
        WHERE u.P_MON = '202607' AND u.STATUS = 'ACTIVE'
        GROUP BY u.USER_ID
        ORDER BY order_count DESC
        LIMIT 100
        """,
        "hive",
    )

    assert structure.status == "parsed"
    assert structure.is_read_only is True
    assert structure.tables == ("dm.d_user", "dm.f_order")
    assert structure.projections == (
        "count(distinct dm.f_order.order_id)",
        "dm.d_user.user_id",
    )
    assert structure.joins[0].join_type == "left"
    assert structure.joins[0].conditions == (
        "dm.d_user.user_id = dm.f_order.user_id",
    )
    assert structure.predicates == (
        PredicateSignature(field="dm.d_user.p_mon", operator="=", values=("202607",)),
        PredicateSignature(field="dm.d_user.status", operator="=", values=("ACTIVE",)),
    )
    assert structure.aggregates == ("count(distinct dm.f_order.order_id)",)
    assert structure.group_by == ("dm.d_user.user_id",)
    assert structure.order_by == ("order_count desc",)
    assert structure.limit == 100


def test_equivalent_aliases_quotes_and_whitespace_produce_same_structure() -> None:
    first = extract_sql_structure(
        'SELECT a."USER_ID" FROM "DM"."D_USER" a WHERE a."STATUS" = \'A\'',
        "hive",
    )
    second = extract_sql_structure(
        " select USER_ID from dm.d_user where STATUS='A' ",
        "hive",
    )

    assert first == second


def test_cte_records_physical_table_without_treating_cte_as_table() -> None:
    structure = extract_sql_structure(
        "WITH active AS (SELECT USER_ID FROM DM.D_USER WHERE STATUS='A') "
        "SELECT USER_ID FROM active",
        "hive",
    )

    assert structure.status == "parsed"
    assert structure.tables == ("dm.d_user",)
    assert structure.has_cte is True


def test_write_statement_is_rejected_without_echoing_sql() -> None:
    structure = extract_sql_structure("DROP TABLE SECRET_CUSTOMERS", "hive")

    assert structure.status == "unsupported"
    assert structure.is_read_only is False
    assert structure.tables == ()
    assert structure.warnings == ("non_read_only_statement",)
    assert "secret" not in str(structure).casefold()


def test_multiple_statements_are_rejected() -> None:
    structure = extract_sql_structure("SELECT 1; SELECT 2", "hive")

    assert structure.status == "unsupported"
    assert structure.warnings == ("multiple_statements",)


def test_invalid_sql_is_unparsed_without_raw_sql_in_warning() -> None:
    structure = extract_sql_structure("SELECT FROM confidential_table WHERE", "hive")

    assert structure.status == "unparsed"
    assert structure.is_read_only is False
    assert structure.warnings == ("sql_parse_failed",)
    assert "confidential" not in str(structure).casefold()


def test_ctas_program_matches_equivalent_query_without_temp_name() -> None:
    reference = sql_structure.extract_evaluable_structure(
        "SELECT ID FROM USER_D WHERE P_DAY='20260822'", "hive"
    )
    generated = sql_structure.extract_evaluable_structure(
        "DROP TABLE IF EXISTS temp_oa_a_result_table; "
        "CREATE TABLE temp_oa_a_result_table AS "
        "SELECT ID FROM USER_D WHERE P_DAY='20260822'",
        "hive",
    )

    assert generated == reference


def test_two_step_ctas_traces_base_table_and_ignores_temp_name() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "DROP TABLE IF EXISTS temp_oa_a_base; "
        "CREATE TABLE temp_oa_a_base AS "
        "SELECT ID FROM USER_D WHERE P_DAY='20260822'; "
        "DROP TABLE IF EXISTS temp_oa_a_result_table; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM temp_oa_a_base",
        "hive",
    )

    assert structure.status == "parsed"
    assert structure.tables == ("user_d",)
    assert structure.projections == ("user_d.id",)
    assert structure.predicates == (
        PredicateSignature(field="user_d.p_day", operator="=", values=("20260822",)),
    )
    assert structure.warnings == ()


def test_unrelated_staging_table_does_not_change_final_result() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "CREATE TABLE temp_oa_a_unused AS SELECT ID FROM SECRET_D; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM USER_D",
        "hive",
    )

    assert structure.tables == ("user_d",)


def test_unknown_intermediate_expression_requires_manual_review() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "CREATE TABLE temp_oa_a_base AS SELECT ID + 1 AS ID FROM USER_D; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM temp_oa_a_base",
        "hive",
    )

    assert structure.warnings == ("unresolved_program_lineage",)


def test_non_ctas_write_is_not_scored() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "INSERT INTO TARGET SELECT ID FROM USER_D", "hive"
    )

    assert structure.status == "unsupported"
    assert structure.is_read_only is False


def test_forward_temp_dependency_cannot_receive_a_score() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "CREATE TABLE temp_oa_a_base AS SELECT ID FROM temp_oa_a_later; "
        "CREATE TABLE temp_oa_a_later AS SELECT ID FROM USER_D; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM temp_oa_a_base",
        "hive",
    )

    assert "unresolved_program_lineage" in structure.warnings


def test_cycle_in_temp_dependency_is_unscorable() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "CREATE TABLE temp_oa_a_base AS SELECT ID FROM temp_oa_a_later; "
        "CREATE TABLE temp_oa_a_later AS SELECT ID FROM temp_oa_a_base; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID FROM temp_oa_a_base",
        "hive",
    )

    assert "unresolved_program_lineage" in structure.warnings


def test_computed_projection_using_temp_column_requires_review() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "CREATE TABLE temp_oa_a_base AS SELECT ID FROM USER_D; "
        "CREATE TABLE temp_oa_a_result_table AS SELECT ID + 1 AS ID FROM temp_oa_a_base",
        "hive",
    )

    assert "unresolved_program_lineage" in structure.warnings


def test_or_predicate_is_not_silently_ignored() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "SELECT ID FROM USER_D WHERE P_DAY='20260822' OR P_DAY='20260821'",
        "hive",
    )

    assert structure.warnings


def test_union_is_not_scored_using_only_first_select() -> None:
    structure = sql_structure.extract_evaluable_structure(
        "SELECT ID FROM USER_D UNION ALL SELECT ID FROM ORDER_D", "hive"
    )

    assert structure.warnings
