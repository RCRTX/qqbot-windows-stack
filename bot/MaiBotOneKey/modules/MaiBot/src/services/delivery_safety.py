"""同一异步发送调用的安全重试标记；无证据时一律视为派发结果不明。"""
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeliverySafetyState:
    not_dispatched: bool = False


# 可变对象使子任务中的驱动也能把“未派发”证据带回本次调用；不同发送互相隔离。
delivery_safety_state: ContextVar[Optional[DeliverySafetyState]] = ContextVar("delivery_safety_state", default=None)
