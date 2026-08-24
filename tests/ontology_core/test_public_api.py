import ontology_core
from ontology_core.repository import OntologySnapshot as RepositoryOntologySnapshot


def test_ontology_snapshot_is_exported_from_package_root() -> None:
    from ontology_core import OntologySnapshot

    assert OntologySnapshot is RepositoryOntologySnapshot
    assert "OntologySnapshot" in ontology_core.__all__


def test_tabular_metadata_import_interfaces_are_exported_from_package_root() -> None:
    expected = {
        "DiagnosticSeverity",
        "FieldMetadata",
        "ImportDiagnostic",
        "MetadataImportResult",
        "MetadataOverrides",
        "OntologyImportError",
        "PackageGenerationOptions",
        "SourceLocation",
        "TableMetadata",
        "TabularMetadataDraft",
        "analyze_metadata",
        "apply_metadata_overrides",
        "generate_metadata_package",
        "load_metadata_overrides",
        "parse_tabular_metadata",
        "raise_for_blocking_diagnostics",
    }

    assert expected <= set(ontology_core.__all__)
    assert all(hasattr(ontology_core, name) for name in expected)
