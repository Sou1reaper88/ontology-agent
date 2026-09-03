"""Deterministically compile validated metadata hypotheses into Hive CTAS."""

from __future__ import annotations

from ontology_core.compiler import _literal, _quote_identifier
from ontology_core.errors import OntologyCompileError
from ontology_core.inference_models import (
    CandidateField,
    CandidateObject,
    CandidateTableFamily,
    ValidatedInferenceTemporalDecision,
    ValidatedInferredFilter,
    ValidatedInferredJoin,
    ValidatedInferredProgram,
)
from ontology_core.program_compiler import HiveProgramCompiler, ProgramTableNamer
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    LineageEdge,
    ProgramCompilationEvidence,
    ProgramStepKind,
    TemporalCompilationEvidence,
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


def _error(message: str) -> OntologyCompileError:
    return OntologyCompileError(message)


def _physical_table(object_: CandidateObject) -> str:
    name = object_.physical_name
    _quote_identifier(name)
    if object_.physical_namespace:
        _quote_identifier(object_.physical_namespace)
        return f"{object_.physical_namespace}.{name}"
    return name


def _table_sql(object_: CandidateObject) -> str:
    name = _quote_identifier(object_.physical_name)
    if object_.physical_namespace:
        return f"{_quote_identifier(object_.physical_namespace)}.{name}"
    return name


def _field_sql(field: CandidateField, alias: str | None = None) -> str:
    name = _quote_identifier(field.physical_name)
    return f"{_quote_identifier(alias)}.{name}" if alias else name


def _value_sql(field: CandidateField, value: str) -> str:
    return _literal(
        RdfLiteral(
            lexical_form=value,
            datatype_uri=field.datatype_uri,
        )
    )


def _filter_sql(filter_: ValidatedInferredFilter, alias: str) -> str:
    field = _field_sql(filter_.field, alias)
    values = tuple(_value_sql(filter_.field, item) for item in filter_.values)
    if filter_.operator in _COMPARISONS and len(values) == 1:
        return f"{field} {_COMPARISONS[filter_.operator]} {values[0]}"
    if filter_.operator == RuleOperator.IN and values:
        return f"{field} IN ({', '.join(values)})"
    if filter_.operator == RuleOperator.BETWEEN and len(values) == 2:
        return f"{field} BETWEEN {values[0]} AND {values[1]}"
    if filter_.operator == RuleOperator.IS_NULL and not values:
        return f"{field} IS NULL"
    raise _error("候选过滤条件包含不支持的操作符或值数量")


def _temporal_sql(
    decision: ValidatedInferenceTemporalDecision,
    alias: str | None,
) -> str:
    field = _field_sql(decision.partition_field, alias)
    start = _value_sql(decision.partition_field, decision.resolved_start)
    end = _value_sql(decision.partition_field, decision.resolved_end)
    if decision.resolved_start == decision.resolved_end:
        return f"{field} = {start}"
    return f"{field} BETWEEN {start} AND {end}"


