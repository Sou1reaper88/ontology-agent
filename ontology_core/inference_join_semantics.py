"""Structural checks for directional candidate joins; no natural-language guessing."""


def join_semantics_error(joins, requested_fields, family_by_member):
    def node(ref):
        return family_by_member.get(ref, ref)

    directed_rights = set()
    for join in joins:
        left, right = node(join.left_object_ref), node(join.right_object_ref)
        if join.join_type == "inner":
            continue
        if left == right or right in directed_rights:
            return "左连接/排除连接的右表必须是独立且唯一的逻辑对象"
        directed_rights.add(right)
        if join.join_type == "anti":
            if any(node(field.object_ref) == right for field in requested_fields):
                return "排除表不能提供输出字段"
            if any(other is not join and right in (
                node(other.left_object_ref), node(other.right_object_ref)
            ) for other in joins):
                return "排除表不能继续参与其他连接，请使用独立排除集合"
    return None
