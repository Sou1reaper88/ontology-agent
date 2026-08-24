from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Protocol

from ontology_core.errors import OntologyCompileError
from ontology_core.query_plan import CompiledQuery, QueryPlan
from ontology_core.semantic_models import RdfLiteral, RuleExpression, RuleOperator

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_INTEGER = re.compile(r"[+-]?\d+")
_XSD = "http://www.w3.org/2001/XMLSchema#"
_TEXT_TYPES = {
    f"{_XSD}string",
    f"{_XSD}normalizedString",
    f"{_XSD}token",
    f"{_XSD}language",
    f"{_XSD}Name",
    f"{_XSD}NCName",
    f"{_XSD}NMTOKEN",
    f"{_XSD}anyURI",
}
_INTEGER_TYPES = {
    f"{_XSD}integer",
    f"{_XSD}long",
    f"{_XSD}int",
    f"{_XSD}short",
    f"{_XSD}byte",
    f"{_XSD}nonNegativeInteger",
    f"{_XSD}positiveInteger",
    f"{_XSD}nonPositiveInteger",
    f"{_XSD}negativeInteger",
    f"{_XSD}unsignedLong",
    f"{_XSD}unsignedInt",
    f"{_XSD}unsignedShort",
    f"{_XSD}unsignedByte",
}
_DECIMAL_TYPES = {f"{_XSD}decimal", f"{_XSD}double", f"{_XSD}float"}
_COMPARISONS = {
    RuleOperator.EQ: "=",
    RuleOperator.NE: "<>",
    RuleOperator.GT: ">",
    RuleOperator.GTE: ">=",
    RuleOperator.LT: "<",
    RuleOperator.LTE: "<=",
}


class SqlCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledQuery: ...


def _compile_error(message: str) -> OntologyCompileError:
    return OntologyCompileError(message)


def _quote_identifier(value: str | None) -> str:
    if value is None or not _IDENTIFIER.fullmatch(value):
        raise _compile_error("物理映射包含不支持的标识符")
    return f'"{value}"'


def _quote_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _literal(value: RdfLiteral) -> str:
    datatype = value.datatype_uri
    lexical = value.lexical_form
    if value.language is not None or datatype is None or datatype in _TEXT_TYPES:
        return _quote_text(lexical)
    if datatype in _INTEGER_TYPES:
        if not _INTEGER.fullmatch(lexical):
            raise _compile_error("规则包含无效的整数值")
        return lexical
    if datatype in _DECIMAL_TYPES:
        try:
            Decimal(lexical)
        except InvalidOperation as exc:
            raise _compile_error("规则包含无效的数值") from exc
        return lexical
    if datatype == f"{_XSD}boolean":
        normalized = lexical.casefold()
        if normalized in {"true", "1"}:
            return "TRUE"
        if normalized in {"false", "0"}:
            return "FALSE"
        raise _compile_error("规则包含无效的布尔值")
    try:
        if datatype == f"{_XSD}date":
            date.fromisoformat(lexical)
        elif datatype == f"{_XSD}dateTime":
            datetime.fromisoformat(lexical.replace("Z", "+00:00"))
        elif datatype == f"{_XSD}time":
            time.fromisoformat(lexical.replace("Z", "+00:00"))
        else:
            raise _compile_error("规则包含不支持的字面量类型")
    except ValueError as exc:
        raise _compile_error("规则包含无效的日期时间值") from exc
    return _quote_text(lexical)


class GenericSqlCompiler:
    def compile(self, plan: QueryPlan) -> CompiledQuery:
        object_name = plan.object_binding.object_name
        namespace = plan.object_binding.physical_namespace
        table_sql = _quote_identifier(object_name)
        table_name = str(object_name)
        if namespace:
            table_sql = f"{_quote_identifier(namespace)}.{table_sql}"
            table_name = f"{namespace}.{object_name}"

        if not plan.selections:
            raise _compile_error("查询计划没有可编译的选择字段")
        selection_names = tuple(item.binding.field_name for item in plan.selections)
        select_sql = ", ".join(_quote_identifier(item) for item in selection_names)
        field_bindings = {
            item.semantic.uri: item.binding.field_name for item in plan.property_bindings
        }
        predicates = tuple(
            self._expression(rule.condition, field_bindings)
            for rule in sorted(
                (item for item in plan.rules if item.condition is not None),
                key=lambda item: (-item.priority, item.short_name.casefold(), item.uri),
            )
        )
        where = ""
        if predicates:
            where = " WHERE " + " AND ".join(predicates)
        sql = f"SELECT {select_sql} FROM {table_sql}{where};"
        return CompiledQuery(
            sql=sql,
            tables=(table_name,),
            fields=tuple(str(item) for item in selection_names),
            predicates=predicates,
        )

    def _expression(
        self,
        expression: RuleExpression,
        field_bindings: Mapping[str, str | None],
    ) -> str:
        operator = expression.operator
        if operator in {RuleOperator.ALL_OF, RuleOperator.ANY_OF}:
            if not expression.children:
                raise _compile_error("逻辑规则缺少子表达式")
            separator = " AND " if operator == RuleOperator.ALL_OF else " OR "
            return (
                "("
                + separator.join(
                    self._expression(child, field_bindings) for child in expression.children
                )
                + ")"
            )
        if operator == RuleOperator.NOT:
            if len(expression.children) != 1:
                raise _compile_error("NOT 规则必须只有一个子表达式")
            return f"NOT ({self._expression(expression.children[0], field_bindings)})"

        field_name = field_bindings.get(expression.property_uri or "")
        field = _quote_identifier(field_name)
        values = tuple(_literal(item) for item in expression.values)
        if operator in _COMPARISONS:
            if len(values) != 1:
                raise _compile_error("比较规则必须只有一个值")
            return f"{field} {_COMPARISONS[operator]} {values[0]}"
        if operator == RuleOperator.IN:
            if not values:
                raise _compile_error("IN 规则至少需要一个值")
            return f"{field} IN ({', '.join(values)})"
        if operator == RuleOperator.BETWEEN:
            if len(values) != 2:
                raise _compile_error("BETWEEN 规则必须有两个值")
            return f"{field} BETWEEN {values[0]} AND {values[1]}"
        if operator == RuleOperator.IS_NULL:
            if values:
                raise _compile_error("IS NULL 规则不能包含值")
            return f"{field} IS NULL"
        raise _compile_error("规则包含不支持的操作符")


class CompilerRegistry:
    def __init__(self, compilers: Mapping[str, SqlCompiler]) -> None:
        self._compilers = MappingProxyType(
            {key.strip().casefold(): value for key, value in compilers.items()}
        )

    @classmethod
    def default(cls) -> CompilerRegistry:
        generic = GenericSqlCompiler()
        return cls({"generic": generic, "ansi": generic})

    def get(self, dialect: str | None) -> SqlCompiler:
        key = (dialect or "generic").strip().casefold()
        try:
            return self._compilers[key]
        except KeyError as exc:
            raise _compile_error("没有可用于该方言的 SQL 编译器") from exc
