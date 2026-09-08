# 本体包管理与多表评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成一个 Python 本体包工作台，使用户能原子导入多张 TSV/XLSX 元数据表，维护对象、字段、直接关系和表级时间策略，显式发布或回滚不可变 RDF 版本，并让影子 SQL 安全消费单表及一条直接关系驱动的双表查询。

**Architecture:** 新增 `ontology_core.management`，以结构化 JSON 草稿作为编辑事实源，以外部文件型 `DraftStore` 提供修订号并发控制和原子替换；发布器把草稿确定性构建为固定六文件 RDF 包，经现有 `OntologyRepository` 校验后写入不可变版本并切换激活指针与运行时快照。FastAPI 新路由和 React 工作台只调用管理服务，不再把旧 MySQL 元数据当作 RDF 事实源；Planner/QueryPlan/Compiler 仅消费已发布快照，并对最多两表、唯一直接关系、等值 `INNER JOIN` 和每表有界账期执行失败关闭。

**Tech Stack:** Python 3.11+、Pydantic v2、FastAPI、RDFLib 7.6、PySHACL 0.40、openpyxl 3.1、pytest、React 18、TypeScript 5.5、Ant Design 5、Vite 5、Git

## Global Constraints

- 管理根目录必须由 `ONTOLOGY__MANAGEMENT_ROOT` 显式提供，规范化后位于应用 Git 工作树之外；未配置或位于工作树内时管理写接口失败关闭。
- 真实上传文件、表名、字段名、字段描述、草稿、诊断和发布包不得进入 Git；测试只使用合成业务标识符。
- DataSource 与 PhysicalMapping 不得保存主机、端口、用户名、密码、Token、Secret 或连接字符串。
- 首期只接收 UTF-8 `.tsv`/`.txt` 和无宏 `.xlsx`；拒绝 `.xls`、`.xlsm`、外部链接、未知扩展名、空文件和超限压缩内容。
- 普通新增导入遇到任意批内重复或草稿内重复时整体拒绝；不跳过、不覆盖、不合并、不部分写入。
- 预览不修改草稿；确认必须绑定工作区、输入摘要、短期单次令牌和 `expected_revision`，成功只增加一次修订号。
- 草稿保存和校验不得改变 Agent；只有显式发布或回滚才能切换运行时快照。
- 发布版本号唯一且不可复用，版本目录不允许就地修改；发布失败时激活指针和运行时快照保持旧值。
- 每张需要分区保护的表必须显式配置分区字段、日/月粒度、默认算法及查询覆盖开关；不使用 Agent 全局时间默认值。
- 双表规划只支持同一数据源上的一条已启用、已确认、映射完整的直接关系和等值 `INNER JOIN`；歧义、多跳、三表以上、非等值和外连接全部失败关闭。
- 双表中的每张分区表都必须生成有界时间过滤；任一分区表不安全时不生成 SQL。
- 已认证用户只能读取发布摘要；“本体维护者”与“全省管理员”可编辑草稿；只有“全省管理员”可发布、回滚或执行破坏性草稿操作。
- API 不返回服务器绝对路径、原始上传内容、完整草稿文件或 TTL；错误只包含稳定 code、安全 message 和脱敏 details。
- 每个逻辑改动先按 TDD 验证再自动 Git 提交；不自动推送或合并。功能完成后先启动服务供用户体验，不执行额外多轮审查。
- 遇到非简单难点、架构取舍或阶段完成时更新工程日志；只记录可验证事实，不记录真实业务标识符。

---

## File Structure

- Create `ontology_core/management/__init__.py`: 导出管理子系统的稳定公共接口。
- Create `ontology_core/management/models.py`: 工作区草稿、对象、字段、关系、时间策略、诊断、导入会话和版本摘要冻结 DTO。
- Create `ontology_core/management/paths.py`: 外部根目录边界、路径穿越、符号链接/reparse point 和文件大小安全检查。
- Create `ontology_core/management/store.py`: `DraftStore` 协议、文件实现、工作区锁、稳定 JSON 与原子替换。
- Create `ontology_core/management/parsers.py`: 多对象 TSV/TXT 与安全 XLSX 解析适配器。
- Create `ontology_core/management/imports.py`: 预览、重复检测、摘要绑定、令牌过期/单次使用和批量原子确认。
- Create `ontology_core/management/editor.py`: 对象/字段描述、关系、时间策略和诊断处置的修订号受控写入。
- Create `ontology_core/management/validation.py`: 草稿快速校验和发布前完整诊断聚合。
- Create `ontology_core/management/builder.py`: 多对象草稿到固定六文件 RDF 包的确定性构建。
- Create `ontology_core/management/publisher.py`: 不可变版本、激活指针、运行时协调切换、恢复和回滚。
- Create `ontology_core/management/service.py`: API 使用的应用服务门面和公开摘要。
- Modify `ontology_core/semantic_models.py`: 为关系增加已确认关联字段、基数、状态和优先级语义。
- Modify `ontology_core/semantic_parser.py`: 解析新增关系谓词并校验属性端点引用。
- Modify `ontology_core/resources/core.ttl`: 声明关系关联字段、基数、状态和优先级谓词。
- Modify `ontology_core/resources/shapes.ttl`: 校验新增关系谓词类型和最大基数，同时保持旧包可读取。
- Modify `ontology_core/resolver.py`: 提供唯一直接关系解析。
- Modify `ontology_core/query_plan.py`: 使用对象绑定和结构化 JOIN 表示最多两表计划。
- Modify `ontology_core/planner.py`: 从查询属性识别一或两个概念，解析关系并对每个对象应用时间安全门。
- Modify `ontology_core/compiler.py`: 编译带别名的单表或双表结构化 SQL。
- Modify `agent/ontology_shadow.py`: 支持原子安装快照、激活版本恢复及双表/关系/多时间证据。
- Modify `config/settings.py`: 增加管理根、工作区、上传限制、令牌 TTL 和角色配置。
- Modify `pyproject.toml`: 显式声明 `openpyxl>=3.1,<4`。
- Create `auth/ontology_roles.py`: 本体读取、维护和管理权限依赖。
- Create `api/schemas/ontology_packages.py`: 管理 API 请求/响应模型。
- Create `api/routes/ontology_packages.py`: 独立 `/ontology-packages` 管理 API。
- Modify `api/main.py`: 注册新路由，并把激活本体有效性纳入就绪状态。
- Create `frontend/src/features/ontology-package/types.ts`: 工作区、导入、诊断和版本 TypeScript 类型。
- Create `frontend/src/features/ontology-package/api.ts`: 新管理 API 客户端。
- Create `frontend/src/features/ontology-package/OntologyWorkbench.tsx`: 工作台状态、刷新和修订冲突协调。
- Create `frontend/src/features/ontology-package/ImportPanel.tsx`: 多文件预览和确认导入。
- Create `frontend/src/features/ontology-package/ObjectPanel.tsx`: 对象、字段搜索与描述编辑。
- Create `frontend/src/features/ontology-package/RelationPanel.tsx`: 直接关系与关联键维护。
- Create `frontend/src/features/ontology-package/TemporalPanel.tsx`: 表级完整时间策略维护。
- Create `frontend/src/features/ontology-package/DiagnosticsPanel.tsx`: 诊断筛选与待确认处置。
- Create `frontend/src/features/ontology-package/VersionPanel.tsx`: 校验、发布历史和回滚。
- Modify `frontend/src/pages/Ontology.tsx`: 仅装载新工作台并标明旧 MySQL 页面已退出事实源链路。
- Create `tests/ontology_management/`: 管理模型、存储、导入、编辑、校验、构建、发布、API 和权限测试。
- Modify `tests/ontology_core/`: 关系解析、QueryPlan、Planner 和 Compiler 双表测试。
- Modify `tests/test_ontology_shadow.py`: 热切换、回滚、双表关系和每表时间证据测试。
- Modify `docs/project-journal/2026-08.md`: 记录多表治理、原子发布和安全 JOIN 的真实难点与证据。
- Modify `docs/career/project-story.md`: 只把本轮已验证成果提炼为转岗 Agent 开发的项目素材。

