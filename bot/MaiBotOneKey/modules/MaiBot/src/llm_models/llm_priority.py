"""LLM 请求的「优先级」标记（2026-10-13）。

背景：并发闸门（openai_client.llm_concurrency_gate）把同一站点的请求串行化了，
但串行不等于公平 —— 后台学习一次 4 个 LLM 批次，前台回复只能排在它后面干等。
所以给请求分级：前台（默认 0）优先，后台学习（-1）最后。

用法：给学习类任务的函数套装饰器 ``@with_llm_low_priority``，
它内部发起的所有 LLM 调用（含它 create_task 出去的子任务，因为
asyncio 创建任务时会复制当前 context）都会自动带上低优先级。

不传标记 = 默认前台优先级，所以现有的调用点一行都不用改。
"""

from __future__ import annotations

import contextvars
import functools
from contextlib import contextmanager
from typing import Any, Callable, Iterator

# 数值越大越优先。前台 0；后台学习 -1。
LLM_PRIORITY_FOREGROUND = 0
LLM_PRIORITY_BACKGROUND = -1

_LLM_PRIORITY: contextvars.ContextVar[int] = contextvars.ContextVar(
    "maibot_llm_priority", default=LLM_PRIORITY_FOREGROUND
)


def current_llm_priority() -> int:
    """当前协程的 LLM 请求优先级。"""
    try:
        return int(_LLM_PRIORITY.get())
    except Exception:  # noqa: BLE001
        return LLM_PRIORITY_FOREGROUND


@contextmanager
def llm_low_priority() -> Iterator[None]:
    """把当前 context 内的 LLM 请求标记为后台（低优先级）。"""
    token = _LLM_PRIORITY.set(LLM_PRIORITY_BACKGROUND)
    try:
        yield
    finally:
        _LLM_PRIORITY.reset(token)


def with_llm_low_priority(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：整个异步函数体内发起的 LLM 请求都算后台优先级。"""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with llm_low_priority():
            return await func(*args, **kwargs)

    return wrapper
