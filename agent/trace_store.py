"""生成链路 trace 的内存存储（实时进度轮询用）。

消息生成在后台线程执行，每个节点完成时把步骤写入这里；
前端轮询 `GET /conversations/messages/{id}/status` 逐步读取。
生成完成后 trace 会落库到 conversation_messages.trace，本存储仅作实时过程态。
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_traces: dict[int, dict[str, Any]] = {}


def new_trace(message_id: int) -> None:
    """登记一条生成中的消息。"""
    with _lock:
        _traces[message_id] = {
            "status": "generating",
            "steps": [],
            "output": None,
            "error": None,
            "started_at": time.time(),
        }


def append_step(message_id: int, step: dict[str, Any]) -> None:
    """追加一个已完成节点步骤。"""
    with _lock:
        tr = _traces.get(message_id)
        if tr is not None:
            tr["steps"].append(step)


def set_output(message_id: int, output: dict[str, Any]) -> None:
    """标记生成成功并缓存输出。"""
    with _lock:
        tr = _traces.get(message_id)
        if tr is not None:
            tr["status"] = "success"
            tr["output"] = output


def set_failed(message_id: int, error: str) -> None:
    """标记生成失败。"""
    with _lock:
        tr = _traces.get(message_id)
        if tr is not None:
            tr["status"] = "failed"
            tr["error"] = error


def get_trace(message_id: int) -> dict[str, Any] | None:
    """读取当前生成状态（线程安全浅拷贝）。"""
    with _lock:
        tr = _traces.get(message_id)
        if tr is None:
            return None
        return {
            "status": tr["status"],
            "steps": list(tr["steps"]),
            "output": tr["output"],
            "error": tr["error"],
        }


def clear_trace(message_id: int) -> None:
    """清理（测试/异常兜底用）。"""
    with _lock:
        _traces.pop(message_id, None)
