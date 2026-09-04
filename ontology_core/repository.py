from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser

from ontology_core.errors import (
    OntologyParseError,
    OntologyValidationError,
    PackageNotFoundError,
)
from ontology_core.manifest import _load_manifest_with_bytes, resolve_package_files
from ontology_core.models import PackageFileRole, PackageInfo
from ontology_core.parse_diagnostics import safe_parse_details
from ontology_core.semantic_models import SemanticCatalog
from ontology_core.semantic_parser import parse_catalog
from ontology_core.temporal_conventions import with_automatic_temporal_policies
from ontology_core.validator import OntologyValidator


def _read_package_files(files: Mapping[PackageFileRole, Path]) -> dict[PackageFileRole, bytes]:
    contents: dict[PackageFileRole, bytes] = {}
    for role in PackageFileRole:
        path = files[role]
        try:
            contents[role] = path.read_bytes()
        except FileNotFoundError as exc:
            raise PackageNotFoundError(
                "本体包文件不存在",
                details={"role": role.value, "path": str(path)},
            ) from exc
        except OSError as exc:
            raise OntologyParseError(
                "本体包文件读取失败",
                details=safe_parse_details("io_error", role.value),
            ) from exc
    return contents


class _LexicalTurtleSink(RDFSink):
    """Create literals without consulting RDFLib's process-wide normalization flag."""

    def newLiteral(self, s: str, dt, lang):  # noqa: N802
        if dt:
            return Literal(s, datatype=dt, normalize=False)
        return Literal(s, lang=lang, normalize=False)


def _parse_with_lexical_sink(content: str, *, base_uri: str) -> Graph:
    graph = Graph()
    parser = SinkParser(
        _LexicalTurtleSink(graph),
        baseURI=base_uri,
        turtle=True,
    )
    parser.loadBuf(content)
    for prefix, namespace in parser._bindings.items():
        graph.bind(prefix, namespace)
    return graph


def _parse_turtle(content: bytes, path: Path, role: PackageFileRole) -> Graph:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OntologyParseError(
            "本体 Turtle 文件解析失败",
            details=safe_parse_details("invalid_utf8", role.value),
        ) from exc
    try:
        return _parse_with_lexical_sink(text, base_uri=path.resolve().as_uri())
    except Exception as exc:
        raise OntologyParseError(
            "本体 Turtle 文件解析失败",
            details=safe_parse_details("turtle_syntax_error", role.value, exc),
        ) from exc


def _digest(
    manifest: bytes,
    files: Mapping[PackageFileRole, bytes],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"manifest\0")
    digest.update(manifest)
    digest.update(b"\0")
    for role in PackageFileRole:
        digest.update(role.value.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[role])
        digest.update(b"\0")
    return digest.hexdigest()


def _serialize(graph: Graph, graph_name: str) -> str:
    try:
        return graph.serialize(format="nt")
    except Exception as exc:
        raise OntologyParseError(
            "本体图序列化失败",
            details={"error_type": "serialization_error", "graph": graph_name},
        ) from exc


def _copy_graph(serialized: str) -> Graph:
    return _parse_with_lexical_sink(
        serialized,
        base_uri="urn:ontology-agent:snapshot",
    )


@dataclass(frozen=True)
class OntologySnapshot:
    info: PackageInfo
    catalog: SemanticCatalog
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
        self._current: OntologySnapshot | None = None

    def publish(self, package_dir: str | Path) -> PackageInfo:
        root = Path(package_dir).resolve()
        manifest, manifest_bytes = _load_manifest_with_bytes(root)
        files = resolve_package_files(root, manifest)
        file_bytes = _read_package_files(files)
        data_graph = Graph()
        for role in (
            PackageFileRole.CORE,
            PackageFileRole.DOMAIN,
            PackageFileRole.MAPPINGS,
            PackageFileRole.RULES,
        ):
            data_graph += _parse_turtle(file_bytes[role], files[role], role)
        shapes_graph = _parse_turtle(
            file_bytes[PackageFileRole.SHAPES],
            files[PackageFileRole.SHAPES],
            PackageFileRole.SHAPES,
        )
        report = self._validator.validate(data_graph, shapes_graph)
        if not report.conforms:
            raise OntologyValidationError(
                "本体包未通过 SHACL 校验",
                details={"violations": [item.model_dump() for item in report.violations]},
            )
        catalog = with_automatic_temporal_policies(parse_catalog(data_graph))
        info = PackageInfo(
            package_id=manifest.package_id,
            version=manifest.version,
            sha256=_digest(manifest_bytes, file_bytes),
            loaded_at=datetime.now(UTC),
            source=str(root),
        )
        candidate = OntologySnapshot(
            info=info,
            catalog=catalog,
            _data_nt=_serialize(data_graph, "data"),
            _shapes_nt=_serialize(shapes_graph, "shapes"),
        )
        with self._lock:
            self._current = candidate
        return info

    def current(self) -> OntologySnapshot:
        with self._lock:
            if self._current is None:
                raise PackageNotFoundError("当前没有有效本体快照")
            return self._current
