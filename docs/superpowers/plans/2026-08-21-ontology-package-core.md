# Python 本体包内核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个纯 Python、与数据库平台无关的本体包内核，能够安全加载版本化 RDF/OWL 包、执行 SHACL 校验、计算内容摘要并发布线程安全的只读有效快照。

**Architecture:** 新增独立 `ontology_core` 包，使用 Pydantic 定义稳定 DTO，RDFLib 负责 Turtle/RDF 图加载，pySHACL 负责约束验证，并以 SHA-256 标识清单与全部包文件内容。Repository 将本体包加载为候选快照，只有解析和 SHACL 校验均通过时才原子发布；失败重载保留最后一个有效快照。本计划不接入现有 Agent、REST API、MySQL 导入器或 SQL 编译链路。

**Tech Stack:** Python 3.11+、Pydantic 2、RDFLib 7.6.x、pySHACL 0.40.x、PyYAML、pytest、ruff、black

## Global Constraints

- 只使用 Python 实现，不引入 Java/Jena 服务。
- 本体包是语义事实源，并由 Git 管理版本。
- 生产代码和仓库测试夹具不得包含真实电信表名、字段名、用户数据或业务敏感口径。
- 对外 DTO 不暴露 RDFLib 的 `Graph`、`URIRef` 或其他内部类型。
- 首期旁路实现，不改变现有 Agent、前端、HiveSQL 生成和执行行为。
- 每个任务严格按红灯、绿灯、重构顺序执行，验证通过后自动创建独立 Git 提交。
- 不提交用户已有的无关改动，不自动推送远程仓库。
- 遇到非简单难点、架构取舍或阶段完成时，更新工程日志；只记录可验证事实。

## Scope Decomposition

完整首期设计分为四个可独立验收的实施计划：

1. 本计划：本体包模型、加载、SHACL 校验和有效快照。
2. 后续计划：概念解析、MappingRegistry 和 QueryPlanValidator Python SDK。
3. 后续计划：`/ontology/v1` REST API。
4. 后续计划：MySQL 元数据确定性导入器。

## File Map

### 新增生产文件

- `ontology_core/__init__.py`：仅导出稳定公共类型和 Repository 接口。
- `ontology_core/errors.py`：本体错误层级和稳定机器错误码。
- `ontology_core/models.py`：不可变 Pydantic DTO，包括清单、违规、校验报告和包信息。
- `ontology_core/manifest.py`：读取 `manifest.yaml`，验证角色文件并阻止路径越界。
- `ontology_core/validator.py`：封装 pySHACL 并转换验证报告。
- `ontology_core/repository.py`：加载 RDF 图、计算摘要、原子发布和复制只读快照。

### 新增测试文件

- `tests/ontology_core/__init__.py`：测试包标记。
- `tests/ontology_core/conftest.py`：匿名本体包 fixture 和临时包构造器。
- `tests/ontology_core/test_models.py`：DTO 不可变性和错误契约。
- `tests/ontology_core/test_manifest.py`：清单解析、缺失文件和路径越界。
- `tests/ontology_core/test_validator.py`：SHACL 通过和违规转换。
- `tests/ontology_core/test_repository.py`：加载、摘要、快照复制、失败重载保留旧版本。
- `tests/fixtures/ontology_core/valid/manifest.yaml`：匿名有效包清单。
- `tests/fixtures/ontology_core/valid/core.ttl`：匿名核心类。
- `tests/fixtures/ontology_core/valid/domain.ttl`：匿名领域类。
- `tests/fixtures/ontology_core/valid/mappings.ttl`：空映射图占位，仅含匿名命名空间。
- `tests/fixtures/ontology_core/valid/rules.ttl`：空规则图占位，仅含匿名命名空间。
- `tests/fixtures/ontology_core/valid/shapes.ttl`：要求 OWL 类必须有标签的匿名 SHACL Shape。

### 修改文件

- `pyproject.toml`：增加 RDFLib 和 pySHACL 运行依赖。
- `docs/project-journal/2026-08.md`：完成本计划后追加真实难点、验证证据和提交引用。
- `docs/career/project-story.md`：仅在验证完成后将对应能力从“设计中”更新为“已实现”。

---

### Task 1: 依赖、错误契约与不可变 DTO

