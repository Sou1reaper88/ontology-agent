"""Snapshot-scoped field detail lookup with a matching enriched validation context."""

from ontology_core.inference_models import CandidateContext


class FieldDetailLookup:
    def __init__(self, catalog, candidates: CandidateContext) -> None:
        self.catalog = catalog
        self.candidates = candidates
        self.loaded = {}

    def search(self, query: str) -> dict:
        """Search the pinned published snapshot, extending the validation scope."""
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("搜索词须为1至500字符")
        found = self.catalog.retrieve(query.strip(), object_limit=8, field_limit_per_object=4)
        objects = {obj.ref: obj for obj in self.candidates.objects}
        returned = []
        for obj in found.objects[:8]:
            if obj.ref not in objects and len(objects) >= 32:
                continue
            objects.setdefault(obj.ref, obj)
            self.loaded.update((f.ref, f) for f in obj.fields if f.details_loaded)
            returned.append(obj)
        families = {family.ref: family for family in self.candidates.families}
        families.update((f.ref, f) for f in found.families
                        if set(f.member_refs).issubset(objects))
        self.candidates = self.candidates.model_copy(update={
            "objects": tuple(objects.values()), "families": tuple(families.values())})
        result = []
        for obj in returned:
            data = obj.model_dump(mode="json", exclude={"fields", "retrieval_score", "matched_terms"})
            data["field_index_columns"] = ["ref", "physical_name", "label"]
            data["field_index"] = [[f.ref, f.physical_name, f.label] for f in obj.fields]
            data["fields"] = [f.model_dump(mode="json", exclude={
                "retrieval_score", "matched_terms", "details_loaded"})
                for f in obj.fields if f.details_loaded]
            result.append(data)
        return {"objects": result,
                "families": [f.model_dump(mode="json") for f in families.values()],
                "truncated": len(returned) < len(found.objects),
                "package_sha256": self.candidates.package_sha256}

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