---

### Task 1: 管理配置、草稿模型与路径边界

**Files:**
- Modify: `config/settings.py:82-91`
- Modify: `pyproject.toml:10-30`
- Create: `ontology_core/management/__init__.py`
- Create: `ontology_core/management/models.py`
- Create: `ontology_core/management/paths.py`
- Test: `tests/ontology_management/test_models.py`
- Test: `tests/ontology_management/test_paths.py`

**Interfaces:**
- Produces: `OntologySettings.management_root: str`, `management_workspace: str`, `import_token_ttl_seconds: int`, `max_upload_bytes: int`, `max_xlsx_uncompressed_bytes: int`
- Produces: frozen `WorkspaceDraft`, `DraftDataSource`, `DraftObject`, `DraftField`, `DraftRelation`, `DraftTemporalPolicy`, `DraftDiagnostic`, `DiagnosticDisposition`, `ImportSession`, `VersionSummary`, `UploadLimits`
- Produces: `resolve_management_root(configured: str, repository_root: Path) -> Path`
- Produces: `safe_child(root: Path, *parts: str) -> Path`

- [ ] **Step 1: Write failing model and deterministic serialization tests**

Create a synthetic workspace with two objects and assert IDs, ordering and revision bounds:

```python
def test_workspace_draft_serializes_objects_and_fields_deterministically() -> None:
    draft = synthetic_workspace(objects=(synthetic_object("Z_TABLE"), synthetic_object("A_TABLE")))
    payload = draft.canonical_json()
    assert payload.index('"A_TABLE"') < payload.index('"Z_TABLE"')
    assert WorkspaceDraft.model_validate_json(payload).revision == 0


def test_relation_requires_distinct_existing_endpoint_ids_at_model_boundary() -> None:
    with pytest.raises(ValidationError):
        DraftRelation(
            id="relation/same",
            source_object_id="object/a",
            source_field_id="field/a/id",
            target_object_id="object/a",
            target_field_id="field/a/id",
            cardinality="many_to_one",
            confirmed=True,
        )
```

- [ ] **Step 2: Run model tests and verify RED**

Run: `pytest tests/ontology_management/test_models.py -q`

Expected: FAIL because `ontology_core.management.models` does not exist.

- [ ] **Step 3: Implement frozen draft DTOs and canonical JSON**

Use explicit types and stable sorting rather than untyped dictionaries:

```python
class DraftRelation(FrozenModel):
    id: str
    label: str
    source_object_id: str
    source_field_id: str
    target_object_id: str
    target_field_id: str
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    status: Literal["active", "inactive"] = "active"
    priority: int = 100
    confirmed: bool = False


class DraftTemporalPolicy(FrozenModel):
    object_id: str
    partition_field_id: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True
    status: Literal["active", "inactive"] = "active"
    priority: int = 100


class WorkspaceDraft(FrozenModel):
    workspace_id: str
    display_name: str
    package_id: str
    base_uri: str
    revision: int = Field(ge=0)
    updated_at: datetime
    data_source: DraftDataSource
    objects: tuple[DraftObject, ...] = ()
    relations: tuple[DraftRelation, ...] = ()
    temporal_policies: tuple[DraftTemporalPolicy, ...] = ()
    dispositions: tuple[DiagnosticDisposition, ...] = ()

    def canonical_json(self) -> str:
        normalized = self.model_copy(update={
            "objects": tuple(sorted(self.objects, key=lambda item: item.id)),
            "relations": tuple(sorted(self.relations, key=lambda item: item.id)),
            "temporal_policies": tuple(sorted(self.temporal_policies, key=lambda item: item.object_id)),
        })
        return normalized.model_dump_json(indent=2, exclude_none=True) + "\n"
```

Add model validators for unique object/field IDs, one active temporal policy per object, distinct relation endpoints and day/month strategy pairing.

- [ ] **Step 4: Write failing path and configuration tests**

Cover blank root, root inside repository, `..`, absolute child segments, symlink/reparse point traversal and a valid sibling root:

```python
def test_management_root_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(OntologyManagementConfigurationError, match="Git 工作树之外"):
        resolve_management_root(str(repository / ".local"), repository)


def test_safe_child_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, "..", "outside")
```

- [ ] **Step 5: Implement settings, dependency and path guards**

Add these exact configuration fields and dependency:

```python
class OntologySettings(BaseSettings):
    base_url: str = ""
    ontology_id: str = ""
    timeout_seconds: int = 30
    retry_times: int = 2
    package_path: str = ""
    shadow_enabled: bool = True
    management_root: str = ""
    management_workspace: str = "evaluation"
    import_token_ttl_seconds: int = 900
    max_upload_bytes: int = 20 * 1024 * 1024
    max_xlsx_uncompressed_bytes: int = 100 * 1024 * 1024
    maintainer_roles: tuple[str, ...] = ("本体维护者", "全省管理员")
    administrator_roles: tuple[str, ...] = ("全省管理员",)
```

In `pyproject.toml`, add `"openpyxl>=3.1,<4"`. Resolve paths with `Path.resolve(strict=False)`, `os.path.commonpath`, `Path.is_symlink()` and `Path.is_junction()` where available; never return the configured root if it is blank or inside the repository.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_models.py tests/ontology_management/test_paths.py -q
ruff check config/settings.py ontology_core/management tests/ontology_management/test_models.py tests/ontology_management/test_paths.py
black --check config/settings.py ontology_core/management tests/ontology_management/test_models.py tests/ontology_management/test_paths.py
```

Expected: all focused tests and checks pass.

- [ ] **Step 7: Commit**

```powershell
git add -- pyproject.toml config/settings.py ontology_core/management tests/ontology_management/test_models.py tests/ontology_management/test_paths.py
git commit -m "feat: 建立本体管理草稿模型与路径边界"
```

---

### Task 2: 文件 DraftStore、修订冲突与原子写入

**Files:**
- Create: `ontology_core/management/store.py`
- Test: `tests/ontology_management/test_store.py`

**Interfaces:**
- Consumes: `WorkspaceDraft.canonical_json()`, `safe_child(...)`
- Produces: `DraftStore.read(workspace_id: str) -> WorkspaceDraft`
- Produces: `DraftStore.commit(workspace_id: str, expected_revision: int, mutate: Callable[[WorkspaceDraft], WorkspaceDraft]) -> WorkspaceDraft`
- Produces: `FileDraftStore.create_workspace(draft: WorkspaceDraft) -> WorkspaceDraft`
- Produces: `FileDraftStore.read_import_session(...)`, `write_import_session(...)`, `consume_import_session(...)`

- [ ] **Step 1: Write failing store tests**

Cover first creation, read, one-revision commit, stale revision `409` domain error, callback failure, `os.replace` failure and concurrent writers:

```python
def test_commit_is_atomic_and_increments_revision_once(tmp_path: Path) -> None:
    store = FileDraftStore(tmp_path)
    store.create_workspace(synthetic_workspace())
    before = (tmp_path / "workspaces/evaluation/draft.json").read_bytes()

    updated = store.commit("evaluation", 0, lambda draft: draft.model_copy(update={"display_name": "评测包"}))

    assert updated.revision == 1
    assert store.read("evaluation").display_name == "评测包"
    assert before != (tmp_path / "workspaces/evaluation/draft.json").read_bytes()


def test_stale_revision_leaves_draft_bytes_unchanged(tmp_path: Path) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)
    with pytest.raises(DraftRevisionConflict) as exc_info:
        store.commit("evaluation", 9, lambda draft: draft)
    assert exc_info.value.details["current_revision"] == 0
    assert draft_bytes(tmp_path) == before