**Files:**
- Modify: `pyproject.toml`
- Create: `ontology_core/__init__.py`
- Create: `ontology_core/errors.py`
- Create: `ontology_core/models.py`
- Create: `tests/ontology_core/__init__.py`
- Create: `tests/ontology_core/test_models.py`

**Interfaces:**
- Consumes: Pydantic 2 `BaseModel`、`ConfigDict`；Python `StrEnum`。
- Produces: `OntologyError`、`PackageNotFoundError`、`OntologyParseError`、`OntologyValidationError`；`PackageFileRole`、`PackageManifest`、`OntologyViolation`、`ValidationReport`、`PackageInfo`。

- [ ] **Step 1: 在依赖清单加入经过版本边界约束的 RDF 库**

在 `pyproject.toml` 的运行依赖中加入：

```toml
    "rdflib>=7.6,<8",
    "pyshacl>=0.40,<0.41",
```

保留现有 `pyyaml` 和 `pydantic` 依赖，不加入 pySHACL 的 HTTP extra。

- [ ] **Step 2: 编写 DTO 与错误契约的失败测试**

创建 `tests/ontology_core/test_models.py`：

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ontology_core.errors import PackageNotFoundError
from ontology_core.models import (
    OntologyViolation,
    PackageFileRole,
    PackageInfo,
    PackageManifest,
    ValidationReport,
)


def test_manifest_requires_all_package_roles() -> None:
    with pytest.raises(ValidationError):
        PackageManifest(
            package_id="example.neutral",
            version="1.0.0",
            files={PackageFileRole.CORE: "core.ttl"},
        )


def test_package_info_is_immutable() -> None:
    info = PackageInfo(
        package_id="example.neutral",
        version="1.0.0",
        sha256="a" * 64,
        loaded_at=datetime.now(timezone.utc),
        source="C:/tmp/package",
    )
    with pytest.raises(ValidationError):
        info.version = "2.0.0"


def test_validation_report_uses_tuple_violations() -> None:
    violation = OntologyViolation(
        focus_node="https://example.invalid/Record",
        path="http://www.w3.org/2000/01/rdf-schema#label",
        message="Label is required",
        severity="http://www.w3.org/ns/shacl#Violation",
        source_shape="https://example.invalid/ClassShape",
    )
    report = ValidationReport(conforms=False, violations=(violation,))
    assert report.violations == (violation,)


def test_error_exposes_stable_code_and_details() -> None:
    exc = PackageNotFoundError("包不存在", details={"path": "missing"})
    assert exc.code == "package_not_found"
    assert exc.details == {"path": "missing"}
```

- [ ] **Step 3: 运行测试并确认红灯原因**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_models.py -v
```

Expected: collection FAIL，错误包含 `ModuleNotFoundError: No module named 'ontology_core'`。

- [ ] **Step 4: 实现最小错误层级**

创建 `ontology_core/errors.py`：

```python
from __future__ import annotations

from typing import Any, ClassVar


class OntologyError(Exception):
    code: ClassVar[str] = "ontology_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PackageNotFoundError(OntologyError):
    code = "package_not_found"


class OntologyParseError(OntologyError):
    code = "ontology_parse_error"


class OntologyValidationError(OntologyError):
    code = "ontology_validation_error"
```

- [ ] **Step 5: 实现不可变 Pydantic DTO**

创建 `ontology_core/models.py`：

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PackageFileRole(StrEnum):
    CORE = "core"
    DOMAIN = "domain"
    MAPPINGS = "mappings"
    RULES = "rules"
    SHAPES = "shapes"


class PackageManifest(FrozenModel):
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    files: dict[PackageFileRole, str]

    @model_validator(mode="after")
    def require_all_roles(self) -> "PackageManifest":
        missing = set(PackageFileRole) - set(self.files)
        if missing:
            names = ", ".join(sorted(role.value for role in missing))
            raise ValueError(f"缺少本体包文件角色: {names}")
        return self


class OntologyViolation(FrozenModel):
    focus_node: str | None = None
    path: str | None = None
    message: str
    severity: str | None = None
    source_shape: str | None = None


class ValidationReport(FrozenModel):
    conforms: bool
    violations: tuple[OntologyViolation, ...] = ()


class PackageInfo(FrozenModel):
    package_id: str
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    loaded_at: datetime
    source: str
