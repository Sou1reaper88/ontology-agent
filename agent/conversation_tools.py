"""Request-local, read-only capabilities. No model calls or SQL execution."""
import re
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from agent.ontology_shadow import get_ontology_runtime
from ontology_core.authored_sql import validate_authored_sql
from ontology_core.metadata_candidates import MetadataCandidateCatalog


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(default="", max_length=500)


class Search(Arguments):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=32)


class Objects(Arguments):
    object_refs: list[str] = Field(min_length=1, max_length=32)


class Fields(Objects):
    field_refs: list[str] = Field(default_factory=list, max_length=64)


class Business(Arguments):
    object_refs: list[str] = Field(default_factory=list, max_length=32)


class Validation(Arguments):
    sql: str = Field(min_length=1, max_length=200000)
    allow_cte: bool


TOOL_MODELS = {
    "search_tables": (Search, "按表名、表描述和字段线索检索已发布对象。返回候选而非强制选择。"),
    "read_fields": (Fields, "读取指定对象字段索引；指定field_refs时返回完整字段类型及描述。可直接使用已知对象引用或真实表名，无需先搜索。"),
    "get_field_mappings": (Fields, "读取指定对象/字段的物理表名、命名空间、数据源及字段映射；不推测关联关系。"),
    "get_business_context": (Business, "读取业务描述、已登记关系/口径、表族及默认账期；空关系不阻止生成，口径分析由你完成。可不指定对象仅获取全局时间。"),
    "validate_sql": (Validation, "只做Hive AST、来源字段、有限分区及安全校验，返回错误以供你按需修改；不执行、不重写、不调用模型。禁用CTE时传false。"),
}
TOOLS = [{"type": "function", "function": {
    "name": name, "description": description,
    "parameters": model.model_json_schema()}}
    for name, (model, description) in TOOL_MODELS.items()]


