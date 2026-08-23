from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyError
from ontology_core.inspection import inspect_package, inspection_from_snapshot
from ontology_core.repository import OntologyRepository


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except OntologyError as error:
        _write_error(error, as_json=getattr(args, "json", False))
        return 1
