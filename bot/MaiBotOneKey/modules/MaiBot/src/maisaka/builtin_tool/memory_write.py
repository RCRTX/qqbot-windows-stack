"""save_memory / correct_memory 内置工具（2026-10-21）。

背景：麦麦原来对长期记忆只会「查」——``query_memory`` 检索段落、``query_person_profile``
查人物画像；写全靠后台自动写回（person_fact_writeback / chat_summary_writeback），
改只能去 WebUI 手工点。用户要求「会写、会用、会改」，这里补上缺的两块：

* ``save_memory``    —— 主动把值得留的事实/约定/偏好写进 A_memorix。
  落的是**段落**（paragraph），实体/关系三元组/人物画像快照由 A_memorix 自己抽取，
  所以写一条好段落就等于把四类数据都喂上了。
* ``correct_memory`` —— 被纠正时说错的东西，走官方的
  ``memory_correction_admin``（preview → execute → rollback 三段式）：
  默认只预览，确认后再执行，执行后可回滚。

两个工具都尊重现有开关：``a_memorix.plugin.enabled`` 与
``a_memorix.integration.fuzzy_modify_enabled``，关掉就不出现。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.person_info.person_info import resolve_person_id_for_memory
from src.services.memory_service import memory_service

from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_memory_write")

_ALLOWED_KINDS = {"fact", "preference", "agreement", "event"}
_MIN_CONTENT_CHARS = 4
_MAX_CONTENT_CHARS = 600


def save_tool_enabled() -> bool:
    """写入工具开关：长期记忆总开关开着就允许。"""

    try:
        return bool(global_config.a_memorix.plugin.enabled)
    except Exception:  # noqa: BLE001 - 配置异常时宁可关掉工具，也别让聊天链路崩
        return False


def correct_tool_enabled() -> bool:
    """修正工具开关：记忆总开关 + 自然语言修正开关都要开。"""

    try:
        return bool(global_config.a_memorix.plugin.enabled) and bool(
            global_config.a_memorix.integration.fuzzy_modify_enabled
        )
    except Exception:  # noqa: BLE001
        return False


# ============================ save_memory ============================


def get_save_memory_tool_spec(*, enabled: bool = True) -> ToolSpec:
    """获取 save_memory 工具声明。"""

    return ToolSpec(
        name="save_memory",
        description="把值得长期记住的内容写进记忆库（事实、约定、偏好、重要经过）。",
        parameters_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记住的事，用完整的一句话说清谁、什么事；不要只写关键词。",
                },
                "kind": {
                    "type": "string",
                    "description": "fact事实 / preference偏好 / agreement约定 / event经过。",
                    "enum": sorted(_ALLOWED_KINDS),
                    "default": "fact",
                },
                "person_name": {
                    "type": "string",
                    "description": "相关的人（昵称即可）；不填就按当前说话人。",
                },
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "涉及的实体（人名、作品、物品等），便于建立实体与关系。",
                },
                "relations": {
                    "type": "array",
                    "description": "可选的关系三元组，如 示例角色-是-鲸鱼娘；不填就只靠实体。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string"},
                            "predicate": {"type": "string"},
                            "object": {"type": "string"},
                        },
                        "required": ["subject", "predicate", "object"],
                    },
                },
            },
            "required": ["content"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
        enabled=enabled,
    )


def _resolve_person(chat_stream: Any, person_name: str) -> tuple[str, str]:
    """解析要关联的 person_id（与 query_memory 保持同一套约定）。"""

    platform = str(getattr(chat_stream, "platform", "") or "").strip()
    user_id = str(getattr(chat_stream, "user_id", "") or "").strip()
    name = str(person_name or "").strip()

    try:
        if name:
            pid = resolve_person_id_for_memory(person_name=name, platform=platform, user_id=user_id)
            if pid:
                return pid, name
        # 2026-10-21：群里也要挂到说话人身上 —— 「记住我喜欢…」这种记忆必须知道是谁的，
        # 不能只在私聊解析（query_memory 只在私聊回落到当前用户，写入场景不适合照抄）。
        if platform and user_id:
            pid = resolve_person_id_for_memory(platform=platform, user_id=user_id)
            if pid:
                return pid, name
    except Exception as exc:  # noqa: BLE001 - 解析失败不该阻断写入
        logger.debug("save_memory 解析人物失败: %s", type(exc).__name__)
    return "", name


async def handle_save_memory_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 save_memory：写一条段落进长期记忆。"""

    del context
    content = " ".join(str(invocation.arguments.get("content") or "").split())
    if len(content) < _MIN_CONTENT_CHARS:
        return tool_ctx.build_failure_result(
            invocation.tool_name, "要记住的内容太短了，请用完整的一句话说明。"
        )
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS]

    kind = str(invocation.arguments.get("kind") or "fact").strip().lower()
    if kind not in _ALLOWED_KINDS:
        kind = "fact"

    raw_entities = invocation.arguments.get("entities")
    entities = []
    if isinstance(raw_entities, list):
        for item in raw_entities:
            token = str(item or "").strip()
            if token and token not in entities and len(token) <= 40:
                entities.append(token)
    entities = entities[:12]

    # 关系三元组（图数据不自动抽取，要显式给）：{subject, predicate, object}
    raw_relations = invocation.arguments.get("relations")
    relations: list[dict[str, Any]] = []
    if isinstance(raw_relations, list):
        for row in raw_relations[:8]:
            if not isinstance(row, dict):
                continue
            subject = str(row.get("subject") or "").strip()
            predicate = str(row.get("predicate") or "").strip()
            obj = str(row.get("object") or "").strip()
            if subject and predicate and obj:
                relations.append(
                    {"subject": subject[:40], "predicate": predicate[:40], "object": obj[:40], "confidence": 1.0}
                )

    chat_stream = getattr(tool_ctx.runtime, "chat_stream", None)
    chat_id = str(getattr(chat_stream, "chat_id", "") or "").strip()
    platform = str(getattr(chat_stream, "platform", "") or "").strip()
    user_id = str(getattr(chat_stream, "user_id", "") or "").strip()
    group_id = str(getattr(chat_stream, "group_id", "") or "").strip()
    person_id, person_name = _resolve_person(chat_stream, str(invocation.arguments.get("person_name") or ""))

    now = time.time()
    digest = hashlib.sha256(f"{chat_id}|{content}|{int(now)}".encode("utf-8")).hexdigest()[:12]
    external_id = f"maisaka-save:{chat_id or platform}:{int(now * 1000)}:{digest}"

    participants = [x for x in [person_name] if x]
    tags = ["maisaka", "manual_save", kind]
    if group_id:
        tags.append(f"group:{group_id}")

    result = await memory_service.ingest_text(
        external_id=external_id,
        source_type="maisaka_saved",
        text=content,
        chat_id=chat_id,
        person_ids=[person_id] if person_id else [],
        participants=participants,
        timestamp=now,
        tags=tags,
        metadata={"origin": "maisaka_save_memory", "kind": kind, "saved_by": "maisaka"},
        entities=entities,
        relations=relations,
    )

    if not getattr(result, "success", False):
        detail = str(getattr(result, "detail", "") or "").strip() or "写入未成功"
        return tool_ctx.build_failure_result(invocation.tool_name, f"没记住：{detail}")

    stored = list(getattr(result, "stored_ids", []) or [])
    logger.info("[记忆] 主动写入成功 stored=%s kind=%s", len(stored), kind)
    return tool_ctx.build_success_result(
        invocation.tool_name,
        content=f"记住了：{content}",
        structured_content={
            "success": True,
            "stored_count": len(stored),
            "stored_ids": stored[:5],
            "kind": kind,
            "entities": entities,
            "relation_count": len(relations),
        },
    )