```

- [ ] **Step 2: Run store tests and verify RED**

Run: `pytest tests/ontology_management/test_store.py -q`

Expected: FAIL because `FileDraftStore` is not defined.

- [ ] **Step 3: Implement lock-scoped copy-on-write store**

Define a protocol and file implementation. Commit must construct the complete candidate before touching the original:

```python
class DraftStore(Protocol):
    def read(self, workspace_id: str) -> WorkspaceDraft: ...
    def commit(
        self,
        workspace_id: str,
        expected_revision: int,
        mutate: Callable[[WorkspaceDraft], WorkspaceDraft],
    ) -> WorkspaceDraft: ...


def commit(self, workspace_id: str, expected_revision: int, mutate: Callable[[WorkspaceDraft], WorkspaceDraft]) -> WorkspaceDraft:
    with self._lock_for(workspace_id):
        current = self.read(workspace_id)
        if current.revision != expected_revision:
            raise DraftRevisionConflict(current_revision=current.revision)
        candidate = mutate(current).model_copy(update={
            "revision": current.revision + 1,
            "updated_at": datetime.now(UTC),
        })
        self._atomic_write(self._draft_path(workspace_id), candidate.canonical_json().encode("utf-8"))
        return candidate
```

`_atomic_write` writes a randomly named sibling file with `open(..., "xb")`, flushes and `os.fsync`, then calls `os.replace`; on failure it removes only the verified sibling temporary file. Import sessions use one JSON file per SHA-256 token hash and never persist the bearer token.

- [ ] **Step 4: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_store.py -q
ruff check ontology_core/management/store.py tests/ontology_management/test_store.py
black --check ontology_core/management/store.py tests/ontology_management/test_store.py
```

Expected: all store atomicity and concurrency tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ontology_core/management/store.py tests/ontology_management/test_store.py
git commit -m "feat: 实现本体草稿原子存储"
```

---

### Task 3: 多对象 TSV/XLSX 安全解析

**Files:**
- Create: `ontology_core/management/parsers.py`
- Modify: `ontology_core/tabular_metadata.py:73-150`
- Test: `tests/ontology_management/test_parsers.py`

**Interfaces:**
- Consumes: existing `FieldMetadata`, `TableMetadata`, `ImportDiagnostic`
- Produces: `ParsedUpload(file_name: str, sha256: str, objects: tuple[DraftObject, ...], diagnostics: tuple[DraftDiagnostic, ...])`
- Produces: `parse_metadata_upload(file_name: str, content: bytes, limits: UploadLimits) -> ParsedUpload`
- Produces: `parse_tabular_objects(text: str, source_name: str) -> tuple[TabularMetadataDraft, ...]`

- [ ] **Step 1: Write failing multi-object TSV tests**

Use one synthetic TSV containing three interleaved objects. Assert aggregation, source row locations, stable ID generation and no single-object error:

```python
def test_tsv_parser_groups_three_objects_atomically() -> None:
    parsed = parse_metadata_upload("objects.tsv", THREE_OBJECTS_TSV.encode("utf-8"), LIMITS)
    assert [item.physical_name for item in parsed.objects] == [
        "DEMO_ACCOUNT_M", "DEMO_CUSTOMER_M", "DEMO_ORDER_D"
    ]
    assert sum(len(item.fields) for item in parsed.objects) == 8
    assert not any(item.code == "multiple_objects" for item in parsed.diagnostics)
```

- [ ] **Step 2: Write failing XLSX and hostile archive tests**

Generate in-memory `.xlsx` fixtures with openpyxl. Cover multiple sheets, multiple objects in one sheet, `data_only=True`, unknown headers, macro member, `xl/externalLinks/`, oversized uncompressed members and `.xlsm` rejection:

```python
def test_xlsx_rejects_external_links_before_workbook_load() -> None:
    payload = synthetic_xlsx_with_member("xl/externalLinks/externalLink1.xml", b"<externalLink/>")
    with pytest.raises(UnsafeUploadError, match="外部链接"):
        parse_metadata_upload("objects.xlsx", payload, LIMITS)
```

- [ ] **Step 3: Run parser tests and verify RED**

Run: `pytest tests/ontology_management/test_parsers.py -q`

Expected: FAIL because `parse_metadata_upload` does not exist.

- [ ] **Step 4: Implement format dispatch and object aggregation**

Decode TSV with strict UTF-8, normalize only comparison keys, preserve physical identifier case and group rows by case-folded object name:

```python
def parse_metadata_upload(file_name: str, content: bytes, limits: UploadLimits) -> ParsedUpload:
    suffix = Path(file_name).suffix.casefold()
    if not content or len(content) > limits.max_upload_bytes:
        raise UnsafeUploadError("上传文件为空或超过大小限制")
    if suffix in {".tsv", ".txt"}:
        drafts = parse_tabular_objects(content.decode("utf-8", errors="strict"), file_name)
    elif suffix == ".xlsx":
        _inspect_xlsx_archive(content, limits)
        drafts = _parse_xlsx(content, file_name)
    else:
        raise UnsafeUploadError("仅支持 TSV、TXT 和无宏 XLSX")
    return _to_parsed_upload(file_name, hashlib.sha256(content).hexdigest(), drafts)
```

Load XLSX with `load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)`. Before loading, inspect every ZIP member, reject encrypted entries, macro files, external-link members, suspicious compression ratios and aggregate uncompressed size above the configured limit. Close every workbook in `finally`.

- [ ] **Step 5: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_parsers.py tests/ontology_core/test_tabular_metadata.py -q
ruff check ontology_core/management/parsers.py ontology_core/tabular_metadata.py tests/ontology_management/test_parsers.py
black --check ontology_core/management/parsers.py ontology_core/tabular_metadata.py tests/ontology_management/test_parsers.py
```

Expected: new multi-object tests and existing single-object import tests all pass.

- [ ] **Step 6: Commit**

```powershell
git add -- pyproject.toml ontology_core/tabular_metadata.py ontology_core/management/parsers.py tests/ontology_management/test_parsers.py
git commit -m "feat: 安全解析多对象元数据文件"
```

---

### Task 4: 导入预览、重复阻断与单次原子确认

**Files:**
- Create: `ontology_core/management/imports.py`
- Test: `tests/ontology_management/test_imports.py`

**Interfaces:**
- Consumes: `FileDraftStore`, `parse_metadata_upload(...)`, `WorkspaceDraft`
- Produces: `BatchImportService.preview(workspace_id: str, expected_revision: int, uploads: Sequence[UploadPayload]) -> ImportPreview`
- Produces: `BatchImportService.confirm(workspace_id: str, token: str, expected_revision: int) -> WorkspaceDraft`
- Produces: stable error codes `duplicate_object_in_batch`, `duplicate_object_in_draft`, `import_token_expired`, `import_token_used`, `import_digest_mismatch`

- [ ] **Step 1: Write failing preview and duplicate tests**

Assert that three unique objects produce one token, while duplicates inside one file, across files or against the draft return `blocked` without a token:

```python
def test_any_duplicate_blocks_whole_preview_without_draft_mutation(tmp_path: Path) -> None:
    service, store = import_service(tmp_path)
    before = store.read("evaluation").canonical_json()
    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(upload("one.tsv", TABLE_A), upload("two.tsv", TABLE_A)),
    )
    assert preview.status == "blocked"
    assert preview.token is None
    assert {item.code for item in preview.diagnostics} == {"duplicate_object_in_batch"}
    assert store.read("evaluation").canonical_json() == before
```

- [ ] **Step 2: Write failing confirmation security tests**

Cover stale revision, wrong workspace, expired token, changed canonical candidate digest, token reuse and injected store failure. In every failure, compare draft bytes and revision before/after.

- [ ] **Step 3: Run import tests and verify RED**

Run: `pytest tests/ontology_management/test_imports.py -q`

Expected: FAIL because `BatchImportService` is not defined.

- [ ] **Step 4: Implement preview without mutation**

Define physical identity exactly once:

```python
def physical_identity(draft: WorkspaceDraft, object_: DraftObject) -> tuple[str, str, str]:
    return (
        normalize_text(draft.data_source.id),
        normalize_text(draft.data_source.physical_namespace),
        normalize_text(object_.physical_name),
    )
```

