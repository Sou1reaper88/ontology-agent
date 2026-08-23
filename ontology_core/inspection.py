from __future__ import annotations

from pathlib import Path

from ontology_core.repository import OntologyRepository, OntologySnapshot
from ontology_core.semantic_models import (
    InspectedPackage,
    PackageInspection,
    SemanticCatalog,
    SemanticCounts,
)


def _counts(catalog: SemanticCatalog) -> SemanticCounts:
    return SemanticCounts(
        concepts=len(catalog.concepts),
        properties=len(catalog.properties),
        relations=len(catalog.relations),
        rules=len(catalog.rules),
        data_sources=len(catalog.data_sources),
        mappings=len(catalog.mappings),
    )


def inspection_from_snapshot(
    snapshot: OntologySnapshot,
    *,
    list_identifiers: bool = False,
) -> PackageInspection:
    catalog = snapshot.catalog
    identifiers = None
    if list_identifiers:
        identifiers = tuple(
            sorted(
                element.uri
                for elements in (
                    catalog.concepts,
                    catalog.properties,
                    catalog.relations,
                    catalog.rules,
                    catalog.data_sources,
                    catalog.mappings,
                )
                for element in elements
            )
        )
    return PackageInspection(
        package=InspectedPackage(
            package_id=snapshot.info.package_id,
            version=snapshot.info.version,
            sha256=snapshot.info.sha256,
        ),
        counts=_counts(catalog),
        identifiers=identifiers,
    )


def inspect_package(path: str | Path, *, list_identifiers: bool = False) -> PackageInspection:
    repository = OntologyRepository()
    repository.publish(path)
    return inspection_from_snapshot(repository.current(), list_identifiers=list_identifiers)
