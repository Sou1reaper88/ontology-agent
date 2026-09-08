"""Read-only time policies derived from managed physical metadata."""

from ontology_core.management.models import DraftTemporalPolicy, WorkspaceDraft
from ontology_core.temporal_conventions import partition_convention


def effective_temporal_policies(draft: WorkspaceDraft) -> tuple[DraftTemporalPolicy, ...]:
    conventional_ids = {o.id for o in draft.objects if partition_convention(o.physical_name)}
    policies = [p for p in draft.temporal_policies if p.object_id not in conventional_ids]
    for object_ in draft.objects:
        convention = partition_convention(object_.physical_name)
        if convention is None or object_.status != "active":
            continue
        name, grain, strategy = convention
        fields = [
            f for f in object_.fields if f.physical_name.upper() == name and f.status == "active"
        ]
        if len(fields) == 1:
            policies.append(
                DraftTemporalPolicy(
                    object_id=object_.id,
                    partition_field_id=fields[0].id,
                    grain=grain,
                    default_strategy=strategy,
                )
            )
    return tuple(policies)
