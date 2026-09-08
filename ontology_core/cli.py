from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyError, OntologyImportError
from ontology_core.inspection import inspect_package, inspection_from_snapshot
from ontology_core.metadata_package import PackageGenerationOptions, generate_metadata_package
from ontology_core.repository import OntologyRepository
from ontology_core.tabular_metadata import (
    DiagnosticSeverity,
    apply_metadata_overrides,
    load_metadata_overrides,
    parse_tabular_metadata,
)


def _write_json(payload: dict[str, Any], *, stream: TextIO | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)


def _write_error(error: OntologyError, *, as_json: bool) -> None:
    if as_json:
        _write_json(
            {
                "code": error.code,
                "details": error.details,
                "message": error.message,
            },
            stream=sys.stderr,
        )
        return
    print(f"{error.code}: {error.message}", file=sys.stderr)


def _inspection_payload(inspection, *, include_identifiers: bool) -> dict[str, Any]:
    return inspection.model_dump(mode="json", exclude_none=not include_identifiers)


def _write_text_inspection(inspection, *, include_identifiers: bool) -> None:
    lines = [
        f"valid: {inspection.package.package_id}@{inspection.package.version}",
        f"sha256: {inspection.package.sha256}",
        "counts:",
        f"  concepts: {inspection.counts.concepts}",
        f"  properties: {inspection.counts.properties}",
        f"  relations: {inspection.counts.relations}",
        f"  rules: {inspection.counts.rules}",
        f"  data_sources: {inspection.counts.data_sources}",
        f"  mappings: {inspection.counts.mappings}",
        f"  temporal_policies: {inspection.counts.temporal_policies}",
    ]
    if include_identifiers:
        lines.append("identifiers:")
        lines.extend(f"  {identifier}" for identifier in inspection.identifiers or ())
    print("\n".join(lines))


def _handle_init(args: argparse.Namespace) -> int:
    manifest = initialize_package(
        Path(args.path),
        package_id=args.package_id,
        base_uri=args.base_uri,
        version=args.version,
    )
    if args.json:
        _write_json(
            {
                "package": {
                    "package_id": manifest.package_id,
                    "version": manifest.version,
                },
                "status": "initialized",
            }
        )
    else:
        print(f"initialized: {manifest.package_id}@{manifest.version}")
    return 0


def _handle_validate(args: argparse.Namespace) -> int:
    repository = OntologyRepository()
    repository.publish(Path(args.path))
    inspection = inspection_from_snapshot(repository.current())
    if args.json:
        _write_json(_inspection_payload(inspection, include_identifiers=False))
    else:
        print(f"valid: {inspection.package.package_id}@{inspection.package.version}")
    return 0


def _handle_inspect(args: argparse.Namespace) -> int:
    inspection = inspect_package(Path(args.path), list_identifiers=args.list_identifiers)
    if args.json:
        _write_json(_inspection_payload(inspection, include_identifiers=args.list_identifiers))
    else:
        _write_text_inspection(inspection, include_identifiers=args.list_identifiers)
    return 0


def _read_utf8(path: Path, *, role: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OntologyImportError(
            "元数据导入文件读取失败",
            details={"role": role, "reason": type(exc).__name__},
        ) from exc


def _import_payload(result) -> dict[str, Any]:
    inspection = result.inspection
    diagnostics = [item.model_dump(mode="json", exclude_none=True) for item in result.diagnostics]
    counts = {
        severity.value: sum(item.severity is severity for item in result.diagnostics)
        for severity in DiagnosticSeverity
    }
    return {
        "status": "imported",
        "target": str(result.target),
        "package": inspection.package.model_dump(mode="json"),
        "counts": inspection.counts.model_dump(mode="json"),
        "diagnostic_counts": counts,
        "diagnostics": diagnostics,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise OntologyImportError(
            "元数据导入报告写入失败",
            details={"reason": type(exc).__name__},
        ) from exc


def _handle_import_tabular(args: argparse.Namespace) -> int:
    draft = parse_tabular_metadata(_read_utf8(Path(args.input), role="input"))
    if args.overrides:
        draft = apply_metadata_overrides(
            draft,
            load_metadata_overrides(Path(args.overrides)),
        )
    result = generate_metadata_package(
        draft,
        Path(args.target),
        PackageGenerationOptions(
            package_id=args.package_id,
            base_uri=args.base_uri,
            version=args.version,
            physical_namespace=args.physical_namespace,
            platform_type=args.platform_type,
            dialect=args.dialect,
        ),
        replace=args.replace,
    )
    payload = _import_payload(result)
    if args.report:
        _write_report(Path(args.report), payload)
    if args.json:
        _write_json(payload)
    else:
        print(
            f"imported: {result.inspection.package.package_id}@"
            f"{result.inspection.package.version}"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontology-core")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init")
    init_parser.add_argument("path")
    init_parser.add_argument("--package-id", required=True)
    init_parser.add_argument("--base-uri", required=True)
    init_parser.add_argument("--version", default="0.1.0")
    init_parser.add_argument("--json", action="store_true")
    init_parser.set_defaults(handler=_handle_init)

    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("path")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(handler=_handle_validate)

    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.add_argument("--list-identifiers", action="store_true")
    inspect_parser.set_defaults(handler=_handle_inspect)

    import_parser = commands.add_parser("import-tabular")
    import_parser.add_argument("input")
    import_parser.add_argument("target")
    import_parser.add_argument("--package-id", required=True)
    import_parser.add_argument("--base-uri", required=True)
    import_parser.add_argument("--version", default="0.1.0")
    import_parser.add_argument("--physical-namespace", required=True)
    import_parser.add_argument("--platform-type", default="generic")
    import_parser.add_argument("--dialect", default="generic")
    import_parser.add_argument("--overrides")
    import_parser.add_argument("--report")
    import_parser.add_argument("--replace", action="store_true")
    import_parser.add_argument("--json", action="store_true")
    import_parser.set_defaults(handler=_handle_import_tabular)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except OntologyError as error:
        _write_error(error, as_json=getattr(args, "json", False))
        return 1
