"""Snapshot-scoped field detail lookup with a matching enriched validation context."""

from ontology_core.inference_models import CandidateContext


class FieldDetailLookup:
    def __init__(self, catalog, candidates: CandidateContext) -> None:
        self.catalog = catalog
        self.candidates = candidates
        self.loaded = {}

    def __call__(self, refs: list[str]) -> list[dict]:
        allowed = {f.ref for o in self.candidates.objects for f in o.fields}
        if not refs or len(refs) > 64 or any(ref not in allowed for ref in refs):
            raise ValueError("字段详情查询只能引用当前候选目录内的1至64个字段")
        fields = [self.catalog.field(ref) for ref in dict.fromkeys(refs)]
        self.loaded.update((f.ref, f) for f in fields)
        return [
            f.model_dump(mode="json", exclude={"retrieval_score", "matched_terms"}) for f in fields
        ]

    def enriched(self) -> CandidateContext:
        if not self.loaded:
            return self.candidates
        return self.candidates.model_copy(
            update={
                "objects": tuple(
                    obj.model_copy(
                        update={"fields": tuple(self.loaded.get(f.ref, f) for f in obj.fields)}
                    )
                    for obj in self.candidates.objects
                )
            }
        )
