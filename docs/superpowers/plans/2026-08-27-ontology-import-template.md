# Ontology Import Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clear import guidance plus backend-generated single-object and multi-object XLSX samples that round-trip through the strict ontology draft importer.

**Architecture:** A new Python import-format module owns the ten-column contract and workbook header discovery, while a focused template builder generates styled XLSX bytes from that same contract. The existing management service and FastAPI route expose workspace-scoped downloads; the React import panel adds guidance, download actions, and cheap client-side file rejection without changing preview/confirm semantics.

**Tech Stack:** Python 3.11+, openpyxl, FastAPI, pytest, React 18, TypeScript, Ant Design, Axios, Vite.

## Global Constraints

- Do not read, copy, commit, or test against `C:/Users/94918/Desktop/test1.xlsx` or `C:/Users/94918/Desktop/test2.xlsx`; use synthetic identifiers only.
- The exact ten columns are `对象英文名称`, `对象中文名称`, `对象描述`, `状态`, `属性英文名`, `属性中文名`, `属性类型`, `属性描述`, `是否主键`, `是否标题`.
- Scan only the first 20 XLSX rows for one unambiguous complete header.
- Keep `.xls`, `.xlsm`, macros, external links, encrypted members, traversal members, and unsafe archives rejected.
- Keep the per-file upload limit at 20 MB and retain the existing 100 MB expanded-XLSX guard.
- Template download must not modify the draft, revision, selected uploads, or current preview.
- Run focused tests and one production build; do not run multi-round broad reviews before visual acceptance.
- Commit each logical task automatically on `codex/ontology-package-core`; do not push or merge.

---

## File Structure

- Create `ontology_core/management/import_format.py`: the canonical columns, row preparation, header discovery, required-value and boolean validation.
- Create `ontology_core/management/templates.py`: deterministic XLSX sample generation and stable download metadata.
- Modify `ontology_core/management/parsers.py`: route TSV and XLSX rows through the strict contract and preserve physical XLSX row numbers.
- Modify `ontology_core/tabular_metadata.py`: accept an explicit source-line offset and strict boolean values already normalized by the management format boundary.
- Modify `ontology_core/management/service.py`: expose a workspace-checked template-generation façade.
- Modify `api/routes/ontology_packages.py`: return a binary XLSX attachment through the maintainer-protected workspace route.
- Modify `frontend/src/features/ontology-package/api.ts`: fetch template bytes and derive a safe server filename.
- Modify `frontend/src/features/ontology-package/ImportPanel.tsx`: show format guidance, download variants, and file type/size feedback.
- Modify `tests/ontology_management/test_parsers.py`: cover strict rows, row offsets, and malformed workbook structures.
- Modify `tests/ontology_management/test_imports.py`: migrate batch-import fixtures to the exact ten-column contract.
- Create `tests/ontology_management/test_templates.py`: verify template structure and parser round trips.
- Modify `tests/ontology_management/test_api.py`: verify permissions, headers, round trip, and immutable draft revision.
- Modify `frontend/tests/ontology-package-client.test.ts`: cover template URL and safe filename parsing helpers.
- Modify `docs/project-journal/2026-08.md`: record the header-row mismatch and single-source contract solution without business metadata.

---

### Task 1: Canonical Import Contract and Header-Aware Parsing

**Files:**
- Create: `ontology_core/management/import_format.py`
- Modify: `ontology_core/management/parsers.py`
- Modify: `ontology_core/tabular_metadata.py`
- Modify: `tests/ontology_management/test_parsers.py`
- Modify: `tests/ontology_management/test_imports.py`

**Interfaces:**
- Produces: `STANDARD_COLUMNS: tuple[str, ...]`, `HEADER_SCAN_LIMIT = 20`, `PreparedTabularText(text: str, line_offset: int)`, `prepare_tsv(text: str) -> PreparedTabularText`, and `prepare_xlsx_rows(rows: Iterable[tuple[object, ...]], sheet_name: str) -> PreparedTabularText`.
- Changes: `parse_tabular_objects(text: str, source_name: str, *, line_offset: int = 0) -> tuple[TabularMetadataDraft, ...]`.
- Consumes: the existing `OntologyImportError`, `SourceLocation`, and management parser safety checks.

