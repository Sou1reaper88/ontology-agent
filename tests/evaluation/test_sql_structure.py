from __future__ import annotations

from evaluation.contracts import PredicateSignature
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
