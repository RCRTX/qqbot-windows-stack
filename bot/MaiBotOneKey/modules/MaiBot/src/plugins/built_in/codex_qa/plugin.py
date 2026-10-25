"""明确问答命令；使用独立 qa 模型任务，不进入日常聊天规划。"""
import asyncio
from collections import OrderedDict
import time
from typing import Any, Dict, Optional

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase
from src.common.explicit_commands import QA_COMMAND_PATTERN


class PluginSection(PluginConfigBase):
    enabled: bool = Field(default=True, description="启用明确问答指令")
    config_version: str = Field(default="1.0.0", description="配置版本")


class QAConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)


class CodexQAPlugin(MaiBotPlugin):
    config_model = QAConfig

    async def on_load(self):
        self._active = set()
        self._last_success = OrderedDict()
        self._seen = OrderedDict()
        self.ctx.logger.info("[问答] 已加载，触发：问答 问题内容；模型任务：qa")

    async def on_unload(self):
        self._active.clear()
        self._last_success.clear()
        self._seen.clear()

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str):
        # 模型任务由 Host 每次请求读取；插件本身只有启用开关。
        return None

    @Command("codex_qa", description="问答 问题内容：调用独立问答模型",
             pattern=QA_COMMAND_PATTERN,
             timeout_ms=110000)
    async def answer(self, stream_id: str = "", user_id: str = "",
                     matched_groups: Optional[Dict[str, Any]] = None,
                     message: Optional[Dict[str, Any]] = None, **kwargs):
        if not stream_id:
            return False, "缺少聊天流", True
        question = str((matched_groups or {}).get("question") or "").strip()
        mid = str((message or {}).get("message_id") or "")
        dedupe_key = (stream_id, mid)
        if mid:
            if dedupe_key in self._seen:
                return True, None, True
            self._seen[dedupe_key] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
        if not question:
            await self.ctx.send.text("用法：问答 问题内容，例如：问答 什么是光合作用？", stream_id)
            return True, None, True
        if len(question) > 3000:
            await self.ctx.send.text("问题太长，请缩短到 3000 字以内。", stream_id)
            return True, None, True
        who = (stream_id, str(user_id))
        if who in self._active:
            await self.ctx.send.text("上个问题还在处理，请稍等。", stream_id)
            return True, None, True
        if time.monotonic() - self._last_success.get(who, float('-inf')) < 15:
            await self.ctx.send.text("请间隔 15 秒再提问。", stream_id)
            return True, None, True
        if len(self._active) >= 2:
            await self.ctx.send.text("问答正在忙，请稍后重试。", stream_id)
            return True, None, True
        self._active.add(who)
        try:
            prompt = ("请作为QQ群的问答助手回答下面的问题。默认用中文，先给结论，简洁清楚。"
                      "不输出思考过程。没有联网工具时不要声称进行了实时查询；"
                      "不确定的信息请说明，不要编造。\n\n问题：\n" + question)
            result = await asyncio.wait_for(self.ctx.llm.generate(
                prompt, task_name="qa", timeout_ms=95000), timeout=100)
            text = str(result.get("response") or "").strip()
            if not result.get("success") or not text:
                raise RuntimeError("问答模型未返回有效回答")
            text = text[:5000]
            for offset in range(0, len(text), 1000):
                sent = await self.ctx.send.text(text[offset:offset + 1000], stream_id)
                if sent is False:
                    raise RuntimeError("问答回答发送失败")
            self._last_success[who] = time.monotonic()
            self._last_success.move_to_end(who)
            while len(self._last_success) > 1000:
                self._last_success.popitem(last=False)
            self.ctx.logger.info("[问答] 回答完成")
            return True, None, True
        except Exception as exc:
            self.ctx.logger.warning(f"[问答] 失败：{type(exc).__name__}")
            await self.ctx.send.text("问答服务暂时不可用，请稍后重试。", stream_id)
            return False, None, True
        finally:
            self._active.discard(who)


def create_plugin():
    return CodexQAPlugin()
