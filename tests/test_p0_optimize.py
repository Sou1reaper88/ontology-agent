"""P0 优化测试：元数据 TTL 缓存 + 字段级上下文裁剪。"""

from __future__ import annotations

from agent import orchestrator as orch
from tools.ontology_client import _cached, clear_ontology_cache


def _map20() -> dict[str, str]:
    return {f"字段{i:02d}": f"FIELD_{i:02d}" for i in range(1, 21)}


# ---------------------------------------------------------------------------
# 元数据 TTL 缓存
# ---------------------------------------------------------------------------


def test_cache_loads_once_within_ttl() -> None:
    """TTL 内多次调用只执行一次 loader；清理后重新加载。"""
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [{"x": 1}]

    clear_ontology_cache()
    assert _cached("t", loader) == [{"x": 1}]
    assert _cached("t", loader) == [{"x": 1}]
    assert calls["n"] == 1


def test_cache_returns_deepcopy() -> None:
    """命中缓存返回深拷贝：调用方修改不污染缓存。"""
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [{"x": 1}]

    clear_ontology_cache()
    a = _cached("t", loader)
    a.append({"x": 2})
    assert _cached("t", loader) == [{"x": 1}]
    assert calls["n"] == 1


def test_cache_clear_reloads() -> None:
    """clear_ontology_cache 后强制重新加载。"""
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return ["v"]

    clear_ontology_cache()
    _cached("t", loader)
    clear_ontology_cache()
    assert _cached("t", loader) == ["v"]
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# 字段级上下文裁剪
# ---------------------------------------------------------------------------


def test_filter_no_keyword_keeps_all() -> None:
    """问题未命中业务词 → 保守全量，不裁剪。"""
    m = _map20()
    assert orch._filter_field_map("随便查一下", m) == m


def test_filter_empty_map() -> None:
    assert orch._filter_field_map("查询沉默用户", {}) == {}


def test_filter_keeps_hits_partition_and_floor() -> None:
    """命中词字段 + 触发词关联字段 + 分区字段必保留，其余按保底补足，无关字段被裁。"""
    m = _map20()
    m.update({"通话次数": "CALL_COUNTS", "GPRS流量": "GPRS_VOLUME", "用户号码": "SUBS_NUMBER"})
    kept = orch._filter_field_map("查询6月沉默用户", m, {"P_MON"})
    assert kept["通话次数"] == "CALL_COUNTS"  # "沉默"触发词关联字段
    assert kept["GPRS流量"] == "GPRS_VOLUME"
    assert "用户号码" in kept  # 问题含"用户"
    assert len(kept) == orch._KEEP_MIN_FIELDS  # 保底补足到 15
    assert "字段20" not in kept  # 无关字段被裁


def test_filter_keeps_partition_even_without_hit_word() -> None:
    """分区字段不依赖问题命中词，始终保留（即使中文名不含命中词）。"""
    m = {"用户号码": "SUBS_NUMBER", "账期": "P_MON"}
    for i in range(3, 24):
        m[f"字段{i:02d}"] = f"F{i:02d}"
    kept = orch._filter_field_map("查询沉默用户", m, {"P_MON"})
    assert kept["账期"] == "P_MON"  # 分区字段保留
    assert kept["用户号码"] == "SUBS_NUMBER"  # 命中"用户"
    assert len(kept) == orch._KEEP_MIN_FIELDS  # 保底补足到 15
    assert "字段16" not in kept  # 靠后的无关字段被裁
    assert "字段23" not in kept
