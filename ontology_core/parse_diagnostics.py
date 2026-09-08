from __future__ import annotations

from typing import Any

from rdflib.plugins.parsers.notation3 import BadSyntax


def safe_parse_details(
    error_type: str,
    role: str,
    error: BaseException | None = None,
) -> dict[str, str | int]:
    """Build parser diagnostics without retaining source text or local paths."""
    details: dict[str, str | int] = {"error_type": error_type, "role": role}
    location = _safe_location(error)
    if location is not None:
        details.update(location)
    return details


def _safe_location(error: BaseException | None) -> dict[str, int] | None:
    mark: Any = getattr(error, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    if isinstance(line, int) and isinstance(column, int):
        return {"line": line + 1, "column": column + 1}

    if isinstance(error, BadSyntax):
        line = getattr(error, "lines", None)
        source = getattr(error, "_str", None)
        offset = getattr(error, "_i", None)
        if isinstance(line, int) and isinstance(source, (bytes, str)) and isinstance(offset, int):
            newline = b"\n" if isinstance(source, bytes) else "\n"
            line_start = source.rfind(newline, 0, offset) + 1
            line_prefix = source[line_start:offset]
            if isinstance(line_prefix, bytes):
                try:
                    column = len(line_prefix.decode("utf-8")) + 1
                except UnicodeDecodeError:
                    return {"line": line + 1}
            else:
                column = len(line_prefix) + 1
            return {"line": line + 1, "column": column}
    return None
