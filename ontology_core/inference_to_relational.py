"""Convert metadata-bound inference into a deterministic relational DAG."""

from __future__ import annotations

from pydantic import ValidationError

from ontology_core.errors import OntologyCompileError
from ontology_core.inference_models import ValidatedInferredProgram
from ontology_core.program_models import ProgramStepKind
from ontology_core.relation_evidence import RelationEvidenceGraph
from ontology_core.relational_plan import (
    AggregateColumn,
    AggregateNode,
    CanonicalRelationalPlan,
    DerivedColumn,
    FilterNode,
    FilterPredicate,
    JoinCondition,
    JoinNode,
    LogicalColumnRef,
    MaterializeNode,
    ProjectNode,
    ScanColumn,
    ScanNode,
    UnionAllNode,
    UnionColumn,
)


class InferenceRelationalAdapter:
    def convert(
        self, plan: ValidatedInferredProgram, relation_graph: RelationEvidenceGraph
    ) -> CanonicalRelationalPlan:
        try:
            return self._convert(plan, relation_graph)
        except (ValidationError, KeyError) as error:
            raise OntologyCompileError("候选语义不能绑定为合法统一关系计划") from error

    def _convert(self, plan, graph):
        objects = {obj.ref: obj for obj in plan.objects}
        if graph.package_sha256 != plan.package_sha256 or not set(objects).issubset(
            graph.object_refs
        ):
            raise OntologyCompileError("关系证据与计划的本体快照不一致")
        family_by_member = {
            member: family.ref for family in plan.families for member in family.member_refs
        }

        def key(ref):
            return family_by_member.get(ref, ref)

        for join in plan.joins:
            if graph.matching(join.left_field.ref, join.right_field.ref) is None:
                raise OntologyCompileError("关联条件缺少可核验的关系证据")
            if key(join.left_object_ref) == key(join.right_object_ref):
                raise OntologyCompileError("同一并集来源不能同时被当成关联双方")

        needed = {
            field.ref
            for field in (
                *plan.requested_fields,
                *plan.group_by_fields,
                *(join.left_field for join in plan.joins),
                *(join.right_field for join in plan.joins),
                *(item.field for item in plan.filters),
                *(item.partition_field for item in plan.temporal_decisions),
                *(item.source_field for item in plan.aggregations if item.source_field is not None),
            )
        }
        all_fields = {field.ref: field for obj in plan.objects for field in obj.fields}
        column_names: dict[str, str] = {}
        counter = 0
        for family in plan.families:
            members = [objects[member] for member in family.member_refs]
            names = sorted(
                {
                    all_fields[ref].physical_name
                    for ref in needed
                    if all_fields[ref].object_ref in family.member_refs
                }
            )
            for name in names:
                counter += 1
                for member in members:
                    field = next(
                        (field for field in member.fields if field.physical_name == name), None
                    )
                    if field is None:
                        raise OntologyCompileError("并集来源缺少必要字段")
                    needed.add(field.ref)
                    column_names[field.ref] = f"c_{counter:04d}"
        for ref in sorted(needed):
            if ref not in column_names:
                counter += 1
                column_names[ref] = f"c_{counter:04d}"

        directed_rights = {
            key(join.right_object_ref) for join in plan.joins if join.join_type != "inner"
        }
        anti_rights = {
            key(join.right_object_ref) for join in plan.joins if join.join_type == "anti"
        }
        nodes = []
        source_nodes: dict[str, str] = {}
        source_columns: dict[str, tuple[str, ...]] = {}
        member_nodes = {}
        filter_count = 0

        def predicate(node_id, field, operator, values):
            return FilterPredicate(
                column=LogicalColumnRef(node_id=node_id, column=column_names[field.ref]),
                operator=operator,
                values=values,
            )

        def temporal(node_id, decision):
            values = (
                (decision.resolved_start,)
                if decision.resolved_start == decision.resolved_end
                else (decision.resolved_start, decision.resolved_end)
            )
            return predicate(
                node_id, decision.partition_field, "eq" if len(values) == 1 else "between", values
            )

        for index, obj in enumerate(sorted(plan.objects, key=lambda obj: obj.ref), start=1):
            scan_id = f"scan_{index:02d}"
            fields = [field for field in obj.fields if field.ref in needed]
            if not fields:
                raise OntologyCompileError("候选来源没有必要字段，不能生成无意义扫描")
            columns = tuple(
                ScanColumn(name=column_names[field.ref], field_ref=field.ref) for field in fields
            )
            nodes.append(ScanNode(node_id=scan_id, object_ref=obj.ref, columns=columns))
            predicates = []
            for item in plan.filters:
                if item.field.object_ref == obj.ref and key(obj.ref) not in directed_rights:
                    predicates.append(predicate(scan_id, item.field, item.operator, item.values))
            for item in plan.temporal_decisions:
                if item.object_ref == obj.ref and (
                    key(obj.ref) not in directed_rights or obj.ref in family_by_member
                ):
                    predicates.append(temporal(scan_id, item))
            source_id = scan_id
            if predicates:
                filter_count += 1
                source_id = f"filter_{filter_count:02d}"
                nodes.append(
                    FilterNode(node_id=source_id, input=scan_id, predicates=tuple(predicates))
                )
            member_nodes[obj.ref] = source_id
            if obj.ref not in family_by_member:
                source_nodes[obj.ref] = source_id
                source_columns[obj.ref] = tuple(column.name for column in columns)

        for index, family in enumerate(plan.families, start=1):
            union_id = f"union_{index:02d}"
            inputs = tuple(member_nodes[member] for member in family.member_refs)
            names = tuple(
                sorted(
                    {
                        column_names[field.ref]
                        for field in objects[family.member_refs[0]].fields
                        if field.ref in needed
                    }
                )
            )
            nodes.append(
                UnionAllNode(
                    node_id=union_id,
                    inputs=inputs,
                    columns=tuple(
                        UnionColumn(
                            name=name,
                            sources=tuple(
                                LogicalColumnRef(node_id=input_id, column=name)
                                for input_id in inputs
                            ),
                        )
                        for name in names
                    ),
                )
            )
            materialized_id = f"family_{index:02d}"
            nodes.append(
                MaterializeNode(
                    node_id=materialized_id, input=union_id, step_kind=ProgramStepKind.INTERMEDIATE
                )
            )
            source_nodes[family.ref] = materialized_id
            source_columns[family.ref] = names

        roots = sorted(set(source_nodes) - directed_rights)
        if not roots:
            raise OntologyCompileError("左连接/排除连接缺少可保留主来源")
        root = next(
            (
                key(field.object_ref)
                for field in plan.requested_fields
                if key(field.object_ref) in roots
            ),
            roots[0],
        )
        visited = {root}
        current = source_nodes[root]
        carried = list(source_columns[root])
        remaining = set(source_nodes) - visited
        unused = list(plan.joins)
        join_count = 0
        while remaining:
            chosen = None
            for join in unused:
                left, right = key(join.left_object_ref), key(join.right_object_ref)
                if left in visited and right in remaining:
                    chosen = (join, right, join.left_field, join.right_field)
                    break
                if (
                    join.join_type == "inner"
                    and right in visited
                    and left in remaining
                    and left not in directed_rights
                ):
                    chosen = (join, left, join.right_field, join.left_field)
                    break
            if chosen is None:
                raise OntologyCompileError("候选关系不能形成合法连接树，拒绝笛卡尔积或反转方向")
            join, new_source, left_field, right_field = chosen
            if join.join_type == "inner" and new_source in directed_rights:
                raise OntologyCompileError("不能用内连接引入左连接/排除集合")
            right_input = source_nodes[new_source]
            match_filters = []
            if join.join_type != "inner":
                for item in plan.filters:
                    if key(item.field.object_ref) == new_source and item.scope == "match":
                        match_filters.append(
                            predicate(right_input, item.field, item.operator, item.values)
                        )
                    if (
                        key(item.field.object_ref) == new_source
                        and item.scope == "where"
                        and new_source in anti_rights
                    ):
                        raise OntologyCompileError("排除表不能提供连接后的 WHERE 条件")
                for item in plan.temporal_decisions:
                    if (
                        key(item.object_ref) == new_source
                        and item.object_ref not in family_by_member
                    ):
                        match_filters.append(temporal(right_input, item))
            join_count += 1
            join_id = f"join_{join_count:02d}"
            output = [
                DerivedColumn(name=name, source=LogicalColumnRef(node_id=current, column=name))
                for name in carried
            ]
            if join.join_type != "anti":
                output.extend(
                    DerivedColumn(
                        name=name, source=LogicalColumnRef(node_id=right_input, column=name)
                    )
                    for name in source_columns[new_source]
                )
                carried.extend(source_columns[new_source])
            nodes.append(
                JoinNode(
                    node_id=join_id,
                    left_input=current,
                    right_input=right_input,
                    join_type=join.join_type,
                    anti_strategy=join.anti_strategy,
                    conditions=(
                        JoinCondition(
                            left=LogicalColumnRef(
                                node_id=current, column=column_names[left_field.ref]
                            ),
                            right=LogicalColumnRef(
                                node_id=right_input, column=column_names[right_field.ref]
                            ),
                        ),
                    ),
                    match_filters=tuple(match_filters),
                    columns=tuple(output),
                )
            )
            current = join_id
            unused.remove(join)
            visited.add(new_source)
            remaining.remove(new_source)
        if unused:
            raise OntologyCompileError("关系图存在未编译关联条件")
        post_filters = [
            predicate(current, item.field, item.operator, item.values)
            for item in plan.filters
            if key(item.field.object_ref) in directed_rights and item.scope == "where"
        ]
        if post_filters:
            filter_count += 1
            filter_id = f"filter_{filter_count:02d}"
            nodes.append(
                FilterNode(node_id=filter_id, input=current, predicates=tuple(post_filters))
            )
            current = filter_id

        def derived(field):
            return DerivedColumn(
                name=field.physical_name,
                source=LogicalColumnRef(node_id=current, column=column_names[field.ref]),
            )

        if plan.aggregations:
            if not {field.ref for field in plan.requested_fields}.issubset(
                field.ref for field in plan.group_by_fields
            ):
                raise OntologyCompileError("聚合输出包含未分组明细字段")
            nodes.append(
                AggregateNode(
                    node_id="aggregate_01",
                    input=current,
                    group_by=tuple(derived(field) for field in plan.group_by_fields),
                    aggregations=tuple(
                        AggregateColumn(
                            name=item.name,
                            function=item.function,
                            distinct=item.distinct,
                            source=LogicalColumnRef(
                                node_id=current, column=column_names[item.source_field.ref]
                            )
                            if item.source_field
                            else None,
                        )
                        for item in plan.aggregations
                    ),
                )
            )
            current = "aggregate_01"
        else:
            nodes.append(
                ProjectNode(
                    node_id="project_01",
                    input=current,
                    columns=tuple(derived(field) for field in plan.requested_fields),
                )
            )
            current = "project_01"
        nodes.append(
            MaterializeNode(node_id="result", input=current, step_kind=ProgramStepKind.RESULT)
        )
        return CanonicalRelationalPlan(
            package_id=plan.package_id,
            package_version=plan.package_version,
            package_sha256=plan.package_sha256,
            data_source_ref=plan.data_source_ref,
            dialect=plan.dialect,
            objects=plan.objects,
            nodes=tuple(nodes),
            result_node_id="result",
            temporal_decisions=plan.temporal_decisions,
            inference_evidence=plan.evidence,
        )