- [ ] **Step 1: Replace parser fixtures with the exact ten-column synthetic contract and write failing layout tests**

Add a shared test header and cases equivalent to:

```python
STANDARD_HEADER = (
    "对象英文名称\t对象中文名称\t对象描述\t状态\t属性英文名\t属性中文名\t"
    "属性类型\t属性描述\t是否主键\t是否标题\n"
)

def test_xlsx_finds_the_exact_header_after_two_presentation_rows() -> None:
    payload = synthetic_xlsx(
        (
            "对象",
            [
                ["注：请替换全部虚拟样例"],
                ["对象元数据信息", None, None, None, "对象属性信息"],
                list(STANDARD_COLUMNS),
                ["SAMPLE_OBJECT_A", "虚拟对象A", None, "启用", "FIELD_ID", "虚拟标识", "string", None, "是", "是"],
            ],
        )
    )
    parsed = parse_metadata_upload("objects.xlsx", payload, LIMITS)
    assert parsed.objects[0].physical_name == "SAMPLE_OBJECT_A"

def test_xlsx_diagnostic_uses_the_physical_row_after_header_discovery() -> None:
    payload = synthetic_xlsx(
        ("对象", [["说明"], ["分组"], list(STANDARD_COLUMNS), ["SAMPLE_OBJECT_A", "虚拟对象A", None, "启用", "", "虚拟标识", "string", None, "", ""]])
    )
    parsed = parse_metadata_upload("objects.xlsx", payload, LIMITS)
    assert "第 4 行，列“属性英文名”" in parsed.diagnostics[0].message
```

Also add failures for a missing standard column, a renamed column, an extra named column, duplicate header rows, no header in rows 1–20, object-level Chinese name/status missing across all rows, per-row field label/type missing, and an unknown non-empty boolean value.

- [ ] **Step 2: Run focused parser tests and confirm the intended failures**

Run:

```powershell
python -m pytest tests/ontology_management/test_parsers.py tests/ontology_management/test_imports.py -q
```

Expected: new tests fail because row 1 is still treated as the header, strict required values are not enforced, and `line_offset` does not exist.

- [ ] **Step 3: Implement the canonical contract and row preparation**

Create `import_format.py` with immutable constants and a focused value object:

```python
from dataclasses import dataclass

STANDARD_COLUMNS = (
    "对象英文名称", "对象中文名称", "对象描述", "状态", "属性英文名",
    "属性中文名", "属性类型", "属性描述", "是否主键", "是否标题",
)
HEADER_SCAN_LIMIT = 20
PER_ROW_REQUIRED = ("对象英文名称", "属性英文名", "属性中文名", "属性类型")
PER_OBJECT_REQUIRED = ("对象中文名称", "状态")

@dataclass(frozen=True)
class PreparedTabularText:
    text: str
    line_offset: int
```

`prepare_tsv` must require the first row to contain exactly the ten standard names. `prepare_xlsx_rows` must materialize at most the rows needed for safe discovery plus data, locate exactly one complete header in rows 1–20, reject duplicate/missing/renamed/extra named columns, and serialize the discovered header plus following rows to canonical TSV. Error details may include safe sheet/column names but never row contents.

Perform per-row and per-object required-value checks after grouping. Normalize blank `是否主键` and `是否标题` to `否`; accept only the existing explicit true tokens plus `0`, `false`, `no`, `n`, `否`, and `停用` as false tokens. Raise or emit deterministic diagnostics for any other non-empty value.

- [ ] **Step 4: Preserve physical row locations and wire both file types through the contract**

Change `parse_tabular_objects` to enumerate with the supplied offset:

```python
reader = csv.DictReader(io.StringIO(text), delimiter="\t")
located_rows = tuple(enumerate(reader, start=2 + line_offset))
for line, row in located_rows:
    table_name = _clean(row, "对象英文名称")
    if table_name is None:
        document_diagnostics.append(
            ImportDiagnostic(
                code="missing_table_name",
                severity=DiagnosticSeverity.ERROR,
                message="对象物理名称为空",
                location=SourceLocation(line=line, column="对象英文名称"),
            )
        )
```

In `parsers.py`, call `prepare_tsv` before `parse_tabular_objects`; for each XLSX worksheet call `prepare_xlsx_rows`, then pass its `text` and `line_offset`. Keep `_inspect_xlsx_archive` unchanged.

