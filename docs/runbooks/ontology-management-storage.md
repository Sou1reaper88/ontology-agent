# 本体管理外部存储运行手册

本体草稿、不可变发布版本和活动版本指针必须保存在源码仓库之外。应用不会为未配置的环境静默创建临时本体目录。

## 本地配置

在不受 Git 管理的 `.env` 中配置：

```dotenv
ONTOLOGY__MANAGEMENT_ROOT=D:/Projects/ontology-agent-data/ontology-management
ONTOLOGY__MANAGEMENT_WORKSPACE=evaluation
```

创建当前本地目录：

```powershell
New-Item -ItemType Directory -Path 'D:\Projects\ontology-agent-data\ontology-management' -Force
```

该目录不能位于源码仓库、`.local`、`.worktrees` 或系统临时目录内，也不能经过符号链接或 Windows reparse point。

## 启动与就绪检查

后端启动时只恢复活动版本指针明确引用的不可变版本，不会自行选择“最新”目录。检查服务状态：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/ready'
```

未发布本体、活动指针无效或存储未配置时，`ontology` 为 `degraded`，`ontology_reason` 只返回稳定错误原因，不返回本地路径或本体内容。

登录并准备认证头后检查活动版本：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/ontology-packages/active' -Headers $headers
```

发布后记录版本号与内容摘要，重启后端，再次调用就绪和活动版本接口；版本号与摘要必须保持一致。

## 备份与恢复边界

- 备份整个 `ONTOLOGY__MANAGEMENT_ROOT`，包括工作区草稿、版本目录、版本摘要和活动指针。
- 恢复时保持原有目录层级和文件权限，随后重启后端并核对活动版本摘要。
- 不要把备份复制进源码仓库，也不要把真实本体包、字段描述或业务口径加入 Git。
- 已删除的草稿只能重新导入源元数据并发布新的不可变版本。系统不能从评测 SQL 反向重建已经删除的业务语义和口径。

## 故障定位

1. `/health` 只表示进程存活；本体是否可用以 `/ready` 为准。
2. `ontology_management_configuration_error`：检查外部目录配置和安全边界。
3. `published_version_not_found`：检查活动指针引用的版本目录是否完整。
4. 发布失败时，运行时应继续保留上一个有效快照；修复草稿或存储问题后重新发布，不要手工改写不可变版本。
