"""Hive 执行器：接口契约 + Mock 实现。

当前无 Hive 集群连接信息，使用 MockHiveExecutor 返回模拟结果走通流程；
接入真实集群时实现 ImpalaHiveExecutor（impyla 连接池/超时/流式 fetch）并替换。
"""

from __future__ import annotations

import time
from typing import Any, Protocol


class HiveExecutor(Protocol):
    """Hive 执行器接口契约。"""

    def execute(
        self, sql: str, timeout_seconds: int | None = None
    ) -> tuple[list[str], list[list[Any]]]:
        """执行 SQL，返回 (columns, rows)。"""
        ...


class MockHiveExecutor:
    """Mock 执行器：按查询特征返回模拟结果。"""

    def execute(
        self, sql: str, timeout_seconds: int | None = None
    ) -> tuple[list[str], list[list[Any]]]:
        time.sleep(0.1)  # 模拟执行耗时
        columns = ["SUBS_NUMBER", "CITY_ID", "CALL_COUNTS", "GPRS_VOLUME", "P_MON"]
        rows: list[list[Any]] = [
            ["13800000001", "0571", 0, 0, "202607"],
            ["13800000002", "0571", 0, None, "202607"],
            ["13800000003", "0572", None, 0, "202607"],
        ]
        return columns, rows


_executor: HiveExecutor | None = None


def get_hive_executor() -> HiveExecutor:
    """返回 Hive 执行器单例（当前为 Mock，接入真实集群时替换）。"""
    global _executor
    if _executor is None:
        _executor = MockHiveExecutor()
    return _executor