- [ ] **Step 5: Run parser tests and formatting checks**

Run:

```powershell
python -m pytest tests/ontology_management/test_parsers.py tests/ontology_management/test_imports.py -q
python -m ruff check ontology_core/management/import_format.py ontology_core/management/parsers.py ontology_core/tabular_metadata.py tests/ontology_management/test_parsers.py tests/ontology_management/test_imports.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit the parsing contract**

```powershell
git add -- ontology_core/management/import_format.py ontology_core/management/parsers.py ontology_core/tabular_metadata.py tests/ontology_management/test_parsers.py tests/ontology_management/test_imports.py
git commit -m "feat: 严格识别本体导入表格格式"
```

---

### Task 2: Dynamic XLSX Sample Builder

**Files:**
- Create: `ontology_core/management/templates.py`
- Create: `tests/ontology_management/test_templates.py`
- Modify: `ontology_core/management/__init__.py`

**Interfaces:**
- Consumes: `STANDARD_COLUMNS` and the strict `parse_metadata_upload` contract from Task 1.
- Produces: `ImportTemplateVariant = Literal["single", "multiple"]`, `GeneratedImportTemplate(file_name: str, media_type: str, content: bytes)`, and `build_import_template(variant: str) -> GeneratedImportTemplate`.

- [ ] **Step 1: Write failing template structure and round-trip tests**

Create tests that assert:

```python
def test_single_template_has_reference_layout_and_one_synthetic_object() -> None:
    generated = build_import_template("single")
    workbook = load_workbook(BytesIO(generated.content), data_only=True)
    sheet = workbook.active
    assert sheet.merged_cells.ranges == {CellRange("A1:J1"), CellRange("A2:D2"), CellRange("E2:J2")}
    assert tuple(cell.value for cell in sheet[3]) == STANDARD_COLUMNS
    parsed = parse_metadata_upload(generated.file_name, generated.content, LIMITS)
    assert [item.physical_name for item in parsed.objects] == ["SAMPLE_OBJECT_A"]

def test_multiple_template_round_trips_two_synthetic_objects() -> None:
    generated = build_import_template("multiple")
    parsed = parse_metadata_upload(generated.file_name, generated.content, LIMITS)
    assert [item.physical_name for item in parsed.objects] == ["SAMPLE_OBJECT_A", "SAMPLE_OBJECT_B"]
```

Also assert macro-free `.xlsx` media type, stable ASCII file names, red required headers, useful widths, frozen third row, and `ImportTemplateVariantError` for unknown variants.

- [ ] **Step 2: Run template tests and verify they fail**

Run:

```powershell
python -m pytest tests/ontology_management/test_templates.py -q
```

Expected: collection fails because `ontology_core.management.templates` is not implemented.

- [ ] **Step 3: Implement the focused template builder**

Use openpyxl `Workbook`, `PatternFill`, `Font`, `Alignment`, and `Border` to create one worksheet named `对象字段`. Merge `A1:J1`, `A2:D2`, and `E2:J2`; write `STANDARD_COLUMNS` to row 3; color required headers red; freeze at `A4`; and write two complete synthetic fields per object.

Return bytes without writing to disk:

```python
@dataclass(frozen=True)
class GeneratedImportTemplate:
    file_name: str
    media_type: str
    content: bytes

def build_import_template(variant: str) -> GeneratedImportTemplate:
    object_count = {"single": 1, "multiple": 2}.get(variant)
    if object_count is None:
        raise ImportTemplateVariantError()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "对象字段"
    worksheet.merge_cells("A1:J1")
    worksheet.merge_cells("A2:D2")
    worksheet.merge_cells("E2:J2")
    worksheet["A1"] = "请替换全部虚拟样例；十列名称不可修改。"
    worksheet["A2"] = "对象元数据信息"
    worksheet["E2"] = "对象属性信息"
    worksheet.append(STANDARD_COLUMNS)
    for index in range(object_count):
        suffix = chr(ord("A") + index)
        worksheet.append(
            (
                f"SAMPLE_OBJECT_{suffix}", f"虚拟对象{suffix}", "", "启用",
                "FIELD_ID", "虚拟标识", "string", "", "是", "是",
            )
        )
        worksheet.append(
            (
                f"SAMPLE_OBJECT_{suffix}", "", "", "",
                "FIELD_NAME", "虚拟名称", "string", "", "", "",
            )
        )
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return GeneratedImportTemplate(
        file_name=f"ontology-import-{variant}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=output.getvalue(),
    )
