"""Deterministic Hive compilation for canonical relational plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ontology_core.compiler import _literal, _quote_identifier
from ontology_core.errors import OntologyCompileError
from ontology_core.inference_models import CandidateField, CandidateObject
from ontology_core.program_compiler import HiveProgramCompiler, ProgramTableNamer
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    LineageEdge,
    ProgramCompilationEvidence,
    ProgramStepKind,
)
from ontology_core.relational_plan import (
    AggregateNode,
    CanonicalRelationalPlan,
    FilterNode,
    FilterPredicate,
    JoinNode,
    LogicalColumnRef,
    MaterializeNode,
    ProjectNode,
    RelationalNode,
    ScanNode,
    UnionAllNode,
)
from ontology_core.semantic_models import RdfLiteral, RuleOperator

_COMPARISONS = {
    RuleOperator.EQ: "=",
    RuleOperator.NE: "<>",
    RuleOperator.GT: ">",
    RuleOperator.GTE: ">=",
    RuleOperator.LT: "<",
    RuleOperator.LTE: "<=",
}
_XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"


def _error(message: str) -> OntologyCompileError:
    return OntologyCompileError(message)


def _physical_table(object_: CandidateObject) -> str:
    _quote_identifier(object_.physical_name)
    if object_.physical_namespace:
        _quote_identifier(object_.physical_namespace)
        return f"{object_.physical_namespace}.{object_.physical_name}"
    return object_.physical_name


def _table_sql(object_: CandidateObject) -> str:
    name = _quote_identifier(object_.physical_name)
    if object_.physical_namespace:
        return f"{_quote_identifier(object_.physical_namespace)}.{name}"
    return name


def _column_sql(reference: LogicalColumnRef) -> str:
    return f"{_quote_identifier(reference.node_id)}.{_quote_identifier(reference.column)}"


class RelationalCompiler(Protocol):
    def compile(
        self,
        plan: CanonicalRelationalPlan,
        *,
        program_id: str,
    ) -> CompiledProgram:
        raise NotImplementedError


class HiveRelationalCompiler:
    platform = "hive"

    def __init__(self, namer: ProgramTableNamer | None = None) -> None:
        self._namer = namer or ProgramTableNamer()

    def compile(
        self,
        plan: CanonicalRelationalPlan,
        *,
        program_id: str,
    ) -> CompiledProgram:
        if plan.dialect.casefold() != self.platform:
            raise _error("关系计划当前没有可用的方言编译器")

        nodes = {item.node_id: item for item in plan.nodes}
        objects = {item.ref: item for item in plan.objects}
        schemas = self._derive_schemas(plan, objects)
        materializations = tuple(item for item in plan.nodes if isinstance(item, MaterializeNode))
        targets = {
            node.node_id: self._namer.target_for(program_id, index, node.step_kind)
            for index, node in enumerate(materializations, start=1)
        }
        statements: list[CompiledStatement] = []
        for node in materializations:
            target = targets[node.node_id]
            select_sql = self._compile_select(
                node.input,
                nodes=nodes,
                objects=objects,
                schemas=schemas,
                materialized_targets=targets,
                available_materializations={item.step_id for item in statements},
            )
            statements.append(
                CompiledStatement(
                    step_id=node.node_id,
                    target_table=target,
                    drop_sql=f"DROP TABLE IF EXISTS {target};",
                    create_sql=f"CREATE TABLE {target} AS\n{select_sql};",
                )
            )

        source_tables, fields = self._physical_evidence(plan, objects)
        lineage = self._lineage(plan, objects)
        result_target = targets[plan.result_node_id]
        intermediate_tables = tuple(
            targets[node.node_id]
            for node in materializations
            if node.step_kind == ProgramStepKind.INTERMEDIATE
        )
        sql = "\n\n".join(
            f"{statement.drop_sql}\n{statement.create_sql}" for statement in statements
        )
        program = CompiledProgram(
            program_id=program_id,
            dialect=self.platform,
            sql=sql,
            statements=tuple(statements),
            intermediate_tables=intermediate_tables,
            result_table=result_target,
            lineage=lineage,
            evidence=ProgramCompilationEvidence(
                source_tables=source_tables,
                fields=fields,
                temporal_decisions=(),
            ),
        )
        HiveProgramCompiler().validate_program(program)
        return program

    def _compile_select(
        self,
        result_input: str,
        *,
        nodes: dict[str, RelationalNode],
        objects: dict[str, CandidateObject],
        schemas: dict[str, dict[str, str]],
        materialized_targets: dict[str, str],
        available_materializations: set[str],
    ) -> str:
        ctes: list[str] = []
        compiled: set[str] = set()

        def compile_node(node_id: str) -> None:
            if node_id in compiled:
                return
            node = nodes[node_id]
            if isinstance(node, MaterializeNode):
                if node.node_id not in available_materializations:
                    raise _error("关系节点引用了尚未创建的物化结果")
                compiled.add(node_id)
                return
            for dependency in self._dependencies(node):
                compile_node(dependency)
            query = self._node_query(
                node,
                objects=objects,
                schemas=schemas,
                materialized_targets=materialized_targets,
            )
            ctes.append(f"{_quote_identifier(node.node_id)} AS (\n{query}\n)")
            compiled.add(node_id)

        compile_node(result_input)
        relation = self._relation_sql(result_input, materialized_targets)
        final_select = f"SELECT * FROM {relation}"
        if not ctes:
            return final_select
        joined_ctes = ",\n".join(ctes)
        return f"WITH\n{joined_ctes}\n{final_select}"

    def _node_query(
        self,
        node: RelationalNode,
        *,
        objects: dict[str, CandidateObject],
        schemas: dict[str, dict[str, str]],
        materialized_targets: dict[str, str],
    ) -> str:
        if isinstance(node, ScanNode):
            object_ = objects[node.object_ref]
            fields = {item.ref: item for item in object_.fields}
            selections = ", ".join(
                f"{_quote_identifier(fields[column.field_ref].physical_name)} "
                f"AS {_quote_identifier(column.name)}"
                for column in node.columns
            )
            return f"SELECT {selections}\nFROM {_table_sql(object_)}"

        if isinstance(node, UnionAllNode):
            branches = []
            for input_index, input_node in enumerate(node.inputs):
                alias = _quote_identifier(input_node)
                selections = ", ".join(
                    f"{alias}.{_quote_identifier(column.sources[input_index].column)} "
                    f"AS {_quote_identifier(column.name)}"
                    for column in node.columns
                )
                source = self._relation_sql(input_node, materialized_targets)
                branches.append(f"SELECT {selections} FROM {source} AS {alias}")
            return "\nUNION ALL\n".join(branches)

        if isinstance(node, JoinNode):
            left_alias = _quote_identifier(node.left_input)
            right_alias = _quote_identifier(node.right_input)
            selections = ", ".join(
                f"{_column_sql(column.source)} AS {_quote_identifier(column.name)}"
                for column in node.columns
            )
            conditions = [
                f"{_column_sql(condition.left)} = {_column_sql(condition.right)}"
                for condition in node.conditions
            ]
            conditions.extend(
                self._predicate_sql(predicate, schemas[predicate.column.node_id])
                for predicate in node.match_filters
            )
            join_sql = "INNER JOIN" if node.join_type == "inner" else "LEFT JOIN"
            left_source = self._relation_sql(node.left_input, materialized_targets)
            right_source = self._relation_sql(node.right_input, materialized_targets)
            query = (
                f"SELECT {selections}\n"
                f"FROM {left_source} AS {left_alias}\n"
                f"{join_sql} {right_source} AS {right_alias}\n"
                f"ON {' AND '.join(conditions)}"
            )
            if node.join_type == "anti":
                query += f"\nWHERE {_column_sql(node.conditions[0].right)} IS NULL"
            return query

        if isinstance(node, FilterNode):
            alias = _quote_identifier(node.input)
            source = self._relation_sql(node.input, materialized_targets)
            predicates = " AND ".join(
                self._predicate_sql(predicate, schemas[node.input]) for predicate in node.predicates
            )
            return f"SELECT {alias}.*\nFROM {source} AS {alias}\nWHERE {predicates}"

        if isinstance(node, ProjectNode):
            alias = _quote_identifier(node.input)
            source = self._relation_sql(node.input, materialized_targets)
            selections = ", ".join(
                f"{_column_sql(column.source)} AS {_quote_identifier(column.name)}"
                for column in node.columns
            )
            return f"SELECT {selections}\nFROM {source} AS {alias}"

        if isinstance(node, AggregateNode):
            alias = _quote_identifier(node.input)
            source = self._relation_sql(node.input, materialized_targets)
            group_selections = [
                f"{_column_sql(column.source)} AS {_quote_identifier(column.name)}"
                for column in node.group_by
            ]
            aggregate_selections = []
            for column in node.aggregations:
                argument = "*" if column.source is None else _column_sql(column.source)
                distinct = "DISTINCT " if column.distinct else ""
                aggregate_selections.append(
                    f"{column.function.upper()}({distinct}{argument}) "
                    f"AS {_quote_identifier(column.name)}"
                )
            selections = ", ".join((*group_selections, *aggregate_selections))
            query = f"SELECT {selections}\nFROM {source} AS {alias}"
            if node.group_by:
                query += "\nGROUP BY " + ", ".join(
                    _column_sql(column.source) for column in node.group_by
                )
            return query

        raise AssertionError(f"unsupported compiled node: {type(node)!r}")

    @staticmethod
    def _relation_sql(
        node_id: str,
        materialized_targets: dict[str, str],
    ) -> str:
        if node_id in materialized_targets:
            return _quote_identifier(materialized_targets[node_id])
        return _quote_identifier(node_id)

    @staticmethod
    def _dependencies(node: RelationalNode) -> tuple[str, ...]:
        if isinstance(node, ScanNode):
            return ()
        if isinstance(node, UnionAllNode):
            return tuple(dict.fromkeys(node.inputs))
        if isinstance(node, JoinNode):
            return (node.left_input, node.right_input)
        if isinstance(node, (FilterNode, ProjectNode, AggregateNode, MaterializeNode)):
            return (node.input,)
        raise AssertionError(f"unsupported relational node: {type(node)!r}")

    @staticmethod
    def _predicate_sql(predicate: FilterPredicate, schema: dict[str, str]) -> str:
        field = _column_sql(predicate.column)
        datatype = schema[predicate.column.column]
        values = tuple(
            _literal(RdfLiteral(lexical_form=value, datatype_uri=datatype))
            for value in predicate.values
        )
        if predicate.operator in _COMPARISONS:
            return f"{field} {_COMPARISONS[predicate.operator]} {values[0]}"
        if predicate.operator == RuleOperator.IN:
            return f"{field} IN ({', '.join(values)})"
        if predicate.operator == RuleOperator.BETWEEN:
            return f"{field} BETWEEN {values[0]} AND {values[1]}"
        if predicate.operator == RuleOperator.IS_NULL:
            return f"{field} IS NULL"
        raise _error("关系过滤条件包含不支持的操作符")

    @staticmethod
    def _derive_schemas(
        plan: CanonicalRelationalPlan,
        objects: dict[str, CandidateObject],
    ) -> dict[str, dict[str, str]]:
        schemas: dict[str, dict[str, str]] = {}
        for node in plan.nodes:
            if isinstance(node, ScanNode):
                fields = {item.ref: item for item in objects[node.object_ref].fields}
                schema = {
                    column.name: fields[column.field_ref].datatype_uri for column in node.columns
                }
            elif isinstance(node, UnionAllNode):
                schema = {
                    column.name: schemas[column.sources[0].node_id][column.sources[0].column]
                    for column in node.columns
                }
            elif isinstance(node, JoinNode):
                schema = {
                    column.name: schemas[column.source.node_id][column.source.column]
                    for column in node.columns
                }
            elif isinstance(node, FilterNode):
                schema = dict(schemas[node.input])
            elif isinstance(node, ProjectNode):
                schema = {
                    column.name: schemas[node.input][column.source.column]
                    for column in node.columns
                }
            elif isinstance(node, AggregateNode):
                schema = {
                    column.name: schemas[node.input][column.source.column]
                    for column in node.group_by
                }
                schema.update(
                    {
                        column.name: (
                            _XSD_INTEGER
                            if column.function == "count"
                            else schemas[node.input][column.source.column]  # type: ignore[union-attr]
                        )
                        for column in node.aggregations
                    }
                )
            elif isinstance(node, MaterializeNode):
                schema = dict(schemas[node.input])
            else:
                raise AssertionError(f"unsupported relational node: {type(node)!r}")
            schemas[node.node_id] = schema
        return schemas

    @staticmethod
    def _physical_evidence(
        plan: CanonicalRelationalPlan,
        objects: dict[str, CandidateObject],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        source_tables: set[str] = set()
        fields: set[str] = set()
        for node in plan.nodes:
            if not isinstance(node, ScanNode):
                continue
            object_ = objects[node.object_ref]
            object_fields: dict[str, CandidateField] = {item.ref: item for item in object_.fields}
            source_tables.add(_physical_table(object_))
            fields.update(object_fields[column.field_ref].physical_name for column in node.columns)
        return tuple(sorted(source_tables)), tuple(sorted(fields))

    @classmethod
    def _lineage(
        cls,
        plan: CanonicalRelationalPlan,
        objects: dict[str, CandidateObject],
    ) -> tuple[LineageEdge, ...]:
        edges: list[LineageEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for node in plan.nodes:
            if isinstance(node, ScanNode):
                sources = ((_physical_table(objects[node.object_ref]), "ontology_source"),)
            else:
                sources = tuple((dependency, "step") for dependency in cls._dependencies(node))
            for source, kind in sources:
                key = (source, node.node_id, kind)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(LineageEdge(source=source, target=node.node_id, kind=kind))
        return tuple(edges)


class RelationalCompilerRegistry:
    def __init__(self, compilers: Mapping[str, RelationalCompiler] | None = None) -> None:
        self._compilers: dict[str, RelationalCompiler] = {}
        for dialect, compiler in (compilers or {}).items():
            self.register(dialect, compiler)

    @classmethod
    def default(cls) -> RelationalCompilerRegistry:
        return cls({"hive": HiveRelationalCompiler()})

    def register(self, dialect: str, compiler: RelationalCompiler) -> None:
        key = dialect.strip().casefold()
        if not key:
            raise _error("关系编译方言不能为空")
        self._compilers[key] = compiler

    def get(self, dialect: str) -> RelationalCompiler:
        key = dialect.strip().casefold()
        try:
            return self._compilers[key]
        except KeyError as error:
            raise _error("没有可用于该方言的关系编译器") from error