```

创建 `ontology_core/__init__.py`，只导出稳定类型和错误；暂不导出 RDFLib 类型：

```python
from ontology_core.errors import (
    OntologyError,
    OntologyParseError,
    OntologyValidationError,
    PackageNotFoundError,
)
from ontology_core.models import (
    OntologyViolation,
    PackageFileRole,
    PackageInfo,
    PackageManifest,
    ValidationReport,
)

__all__ = [
    "OntologyError",
    "OntologyParseError",
    "OntologyValidationError",
    "OntologyViolation",
    "PackageFileRole",
    "PackageInfo",
    "PackageManifest",
    "PackageNotFoundError",
    "ValidationReport",
]
```

- [ ] **Step 6: 安装依赖并运行 DTO 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_models.py -v
```

Expected: `4 passed`。

- [ ] **Step 7: 运行静态检查并提交**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check ontology_core tests/ontology_core/test_models.py
.\.venv\Scripts\python.exe -m black --check ontology_core tests/ontology_core/test_models.py
```

Expected: 两条命令 exit code 0。

Commit:

```powershell
git add pyproject.toml ontology_core tests/ontology_core
git commit -m "feat: 定义本体内核基础契约"
```

---

### Task 2: 安全、确定性的本体包清单加载

**Files:**
- Create: `ontology_core/manifest.py`
- Create: `tests/ontology_core/conftest.py`
- Create: `tests/ontology_core/test_manifest.py`
- Create: `tests/fixtures/ontology_core/valid/manifest.yaml`
- Create: `tests/fixtures/ontology_core/valid/core.ttl`
- Create: `tests/fixtures/ontology_core/valid/domain.ttl`
- Create: `tests/fixtures/ontology_core/valid/mappings.ttl`
- Create: `tests/fixtures/ontology_core/valid/rules.ttl`
- Create: `tests/fixtures/ontology_core/valid/shapes.ttl`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: `PackageManifest`、`PackageFileRole`、`PackageNotFoundError`、`OntologyParseError`。
- Produces: `load_manifest(package_dir: str | Path) -> PackageManifest`；`resolve_package_files(package_dir: str | Path, manifest: PackageManifest) -> dict[PackageFileRole, Path]`。

- [ ] **Step 1: 创建匿名有效本体包 fixture**

`tests/fixtures/ontology_core/valid/manifest.yaml`：

```yaml
package_id: example.neutral
version: 1.0.0
files:
  core: core.ttl
  domain: domain.ttl
  mappings: mappings.ttl
  rules: rules.ttl
  shapes: shapes.ttl
```

`core.ttl`：

```turtle
@prefix ex: <https://example.invalid/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:SemanticElement a owl:Class ;
    rdfs:label "Semantic element" .
```

`domain.ttl`：

```turtle
@prefix ex: <https://example.invalid/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Record a owl:Class ;
    rdfs:subClassOf ex:SemanticElement ;
    rdfs:label "Record" .
```

`mappings.ttl`：

```turtle
@prefix ex: <https://example.invalid/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Mapping a owl:Class ;
    rdfs:label "Mapping" .
```

`rules.ttl`：

```turtle
@prefix ex: <https://example.invalid/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Rule a owl:Class ;
    rdfs:label "Rule" .
```

`shapes.ttl`：

```turtle
@prefix ex: <https://example.invalid/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

ex:OntologyClassShape a sh:NodeShape ;
    sh:targetClass owl:Class ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:message "OWL class requires a label"
    ] .
```

- [ ] **Step 2: 编写清单安全测试**

创建 `tests/ontology_core/conftest.py`，提供：

```python
from pathlib import Path

import pytest


@pytest.fixture()
def valid_package_dir() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "ontology_core" / "valid"
```

创建 `tests/ontology_core/test_manifest.py`，覆盖：

```python
from pathlib import Path

import pytest

from ontology_core.errors import OntologyParseError, PackageNotFoundError
from ontology_core.manifest import load_manifest, resolve_package_files
from ontology_core.models import PackageFileRole


def test_load_manifest_and_resolve_all_roles(valid_package_dir: Path) -> None:
    manifest = load_manifest(valid_package_dir)
    files = resolve_package_files(valid_package_dir, manifest)
    assert manifest.package_id == "example.neutral"
    assert tuple(files) == tuple(PackageFileRole)
    assert all(path.is_file() for path in files.values())