# ============================ correct_memory ============================


def get_correct_memory_tool_spec(*, enabled: bool = True) -> ToolSpec:
    """获取 correct_memory 工具声明。"""

    return ToolSpec(
        name="correct_memory",
        description="纠正记忆库里说错/过时的内容（默认先预览，确认后再执行）。",
        parameters_schema={
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "要改成什么，用自然语言说清（例：示例角色不是猫娘，是鲸鱼娘）。",
                },
                "apply": {
                    "type": "boolean",
                    "description": "true=直接执行；false=只预览改哪些（默认 false）。",
                    "default": False,
                },
                "person_name": {
                    "type": "string",
                    "description": "相关人物；不填就在当前对话里找。",
                },
                "plan_id": {
                    "type": "string",
                    "description": "已有预览计划时填它并配 apply=true，直接执行该计划。",
                },
            },
            "required": ["request"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
        enabled=enabled,
    )


def _summarize_operations(preview: Dict[str, Any]) -> str:
    """把预览里的操作压成一行人话。"""

    ops = preview.get("operations") if isinstance(preview, dict) else None
    if not isinstance(ops, list) or not ops:
        return "没有找到需要改动的条目。"
    parts: list[str] = []
    for op in ops[:5]:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or op.get("type") or "").strip()
        target = str(op.get("target") or op.get("paragraph_hash") or op.get("person_id") or "").strip()
        text = str(op.get("text") or op.get("value_text") or "").strip()
        label = {"mark_superseded": "作废旧记忆", "ingest_text": "写入新说法",
                 "refresh_person_profile": "刷新画像"}.get(action, action or "调整")
        brief = f"{label}"
        if text:
            brief += f"「{text[:40]}」"
        elif target:
            brief += f"({target[:12]})"
        parts.append(brief)
    more = f" 等 {len(ops)} 项" if len(ops) > 5 else ""
    return "；".join(parts) + more


