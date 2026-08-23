from unicodedata import normalize


def normalize_text(value: str) -> str:
    """Normalize human-authored identifiers and labels for deterministic comparison."""
    return normalize("NFKC", value).strip().casefold()