def test_missing_manifest_raises_stable_error(tmp_path: Path) -> None:
    with pytest.raises(PackageNotFoundError) as caught:
        load_manifest(tmp_path)
    assert caught.value.code == "package_not_found"


def test_manifest_rejects_parent_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ttl"
    outside.write_text("", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    package.joinpath("manifest.yaml").write_text(
        "package_id: x\nversion: 1\nfiles:\n"
        "  core: ../outside.ttl\n  domain: ../outside.ttl\n"
        "  mappings: ../outside.ttl\n  rules: ../outside.ttl\n"
        "  shapes: ../outside.ttl\n",
        encoding="utf-8",
    )
    manifest = load_manifest(package)
    with pytest.raises(OntologyParseError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_manifest.py -v
```

Expected: collection FAIL，错误包含 `No module named 'ontology_core.manifest'`。

- [ ] **Step 4: 实现清单加载和路径保护**

创建 `ontology_core/manifest.py`：

```python
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ontology_core.errors import OntologyParseError, PackageNotFoundError
from ontology_core.models import PackageFileRole, PackageManifest


def load_manifest(package_dir: str | Path) -> PackageManifest:
    root = Path(package_dir).resolve()
    path = root / "manifest.yaml"
    if not path.is_file():
        raise PackageNotFoundError("本体包清单不存在", details={"path": str(path)})
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return PackageManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise OntologyParseError(
            "本体包清单解析失败",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def resolve_package_files(
    package_dir: str | Path,
    manifest: PackageManifest,
) -> dict[PackageFileRole, Path]:
    root = Path(package_dir).resolve()
    resolved: dict[PackageFileRole, Path] = {}
    for role in PackageFileRole:
        candidate = (root / manifest.files[role]).resolve()
        if not candidate.is_relative_to(root):
            raise OntologyParseError(
                "本体包文件路径越界",
                details={"role": role.value, "path": str(candidate)},
            )
        if not candidate.is_file():
            raise PackageNotFoundError(
                "本体包文件不存在",
                details={"role": role.value, "path": str(candidate)},
            )
        resolved[role] = candidate
    return resolved
```

在 `ontology_core/__init__.py` 增加公共导出：

```python
from ontology_core.manifest import load_manifest, resolve_package_files

__all__ += ["load_manifest", "resolve_package_files"]
```

- [ ] **Step 5: 运行测试、静态检查并提交**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_manifest.py -v
.\.venv\Scripts\python.exe -m ruff check ontology_core tests/ontology_core
.\.venv\Scripts\python.exe -m black --check ontology_core tests/ontology_core
```

Expected: manifest 测试 `3 passed`，静态检查 exit code 0。

Commit:

```powershell
git add ontology_core tests/ontology_core tests/fixtures/ontology_core
git commit -m "feat: 安全加载版本化本体包清单"
```

---

### Task 3: SHACL 校验与稳定违规报告

**Files:**
- Create: `ontology_core/validator.py`
- Create: `tests/ontology_core/test_validator.py`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: RDFLib `Graph`；`OntologyViolation`、`ValidationReport`、`OntologyParseError`。
- Produces: `OntologyValidator.validate(data_graph: Graph, shapes_graph: Graph) -> ValidationReport`。

- [ ] **Step 1: 编写有效和无效图测试**

创建 `tests/ontology_core/test_validator.py`：

```python
from pathlib import Path

from rdflib import Graph

from ontology_core.validator import OntologyValidator


def _graph(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


def test_valid_graph_conforms(valid_package_dir: Path) -> None:
    data = _graph(valid_package_dir / "core.ttl")
    data += _graph(valid_package_dir / "domain.ttl")
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is True
    assert report.violations == ()


def test_missing_label_returns_structured_violation(valid_package_dir: Path) -> None:
    data = Graph().parse(
        data=(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "ex:Unlabelled a owl:Class .\n"
        ),
        format="turtle",
    )
    shapes = _graph(valid_package_dir / "shapes.ttl")
    report = OntologyValidator().validate(data, shapes)
    assert report.conforms is False
    assert len(report.violations) == 1
    assert report.violations[0].focus_node.endswith("Unlabelled")
    assert report.violations[0].message == "OWL class requires a label"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_validator.py -v
```

Expected: collection FAIL，错误包含 `No module named 'ontology_core.validator'`。

- [ ] **Step 3: 实现 pySHACL 适配器**

创建 `ontology_core/validator.py`：

```python
from __future__ import annotations

from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import RDF, SH

from ontology_core.errors import OntologyParseError
from ontology_core.models import OntologyViolation, ValidationReport


def _text(graph: Graph, subject, predicate) -> str | None:
    value = graph.value(subject, predicate)
    return str(value) if value is not None else None


class OntologyValidator:
    def validate(self, data_graph: Graph, shapes_graph: Graph) -> ValidationReport:
        try:
            conforms, result_graph, _ = validate(
                data_graph=data_graph,
                shacl_graph=shapes_graph,
                inference="rdfs",
                abort_on_first=False,
                allow_infos=False,
                allow_warnings=False,
            )
        except Exception as exc:
            raise OntologyParseError(
                "SHACL 校验执行失败",
                details={"reason": str(exc)},
            ) from exc

        if not isinstance(result_graph, Graph):
            raise OntologyParseError("SHACL 校验未返回 RDF 报告图")

        violations = []
        for result in result_graph.subjects(RDF.type, SH.ValidationResult):
            violations.append(
                OntologyViolation(
                    focus_node=_text(result_graph, result, SH.focusNode),
                    path=_text(result_graph, result, SH.resultPath),
                    message=_text(result_graph, result, SH.resultMessage)
                    or "Ontology constraint violation",
                    severity=_text(result_graph, result, SH.resultSeverity),
                    source_shape=_text(result_graph, result, SH.sourceShape),
                )
            )
        violations.sort(key=lambda item: (
            item.focus_node or "",
            item.path or "",
            item.message,
        ))
        return ValidationReport(conforms=bool(conforms), violations=tuple(violations))
```

在 `ontology_core/__init__.py` 增加公共导出：

```python
from ontology_core.validator import OntologyValidator

__all__ += ["OntologyValidator"]
```

- [ ] **Step 4: 运行测试和静态检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_validator.py -v
.\.venv\Scripts\python.exe -m ruff check ontology_core tests/ontology_core
.\.venv\Scripts\python.exe -m black --check ontology_core tests/ontology_core
```

Expected: validator 测试 `2 passed`，静态检查 exit code 0。

- [ ] **Step 5: 提交**

```powershell
git add ontology_core/validator.py ontology_core/__init__.py tests/ontology_core/test_validator.py
git commit -m "feat: 使用 SHACL 校验本体图"
```

---

### Task 4: 有效快照 Repository 与失败回滚

**Files:**
- Create: `ontology_core/repository.py`
- Create: `tests/ontology_core/test_repository.py`
- Modify: `ontology_core/__init__.py`

**Interfaces:**
- Consumes: `load_manifest`、`resolve_package_files`、`OntologyValidator`、`PackageInfo`、`OntologyValidationError`。
- Produces: 内部 `_OntologySnapshot.copy_data_graph() -> Graph`、内部 `_OntologySnapshot.copy_shapes_graph() -> Graph`、`OntologyRepository.publish(package_dir: str | Path) -> PackageInfo`、基础设施内部使用的 `OntologyRepository.current() -> _OntologySnapshot`。`_OntologySnapshot` 不属于后续 Python SDK 公共 DTO。

- [ ] **Step 1: 编写 Repository 行为测试**

创建 `tests/ontology_core/test_repository.py`，包含：

```python
from pathlib import Path

import pytest
from rdflib.namespace import OWL, RDF

from ontology_core.errors import OntologyValidationError, PackageNotFoundError
from ontology_core.repository import OntologyRepository


def test_publish_valid_package_exposes_info_and_graph_copy(valid_package_dir: Path) -> None:
    repository = OntologyRepository()
    info = repository.publish(valid_package_dir)
    snapshot = repository.current()
    first = snapshot.copy_data_graph()
    first.remove((None, None, None))
    second = snapshot.copy_data_graph()

    assert info.package_id == "example.neutral"
    assert info.version == "1.0.0"
    assert len(info.sha256) == 64
    assert len(second) > 0
    assert any(second.triples((None, RDF.type, OWL.Class)))


def test_current_before_publish_raises_stable_error() -> None:
    with pytest.raises(PackageNotFoundError) as caught:
        OntologyRepository().current()
    assert caught.value.code == "package_not_found"


def test_failed_reload_keeps_previous_snapshot(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    repository = OntologyRepository()
    previous = repository.publish(valid_package_dir)
    broken = tmp_path / "broken"
    broken.mkdir()
    for source in valid_package_dir.iterdir():
        broken.joinpath(source.name).write_bytes(source.read_bytes())
    broken.joinpath("domain.ttl").write_text(
        "@prefix ex: <https://example.invalid/ontology/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:Unlabelled a owl:Class .\n",
        encoding="utf-8",
    )

    with pytest.raises(OntologyValidationError):
        repository.publish(broken)

    assert repository.current().info.sha256 == previous.sha256


def test_same_bytes_produce_same_digest(valid_package_dir: Path) -> None:
    first = OntologyRepository().publish(valid_package_dir)
    second = OntologyRepository().publish(valid_package_dir)
    assert first.sha256 == second.sha256


def test_manifest_change_changes_digest(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "copied"
    copied.mkdir()
    for source in valid_package_dir.iterdir():
        copied.joinpath(source.name).write_bytes(source.read_bytes())
    first = OntologyRepository().publish(copied)
    manifest = copied.joinpath("manifest.yaml")
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"),
        encoding="utf-8",
    )
    second = OntologyRepository().publish(copied)
    assert first.sha256 != second.sha256
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_repository.py -v
```

Expected: collection FAIL，错误包含 `No module named 'ontology_core.repository'`。

- [ ] **Step 3: 实现内部快照与确定性摘要**

创建 `ontology_core/repository.py`，核心实现遵循：

```python
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph

from ontology_core.errors import (
    OntologyParseError,
    OntologyValidationError,
    PackageNotFoundError,
)
from ontology_core.manifest import load_manifest, resolve_package_files
from ontology_core.models import PackageFileRole, PackageInfo
from ontology_core.validator import OntologyValidator


def _parse_turtle(path: Path) -> Graph:
    try:
        return Graph().parse(path, format="turtle")
    except Exception as exc:
        raise OntologyParseError(
            "本体 Turtle 文件解析失败",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def _digest(manifest_path: Path, files: dict[PackageFileRole, Path]) -> str:
    digest = hashlib.sha256()
    digest.update(b"manifest\0")
    digest.update(manifest_path.read_bytes())
    digest.update(b"\0")
    for role in PackageFileRole:
        digest.update(role.value.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[role].read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _serialize(graph: Graph) -> str:
    return graph.serialize(format="nt")


def _copy_graph(serialized: str) -> Graph:
    return Graph().parse(data=serialized, format="nt")


@dataclass(frozen=True)
class _OntologySnapshot:
    info: PackageInfo
    _data_nt: str
    _shapes_nt: str

    def copy_data_graph(self) -> Graph:
        return _copy_graph(self._data_nt)

    def copy_shapes_graph(self) -> Graph:
        return _copy_graph(self._shapes_nt)


class OntologyRepository:
    def __init__(self, validator: OntologyValidator | None = None) -> None:
        self._validator = validator or OntologyValidator()
        self._lock = threading.RLock()
        self._current: _OntologySnapshot | None = None

    def publish(self, package_dir: str | Path) -> PackageInfo:
        root = Path(package_dir).resolve()
        manifest = load_manifest(root)
        files = resolve_package_files(root, manifest)
        data_graph = Graph()
        for role in (
            PackageFileRole.CORE,
            PackageFileRole.DOMAIN,
            PackageFileRole.MAPPINGS,
            PackageFileRole.RULES,
        ):
            data_graph += _parse_turtle(files[role])
        shapes_graph = _parse_turtle(files[PackageFileRole.SHAPES])
        report = self._validator.validate(data_graph, shapes_graph)
        if not report.conforms:
            raise OntologyValidationError(
                "本体包未通过 SHACL 校验",
                details={
                    "violations": [item.model_dump() for item in report.violations]
                },
            )
        info = PackageInfo(
            package_id=manifest.package_id,
            version=manifest.version,
            sha256=_digest(root / "manifest.yaml", files),
            loaded_at=datetime.now(timezone.utc),
            source=str(root),
        )
        candidate = _OntologySnapshot(
            info=info,
            _data_nt=_serialize(data_graph),
            _shapes_nt=_serialize(shapes_graph),
        )
        with self._lock:
            self._current = candidate
        return info

    def current(self) -> _OntologySnapshot:
        with self._lock:
            if self._current is None:
                raise PackageNotFoundError("当前没有有效本体快照")
            return self._current
```

实现时保留 `_OntologySnapshot`、`_data_nt`、`_shapes_nt` 和图复制函数为基础设施内部实现，不从 `ontology_core.__init__` 导出，避免后续 Python SDK 暴露 RDFLib `Graph`。

在 `ontology_core/__init__.py` 增加公共导出：

```python
from ontology_core.repository import OntologyRepository

__all__ += ["OntologyRepository"]
```

- [ ] **Step 4: 运行 Repository 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_repository.py -v
```

Expected: `5 passed`。

- [ ] **Step 5: 运行本体内核完整测试和格式检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core -v
.\.venv\Scripts\python.exe -m ruff check ontology_core tests/ontology_core
.\.venv\Scripts\python.exe -m black --check ontology_core tests/ontology_core
```

Expected: 所有本体内核测试通过，ruff 和 black exit code 0。

- [ ] **Step 6: 提交**

```powershell
git add ontology_core/repository.py ontology_core/__init__.py tests/ontology_core/test_repository.py
git commit -m "feat: 原子发布有效本体快照"
```

---

### Task 5: 回归验证、工程记录与首个内核里程碑

**Files:**
- Modify: `docs/project-journal/2026-08.md`
- Modify: `docs/career/project-story.md`

**Interfaces:**
- Consumes: Tasks 1-4 的测试输出和 Git 提交。
- Produces: 可复核的里程碑记录；不新增运行时接口。

- [ ] **Step 1: 运行完整后端测试套件**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Expected: 现有测试与新增本体内核测试全部通过。若环境依赖的 PostgreSQL/MySQL 测试无法运行，必须记录具体失败命令、依赖和未验证范围，不能表述为完整通过。

- [ ] **Step 2: 运行项目静态检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
```

Expected: 两条命令 exit code 0。若历史文件存在与本次无关的失败，记录基线并至少保证 `ontology_core` 和 `tests/ontology_core` 通过。

- [ ] **Step 3: 更新工程日志**

在 `docs/project-journal/2026-08.md` 追加一节，必须写入：

- 实际遇到的 RDFLib、pySHACL、Windows 或测试环境问题。
- 最终采用的解决方式和放弃的方案。
- `pytest`、ruff、black 的真实输出摘要。
- Tasks 1-4 的 Git 提交哈希。
- 未完成或未验证的范围。

不得预填不存在的性能收益或测试数量。

- [ ] **Step 4: 更新职业素材**

只有在对应验证通过后，才在 `docs/career/project-story.md` 中加入：

```text
实现纯 Python 本体包内核，支持版本化 RDF/OWL 加载、SHACL 约束校验、内容摘要和失败重载保护；通过不可变 DTO 与复制快照隔离 RDF 图内部状态，为后续多数据库查询编译器提供稳定语义基础。
```

同时附上真实测试数量或明确写“测试数量待完整环境验证”，不得估算。

- [ ] **Step 5: 核对敏感明文**

Run:

```powershell
rg -n "CALL_COUNTS|GPRS_VOLUME|SUBS_NUMBER|D_BBZX" ontology_core tests/ontology_core tests/fixtures/ontology_core
```

Expected: no output。

- [ ] **Step 6: 检查变更范围并提交里程碑记录**

Run:

```powershell
git diff --check
git status --short
```

Expected: 仅显示本任务的两个文档改动，没有用户无关文件。

Commit:

```powershell
git add docs/project-journal/2026-08.md docs/career/project-story.md
git commit -m "docs: 记录本体包内核实施经验"
```

## Completion Gate

在声称本计划完成前，必须重新运行并保存以下新鲜证据：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ontology_core -v
.\.venv\Scripts\python.exe -m ruff check ontology_core tests/ontology_core
.\.venv\Scripts\python.exe -m black --check ontology_core tests/ontology_core
git status --short
git log -5 --oneline
```

完成条件：本体内核测试全部通过；静态检查通过；没有意外工作区改动；每个逻辑任务均有独立提交；工程日志和职业素材仅记录已验证事实。