Parse all uploads first, sort candidates deterministically, collect every diagnostic, and only issue `secrets.token_urlsafe(32)` when no `error` exists. Persist the token hash, candidate canonical payload hash, workspace, expected revision, expiration and normalized candidates; do not retain original file bytes.

- [ ] **Step 5: Implement confirmation as one DraftStore commit**

Confirmation validates the session under the workspace lock and appends all objects in one mutation:

```python
def confirm(self, workspace_id: str, token: str, expected_revision: int) -> WorkspaceDraft:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = self._store.read_import_session(workspace_id, token_hash)
    self._validate_session(session, workspace_id, expected_revision)

    def append_all(current: WorkspaceDraft) -> WorkspaceDraft:
        self._assert_no_duplicates(current, session.objects)
        return current.model_copy(update={"objects": (*current.objects, *session.objects)})

    updated = self._store.commit(workspace_id, expected_revision, append_all)
    self._store.consume_import_session(workspace_id, token_hash)
    return updated
```

Mark a successful token consumed atomically. If token cleanup fails after the draft commit, keep a committed-revision marker in the session so retries return `import_token_used` rather than importing twice.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_imports.py -q
ruff check ontology_core/management/imports.py tests/ontology_management/test_imports.py
black --check ontology_core/management/imports.py tests/ontology_management/test_imports.py
```

Expected: unique batches commit once; every duplicate and token failure preserves original draft bytes.

- [ ] **Step 7: Commit**

```powershell
git add -- ontology_core/management/imports.py tests/ontology_management/test_imports.py
git commit -m "feat: 实现多表导入预览与原子确认"
```

---

### Task 5: 草稿编辑、引用保护与诊断处置

**Files:**
- Create: `ontology_core/management/editor.py`
- Create: `ontology_core/management/validation.py`
- Test: `tests/ontology_management/test_editor.py`
- Test: `tests/ontology_management/test_validation.py`

**Interfaces:**
- Consumes: `DraftStore.commit(...)`
- Produces: `DraftEditor.update_object(...)`, `update_field(...)`, `upsert_relation(...)`, `delete_relation(...)`, `upsert_temporal_policy(...)`, `delete_draft_object(...)`, `resolve_diagnostic(...)`
- Produces: `DraftValidator.validate(draft: WorkspaceDraft) -> tuple[DraftDiagnostic, ...]`
- Produces: `DraftValidator.assert_publishable(draft: WorkspaceDraft) -> tuple[DraftDiagnostic, ...]`

- [ ] **Step 1: Write failing edit and revision tests**

Verify descriptions can change without changing stable IDs, relation edits require fields to belong to endpoints, time policies require an owned mapped field, and every successful call increments one revision:

```python
def test_editing_description_preserves_stable_identity() -> None:
    editor, store = initialized_editor()
    before = store.read("evaluation").objects[0]
    updated = editor.update_object("evaluation", before.id, expected_revision=0, label="客户", description="客户主数据")
    after = updated.objects[0]
    assert after.id == before.id
    assert after.physical_name == before.physical_name
    assert updated.revision == 1
```

- [ ] **Step 2: Write failing deletion and diagnostic disposition tests**

Assert referenced objects/fields cannot be deleted; published object IDs cannot be deleted through ordinary editing; `confirmation_required` is blocking until a disposition contains actor, explanation and timestamp.

- [ ] **Step 3: Run editor/validator tests and verify RED**

Run: `pytest tests/ontology_management/test_editor.py tests/ontology_management/test_validation.py -q`

Expected: FAIL because editor and validator are not defined.

- [ ] **Step 4: Implement copy-on-write editor operations**

Every operation accepts `expected_revision`, locates stable IDs exactly and delegates one mutation to the store. Relation creation must be explicit and initially unconfirmed unless the request says `confirmed=True`:

```python
def upsert_relation(self, workspace_id: str, relation: DraftRelation, expected_revision: int) -> WorkspaceDraft:
    def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
        self._require_relation_endpoints(draft, relation)
        retained = tuple(item for item in draft.relations if item.id != relation.id)
        return draft.model_copy(update={"relations": (*retained, relation)})
    return self._store.commit(workspace_id, expected_revision, mutate)
```

- [ ] **Step 5: Implement stable diagnostics and publish gate**

Generate a diagnostic ID from `code + sorted related IDs`, not from mutable text. Cover duplicate IDs, invalid identifiers/types, relation endpoint ownership, type compatibility, missing confirmation, temporal ownership/mapping, conflicting active strategies, blank descriptions and unconfigured optional metadata:

```python
def assert_publishable(self, draft: WorkspaceDraft) -> tuple[DraftDiagnostic, ...]:
    diagnostics = self.validate(draft)
    blocking = tuple(item for item in diagnostics if item.severity in {"error", "confirmation_required"} and not self._is_resolved(draft, item))
    if blocking:
        raise DraftNotPublishableError(diagnostics=blocking)
    return diagnostics
```

Resolved confirmation records remain tied to the diagnostic stable ID; if referenced semantic IDs change, a new diagnostic ID is produced and must be confirmed again.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_editor.py tests/ontology_management/test_validation.py -q
ruff check ontology_core/management/editor.py ontology_core/management/validation.py tests/ontology_management/test_editor.py tests/ontology_management/test_validation.py
black --check ontology_core/management/editor.py ontology_core/management/validation.py tests/ontology_management/test_editor.py tests/ontology_management/test_validation.py
```

Expected: all revision, reference, diagnostic and deletion safety tests pass.

- [ ] **Step 7: Commit**

```powershell
git add -- ontology_core/management/editor.py ontology_core/management/validation.py tests/ontology_management/test_editor.py tests/ontology_management/test_validation.py
git commit -m "feat: 支持本体草稿编辑与诊断治理"
```

---

### Task 6: 关系 RDF 语义与多对象六文件构建

**Files:**
- Create: `ontology_core/management/builder.py`
- Modify: `ontology_core/metadata_package.py:62-316`
- Modify: `ontology_core/semantic_models.py:65-68`
- Modify: `ontology_core/semantic_parser.py:984-1022,1571-1581`
- Modify: `ontology_core/resources/core.ttl`
- Modify: `ontology_core/resources/shapes.ttl:50-63`
- Modify: `ontology_core/vocabulary.py`
- Test: `tests/ontology_management/test_builder.py`
- Modify: `tests/ontology_core/test_semantic_parser.py`
- Modify: `tests/ontology_core/test_semantic_models.py`

**Interfaces:**
- Consumes: publishable `WorkspaceDraft`
- Produces: `PackageBuilder.build(draft: WorkspaceDraft, target: Path, version: str) -> OntologySnapshot`
- Produces: extended `Relation.source_property_uri`, `target_property_uri`, `cardinality`, `status`, `priority`, `confirmed`

- [ ] **Step 1: Write failing relation semantic parser tests**

Add synthetic Turtle with two concepts, two key properties and one relation. Assert every structural field survives parsing and unknown/misowned property references fail:

```python
def test_relation_preserves_confirmed_physical_join_semantics() -> None:
    catalog = parse_catalog(graph_with_direct_relation())
    relation = catalog.relations[0]
    assert relation.source_property_uri.endswith("/CustomerId")
    assert relation.target_property_uri.endswith("/OrderCustomerId")
    assert relation.cardinality == "one_to_many"
    assert relation.status == "active"
    assert relation.priority == 100
    assert relation.confirmed is True
```

- [ ] **Step 2: Write failing deterministic multi-object builder tests**

Build the same three-object draft twice into separate directories. Assert six exact files, equal semantic graph canonicalization, three concepts, all fields, one data source, one relation, two time policies and no credential predicates. Also assert a blocking draft produces no target directory.

- [ ] **Step 3: Run semantic and builder tests and verify RED**

Run: `pytest tests/ontology_management/test_builder.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_semantic_models.py -q`

