"""Validate model-authored scripts without rendering or executing their SQL."""

import re
from datetime import datetime

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from ontology_core.inference_models import InferenceEvidence
from ontology_core.program_compiler import HiveProgramCompiler
from ontology_core.program_models import CompiledProgram, CompiledStatement, ProgramCompilationEvidence


def _name(table):
    if not isinstance(table, exp.Table):
        raise ValueError("DDL目标必须是表名")
    return ".".join(part.name for part in table.parts).casefold()


def _bounds(node, alias, partition):
    """AND combines bounds; every OR branch must remain bounded."""
    if node is None:
        return set()
    if isinstance(node, exp.Paren):
        return _bounds(node.this, alias, partition)
    if isinstance(node, (exp.And, exp.Or)):
        left, right = _bounds(node.this, alias, partition), _bounds(node.expression, alias, partition)
        return left | right if isinstance(node, exp.And) else left & right
    column = node.this
    if not isinstance(column, exp.Column) or column.table.casefold() != alias.casefold() or column.name.casefold() != partition.casefold():
        return set()
    values = (node.args.get("low"), node.args.get("high")) if isinstance(node, exp.Between) else (
        tuple(node.expressions) if isinstance(node, exp.In) else (node.expression,))
    if not values or not all(isinstance(v, exp.Literal) and re.fullmatch(r"\d{6}|\d{8}", v.this) for v in values):
        return set()
    try:
        for value in values:
            if partition.upper().replace("_", "") == "PMON" and len(value.this) != 6:
                return set()
            if partition.upper().replace("_", "") == "PDAY" and len(value.this) != 8:
                return set()
            datetime.strptime(value.this, "%Y%m%d" if len(value.this) == 8 else "%Y%m")
    except ValueError:
        return set()
    if isinstance(node, (exp.EQ, exp.In, exp.Between)):
        return {"lower", "upper"}
    if isinstance(node, (exp.GT, exp.GTE)):
        return {"lower"}
    if isinstance(node, (exp.LT, exp.LTE)):
        return {"upper"}
    return set()


