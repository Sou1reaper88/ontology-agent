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
    def require_all_roles(self) -> PackageManifest:
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
