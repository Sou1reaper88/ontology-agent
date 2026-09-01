from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.ontology_shadow import OntologyRuntime
from ontology_core.management.bootstrap import (
    ManagedRuntimeBootstrapError,
    recover_managed_runtime,
)
from ontology_core.management.models import (
    DraftDataSource,
    DraftField,
    DraftObject,
    WorkspaceDraft,
)
from ontology_core.management.publisher import PackagePublisher
from ontology_core.management.store import FileDraftStore


@pytest.fixture()
def synthetic_published_workspace(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "management"
    repository_root = tmp_path / "repo"
    store = FileDraftStore(root, repository_root=repository_root)
    store.create_workspace(
        WorkspaceDraft(
            workspace_id="evaluation",
            display_name="Synthetic evaluation",
            package_id="tests.evaluation",
            base_uri="https://example.invalid/tests/evaluation/",
            revision=1,
            updated_at=datetime(2026, 8, 26, tzinfo=UTC),
            data_source=DraftDataSource(
                id="source/evaluation",
                label="Synthetic source",
                platform_type="generic_sql",
                dialect="generic",
                physical_namespace="synthetic",
            ),
            objects=(
                DraftObject(
                    id="object/stable_customer",
                    physical_name="SYNTHETIC_CUSTOMER",
                    label="Synthetic customer",
                    description="Synthetic object used only by tests",
                    fields=(
                        DraftField(
                            id="field/stable_customer/customer_id",
                            physical_name="CUSTOMER_ID",
                            label="Synthetic customer identifier",
                            description="Synthetic key used only by tests",
                            xsd_type="string",
                            primary_key=True,
                        ),
                    ),
                ),
            ),
        )
    )
    version = "1.0.0"
    publisher = PackagePublisher(store, root, OntologyRuntime())
    publisher.publish("evaluation", version, "first", 1, "tester")
    return SimpleNamespace(root=root, version=version)


def test_bootstrap_recovers_exact_active_version(tmp_path, synthetic_published_workspace):
    runtime = OntologyRuntime()
    health = recover_managed_runtime(
        root=synthetic_published_workspace.root,
        workspace_id="evaluation",
        repository_root=tmp_path / "repo",
        runtime=runtime,
    )
    assert health.status == "ok"
    assert runtime.snapshot().info.version == synthetic_published_workspace.version


def test_bootstrap_hides_unconfigured_root(tmp_path):
    with pytest.raises(ManagedRuntimeBootstrapError) as exc_info:
        recover_managed_runtime(
            root="",
            workspace_id="evaluation",
            repository_root=tmp_path / "repo",
            runtime=OntologyRuntime(),
        )
    assert exc_info.value.code == "ontology_runtime_bootstrap_failed"
    assert str(tmp_path) not in str(exc_info.value)