Expected: FAIL because relation fields and `PackageBuilder` are absent.

- [ ] **Step 4: Extend RDF vocabulary, shape and parser**

Declare and parse `oa:sourceProperty`, `oa:targetProperty`, `oa:cardinality`, `oa:status`, `oa:priority` and `oa:confirmed`. Keep source/target property optional at generic SHACL level so old valid packages still load, but require them in `DraftValidator` for managed active relations. Validate referenced properties exist and belong to the relation concepts before constructing:

```python
class Relation(SemanticElement):
    source_concept_uri: str
    target_concept_uri: str
    source_property_uri: str | None = None
    target_property_uri: str | None = None
    cardinality: str | None = None
    status: str = "active"
    priority: int = 0
    confirmed: bool = False
```

- [ ] **Step 5: Implement deterministic workspace package builder**

Reuse `_uri`, `_datatype`, `_add_element_text` and graph serialization helpers from `metadata_package.py`, but generate all concepts/mappings into one graph set. Use stable IDs from the draft for URI suffixes. Add one DataSource, one object mapping per object, one field mapping per field, one RDF relation per draft relation and one temporal policy per configured object:

```python
class PackageBuilder:
    def build(self, draft: WorkspaceDraft, target: Path, version: str) -> OntologySnapshot:
        self._validator.assert_publishable(draft)
        initialize_package(target, package_id=draft.package_id, base_uri=draft.base_uri, version=version)
        self._write_graph(target / "domain.ttl", self._domain_graph(draft))
        self._write_graph(target / "mappings.ttl", self._mappings_graph(draft))
        self._write_graph(target / "rules.ttl", self._rules_graph(draft))
        repository = OntologyRepository()
        repository.publish(target)
        return repository.current()
```

The caller always provides a new staging directory; `build` refuses any non-empty target. Keep `generate_metadata_package` backward compatible by adapting a single `TabularMetadataDraft` to the same graph helpers.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_builder.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_repository.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_semantic_models.py -q
ruff check ontology_core/management/builder.py ontology_core/metadata_package.py ontology_core/semantic_models.py ontology_core/semantic_parser.py tests/ontology_management/test_builder.py
black --check ontology_core/management/builder.py ontology_core/metadata_package.py ontology_core/semantic_models.py ontology_core/semantic_parser.py tests/ontology_management/test_builder.py
```

Expected: managed multi-object and existing single-object packages all validate and load.

- [ ] **Step 7: Commit**

```powershell
git add -- ontology_core/management/builder.py ontology_core/metadata_package.py ontology_core/semantic_models.py ontology_core/semantic_parser.py ontology_core/resources/core.ttl ontology_core/resources/shapes.ttl ontology_core/vocabulary.py tests/ontology_management/test_builder.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_semantic_models.py
git commit -m "feat: 构建多对象关系本体包"
```

---

### Task 7: 不可变发布、热加载、启动恢复与回滚

**Files:**
- Create: `ontology_core/management/publisher.py`
- Modify: `agent/ontology_shadow.py:84-100,256-266`
- Test: `tests/ontology_management/test_publisher.py`
- Modify: `tests/test_ontology_shadow.py`

**Interfaces:**
- Consumes: `PackageBuilder.build(...)`, `FileDraftStore`, `OntologySnapshot`
- Produces: `OntologyRuntime.install(snapshot: OntologySnapshot) -> None`
- Produces: `OntologyRuntime.health() -> RuntimeHealth`
- Produces: `PackagePublisher.publish(workspace_id: str, version: str, release_notes: str, expected_revision: int, actor: str) -> VersionSummary`
- Produces: `PackagePublisher.rollback(workspace_id: str, version: str, reason: str, actor: str) -> VersionSummary`
- Produces: `PackagePublisher.recover(workspace_id: str) -> RuntimeHealth`
- Produces: process-wide `get_ontology_runtime() -> OntologyRuntime`, shared by Publisher and `OntologyShadowService`

- [ ] **Step 1: Write failing publisher success and immutability tests**

Assert candidate validation occurs before version activation, version reuse is rejected, a successful publish writes six files and `active-version.json`, and the runtime immediately returns the new snapshot without restart.

- [ ] **Step 2: Write failing crash-boundary and rollback tests**

Inject failures during build, repository validation, version-directory rename and active-pointer write. Assert old pointer and old runtime remain unchanged. Then publish two valid versions, roll back to the first, and assert no version directory bytes changed.

```python
def test_pointer_failure_keeps_old_runtime_and_active_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher, runtime = published_v1(tmp_path)
    old_sha = runtime.snapshot().info.sha256
    monkeypatch.setattr(publisher, "_write_active_pointer", raising_os_error)
    with pytest.raises(OntologyPublishError):
        publisher.publish("evaluation", "1.1.0", "second", 1, "tester")
    assert runtime.snapshot().info.sha256 == old_sha
    assert publisher.active_version("evaluation").version == "1.0.0"
