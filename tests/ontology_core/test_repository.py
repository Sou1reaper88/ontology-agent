from pathlib import Path

import pytest
from rdflib.namespace import OWL, RDF

from ontology_core.errors import (
    OntologyParseError,
    OntologyValidationError,
    PackageNotFoundError,
)
from ontology_core.repository import OntologyRepository
from ontology_core.validator import OntologyValidator


def _copy_package(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir()
    for source in source_dir.iterdir():
        target_dir.joinpath(source.name).write_bytes(source.read_bytes())


class _MutatingValidator:
    def __init__(self, target: Path) -> None:
        self._target = target

    def validate(self, data_graph, shapes_graph):
        report = OntologyValidator().validate(data_graph, shapes_graph)
        self._target.write_text(
            "@prefix ex: <https://example.invalid/ontology/> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            'ex:Rewritten a owl:Class ; rdfs:label "Rewritten" .\n',
            encoding="utf-8",
        )
        return report


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
        "@prefix oa: <urn:ontology-agent:core#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:Unlabelled a owl:Class, oa:Concept .\n",
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


def test_digest_uses_the_same_bytes_as_the_published_graph(
    valid_package_dir: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "copied"
    _copy_package(valid_package_dir, copied)
    domain = copied / "domain.ttl"

    first = OntologyRepository(validator=_MutatingValidator(domain)).publish(copied)
    second = OntologyRepository().publish(copied)

    assert first.sha256 != second.sha256


def test_disappearing_file_raises_stable_error_and_keeps_snapshot(
    valid_package_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = tmp_path / "copied"
    _copy_package(valid_package_dir, copied)
    repository = OntologyRepository()
    previous = repository.publish(valid_package_dir)
    target = copied / "domain.ttl"
    original_read_bytes = Path.read_bytes

    def disappearing(path: Path) -> bytes:
        if path == target:
            raise FileNotFoundError(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", disappearing)

    with pytest.raises(PackageNotFoundError) as caught:
        repository.publish(copied)
    assert caught.value.details["role"] == "domain"
    assert repository.current().info.sha256 == previous.sha256


def test_unreadable_file_raises_parse_error_and_keeps_snapshot(
    valid_package_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = tmp_path / "copied"
    _copy_package(valid_package_dir, copied)
    repository = OntologyRepository()
    previous = repository.publish(valid_package_dir)
    target = copied / "rules.ttl"
    original_read_bytes = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == target:
            raise PermissionError(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    with pytest.raises(OntologyParseError) as caught:
        repository.publish(copied)
    assert caught.value.details["role"] == "rules"
    assert repository.current().info.sha256 == previous.sha256


def test_serialization_failure_raises_parse_error_and_keeps_snapshot(
    valid_package_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = OntologyRepository()
    previous = repository.publish(valid_package_dir)

    def fail_serialize(*_args, **_kwargs):
        raise OSError("serialization failed")

    monkeypatch.setattr("ontology_core.repository.Graph.serialize", fail_serialize)

    with pytest.raises(OntologyParseError) as caught:
        repository.publish(valid_package_dir)
    assert caught.value.details["graph"] == "data"
    assert repository.current().info.sha256 == previous.sha256
