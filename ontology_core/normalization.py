from unicodedata import normalize


def normalize_text(value: str) -> str:
    """Normalize human-authored identifiers and labels for deterministic comparison."""
    return normalize("NFKC", value).strip().casefold()


def datatype_group(uri: str) -> str:
    """Use the same datatype compatibility rules for evidence and plan validation."""
    name = uri.rsplit("#", maxsplit=1)[-1].casefold()
    if name in {
        "byte",
        "decimal",
        "double",
        "float",
        "int",
        "integer",
        "long",
        "negativeinteger",
        "nonnegativeinteger",
        "nonpositiveinteger",
        "positiveinteger",
        "short",
    }:
        return "numeric"
    if name in {"normalizedstring", "string", "token"}:
        return "string"
    if name in {"date", "datetime", "gyearmonth", "time"}:
        return "date"
    if name == "boolean":
        return "boolean"
    return uri.casefold()