```

- [ ] **Step 3: Run publisher tests and verify RED**

Run: `pytest tests/ontology_management/test_publisher.py tests/test_ontology_shadow.py -q`

Expected: FAIL because publisher and runtime install/recovery methods are absent.

- [ ] **Step 4: Add prevalidated runtime snapshot installation**

Keep runtime reads lock-protected and make installation a non-failing reference assignment:

```python
class OntologyRuntime:
    def __init__(self, initial_package_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._snapshot = self._load_explicit(initial_package_path) if initial_package_path else None

    def install(self, snapshot: OntologySnapshot) -> None:
        if not isinstance(snapshot, OntologySnapshot):
            raise TypeError("snapshot must be OntologySnapshot")
        with self._lock:
            self._snapshot = snapshot

    def snapshot(self) -> OntologySnapshot:
        with self._lock:
            if self._snapshot is None:
                raise PackageNotFoundError("当前没有有效本体快照")
            return self._snapshot
```

`_load_explicit` eagerly validates only the explicitly configured compatibility `package_path`; managed versions are loaded exclusively by `PackagePublisher.recover` from the exact active pointer. Add one cached `get_ontology_runtime()` and inject the same instance into Publisher and `OntologyShadowService`, so a successful publish is visible to subsequent chat requests without rebuilding the service cache.

- [ ] **Step 5: Implement staging, version commit and coordinated activation**

Within one workspace publish lock: re-read revision, assert publishable, build into a random sibling staging directory, load a complete candidate snapshot, rename staging to a new `versions/<version>` directory, then under the runtime coordination lock atomically write `active-version.json` followed by `runtime.install(candidate)`. Since the candidate is validated and `install` is assignment-only, no fallible work occurs between pointer and snapshot assignment.

If active-pointer writing fails, runtime remains old and the valid unactivated version may remain listed with `active=False`. On process start, recover only the exact pointer target; missing/invalid targets yield degraded readiness and no silent fallback.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_publisher.py tests/test_ontology_shadow.py -q
ruff check ontology_core/management/publisher.py agent/ontology_shadow.py tests/ontology_management/test_publisher.py tests/test_ontology_shadow.py
black --check ontology_core/management/publisher.py agent/ontology_shadow.py tests/ontology_management/test_publisher.py tests/test_ontology_shadow.py
```

Expected: publish, hot install, restart recovery and rollback pass; all injected failures preserve the active snapshot contract.

- [ ] **Step 7: Commit**

```powershell
git add -- ontology_core/management/publisher.py agent/ontology_shadow.py tests/ontology_management/test_publisher.py tests/test_ontology_shadow.py
git commit -m "feat: 支持本体版本发布热加载与回滚"
```

---

### Task 8: 管理服务、权限、审计与 FastAPI 路由

**Files:**
- Create: `ontology_core/management/service.py`
- Create: `auth/ontology_roles.py`
- Create: `api/schemas/ontology_packages.py`
- Create: `api/routes/ontology_packages.py`
- Modify: `api/routes/__init__.py`
- Modify: `api/main.py:13-46,55-64`
- Modify: `scripts/seed.py:21-31`
- Test: `tests/ontology_management/test_api.py`
- Test: `tests/ontology_management/test_permissions.py`

**Interfaces:**
- Consumes: import, editor, validator and publisher services
- Produces: `/ontology-packages/workspaces/{workspace_id}` overview and nested resource endpoints
- Produces: stable envelope `{"data": ..., "revision": int}` and errors `{"code": str, "message": str, "details": object}`
- Produces: dependency `require_ontology_maintainer`, `require_ontology_administrator`

- [ ] **Step 1: Write failing API happy-path tests**

Override the service and authentication dependencies in `TestClient`. Exercise overview, multipart preview, token confirmation, object/field patch, relation/time policy upsert, validation, publish, version list and rollback. Assert preview leaves revision unchanged and confirmation increments it once.

- [ ] **Step 2: Write failing permission, conflict and privacy tests**

Use users with “地市生产岗”, “本体维护者” and “全省管理员”. Assert read/edit/publish boundaries, `409 draft_revision_conflict`, blocked `422`, expired token `410`, and no absolute root, uploaded text or TTL in any JSON response.

The workspace overview and every draft endpoint require a maintainer; only `GET /ontology-packages/active` is available to any authenticated user. Publishing, rollback and destructive deletion require an administrator.

```python
def test_maintainer_cannot_publish(client: TestClient, maintainer_token: str) -> None:
    response = client.post(
        "/ontology-packages/workspaces/evaluation/versions",
        json={"version": "1.0.0", "release_notes": "first", "expected_revision": 3},
        headers=bearer(maintainer_token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ontology_administrator_required"
```

- [ ] **Step 3: Run API tests and verify RED**

Run: `pytest tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py -q`

Expected: FAIL because the new router and dependencies do not exist.

- [ ] **Step 4: Implement role dependencies and seed role**

Resolve `user.role.name` against configured exact role tuples. Create the “本体维护者” seed role without changing existing users. Return stable 403 responses. Continue using `get_current_user`; do not trust JWT role IDs without loading the current database user.

- [ ] **Step 5: Implement schemas, service façade and routes**

Use the following endpoint boundary:

```text
GET    /ontology-packages/workspaces/{id}
POST   /ontology-packages/workspaces/{id}/imports/preview
POST   /ontology-packages/workspaces/{id}/imports/{token}/confirm
PATCH  /ontology-packages/workspaces/{id}/objects/{object_id}
PATCH  /ontology-packages/workspaces/{id}/fields/{field_id}
PUT    /ontology-packages/workspaces/{id}/relations/{relation_id}
DELETE /ontology-packages/workspaces/{id}/relations/{relation_id}
PUT    /ontology-packages/workspaces/{id}/temporal-policies/{object_id}
POST   /ontology-packages/workspaces/{id}/diagnostics/{diagnostic_id}/resolve
POST   /ontology-packages/workspaces/{id}/validate
GET    /ontology-packages/workspaces/{id}/versions
POST   /ontology-packages/workspaces/{id}/versions
POST   /ontology-packages/workspaces/{id}/versions/{version}/rollback
GET    /ontology-packages/active
```

Multipart preview accepts `files: list[UploadFile]` and `expected_revision: Form(int)`, reads each stream with a byte cap and closes it in `finally`. Map domain exceptions in one route-level handler. Audit each write with actor ID, workspace, old/new revision, action, result, time and counts/digests only; never log metadata text.

- [ ] **Step 6: Register route and readiness**

Add `ontology_packages.router` without removing `ontology.router`. `/ready` includes `ontology="ok"|"degraded"`; database and ontology health are reported independently. A missing management root disables management writes but does not break `/health` or the existing legacy query path.

- [ ] **Step 7: Run focused verification**

Run:

```powershell
pytest tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py tests/test_health.py tests/test_auth.py -q
ruff check auth/ontology_roles.py api/schemas/ontology_packages.py api/routes/ontology_packages.py ontology_core/management/service.py api/main.py scripts/seed.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
black --check auth/ontology_roles.py api/schemas/ontology_packages.py api/routes/ontology_packages.py ontology_core/management/service.py api/main.py scripts/seed.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
```

Expected: all endpoint, role, privacy and readiness tests pass; legacy route tests remain unchanged.

- [ ] **Step 8: Commit**

```powershell
git add -- auth/ontology_roles.py api/schemas/ontology_packages.py api/routes/ontology_packages.py api/routes/__init__.py api/main.py ontology_core/management/service.py scripts/seed.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
git commit -m "feat: 提供本体包管理 API"
```

---

### Task 9: 本体包工作台第一阶段——概览、导入、对象与字段

**Files:**
- Create: `frontend/src/features/ontology-package/types.ts`
- Create: `frontend/src/features/ontology-package/api.ts`
- Create: `frontend/src/features/ontology-package/OntologyWorkbench.tsx`
- Create: `frontend/src/features/ontology-package/ImportPanel.tsx`
- Create: `frontend/src/features/ontology-package/ObjectPanel.tsx`
- Modify: `frontend/src/pages/Ontology.tsx:1-638`

**Interfaces:**
- Consumes: overview/import/object API from Task 8
- Produces: a visible `/ontology` workbench with active version, draft revision, counts, multi-file preview/confirm and editable object/field descriptions

- [ ] **Step 1: Define strict API types and client functions**

Define discriminated import status and stable revision fields:

```typescript
export type DiagnosticSeverity = "error" | "warning" | "confirmation_required";

export interface WorkspaceOverview {
  workspaceId: string;
  displayName: string;
  revision: number;
  activeVersion: VersionSummary | null;
  counts: { objects: number; fields: number; relations: number; temporalPolicies: number };
  objects: DraftObject[];
  diagnostics: DraftDiagnostic[];
}

export interface ImportPreview {
  status: "ready" | "blocked";
  token: string | null;
  objectCount: number;
  fieldCount: number;
  diagnostics: DraftDiagnostic[];
}
```

Add API functions with URL-encoded stable IDs and preserve the Axios interceptor.

- [ ] **Step 2: Replace the legacy page shell with the workbench**

`Ontology.tsx` becomes a thin entry:

```tsx
import OntologyWorkbench from "../features/ontology-package/OntologyWorkbench";

export default function Ontology() {
  return <OntologyWorkbench workspaceId="evaluation" />;
}
```

The workbench header shows “本体包工作台”, active version, draft revision and object/field/relation/policy counts. Show a non-alarming note that legacy MySQL metadata APIs remain compatible but no longer drive RDF publication.

- [ ] **Step 3: Implement multi-file preview and explicit confirmation**

Use Ant Design `Upload` with `multiple`, `beforeUpload={() => false}` and accepted suffixes `.tsv,.txt,.xlsx`. The first button only previews. A ready preview displays files, object/field counts and diagnostics; a second “确认导入到草稿” action submits the token and current revision. Blocked previews have no confirm action.

- [ ] **Step 4: Implement object/field browsing and revision-safe edits**

Provide object search, field search, an object drawer and inline label/description forms. Every save sends the currently loaded revision. On `draft_revision_conflict`, display “草稿已被更新，已为你刷新；请核对后重新保存”, refresh overview, and never auto-replay stale text.

- [ ] **Step 5: Build frontend**

Run:

```powershell
npm --prefix frontend run build
```

Expected: TypeScript build and Vite production bundle complete with exit code 0.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/src/pages/Ontology.tsx frontend/src/features/ontology-package
git commit -m "feat: 建立本体包导入与对象工作台"
```

---

### Task 10: 本体包工作台第二阶段——关系、时间、诊断与版本

**Files:**
- Create: `frontend/src/features/ontology-package/RelationPanel.tsx`
- Create: `frontend/src/features/ontology-package/TemporalPanel.tsx`
- Create: `frontend/src/features/ontology-package/DiagnosticsPanel.tsx`
- Create: `frontend/src/features/ontology-package/VersionPanel.tsx`
- Modify: `frontend/src/features/ontology-package/OntologyWorkbench.tsx`
- Modify: `frontend/src/features/ontology-package/api.ts`
- Modify: `frontend/src/features/ontology-package/types.ts`

**Interfaces:**
- Consumes: relation, temporal, diagnostics, validation, publish and rollback API from Task 8
- Produces: complete management workflow without direct TTL editing

- [ ] **Step 1: Implement direct relation editor**

Use source object → source field → target object → target field dependent selectors. Require label, cardinality and explicit “我已确认关联方向与字段” checkbox before sending `confirmed=true`. Display only stable business labels and physical identifiers; never expose URIs or server paths.

- [ ] **Step 2: Implement per-table temporal strategy editor**

For each object, select one owned field, grain and compatible default algorithm. Day only offers `t_minus_2`; month only offers `previous_complete_month`. Include `allowQueryOverride`, status and priority. Do not show or submit a global default.

```typescript
const strategyOptions = {
  day: [{ value: "t_minus_2", label: "系统日 T-2" }],
  month: [{ value: "previous_complete_month", label: "上一个完整月" }],
} as const;
```

- [ ] **Step 3: Implement diagnostics center**

Add severity, object and disposition filters. Errors link to the relevant editor. `confirmation_required` offers “修正元数据” or an explicit disposition modal requiring a non-empty explanation; warnings remain visible but do not disable publish.

- [ ] **Step 4: Implement validation, publish and rollback**

The version panel lists immutable versions, active marker, counts, digest prefix, actor and timestamp. Publish requires a unique version, release notes, current revision and a confirmation summary of every warning. Rollback requires a reason and a second confirmation; never mutate the draft after rollback.

- [ ] **Step 5: Build frontend**

Run: `npm --prefix frontend run build`

Expected: TypeScript and Vite build pass with no type errors.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/src/features/ontology-package
git commit -m "feat: 完成本体关系时间与版本工作台"
```

---

### Task 11: 唯一直接关系解析与结构化双表 QueryPlan/Compiler

**Files:**
- Modify: `ontology_core/resolver.py:44-214`
- Modify: `ontology_core/query_plan.py:21-60`
- Modify: `ontology_core/compiler.py:107-213`
- Modify: `ontology_core/planner.py:134-249`
- Modify: `agent/ontology_shadow.py:148-225`
- Modify: `ontology_core/__init__.py`
- Modify: `tests/ontology_core/test_resolver.py`
- Modify: `tests/ontology_core/test_models.py`
- Modify: `tests/ontology_core/test_compiler.py`
- Modify: `tests/ontology_core/test_public_api.py`
- Modify: `tests/ontology_core/test_planner.py`
- Modify: `tests/test_ontology_shadow.py`

**Interfaces:**
- Consumes: extended confirmed `Relation`
- Produces: `OntologyResolver.resolve_direct_relation(left_concept_id: str, right_concept_id: str) -> Relation`
- Produces: `BoundObject`, `ResolvedJoin`, tuple-based `QueryPlan.objects`, `concepts`, `joins`, `temporal_policies`, `temporal_decisions`
- Produces: aliased, equality-only `INNER JOIN` SQL

- [ ] **Step 1: Write failing direct-relation resolver tests**

Cover forward/reverse lookup, inactive/unconfirmed/missing key mapping, one unique highest-priority relation, same-priority ambiguity and no direct relation. Incoming lookup may reverse object order but must not reverse the stored source/target key semantics.

- [ ] **Step 2: Write failing QueryPlan validation and compiler tests**

Construct a two-object plan explicitly and assert exact SQL:

```python
assert compiled.sql == (
    'SELECT "t0"."customer_id", "t1"."order_amount" '
    'FROM "analytics"."customer_m" AS "t0" '
    'INNER JOIN "analytics"."order_d" AS "t1" '
    'ON "t0"."customer_id" = "t1"."customer_id" '
    'WHERE "t0"."p_mon" = \'202607\' AND "t1"."p_day" = \'20260822\';'
)
```

Also assert model validation rejects more than two objects, more than one join, cross-source objects, non-inner join types, non-equality operators and joins whose fields do not belong to their objects.

- [ ] **Step 3: Run resolver/compiler tests and verify RED**

Run: `pytest tests/ontology_core/test_resolver.py tests/ontology_core/test_models.py tests/ontology_core/test_compiler.py -q`

Expected: FAIL because direct relation resolution and structured join plan types are absent.

- [ ] **Step 4: Implement deterministic direct relation resolution**

Index relations by unordered endpoint pair, retain only active, confirmed relations with both join properties, sort by descending priority and URI, return one highest-priority relation, and raise `AmbiguousIdentifierError` when multiple top-priority candidates remain.

- [ ] **Step 5: Refactor QueryPlan to explicit object bindings**

Use one representation for single and double table plans:

```python
class BoundObject(FrozenModel):
    alias: str = Field(pattern=r"^t[01]$")
    semantic: Concept
    binding: PhysicalMapping


class BoundProperty(FrozenModel):
    semantic: Property
    binding: PhysicalMapping
    object_alias: str = Field(pattern=r"^t[01]$")


class ResolvedJoin(FrozenModel):
    relation: Relation
    left: BoundProperty
    right: BoundProperty
    join_type: Literal["inner"] = "inner"


class QueryPlan(FrozenModel):
    concepts: tuple[Concept, ...]
    data_source: DataSource
    objects: tuple[BoundObject, ...] = Field(min_length=1, max_length=2)
    selections: tuple[BoundProperty, ...]
    property_bindings: tuple[BoundProperty, ...]
    joins: tuple[ResolvedJoin, ...] = Field(default=(), max_length=1)
    rules: tuple[BusinessRule, ...] = ()
    filters: tuple[ResolvedFilter, ...] = ()
    temporal_policies: tuple[TemporalPartitionPolicy, ...] = ()
    temporal_decisions: tuple[TemporalDecision, ...] = ()
```

Add validators for alias uniqueness, one shared data source, semantic ownership and exactly zero joins for one object / one join for two objects. Update existing single-table test fixtures to use `t0` without changing their expected unaliased SQL.

Adapt the existing Planner to emit the new tuple form for its current one-concept path, and adapt shadow evidence to read `plan.concepts[0]`, `plan.objects[0]` and `plan.temporal_decisions`. This task must leave the application and all existing single-table behavior runnable before Task 12 adds the second concept.

- [ ] **Step 6: Compile aliases only for two-object plans**

For one object, preserve the current SQL exactly to minimize unrelated diffs. For two objects, quote fixed aliases, qualify every selection/filter/rule field, compile the join from `ResolvedJoin` only, and derive `CompiledQuery.tables` from both object mappings. Never concatenate RDF text or user-provided SQL fragments.

- [ ] **Step 7: Run focused verification**

Run:

```powershell
pytest tests/ontology_core/test_resolver.py tests/ontology_core/test_models.py tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py tests/ontology_core/test_public_api.py tests/test_ontology_shadow.py -q
ruff check ontology_core/resolver.py ontology_core/query_plan.py ontology_core/compiler.py ontology_core/planner.py agent/ontology_shadow.py ontology_core/__init__.py tests/ontology_core/test_resolver.py tests/ontology_core/test_models.py tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py tests/test_ontology_shadow.py
black --check ontology_core/resolver.py ontology_core/query_plan.py ontology_core/compiler.py ontology_core/planner.py agent/ontology_shadow.py ontology_core/__init__.py tests/ontology_core/test_resolver.py tests/ontology_core/test_models.py tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py tests/test_ontology_shadow.py
```

Expected: old single-table SQL remains byte-for-byte stable and new two-table SQL is fully structured and bounded.

- [ ] **Step 8: Commit**

```powershell
git add -- ontology_core/resolver.py ontology_core/query_plan.py ontology_core/compiler.py ontology_core/planner.py agent/ontology_shadow.py ontology_core/__init__.py tests/ontology_core/test_resolver.py tests/ontology_core/test_models.py tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py tests/ontology_core/test_public_api.py tests/test_ontology_shadow.py
git commit -m "feat: 编译唯一直接关系双表计划"
```

---

### Task 12: 双概念 Planner、每表时间安全门与影子证据

**Files:**
- Modify: `ontology_core/planner.py:78-249`
- Modify: `agent/ontology_shadow.py:39-81,148-247`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/components/OntologyComparison.tsx`
- Modify: `tests/ontology_core/test_planner.py`
- Modify: `tests/test_ontology_shadow.py`

**Interfaces:**
- Consumes: direct relation resolver and tuple-based QueryPlan
- Produces: Planner plan for one concept or exactly two concepts
- Produces: evidence containing both concepts, the selected relation, all used mappings and zero/one/two temporal decisions

- [ ] **Step 1: Write failing two-concept planning tests**

Use customer-month and order-day concepts with one confirmed direct relation. Query both concepts’ unique properties and assert two object bindings, one join and selections in query order. Add failure tests for three matched concepts, no direct relation, same-priority relation ambiguity, missing key field mapping and different data sources.

- [ ] **Step 2: Write failing per-object temporal safety tests**

With system date `2026-08-24`, assert monthly object gets `202607` and daily object gets `20260822`. If either participating temporal policy has no mapped partition field, conflicting explicit periods or an unbounded request, planning must fail before SQL compilation.

- [ ] **Step 3: Write failing shadow evidence tests**

Assert generated shadow result includes both concept names, relation name, both object/key/partition mappings, two tables and two temporal evidence entries. Assert ambiguity and unsafe time return no SQL and no partial evidence.

- [ ] **Step 4: Run Planner/shadow tests and verify RED**

Run: `pytest tests/ontology_core/test_planner.py tests/test_ontology_shadow.py -q`

Expected: FAIL because Planner still chooses one concept and shadow evidence is singular.

- [ ] **Step 5: Implement deterministic one-or-two concept selection**

Rank property matches per concept. Keep concepts with at least one uniquely best matched property, cap at two, and use direct concept labels only as supporting evidence. When two concepts remain, require one shared data source and `resolve_direct_relation`. Bind relation keys even when they are not selected so the compiler can build the join.

Do not infer a relation from same-named fields. Do not choose between equal direct relations without a unique top priority.

- [ ] **Step 6: Apply temporal parsing independently per object**

For every bound object, load its own policy and owned properties, call `parse_temporal_intents` with that policy’s grain/default, and append a partition filter tied to that object alias. A temporal object without a safe decision raises `TemporalIntentError`; objects without a configured policy remain allowed but produce a warning at authoring time.

- [ ] **Step 7: Expand shadow evidence without exposing URIs**

Change singular `temporal_decision` to `temporal_decisions: tuple[TemporalEvidence, ...]`, add `relations: tuple[str, ...]` to `OntologyEvidence`, and return short names only. Update the chat-facing serializer/components that consume this response so one decision still renders normally and two decisions render as separate table strategy cards.

- [ ] **Step 8: Run focused verification**

Run:

```powershell
pytest tests/ontology_core/test_planner.py tests/ontology_core/test_compiler.py tests/test_ontology_shadow.py tests/test_conversation.py -q
ruff check ontology_core/planner.py agent/ontology_shadow.py tests/ontology_core/test_planner.py tests/test_ontology_shadow.py
black --check ontology_core/planner.py agent/ontology_shadow.py tests/ontology_core/test_planner.py tests/test_ontology_shadow.py
```

Expected: single-table behavior remains stable; the direct two-table request generates bounded SQL; all ambiguous and unsafe cases return no SQL.

- [ ] **Step 9: Commit**

```powershell
git add -- ontology_core/planner.py agent/ontology_shadow.py tests/ontology_core/test_planner.py tests/test_ontology_shadow.py frontend/src/pages/Chat.tsx frontend/src/components/OntologyComparison.tsx
git commit -m "feat: 规划双表本体查询与账期证据"
```

---

### Task 13: 端到端验收、工程记录与服务体验

**Files:**
- Create: `tests/ontology_management/test_end_to_end.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/project-journal/2026-08.md`
- Modify: `docs/career/project-story.md`

**Interfaces:**
- Consumes: complete management, runtime and planning chain
- Produces: repeatable synthetic acceptance evidence and a running local service

- [ ] **Step 1: Write the full synthetic acceptance test**

Drive the public service boundary with three generated tables:

```python
def test_import_edit_publish_join_rollback_end_to_end(tmp_path: Path) -> None:
    app = configured_test_app(tmp_path)
    preview = preview_three_tables(app)
    draft = confirm_preview(app, preview)
    draft = add_confirmed_relation_and_temporal_policies(app, draft)
    first = publish_version(app, draft, "1.0.0")
    assert shadow_preview(app, "查询客户编号和订单金额", "2026-08-24").status == "generated"
    second = publish_description_change(app, "1.1.0")
    rollback_version(app, first.version, reason="验收回滚")
    assert active_version(app).version == "1.0.0"
    assert second.version == "1.1.0"
```

Also verify a duplicate batch does not change draft bytes and an ambiguous relation does not emit SQL.

- [ ] **Step 2: Run the complete automated suite once**

Run:

```powershell
pytest -q
ruff check .
black --check .
npm --prefix frontend run build
```

Expected: all Python tests, lint, format checks and frontend production build pass. Record exact counts from actual output in the journal; do not estimate them.

- [ ] **Step 3: Document external-root setup and operating flow**

Add only generic examples to `.env.example` and README:

```dotenv
ONTOLOGY__MANAGEMENT_ROOT=D:\ontology-agent-data
ONTOLOGY__MANAGEMENT_WORKSPACE=evaluation
```

Document preview → confirm → edit → validate → publish → shadow query → rollback. Explicitly state that the path must be outside the Git worktree and that legacy `/ontology/*` MySQL APIs do not publish RDF.

- [ ] **Step 4: Update project journal and career material from evidence**

Append verified facts covering: multi-file atomicity, optimistic revision control, immutable RDF versions, pointer/runtime coordination, relation-driven JOIN, per-table time safety, privacy isolation, test/build evidence and commit references. Add one concise STAR-style project entry only for completed behavior. Do not include real table/field names or descriptions.

- [ ] **Step 5: Commit documentation and acceptance test**

```powershell
git add -- tests/ontology_management/test_end_to_end.py .env.example README.md docs/project-journal/2026-08.md docs/career/project-story.md
git commit -m "docs: 记录本体包管理交付实践"
```

- [ ] **Step 6: Configure an external local management root**

Set `ONTOLOGY__MANAGEMENT_ROOT` only in the ignored local `.env` to an explicit external directory. Verify the resolved absolute path is outside `D:\Projects\ontology-agent` before creating its workspace. Do not commit `.env`, uploads, draft JSON or versions.

- [ ] **Step 7: Start backend and frontend for user inspection**

Run backend and frontend from the feature worktree using the existing local ports:

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5199
```

Expected: `http://127.0.0.1:8001/health` returns `status=ok`, readiness reports ontology state, and `http://127.0.0.1:5199/ontology` displays “本体包工作台”. Keep both processes running so the user can import additional real tables and provide review feedback.

- [ ] **Step 8: Perform the real-data acceptance gate when inputs exist**

Through the running page, import at least three user-provided real metadata tables into the external root, configure one confirmed direct relation and each applicable table’s time policy, publish a new version, and test one request per table plus one direct two-table request. If fewer than three real tables are available, report this gate as pending and do not claim real-data acceptance; the synthetic automated acceptance remains valid.

---

## Execution Checkpoints

- After Task 4: backend unit evidence proves multi-table import is atomic before UI work begins.
- After Task 7: version publication, hot loading and rollback are usable through Python services.
- After Task 10: start the service briefly if the user wants an early visual check; defer broad review until user feedback.
- After Task 12: compare a single-table and direct two-table shadow SQL result, including per-table time evidence.
- After Task 13: keep services running and wait for the user’s real metadata/test-set feedback; do not push or merge without explicit instruction.
