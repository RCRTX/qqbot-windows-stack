"""好感度 / 表现分插件（0.11 自建插件移植到 1.2.5）。

## 结构

- `logic.py` —— 从旧插件**原样搬过来**的 2257 行纯逻辑（常量、`classify`、`favor_delta`、
  `ScoreStore`、`FavorStore`、`ReflectionStore`、各种 handler 辅助函数）。
  只改了 3 处 0.11 专有的东西（import 块、两处 `emoji_api`）。
- `plugin.py`（本文件）—— 新版 SDK 的接线：把 1.2.5 的命名 Hook / 消息格式
  适配成旧代码认的形状，然后调用 `logic` 里的东西。

## 挂载点（2026-09-24 实测三个 hook 都命中过）

| 旧（0.11 事件总线） | 新（1.2.5 命名 Hook） |
|---|---|
| `EventType.AFTER_SEND` | `send_service.after_send` |
| `EventType.ON_MESSAGE` | `chat.receive.after_process`（可 abort） |
| `EventType.POST_LLM` | `maisaka.replyer.before_request` 的 `extra_prompt` |

⚠️ 别用 `@EventHandler(event_type=...)`：SDK 里还留着，但那条旧总线已经被摘掉
（`events_manager.py` 都没了），装上去能加载、永远收不到消息。
`plugins/hello_world_plugin` 就是过期示范。

## 数据文件路径不能改

面板直接读 `data/behavior_score.json` 与 `data/favorability.json`，
所以 `logic.ROOT` / `SCORE_FILE` / `FAV_FILE` 保持旧算法（本文件与旧文件同层级，
往上四层就是麦麦根目录）。**不要**改用 `ctx.data_dir`。
"""

from typing import Any, ClassVar, Dict, List, Optional, Tuple

import asyncio
import importlib.util
import os
import re
import time

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin, PluginConfigBase
from src.common.explicit_commands import QA_COMMAND_RE, FAVOR_RANK_RE, FAVOR_RANK_PATTERN


def _load_logic() -> Any:
    """按文件路径加载同目录的 `logic.py`。

    不能用 `import logic`：宿主是用 importlib 按文件加载 `plugin.py` 的，
    插件目录不在 `sys.path` 上，绝对导入会报 `No module named 'logic'`（踩过）。
    也不能用 `from . import logic`：那不是包导入。

    Returns:
        Any: 已执行的 `logic` 模块对象。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logic.py")
    spec = importlib.util.spec_from_file_location("behavior_score_logic", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"加载 logic.py 失败: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logic = _load_logic()

# 管理命令（**带参数**才算）的识别正则，必须和下面两个 `@Command` 的 pattern 一致。
#
# ⚠️ 为什么要在闸门里自己认一遍：宿主的命令匹配发生在 `chat.receive.after_process`
# **之后**（`bot.py:786` 调 hook，799 才进命令链），而闸门的"问好感度就直答"会 abort
# 掉整条消息 —— 结果「好感度 @某人 50」这种管理命令会被答成"你在我这儿 N"，
# 命令根本不执行（2026-09-24 实测踩到：管理员发「好感度 随便」，回的是好感度数字）。
# 旧版不会这样：那时闸门挂在 POST_LLM 上，命令链先拦下消息，闸门压根不跑。
# 注意判据要**带参数**（`\s+\S`）：光说「好感度」是"查询"，要留给闸门直答。
#
# ⚠️ 2026-10-11 修：「@」前缀不能只认 `@<昵称:QQ号>`。1.2.5 把 @ 渲染成纯文本
# `@昵称`（见 `logic._parse_target` 的注释），旧 pattern 要求必须有尖括号，
# 结果 `@示例助手 好感度 50` **整条命令匹配不上**，用户报「艾特人调好感度失效」。
# 现在 @ 前缀放宽成"任意一段非空白字符"，让 `@昵称` / `@<昵称:QQ号>` 都能过。
_ADMIN_AT_PREFIX = r"(?:@[^\s]+[ \t]*)?"
_FEED_PATTERN = r"^\s*(?:@[^\r\n]+?\s+)?(?:鱼[，,:：\s]*)?(?P<food>投食|吐司|[tT][sS])\s*$"
_PLAYFUL_RE = re.compile(r"^\s*(?:@[^\r\n]+?\s+)?(?:鱼[，,:：\s]*)?(?:投食|吐司|投尸|投史|偷师|骰十|偷食|投石|陨石|今日陨石|头饰|透视|天使|[tT][sS]|[yY][sS])\s*$")

_ADMIN_CMD_PATTERN = re.compile(rf"^{_ADMIN_AT_PREFIX}/?(?:好感度|表现分)\s+\S")


def _is_admin_command(raw_text: str) -> bool:
    """判断这条消息是不是**带参数的管理命令**。

    必须拿**原文**判：`logic.clean()` 会把所有空白都去掉（它顺手防"不 可以"这种拆字），
    清洗后再也看不出「好感度␣参数」这个形状（2026-09-24 踩过：清洗后判据永远不命中）。
    引用前缀单独剥掉，因为宿主是按 `processed_plain_text` 匹配命令的。

    Args:
        raw_text: 原始消息文本。

    Returns:
        bool: 是带参数的管理命令返回 True。
    """
    text = logic._REPLY_PREFIX.sub("", str(raw_text or "")).strip()
    return bool(_ADMIN_CMD_PATTERN.match(text))


class PluginSectionConfig(PluginConfigBase):
    """插件的 `[plugin]` 基础节。

    ⚠️ 必须有这一节：宿主是拿**配置模型**和 config.toml 合并后再校验的，
    模型里没有 `plugin` 字段的话，合并结果就没有 `[plugin]`，于是报
    「插件配置文件缺少 [plugin] 配置节」——配置文件里写了也没用。
    """

    __ui_label__: ClassVar[str] = "基础设置"
    config_version: str = Field(default="1.3.0", description="配置版本号")
    enabled: bool = Field(default=True, description="是否启用好感度/表现分插件")


class BehaviorScoreSection(PluginConfigBase):
    """`[behavior_score]`：整体表现分（奖励/惩罚）。"""

    __ui_label__: ClassVar[str] = "表现分"
    window_seconds: float = Field(default=180, description="机器人发言后多久内的回应才算数（秒）")
    inject_prompt: bool = Field(default=True, description="是否把分数和最近扣分原因写进回复提示词")
    admin_qq: List[str] = Field(default_factory=list, description="谁能用管理命令")
    penalty_stop: int = Field(default=-20, description="被明确叫停扣多少")
    penalty_deny: int = Field(default=-15, description="被否定且冲着它来 / 消息很短，扣多少")
    penalty_deny_soft: int = Field(default=-10, description="一般否定（长句、随口不满）扣多少")


class FavorabilitySection(PluginConfigBase):
    """`[favorability]`：AI 对每个人的好感度。"""

    __ui_label__: ClassVar[str] = "好感度"
    initial: int = Field(default=100, description="第一次见到某人时给多少分")
    max_value: int = Field(default=0, description="上限；0 = 无上限")
    low_threshold: int = Field(default=30, description="低于它就不再理这个人")
    penalty_hostile: int = Field(default=-10, description="被骂/人身攻击扣多少（好感度唯一会掉的情形）")
    penalty_stop: int = Field(default=-20, description="（已停用）叫停只走表现分")
    penalty_deny: int = Field(default=-10, description="（已停用）否定只走表现分")


class ReflectionSection(PluginConfigBase):
    """`[reflection]`：长期错题本。"""

    __ui_label__: ClassVar[str] = "反思库"
    enabled: bool = Field(default=True, description="是否把反思库写进回复提示词")
    limit: int = Field(default=8, description="每轮最多注入几条教训")


class BehaviorScoreConfig(PluginConfigBase):
    """插件配置模型（键名与旧插件的 config.toml 保持一致）。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig, description="插件基础配置")
    behavior_score: BehaviorScoreSection = Field(
        default_factory=BehaviorScoreSection, description="表现分配置")
    favorability: FavorabilitySection = Field(
        default_factory=FavorabilitySection, description="好感度配置")
    reflection: ReflectionSection = Field(default_factory=ReflectionSection, description="反思库配置")
    debug_log: bool = Field(default=True, description="把 hook 触发的关键信息写进日志")