def validate_authored_program(sql, *, program_id, catalog, request="", allow_cte=True, assumptions=()):
    if not isinstance(sql, str) or len(sql) > 200000:
        raise ValueError("脚本为空或超过校验大小限制")
    try:
        parsed = sqlglot.parse(sql, read="hive")
    except ParseError as error:
        raise ValueError("Hive脚本无法解析") from error
    if not parsed or len(parsed) % 2 or any(p is None for p in parsed):
        raise ValueError("每步必须是DROP/CREATE配对，禁止末尾清理")
    if not allow_cte and any(p.find(exp.CTE) for p in parsed):
        raise ValueError("当前提示词禁止CTE，请改用物理中间表或子查询")
    raw, start = [], 0
    for token in sqlglot.Dialect.get_or_raise("hive").tokenize(sql):
        if token.token_type == sqlglot.tokens.TokenType.SEMICOLON:
            raw.append(sql[start:token.end + 1].strip())
            start = token.end + 1
    if sql[start:].strip():
        raw.append(sql[start:].strip())
    if len(raw) != len(parsed):
        raise ValueError("脚本语句边界不明确")
    objects = {f"{o.physical_namespace + '.' if o.physical_namespace else ''}{o.physical_name}".casefold(): o
               for o in catalog.objects}
    known = dict(objects)
    for obj in catalog.objects:
        if sum(o.physical_name.casefold() == obj.physical_name.casefold() for o in catalog.objects) == 1:
            known[obj.physical_name.casefold()] = obj
    schemas, statements, sources, external = {}, [], set(), set()
    for index in range(0, len(parsed), 2):
        drop, create = parsed[index:index + 2]
        if not isinstance(drop, exp.Drop) or not isinstance(create, exp.Create):
            raise ValueError("只允许临时表DROP TABLE IF EXISTS / CREATE TABLE AS SELECT")
        target = _name(create.this)
        if not re.fullmatch(rf"temp_oa_{re.escape(program_id)}_[a-z0-9_]+", target):
            raise ValueError("DDL目标只能是当前请求命名空间内的临时表")
        if _name(drop.this) != target or not drop.args.get("exists") or drop.args.get("kind") != "TABLE" or create.args.get("kind") != "TABLE" or not isinstance(create.expression, exp.Query):
            raise ValueError("DROP/CREATE目标或CTAS语句不符合约束")
        if drop.args.get("cascade") or create.args.get("replace") or create.args.get("properties"):
            raise ValueError("不允许额外DDL属性或覆盖操作")
        query = create.expression.copy()
        normalized_schema, source_objects = {}, {}
        # ponytail: normalize identifiers only on the validation copy; never rewrite the delivered script.
        for scope in traverse_scope(query):
            for alias, (_, table) in scope.selected_sources.items():
                if not isinstance(table, exp.Table):  # CTE/subquery, not a physical source.
                    continue
                name = _name(table)
                obj = known.get(name)
                columns = schemas.get(name)
                if obj is not None:
                    columns = {f.physical_name: "STRING" for f in obj.fields}
                    sources.add(name)
                elif columns is None:
                    if name.startswith("temp_oa_") or not re.search(rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?![A-Za-z0-9_.])", request, re.I):
                        raise ValueError(f"来源表未在本体或用户明确指定的外部表中：{name}")
                    external.add(name)
                    # External fields are declarations, not verified ontology facts.
                    columns = {c.name: "STRING" for c in scope.columns if not c.table or c.table.casefold() == alias.casefold()}
                key = f"source_{len(normalized_schema)}"
                normalized_schema[key] = columns
                source_objects[key] = obj
                table.set("this", exp.to_identifier(key))
                table.set("db", None)
                table.set("catalog", None)
                table.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
        try:
            checked = qualify(query, dialect="hive", schema=normalized_schema, infer_schema=False,
                              quote_identifiers=False, identify=False)
        except OptimizeError as error:
            raise ValueError("字段不存在、引用歧义或中间表输出字段不匹配：" + str(error)) from error
        for scope in traverse_scope(checked):
            for alias, (_, table) in scope.selected_sources.items():
                if not isinstance(table, exp.Table):
                    continue
                obj = source_objects.get(table.name)
                if obj is None:
                    continue
                suffix = obj.physical_name.upper()
                partition = "P_DAY" if suffix.endswith("_D") else "P_MON" if suffix.endswith("_M") else None
                if obj.temporal_policy:
                    partition = next(f.physical_name for f in obj.fields if f.ref == obj.temporal_policy.partition_field_ref)
                if not partition:
                    continue
                where = scope.expression.args.get("where")
                bounds = _bounds(where.this if where else None, alias, partition)
                for join in scope.expression.args.get("joins") or []:
                    side, kind = str(join.args.get("side") or "").upper(), str(join.args.get("kind") or "").upper()
                    if (not side and kind not in {"ANTI", "SEMI"}) or (side == "LEFT" and join.this.alias_or_name.casefold() == alias.casefold()):
                        bounds |= _bounds(join.args.get("on"), alias, partition)
                if bounds != {"lower", "upper"}:
                    raise ValueError(f"来源表{obj.physical_name}缺少有限{partition}分区范围（WHERE或适用JOIN ON）")
        schemas[target] = {name: "STRING" for name in checked.named_selects}
        statements.append(CompiledStatement(step_id=f"step_{index // 2 + 1:02d}", target_table=target,
                                             drop_sql=raw[index], create_sql=raw[index + 1]))
    reasons = tuple(assumptions) or ("模型依据需求与已发布元数据直接编写SQL；静态校验不证明业务口径正确",)
    unresolved = tuple(f"外部表{name}的字段未经本体验证" for name in sorted(external))
    program = CompiledProgram(program_id=program_id, dialect="hive", sql=sql, statements=tuple(statements),
                              intermediate_tables=tuple(s.target_table for s in statements[:-1]),
                              result_table=statements[-1].target_table,
                              evidence=ProgramCompilationEvidence(source_tables=tuple(sorted(sources)),
                                  inference=InferenceEvidence(overall_confidence="medium", reasons=reasons,
                                                              unresolved_items=unresolved)))
    HiveProgramCompiler().validate_program(program)  # Reuse safety checks, never .compile().
    return program