class HiveInferenceCompiler:
    """Compile only validated references; never accepts SQL fragments from the LLM."""

    def __init__(self, namer: ProgramTableNamer | None = None) -> None:
        self._namer = namer or ProgramTableNamer()

    def compile(
        self,
        plan: ValidatedInferredProgram,
        *,
        program_id: str,
    ) -> CompiledProgram:
        if plan.dialect.casefold() != "hive":
            raise _error("候选程序当前没有可用的方言编译器")
        objects_by_ref = {item.ref: item for item in plan.objects}
        family_by_member = {
            member: family.ref for family in plan.families for member in family.member_refs
        }
        decisions_by_object = {item.object_ref: item for item in plan.temporal_decisions}
        statements: list[CompiledStatement] = []
        lineage: list[LineageEdge] = []
        source_tables = {_physical_table(item) for item in plan.objects}
        family_targets: dict[str, str] = {}

        for family_index, family in enumerate(plan.families, start=1):
            step_id = f"family_{family_index:02d}"
            target = self._namer.target_for(
                program_id,
                family_index,
                ProgramStepKind.INTERMEDIATE,
            )
            create_sql = self._compile_family(
                family,
                plan,
                objects_by_ref,
                decisions_by_object,
                target,
            )
            statements.append(
                CompiledStatement(
                    step_id=step_id,
                    target_table=target,
                    drop_sql=f"DROP TABLE IF EXISTS {target};",
                    create_sql=create_sql,
                )
            )
            family_targets[family.ref] = target
            lineage.extend(
                LineageEdge(
                    source=_physical_table(objects_by_ref[member]),
                    target=step_id,
                    kind="ontology_source",
                )
                for member in family.member_refs
            )

        result_index = len(statements) + 1
        result_target = self._namer.target_for(
            program_id,
            result_index,
            ProgramStepKind.RESULT,
        )
        result_step_id = "result"
        result_create, result_lineage = self._compile_result(
            plan,
            objects_by_ref,
            family_by_member,
            family_targets,
            decisions_by_object,
            result_target,
            result_step_id,
        )
        statements.append(
            CompiledStatement(
                step_id=result_step_id,
                target_table=result_target,
                drop_sql=f"DROP TABLE IF EXISTS {result_target};",
                create_sql=result_create,
            )
        )
        lineage.extend(result_lineage)
        fields = {
            item.physical_name
            for item in (
                *plan.requested_fields,
                *(join.left_field for join in plan.joins),
                *(join.right_field for join in plan.joins),
                *(filter_.field for filter_ in plan.filters),
                *(item.partition_field for item in plan.temporal_decisions),
            )
        }
        temporal = tuple(
            TemporalCompilationEvidence(
                partition_property_ref=item.partition_field.ref,
                grain=item.grain.value,
                source=item.source,
                resolved_start=item.resolved_start,
                resolved_end=item.resolved_end,
                explanation=item.explanation,
            )
            for item in plan.temporal_decisions
        )
        sql = "\n\n".join(
            f"{item.drop_sql}\n{item.create_sql}" for item in statements
        )
        program = CompiledProgram(
            program_id=program_id,
            dialect=plan.dialect,
            sql=sql,
            statements=tuple(statements),
            intermediate_tables=tuple(item.target_table for item in statements[:-1]),
            result_table=result_target,
            lineage=tuple(lineage),
            evidence=ProgramCompilationEvidence(
                source_tables=tuple(sorted(source_tables)),
                fields=tuple(sorted(fields)),
                temporal_decisions=temporal,
                inference=plan.evidence,
            ),
        )
        HiveProgramCompiler().validate_program(program)
        return program

    def _compile_family(
        self,
        family: CandidateTableFamily,
        plan: ValidatedInferredProgram,
        objects_by_ref: dict[str, CandidateObject],
        decisions_by_object: dict[str, ValidatedInferenceTemporalDecision],
        target: str,
    ) -> str:
        members = tuple(objects_by_ref[ref] for ref in family.member_refs)
        needed = self._needed_family_fields(family, plan, members)
        queries: list[str] = []
        for member in members:
            available = {item.physical_name: item for item in member.fields}
            if any(name not in available for name in needed):
                raise _error("候选表族成员缺少编译所需字段")
            decision = decisions_by_object.get(member.ref)
            if decision is None:
                raise _error("候选表族成员缺少时间决策")
            selections = ", ".join(_quote_identifier(name) for name in needed)
            queries.append(
                f"SELECT {selections} FROM {_table_sql(member)} "
                f"WHERE {_temporal_sql(decision, None)}"
            )
        union_sql = "\nUNION ALL\n".join(queries)
        return f"CREATE TABLE {target} AS\n{union_sql};"

    @staticmethod
    def _needed_family_fields(
        family: CandidateTableFamily,
        plan: ValidatedInferredProgram,
        members: tuple[CandidateObject, ...],
    ) -> tuple[str, ...]:
        member_refs = set(family.member_refs)
        fields: list[CandidateField] = [
            item for item in plan.requested_fields if item.object_ref in member_refs
        ]
        fields.extend(
            item.field for item in plan.filters if item.field.object_ref in member_refs
        )
        for join in plan.joins:
            if join.left_object_ref in member_refs:
                fields.append(join.left_field)
            if join.right_object_ref in member_refs:
                fields.append(join.right_field)
        fields.extend(
            item.partition_field
            for item in plan.temporal_decisions
            if item.object_ref in member_refs
        )
        if not fields:
            fields.extend(members[0].fields)
        return tuple(sorted({item.physical_name for item in fields}))

    def _compile_result(
        self,
        plan: ValidatedInferredProgram,
        objects_by_ref: dict[str, CandidateObject],
        family_by_member: dict[str, str],
        family_targets: dict[str, str],
        decisions_by_object: dict[str, ValidatedInferenceTemporalDecision],
        result_target: str,
        result_step_id: str,
    ) -> tuple[str, tuple[LineageEdge, ...]]:
        logical_keys = [item.ref for item in plan.families]
        logical_keys.extend(
            item.ref for item in plan.objects if item.ref not in family_by_member
        )
        logical_keys = list(dict.fromkeys(logical_keys))
        aliases = {key: f"t{index}" for index, key in enumerate(logical_keys)}

        def key_for_object(ref: str) -> str:
            return family_by_member.get(ref, ref)

        def source_sql(key: str) -> str:
            if key in family_targets:
                source = _quote_identifier(family_targets[key])
            else:
                source = _table_sql(objects_by_ref[key])
            return f"{source} AS {_quote_identifier(aliases[key])}"

        selections = ", ".join(
            _field_sql(item, aliases[key_for_object(item.object_ref)])
            for item in plan.requested_fields
        )
        if not selections:
            raise _error("候选程序没有可编译的输出字段")
        first = logical_keys[0]
        from_sql = source_sql(first)
        visited = {first}
        remaining = set(logical_keys[1:])
        usable_joins = tuple(
            item
            for item in plan.joins
            if key_for_object(item.left_object_ref) != key_for_object(item.right_object_ref)
        )
        while remaining:
            selected: tuple[ValidatedInferredJoin, str] | None = None
            for join in usable_joins:
                left = key_for_object(join.left_object_ref)
                right = key_for_object(join.right_object_ref)
                if left in visited and right in remaining:
                    selected = (join, right)
                    break
                if right in visited and left in remaining:
                    selected = (join, left)
                    break
            if selected is None:
                raise _error("候选程序连接图不完整，拒绝生成笛卡尔积")
            join, new_key = selected
            left_alias = aliases[key_for_object(join.left_object_ref)]
            right_alias = aliases[key_for_object(join.right_object_ref)]
            condition = (
                f"{_field_sql(join.left_field, left_alias)} = "
                f"{_field_sql(join.right_field, right_alias)}"
            )
            from_sql += f" INNER JOIN {source_sql(new_key)} ON {condition}"
            visited.add(new_key)
            remaining.remove(new_key)

        predicates = [
            _filter_sql(
                item,
                aliases[key_for_object(item.field.object_ref)],
            )
            for item in plan.filters
        ]
        predicates.extend(
            _temporal_sql(item, aliases[item.object_ref])
            for item in plan.temporal_decisions
            if item.object_ref not in family_by_member
        )
        where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
        create_sql = (
            f"CREATE TABLE {result_target} AS\n"
            f"SELECT {selections} FROM {from_sql}{where};"
        )
        lineage: list[LineageEdge] = []
        for key in logical_keys:
            if key in family_targets:
                family_index = next(
                    index
                    for index, family in enumerate(plan.families, start=1)
                    if family.ref == key
                )
                lineage.append(
                    LineageEdge(
                        source=f"family_{family_index:02d}",
                        target=result_step_id,
                        kind="step",
                    )
                )
            else:
                lineage.append(
                    LineageEdge(
                        source=_physical_table(objects_by_ref[key]),
                        target=result_step_id,
                        kind="ontology_source",
                    )
                )
        return create_sql, tuple(lineage)