```

The content must contain only generic placeholder values and a note that all sample rows must be replaced before upload.

- [ ] **Step 4: Run round-trip tests and Ruff**

Run:

```powershell
python -m pytest tests/ontology_management/test_templates.py tests/ontology_management/test_parsers.py -q
python -m ruff check ontology_core/management/templates.py tests/ontology_management/test_templates.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the template builder**

```powershell
git add -- ontology_core/management/templates.py ontology_core/management/__init__.py tests/ontology_management/test_templates.py
git commit -m "feat: 动态生成本体导入样例"
```

---

### Task 3: Workspace-Scoped Template Download API

**Files:**
- Modify: `ontology_core/management/service.py`
- Modify: `api/routes/ontology_packages.py`
- Modify: `tests/ontology_management/test_api.py`

**Interfaces:**
- Consumes: `build_import_template(variant: str) -> GeneratedImportTemplate` from Task 2.
- Produces: `OntologyManagementService.import_template(workspace_id: str, variant: str) -> GeneratedImportTemplate` and `GET /ontology-packages/workspaces/{workspace_id}/imports/template?variant=single|multiple`.

- [ ] **Step 1: Write failing API tests**

Add tests that download both variants as a maintainer and assert:

```python
response = client.get(
    "/ontology-packages/workspaces/evaluation/imports/template",
    params={"variant": "multiple"},
)
assert response.status_code == 200
assert response.headers["content-type"].startswith(
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
assert response.headers["content-disposition"] == (
    'attachment; filename="ontology-import-multiple.xlsx"'
)
assert management_service.draft_revision("evaluation") == 0
```

Parse `response.content` through `parse_metadata_upload` and assert two objects. Add unknown-variant `400`, unknown-workspace stable error, unauthenticated/unauthorized denial, and no revision change.

- [ ] **Step 2: Run API tests and confirm route absence**

Run:

```powershell
python -m pytest tests/ontology_management/test_api.py -q
```

Expected: new template route tests fail with `404`.

- [ ] **Step 3: Implement the service façade and binary route**

The service must verify the workspace exists before generation:

```python
def import_template(self, workspace_id: str, variant: str) -> GeneratedImportTemplate:
    self._store.read(workspace_id)
    return build_import_template(variant)
```

Add a route before `/{token}/confirm` so the literal `template` path cannot be captured as a token:

```python
@router.get("/workspaces/{workspace_id}/imports/template")
def download_import_template(
    workspace_id: str,
    variant: str,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> Response:
    generated = service.import_template(workspace_id, variant)
    return Response(
        content=generated.content,
        media_type=generated.media_type,
        headers={"Content-Disposition": f'attachment; filename="{generated.file_name}"'},
    )
```

Do not audit this read-only action as a draft write and do not emit an envelope around binary content.

- [ ] **Step 4: Run API and permission tests**

Run:

