"""Deterministic Hive CTAS program compilation and AST safety validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ontology_core.compiler import GenericSqlCompiler
from ontology_core.errors import OntologyCompileError
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    LineageEdge,
    ProgramCompilationEvidence,
    ProgramStep,
    ProgramStepKind,
    SqlProgramPlan,
    TemporalCompilationEvidence,
)
from ontology_core.query_plan import BoundObject

_UNSAFE_PROGRAM_ID = re.compile(r"[^a-z0-9_]+")
_DUPLICATE_UNDERSCORE = re.compile(r"_+")


def _compile_error(message: str) -> OntologyCompileError:
    return OntologyCompileError(message)


class ProgramTableNamer:
    """Assign stable materialization targets without accepting business names."""

    def target_for(
        self,
        program_id: str,
        step_index: int,
        kind: ProgramStepKind,
    ) -> str:
        normalized = _DUPLICATE_UNDERSCORE.sub(
            "_",
            _UNSAFE_PROGRAM_ID.sub("_", program_id.strip().casefold()),
        ).strip("_")[:48]
        if not normalized:
            raise _compile_error("程序标识无法生成安全目标表名")
        if step_index < 1 or step_index > 99:
            raise _compile_error("程序步骤序号超出支持范围")
        if kind == ProgramStepKind.RESULT:
            return f"temp_oa_{normalized}_result_table"
        return f"temp_oa_{normalized}_{step_index:02d}"


class ProgramCompiler(Protocol):
    def compile(self, plan: SqlProgramPlan) -> CompiledProgram: ...


class HiveProgramCompiler:
    platform = "hive"

    def __init__(
        self,
        query_compiler: GenericSqlCompiler | None = None,
        namer: ProgramTableNamer | None = None,
    ) -> None:
        self._query_compiler = query_compiler or GenericSqlCompiler()
        self._namer = namer or ProgramTableNamer()

    def compile(self, plan: SqlProgramPlan) -> CompiledProgram:
        targets = {
            step.step_id: self._namer.target_for(plan.program_id, index, step.kind)
            for index, step in enumerate(plan.steps, start=1)
        }
        statements: list[CompiledStatement] = []
        lineage: list[LineageEdge] = []
        source_tables: set[str] = set()
        fields: set[str] = set()
        relations: set[str] = set()
        rules: set[str] = set()
        temporal_decisions: list[TemporalCompilationEvidence] = []
        for step in plan.steps:
            overrides = self._source_overrides(step, targets)
            compiled_query = self._query_compiler.compile(
                step.query_plan,
                source_table_overrides=overrides,
            )
            target = targets[step.step_id]
            select_sql = compiled_query.sql.strip().rstrip(";")
            drop_sql = f"DROP TABLE IF EXISTS {target};"
            create_sql = f"CREATE TABLE {target} AS\n{select_sql};"
            statements.append(
                CompiledStatement(
                    step_id=step.step_id,
                    target_table=target,
                    drop_sql=drop_sql,
                    create_sql=create_sql,
                )
            )
            for binding in step.source_bindings:
                if binding.source_step_id is not None:
                    lineage.append(
                        LineageEdge(
                            source=binding.source_step_id,
                            target=step.step_id,
                            kind="step",
                        )
                    )
                    continue
                object_ = self._object_for_ref(step, binding.object_ref)
                physical = self._physical_table(object_)
                source_tables.add(physical)
                lineage.append(
                    LineageEdge(
                        source=physical,
                        target=step.step_id,
                        kind="ontology_source",
                    )
                )
            fields.update(compiled_query.fields)
            relations.update(item.relation.uri for item in step.query_plan.joins)
            rules.update(item.uri for item in step.query_plan.rules)
            temporal_decisions.extend(
                TemporalCompilationEvidence(
                    partition_property_ref=item.partition_property_uri,
                    grain=item.grain.value,
                    source=("default" if item.source.value == "ontology_default" else "user"),
                    resolved_start=item.resolved_start,
                    resolved_end=item.resolved_end,
                    explanation=item.explanation,
                )
                for item in step.query_plan.temporal_decisions
            )
        result_table = targets[plan.result_step_id]
        intermediate_tables = tuple(
            targets[item.step_id]
            for item in plan.steps
            if item.kind == ProgramStepKind.INTERMEDIATE
        )
        sql = "\n\n".join(
            f"{item.drop_sql}\n{item.create_sql}" for item in statements
        )
        program = CompiledProgram(
            program_id=plan.program_id,
            dialect=plan.dialect,
            sql=sql,
            statements=tuple(statements),
            intermediate_tables=intermediate_tables,
            result_table=result_table,
            lineage=tuple(lineage),
            evidence=ProgramCompilationEvidence(
                source_tables=tuple(sorted(source_tables)),
                fields=tuple(sorted(fields)),
                relations=tuple(sorted(relations)),
                rules=tuple(sorted(rules)),
                temporal_decisions=tuple(temporal_decisions),
            ),
        )
        self.validate_program(program)
        return program

    def validate_program(self, program: CompiledProgram) -> None:
        try:
            parsed = sqlglot.parse(program.sql, read="hive")
        except ParseError as error:
            raise _compile_error("Hive 程序包含无法解析的语句") from error
        if len(parsed) != len(program.statements) * 2:
            raise _compile_error("Hive 程序语句数量或配对关系无效")
        targets = tuple(item.target_table for item in program.statements)
        target_keys = {item.casefold() for item in targets}
        source_keys = {item.casefold() for item in program.evidence.source_tables}
        source_table_names = {item.rsplit(".", maxsplit=1)[-1] for item in source_keys}
        if target_keys & (source_keys | source_table_names):
            raise _compile_error("本体源表不能作为程序 DDL 目标")
        created: set[str] = set()
        for index, statement in enumerate(program.statements):
            drop = parsed[index * 2]
            create = parsed[index * 2 + 1]
            expected = statement.target_table.casefold()
            if (
                not isinstance(drop, exp.Drop)
                or drop.args.get("kind") != "TABLE"
                or not drop.args.get("exists")
                or self._table_name(drop.this).casefold() != expected
            ):
                raise _compile_error("Hive 程序 DROP 语句不符合安全约束")
            if (
                not isinstance(create, exp.Create)
                or create.args.get("kind") != "TABLE"
                or not isinstance(create.expression, exp.Query)
                or self._table_name(create.this).casefold() != expected
            ):
                raise _compile_error("Hive 程序 CREATE TABLE AS SELECT 语句无效")
            for table in create.expression.find_all(exp.Table):
                source = self._table_name(table).casefold()
                if source in target_keys and source not in created:
                    raise _compile_error("程序步骤引用了尚未创建的目标表")
                if source.startswith("temp_oa_") and source not in created:
                    raise _compile_error("程序步骤包含悬空的系统表引用")
            created.add(expected)
        if created != target_keys:
            raise _compile_error("Hive 程序没有完整创建所有目标表")

    @classmethod
    def _source_overrides(
        cls,
        step: ProgramStep,
        targets: Mapping[str, str],
    ) -> dict[str, str]:
        overrides: dict[str, str] = {}
        for binding in step.source_bindings:
            if binding.source_step_id is None:
                continue
            try:
                target = targets[binding.source_step_id]
            except KeyError as error:
                raise _compile_error("程序步骤引用了未知前置步骤") from error
            object_ = cls._object_for_ref(step, binding.object_ref)
            overrides[object_.semantic.uri] = target
        return overrides

    @staticmethod
    def _object_for_ref(step: ProgramStep, object_ref: str) -> BoundObject:
        matches = tuple(
            item
            for item in step.query_plan.objects
            if object_ref in {item.semantic.uri, item.semantic.short_name, item.semantic.label}
        )
        if len(matches) != 1:
            raise _compile_error("步骤来源对象没有唯一的本体绑定")
        return matches[0]

    @staticmethod
    def _physical_table(object_: BoundObject) -> str:
        object_name = object_.binding.object_name
        if object_name is None:
            raise _compile_error("对象映射缺少物理表名")
        namespace = object_.binding.physical_namespace
        return f"{namespace}.{object_name}" if namespace else object_name

    @staticmethod
    def _table_name(table: exp.Expression) -> str:
        if not isinstance(table, exp.Table):
            raise _compile_error("DDL 目标不是有效表标识")
        parts = tuple(part.name for part in table.parts)
        return ".".join(parts)


class ProgramCompilerRegistry:
    def __init__(self, compilers: Mapping[str, ProgramCompiler] | None = None) -> None:
        self._compilers: dict[str, ProgramCompiler] = {}
        for dialect, compiler in (compilers or {}).items():
            self.register(dialect, compiler)

    @classmethod
    def default(cls) -> ProgramCompilerRegistry:
        return cls({"hive": HiveProgramCompiler()})

    def register(self, dialect: str, compiler: ProgramCompiler) -> None:
        key = dialect.strip().casefold()
        if not key:
            raise _compile_error("程序编译方言不能为空")
        self._compilers[key] = compiler

    def get(self, dialect: str) -> ProgramCompiler:
        key = dialect.strip().casefold()
        try:
            return self._compilers[key]
        except KeyError as error:
            raise _compile_error("没有可用于该方言的程序编译器") from error
