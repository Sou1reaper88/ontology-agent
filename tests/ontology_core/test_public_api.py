import ontology_core
from ontology_core.repository import OntologySnapshot as RepositoryOntologySnapshot


def test_ontology_snapshot_is_exported_from_package_root() -> None:
    from ontology_core import OntologySnapshot

    assert OntologySnapshot is RepositoryOntologySnapshot
    assert "OntologySnapshot" in ontology_core.__all__
