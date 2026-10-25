"""Maisaka 内置工具聚合入口。"""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from src.config.config import global_config
from src.core.tooling import ToolAvailabilityContext, ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.llm_models.payload_content.tool_option import ToolDefinitionInput

from src.maisaka.focus import focus_mode_manager
from .context import BuiltinToolRuntimeContext
from .fetch_history import get_tool_spec as get_fetch_history_tool_spec
from .fetch_history import handle_tool as handle_fetch_history_tool
from .memory_write import correct_tool_enabled
from .memory_write import get_correct_memory_tool_spec
from .memory_write import get_save_memory_tool_spec
from .memory_write import handle_correct_memory_tool
from .memory_write import handle_save_memory_tool
from .memory_write import save_tool_enabled
from .notebook_write import get_tool_spec as get_write_notebook_tool_spec
from .notebook_write import handle_tool as handle_write_notebook_tool
from .notebook_write import tool_enabled as notebook_write_enabled
from .query_memory import get_tool_spec as get_query_memory_tool_spec
from .query_memory import handle_tool as handle_query_memory_tool
from .query_person_profile import get_tool_spec as get_query_person_profile_tool_spec
from .query_person_profile import handle_tool as handle_query_person_profile_tool
from .reply import get_tool_spec as get_reply_tool_spec
from .reply import handle_tool as handle_reply_tool
from .send_emoji import get_tool_spec as get_send_emoji_tool_spec
from .send_emoji import handle_tool as handle_send_emoji_tool
from .send_image import get_tool_spec as get_send_image_tool_spec
from .send_image import handle_tool as handle_send_image_tool
from .switch_chat import get_tool_spec as get_switch_chat_tool_spec
from .switch_chat import handle_tool as handle_switch_chat_tool
from .tool_search import get_tool_spec as get_tool_search_tool_spec
from .tool_search import handle_tool as handle_tool_search_tool
from .view_forward_message import get_tool_spec as get_view_forward_message_tool_spec
from .view_forward_message import handle_tool as handle_view_forward_message_tool
from .wait import get_tool_spec as get_wait_tool_spec
from .wait import handle_tool as handle_wait_tool

BuiltinToolHandler = Callable[[ToolInvocation, Optional[ToolExecutionContext]], Awaitable[ToolExecutionResult]]
BuiltinToolRawHandler = Callable[
    [BuiltinToolRuntimeContext, ToolInvocation, Optional[ToolExecutionContext]],
    Awaitable[ToolExecutionResult],
]
BuiltinToolStage = Literal["action", "both"]
BuiltinToolVisibility = Literal["visible", "deferred", "hidden"]
BuiltinToolChatScope = Literal["all", "group", "private"]


@dataclass(frozen=True)
class BuiltinToolEntry:
    """内置工具目录项，集中声明工具所属阶段与默认可见性。"""

    name: str
    get_spec: Callable[[], ToolSpec]
    handle_tool: BuiltinToolRawHandler
    stage: BuiltinToolStage
    visibility: BuiltinToolVisibility = "visible"
    chat_scope: BuiltinToolChatScope = "all"

    def build_spec(self) -> ToolSpec:
        """生成带统一可见性元数据的工具声明。"""

        tool_spec = deepcopy(self.get_spec())
        tool_spec.metadata["builtin_stage"] = self.stage
        tool_spec.metadata["visibility"] = self.visibility
        return tool_spec


def _get_query_memory_tool_spec() -> ToolSpec:
    """根据配置生成 query_memory 工具声明。"""

    return get_query_memory_tool_spec(enabled=bool(global_config.a_memorix.integration.enable_memory_query_tool))


def _get_query_person_profile_tool_spec() -> ToolSpec:
    """根据配置生成 query_person_profile 工具声明。"""

    return get_query_person_profile_tool_spec(
        enabled=bool(global_config.a_memorix.integration.enable_person_profile_query_tool)
    )


def _get_save_memory_tool_spec() -> ToolSpec:
    """根据配置生成 save_memory 工具声明（2026-10-21：让麦麦会写记忆）。"""

    return get_save_memory_tool_spec(enabled=save_tool_enabled())


def _get_correct_memory_tool_spec() -> ToolSpec:
    """根据配置生成 correct_memory 工具声明（2026-10-21：让麦麦会改记忆）。"""

    return get_correct_memory_tool_spec(enabled=correct_tool_enabled())


def _get_write_notebook_tool_spec() -> ToolSpec:
    """根据配置生成 write_notebook 工具声明（2026-10-22：本子记自己觉得重要的事）。"""

    return get_write_notebook_tool_spec(enabled=notebook_write_enabled())