```powershell
python -m pytest tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py -q
python -m ruff check ontology_core/management/service.py api/routes/ontology_packages.py tests/ontology_management/test_api.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the download API**

```powershell
git add -- ontology_core/management/service.py api/routes/ontology_packages.py tests/ontology_management/test_api.py
git commit -m "feat: 提供本体导入样例下载接口"
```

---

### Task 4: Import Guidance, Sample Download, and Client-Side Rejection

**Files:**
- Modify: `frontend/src/features/ontology-package/api.ts`
- Modify: `frontend/src/features/ontology-package/ImportPanel.tsx`
- Modify: `frontend/tests/ontology-package-client.test.ts`

**Interfaces:**
- Produces: `importTemplatePath(workspaceId: string, variant: ImportTemplateVariant) -> string`, `safeAttachmentFileName(contentDisposition: string | undefined, fallback: string) -> string`, and `downloadImportTemplate(workspaceId: string, variant: ImportTemplateVariant) -> Promise<DownloadedTemplate>`.
- Consumes: the binary API from Task 3 and the existing Ant Design import panel.

- [ ] **Step 1: Add client contract checks before UI changes**

Extend the existing lightweight client contract file with assertions equivalent to:

```typescript
equal(
  importTemplatePath("workspace / 中文", "multiple"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/imports/template?variant=multiple",
  "template path is workspace scoped and encoded"
);
equal(
  safeAttachmentFileName('attachment; filename="ontology-import-single.xlsx"', "fallback.xlsx"),
  "ontology-import-single.xlsx",
  "safe ASCII attachment name is retained"
);
equal(
  safeAttachmentFileName('attachment; filename="../unsafe.xlsx"', "fallback.xlsx"),
  "fallback.xlsx",
  "unsafe attachment names fall back"
);
```

- [ ] **Step 2: Implement the binary client and safe browser save flow**

In `api.ts`, request with `{ responseType: "blob" }`, parse only a basename ending in `.xlsx`, and return `{ blob, fileName }`. In `ImportPanel.tsx`, create an object URL, click a temporary anchor, remove it, and revoke the URL in `finally`. Keep a `downloadingVariant` state so only the selected menu item shows progress.

- [ ] **Step 3: Add visible guidance and file rejection**

Change the card content to include:

```tsx
<Alert
  type="info"
  showIcon
  message="支持无宏 XLSX、UTF-8 TSV/TXT；单文件不超过 20 MB"
  description="文件须包含固定的 10 列。对象中文名称和状态每对象至少填写一次；属性英文名、属性中文名和属性类型每行必填；描述可空，主键和标题留空按否。"
/>
```

Add an Ant Design `Dropdown` button named `下载填写样例` with `single` and `multiple` menu keys next to `选择文件`. Update `beforeUpload` to return `Upload.LIST_IGNORE` and show a message for disallowed extensions or files over `20 * 1024 * 1024`; valid files continue returning `false` so preview behavior is unchanged.

- [ ] **Step 4: Run TypeScript checks and production build**

Run:

```powershell
npm run build
```

from `frontend/`.

Expected: TypeScript and Vite production build complete successfully. Also inspect `frontend/tests/ontology-package-client.test.ts` changes for exact URL/filename assertions; the repository currently has no installed TS test runner, so do not add a new dependency solely for this feature.

- [ ] **Step 5: Commit the frontend behavior**

```powershell
git add -- frontend/src/features/ontology-package/api.ts frontend/src/features/ontology-package/ImportPanel.tsx frontend/tests/ontology-package-client.test.ts
git commit -m "feat: 增加本体导入提示与样例下载"
```

---

### Task 5: Focused Integration Verification, Project Journal, and Visual Handoff

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: recorded engineering evidence and running services for user acceptance.

- [ ] **Step 1: Run the focused backend suite**

Run:

```powershell
python -m pytest tests/ontology_management/test_parsers.py tests/ontology_management/test_imports.py tests/ontology_management/test_templates.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run formatting and frontend build once**

Run:

```powershell
python -m ruff check ontology_core/management/import_format.py ontology_core/management/templates.py ontology_core/management/parsers.py ontology_core/management/service.py api/routes/ontology_packages.py tests/ontology_management/test_parsers.py tests/ontology_management/test_templates.py tests/ontology_management/test_api.py
npm run build
```

Expected: Ruff has no findings and Vite production build succeeds.

- [ ] **Step 3: Record the engineering difficulty and resolution**

Append a concise journal entry explaining that real metadata workbooks placed instructions and merged grouping rows above the actual header, while the original parser assumed row 1. Record the solution: one canonical ten-column contract drives header discovery, strict validation, and dynamic sample generation; tests use synthetic data so private business metadata remains outside Git.

- [ ] **Step 4: Commit the journal entry**

```powershell
git add -- docs/project-journal/2026-08.md
git commit -m "docs: 记录本体导入模板兼容实践"
```

- [ ] **Step 5: Start or restart the existing local services**

Start the backend on `127.0.0.1:8001` and the frontend on `127.0.0.1:5199` using the existing project commands and external management root. Verify only:

```text
GET http://127.0.0.1:8001/health -> 200
GET http://127.0.0.1:5199/ontology -> page loads
```

Do not perform additional review rounds before the user sees the page.

- [ ] **Step 6: Hand off visual acceptance**

Open `/ontology`, report the visible changes and commit hashes, and ask the user to try both sample downloads and one import preview. Do not push or merge.