class MessageAdapter:
    """把 1.2.5 的入站消息 payload 适配成旧代码认的属性名。

    `logic.py` 里那 2257 行是按 0.11 的 `MaiMessages` 写的（`message.stream_id` /
    `plain_text` / `message_base_info` / `message_segments` …）。与其改几十处调用点，
    不如在这里包一层 —— 旧逻辑一行不用动。

    实测 payload 形状（2026-09-24 抓的）：
        {"message_id","timestamp","platform","message_info":{"user_info":{...},
         "group_info":{...},"additional_config":{}},"raw_message":[{"type","data"}...],
         "is_mentioned","is_at","is_emoji","is_picture","is_command","is_notify",
         "session_id","processed_plain_text"}
    注意 `raw_message` 在这里是**段数组**，而旧代码里它是字符串，所以这里分开存：
    `message_segments` 给数组，`raw_message` 给拼好的文本。
    """

    def __init__(self, payload: Dict[str, Any]) -> None:
        """初始化适配器。

        Args:
            payload: hook 传下来的消息字典。
        """
        self._payload = payload or {}
        info = self._payload.get("message_info") or {}
        user = info.get("user_info") or {}
        group = info.get("group_info") or {}

        self.message_id: str = str(self._payload.get("message_id") or "")
        self.stream_id: str = str(self._payload.get("session_id") or "")
        self.platform: str = str(self._payload.get("platform") or "")
        self.processed_plain_text: str = str(self._payload.get("processed_plain_text") or "")
        self.plain_text: str = self.processed_plain_text

        self.is_mentioned: bool = bool(self._payload.get("is_mentioned"))
        self.is_at: bool = bool(self._payload.get("is_at"))

        # 旧代码统一从 `message_base_info` 里取 user_id / group_id / nickname
        self.message_base_info: Dict[str, Any] = {**user, **group}
        self.message_info: Dict[str, Any] = info

        # 旧代码用 `additional_data["reply_message_id"]` 判断"这条是不是引用回复"。
        # 1.2.5 的 hook payload 里对应字段是 `reply_to`（数据库列也叫 reply_to）。
        self.additional_data: Dict[str, Any] = {
            "reply_message_id": self._payload.get("reply_to") or "",
            "is_mentioned": self.is_mentioned,
            "is_at": self.is_at,
        }

        segments = self._payload.get("raw_message")
        self.message_segments: Any = (
            [_Seg(s) for s in segments] if isinstance(segments, list) else [])
        self.raw_message: str = self._segments_to_text(self.message_segments)

    @staticmethod
    def _segments_to_text(segments: Any) -> str:
        """把段数组拼成纯文本（旧代码拿 `raw_message` 当纯文本兜底用）。

        Args:
            segments: 段数组。

        Returns:
            str: 拼接后的文本。
        """
        if not isinstance(segments, list):
            return ""
        parts: List[str] = []
        for seg in segments:
            if getattr(seg, "type", "") == "text" and seg.data:
                parts.append(str(seg.data))
        return "".join(parts)


class _Seg:
    """把 1.2.5 的**段字典**包成旧代码认的对象（0.11 里是 `maim_message.Seg`）。

    旧逻辑一律用 `getattr(seg, "type")` / `getattr(seg, "data")` 取段
    （见 `logic._reply_image_b64s`、`logic._seg_mentions`），直接把 dict 给它会
    **静默取不到** —— 表现为「回复表情包说删掉」认不出是哪张图、md5 兜底也失效
    （2026-09-24 踩过，探针里 `recalled=[] deleted=[]`，日志却一声不吭）。
    """

    __slots__ = ("type", "data")

    def __init__(self, seg: Any) -> None:
        """初始化。

        Args:
            seg: 一个消息段（1.2.5 的字典，或已经是旧格式对象）。
        """
        if isinstance(seg, dict):
            self.type = str(seg.get("type") or "")
            data = seg.get("data")
            # 嵌套的 seglist 里装的还是段字典，递归包一层
            self.data = [_Seg(x) for x in data] if isinstance(data, list) else data
        else:
            self.type = str(getattr(seg, "type", "") or "")
            self.data = getattr(seg, "data", None)