BUILTIN_TOOL_ENTRIES: List[BuiltinToolEntry] = [
    BuiltinToolEntry("wait", get_wait_tool_spec, handle_wait_tool, stage="both"),
    BuiltinToolEntry("reply", get_reply_tool_spec, handle_reply_tool, stage="action"),
    BuiltinToolEntry(
        "view_forward_message",
        get_view_forward_message_tool_spec,
        handle_view_forward_message_tool,
        stage="action",
        visibility="deferred",
    ),
    BuiltinToolEntry("query_memory", _get_query_memory_tool_spec, handle_query_memory_tool, stage="action"),
    BuiltinToolEntry(
        "query_person_profile",
        _get_query_person_profile_tool_spec,
        handle_query_person_profile_tool,
        stage="action",
    ),
    # 2026-10-21 用户要求「记忆库要让他会写会用会改」：原来只有查，写靠后台自动写回、
    # 改只能去 WebUI。这里补上主动写（段落 + 实体，其余三类由系统抽取）与自然语言修正
    # （preview → execute，可回滚）。
    BuiltinToolEntry(
        "save_memory",
        _get_save_memory_tool_spec,
        handle_save_memory_tool,
        stage="action",
    ),
    BuiltinToolEntry(
        "correct_memory",
        _get_correct_memory_tool_spec,
        handle_correct_memory_tool,
        stage="action",
    ),
    # 2026-10-22 用户要求「本子应该记他认为重要的东西」：以前本子只由日记后台自动生成，
    # 麦麦自己写不了。给一个当场能写的工具（同一天追加到同一页）。
    BuiltinToolEntry(
        "write_notebook",
        _get_write_notebook_tool_spec,
        handle_write_notebook_tool,
        stage="action",
    ),
    BuiltinToolEntry("send_emoji", get_send_emoji_tool_spec, handle_send_emoji_tool, stage="action"),
    BuiltinToolEntry("send_image", get_send_image_tool_spec, handle_send_image_tool, stage="action"),
    BuiltinToolEntry("tool_search", get_tool_search_tool_spec, handle_tool_search_tool, stage="action"),
    BuiltinToolEntry(
        "fetch_history",
        get_fetch_history_tool_spec,
        handle_fetch_history_tool,
        stage="action",
    ),
    BuiltinToolEntry("switch_chat", get_switch_chat_tool_spec, handle_switch_chat_tool, stage="action"),
]


def _get_builtin_tool_entries(
    *,
    stage: Optional[BuiltinToolStage] = None,
    visibility: Optional[BuiltinToolVisibility] = None,
    context: Optional[ToolAvailabilityContext] = None,
) -> List[BuiltinToolEntry]:
    """按阶段与可见性筛选内置工具目录项。"""

    entries = BUILTIN_TOOL_ENTRIES
    entries = [entry for entry in entries if _is_builtin_tool_enabled_by_config(entry)]
    if stage is not None:
        entries = [entry for entry in entries if entry.stage in {stage, "both"}]
    if visibility is not None:
        entries = [entry for entry in entries if entry.visibility == visibility]
    if context is not None:
        entries = [entry for entry in entries if _is_builtin_tool_available(entry, context)]
    return entries


def _is_builtin_tool_enabled_by_config(entry: BuiltinToolEntry) -> bool:
    """根据全局配置判断内置工具是否应暴露。"""

    if entry.name in {"send_emoji", "send_image"} and bool(global_config.experimental.enable_rich_reply):
        return False
    if entry.name in {"fetch_history", "switch_chat"}:
        return bool(global_config.experimental.focus_mode)
    return True


def _is_builtin_tool_available(entry: BuiltinToolEntry, context: ToolAvailabilityContext) -> bool:
    """判断内置工具是否适用于当前聊天。"""

    if entry.name in {"fetch_history", "switch_chat"}:
        if context.session_id:
            return focus_mode_manager.is_enabled_for_session(
                context.session_id,
                is_group_chat=context.is_group_chat,
            )
        if not focus_mode_manager.is_enabled_for_chat(is_group_chat=context.is_group_chat):
            return False
    if entry.chat_scope == "all":
        return True
    if entry.chat_scope == "group":
        return context.is_group_chat is True
    if entry.chat_scope == "private":
        return context.is_group_chat is False
    return True


def get_builtin_tool_visibility(tool_spec: ToolSpec) -> BuiltinToolVisibility:
    """读取工具声明里的可见性。"""

    raw_visibility = str(tool_spec.metadata.get("visibility") or "").strip()
    if raw_visibility == "deferred":
        return "deferred"
    if raw_visibility == "hidden":
        return "hidden"
    return "visible"


def is_builtin_tool_in_action_stage(tool_spec: ToolSpec) -> bool:
    """判断内置工具是否属于 Action Loop 阶段。"""

    return str(tool_spec.metadata.get("builtin_stage") or "").strip() in {"action", "both"}


def get_all_builtin_tool_specs(context: Optional[ToolAvailabilityContext] = None) -> List[ToolSpec]:
    """获取全部内置工具声明。"""

    return [entry.build_spec() for entry in _get_builtin_tool_entries(context=context)]


def get_builtin_tools(context: Optional[ToolAvailabilityContext] = None) -> List[ToolDefinitionInput]:
    """获取默认暴露给模型层的内置工具定义。"""

    tool_specs = [
        entry.build_spec()
        for entry in _get_builtin_tool_entries(stage="action", visibility="visible", context=context)
    ]
    return [tool_spec.to_llm_definition() for tool_spec in tool_specs if tool_spec.enabled]


def build_builtin_tool_handlers(tool_ctx: BuiltinToolRuntimeContext) -> Dict[str, BuiltinToolHandler]:
    """构建内置工具处理器映射。"""

    return {
        entry.name: lambda invocation, context=None, entry=entry: entry.handle_tool(tool_ctx, invocation, context)
        for entry in BUILTIN_TOOL_ENTRIES
    }
