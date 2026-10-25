"""短生命周期的必答批次；只重试尚未产生可见回复的真实入站消息。"""
from collections import OrderedDict
from typing import Any

import time


class RequiredReplyTracker:
    def __init__(self, *, max_retries: int = 2, ttl: float = 120.0) -> None:
        self.max_retries = max_retries
        self.ttl = ttl
        self.pending: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.active_ids: tuple[str, ...] = ()
        self.retries = 0
        self.retry_reason = ""

    def track(self, message_id: str, message: Any) -> None:
        if not message_id or message_id in self.seen:
            return
        self.seen[message_id] = None
        while len(self.seen) > 512:
            self.seen.popitem(last=False)
        self.pending[message_id] = (message, time.monotonic() + self.ttl)
        while len(self.pending) > 64:
            self.pending.popitem(last=False)

    def begin_turn(self) -> None:
        self.retries = 0
        self.retry_reason = ""

    def begin_round(self) -> None:
        now = time.monotonic()
        for message_id, (_, deadline) in list(self.pending.items()):
            if deadline <= now:
                self.pending.pop(message_id, None)
        self.active_ids = tuple(self.pending)
        self.retry_reason = ""

    def outcome(self, target_id: str, outcome: str) -> None:
        if target_id not in self.active_ids:
            return
        if outcome == "retryable":
            self.retry_reason = "尚未生成或派发可见回复"
        else:
            # 同人的连续消息可合并；不同群友的 @ 不因回复了别人而变成已答。
            target = self.pending.get(target_id)
            sender = self._sender_key(target[0]) if target else None
            completed_ids = {
                message_id for message_id in self.active_ids
                if message_id == target_id or (
                    sender is not None and message_id in self.pending
                    and self._sender_key(self.pending[message_id][0]) == sender
                )
            }
            for message_id in completed_ids:
                self.pending.pop(message_id, None)
            self.active_ids = tuple(message_id for message_id in self.active_ids if message_id not in completed_ids)
            self.retry_reason = "同批次还有其他人的未答消息" if self.active_ids else ""

    @staticmethod
    def _sender_key(message: Any) -> Any:
        info = getattr(message, "message_info", None)
        user = getattr(info, "user_info", None)
        user_id = str(getattr(user, "user_id", "") or "")
        return (str(getattr(message, "platform", "")), user_id) if user_id else None

    def request_retry(self, *, no_tool: bool = False) -> tuple[str, ...]:
        now = time.monotonic()
        for message_id, (_, deadline) in list(self.pending.items()):
            if deadline <= now:
                self.pending.pop(message_id, None)
        remaining = tuple(message_id for message_id in self.active_ids if message_id in self.pending)
        if not remaining or self.retries >= self.max_retries:
            return ()
        if not no_tool and not self.retry_reason:
            return ()
        self.retries += 1
        self.retry_reason = ""
        return remaining

    def discard_active(self) -> None:
        for message_id in self.active_ids:
            self.pending.pop(message_id, None)
        self.active_ids = ()
        self.retry_reason = ""
