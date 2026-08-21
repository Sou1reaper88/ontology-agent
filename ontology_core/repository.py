from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
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
                details={"violations": [item.model_dump() for item in report.violations]},
            )
        info = PackageInfo(
            package_id=manifest.package_id,
            version=manifest.version,
            sha256=_digest(root / "manifest.yaml", files),
            loaded_at=datetime.now(UTC),
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
