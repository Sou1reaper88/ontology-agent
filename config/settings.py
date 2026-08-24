"""应用配置中心。

通过 Pydantic Settings 读取 .env 与 YAML，实现配置与逻辑分离。
环境分离：dev / staging / prod，通过 .env 与 settings.yaml 切换。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL 连接配置（业务库）。"""

    host: str = "localhost"
    port: int = 5432
    user: str = "ontology"
    password: str = "ontology"
    name: str = "ontology_agent"

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class MySQLSettings(BaseSettings):
    """本体表结构库 MySQL 连接配置（OAG 知识源，与业务 PG 库隔离）。"""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "root"
    database: str = "ontology"  # 对象定义（业务表）库
    meta_database: str = "ontology_meta"  # 本体元数据（关系/逻辑/字段描述/表描述）库


class RedisSettings(BaseSettings):
    """Redis 连接配置（任务队列 / 结果缓存 / 会话）。"""

    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


class HiveSettings(BaseSettings):
    """Hive 集群连接配置（执行生成的 HiveSQL）。"""

    host: str = "localhost"
    port: int = 10000
    user: str = "hive"
    database: str = "default"
    timeout_seconds: int = 300


class LLMSettings(BaseSettings):
    """商业 LLM API 配置。

    LLM 仅参与生成 SQL（接收需求 + 表结构，不脱敏）；
    SQL 执行与结果存储在本地，数据不流出。
    """

    base_url: str = ""
    api_key: str = ""
    model: str = "qwen2.5-coder-32b-instruct"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_seconds: int = 60


class OntologySettings(BaseSettings):
    """现有本体平台 API 配置（4 个工具）。"""

    base_url: str = ""
    ontology_id: str = ""
    timeout_seconds: int = 30
    retry_times: int = 2
    package_path: str = ""
    shadow_enabled: bool = True


class Settings(BaseSettings):
    """全局配置入口。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    app_name: str = "ontology-agent"
    env: str = "dev"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 480

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    mysql: MySQLSettings = Field(default_factory=MySQLSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    hive: HiveSettings = Field(default_factory=HiveSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ontology: OntologySettings = Field(default_factory=OntologySettings)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        """从 YAML 文件加载配置（与 .env 合并，.env 优先）。"""
        path = Path(path)
        if not path.exists():
            return cls()
        with path.open(encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls(**data)


def get_settings() -> Settings:
    """获取配置单例（YAML 提供默认值，.env 覆盖敏感项）。"""
    yaml_path = Path(__file__).resolve().parent / "settings.yaml"
    return Settings.from_yaml(yaml_path)


settings = get_settings()
