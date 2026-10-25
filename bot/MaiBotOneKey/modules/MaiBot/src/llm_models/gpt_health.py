"""GPT 连续执行超时后短暂熔断；保留原模型顺序，到期由真实请求探测恢复。"""

from dataclasses import dataclass
from threading import Lock
from typing import Awaitable, Callable, TypeVar

import time

from src.llm_models.exceptions import LLMTaskTimeoutError, ModelAttemptFailed, RespNotOkException

T = TypeVar("T")


class GPTModelCooldown(ModelAttemptFailed):
    """模型已暂缓；当前任务应使用原有备用，不当作又一次实际请求失败。"""


def is_remote_gpt(identifier: str) -> bool:
    name = identifier.lower()
    return name.startswith("gpt-") and not name.startswith("gpt-oss")


def _is_rate_limit(error: BaseException) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, RespNotOkException) and error.status_code == 429:
            return True
        error = error.original_exception if isinstance(error, ModelAttemptFailed) else error.__cause__
    return False


@dataclass
class _HealthState:
    failures: int = 0
    retry_at: float = 0.0
    cooldown: float = 60.0
    probing: bool = False
    epoch: int = 0
    reason: str = "连续超时"


class GPTTimeoutCircuit:
    """跨任务共享同端点、同模型健康状态；排队超时和外部取消不记模型执行失败。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._states: dict[tuple[str, str], _HealthState] = {}
        self._lock = Lock()

    def acquire(self, endpoint: str, identifier: str) -> tuple[tuple[str, str], int] | None:
        if not is_remote_gpt(identifier):
            return None
        key = (endpoint.rstrip("/"), identifier)
        with self._lock:
            state = self._states.setdefault(key, _HealthState())
            now = self._clock()
            if state.retry_at:
                if state.probing or now < state.retry_at:
                    remaining = max(0.0, state.retry_at - now)
                    raise GPTModelCooldown(f"GPT 模型 {identifier} {state.reason}暂缓请求（{remaining:.0f}s；到期单次探测）")
                state.probing = True
                state.epoch += 1
            return key, state.epoch

    def finish(self, ticket: tuple[tuple[str, str], int] | None, outcome: str) -> None:
        if ticket is None:
            return
        key, epoch = ticket
        with self._lock:
            state = self._states[key]
            # 熔断前已在途的迟到结果，不能覆盖新探测的健康状态。
            if state.epoch != epoch:
                return
            if outcome == "success":
                self._states[key] = _HealthState(epoch=epoch + 1)
            elif outcome == "rate_limit":
                if state.probing:
                    state.cooldown = min(300.0, state.cooldown * 2)
                state.reason = "HTTP 429限流"
                state.retry_at = self._clock() + state.cooldown
                state.probing = False
                state.epoch += 1
            elif outcome == "timeout":
                state.failures += 1
                if state.probing or state.failures >= 2:
                    if state.probing:
                        state.cooldown = min(300.0, state.cooldown * 2)
                    state.retry_at = self._clock() + state.cooldown
                    state.probing = False
                    state.epoch += 1
            elif state.probing:
                # 取消或其他错误无法证明恢复；有限期释放探测权，避免永久半开。
                state.retry_at = self._clock() + state.cooldown
                state.probing = False
                state.epoch += 1
            else:
                state.failures = 0


GPT_TIMEOUT_CIRCUIT = GPTTimeoutCircuit()


async def with_gpt_timeout_circuit(endpoint: str, identifier: str, attempt: Callable[[], Awaitable[T]]) -> T:
    ticket = GPT_TIMEOUT_CIRCUIT.acquire(endpoint, identifier)
    try:
        result = await attempt()
    except LLMTaskTimeoutError:
        GPT_TIMEOUT_CIRCUIT.finish(ticket, "timeout")
        raise
    except BaseException as error:
        GPT_TIMEOUT_CIRCUIT.finish(ticket, "rate_limit" if _is_rate_limit(error) else "other")
        raise
    GPT_TIMEOUT_CIRCUIT.finish(ticket, "success")
    return result