class ConversationTools:
    def __init__(self, *, program_id, request, system_time=None):
        self.program_id = program_id
        self.request = request
        self.now = (system_time if isinstance(system_time, datetime) else
                    datetime.fromisoformat(system_time) if system_time else datetime.now())
        self.catalog = None
        self.runtime = None
        self.allow_cte = True

    def defaults(self):
        return {"system_time": self.now.isoformat(),
                "default_partitions": {"P_DAY": (self.now - timedelta(days=2)).strftime("%Y%m%d"),
                    "P_MON": (self.now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")},
                "partition_conventions": {"_D": "P_DAY", "_M": "P_MON"},
                "temporary_table_prefix": f"temp_oa_{self.program_id}_",
                "result_table": f"temp_oa_{self.program_id}_result_table",
                "explicit_requirement_dates_take_precedence": True}

    def _load_catalog(self):
        self.runtime = get_ontology_runtime()
        return MetadataCandidateCatalog.from_snapshot(self.runtime.snapshot())

    def _catalog(self):
        if self.catalog is None:
            self.catalog = self._load_catalog()
        return self.catalog

    def package(self):
        if self.catalog is None or not hasattr(self.catalog, "snapshot"):
            return None
        info = self.catalog.snapshot.info
        return {"package_id": info.package_id, "version": info.version, "sha256": info.sha256}

    def check_snapshot(self):
        if self.runtime and self.runtime.snapshot().info.sha256 != self.catalog.snapshot.info.sha256:
            raise ValueError("本轮使用的本体版本已变化，请用新版本重新生成")

    def _objects(self, refs):
        result = []
        for ref in refs:
            matches = [o for o in self._catalog().objects if ref.casefold() in {
                o.ref.casefold(), o.physical_name.casefold(), self._table_name(o).casefold()}]
            if len(matches) != 1:
                raise ValueError(f"对象引用不存在或不唯一：{ref}")
            result.append(matches[0])
        return result

    @staticmethod
    def _table_name(obj):
        return f"{obj.physical_namespace + '.' if obj.physical_namespace else ''}{obj.physical_name}"

    def _selected_fields(self, args):
        objects = self._objects(args.object_refs)
        fields = [f for o in objects for f in o.fields]
        if args.field_refs:
            selected = []
            for requested in args.field_refs:
                matches = [f for f in fields if requested.casefold() in {
                    f.ref.casefold(), f.physical_name.casefold()}]
                if len(matches) != 1:
                    raise ValueError(f"字段引用或物理字段名不存在或不唯一：{requested}")
                if matches[0] not in selected:
                    selected.append(matches[0])
            fields = selected
        return objects, fields

    def execute(self, name, arguments):
        if name not in TOOL_MODELS:
            raise ValueError("unsupported tool")
        args = TOOL_MODELS[name][0].model_validate(arguments)
        if name == "search_tables":
            candidates = self._catalog().retrieve(args.query, object_limit=args.limit, field_limit_per_object=1)
            value = {"objects": [{"ref": o.ref, "label": o.label, "description": o.description,
                       "table": self._table_name(o), "family_ref": o.family_ref} for o in candidates.objects],
                     "families": [f.model_dump(mode="json") for f in candidates.families]}
        elif name in {"read_fields", "get_field_mappings"}:
            objects, fields = self._selected_fields(args)
            if name == "read_fields":
                value = {"fields": [f.model_dump(mode="json") if args.field_refs else {
                    "ref": f.ref, "object_ref": f.object_ref, "name": f.physical_name, "label": f.label}
                    for f in fields], "details_loaded": bool(args.field_refs)}
            else:
                value = {"mappings": [{"object_ref": o.ref, "table": self._table_name(o),
                    "data_source_ref": o.data_source_ref, "fields": [
                        {"ref": f.ref, "physical_name": f.physical_name} for f in fields if f.object_ref == o.ref]}
                    for o in objects]}
        elif name == "get_business_context":
            value = self.defaults()
            if args.object_refs:
                objects = self._objects(args.object_refs)
                snapshot = self._catalog().snapshot
                uris = {c.uri for c in snapshot.catalog.concepts if c.short_name in {o.ref for o in objects}}
                value.update(objects=[{"ref": o.ref, "description": o.description} for o in objects],
                    relations=[r.model_dump(mode="json") for r in snapshot.catalog.relations
                        if r.status == "active" and (r.source_concept_uri in uris or r.target_concept_uri in uris)],
                    rules=[r.model_dump(mode="json") for r in snapshot.catalog.rules
                        if r.status == "active" and r.applies_to_uri in uris],
                    families=[f.model_dump(mode="json") for f in self._catalog().families
                        if set(f.member_refs) & {o.ref for o in objects}])
        else:
            self.allow_cte = self.allow_cte and args.allow_cte
            try:
                artifact = self.validate(args.sql, allow_cte=args.allow_cte)
                value = {"valid": True, "statement_count": artifact["statement_count"],
                         "inference_evidence": artifact["inference_evidence"]}
            except ValueError as error:
                value = {"valid": False, "errors": [str(error)]}
        return {**value, "package": self.package()}, args.summary

    def validate(self, sql, *, allow_cte=True, assumptions=()):
        self.allow_cte = self.allow_cte and allow_cte
        # Reject mutation/CTE before touching storage; constants need no ontology.
        import sqlglot
        from sqlglot import exp
        from sqlglot.errors import ParseError
        try:
            parsed = sqlglot.parse(sql, read="hive")
        except ParseError as error:
            raise ValueError("Hive脚本无法解析") from error
        if not self.allow_cte and any(p is not None and p.find(exp.CTE) for p in parsed):
            raise ValueError("当前提示词禁止CTE")
        placeholder = re.compile(r"^(?:<[^<>]+>|\$\{[^{}]+\}|\{\{[^{}]+\}\}|TODO|TBD)$", re.I)
        if any(placeholder.fullmatch(item.this.strip()) for statement in parsed if statement is not None
               for item in statement.find_all(exp.Literal) if item.is_string):
            raise ValueError("SQL包含尚未替换的占位符，只能作为待确认草稿")
        if any(p is not None and not isinstance(p, (exp.Query, exp.Drop, exp.Create)) for p in parsed):
            raise ValueError("只允许只读查询或受限CTAS，禁止其他写操作")
        from types import SimpleNamespace
        catalog = self._catalog() if any(p is not None and p.find(exp.Table) for p in parsed) else SimpleNamespace(objects=())
        result = validate_authored_sql(sql, program_id=self.program_id, catalog=catalog,
                    request=self.request, allow_cte=self.allow_cte, assumptions=assumptions)
        self.check_snapshot()
        return result