class _EmojiProvider:
    """把 SDK 的 emoji 能力包成 `logic` 期望的形状。

    SDK 返回的是 `{"success":…, "emojis":[{"base64":…, "description":…, "emotion":…}]}`
    （见 `plugin_runtime/capabilities/data.py` 的 `_cap_emoji_get_random`），
    而旧代码按 `(base64, …)` 这种下标取（`send_lib_stickers` 里 `item[0]`），
    所以这里转成元组列表；`delete_emoji` 一路透传。
    """

    def __init__(self, ctx: Any) -> None:
        """初始化。

        Args:
            ctx: 插件运行时上下文。
        """
        self._ctx = ctx

    async def get_random(self, count: int) -> List[Tuple[str, str]]:
        """随机取几张表情包。

        Args:
            count: 要几张。

        Returns:
            List[Tuple[str, str]]: `(base64, 描述)` 列表；失败返回空。
        """
        result = await self._ctx.emoji.get_random(int(count))
        # ⚠️ SDK 层返回的是**列表**，不是宿主那层的 `{"success":…, "emojis":[…]}`：
        # 实测拿回来是 `[{"base64":…, "description":…, "emotion":…}]`
        # （`plugin_runtime/capabilities/data.py` 里返回的是 dict，SDK 又拆了一层 ——
        #  跟 llm.generate 那次一样，文档和实际不一致，别照文档写）。
        if isinstance(result, list):
            raw_items = result
        elif isinstance(result, dict):
            raw_items = result.get("emojis") or []
        else:
            logic.logger.warning(f"[表情包] emoji.get_random 返回了意外类型: {type(result).__name__}")
            return []

        out: List[Tuple[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            b64 = str(item.get("base64") or "")
            if b64:
                out.append((b64, str(item.get("description") or "")))
        if raw_items and not out:
            # 拿回来的条目里没有 base64 → 多半是图片路径解析/读文件失败（宿主侧
            # `_serialize_emoji_payload` 会对发不出 base64 的条目直接丢弃）
            logic.logger.warning(
                f"[表情包] emoji.get_random 给了 {len(raw_items)} 条但都没有 base64，"
                f"首条字段={sorted(raw_items[0].keys()) if isinstance(raw_items[0], dict) else type(raw_items[0])}")
        elif not raw_items:
            logic.logger.warning("[表情包] emoji.get_random 返回 0 条（宿主表情包库取不到图）")
        return out

    async def delete_emoji(self, emoji_hash: str) -> Any:
        """从库里删一张表情包。

        Args:
            emoji_hash: 表情包 hash。

        Returns:
            Any: SDK 的原始返回。
        """
        return await self._ctx.emoji.delete_emoji(str(emoji_hash))


class BehaviorScorePlugin(MaiBotPlugin):
    """好感度 / 表现分插件。"""

    config_model = BehaviorScoreConfig

    # 每个聊天流最近一条入站消息（`before_request` 只给 session_id 和 reply_message_id，
    # 拿不到正文，所以在这里记下来给它用）。键是 stream_id。
    _latest_inbound: ClassVar[Dict[str, MessageAdapter]] = {}
    _inbound_by_id: ClassVar[Dict[str, Any]] = {}

    # 当前正在处理的那条消息的消息段。
    #
    # ⚠️ 为什么要有它：命令处理（`handle_favor_admin`）拿到的只有 `stream_id` /
    # `matched_groups`，**没有消息段**，而目标的真 QQ 号只存在于段结构的
    # `target_user_id` 里（文本里只有 `@昵称`）。所以闸门（hook 收消息时）顺手把段存下来，
    # 命令处理时再取。2026-10-11 修「艾特人调好感度失效」时加的。
    _current_segments: ClassVar[Any] = None

    def __init__(self):
        super().__init__()
        self._feeding_active = set()

    async def on_load(self) -> None:
        """插件加载时调用。"""
        # 让 logic 里的日志进麦麦的日志流（它默认用标准库 logger，单独 import 也不会炸）
        logic.logger = self.ctx.logger
        # 新版能力要 ctx，logic 是纯函数模块拿不到，用注入的方式给它
        logic.llm_provider = self
        logic.emoji_provider = _EmojiProvider(self.ctx)
        self._latest_inbound = {}
        self._inbound_by_id = {}
        self._apply_favor_config()
        BehaviorScorePlugin._current_segments = None
        self._log("插件已加载（好感度/表现分）")

    async def on_unload(self) -> None:
        """插件卸载时调用。"""
        self._log("插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置热更新：基类要求必须实现，否则插件注册直接失败。

        Args:
            scope: 变更范围，`self` / `bot` / `model`。
            config_data: 该范围的最新配置数据。
            version: 配置版本号。
        """
        self._apply_favor_config()
        self._log(f"配置更新 scope={scope} version={version}")

    def _apply_favor_config(self) -> None:
        """配置加载/热更新后同步到账本规则。"""
        logic.FAVOR.initial = max(0, int(self.get_config("favorability.initial", 100)))
        logic.FAVOR.cap = max(0, int(self.get_config("favorability.max_value", 0)))
        logic.LOW_FAV = max(0, int(self.get_config("favorability.low_threshold", 30)))
        logic.FAV_DOWN_INSULT = min(0, int(self.get_config("favorability.penalty_hostile", -10)))

    def _remember_message(self, adapted: MessageAdapter) -> None:
        self._latest_inbound[adapted.stream_id] = adapted
        cache = self._inbound_by_id.setdefault(adapted.stream_id, {})
        if adapted.message_id:
            cache[adapted.message_id] = adapted
            while len(cache) > 128:
                cache.pop(next(iter(cache)))

    def _interaction_target(self, adapted: MessageAdapter, st: Dict[str, Any],
                            mentioned: bool, quoted: bool, fresh: bool,
                            now: float) -> Tuple[bool, bool]:
        """可靠引用/@优先；自然接话只认机器人后的首个短窗口回应。"""
        if not adapted.message_base_info.get("group_id"):
            return True, quoted
        if mentioned:
            return True, quoted
        bot_qq, bot_nick = logic._bot_ids()
        if logic._at_others(adapted, bot_qq, bot_nick):
            return False, False
        if quoted:
            rid = str(adapted.additional_data.get("reply_message_id") or "")
            target = self._inbound_by_id.get(adapted.stream_id, {}).get(rid)
            target_uid = str((target.message_base_info if target else {}).get("user_id") or "")
            # 未知引用不借用 fresh 推断收件人。
            return bool(target_uid and target_uid == bot_qq), bool(target_uid and target_uid == bot_qq)
        last_bot_ts = float(st.get("last_bot_ts") or 0)
        first_reply = float(st.get("other_spoke_ts") or 0) <= last_bot_ts
        target_uid = str(st.get("last_bot_target_uid") or "")
        uid = str(adapted.message_base_info.get("user_id") or "")
        return bool(fresh and first_reply and target_uid == uid and now - last_bot_ts <= 30), False

    # ------------------------------------------------------- 旧代码要用的接口

    def get_config(self, key: str, default: Any = None) -> Any:
        """按旧插件的点号写法读配置（`logic.py` 里的辅助函数都走这个）。

        Args:
            key: 形如 `behavior_score.window_seconds` 的点号键。
            default: 取不到时的默认值。

        Returns:
            Any: 配置值或默认值。
        """
        node: Any = self.config
        for part in str(key).split("."):
            if isinstance(node, dict):
                if part not in node:
                    return default
                node = node[part]
            elif hasattr(node, part):
                node = getattr(node, part)
            else:
                return default
        return default if node is None else node

    async def send_text(self, sid: str, text: str) -> Any:
        """发一条文本（旧代码里叫 `handler.send_text`）。

        Args:
            sid: 目标聊天流 ID。
            text: 文本内容。

        Returns:
            Any: 发送结果。
        """
        return await self.ctx.send.text(str(text), str(sid))

    async def send_image(self, sid: str, b64: str) -> Any:
        """发一张图片（base64）。

        Args:
            sid: 目标聊天流 ID。
            b64: 图片 base64。

        Returns:
            Any: 发送结果。
        """
        return await self.ctx.send.image(str(b64), str(sid))

    async def llm_generate(self, prompt: str, task_name: str = "utils") -> str:
        """调一次模型生成文本（`logic.llm_provider` 要的接口，用于被扣分后的复盘）。

        Args:
            prompt: 提示词。
            task_name: 模型任务名（新版任务表：planner / utils / learner / memory…）。

        Returns:
            str: 模型生成的文本；取不到时返回空串。
        """
        result = await self.ctx.llm.generate(prompt, task_name=task_name)
        if isinstance(result, dict):
            # ⚠️ SDK 把结果归一化成 `{"success","response","reasoning","model"}`
            # （见 maibot_sdk/capabilities/llm.py 的 `_normalize_llm_result`）——
            # 正文在 **`response`** 里，不叫 content/text（这里取错过一次，复盘恒为空）。
            return str(result.get("response") or "")
        return str(result or "")

    def _log(self, text: str) -> None:
        """按配置决定是否打日志。"""
        try:
            if self.get_config("debug_log", True):
                self.ctx.logger.info(f"[behavior_score] {text}")
        except Exception:
            pass

    # ------------------------------------------------------------------ hooks

    @HookHandler("chat.receive.after_process", name="behavior_score_on_message")
    async def on_message(self, message: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """入站消息（等价于旧的 ON_MESSAGE + POST_LLM 里的闸门部分）。

        旧版是**两个**处理器：`ReactionHandler`（记账）→ `ReplyGuardHandler`（闸门 + 注入）。
        新版注入挪到了 `before_request`，闸门必须留在这一层 —— 因为
        `before_request` **不允许 abort**（实测 `allow_abort=False`），
        而"低好感就不理他""问好感度直接答完就别说第二遍"都要能中止这次回复。

        Args:
            message: 序列化后的 SessionMessage。
            **kwargs: 宿主附加参数。

        Returns:
            Optional[Dict[str, Any]]: 需要中止后续回复链路时返回 `{"action": "abort"}`。
        """
        adapted = MessageAdapter(message or {})
        if not adapted.stream_id:
            return None
        # 彩蛋命令自行处理，避免额外自然记分或被低分闸门吞掉。
        if _PLAYFUL_RE.fullmatch(adapted.plain_text.strip()):
            return None
        # 明确问答交给独立命令处理，问题正文不能触发生图/好感度等闸门。
        if QA_COMMAND_RE.fullmatch(adapted.plain_text.strip()):
            return None
        if FAVOR_RANK_RE.fullmatch(adapted.plain_text.strip()):
            self._remember_message(adapted)
            return None
        # 🔴 平台层重复投递硬去重（2026-10-11）：MaiSaka 会对同一批积压消息连跑多个
        # planner 轮次，本钩子对**同一条消息**会进来 2 次。不清掉的话，每次都会把
        # `handle_admin_draw`（主人点名生图）/ `handle_sticker`（发库表情包）完整跑一遍
        # —— 用户看到的就是「点一次生图出了 4 张」「一次发了 10 张表情包」。
        # 用 QQ 的 message_id 判重：同一条消息只处理一次。
        if logic.is_duplicate_message(adapted.message_id):
            self._log(f"[去重] 这条消息（id={adapted.message_id}）已经处理过，跳过重复投递")
            return None
        self._remember_message(adapted)
        # 🔴 把消息段存下来给命令处理用（2026-10-11）：命令处理只给 stream_id，
        # 拿不到段结构，而「@某人 好感度 50」的**目标 QQ 号**只存在于段的
        # `target_user_id` 里（文本里只有 `@昵称`）。不存的话目标解析永远回落到发送者。
        BehaviorScorePlugin._current_segments = adapted.message_segments
        await self._account(adapted)
        return await self._guard(adapted)

    @Command("feeding_reward", description="投食或吐司：每天共一次，随机增加3至10好感并发图片", pattern=_FEED_PATTERN, timeout_ms=15000)
    async def feeding_reward(self, stream_id: str = "", platform: str = "", user_id: str = "",
                             message: Optional[Dict[str, Any]] = None, matched_groups: Optional[Dict[str, Any]] = None, **kwargs):
        adapted = MessageAdapter(message or {})
        uid = str(adapted.message_base_info.get("user_id") or "")
        if platform != "qq" or not stream_id or adapted.stream_id != stream_id or adapted.platform != platform or uid != str(user_id) or not adapted.message_id:
            return False, "无法核对真实投食消息", True
        bot_qq, bot_nick = logic._bot_ids()
        def at_ids(value):
            if isinstance(value, list):
                return [target for item in value for target in at_ids(item)]
            if isinstance(value, dict):
                data = value.get("data")
                if value.get("type") == "at" and isinstance(data, dict):
                    target = str(data.get("target_user_id") or data.get("qq") or "")
                    return [target] if target else []
                return [target for item in value.values() if isinstance(item, (list, dict)) for target in at_ids(item)]
            return []
        targets = at_ids((message or {}).get("raw_message"))
        aimed_elsewhere = any(target != bot_qq for target in targets) if targets else logic._at_others(adapted, bot_qq, bot_nick)
        if uid == bot_qq or aimed_elsewhere:
            return False, None, False
        match = re.fullmatch(_FEED_PATTERN, adapted.plain_text.strip())
        if not match:
            return False, None, False
        food = match["food"].lower()
        name = str(adapted.message_base_info.get("user_cardname") or adapted.message_base_info.get("user_nickname") or "")
        gid = str(adapted.message_base_info.get("group_id") or "")
        key = (platform, gid, adapted.message_id, uid)
        if key in self._feeding_active:
            return True, None, True
        self._feeding_active.add(key)
        try:
            receipt = await asyncio.to_thread(logic.FAVOR.feed_reward, uid, name, platform=platform, group_id=gid, message_id=adapted.message_id, food=food)
            if receipt.get("daily_limit"):
                sent = await self.ctx.send.text("今天已经投过食啦，明天再来喂我吧。", stream_id)
                return bool(sent), None, True
            if receipt.get("delivered"):
                return True, None, True
            card = await asyncio.to_thread(logic.render_feeding_card, food, receipt["delta"], receipt["score"], receipt.get("item", ""), receipt.get("category", ""))
            sent = await self.ctx.send.image(card, stream_id, return_details=True)
            ok = sent is True or (isinstance(sent, dict) and sent.get("sent") is True)
            if ok:
                await asyncio.to_thread(logic.FAVOR.mark_feed_delivered, receipt["receipt_id"])
            return ok, None if ok else "投食已记账，但图片发送失败，可查询好感度确认", True
        except Exception as exc:
            self.ctx.logger.error(f"[投食] 处理失败: {type(exc).__name__}")
            return False, "投食处理失败，未确认成功，请稍后查询好感度", True
        finally:
            self._feeding_active.discard(key)

    @Command("favor_ranking", description="本群好感度排行榜（前十）",
             pattern=FAVOR_RANK_PATTERN, timeout_ms=15000)
    async def favor_ranking(self, stream_id: str = "", group_id: str = "",
                           message: Optional[Dict[str, Any]] = None, **kwargs):
        if not stream_id:
            return False, "缺少聊天流", True
        adapted = MessageAdapter(message or {})
        if not adapted.stream_id:
            adapted = self._latest_inbound.get(stream_id)
        if adapted and logic._at_others(adapted, *logic._bot_ids()):
            return True, None, True
        gid = str(group_id or (adapted.message_base_info if adapted else {}).get("group_id") or "")
        if not gid:
            await self.ctx.send.text("请在群里发送“好感度排行榜”。", stream_id)
            return True, None, True
        mid = str(getattr(adapted, "message_id", "") or "")
        if mid and logic.is_duplicate_message("favor-ranking:" + stream_id + ":" + mid):
            return True, None, True
        try:
            members = await asyncio.to_thread(logic.read_group_members, gid)
            logic.FAVOR._maybe_reload()
            with logic.FAVOR._lock:
                users = {uid: dict(rec) for uid, rec in logic.FAVOR.data.get("users", {}).items()
                         if isinstance(rec, dict)}
            rows = logic.favor_leaderboard(users, members)
            text = "好感度排行榜\n" + ("\n".join(
                f"第{row['rank']}名  {row['name']} · {row['score']:g}" for row in rows
            ) if rows else "本群还没有好感度记录。") + "\n本群成员 · 全局好感度 · 前十"
        except Exception as exc:
            self.ctx.logger.warning(f"[好感度排行榜] 成员读取失败：{type(exc).__name__}")
            text = "暂时取不到本群成员，排行榜稍后再试。"
        await self.ctx.send.text(text, stream_id)
        return True, None, True

    async def _account(self, adapted: MessageAdapter) -> None:
        """记账：①表现分 ②好感度 ③被扣分就反思一句（旧 `ReactionHandler.execute`）。

        Args:
            adapted: 适配后的入站消息。
        """
        try:
            sid = adapted.stream_id
            text = adapted.plain_text
            info = adapted.message_base_info
            uid = str(info.get("user_id", "") or "")
            # 2026-10-10：群里昵称可能带控制字符/二进制垃圾（日志里见过形如
            # `\b%\u0100\u0100\u0007...某科学的超威蓝猫` 的昵称），进日志和提示词前先洗净
            uname = logic.safe_name(info.get("user_cardname") or info.get("user_nickname") or "")
            bot_qq, bot_nick = logic._bot_ids()
            if bot_qq and uid == bot_qq:
                return  # 机器人自己发的不算

            window = float(self.get_config("behavior_score.window_seconds", logic.DEFAULT_WINDOW)
                           or logic.DEFAULT_WINDOW)
            st = logic.SCORE.stream(sid)
            now = time.time()
            last_ts = float(st.get("last_bot_ts") or 0)
            fresh = bool(st.get("last_bot_text")) and (now - last_ts) <= window
            mentioned, quoted = logic._mentioned_bot(adapted, bot_qq, bot_nick)

            # ---- 回复机器人发的那张表情包 + 说「删掉」→ 撤回 + 出库 ----
            # 放得比身份/梗图更靠前：这种事只有"引用回复"一种形态，认不出会自动放行。
            if await logic.handle_sticker_delete(self, adapted, uid, uname, text):
                self._mark_cmd(uid, text)
                return

            # ---- 身份 / 称呼 / 菜单命令：**必须挂在收消息这一层**（2026-09-20 踩坑）----
            # 原来挂在 POST_LLM，而那个钩子只在"机器人打算回这条消息"时才触发：
            # 群里那句「@示例助手 A」规划器没打算回 → 钩子根本没跑 → 回答被整个吞掉。
            if await logic.handle_identity_and_callname(self, adapted, uid, uname, text, mentioned):
                self._mark_cmd(uid, text)
                return

            # ---- 主人专属：点名要一张纪念图（2026-10-11 新增）----
            # 放在梗图**前面**：它只认「生图 / 出图」这几个词，和梗图的「画一张」不撞，
            # 但先判主人这条，免得以后有人在 admin_draw.keywords 里加了重合的词时抢错。
            if await logic.handle_admin_draw(self, adapted, uid, uname, text, mentioned):
                self._mark_cmd(uid, text)
                return

            # ---- 梗图（Q版表情包）：同样挂这一层，理由同上 ----
            if await logic.handle_sticker(self, adapted, uid, uname, text, mentioned):
                self._mark_cmd(uid, text)
                return

            # ---- 「主人在干什么」：读本机正在运行的应用名回给他 ----
            if await logic.handle_pc_status(self, adapted, uid, uname, text, mentioned):
                self._mark_cmd(uid, text)
                return

            # ---- 管理命令自己不算交流（不然发个"好感度 重置"还能加分）----
            if logic._looks_like_command(text):
                return

            # ---- ② 好感度：只对"冲着机器人来的"消息动手 ----
            # 「纯查询」不算交流，别给分：实测有人打「查询好感度」白拿 +1（08-19 19:06）。
            ask_txt = logic.clean(text)
            # 2026-10-21 用户要求「全字符命中」：整句等于问法才算在问，
            # 句子里夹带「好感度」三字的正常聊天不再被当成问句。
            pure_ask = logic.is_full_ask(ask_txt, logic.FAV_ASK) \
                or logic.is_full_ask(ask_txt, logic.REL_ASK)
            if (fresh or mentioned or quoted or not info.get("group_id")) and not pure_ask:
                aimed, reliable_quote = self._interaction_target(adapted, st, mentioned, quoted, fresh, now)
                new_fav, d_fav, why = logic.FAVOR.record_interaction(
                    uid, uname, text, aimed=aimed, mentioned=mentioned, quoted=reliable_quote,
                    message_id=adapted.message_id, group_id=str(info.get("group_id") or ""))
                if d_fav:
                    self._log(f"好感度 {uname or uid} {d_fav:+d} → {new_fav}（{why}）")
                    # ---- ④ 里程碑 CG：跨过新档位就后台出一张图，@ 他发到群里 ----
                    # 放 create_task 里跑：出图要几秒到几十秒，绝不能卡住消息处理
                    try:
                        lvl = logic._cg_level_for(new_fav)
                        if lvl > int(logic.FAVOR.rec(uid).get("cg_level") or 0):
                            gid = str(info.get("group_id") or "")
                            asyncio.create_task(self._send_cg(uid, uname, sid, gid, new_fav, lvl))
                    except Exception as exc:  # noqa: BLE001
                        self.ctx.logger.warning(f"[CG] 里程碑判定失败: {type(exc).__name__}: {exc}")

            # ---- ① 表现分：只在"紧接着机器人的话"时才结算 ----
            if not fresh:
                return
            if float(st.get("last_scored_ts") or 0) >= last_ts:
                st["other_spoke_ts"] = now      # 已结算过，只标一下"别人插话了"
                logic.SCORE.save()
                return

            else_spoke = float(st.get("other_spoke_ts") or 0) > last_ts
            delta, reason = logic.classify(text, mentioned_bot=mentioned, quoted_bot=quoted,
                                           gap_seconds=now - last_ts, someone_else_spoke=else_spoke,
                                           aimed_at_bot=(mentioned or quoted or not else_spoke),
                                           window=window)
            if delta:
                ev = logic.SCORE.add(delta, reason, sid, text, st.get("last_bot_text", ""))
                st["last_scored_ts"] = now
                logic.SCORE.save()
                self._log(f"表现分 {delta:+d} → {ev.get('score')}（{reason}）")
                # ---- ③ 被扣分 → 让模型自己复盘一句错在哪 ----
                if delta < 0:
                    # 带上下文再复盘：光给"它说X、对方回Y"，模型分不清是梗太冷、
                    # 插错话还是答非所问（2026-09-18 补）
                    history = logic._recent_context(sid, limit=8) if sid else ""
                    lesson = await logic.make_lesson(ev.get("bot_said", ""), ev.get("they_said", ""),
                                                     reason, history=history)
                    logic.SCORE.set_lesson(ev, lesson)
                    # 同时记进**长期**反思库：events 有 MAX_EVENTS 上限，附在事件上的
                    # 教训会随流水账被滚掉；反思库按 hits 累积，同一个毛病反复犯会越来越显眼。
                    if lesson:
                        logic.REFLECT.add(
                            lesson,
                            kind=str(reason or "").split("（")[0] or "被否定",
                            scene=f"它说「{ev.get('bot_said', '')}」，有人说「{ev.get('they_said', '')}」",
                            source="auto",
                        )
            else:
                st["other_spoke_ts"] = now
                logic.SCORE.save()
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[表现分] 判定失败: {type(exc).__name__}: {exc}")

    async def _guard(self, adapted: MessageAdapter) -> Optional[Dict[str, Any]]:
        """回复闸门（旧 `ReplyGuardHandler.execute` 的前半段，搬到这层是为了能 abort）。

        做三件事，顺序和旧版一致：
          1. 问好感度 / 问关系 → **直接答真实数字**，然后中止正常回复（免得一次说两遍）；
          2. 好感度低于阈值 → @ 它才回一句"你是坏人"（有冷却），没 @ 就干脆不理；
          3. 身份/称呼命令已经答过 → 中止，别让规划器再回一遍。

        Args:
            adapted: 适配后的入站消息。

        Returns:
            Optional[Dict[str, Any]]: 需要中止时返回 `{"action": "abort"}`。
        """
        try:
            sid = adapted.stream_id
            info = adapted.message_base_info
            uid = str(info.get("user_id", "") or "")
            # 2026-10-10：群里昵称可能带控制字符/二进制垃圾（日志里见过形如
            # `\b%\u0100\u0100\u0007...某科学的超威蓝猫` 的昵称），进日志和提示词前先洗净
            uname = logic.safe_name(info.get("user_cardname") or info.get("user_nickname") or "")
            bot_qq, bot_nick = logic._bot_ids()
            if bot_qq and uid == bot_qq:
                return None
            # 带参数的管理命令让路给命令链（理由见文件顶部 _ADMIN_CMD_PATTERN 的注释）
            if _is_admin_command(adapted.plain_text):
                return None
            text = logic.clean(adapted.plain_text or "")
            mentioned, quoted = logic._mentioned_bot(adapted, bot_qq, bot_nick)

            asking = logic.is_full_ask(text, logic.FAV_ASK)
            # 光说"好感度"三个字也算在问 —— 2026-09-19 实测：用户接着它的话只打了
            # 「好感度」两个字，没有 @、没有引用，于是不给直接答，模型就开始**自己编数字**
            # （108 / 128 / 201 一连串，用户当场问"我是什么很贱的人吗"）。
            bare_ask = asking and len(text) <= 12
            # @ 的是**别人** → 这条根本不是问它。2026-09-22 实测：有人在群里发
            # 「@某人 好感度」，插件把它当成"问自己好感度"，20 秒里连答两遍。
            if bare_ask and logic._at_others(adapted, bot_qq, bot_nick):
                bare_ask = False
                self._log(f"[好感度] {uname or uid} 这条 @ 的是别人，不抢答")
            low = logic.FAVOR.get(uid) < logic.LOW_FAV

            # 同一条消息只直接答一次：麦麦一条消息可能跑两个回复周期，签名跟消息内容绑定。
            sig = logic._cmd_sig(uid, text)
            rec = logic.FAVOR.rec(uid)
            answered = (str(rec.get("fav_ans_sig") or "") == sig
                        and (time.time() - float(rec.get("fav_ans_ts") or 0)) < logic.CMD_DEDUPE_WINDOW)
            if (asking or logic.is_full_ask(text, logic.REL_ASK)) and answered:
                # 2026-10-11：和下面的 `cmd_sig` 同一套改法 —— 计数拦（最多 MAX_HITS 次）。
                # 只拦一次挡不住 MaiSaka 对同一批消息连跑的几个轮次，会重复报同一串数字。
                hits = logic._int_of(rec.get("fav_ans_hits"), 0)
                if hits < logic.CMD_DEDUPE_MAX_HITS:
                    rec["fav_ans_hits"] = hits + 1
                    logic.FAVOR.save()
                    self._log(f"[好感度] {uname or uid} 这条好感度/关系问题已经答过了，"
                              f"取消重复回复（第 {hits + 1} 次）")
                    return {"action": "abort"}

            # ---- 问好感度：**直接答**，不走模型 ----
            # 实测（2026-09-18 01:53）：只把数字塞进提示词的话，规划器一旦把回复目标选成
            # 别的消息，模型就会去答那个、把问句晾着。触发条件用 `mentioned or quoted`：
            # **引用它**问也一样算数。
            if asking and (mentioned or quoted or bare_ask):
                line = f"你在我这儿 {logic.FAVOR.get(uid)}"
                try:
                    await self.send_text(sid, line)
                    rec["fav_ans_sig"] = sig
                    rec["fav_ans_ts"] = time.time()
                    rec["fav_ans_hits"] = 0
                    logic.FAVOR.save()
                    self._log(f"[好感度] 直接回答 {uname or uid}: {line}")
                    return {"action": "abort"}
                except Exception as exc:  # noqa: BLE001
                    self.ctx.logger.warning(
                        f"[好感度] 直接回答失败，退回注入方式: {type(exc).__name__}: {exc}")
            elif asking:
                self.ctx.logger.warning(
                    f"[好感度] 没直接回答：@={mentioned} 引用={quoted} "
                    f"text={adapted.plain_text[:80]!r}")

            # ---- 问"我们是什么关系"：同样按表直接答 ----
            # 模板故意用「咱俩啊…{label}」，不写「算{label}吧」——
            # 「算」和标签里的「算是认识」「不熟」会撞成"算算是认识吧"。
            if logic.is_full_ask(text, logic.REL_ASK) \
                    and (mentioned or quoted
                         or (len(text) <= 12 and not logic._at_others(adapted, bot_qq, bot_nick))):
                line = f"咱俩啊…{logic.FAVOR.relation_label(uid)}"
                try:
                    await self.send_text(sid, line)
                    rec["fav_ans_sig"] = sig
                    rec["fav_ans_ts"] = time.time()
                    rec["fav_ans_hits"] = 0
                    logic.FAVOR.save()
                    self._log(f"[好感度] 直接回答关系 {uname or uid}: {line}")
                    return {"action": "abort"}
                except Exception as exc:  # noqa: BLE001
                    self.ctx.logger.warning(f"[好感度] 回答关系失败: {type(exc).__name__}: {exc}")

            # ---- 好感度太低：翻脸 / 不理 ----
            if low and not asking:
                # 翻脸档：**插件直接接管这次回复**，不再拿提示词去劝模型。
                # 2026-09-20 实测：0 好感的人 @"坏鱼"，模型回了句「行行行，坏鱼就坏鱼吧」，
                # 提示词完全没压住。
                if mentioned:
                    now = time.time()
                    left = logic.SHUN_COOLDOWN - (now - float(logic.FAVOR.rec(uid).get("last_shun_ts") or 0))
                    if left <= 0:
                        line = logic.SHUN_LINES[int(now // logic.SHUN_COOLDOWN) % len(logic.SHUN_LINES)]
                        try:
                            await self.send_text(sid, line)
                            logic.FAVOR.mark_shunned(uid)
                            self._log(f"[好感度] {uname or uid} 好感度 {logic.FAVOR.get(uid)}"
                                      f" < {logic.LOW_FAV} → 翻脸回一句：{line}")
                        except Exception as exc:  # noqa: BLE001
                            self.ctx.logger.warning(f"[好感度] 翻脸回话失败: {type(exc).__name__}: {exc}")
                    else:
                        self._log(f"[好感度] {uname or uid} 好感度 {logic.FAVOR.get(uid)} < {logic.LOW_FAV}"
                                  f"，还在翻脸冷却里（剩 {max(0, left):.0f} 秒）→ 直接不理")
                    # 无论发没发，都取消正常回复：不然模型又要自由发挥一遍
                    return {"action": "abort"}
                self._log(f"[好感度] {uname or uid} 好感度 {logic.FAVOR.get(uid)}，"
                          f"低于 {logic.LOW_FAV}，这次不回复")
                return {"action": "abort"}

            # ---- 身份/称呼命令已经在记账那层处理过了，这里只负责别让规划器再回一遍 ----
            # 判据是**消息签名**而不是"多久之内"：回复链路可能隔一分钟才跑到这里（实测 53 秒），
            # 时间窗口会漏（重复输出）。
            if str(rec.get("cmd_sig") or "") == logic._cmd_sig(uid, text) \
                    and (time.time() - float(rec.get("cmd_ts") or 0)) < logic.CMD_DEDUPE_WINDOW:
                # 2026-10-11 改成**计数拦**（最多 CMD_DEDUPE_MAX_HITS 次）：
                # · 老逻辑"命中就拦、窗口 600 秒" → 用户 10 分钟内再发一次同样命令被静默吞掉；
                # · 中间那版"命中即消费（只拦 1 次）" → 但 MaiSaka 会对**同一批积压消息**
                #   连跑好几个轮次（日志里循环编号 8、9、10…），拦一次不够，第三个轮次
                #   就会把同一句命令再答一遍 —— 这正是"重复回复"的一个来源。
                # 计数拦两头都要：挡住重复输出，又不吞掉用户后来真的再发一次。
                hits = logic._int_of(rec.get("cmd_hits"), 0)
                if hits < logic.CMD_DEDUPE_MAX_HITS:
                    rec["cmd_hits"] = hits + 1
                    logic.FAVOR.save()
                    self._log(f"[身份] {uname or uid} 的这条命令已经答过了，"
                              f"取消这次正常回复（第 {hits + 1} 次）")
                    return {"action": "abort"}

            # ---- ⑤ 主动弹身份菜单（2026-10-11 用户要求）----
            # 用户原话：「没选择身份的人在和 ai 聊天的时候应该适时蹦出来选择身份的选项并 @ 他」。
            # 关键在"适时"：不能每句都弹（刷屏）。判定全部塞进 `logic.should_nudge_identity`
            # （纯逻辑、可测），这里只负责真发出去 + 记账。
            if await self._nudge_identity(adapted, uid, uname, text, mentioned, rec):
                return {"action": "abort"}
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[闸门] 判定失败: {type(exc).__name__}: {exc}")
        return None

    async def _nudge_identity(self, adapted: MessageAdapter, uid: str, uname: str,
                              text: str, mentioned: bool, rec: Dict[str, Any]) -> bool:
        """没选身份的人聊到一定份上 → @ 他弹一次身份菜单。

        返回 True = 已经发了菜单（调用方中止正常回复，免得模型又自由发挥一遍）。

        Args:
            adapted: 适配后的入站消息。
            uid: 用户 ID。
            uname: 用户昵称。
            text: 已 clean 的文本。
            mentioned: 是否 @ 了机器人。
            rec: 该用户的好感度记录。

        Returns:
            bool: 发了菜单就 True。
        """
        try:
            ok, why = logic.should_nudge_identity(uid, text, mentioned, rec)
            if not ok:
                return False
            sid = adapted.stream_id
            gid = str((adapted.message_base_info or {}).get("group_id") or "")
            id_cfg = logic.PROMPTS.get("identity", default={}) or {}
            try:
                need = int(id_cfg.get("min_favor") or 500)
            except (TypeError, ValueError):
                need = 500
            try:
                cost = int(id_cfg.get("penalty_no_choice") or 150)
            except (TypeError, ValueError):
                cost = 150
            cur = logic.FAVOR.get(uid)
            # 复用「问身份」那条文案（`identity.menu`），保证菜单内容永远和配置同步
            line = logic._fmt(str(id_cfg.get("menu") or ""), who=uname or uid, cur=cur,
                              min_favor=need, after=max(0, cur - cost), cost=cost,
                              options=logic._options_lines())
            # 弹了就记 pending：这样用户直接回「A」/「鱼娘」不用再 @ 一次（和主动问同一套）
            rec["id_pending_ts"] = time.time()
            rec["id_nudge_ts"] = time.time()
            rec["id_nudge_count"] = logic._int_of(rec.get("id_nudge_count"), 0) + 1
            logic.FAVOR.save()
            if gid:
                segs = [logic.at_seg(uid), logic.text_seg("\n" + line)]
                sent, info = await logic.napcat_group_msg(gid, segs)
                if not sent:
                    self.ctx.logger.warning(f"[身份] 主动菜单直发失败，退回麦麦出站: {str(info)[:80]}")
                    if sid:
                        await self.send_text(sid, line)
            elif sid:
                await self.send_text(sid, line)
            self._log(f"[身份] {uname or uid} 还没选身份（{why}）→ 主动 @他 弹了菜单"
                      f"（第 {rec['id_nudge_count']} 次）")
            return True
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning(f"[身份] 主动菜单失败: {type(exc).__name__}: {exc}")
            return False

    def _mark_cmd(self, uid: str, text: str) -> None:
        """记下"刚处理过这个人的一条命令"，用于 `before_request` 的不重复响应判断。

        Args:
            uid: 用户 ID。
            text: 消息文本。
        """
        rec = logic.FAVOR.rec(uid)
        rec["cmd_ts"] = time.time()
        rec["cmd_sig"] = logic._cmd_sig(uid, text)
        # 记新的一条命令时把拦截计数清零 —— 不然用户后来真的再发一次同样的命令，
        # 会被上一次残留的计数挡住（那正是要修的"静默吞掉"）。
        rec["cmd_hits"] = 0
        logic.FAVOR.save()

    async def _send_cg(self, uid: str, uname: str, sid: str, gid: str,
                       score: int, level: int, force: bool = False) -> None:
        """里程碑 CG：出图 → 真 @ 目标人物 → 发到群里（2026-09-20 新增）

        失败不推进 `cg_level`（下次还能再试），但有冷却 + 每日上限兜住费用。
        从旧 `ReactionHandler._send_cg` 原样搬过来。

        Args:
            uid: 用户 ID。
            uname: 用户昵称。
            sid: 聊天流 ID。
            gid: 群 ID。
            score: 当前好感度。
            level: 达到的 CG 档位。
            force: True = 主人点名要的（`cg.admin_draw`），**跳过门槛/冷却/每日上限**，
                   并且**不推进真实档位记录**（`cg_level`）、**不占当日额度** ——
                   这张图是"主人想看"，不能把正常的里程碑进度顶掉。
        """
        key = None                                   # (uid, level) 防重入键，见末尾 finally
        old_level = None                             # 占位记账前的档位，出图失败要回滚
        try:
            cfg = logic.PROMPTS.get("cg", default={}) or {}
            rec = logic.FAVOR.rec(uid)
            now = time.time()
            # 🔴 身份闸门（2026-10-11 用户要求）：「没有选择身份的不给他生成图片」。
            # 为什么必须挡在出图**之前**：没选身份时 `_cg_prompt` 会退回通用兜底
            # （`identity_hint[""]` = "casual clothes, long silver hair"），出的是银发路人，
            # 既不是鱼娘也不是任何人 —— 白烧钱还难看（用户看到的"低质量图片"就是这个）。
            identity = str(rec.get("identity") or "")
            if not identity:
                self._log(f"[CG] {uname or uid} 还没选身份，不出图（先让他 @它 选一个）")
                if force:
                    # 主人点名这种情况要**告诉他为什么没出**，不然他以为坏了
                    try:
                        id_cfg = logic.PROMPTS.get("identity", default={}) or {}
                        tip = str(id_cfg.get("need_identity_draw")
                                  or "你先选个身份我才能画呀 —— @我说「身份」挑一个～")
                        await self.send_text(sid, tip)
                    except Exception as exc:  # noqa: BLE001
                        self.ctx.logger.warning(f"[CG] 提示选身份失败: {type(exc).__name__}: {exc}")
                return
            if not force:
                try:
                    cd = float(cfg.get("cooldown_seconds") or 60)
                except (TypeError, ValueError):
                    cd = 60.0
                if now - float(rec.get("cg_last_ts") or 0) < cd:
                    self._log(f"[CG] {uname or uid} 还在出图冷却里，先跳过第 {level} 张")
                    return
                try:
                    limit = int(cfg.get("daily_limit") or 10)
                except (TypeError, ValueError):
                    limit = 10
                if logic._cg_daily_count(uid) >= limit:
                    self._log(f"[CG] {uname or uid} 今天已经出了 {limit} 张，不再出")
                    return

            # 2026-10-13：同一张还没画完就不要再触发第二次。
            # 豆包出一张要 60~70s，比 CG 冷却（cooldown_seconds=60）还长 ——
            # 上一张没画完冷却就过了，后面的消息会把同一档再触发一次，群里就连出两张。
            key = (str(uid), int(level))
            if key in logic.CG_INFLIGHT:
                self._log(f"[CG] 第 {level} 张还在画（{uname or uid}），跳过这次重复触发")
                if force:
                    try:
                        await self.send_text(sid, f"第 {level} 张还在画呢，画完我叫你～")
                    except Exception as exc:        # noqa: BLE001
                        self.ctx.logger.warning(f"[CG] 提示失败: {type(exc).__name__}: {exc}")
                return
            logic.CG_INFLIGHT.add(key)

            prompt, stage = logic._cg_prompt(level, identity)
            name = str(stage.get("name") or f"第 {level} 张")
            self._log(f"[CG] 给 {uname or uid} 出第 {level} 张（{name}）"
                      f"{'[主人点名] ' if force else ''}provider={cfg.get('provider')}"
                      f" 好感度={score}")
            if not force:
                # 占位记账：出图要 60s+，先把档位写进去，这段时间里就不会被再次触发。
                # 真出失败了会在下面回滚成原档位（不让一次失败白吃掉一次里程碑）。
                old_level = rec.get("cg_level")
                rec["cg_last_ts"] = now
                rec["cg_level"] = level
                logic.FAVOR.save()

            # 出图 + **自检重试**：纯文字提示画"鲸鱼长在身上"只有一半概率，
            # 出完让 VLM 看一眼，不合格就重画（最多 check_attempts 张）
            attempts = max(1, logic._int_of(cfg.get("check_attempts"), 1))
            over_cg = (logic._identity_options().get(identity) or {}).get("cg")
            over_cg = over_cg if isinstance(over_cg, dict) else {}
            # 自检的**问题**按身份写（鲸鱼娘问尾鳍归属+腿有没有被盖住，猫娘可以问猫耳），
            # 生成参数（attempts / 模型 / 判定词）放全局 `cg`。
            # check_prompt 允许两种写法：一句字符串，或者 [[问题, 通过词], ...] —— 后者要求**全部通过**。
            raw_checks = over_cg.get("check_prompt") or cfg.get("check_prompt") or ""
            dflt_pass = [str(w) for w in (cfg.get("check_pass") or ["有", "是"]) if w]
            checks: List[Tuple[str, List[str]]] = []
            if isinstance(raw_checks, str) and raw_checks.strip():
                checks.append((raw_checks.strip(), dflt_pass))
            elif isinstance(raw_checks, list):
                for item in raw_checks:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        words = item[1] if isinstance(item[1], (list, tuple)) else [item[1]]
                        checks.append((str(item[0]), [str(x) for x in words]))
                    elif isinstance(item, str) and item.strip():
                        checks.append((item.strip(), dflt_pass))
            ok, info, dest = False, "", ""
            # 2026-10-13 用户定稿「全用豆包」：所有档位/所有身份的 CG 都先走豆包
            # （有参考图垫图、无参考图纯文生），失败才回落硅基流动兜底。
            dest = os.path.join(logic.CG_IMG_DIR, f"{uid}_{level}_{int(now)}_d.jpg")
            try:
                ok, info = await asyncio.to_thread(
                    logic._doubao_cg, level, identity, prompt, dest)
                if ok:
                    self.ctx.logger.info(f"[CG] lv{level}（{identity}）走豆包成功")
            except Exception as e:                          # noqa: BLE001
                self.ctx.logger.warning(f"[CG] 豆包通路异常，回落硅基流动: {e}")
                ok = False
            if not ok:
                if os.path.exists(dest):                    # 豆包可能写了坏图，清掉
                    try:
                        os.remove(dest)
                    except OSError:
                        pass
            for attempt in range(attempts if not ok else 0):
                dest = os.path.join(logic.CG_IMG_DIR, f"{uid}_{level}_{int(now)}_{attempt}.jpg")
                ok, info = await asyncio.to_thread(logic._fetch_cg_image, prompt, dest,
                                                   logic._cg_size(identity), logic._cg_negative(identity))
                if not ok:
                    self.ctx.logger.warning(f"[CG] 第 {attempt + 1} 次出图失败: {info}")
                    continue
                good = True
                for q_i, pass_i in checks:
                    if not await asyncio.to_thread(logic._vlm_yes_no, dest, q_i, pass_i):
                        good = False
                        break
                if good:
                    break
                self._log(f"[CG] 第 {attempt + 1} 张自检没过，重画")
            if not ok:
                # 出图失败 → 把刚才占位的档位回滚，别让这次失败吃掉一次里程碑
                if not force:
                    rec["cg_level"] = old_level
                    logic.FAVOR.save()
                self.ctx.logger.warning(f"[CG] 出图失败，下次再试: {info}")
                return
            self._log(f"[CG] 出图成功（{info}）→ {os.path.basename(dest)}")
            # 只有正常跨档才记账：主人点名要的那张是"额外"的，不占当日额度、
            # 也不推进里程碑档位（免得把正常跨档那张顶掉，也免得 cg_level 被指定的低档位写回去）
            if not force:
                logic._cg_bump_count(uid)
                rec["cg_level"] = level
            logic.FAVOR.save()

            ad_cfg = logic.PROMPTS.get("cg", "admin_draw", default={}) or {}
            tpl = str((ad_cfg.get("caption") if force else "")
                      or cfg.get("caption") or "{who} 好感度到 {score} 啦")
            caption = logic._fmt(tpl, who=uname or uid, score=score, level=level,
                                 name=name, identity=identity)
            await logic.send_image_msg(self, sid, gid, uid, uname, dest, caption,
                                       cfg.get("mention_target", True) is not False)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[CG] 出图/发送异常: {type(exc).__name__}: {exc}")
        finally:
            # 成功失败都要解锁，不然这一档会被永久卡住（以后再也出不了这张）
            if key is not None:
                logic.CG_INFLIGHT.discard(key)

    @HookHandler("send_service.after_send", name="behavior_score_after_send")
    async def on_after_send(
        self,
        message: Optional[Dict[str, Any]] = None,
        sent: bool = False,
        **kwargs: Any,
    ) -> None:
        """出站消息发送结束（等价于旧的 AFTER_SEND）：记下麦麦刚说了什么，用于归因。

        Args:
            message: 本次发送的序列化 SessionMessage。
            sent: 是否发送成功。
            **kwargs: 宿主附加参数。
        """
        if not sent:
            return
        adapted = MessageAdapter(message or {})
        if not adapted.stream_id:
            return
        text = adapted.plain_text or adapted.raw_message or ""
        if not text:
            return
        try:
            reply_id = str(adapted.additional_data.get("reply_message_id") or "")
            reply_target = self._inbound_by_id.get(adapted.stream_id, {}).get(reply_id)
            self._remember_message(adapted)
            st = logic.SCORE.stream(adapted.stream_id)
            st["last_bot_target_uid"] = str((reply_target.message_base_info if reply_target else {}).get("user_id") or "")
            logic.SCORE.note_bot_said(adapted.stream_id, text)
            info = adapted.message_base_info
            self._log(f"AFTER_SEND 记下麦麦发言 sid={adapted.stream_id[:8]} text={text[:40]!r}")
            # 表情包频率：机器人每次说完话，按概率顺手补一张库里的图
            await logic.maybe_auto_sticker(self, adapted.stream_id, str(info.get("group_id") or ""), text)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[behavior_score] 记录机器人发言失败: {type(exc).__name__}: {exc}")

    @HookHandler("maisaka.replyer.before_request", name="behavior_score_reply_prompt")
    async def on_before_reply_request(self, **kwargs: Any) -> Dict[str, Any]:
        """回复前的提示词注入点（等价于旧的 POST_LLM 的注入部分）。

        旧版是直接改 `message.llm_prompt`；新版这个 hook **不给你提示词正文**，
        只给一个 `extra_prompt` 字段，返回值里改它就会被追加进本次 replyer 提示词
        （`allow_kwargs_mutation=True`）。

        ⚠️ 这个 hook **不能 abort**（实测 `allow_abort=False`），所以"低好感就不理他"
        那类接管在上一个 hook（`chat.receive.after_process`）里做。

        Args:
            **kwargs: 宿主传入的请求上下文，含 `session_id` / `extra_prompt` 等。

        Returns:
            Dict[str, Any]: `modified_kwargs.extra_prompt` 会被追加进本次回复提示词。
        """
        try:
            sid = str(kwargs.get("session_id") or "")
            reply_id = str(kwargs.get("reply_message_id") or "")
            adapted = (self._inbound_by_id.get(sid, {}).get(reply_id) if reply_id
                       else self._latest_inbound.get(sid))
            blocks: List[str] = []

            uid = uname = text = ""
            mentioned = quoted = asking = False
            if adapted is not None:
                info = adapted.message_base_info
                uid = str(info.get("user_id", "") or "")
                # 2026-10-10：群里昵称可能带控制字符/二进制垃圾（日志里见过形如
                # `\b%\u0100\u0100\u0007...某科学的超威蓝猫` 的昵称），进日志和提示词前先洗净
                uname = logic.safe_name(info.get("user_cardname") or info.get("user_nickname") or "")
                text = logic.clean(adapted.plain_text or "")
                bot_qq, bot_nick = logic._bot_ids()
                mentioned, quoted = logic._mentioned_bot(adapted, bot_qq, bot_nick)
                asking = logic.is_full_ask(text, logic.FAV_ASK)

            if uid and logic.FAVOR.get(uid) < logic.LOW_FAV:
                # 入站闸门之后 Planner 仍可能选到历史消息；按真正目标再挡一次。
                await self._guard(adapted)
                return {"action": "abort"}

            # ---- 表现分 + 教训 ----
            if self.get_config("behavior_score.inject_prompt", True) is not False:
                blocks.append(logic.SCORE.prompt_block())
            # ---- 好感度（含档位描述、专属称呼等）----
            # 2026-10-11：`is_master` 一起传进去 —— 只有对**主人本人**才允许叫「主人」。
            # 不传的话，那段"主人只有一个"的约束对模型来说没有落点，
            # 它会继续对每个高好感度群友喊主人（实测 `主人你管她叫ak干嘛`）。
            fb = logic.FAVOR.prompt_block(uid, uname, asking=asking, alive=True,
                                          is_master=self._is_admin(uid))
            if fb:
                blocks.append(fb)
            # ---- 身份风格 + 专属称呼 ----
            # 身份是"对这个人"的，所以每轮都得带上，且要说清"跟他说话用这个风格"，
            # 不然模型会一直用默认口吻。
            rec = logic.FAVOR.rec(uid) if uid else {}
            ident = str(rec.get("identity") or "")
            if ident:
                style = str((logic._identity_options().get(ident) or {}).get("style") or "")
                if style:
                    blocks.append(style)
            nick = str(rec.get("nickname") or "")
            if nick:
                cn = str(logic.PROMPTS.get("callname", "prompt", default="") or "")
                if cn:
                    blocks.append(logic._fmt(cn, nick=nick, who=uname or uid))
            # ---- 长期错题本：按"犯过几次"排序注入，专治反复犯的老毛病 ----
            if self.get_config("reflection.enabled", True) is not False:
                try:
                    rn = int(self.get_config("reflection.limit", logic.REFLECT_LIMIT)
                             or logic.REFLECT_LIMIT)
                except (TypeError, ValueError):
                    rn = logic.REFLECT_LIMIT
                rb = logic.REFLECT.prompt_block(max(1, min(20, rn)))
                if rb:
                    blocks.append(rb)
            # ---- 冒犯候选词 → 结合语境表达边界，不把孤立词直接当作辱骂 ----
            hostile = [w for w in logic.HOSTILE if w in text]
            if hostile:
                blocks.append(
                    f"【可能的冒犯】{uname or uid} 的话里出现了「{hostile[0]}」。结合指向、上下文和熟人玩笑判断，"
                    f"不要凭孤立词就认定在辱骂你。确有冒犯时，可以针对具体言行有分寸地表达不悦、拒绝或结束话题；"
                    f"不必赔笑、附和或自贬，也不用固定对白。真被惹怒时可以尖锐回怼、讽刺或嫌弃，反击对方实际说的话和行为；不编黑料、曝隐私、作威胁，不迁怒无关的人。对方解释或道歉后可以降温。\n"
                    f"（表现分和好感度的数字**只有上面给你的那些是真的**，不许自己编。"
                    f"好感度已经因为他骂你掉过了，你不用自己再算。）"
                )

            if ident:
                blocks.append(
                    "【身份设定的使用范围】以上身份、外形、动作与吃饭睡觉描述只供角色表达，"
                    "不当作刚刚发生的现实经历；称呼和亲疏照旧，不能改写事实回答，"
                    "不能为了角色口气编造上课、出门、吃饭等现实行程。日常聊天、称呼和身份玩笑沿用鱼或示例角色的角色语境，"
                    "不主动转成AI身份科普；明确询问底层模型、接口或现实办事能力时如实说明。"
                )
            extra = "\n\n".join(b for b in blocks if b)
            self._log(f"注入提示词 {len(extra)} 字（{len([b for b in blocks if b])} 段）sid={sid[:8]}")
            return {"action": "continue", "modified_kwargs": {**kwargs, "extra_prompt": extra}}
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[表现分] 注入提示词失败: {type(exc).__name__}: {exc}")
            return {"action": "continue"}


    # ----------------------------------------------------------------- 管理命令

    def _is_admin(self, uid: str) -> bool:
        """判断是不是管理员（`[behavior_score].admin_qq`，默认机器人主人）。

        Args:
            uid: 发送者 ID。

        Returns:
            bool: 是管理员返回 True。
        """
        return logic._is_admin(uid, {"admin_qq": self.get_config("behavior_score.admin_qq", None)})

    @Command(
        "favor_admin",
        description="好感度管理（仅管理员）：设置/加减/重置（查数字直接问它就行）",
        # ⚠️ 必须**带参数**才算命令（`\s+` + `\S.*`，不能用 `\s*` + `.*`）。
        # 否则「@示例助手 好感度」会被整条标成命令，而消息链默认会滤掉命令 ——
        # 用户看到的就是"@它不理人"（2026-09-18 踩过：某群 5 条「@示例助手 好感度」全石沉大海）。
        # 参数首字符必须**非空白**，否则「好感度␣␣␣」也会被当成命令。
        # ⚠️ 2026-10-11：@ 前缀放宽成 `@[^\s]+`，因为真实消息里是 `@示例助手 好感度 50`
        # （不带尖括号和 QQ 号），旧 pattern 的 `@<[^>]*>` 匹配不上整条命令。
        pattern=rf"^{_ADMIN_AT_PREFIX}/?(?P<fav_cmd>好感度)\s+(?P<fav_args>\S.*)$",
    )
    async def handle_favor_admin(
        self,
        stream_id: str = "",
        platform: str = "",
        user_id: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, Optional[str], bool]:
        """好感度管理命令（旧 `FavorAdminCommand.execute`）。

        Args:
            stream_id: 聊天流 ID。
            platform: 平台名。
            user_id: 发送者 ID。
            matched_groups: 正则命名组。
            **kwargs: 宿主附加参数。

        Returns:
            Tuple[bool, Optional[str], bool]: (成功, 说明, 是否拦截)。
        """
        try:
            sender = str(user_id or "")
            if not self._is_admin(sender):
                # 不是管理员：不吭声、也不拦（让正常聊天继续），免得暴露这是个管理命令
                return True, None, False

            raw = str(kwargs.get("text", "") or "")
            args = str((matched_groups or {}).get("fav_args") or "").strip()
            # ⚠️ 目标解析必须带上消息段：真 QQ 号只存在于段结构的 `target_user_id` 里，
            # 文本里只有 `@昵称`（2026-10-11 修，详见 logic._parse_target）。
            uid, name = logic._parse_target(args or raw, sender, self._current_segments)
            who = name or f"QQ{uid}"

            if not args:
                line = f"{who} 的好感度是 {logic.FAVOR.get(uid)}"
            elif "重置" in args:
                if uid != sender or logic._has_at_mark(args):
                    line = f"已把 {who} 的好感度重置为 {logic.FAVOR.admin_reset(uid, name)}"
                else:
                    logic.FAVOR.admin_reset()
                    line = f"已把所有人的好感度重置为 {logic.FAVOR.initial}"
            else:
                # ⚠️ 先去掉 @<昵称:QQ号> 和 @昵称 再找数字：那里面就有个 QQ 号，
                # 直接 findall 会把 QQ 号当成"要设成的数值"（踩过：「好感度 @阿彬 50」被设成了 123）
                args_clean = logic._CMD_AT.sub(" ", args)
                args_clean = logic._strip_first_at_nick(args_clean)
                nums = logic._CMD_NUM.findall(args_clean)
                if not nums:
                    line = "用法：好感度 [@某人] [重置|设为的数字|+N|-N]"
                elif re.search(r"[+-]\s*\d+", args_clean):
                    line = f"{who} 的好感度 {int(nums[0]):+d} → {logic.FAVOR.admin_add(uid, int(nums[0]), name)}"
                else:
                    line = f"已把 {who} 的好感度设为 {logic.FAVOR.admin_set(uid, int(nums[0]), name)}"
            await self.ctx.send.text(line, stream_id)
            self._log(f"[好感度] 管理命令 → {line}")
            return True, line, True
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[好感度] 管理命令出错: {type(exc).__name__}: {exc}")
            return True, None, False

    @Command(
        "score_admin",
        description="表现分管理（仅管理员）：设置/重置（查分数直接问它就行）",
        # 同好感度命令：必须带参数，光说「表现分」不算命令（否则会被当命令滤掉）
        # ⚠️ 2026-10-11：@ 前缀同样放宽（旧版只认 `@<昵称:QQ号>`，真实消息是 `@昵称`）
        pattern=rf"^{_ADMIN_AT_PREFIX}/?(?P<score_cmd>表现分)\s+(?P<score_args>\S.*)$",
    )
    async def handle_score_admin(
        self,
        stream_id: str = "",
        platform: str = "",
        user_id: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, Optional[str], bool]:
        """表现分管理命令（旧 `ScoreAdminCommand.execute`）。

        Args:
            stream_id: 聊天流 ID。
            platform: 平台名。
            user_id: 发送者 ID。
            matched_groups: 正则命名组。
            **kwargs: 宿主附加参数。

        Returns:
            Tuple[bool, Optional[str], bool]: (成功, 说明, 是否拦截)。
        """
        try:
            sender = str(user_id or "")
            if not self._is_admin(sender):
                return True, None, False
            args = str((matched_groups or {}).get("score_args") or "").strip()
            if not args:
                line = f"当前表现分 {logic.SCORE.data.get('score', 100)}/100"
            elif "重置" in args:
                line = f"表现分已重置为 {logic.SCORE.admin_reset()}/100"
            else:
                nums = logic._CMD_NUM.findall(args)
                if not nums:
                    line = "用法：表现分 [重置|数字]"
                else:
                    line = f"表现分已设为 {logic.SCORE.admin_set(int(nums[0]))}/100"
            await self.ctx.send.text(line, stream_id)
            self._log(f"[表现分] 管理命令 → {line}")
            return True, line, True
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.error(f"[表现分] 管理命令出错: {type(exc).__name__}: {exc}")
            return True, None, False


def create_plugin() -> BehaviorScorePlugin:
    """创建插件实例（宿主按此入口加载）。

    Returns:
        BehaviorScorePlugin: 插件实例。
    """
    return BehaviorScorePlugin()
