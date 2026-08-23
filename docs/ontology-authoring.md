# 使用 Protégé 编辑外部本体包

本指南面向本项目的外部、私有 RDF/Turtle 本体包。RDF/OWL 和 SHACL 是本体事实源；本项目的 Python `OntologyRepository` 负责加载、校验和发布不可变快照，`OntologyResolver` 是快照之上的只读 Python 查询边界。

> 下文所有 Turtle 片段都是文档示例，不是生产默认内容。它们只使用 `https://example.invalid/` 下的中性标识；真实本体包应存放在应用仓库之外的受控私有目录或私有 Git 仓库。

## 1. 前置条件：安装并打开 Protégé

- 按 [Protégé 官方安装文档](https://protegeproject.github.io/protege/installation/) 安装桌面应用；需要项目入口时可访问 [Protégé 主页](https://protege.stanford.edu/)。
- 使用项目 Python 虚拟环境运行命令；CLI 入口是 `python -m ontology_core`，包含 `init`、`validate` 和 `inspect`。
- 先在外部私有工作目录创建本体包，再用 Protégé 打开该目录中的 `domain.ttl`。不要在应用代码仓库内创建真实领域包。

Protégé 用于编辑 RDF/OWL；是否可被项目使用始终以本地 `validate` 的 SHACL 与 Python 语义校验结果为准。

## 2. 创建外部私有本体包

在私有目录初始化空白包。以下路径、包 ID 和 URI 都是中性示例：

```powershell
python -m ontology_core init D:\private\ontology-package --package-id private.package --base-uri https://example.invalid/private/
```

可选 `--version`；未提供时版本为 `0.1.0`。初始化只生成通用词汇、SHACL 和空白模块，不生成领域概念、真实表字段或业务样例。目标目录必须不存在或为空；命令不会覆盖非空目录。

生成包固定包含：

```text
manifest.yaml
core.ttl
domain.ttl
rules.ttl
mappings.ttl
shapes.ttl
```

## 3. 打开 `domain.ttl` 并保留模块边界

用 Protégé 打开 `domain.ttl`，在其中编辑领域概念、数据属性与对象关系。`rules.ttl` 放规则个体，`mappings.ttl` 放逻辑数据源与物理映射个体。

保留 `manifest.yaml` 的五个角色映射以及所有六个文件。`core.ttl` 定义固定的 `urn:ontology-agent:core#` 通用词汇，`shapes.ttl` 定义通用 SHACL 约束；日常领域编辑不应删除、重命名或用领域实例替换它们。修改通用词汇或 SHACL 是兼容性变更，应单独评审并同步升级版本。

Protégé 的图形界面适合创建类、属性和个体；保存后请检查 Turtle 序列化仍保留本指南所示的 `oa:` 标记和 `rdfs:domain` / `rdfs:range` 三元组。CLI 不会把仅有 OWL 元模型类型、但没有 `oa:` 标记的元素当作领域元素。

## 4. 创建概念：同时声明 `owl:Class` 与 `oa:Concept`

在 Protégé 中创建类后，确保其 RDF 类型同时包含 `owl:Class` 和 `oa:Concept`，并设置一个全局唯一的 `oa:shortName` 和至少一个 `rdfs:label`：

```turtle
@prefix oa: <urn:ontology-agent:core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.invalid/private/Concept> a owl:Class, oa:Concept ;
    oa:shortName "Concept" ;
    rdfs:label "概念"@zh ;
    rdfs:label "Concept"@en ;
    rdfs:comment "Neutral documentation concept." .

<https://example.invalid/private/OtherConcept> a owl:Class, oa:Concept ;
    oa:shortName "OtherConcept" ;
    rdfs:label "另一概念"@zh .
```

`owl:Class` 保留标准 OWL 类语义；`oa:Concept` 是项目的领域元素标记，用于把领域概念与 `core.ttl` 中的通用元词汇区分开。父概念用 IRI `rdfs:subClassOf` 指向另一个已标记概念。

## 5. 创建数据属性与对象关系

在 Protégé 的 Data Properties 中创建数据属性，在 Object Properties 中创建概念间关系。保存后的 Turtle 必须包含相应的项目标记、源概念 domain 和 range。

```turtle
@prefix oa: <urn:ontology-agent:core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.invalid/private/attribute> a owl:DatatypeProperty, oa:Property ;
    oa:shortName "attribute" ;
    rdfs:label "属性"@zh ;
    rdfs:domain <https://example.invalid/private/Concept> ;
    rdfs:range xsd:string .

<https://example.invalid/private/relatedTo> a owl:ObjectProperty, oa:Relation ;
    oa:shortName "relatedTo" ;
    rdfs:label "关联到"@zh ;
    rdfs:domain <https://example.invalid/private/Concept> ;
    rdfs:range <https://example.invalid/private/OtherConcept> .
```

`oa:Property` 只能表示数据属性，range 必须是 `http://www.w3.org/2001/XMLSchema#` 命名空间中的 XSD 数据类型 URI，不接受自定义 datatype IRI。`oa:Relation` 表示对象关系，domain 与 range 必须指向已标记的概念。SHACL 同时要求每个标记元素有一个 IRI、一个 short name 和至少一个 label。

## 6. 创建规则、数据源与映射个体

在 Protégé 的 Individuals 中创建以下个体；它们不是 OWL 类。规则以 `oa:BusinessRule` 标记，数据源以 `oa:DataSource` 标记，映射以 `oa:PhysicalMapping` 标记：

```turtle
@prefix oa: <urn:ontology-agent:core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.invalid/private/rule> a oa:BusinessRule ;
    oa:shortName "rule" ;
    rdfs:label "中性规则"@zh ;
    oa:appliesTo <https://example.invalid/private/Concept> ;
    oa:usesProperty <https://example.invalid/private/attribute> .

<https://example.invalid/private/source> a oa:DataSource ;
    oa:shortName "source" ;
    rdfs:label "逻辑数据源"@zh ;
    oa:platformType "generic" .

<https://example.invalid/private/mapping> a oa:PhysicalMapping ;
    oa:shortName "mapping" ;
    rdfs:label "中性映射"@zh ;
    oa:semanticElement <https://example.invalid/private/attribute> ;
    oa:dataSource <https://example.invalid/private/source> ;
    oa:objectName "neutral_object" ;
    oa:fieldName "neutral_field" .
```

规则的条件树只能使用 `oa:AllOf`、`oa:AnyOf`、`oa:Not`、`oa:Eq`、`oa:Ne`、`oa:Gt`、`oa:Gte`、`oa:Lt`、`oa:Lte`、`oa:In`、`oa:Between`、`oa:IsNull` 等通用节点；比较左值引用属性 IRI，右值是 RDF 字面量或参数引用。`In` 与 `Between` 使用 RDF Collection，后者按下界、上界顺序保存。该阶段只校验和解析规则，不执行或编译规则。

## 7. 稳定标识、短名、语言标签与版本规则

- URI 必须是稳定绝对 URI；相对 URI 和 `file:` URI 会被拒绝，以免同一本体在不同本地路径下得到不同目录或泄露物理路径。创建后不要因展示文案或物理实现变化而替换。推荐在私有包自己的 base URI 下创建，例如 `https://example.invalid/private/Concept`。
- `oa:shortName` 是 API 与人工引用的稳定短名，必须在整个有效包内按 Unicode NFKC、去除首尾空白和大小写折叠后的结果全局唯一，不能依赖 RDF 图的遍历顺序。
- `rdfs:label` 用于显示；至少保留一个标签。Resolver 选择显示名时优先中文（`zh` / `zh-*`），其次无语言标签，再其次其他语言标签；同一层级按规范化文本稳定排序。
- Resolver 对短名、标签和搜索文本执行 Unicode NFKC、去除首尾空白与大小写折叠；URI 查询保持精确匹配。搜索按精确 URI/短名、精确标签、短名前缀、标签包含、说明包含的等级排序。
- `version` 是包清单元数据。每次经过评审的语义变更都应在私有仓库中更新版本并保留 Git 记录；当前初始化器只要求版本为非空字符串，不强制某一种版本号格式。

## 8. 本地校验与检查

编辑后先校验，再检查公开摘要与元素统计：

```powershell
python -m ontology_core validate D:\private\ontology-package
python -m ontology_core inspect D:\private\ontology-package
python -m ontology_core inspect D:\private\ontology-package --json --list-identifiers
```

`validate` 执行清单、路径、Turtle、SHACL 和 Python 语义引用校验。`inspect` 只在包有效时输出 package ID、版本、SHA-256 摘要与六类元素数量；只有指定 `--list-identifiers` 才会输出排序后的 URI 标识列表。加 `--json` 时成功 JSON 写到 stdout，ontology 错误 JSON 写到 stderr，便于 CI 检查退出码和机器读取。

## 9. Git 审查与部署流程

1. 包共六个文件：五个 TTL 模块和一个 `manifest.yaml`。日常编辑 `domain.ttl`、`rules.ttl`、`mappings.ttl`；`core.ttl`、`shapes.ttl` 与 manifest 作为受控变更保留并单独审查。
2. 运行 `validate` 和 `inspect --json --list-identifiers`，将输出和退出码纳入 CI 或评审证据。
3. 审查 Turtle 差异：确认 URI、short name、语言标签、引用和版本变更符合预期。
4. 将通过评审的本体包提交到独立私有 Git 仓库；应用只通过显式文件系统路径读取已检出的版本。
5. 由 `OntologyRepository.publish()` 构造候选快照。候选包任一步校验、解析或序列化失败时，当前已发布快照不会被替换；成功后才原子切换。

该里程碑没有在线写入、远程发布或自动审批接口。不要把真实本体包、导出的真实数据或凭据提交到本应用仓库。

## 10. 禁止内容与存储边界

禁止在 `domain.ttl`、`rules.ttl` 或 `mappings.ttl` 中写入：

- 数据库主机、端口、用户名、密码、token、secret、连接字符串或其他凭据；对 DataSource 与 PhysicalMapping，解析器会拒绝常见凭据谓词的 fragment、path 和 URN 变体。
- SQL 片段、可执行 SQL、真实查询条件或把规则写成任意 SQL 文本；规则应使用受支持的结构化条件树。
- 真实用户数据、真实业务口径、真实表名或字段名。
- 存放在本应用代码仓库内的真实领域本体包。

物理对象名、字段名和 join path 仅属于映射层；它们不是领域概念的属性。数据库连接与执行配置必须留在受控的运行环境或后续数据源适配层，而不是 RDF 映射文件。
