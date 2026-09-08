"""Parse read-only SQL into deterministic structural snapshots."""

from __future__ import annotations

from collections.abc import Iterator

from sqlglot import exp, parse, parse_one
from sqlglot.errors import ParseError, SqlglotError

from evaluation.contracts import JoinSignature, PredicateSignature, SqlStructure

_COMPARISONS: tuple[tuple[type[exp.Expression], str], ...] = (
    (exp.EQ, "="),
    (exp.NEQ, "!="),
    (exp.GTE, ">="),
    (exp.LTE, "<="),
    (exp.GT, ">"),
    (exp.LT, "<"),
)


def _failed(status: str, warning: str) -> SqlStructure:
    return SqlStructure(
        status=status,  # type: ignore[arg-type]
        is_read_only=False,
        warnings=(warning,),
    )


def _identifier(value: str | None) -> str:
    return (value or "").strip().strip('`"').casefold()


def _table_name(table: exp.Table) -> str:
    return ".".join(
        item
        for item in (
            _identifier(table.catalog),
            _identifier(table.db),
            _identifier(table.name),
        )
        if item
    )


def _column_expression(qualified_name: str, dialect: str) -> exp.Column:
    parsed = parse_one(qualified_name, read=dialect, into=exp.Column)
    if not isinstance(parsed, exp.Column):
        raise ParseError("column normalization failed")
    return parsed


def _canonical_context(
    statement: exp.Expression,
) -> tuple[dict[str, str], tuple[str, ...], set[str]]:
    cte_names = {
        _identifier(cte.alias_or_name)
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }
    aliases: dict[str, str] = {}
    physical_tables: set[str] = set()
    for table in statement.find_all(exp.Table):
        name = _table_name(table)
        if not name or _identifier(table.name) in cte_names:
            continue
        physical_tables.add(name)
        aliases[_identifier(table.alias_or_name)] = name
        aliases[_identifier(table.name)] = name
    return aliases, tuple(sorted(physical_tables)), cte_names


def _canonical_expression(
    expression: exp.Expression,
    *,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
    dialect: str,
) -> str:
    def replace(node: exp.Expression) -> exp.Expression:
        if not isinstance(node, exp.Column):
            return node
        table = _identifier(node.table)
        source = aliases.get(table)
        if source is None and not table and len(physical_tables) == 1:
            source = physical_tables[0]
        name = _identifier(node.name)
        qualified = f"{source}.{name}" if source else name
        return _column_expression(qualified, dialect)

    normalized = expression.copy().transform(replace)
    return " ".join(normalized.sql(dialect=dialect, normalize=True).split()).casefold()


