from pathlib import Path

import pytest
from rdflib.namespace import OWL, RDF

from ontology_core.errors import OntologyValidationError, PackageNotFoundError
from ontology_core.repository import OntologyRepository


def test_publish_valid_package_exposes_info_and_graph_copy(valid_package_dir: Path) -> None:
    repository = OntologyRepository()
    info = repository.publish(valid_package_dir)
    snapshot = repository.current()
    first = snapshot.copy_data_graph()
    first.remove((None, None, None))
    second = snapshot.copy_data_graph()

    assert info.package_id == "example.neutral"
    assert info.version == "1.0.0"
    assert len(info.sha256) == 64
    assert len(second) > 0
    assert any(second.triples((None, RDF.type, OWL.Class)))


def test_current_before_publish_raises_stable_error() -> None:
    with pytest.raises(PackageNotFoundError) as caught:
        OntologyRepository().current()
    assert caught.value.code == "package_not_found"


def test_failed_reload_keeps_previous_snapshot(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    repository = OntologyRepository()
    previous = repository.publish(valid_package_dir)
    broken = tmp_path / "broken"
    broken.mkdir()
    for source in valid_package_dir.iterdir():
        broken.joinpath(source.name).write_bytes(source.read_bytes())
    broken.joinpath("domain.ttl").write_text(
        "@prefix ex: <https://example.invalid/ontology/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:Unlabelled a owl:Class .\n",
        encoding="utf-8",
    )

    with pytest.raises(OntologyValidationError):
        repository.publish(broken)

    assert repository.current().info.sha256 == previous.sha256


def test_same_bytes_produce_same_digest(valid_package_dir: Path) -> None:
    first = OntologyRepository().publish(valid_package_dir)
    second = OntologyRepository().publish(valid_package_dir)
    assert first.sha256 == second.sha256


def test_manifest_change_changes_digest(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "copied"
    copied.mkdir()
    for source in valid_package_dir.iterdir():
        copied.joinpath(source.name).write_bytes(source.read_bytes())
    first = OntologyRepository().publish(copied)
    manifest = copied.joinpath("manifest.yaml")
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"),
        encoding="utf-8",
    )
    second = OntologyRepository().publish(copied)
    assert first.sha256 != second.sha256