async def handle_correct_memory_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 correct_memory：预览或应用一次记忆修正。"""

    del context
    request_text = " ".join(str(invocation.arguments.get("request") or "").split())
    apply_now = bool(invocation.arguments.get("apply"))
    plan_id = str(invocation.arguments.get("plan_id") or "").strip()

    if not request_text and not plan_id:
        return tool_ctx.build_failure_result(
            invocation.tool_name, "要说明改成什么，或者给出已有的 plan_id。"
        )

    chat_stream = getattr(tool_ctx.runtime, "chat_stream", None)
    chat_id = str(getattr(chat_stream, "chat_id", "") or "").strip()
    person_id, _ = _resolve_person(chat_stream, str(invocation.arguments.get("person_name") or ""))

    # 已有计划：直接执行
    if plan_id:
        result = await memory_service.memory_correction_admin(
            action="execute", plan_id=plan_id, confirmed=True,
            requested_by="maisaka", reason="bot_correct_memory",
        )
        if not result.get("success"):
            return tool_ctx.build_failure_result(
                invocation.tool_name, f"没能执行修正：{result.get('error') or '未知原因'}"
            )
        return tool_ctx.build_success_result(
            invocation.tool_name,
            content="记忆已经改好了。",
            structured_content={"success": True, "plan_id": plan_id, "applied": True},
        )

    # 先出预览
    preview_result = await memory_service.memory_correction_admin(
        action="preview",
        request_text=request_text,
        scope="person_profile" if person_id else "global",
        person_id=person_id,
        chat_id=chat_id,
        requested_by="maisaka",
        reason="bot_correct_memory",
    )
    if not preview_result.get("success"):
        return tool_ctx.build_failure_result(
            invocation.tool_name, f"没能生成修正方案：{preview_result.get('error') or '未知原因'}"
        )

    new_plan_id = str(preview_result.get("plan_id") or "").strip()
    preview = preview_result.get("preview") if isinstance(preview_result.get("preview"), dict) else {}
    summary = _summarize_operations(preview)

    if not apply_now:
        return tool_ctx.build_success_result(
            invocation.tool_name,
            content=f"准备这样改：{summary}",
            structured_content={
                "success": True,
                "applied": False,
                "plan_id": new_plan_id,
                "summary": summary,
                "operations": preview.get("operations") or [],
            },
        )

    exec_result = await memory_service.memory_correction_admin(
        action="execute", plan_id=new_plan_id, confirmed=True,
        requested_by="maisaka", reason="bot_correct_memory",
    )
    if not exec_result.get("success"):
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"方案已生成但执行失败：{exec_result.get('error') or '未知原因'}（plan_id={new_plan_id}）",
        )
    logger.info("[记忆] 修正已应用 plan_id=%s", new_plan_id)
    return tool_ctx.build_success_result(
        invocation.tool_name,
        content=f"记忆已修正：{summary}",
        structured_content={
            "success": True,
            "applied": True,
            "plan_id": new_plan_id,
            "summary": summary,
        },
    )