def _projection_expression(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _flatten_and(expression: exp.Expression | None) -> Iterator[exp.Expression]:
    if expression is None:
        return
    if isinstance(expression, exp.And):
        yield from _flatten_and(expression.left)
        yield from _flatten_and(expression.right)
        return
    yield expression


def _literal_value(expression: exp.Expression, dialect: str) -> str:
    if isinstance(expression, exp.Literal):
        return str(expression.this)
    if isinstance(expression, exp.Null):
        return "null"
    return " ".join(expression.sql(dialect=dialect, normalize=True).split()).casefold()


def _predicate(
    expression: exp.Expression,
    *,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
    dialect: str,
) -> PredicateSignature | None:
    for expression_type, operator in _COMPARISONS:
        if isinstance(expression, expression_type):
            if isinstance(expression.left, exp.Column):
                field_expression = expression.left
                value_expression = expression.right
            elif isinstance(expression.right, exp.Column):
                field_expression = expression.right
                value_expression = expression.left
            else:
                return None
            return PredicateSignature(
                field=_canonical_expression(
                    field_expression,
                    aliases=aliases,
                    physical_tables=physical_tables,
                    dialect=dialect,
                ),
                operator=operator,
                values=(_literal_value(value_expression, dialect),),
            )
    if isinstance(expression, exp.In) and isinstance(expression.this, exp.Column):
        return PredicateSignature(
            field=_canonical_expression(
                expression.this,
                aliases=aliases,
                physical_tables=physical_tables,
                dialect=dialect,
            ),
            operator="in",
            values=tuple(sorted(_literal_value(item, dialect) for item in expression.expressions)),
        )
    if isinstance(expression, exp.Between) and isinstance(expression.this, exp.Column):
        return PredicateSignature(
            field=_canonical_expression(
                expression.this,
                aliases=aliases,
                physical_tables=physical_tables,
                dialect=dialect,
            ),
            operator="between",
            values=(
                _literal_value(expression.args["low"], dialect),
                _literal_value(expression.args["high"], dialect),
            ),
        )
    if isinstance(expression, exp.Is) and isinstance(expression.this, exp.Column):
        return PredicateSignature(
            field=_canonical_expression(
                expression.this,
                aliases=aliases,
                physical_tables=physical_tables,
                dialect=dialect,
            ),
            operator="is",
            values=(_literal_value(expression.expression, dialect),),
        )
    return None


def _predicates(
    clause: exp.Expression | None,
    *,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
    dialect: str,
) -> tuple[PredicateSignature, ...]:
    expression = clause.this if isinstance(clause, (exp.Where, exp.Having)) else clause
    signatures = (
        signature
        for item in _flatten_and(expression)
        if (
            signature := _predicate(
                item,
                aliases=aliases,
                physical_tables=physical_tables,
                dialect=dialect,
            )
        )
        is not None
    )
    return tuple(sorted(signatures, key=lambda item: (item.field, item.operator, item.values)))


def _first_select(statement: exp.Expression) -> exp.Select | None:
    if isinstance(statement, exp.Select):
        return statement
    return next(statement.find_all(exp.Select), None)


def _join_type(join: exp.Join) -> str:
    side = _identifier(str(join.args.get("side") or ""))
    kind = _identifier(str(join.args.get("kind") or ""))
    return side or kind or "inner"


def _joins(
    select: exp.Select,
    *,
    aliases: dict[str, str],
    physical_tables: tuple[str, ...],
    dialect: str,
) -> tuple[JoinSignature, ...]:
    from_clause = select.args.get("from") or select.args.get("from_")
    left_expression = from_clause.this if isinstance(from_clause, exp.From) else None
    left = _table_name(left_expression) if isinstance(left_expression, exp.Table) else ""
    signatures: list[JoinSignature] = []
    for join in select.args.get("joins") or ():
        target = join.this
        right = (
            _table_name(target)
            if isinstance(target, exp.Table)
            else _identifier(target.alias_or_name)
        )
        on = join.args.get("on")
        conditions = (
            (
                _canonical_expression(
                    on,
                    aliases=aliases,
                    physical_tables=physical_tables,
                    dialect=dialect,
                ),
            )
            if isinstance(on, exp.Expression)
            else ()
        )
        signatures.append(
            JoinSignature(
                join_type=_join_type(join),
                left=left,
                right=right,
                conditions=conditions,
            )
        )
        left = right
    return tuple(signatures)


def _limit(select: exp.Select | None) -> int | None:
    if select is None:
        return None
    limit = select.args.get("limit")
    expression = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(expression, exp.Literal) and not expression.is_string:
        try:
            return int(expression.this)
        except (TypeError, ValueError):
            return None
    return None


def extract_sql_structure(sql: str, dialect: str) -> SqlStructure:
    """Parse one read-only query without leaking SQL through failures."""

    try:
        statements = [item for item in parse(sql, read=dialect) if item is not None]
    except (ParseError, SqlglotError, TypeError, ValueError):
        return _failed("unparsed", "sql_parse_failed")
    if len(statements) != 1:
        return _failed("unsupported", "multiple_statements")
    statement = statements[0]
    if not isinstance(statement, exp.Query) or isinstance(statement, exp.Command):
        return _failed("unsupported", "non_read_only_statement")

    aliases, tables, _ = _canonical_context(statement)
    select = _first_select(statement)
    if select is None:
        return _failed("unsupported", "unsupported_query_shape")

    def canonical(item: exp.Expression) -> str:
        return _canonical_expression(
            item,
            aliases=aliases,
            physical_tables=tables,
            dialect=dialect,
        )

    projections = tuple(
        sorted(canonical(_projection_expression(item)) for item in select.expressions)
    )
    aggregates = tuple(
        sorted(
            {
                canonical(item)
                for projection in select.expressions
                for item in projection.find_all(exp.AggFunc)
            }
        )
    )
    group = select.args.get("group")
    group_by = (
        tuple(sorted(canonical(item) for item in group.expressions))
        if isinstance(group, exp.Group)
        else ()
    )
    order = select.args.get("order")
    order_by = ()
    if isinstance(order, exp.Order):
        order_by = tuple(
            f"{canonical(item.this)} {'desc' if item.args.get('desc') else 'asc'}"
            for item in order.expressions
            if isinstance(item, exp.Ordered)
        )
    distinct = select.args.get("distinct") is not None

    unresolved = any(
        not column.table and len(tables) != 1 for column in statement.find_all(exp.Column)
    )
    warnings = ("unresolved_column_source",) if unresolved else ()
    return SqlStructure(
        status="parsed",
        is_read_only=True,
        tables=tables,
        projections=projections,
        joins=_joins(
            select,
            aliases=aliases,
            physical_tables=tables,
            dialect=dialect,
        ),
        predicates=_predicates(
            select.args.get("where"),
            aliases=aliases,
            physical_tables=tables,
            dialect=dialect,
        ),
        having=_predicates(
            select.args.get("having"),
            aliases=aliases,
            physical_tables=tables,
            dialect=dialect,
        ),
        aggregates=aggregates,
        group_by=group_by,
        distinct=distinct,
        order_by=order_by,
        limit=_limit(select),
        has_star=any(True for _ in statement.find_all(exp.Star)),
        has_cte=any(True for _ in statement.find_all(exp.CTE)),
        has_subquery=any(True for _ in statement.find_all(exp.Subquery)),
        warnings=warnings,
    )
