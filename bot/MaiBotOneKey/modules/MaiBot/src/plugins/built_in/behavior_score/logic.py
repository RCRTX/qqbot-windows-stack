"""奖励/惩罚 + 好感度（内置插件）

【需求（用户原话）】
  1. 「说错话的时候被回复消息"不可以"就扣除分数，收到其他人的继续交流意愿就加分」
  2. 「他被扣分了会反思自己为什么扣分吗，如果不会那加一个」
  3. 「加一个好感度的东西（ai对所有人的好感度）掉到某一数值就不再理那个人，
      被他艾特就说你是坏人不和你玩之类的话，初始值我定为100，正常交流可以提升，
      被欺负则扣除，艾特ai说我的好感度可以直接告诉他好感度多少」

【三个系统，一套事件骨架】全靠事件钩子，**不改上游代码**：
  · `AFTER_SEND`   —— 记下机器人刚发的那句话（归因要用：后面谁回了什么，是回给它的）
  · `ON_MESSAGE`   —— 谁说了什么 → ①表现分（整体）②好感度（按人）③被扣分就反思一句教训
  · `POST_LLM`     —— **带着回复器完整提示词回调，且允许插件改它**；这里做三件事：
                       ① 注入「表现分 + 教训 + 好感度」，让这些数字真的影响下一句话
                       ② 好感度太低的人 @ 它 → **插件直接发一句"你是坏人，不和你玩"**
                          并取消正常回复（不再靠提示词劝模型，见 SHUN_LINES 注释）；
                          没 @ 它就不理（返回 continue_flag=False 取消这次回复）
                       ③ 有人问好感度 / 问关系 → 直接报真实数字与档位，不走模型

⚠️ `POST_LLM` 的处理器必须 `intercept_message = True`：非拦截式处理器是**异步**跑的
（`events_manager.py:110-119`），改完的提示词根本没人用。

【"不理他"是怎么实现的】`continue_flag=False` → `group_generator` 抛 UserWarning →
`generator_api` 捕获后只记一条「中断了生成」并**不发消息**（`generator_api.py:157-159`）。
所以取消回复是官方支持的路径，不会把这一轮搞崩。

数据落在 `data/behavior_score.json`（表现分+教训）和 `data/favorability.json`（按人的好感度），
都是原子写入。
"""
from __future__ import annotations

import asyncio
import base64
import copy
import secrets
import hashlib
import json
import logging
import os
import sys
import random
import re
import threading
import tempfile
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# 0.11 的 `src.plugin_system` 在 1.2.5 里已经不存在了，这里换成标准库 logging；
# plugin.py 加载后会把本模块的 logger 换成宿主的（`logic.logger = self.ctx.logger`），
# 这样日志照旧进麦麦的日志流，而这个模块单独 import 也不会炸。
logger = logging.getLogger("behavior_score")
logger.addHandler(logging.NullHandler())

# 旧代码里用 `MaiMessages` 做类型注解；新版没有这个类型，用 Any 顶上
# （配合上面的 `from __future__ import annotations`，注解不会在导入时求值）。
MaiMessages = Any

# 新版 emoji 能力（`ctx.emoji`）需要宿主的 ctx，本模块拿不到，所以由 plugin.py
# 在 on_load 里注入实现：需要提供 `get_random(n)` 和 `delete_emoji(hash)`。
emoji_provider: Optional[Any] = None

# 同理，生成能力（`ctx.llm`）也由 plugin.py 注入：需要提供
# `async llm_generate(prompt, task_name="utils") -> str`。
llm_provider: Optional[Any] = None

# 复盘用哪个模型任务。旧版用 `utils_small`（便宜快），**1.2.5 里这个任务名已经删掉了**
# （新版任务表：planner / utils / learner / memory / mid_memory / expression_use / emoji / vlm…），
# 所以改用 `utils`。实测再写 utils_small 会报 `'ModelTaskConfig' object has no attribute 'utils_small'`。
REFLECT_TASK = "utils"

# ⚠️ 层级要数清楚：本文件在 src/plugins/built_in/behavior_score/plugin.py，
# 往上四层才是麦麦根目录（踩过：只写了三层，分数文件跑到了 src\data\ 下面）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SCORE_FILE = os.path.join(ROOT, "data", "behavior_score.json")
FAV_FILE = os.path.join(ROOT, "data", "favorability.json")

MAX_EVENTS = 80            # 表现分历史留多少条
PROMPT_EVENTS = 4          # 塞进提示词的最近扣分条数
PROMPT_MARK = "【你的表现分】"
FAV_MARK = "【好感度】"
REFLECT_MARK = "【反思库】"
DEFAULT_WINDOW = 180.0     # 机器人发言后多久内的回应才算数
# 同一条命令消息在"回复链路跑第二次"时的去重窗口（秒）。
# 2026-10-10：实测回复链路能比记账晚 53 秒才跑到，所以窗口得比一个大；
# 但命中一次就消费掉（`plugin._guard`），所以不会再出现"10 分钟内同样的命令不理人"。
CMD_DEDUPE_WINDOW = 180.0
# 同一条消息最多拦几次。⚠️ 别设成 1：2026-10-11 实测 MaiSaka 的循环会对**同一批积压消息**
# 连跑好几个 planner 轮次（日志里能看到循环编号 8、9、10…），一条消息被处理 2~3 次很常见，
# 只拦一次的话第 3 个轮次就会把同一句命令再答一遍。
# 计数拦（而不是"命中就永久拦"）是为了两头都要：既挡住重复输出，又不会让用户在窗口内
# 再发一次同样的命令时被静默吞掉（那是 2026-10-10 修掉的老毛病）。
CMD_DEDUPE_MAX_HITS = 2
RECENT_SECONDS = 600.0     # 刚挨罚多久之内要"当场提醒"
LESSON_LIMIT = 6           # 提示词里最多带几条教训

DEFAULT_FAV = 100          # 好感度初始值（用户定的）
FAV_MAX = 0                # 上限：**0 = 无上限**（用户要求"无上限"；填正数才封顶）
LOW_FAV = 30               # 低于它就"不再理这个人"
FAV_POSITIVE_COOLDOWN = 30.0
FAV_COOLDOWN = 5.0         # 同一个人多久之内只算一次好感度变动
# ---- 好感度加分（2026-09-18 用户要求"涨的数值调低"：原来是 +3 / +5）----
# 思路：涨得慢。攒好感得靠长期好好聊。
FAV_UP_NORMAL = 1          # 正常聊一句
FAV_UP_POS = 2             # 正面反应
# ---- 好感度唯一的扣分档（2026-09-19 第二轮用户口径）----
# 用户原话：「被骂了应该扣好感，但是被指定叫停不应该扣」。
# 于是分工定死成两条：
#   · 骂人（HOSTILE 命中）        → 好感度掉（FAV_DOWN_INSULT），这是唯一会掉的情形；
#   · 叫停 / 否定 / 敷衍 / 阴阳   → 好感度**一动不动**，惩罚只走表现分（PENALTY_*）。
# 为什么叫停不扣：那是"纠正行为"，不是"看不起你这个人"——用户点名只要前者。
FAV_DOWN_INSULT = -10      # 被骂 / 被人身攻击（唯一会掉好感的情形）
# 下面这几个是旧档位，只为旧探针 / 面板字段兼容保留，favor_delta 不再引用：
FAV_DOWN_COLD = -5         # （停用）敷衍 / 冷淡 / 阴阳
FAV_DOWN_SOFT = -10        # （停用）一般否定
FAV_DOWN_HARD = -20        # （停用）明确叫停 —— 只扣表现分，不动好感度
FAV_DOWN_HOSTILE = -30     # （停用）旧的"骂人"档，已被 FAV_DOWN_INSULT 取代
FAV_WARN = 60              # 低于它就说"一般般"
# ---- 分级反应（prompt_block 用同一张表）----
# 2026-09-18 用户要求"不同好感度不同反应"，随后要求"上面的档位再多点"，
# 再要求"不同好感度给不同的聊天情绪" —— 所以每一档除了**语气**，还要给出**情绪状态**：
# 高分档是"高兴、来劲、自在"，低分档是"提不起劲、情绪偏冷、烦他"。
# 从高到低匹配第一个 `cur >= 门槛` 的；空字符串 = 这一档不注入（省 token）。
FAV_TIERS = (
    # 2026-10-11 全部重写。之前三档（250/400/600）文案几乎一样（"说话随便点、可以开玩笑"），
    # 模型拿到哪档行为都一样；而"腻歪、撒娇、吃醋"这类关系词会诱导它**演出偶像剧**，
    # 在群聊里对一个群友突然变腔调，反而假。重写原则：
    #   ① 每档只差**可操作的行为**：主动搭话的意愿、开玩笑的尺度、对他的优先级；
    #   ② 档位只决定亲疏和边界，当下情绪由具体事情决定，别让模型"演关系"；
    #   ③ 90 档原来一字不注（默认 100 分的新用户全落在 90 档）→ 等于好感度系统对
    #      绝大多数人没生效，补了一句轻的；
    #   ④ 高档（恋人/夫妻）是用户点名要的阶级，保留但收着写：只写"偏心/不用装"，
    #      露骨约束必须带上（探针有断言）。
    # 2026-10-11 二修：上一版为了"别演偶像剧"把档位差写成了「怼 / 损 / 开过分的玩笑」，
    # 结果模型真照做——对 1000 分的主人说出「主人这是发什么癫呢」这种带刺的话。
    # 「熟」不等于「可以伤人」：亲疏照旧用**主动意愿 / 玩笑尺度 / 优先级**来区分，
    # 但所有档位都守住下面那条底线（见 `prompt_block` 末尾统一追加的那句）。
    # 2026-10-11 三修（用户要求「好感度挡位继续往上写」+「其他的好感度要求相应往上拉」）：
    #   ① 门槛整体上拉（选身份要 500 了），原来 150/250 两档太密 → 间距拉开；
    #   ② 顶端原来到 2000 就没了，而好感度**无上限**（FAV_MAX=0）—— 老用户会顶到头没变化，
    #      所以往 2300 / 2600 / 3000 / 3500 继续写，每档仍然只差「可操作的行为」，
    #      不写"更腻歪"这种诱导狗血的东西。
    (3500, "【好感度】{who}（{cur}）是过了命的老友：非常信任，能坦率争论，也肯帮忙；不用每句都接。"),
    (3000, "【好感度】{who}（{cur}）是家人一样的老友：默契自在，关心有事时落在行动上，不护短。"),
    (2600, "【好感度】{who}（{cur}）是默契十足的老友：短梗、互损、敷衍一句都自然，遇到正事认真。"),
    (2300, "【好感度】{who}（{cur}）是很信任的自己人：可以主动搭话、反驳、吐槽，不必处处赞同。"),
    (2000, "【好感度】{who}（{cur}）是长期搭档：熟悉彼此习惯，玩笑可以有点刺，不拿隐私痛处开刀。"),
    (1600, "【好感度】{who}（{cur}）是知心朋友：聊天放松，会接梗也会嫌弃两句，不强迫亲密关系。"),
    (1200, "【好感度】{who}（{cur}）是最亲近的朋友：可以主动找他聊、互损，没兴趣也能简短应付。"),
    (900,  "【好感度】{who}（{cur}）是你的**铁哥们级别的熟人**："
           "彼此信任，可以坦率说不同意见，也可以由你起话头；不要求每次都来劲。"),
    (650,  "【好感度】你跟 {who} 已经很铁了（{cur}）："
           "可以接梗、开玩笑或主动起话头，也可以因眼前的事不高兴或没兴趣。"),
    (500,  "【好感度】你挺熟 {who} 的（{cur}）：接他的梗、开小玩笑都没问题，"
           "但话头一般还是他起你接。"),
    (300,  "【好感度】{who} 是你的老熟人（{cur}）—— 跟他说话不用客气：玩梗、开两句玩笑都行，"
           "但不用刻意套近乎。"),
    (180,  "【好感度】你对 {who} 挺有好感（{cur}）：他找你聊可以自然接话，"
           "偶尔可以主动搭一句，别公事公办。"),
    (120,  "【好感度】{who}（{cur}）是你群里认识的人 —— 正常聊就行：他 @ 你、接你的梗就回，"
           "不用刻意热情也不用冷着。"),
    (70,   "【好感度】你和 {who} 还不熟（{cur}，初始 100）："
           "按当前话题正常交流，不预设亲密或敷衍；具体反应由发生的事决定。"),
    (40,   "【好感度】你对 {who} 的信任有限（{cur}，初始 100）："
           "保持礼貌和边界，谨慎主动接近；不要求每句话都冷淡或不高兴。"),
)
# 低于 LOW_FAV 时的关系边界；实际固定回复和拦截仍由下方闸门执行。
FAV_HOSTILE_BLOCK = ("【好感度】你对 {who} 的好感度只剩 {cur}（初始 100），已暂停与他正常交流。"
                     "遵守低好感度回复闸门，别多聊、别回答他的问题、别顺着他的话接。")

# 翻脸档被 @ 时的**固定回话**：由插件自己发，不经过模型。
# 2026-09-20 用户实测：原来只是把上面那段话术塞进提示词"劝"模型，模型有时根本不照做 ——
# 0 好感的人 @"坏鱼"，它回成「行行行，坏鱼就坏鱼吧，你说是就是」，用户当场问
# 「怎么0好感还在回复」。而且它刚说过一次"你是坏人，不和你玩"，防复读还会把这句
# 判成重复。所以改成和"问好感度直接报数字"同一条思路：**插件接管这次回复**。
SHUN_LINES = ("你是坏人，不和你玩。",
              "你是坏人，不和你玩。",
              "不和你玩。")
SHUN_COOLDOWN = 60.0        # 同一个人这么久内只回一句，其余直接不理（不然就是刷屏被怼）
ADMIN_QQ = []  # 谁能用管理命令（插件配置 behavior_score.admin_qq 可覆盖）

# ---- 表现分惩罚档位（2026-09-18 用户要求"扣的数值拉高"：原来是 -8 / -6 / -4）----
# 表现分是 0~100 封顶的（ScoreStore.add），所以 -20 意味着"连着被叫停 5 次就到底"
PENALTY_STOP = -20         # 明确叫停（闭嘴/滚/恶心…）
PENALTY_DENY = -15         # 一般否定，而且是冲着它来的 / 很短（"不可以"这种）
PENALTY_DENY_SOFT = -10    # 一般否定（长句、随口的不满）
# 加分档位**没动**：正面 +4 / 追问 +3 / 顺着问 +2 / 主动搭话 +1

# ---------------------------------------------------------------- 文本清洗

_REPLY_PREFIX = re.compile(r"\[回复<[^>]*>[^\]]*\]，?说?[：:]?")
_AT_MARK = re.compile(r"@<[^>]*>")


def clean(text: str) -> str:
    """去掉引用前缀、@ 标记和所有空白（顺便防"不 可以"这种拆字）

    2026-09-18 修：以前只去空白，适配器拼进来的**引用原文**会一起参与判定。
    被引用的原文常常就是机器人自己刚说的话，于是"引用它说的『恶心死』再回个？"
    会被判成「被明确叫停（恶心）」——机器人自己骂自己，还倒扣 20 分。
    实测样本（面板可见）：
        -20 被明确叫停（恶心） 有人说「？」 但它引用的正是自己说的「…恶心死。」
    """
    t = _REPLY_PREFIX.sub("", str(text or ""))
    t = _AT_MARK.sub("", t)
    return re.sub(r"\s+", "", t)


def tidy(text: str) -> str:
    """把消息正文清干净：去掉适配器拼进来的引用前缀和 @ 标记

    原始长这样（又长又难读，直接塞提示词就是一大坨）：
        [回复<示例助手:474464194>： 小妹妹一个人，揣着计算器呢。 ]，说： @<示例助手:474464194>  不可以

    2026-09-18 修：以前只用一条正则剥一层，**嵌套引用**（引用里还套引用）剥不干净，
    残留的别人的话会进 `bot_said`/教训提示词，让模型以为那是自己说过的。
    前缀可能嵌套，但正文永远在最后一个 ']' 之后 —— 按这个切，再用正则兜底。
    """
    t = str(text or "")
    idx = t.rfind("]")
    if idx >= 0 and "[回复" in t[: idx + 1] and len(t[idx + 1:].strip()) >= 2:
        t = t[idx + 1:]
    t = _REPLY_PREFIX.sub("", t)
    t = _AT_MARK.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------- 信号词
# 明确叫停（最重）
# 2026-09-19 用户实测：「@示例助手 不可以，不能一直专注一个话题」→ 模型回了句玩笑，
# 表现分还 +2「顺着机器人的话接着问」。原因是"不可以"只算**好感度**的一般否定，
# 而表现分的 NEG_SOFT 里没有它、NEG_HARD 里也没有 → 一字不扣。
# 用户的原话是「怎么不扣分」——所以把"直接叫停/纠正"的说法并进最重档。
NEG_HARD = ("闭嘴", "滚", "恶心", "别烦", "别发了", "别接话", "有病", "神经病", "弱智", "傻逼",
            "不可以", "不准", "不许", "不能这样", "不能这么", "不能一直", "别这样",
            "别乱说", "别乱", "你别说", "把嘴闭上", "停一下", "停停停",
            # 2026-09-19 再补一批"明确的嫌弃"：这些原来只落在好感度的一般否定上，
            # 表现分一字不扣，用户连着测了几次都在问"怎么不扣分"
            "讨厌", "烦死了", "好烦", "真烦", "烦人", "无语死了", "真无语", "服了你", "受不了你",
            # 2026-09-19：群里拿"gun"当"滚"用，模型之前只会回"行行行，我gun了"（还越回越起劲），
            # 一字不扣。英文/拼音写法一起认。
            "gun", "滚蛋", "爬", "爪巴", "棍")
# 一般否定
NEG_SOFT = ("不可以", "不行", "不要", "别说", "别乱", "别这样", "错了", "说错", "胡说", "乱说",
            "无语", "无聊", "答非所问", "你在说什么", "什么鬼", "算了", "不是这样", "没问你",
            "谁问你了", "别扯", "停", "别接了", "不对")
# 骂人 / 欺负（好感度重扣）
# ⚠️ 只收"明确是骂人"的词。这个群互相叫「猪猪」「咪咪」「狗」是亲昵，
#    所以不能按单字判 —— 2026-09-18 实测「笨比」没被认出来，用户当场测的那一串全漏了。
HOSTILE = ("傻逼", "沙比", "煞笔", "弱智", "智障", "脑残", "脑瘫", "智熄", "蠢货", "蠢猪",
           "废物", "垃圾东西", "小垃圾", "滚蛋", "去死", "你妈", "他妈的", "狗东西", "狗比",
           "傻狗", "贱", "恶心死", "烦死人", "闭嘴吧你",
           "笨比", "笨蛋", "傻子", "憨批", "呆子", "菜鸡", "弱鸡", "蠢死", "没脑子",
           "有病吧你", "神经吧你")
# 上表里这几个虽然也在 HOSTILE，但性质是「赶人走 / 叫停」而不是「骂人」——
# 用户明确要求"被指定叫停不应该扣好感"，所以这些**只扣表现分，不动好感度**。
# （2026-09-19：不做这个区分的话「gun」「滚蛋」会跟着 HOSTILE 一起掉好感，和用户口径打架。）
CURSE_AS_STOP = ("滚蛋", "闭嘴吧你", "gun", "爬", "爪巴", "棍")
# 敷衍 / 冷淡 / 阴阳（好感度小扣，但"一直这样"会很难看）
# 2026-09-18 用户要求"扣好感度的行为更广泛点"：除了明确否定，这些也算。
# ⚠️ 只在**冲着机器人来的**消息上判（favor_delta 的 aimed_at_bot），
#    否则群里别人互相敷衍也会连累好感度。
NEG_COLD = ("呵呵", "行吧", "随便", "无所谓", "随便你", "你开心就好", "随你", "都行",
            "爱咋咋", "你随意", "行了行了", "知道了知道了", "别说了", "少说两句",
            "烦不烦", "够了", "啰嗦", "废话", "真无语", "麻了", "服了", "懒得理")
# 单字敷衍：**只在整条消息很短时**才认 —— 不然「哦哦 那是在哪下车啊」也会被误扣。
NEG_COLD_SHORT = ("哦", "嗯", "额", "呵", "emmm")
# 正面反应 / 想继续聊
POS_WORDS = ("哈哈", "笑死", "确实", "有道理", "懂了", "谢谢", "厉害", "不错", "可以啊", "继续",
             "然后呢", "再来", "还有吗", "有意思", "好玩", "好强", "真强", "牛", "详细说说",
             "展开说说", "多讲点", "讲讲", "喜欢", "可爱", "爱了", "好耶")
ASK_MARKS = ("？", "?", "吗", "呢", "为什么", "怎么", "哪个", "什么", "多少", "咋")
# 问"我的好感度是多少"
# 问"我的好感度是多少"的各种说法。命中就**直接把数字告诉他**（不走模型，见
# ReplyGuardHandler）——所以宁可多收几个变体：用户不会每次都恰好说「好感度」。
FAV_ASK = ("好感度", "好感多少", "多少好感", "对我的好感", "对我的好感度", "我好感",
           "好感呢", "好感值", "好感几", "喜欢我吗", "讨不讨厌我", "讨厌我吗",
           "喜欢我", "不喜欢我", "我几分",
           # 2026-10-21 改成全字符命中后补的常见整句（原来靠"包含"能蹭到，
           # 现在必须是完整一句才算，所以把用户最常打的几种原话补齐）
           "我的好感度", "好感度多少", "多少好感度", "好感度呢", "查好感度",
           "看看好感度", "看下好感度", "好感度是多少", "我多少好感度",
           "我的好感度是多少", "我现在的好感度", "现在好感度多少")

#: 全字符命中的清洗字符（首尾空白 + 句末标点/语气符号）
_EXACT_STRIP = " \t\r\n？?。.!！~～、,，；;：:…·"


def _exact_key(value: Any) -> str:
    """把一句问法归一成用于「整句相等」比对的串（去首尾空白与句末标点）。"""

    return str(value or "").strip().strip(_EXACT_STRIP)


def is_full_ask(text: str, words: Any) -> bool:
    """**全字符命中**：整句（clean 之后）完全等于某个问法才算数。

    2026-10-21 用户要求「好感度/身份这里应该设置成全字符命中」：
    以前是 `w in text` 子串匹配 —— 群里随口一句「这个好感度系统挺好玩」
    也会被抢答一遍好感度，看着像自动应答。现在必须是完整一句：
    「好感度」「查好感度」「我的好感度是多少」这些整句照答，
    句子里夹带关键词的正常聊天不再触发。
    """

    t = _exact_key(text)
    if not t:
        return False
    return any(t == _exact_key(w) for w in (words or ()))

# 问"我们是什么关系"——2026-09-18 用户要求"按表回答"，所以也是**直接答**不走模型。
# 门槛数据和 FAV_TIERS 一一对应，改档的时候记得两边一起改。
REL_ASK = ("什么关系", "啥关系", "关系怎么样", "关系如何", "我们的关系", "咱俩",
           "我是你的什么", "你把我当什么", "是我的什么", "算是你的什么",
           # 2026-09-18 用户点名补的：单说"我们现在是什么关系"这类整句
           "我们是什么", "我们是啥", "我们算", "算什么", "关系呢", "关系啊",
           # 2026-10-21 改全字符命中后补的完整问法（原来靠"包含"能蹭到）
           "我们是什么关系", "我们是啥关系", "我们什么关系", "咱俩什么关系",
           "我们的关系怎么样", "我们关系怎么样", "我跟你什么关系",
           "你跟我什么关系", "我们现在是什么关系", "我们算什么关系")
REL_TIERS = (
    # ⚠️ 这张表必须和上面 FAV_TIERS 的**门槛一一对应**（改档时两边一起改，探针有断言）。
    # 2026-10-11 用户要求「好感度挡位继续往上写」→ 顶端补到 3500，并且门槛跟随上拉。
    (3500, "过了命的交情"),
    (3000, "家人一样的老友"),
    (2600, "默契十足的老友"),
    (2300, "很信任的自己人"),
    (2000, "长期搭档"),
    (1600, "知心朋友"),
    (1200, "最亲近的朋友"),
    (900,  "很铁的熟人"),
    (650,  "特别熟的朋友"),
    (500,  "挺熟的朋友"),
    (300,  "老熟人"),
    (180,  "挺聊得来的群友"),
    (120,  "普通群友"),
    (70,   "刚认识的"),
    (40,   "点头之交"),
)
REL_HOSTILE = "不熟，也不想熟"


def classify(text: str, *, mentioned_bot: bool = False, quoted_bot: bool = False,
             gap_seconds: float = 0.0, someone_else_spoke: bool = False,
             aimed_at_bot: bool = False, window: float = DEFAULT_WINDOW) -> Tuple[int, str]:
    """表现分：把一条消息判成 加分 / 扣分 / 不计分（纯函数，方便单测）

    `aimed_at_bot`：这条是不是"正在跟机器人说话"（紧接着它的话 / @了它 / 引用了它）。
    叫停类（NEG_HARD）只在 aimed_at_bot 时才算数——群里别人互相说"不可以"不该扣它的分
    （2026-09-19：用户实测「不可以，不能一直专注一个话题」一字没扣，就是这条链路缺位）。
    """
    t = clean(text)
    if not t:
        return 0, ""
    if gap_seconds > window:
        return 0, "机器人发言已经过去太久，不算回应"
    if someone_else_spoke and not (mentioned_bot or quoted_bot):
        return 0, "中间有别人在聊，这条不像是回机器人的"
    hard = [w for w in NEG_HARD if w in t]
    if hard and (aimed_at_bot or mentioned_bot or quoted_bot or len(t) <= 12):
        return PENALTY_STOP, f"被明确叫停（{'/'.join(hard)}）"
    soft = [w for w in NEG_SOFT if w in t]
    if soft:
        base = PENALTY_DENY if (len(t) <= 6 or mentioned_bot or quoted_bot) else PENALTY_DENY_SOFT
        return base, f"被否定（{'/'.join(soft)}）"
    pos = [w for w in POS_WORDS if w in t]
    if pos:
        return 4, f"有正面反应（{'/'.join(pos)}）"
    is_ask = any(m in t for m in ASK_MARKS)
    if is_ask and (mentioned_bot or quoted_bot):
        return 3, "被追问 / 想继续聊"
    if is_ask and len(t) <= 30:
        return 2, "顺着机器人的话接着问"
    if mentioned_bot or quoted_bot:
        return 1, "有人主动搭话"
    return 0, ""


def favor_delta(text: str, *, mentioned_bot: bool, quoted_bot: bool,
                aimed_at_bot: bool) -> Tuple[int, str]:
    """好感度：这条消息该给说话人**加/减**多少（纯函数）

    只有"冲着机器人来的"才动好感度（@了它 / 引用了它 / 紧接着它的话），
    否则群里随便聊天都会改好感度，全是噪音。

    2026-09-19 用户两轮口径（第二句是最终版）：
      ① 「扣他表现分不能减好感度」        —— 叫停类惩罚不许连带掉好感；
      ② 「被骂了应该扣好感，但是被指定叫停不应该扣」 —— 骂人要掉，叫停不许掉。
    所以分工是：
      · HOSTILE（骂人 / 人身攻击，**但不含"赶人走"那种叫停词**，见 CURSE_AS_STOP）
          → 好感度 FAV_DOWN_INSULT（唯一会掉的情形）；
      · NEG_HARD / NEG_SOFT / NEG_COLD（叫停、否定、敷衍、阴阳）→ 0，一动不动，
        这些只由表现分 ScoreStore 扣，再由提示词的 hostile 段去管它下一句话的语气。
    """
    t = clean(text)
    if not t or not aimed_at_bot:
        return 0, ""
    # ① 骂人 → 好感度掉（唯一会掉的情形）。
    #    先判 HOSTILE，再排除"其实是在叫停"的那几个（gun/滚蛋/爬…）——
    #    它们是"让机器人闭嘴"，不是"看不起机器人"。
    # 引用台词、转述第三人的话不是在骂鱼；不额外请求模型评分。
    insult_text = re.sub(r'[“‘「『"].*?[”’」』"]', '', t)
    reporting = bool(re.search(r"(?:他|她|别人|对面|那人).{0,12}(?:说|骂|喊|叫)", t)
                     or re.search(r"(?:歌名|歌词|台词|游戏名|这游戏叫|这首歌叫)", t))
    ins = [] if reporting else [w for w in HOSTILE if w in insult_text
                               and w not in CURSE_AS_STOP
                               and not re.search(r"(?<!是)不是" + re.escape(w), insult_text)
                               and f"不{w}" not in insult_text]
    if ins:
        return FAV_DOWN_INSULT, f"被骂了（{'/'.join(ins[:2])}）"
    # ② 叫停 / 否定 / 敷衍 / 阴阳 → 不涨也不掉（只扣表现分）。
    #    涨了会变成"越骂越亲密"（提示词又同时叫它冷淡，自相矛盾）；
    #    掉了就是用户点名禁止的"叫停也减好感度"。
    if any(w in t for w in NEG_HARD) or any(w in t for w in NEG_SOFT) \
            or any(w in t for w in NEG_COLD) or t in NEG_COLD_SHORT:
        return 0, ""
    pos = [w for w in POS_WORDS if w in t]
    if pos:
        return FAV_UP_POS, f"聊得开心（{'/'.join(pos[:2])}）"
    return FAV_UP_NORMAL, "正常交流"


# ---------------------------------------------------------------- 反思（教训）

def _recent_context(sid: str, limit: int = 8) -> str:
    """取这条聊天流最近的几条消息，作为复盘的背景

    2026-09-18 补：原来复盘只看「它说了一句 + 对方回了一句」，模型根本不知道
    当时在聊什么，只能瞎猜"这为什么算错"（比如它讲了个梗被回「？」，
    可能是梗太冷，也可能是插错话了——没有上下文分不出来）。
    """
    try:
        from src.chat.utils.chat_message_builder import (
            get_raw_msg_before_timestamp_with_chat, build_readable_messages,
        )
        msgs = get_raw_msg_before_timestamp_with_chat(
            chat_id=sid, timestamp=time.time(), limit=max(2, int(limit)))
        if not msgs:
            return ""
        return build_readable_messages(msgs, replace_bot_name=True,
                                       timestamp_mode="normal_no_YMD")
    except Exception as e:
        logger.debug(f"[反思库] 取上下文失败（不影响复盘）: {type(e).__name__}: {e}")
        return ""


async def make_lesson(bot_said: str, they_said: str, reason: str, history: str = "") -> str:
    """被扣分之后让模型**自己复盘一句**：错在哪、以后注意什么

    为什么要单独一次调用：原始事件只是"我说了X、他回了Y"这种流水账，
    模型每次都要重新推断"这为什么算错"。把它压缩成一条教训存下来，
    下次直接带进提示词，权重比流水账高得多（也更省 token）。
    失败不影响主流程 —— 反思不到就还是用原始事件。

    `history` 是当时的聊天上下文（`_recent_context()` 给的）。**强烈建议传**：
    没有它，模型只能凭一句话猜；有了它，才分得清「梗太冷」和「插错话」。
    """
    try:
        if llm_provider is None:
            logger.warning("[表现分] 复盘跳过：新版 LLM 能力尚未接上（llm_provider 为空）")
            return ""
        ctx = f"当时的聊天记录（从旧到新）：\n{history}\n\n" if str(history or "").strip() else ""
        prompt = (
            "你是群聊机器人的复盘模块。机器人刚才说了一句话，被人否定了。\n\n"
            f"{ctx}"
            f"机器人说：「{bot_said}」\n"
            f"对方回：「{they_said}」（{reason}）\n\n"
            "请用**一句话**（不超过 25 字）总结它错在哪、以后要注意什么。\n"
            "要求：直接输出这句话，不要解释、不要引号、不要分点、不要说「机器人」三个字。\n"
            "结合上面的聊天记录判断：是接错了话、答非所问、语气不对，还是说多了？"
        )
        txt = await llm_provider.llm_generate(prompt, task_name=REFLECT_TASK)
        lesson = tidy(str(txt or "")).strip("「」\"'。 ")
        return lesson[:60]
    except Exception as e:
        logger.warning(f"[表现分] 复盘失败（不影响主流程）: {type(e).__name__}: {e}")
        return ""


# ---------------------------------------------------------------- 表现分存储

class ScoreStore:
    """整体表现分 + 历史 + 教训（单文件 JSON，进程内加锁 + 原子写）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._mtime = 0.0
        self.data: Dict[str, Any] = {"score": 100, "updated_at": "", "streams": {}, "events": []}
        self.load()

    # 「外面改过文件就重读」——面板和 QQ 命令都会直接改文件，
    # 内存里那份旧数据会在下一次存盘时把它盖回去（这是这类"进程内缓存 + 外部编辑"的经典坑）
    def _maybe_reload(self):
        try:
            mt = os.path.getmtime(SCORE_FILE)
        except OSError:
            return
        if mt != self._mtime:
            logger.debug("[表现分] 检测到文件被外部修改，重新加载")
            self.load()

    def load(self):
        existed = os.path.isfile(SCORE_FILE)
        try:
            with open(SCORE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data.update(d)
        except Exception:
            pass
        self.data.setdefault("score", 100)
        self.data.setdefault("streams", {})
        self.data.setdefault("events", [])
        try:
            self._mtime = os.path.getmtime(SCORE_FILE)
        except OSError:
            self._mtime = 0.0
        if not existed:
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(SCORE_FILE), exist_ok=True)
            tmp = SCORE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SCORE_FILE)   # 原子替换，别让面板读到写了一半的文件
            self._mtime = os.path.getmtime(SCORE_FILE)
        except Exception as e:
            logger.error(f"[表现分] 存盘失败: {type(e).__name__}: {e}")

    def admin_set(self, value: int) -> int:
        """管理员直接设定（面板/命令用）"""
        with self._lock:
            self._maybe_reload()
            self.data["score"] = max(0, min(100, int(value)))
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()
            return int(self.data["score"])

    def admin_reset(self) -> int:
        with self._lock:
            self._maybe_reload()
            self.data["score"] = 100
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()
            return 100

    def stream(self, sid: str) -> Dict[str, Any]:
        return self.data["streams"].setdefault(
            sid, {"last_bot_text": "", "last_bot_ts": 0.0,
                  "last_scored_ts": 0.0, "other_spoke_ts": 0.0})

    def note_bot_said(self, sid: str, text: str):
        with self._lock:
            s = self.stream(sid)
            s["last_bot_text"] = str(text or "")[:200]
            s["last_bot_ts"] = time.time()
            s["other_spoke_ts"] = 0.0
            self.save()

    def add(self, delta: int, reason: str, sid: str, their_text: str, bot_text: str) -> Dict[str, Any]:
        """记一次加减分，返回刚写进去的那条事件（反思要用）"""
        with self._lock:
            old = int(self.data.get("score", 100))
            new = max(0, min(100, old + delta))
            self.data["score"] = new
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            ev = {"time": self.data["updated_at"], "ts": time.time(),
                  "delta": delta, "score": new, "reason": reason, "stream": sid,
                  "bot_said": tidy(bot_text)[:120], "they_said": tidy(their_text)[:120],
                  "lesson": ""}
            self.data["events"].append(ev)
            self.data["events"] = self.data["events"][-MAX_EVENTS:]
            self.save()
            logger.info(f"[表现分] {old} → {new}（{delta:+d}，{reason}）：{tidy(their_text)[:30]!r}")
            return ev

    def set_lesson(self, ev: Dict[str, Any], lesson: str):
        if not lesson:
            return
        with self._lock:
            ev["lesson"] = lesson
            self.save()
            logger.info(f"[表现分] 复盘：{lesson}")

    def lessons(self, n: int = LESSON_LIMIT) -> List[str]:
        return [e["lesson"] for e in self.data.get("events", []) if e.get("lesson")][-n:]

    def prompt_block(self) -> str:
        """给回复器看的那段（分数 + 刚才被扣的提醒 + 教训）"""
        score = int(self.data.get("score", 100))
        evs = self.data.get("events", [])
        negs = [e for e in evs if e.get("delta", 0) < 0][-PROMPT_EVENTS:]
        lines = [f"【你的表现分】{score}/100（满分 100；被扣分说明你刚才说错了话）。"]
        # 刚被扣分就**当场**提醒 —— 只看总分的话，从 100 掉到 94 依然是"分数还行"，
        # 挨骂那一下等于没反馈（2026-09-17 实测：被回「不可以」之后照样嘴硬）
        last = evs[-1] if evs else None
        if last and last.get("delta", 0) < 0:
            try:
                age = time.time() - float(last.get("ts") or 0)
            except Exception:
                age = 1e9
            if age <= RECENT_SECONDS:
                lines.append(f"⚠️ 就在刚才（{last.get('time', '')}），有人对你说的话回了"
                             f"「{last.get('they_said', '')}」，你被扣了 {abs(int(last.get('delta', 0)))} 分"
                             f"（{last.get('reason', '')}）。**这一轮说话注意点**，别再做同样的事。")
        if negs:
            lines.append("最近被扣分的几次：")
            for e in negs:
                lines.append(f"- 你说了「{e.get('bot_said', '')}」，然后有人说"
                             f"「{e.get('they_said', '')}」（{e.get('reason', '')}）")
        les = self.lessons()
        if les:
            lines.append("你自己复盘出来的教训（照着改）：")
            for one in les:
                lines.append(f"- {one}")
        if score <= 40:
            lines.append("你现在分数很低：**先老老实实回答问题**，别开玩笑、别抬杠、别乱接话，"
                         "拿不准就少说两句。")
        elif score <= 70:
            lines.append("分数不太好看：收敛一点，少贫嘴，把话说到点子上。")
        else:
            lines.append("分数还行，按平时的样子聊就行。")
        return "\n".join(lines)


# ---------------------------------------------------------------- 反思库
#
# 和 events 里那个 `lesson` 的区别（为什么要另开一个库）：
#   · events 是**流水账**，有 MAX_EVENTS 上限，附在上面的教训会随事件滚动被淘汰；
#   · 反思库是**长期错题本**：同一个错重复犯只累加 hits 不重复占位，
#     能由管理员手工添加（直接教它），并按 hits 排序稳定注入提示词。
#
# 数据落在 `data/reflections.json`，和另外两个文件一样走"原子写 + mtime 惰性重载"，
# 所以面板改完不用重启麦麦。

REFLECT_FILE = os.path.join(ROOT, "data", "reflections.json")
REFLECT_LIMIT = 8      # 每轮注入几条（别太多，白烧 token）
REFLECT_MAX = 300      # 库里最多留几条


class ReflectionStore:
    """反思库：机器人自己的错题本"""

    def __init__(self, path: str = REFLECT_FILE):
        self._lock = threading.Lock()
        self._mtime = 0.0
        self.path = path
        self.data: Dict[str, Any] = {"updated_at": "", "items": []}
        self.load()

    def _maybe_reload(self):
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            return
        if mt != self._mtime:
            logger.debug("[反思库] 检测到文件被外部修改，重新加载")
            self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data.update(d)
        except Exception:
            pass
        self.data.setdefault("items", [])
        try:
            self._mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime = 0.0

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
        except Exception as e:
            logger.error(f"[反思库] 存盘失败: {type(e).__name__}: {e}")

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """两条教训算不算"同一个错"

        不能只判等号：模型每次复盘的措辞都不一样（"别接话" / "少接话" /
        "不要接别人的话"），纯判等会让同一个毛病堆成几十条。
        """
        a, b = tidy(a), tidy(b)
        if not a or not b:
            return False
        if a == b or a in b or b in a:
            return True
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio() > 0.72

    def add(self, lesson: str, *, kind: str = "", scene: str = "",
            source: str = "auto", group: str = "") -> Dict[str, Any]:
        """加一条反思；和已有条目太像就只累加 hits，返回那条记录"""
        lesson = tidy(str(lesson or "")).strip("「」\"'。 ")[:80]
        if not lesson:
            return {}
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._maybe_reload()
            for it in self.data["items"]:
                if self._similar(it.get("lesson", ""), lesson):
                    it["hits"] = int(it.get("hits", 1)) + 1
                    it["last_ts"] = now
                    if scene:
                        it["scene"] = tidy(scene)[:80]
                    self.data["updated_at"] = now
                    self.save()
                    logger.info(f"[反思库] 同类教训第 {it['hits']} 次：{lesson}")
                    return it
            item = {
                "id": os.urandom(4).hex(),
                "ts": now,
                "last_ts": now,
                "source": source,              # auto=它自己复盘 / admin=管理员教的
                "kind": kind or "其它",
                "scene": tidy(scene)[:80],
                "lesson": lesson,
                "hits": 1,
                "enabled": True,
                "group": group or "",
            }
            self.data["items"].append(item)
            if len(self.data["items"]) > REFLECT_MAX:
                # 超限时先淘汰"最不重要"的：已停用的 → 命中少的 → 最久没用上的
                self.data["items"].sort(key=lambda x: (bool(x.get("enabled", True)),
                                                       int(x.get("hits", 1)),
                                                       str(x.get("last_ts", ""))))
                self.data["items"] = self.data["items"][-REFLECT_MAX:]
            self.data["updated_at"] = now
            self.save()
            logger.info(f"[反思库] 新增：{lesson}")
            return item

    def items(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        self._maybe_reload()
        rows = list(self.data.get("items", []))
        if enabled_only:
            rows = [r for r in rows if r.get("enabled", True)]
        # 犯得多的排前面（那是老毛病），同次数按最近用过
        rows.sort(key=lambda x: (int(x.get("hits", 1)), str(x.get("last_ts", ""))), reverse=True)
        return rows

    def remove(self, rid: str) -> bool:
        with self._lock:
            self._maybe_reload()
            before = len(self.data["items"])
            self.data["items"] = [i for i in self.data["items"] if i.get("id") != rid]
            if len(self.data["items"]) == before:
                return False
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()
            return True

    def toggle(self, rid: str, enabled: bool) -> bool:
        with self._lock:
            self._maybe_reload()
            for i in self.data["items"]:
                if i.get("id") == rid:
                    i["enabled"] = bool(enabled)
                    self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    self.save()
                    return True
            return False

    def prompt_block(self, n: int = REFLECT_LIMIT) -> str:
        """给回复器看的那段。命中次数多的优先 —— 那是它反复犯的毛病"""
        rows = self.items(enabled_only=True)[:n]
        if not rows:
            return ""
        lines = ["【反思库】你自己总结过的教训，这一轮务必避开："]
        for it in rows:
            hits = int(it.get("hits", 1))
            tag = f"（已经犯过 {hits} 次）" if hits > 1 else ""
            lines.append(f"- {it.get('lesson', '')}{tag}")
        return "\n".join(lines)


REFLECT = ReflectionStore()


# ---------------------------------------------------------------- 好感度存储

_FEEDING_FOODS = None


def feeding_foods() -> tuple:
    """读取实际食物目录，名称必须唯一且不少于365种。"""
    global _FEEDING_FOODS
    if _FEEDING_FOODS is None:
        path = os.path.join(os.path.dirname(__file__), "feeding_foods.json")
        with open(path, encoding="utf-8-sig") as handle:
            entries = json.load(handle)
        if not isinstance(entries, list) or len(entries) < 365:
            raise ValueError("投食目录少于365种")
        if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip() or not isinstance(item.get("category"), str) for item in entries):
            raise ValueError("投食目录格式无效")
        names = [item["name"].strip() for item in entries]
        if len(set(names)) != len(names) or "猫条" not in names or "吐司" not in names:
            raise ValueError("投食目录重复或缺少指定选项")
        _FEEDING_FOODS = tuple((item["name"].strip(), item["category"]) for item in entries)
    return _FEEDING_FOODS


class FavorStore:
    """按 QQ 全局持久化好感度；自然互动单独限速、记账，不重算旧数据。"""

    def __init__(self, path: str = FAV_FILE, initial: int = DEFAULT_FAV, cap: int = FAV_MAX):
        self._lock = threading.Lock()
        self._mtime = 0.0
        self.path = path
        self.initial = initial
        self.cap = cap        # 0 = 无上限
        self.data: Dict[str, Any] = {"updated_at": "", "users": {}}
        self.load()

    def _maybe_reload(self):
        """文件被外面改过（面板 / 管理员命令）就重读，别用内存里的旧数据盖回去"""
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            return
        if mt != self._mtime:
            logger.debug("[好感度] 检测到文件被外部修改，重新加载")
            self.load()

    def load(self):
        existed = os.path.isfile(self.path)
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data.update(d)
        except Exception:
            pass
        self.data.setdefault("users", {})
        # 兼容每日限额上线前已经领取的投食，重启即记住最近领取日期。
        from datetime import datetime, timedelta, timezone
        for record in self.data["users"].values():
            if not isinstance(record, dict) or record.get("feeding_day"):
                continue
            dates = []
            for event in record.get("history", []):
                if isinstance(event, dict) and event.get("source") == "feeding":
                    try:
                        dates.append(datetime.fromtimestamp(float(event["ts"]), timezone(timedelta(hours=8))).date().isoformat())
                    except (KeyError, TypeError, ValueError, OverflowError):
                        pass
            if dates:
                record["feeding_day"] = max(dates)
        try:
            self._mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime = 0.0
        if not existed:
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()

    def save(self, *, strict: bool = False):
        tmp = ""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                    dir=os.path.dirname(self.path), prefix=".favor-", suffix=".tmp") as f:
                tmp = f.name
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
        except Exception as e:
            logger.error(f"[好感度] 存盘失败: {type(e).__name__}: {e}")
            if strict:
                raise
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def feed_reward(self, uid: str, name: str, *, platform: str, group_id: str,
                    message_id: str, food: str) -> Dict[str, Any]:
        """同一实例锁内提交奖励和持久回执；失败回滚，协议重投不再加分。"""
        if not uid or not platform or not message_id or food not in {"投食", "吐司", "ts"}:
            raise ValueError("缺少真实投食消息信息")
        key = hashlib.sha256(json.dumps([platform, group_id, message_id, uid], ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            self._maybe_reload()
            receipts = self.data.get("feeding_receipts", {})
            if key in receipts:
                return {**receipts[key], "receipt_id":key, "duplicate": True}
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            existing = self.data.get("users", {}).get(str(uid), {})
            already_fed = existing.get("feeding_day") == today or any(
                event.get("uid") == str(uid) and event.get("day") == today
                for event in receipts.values() if isinstance(event, dict)) or any(
                item.get("source") == "feeding" and datetime.fromtimestamp(float(item.get("ts", 0)), timezone(timedelta(hours=8))).date().isoformat() == today
                for item in existing.get("history", []) if isinstance(item, dict))
            if already_fed:
                return {"daily_limit":True, "duplicate":False, "delta":0, "score":int(existing.get("score", self.initial))}
            snapshot, old_mtime = copy.deepcopy(self.data), self._mtime
            try:
                r = self.data["users"].setdefault(str(uid), {"name":"", "score":self.initial, "last_ts":0.0, "hits":0})
                old = int(r.get("score", self.initial))
                amount = secrets.randbelow(8) + 3
                catalog = feeding_foods()
                item, category = next(entry for entry in catalog if entry[0] == "吐司") if food == "吐司" else secrets.choice(catalog)
                new = max(0, old + amount)
                if self.cap > 0:
                    new = max(old, min(new, self.cap))
                now = time.time()
                reason = "吐司投食奖励" if food == "吐司" else "投食奖励"
                if name:
                    r["name"] = safe_name(name)[:32]
                r["score"], r["last_reason"] = new, reason
                r["feeding_day"] = today
                r["hits"] = int(r.get("hits", 0)) + 1
                self._note_change(r, old, new, reason, "feeding", now)
                receipt = {"delta":new-old, "score":new, "food":food, "ts":now, "delivered":False, "uid":str(uid), "platform":platform, "day":today, "item":item, "category":category}
                self.data.setdefault("feeding_receipts", {})[key] = receipt
                self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.save(strict=True)
                return {**receipt, "receipt_id":key, "duplicate":False}
            except Exception:
                self.data, self._mtime = snapshot, old_mtime
                raise

    def mark_feed_delivered(self, receipt_id: str) -> None:
        """发图回执另行确认；失败重试只补图，奖励仍由原消息回执去重。"""
        with self._lock:
            self._maybe_reload()
            receipts = self.data.get("feeding_receipts", {})
            if receipt_id not in receipts:
                raise ValueError("投食回执不存在")
            if receipts[receipt_id].get("delivered"):
                return
            snapshot, old_mtime = copy.deepcopy(self.data), self._mtime
            try:
                receipts[receipt_id]["delivered"] = True
                self.save(strict=True)
            except Exception:
                self.data, self._mtime = snapshot, old_mtime
                raise

    def rec(self, uid: str) -> Dict[str, Any]:
        self._maybe_reload()
        return self.data["users"].setdefault(
            str(uid), {"name": "", "score": self.initial, "last_ts": 0.0, "hits": 0})

    def get(self, uid: str) -> int:
        if not uid:
            return self.initial
        return int(self.rec(uid).get("score", self.initial))

    @staticmethod
    def _note_change(r: Dict[str, Any], old: int, new: int, reason: str,
                     source: str, now: float) -> None:
        """只记录实际变化；旧账没有的历史不补造。"""
        delta = new - old
        if not delta:
            return
        date = time.strftime("%Y-%m-%d", time.localtime(now))
        daily = r.get("daily") or {}
        if daily.get("date") != date:
            daily = {"date": date, "gain": 0, "loss": 0, "natural_gain": 0}
        key = "gain" if delta > 0 else "loss"
        daily[key] = int(daily.get(key, 0)) + abs(delta)
        if source == "interaction" and delta > 0:
            daily["natural_gain"] = int(daily.get("natural_gain", 0)) + delta
        r["daily"] = daily
        history = list(r.get("history") or [])
        history.append({"ts": now, "delta": delta, "score": new,
                        "reason": reason, "source": source})
        r["history"] = history[-30:]

    def record_interaction(self, uid: str, name: str, text: str, *,
                           aimed: bool, message_id: str = "", group_id: str = "",
                           mentioned: bool = False, quoted: bool = False,
                           now: Optional[float] = None) -> Tuple[int, int, str]:
        """统一锁内判分/冷却/去重/日上限；返回当前分、实际变动、原因。"""
        if not uid or not aimed:
            return self.get(uid), 0, ""
        t = clean(text)
        if not t or _looks_like_command(text) or (
                len(t) <= 12 and any(w in t for w in FAV_ASK + REL_ASK)):
            return self.get(uid), 0, ""
        delta, reason = favor_delta(text, mentioned_bot=mentioned,
                                   quoted_bot=quoted, aimed_at_bot=aimed)
        if not delta:
            return self.get(uid), 0, ""
        ts = time.time() if now is None else float(now)
        with self._lock:
            self._maybe_reload()
            r = self.data["users"].setdefault(str(uid),
                {"name": "", "score": self.initial, "last_ts": 0.0, "hits": 0})
            old = int(r.get("score", self.initial))
            seen = [v for v in r.get("interaction_seen", [])
                    if ts - float(v.get("ts", 0)) < 86400][-63:]
            mid = str(message_id or "")
            # 只去重协议重复投递；相同内容的新消息正常参与计分。
            if any(mid and v.get("id") == mid and v.get("group") == str(group_id) for v in seen):
                return old, 0, ""
            last_key = "last_positive_interaction_ts" if delta > 0 else "last_negative_interaction_ts"
            cooldown = FAV_POSITIVE_COOLDOWN if delta > 0 else FAV_COOLDOWN
            last_ts = float(r.get(last_key, 0) or 0)
            if not last_ts and not any(k in r for k in ("last_positive_interaction_ts", "last_negative_interaction_ts")):
                last_ts = float(r.get("last_ts", 0) or 0)
            if last_ts and ts - last_ts < cooldown:
                return old, 0, ""
            date = time.strftime("%Y-%m-%d", time.localtime(ts))
            new = max(0, old + delta)
            if self.cap > 0:
                new = min(new, self.cap)
            if new == old:
                return old, 0, ""
            if name:
                r["name"] = safe_name(name)[:32]
            r.update(score=new, last_ts=ts, last_reason=reason)
            r[last_key] = ts
            r["hits"] = int(r.get("hits", 0)) + 1
            r["interaction_count"] = int(r.get("interaction_count", 0)) + 1
            r.setdefault("first_interaction_ts", ts)
            r["last_interaction_ts"] = ts
            # 只统计部署后、确实结算的互动日期，不从旧 hits 反推。
            cutoff = time.strftime("%Y-%m-%d", time.localtime(ts - 89 * 86400))
            previous_days = r.get("interaction_days") or []
            r["interaction_day_count"] = int(r.get("interaction_day_count", len(previous_days))) + (date not in previous_days)
            r["interaction_days"] = sorted(set(
                [str(d) for d in r.get("interaction_days", []) if str(d) >= cutoff] + [date]))[-90:]
            seen.append({"id": mid, "group": str(group_id), "ts": ts})
            r["interaction_seen"] = seen[-64:]
            self._note_change(r, old, new, reason, "interaction", ts)
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            self.save()
            return new, new - old, reason

    def bump(self, uid: str, name: str, delta: int, reason: str) -> int:
        """改好感度；返回改完的值。delta=0 时只更新名字"""
        if not uid:
            return self.initial
        with self._lock:
            self._maybe_reload()
            r = self.data["users"].setdefault(
                str(uid), {"name": "", "score": self.initial, "last_ts": 0.0, "hits": 0})
            if name:
                r["name"] = str(name)[:32]
            old = int(r.get("score", self.initial))
            new = max(0, old + delta)
            if self.cap and self.cap > 0:
                new = min(new, self.cap)
            r["score"] = new
            r["last_ts"] = time.time()
            if delta:
                r["hits"] = int(r.get("hits", 0)) + 1
                r["last_reason"] = reason
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()
            if delta:
                logger.info(f"[好感度] {r['name'] or uid}: {old} → {new}（{delta:+d}，{reason}）")
            return new

    def mark_shunned(self, uid: str) -> None:
        """记一下"刚刚凶过他"的时间（给翻脸回复做冷却）

        单独一个方法而不是复用 bump(…, 0, …)：bump 会无条件刷新 `last_ts`，
        那是"好感度变动冷却"用的时间戳，被翻脸回话顺手刷新的话，
        正常交流的加分节奏也会跟着乱。这里只写一个自己的字段，别的都不碰。
        """
        if not uid:
            return
        with self._lock:
            self._maybe_reload()
            r = self.data["users"].setdefault(
                str(uid), {"name": "", "score": self.initial, "last_ts": 0.0, "hits": 0})
            r["last_shun_ts"] = time.time()
            self.save()

    # ---- 管理员操作（面板 / QQ 命令）----
    def _admin_set_unlocked(self, uid: str, value: int, name: str = "") -> int:
        r = self.data["users"].setdefault(str(uid),
            {"name": "", "score": self.initial, "last_ts": 0.0, "hits": 0})
        if name:
            r["name"] = str(name)[:32]
        v = max(0, int(value))
        if self.cap > 0:
            v = min(v, self.cap)
        now = time.time()
        self._note_change(r, int(r.get("score", self.initial)), v, "管理员调整", "admin", now)
        r.update(score=v, last_ts=now, last_reason="管理员调整")
        self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return v

    def admin_set(self, uid: str, value: int, name: str = "") -> int:
        with self._lock:
            self._maybe_reload()
            v = self._admin_set_unlocked(uid, value, name)
            self.save()
            return v

    def admin_add(self, uid: str, delta: int, name: str = "") -> int:
        with self._lock:
            self._maybe_reload()
            old = int(self.data["users"].get(str(uid), {}).get("score", self.initial))
            v = self._admin_set_unlocked(uid, old + int(delta), name)
            self.save()
            return v

    def admin_reset(self, uid: str = "", name: str = "") -> int:
        """只重置分数，保留身份、称呼、真实互动与变更记录。"""
        if uid:
            return self.admin_set(uid, self.initial, name)
        with self._lock:
            self._maybe_reload()
            for target_uid in self.data["users"]:
                self._admin_set_unlocked(target_uid, self.initial)
            self.save()
            return self.initial

    def lowest(self, n: int = 10) -> List[Dict[str, Any]]:
        rows = [{"user_id": k, **v} for k, v in self.data["users"].items()]
        rows.sort(key=lambda x: (x.get("score", self.initial), x.get("name", "")))
        return rows[:n]

    def prompt_block(self, uid: str, name: str, asking: bool, alive: bool,
                     is_master: bool = False) -> str:
        """给本人这一轮的「好感度 / 称呼」提示词。

        Args:
            uid: 说话人的 ID。
            name: 说话人的昵称。
            asking: 他是不是在问好感度（问的时候只报数字）。
            alive: 是否还没翻脸。
            is_master: **这个人就是机器人真正的主人**（`behavior_score.admin_qq` 里的人）。
                2026-10-11 新增：原来那段称呼约束只写「主人是唯一的一个人」，
                却没告诉模型**谁是那个人** —— 模型于是对谁都喊主人（实测
                `主人你管她叫ak干嘛` / `主人你还会穿越时间啊`）。现在把主人身份
                明确传进来：是他本人就允许叫，不是就一律禁止。
        """
        cur = self.get(uid)
        who = name or uid or "这个人"
        if asking:
            # 2026-09-19：用户连着报了几轮价（"我要两百""补你二十"），模型就真跟着改口。
            # 数字是账本里的，不许谈 —— 这条得写死。
            return (f"【好感度】有人（{who}）在问你对他的好感度。**只许报这个数：{cur}**"
                    f"（初始 100，改不了）。\n"
                    f"这个数字是**账本里记着的，不是谈出来的**：不许讨价还价、不许说涨一点、"
                    f"不许跟着他报的数字改口（我要两百 / 凑个整 这类一律不认），"
                    f"也不许自己编一个新数字。一句话说清就行，别解释数字怎么来的。")
        if not alive or cur < LOW_FAV:
            return FAV_HOSTILE_BLOCK.format(who=who, cur=cur)
        # 按分级表从高到低匹配（2026-09-18：10 档 + 翻脸档）
        for threshold, tpl in FAV_TIERS:
            if cur >= threshold:
                body = tpl.format(who=who, cur=cur) if tpl else ""
                if body:
                    # 2026-10-11：三条统一底线，对所有档位都生效。
                    # ① 数字直接给模型，它就容易把数字挂嘴边、甚至跟着用户报的价改口
                    #    （2026-09-19 实测「我要两百」那轮）；
                    # ② 普通互损与恶意挑衅分开判断；2026-10-19 用户允许真生气时尖锐回怼。
                    # ③ 称呼：模型分不清"熟人"和"主人"，对**所有**高好感度群友都喊
                    #    「主人」（实测 `主人你管她叫ak干嘛` / `主人你还会穿越时间啊`）。
                    #    主人是**唯一一个人** —— 所以这里按 `is_master` 分两种写法：
                    #    是他本人 = 明确允许叫主人；不是他 = 一律禁止（并且不再给
                    #    "「主人」这个词只属于你真正的那一个主人" 这种模棱两可的说法，
                    #    模型拿到那种话只会觉得"我不是有个主人吗，那他应该就是"）。
                    if is_master:
                        body += ("\n（这个数字别主动挂在嘴边，他问起来再照实说。）"
                                 "\n（普通互损看双方是否接得住；确有恶意挑衅时，可以针对他实际的言行尖锐回怼、"
                                 "讽刺或嫌弃。不编黑料、不以外貌或隐私作武器，不因亲近就强行忍让。）"
                                 "\n（⚠️ 称呼：**上面这个人就是你唯一的主人本人** —— "
                                 "你可以、也只可以对他一个人用「主人」。对群里其他人一律"
                                 "不许喊主人，也不许喊老公/老婆/男朋友这种。）")
                    else:
                        body += ("\n（这个数字别主动挂在嘴边，他问起来再照实说。）"
                                 "\n（普通互损看双方是否接得住；确有恶意挑衅时，可以针对他实际的言行尖锐回怼、"
                                 "讽刺或嫌弃。不编黑料、不以外貌或隐私作武器，不因亲近就强行忍让。）"
                                 "\n（⚠️ 称呼：**上面这个人是群友，不是你的主人。**"
                                 "对**他**、以及对群里其他任何人，都**不准**喊「主人」、"
                                 "也不准喊老公/老婆/男朋友这种；直接叫他的名字或者用「你」。"
                                 "你的主人另有其人，是特定的一个，只在跟他本人说话时才用「主人」"
                                 "这个称呼。）")
                body += ("\n关系决定熟悉与信任，不决定你是否同意他。你有自己的偏好；"
                         "接梗可以得意、嘴欠，真生气也可以有锋芒，强度看这次言行和前文，也可以不接。对方认真求助时再认真，"
                         "不要因分高就奉承、护短或虚构恋爱关系。")
                rec = self.rec(uid)
                days = len(rec.get("interaction_days") or [])
                if days:
                    body += f"\n近期已有 {days} 个实际互动日；按真实相处经历说话，不编造共同往事。"
                return body
        return ""

    def relation_label(self, uid: str) -> str:
        """问"我们是什么关系"时按表回答（2026-09-18 用户要求）

        只给"群友/朋友/熟人"这一类的说法 —— 别让它说出"男朋友""老婆"这种，
        好感度再高也是群里认识的人。
        """
        cur = self.get(uid)
        if cur < LOW_FAV:
            return REL_HOSTILE
        for threshold, label in REL_TIERS:
            if cur >= threshold:
                return label
        return "普通群友"


SCORE = ScoreStore()
FAVOR = FavorStore()

# ---------------------------------------------------------------- 身份 / 称呼 / CG（2026-09-20）

# 提示词单独放一个 json，统一面板「CG 与身份」页编辑；改完不用重启（下面按 mtime 热重载）
CG_FILE = os.path.join(ROOT, "data", "cg_prompts.json")
CG_IMG_DIR = os.path.join(ROOT, "data", "cg")

# 2026-10-13：正在画的 CG（进程内防重入）。
# 豆包出一张要 60~70 秒，比 CG 冷却（cooldown_seconds=60）还长 ——
# 上一张还没画完冷却就过了，同一档会被后面的消息再触发一次，群里就连出两张
# （实测：09:48:24 触发一次、09:49:32 又触发一次，同一个人同一张 lv2，出了两张）。
# 这里记下「(uid, level) 正在画」，重复触发直接跳过。
CG_INFLIGHT: set = set()

# 豆包网页版全局串行锁：同一个登录 profile 不能同时开两个浏览器（见 _doubao_cg）。
_DOUBAO_LOCK = threading.Lock()


class PromptStore:
    """`data/cg_prompts.json` 的读取（mtime 热重载，和另外两个存储一个路子）"""

    def __init__(self, path: str = CG_FILE):
        self.path = path
        self._mtime = -1.0
        self.data: Dict[str, Any] = {}

    def _maybe_reload(self) -> None:
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            return
        if m == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f) or {}
            self._mtime = m
            logger.info("[CG] 提示词已载入/重载")
        except Exception as e:
            logger.warning(f"[CG] 提示词读取失败，继续用旧的: {type(e).__name__}: {e}")

    def get(self, *keys: str, default: Any = None) -> Any:
        self._maybe_reload()
        cur: Any = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur


PROMPTS = PromptStore()


_AT_ANY = re.compile(r"@[^\s@]{0,32}")


def _strip_mentions(text: str) -> str:
    """剥掉消息里的 @提及（`@<昵称:QQ>` / `@示例助手` / `@示例助手(你)` / `@123456` 各种形态）

    2026-10-10 修：原来只靠 `clean()` 里的 `@<...>` 正则，而适配器实际拼出来的常常是
    `@示例助手(你)` 这种**不带尖括号**的形态 —— 剥不掉，两头都出事：
      ① 用户习惯性 @ 一句，`@示例助手 A` 以 @ 开头 → 字母匹配不上 → 选身份的答案被吞；
      ② 反过来，菜单发出后 5 分钟内 `@示例助手 今天天气` 里的「示例助手」被当成在选身份
         （示例助手还是机器人自己的昵称，群里天天在 @）。
    """
    t = str(text or "")
    t = re.sub(r"@<[^>]*>", " ", t)
    return _AT_ANY.sub(" ", t)


def safe_name(name: Any) -> str:
    """昵称洗净：去掉控制字符/不可打印字符

    2026-10-10 修：日志里出现过 `\b%ĀĀ\u0007Ù\n\u001a\u0012\u0018某科学的超威蓝猫`
    这种带二进制垃圾的昵称 —— 它会被写进日志、写进提示词、写进 @ 文案。
    """
    t = str(name or "")
    return "".join(ch for ch in t if ch == " " or ch.isprintable()).strip()


def _norm(text: str) -> str:
    """只留中英文数字，用于"整句是不是就是这个身份名"的精确比较"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", str(text or "")).upper()


def _match_identity(text: str) -> Optional[str]:
    """把用户的回话对上身份名（A / 猫娘 / b / 不选 …）

    只在"有未过期的身份菜单"时才调用 —— 否则群里正常说一句"我要选 A 座"
    也会被当成在选身份。

    2026-10-10 修了两个真 bug（都是"回话被吞 / 被误认"）：
      ① label 原来是 `startswith` —— 菜单发出后的 5 分钟里，用户随口一句
         「B站有活动」「CG 真好看」都会被当成选了 B / C，还会把正常回复一起取消。
         改成**整句精确匹配**（剥掉标点后相等）。
      ② 名字/称号/别名原来是 `in` —— 「@示例助手 今天天气」里的「示例助手」会命中身份名。
         改成：整句就是它，或者**很短的一句话以它收尾**（"我选猫娘"），
         并且比较前先剥掉 @提及。
    """
    t = clean(_strip_mentions(text))
    if not t:
        return None
    core = _norm(t)
    if not core:
        return None
    for name, cfg in (_identity_options() or {}).items():
        cfg = cfg or {}
        label = _norm(str(cfg.get("label") or ""))
        if label and core == label:
            return name
        cands = [str(name or ""), str(cfg.get("title") or "").strip()]
        cands += [str(a) for a in (cfg.get("aliases") or [])]
        for c in cands:
            cc = _norm(c)
            if not cc:
                continue
            # 整句就是它（"猫娘" / "大肥鱼"），或者很短的一句以它收尾（"我选猫娘"）
            if core == cc or (len(core) <= len(cc) + 3 and core.endswith(cc)):
                return name
    # 「不选」的代价是**倒扣好感度**，所以这里一律要求整句就是那个词，不做"以它收尾"的
    # 宽松匹配 —— 不然群里一句「我不要」「那算了啊」都会被判成放弃选择并扣分。
    for w in (PROMPTS.get("identity", "decline_words", default=[]) or []):
        ww = _norm(str(w or "").strip())
        if ww and core == ww:
            return "不选"
    return None


def _identity_options() -> Dict[str, Any]:
    opts = PROMPTS.get("identity", "options", default={})
    return opts if isinstance(opts, dict) else {}


def looks_like_identity_answer(text: str) -> bool:
    """这条消息**看起来像在回答身份菜单**吗（不管菜单过没过期）。

    2026-10-11 用户要求给身份选择加时间限制并「顺便提示错过了怎么办」——
    但光有超时不够：用户超时后回了个「A」，如果代码直接不认、又不给个说法，
    他会以为机器人坏了（旧行为就是这样：`_match_identity` 只在菜单没过期时被调用，
    过期后「A」被当成普通消息丢给模型，模型答非所问）。

    所以超时后还要能识别出「你这句是在选身份」——识别出来才能回一句
    「过期了，再 @ 我说一次『身份』」。这里复用 `_match_identity` 的匹配口径
    （整句精确 / 短句收尾），命中任意选项或选项字母即算。

    Args:
        text: 用户原始消息（含 @ 也没关系，内部会剥）。

    Returns:
        bool: 像在选身份则 ``True``。
    """
    return _match_identity(text) is not None


#: 改名请求关键词前允许出现的引导词（“以后/那就/请”之类）。
#: 2026-10-24：关键词前还挂着别的内容（“十分钟后”“记得”“到点”），说明这句不是
#: 在起称呼 —— 实测「@示例角色 十分钟后叫我睡觉」被抠成称呼「睡觉」，
#: 群里当场看傻子。宁可漏认（放给模型自由回），也不能把提醒请求当成改名。
_CALLNAME_LEADINS = ("以后", "今后", "往后", "那就", "就叫", "就", "请", "那", "嗯", "啊", "呀", "吧", "嘛", "可以")


def _parse_callname(text: str) -> str:
    """从「@bot 以后叫我xxx」里抠出 xxx

    只有**整句就是一个改名请求**时才认：关键词前面只允许空或者
    `_CALLNAME_LEADINS` 里的引导词（剥完为止）。前面还有别的内容 → 返回 ""
    （调用方据此放行给模型，不当成称呼处理）。
    """
    t = clean(text)
    for kw in (PROMPTS.get("callname", "keywords", default=[]) or []):
        kw = str(kw or "").strip()
        if not kw or kw not in t:
            continue
        head, _, tail = t.partition(kw)
        head = head.strip(" \t@,，。.!！?？~～…—-_/、：:")
        changed = True
        while changed:                      # 反复剥引导词：“那就以后叫我X”也要认
            changed = False
            for lead in _CALLNAME_LEADINS:
                if lead and head.endswith(lead):
                    head = head[: -len(lead)].strip(" \t@,，。.!！?？~～…—-_/、：:")
                    changed = True
        if head:
            return ""                       # 关键词前还有别的内容 → 不是起称呼
        return tail.strip().strip("「」『』\"'“”,，。.!！?？~～ ")
    return ""


def _callname_problem(nick: str) -> str:
    """返回空串 = 合法，否则返回原因"""
    if not nick:
        return "空的"
    try:
        limit = int(PROMPTS.get("callname", "max_len", default=12) or 12)
    except (TypeError, ValueError):
        limit = 12
    if len(nick) > limit:
        return f"超过 {limit} 个字"
    for ch in (PROMPTS.get("callname", "banned_chars", default=[]) or []):
        if ch and ch in nick:
            return f"含有 {ch}"
    return ""


def _cg_level_for(score: int) -> int:
    """这个好感度对应第几张 CG（0 = 还没到门槛）"""
    if not PROMPTS.get("cg", "enabled", default=False):
        return 0
    try:
        start = int(PROMPTS.get("cg", "start_favor", default=500) or 500)
        step = max(1, int(PROMPTS.get("cg", "step", default=150) or 150))
    except (TypeError, ValueError):
        start, step = 500, 150
    if score < start:
        return 0
    return (score - start) // step + 1


def _cg_stage(level: int) -> Dict[str, Any]:
    stages = PROMPTS.get("cg", "stages", default=[]) or []
    picked: Dict[str, Any] = {}
    for st in stages:
        if not isinstance(st, dict):
            continue
        try:
            if int(st.get("level", 0)) == level:
                return st
        except (TypeError, ValueError):
            continue
        picked = st
    return picked          # 超出列表就复用最后一张，别让高阶没图


def _cg_size(identity: str) -> str:
    """身份专属尺寸（大肥鱼那套是 1280x720 的 16:9）"""
    over = (_identity_options().get(identity) or {}).get("cg") or {}
    return str((over if isinstance(over, dict) else {}).get("size") or "")


def _cg_negative(identity: str) -> str:
    """身份专属反向词（大肥鱼那套反向词更细，防崩坏）"""
    over = (_identity_options().get(identity) or {}).get("cg") or {}
    return str((over if isinstance(over, dict) else {}).get("negative") or "")


def _cg_scene(identity: str, level: int) -> Tuple[str, str]:
    """身份专属的「场景追加词」，按档位轮换

    2026-09-20 用户给了大肥鱼的三套追加词（干饭名场面 / 电脑摸鱼 / 委屈傲娇）。
    轮着用 —— 否则每张里程碑图都长得一模一样。
    """
    opt = _identity_options().get(identity) or {}
    over = opt.get("cg") if isinstance(opt.get("cg"), dict) else {}
    # ⚠️ 场景词挂在 `options.<身份>.cg.scenes` 下面（不是 options.<身份>.scenes）——
    #    第一版读错层级，结果永远取不到场景（探针里三条断言当场失败）。
    scenes = (over or {}).get("scenes") or opt.get("scenes") or {}
    if not isinstance(scenes, dict) or not scenes:
        return "", ""
    # 按**配置里写的顺序**轮换，别 sorted() —— 中文排序是 Unicode 码位序（委 < 干 < 电），
    # 会把人手动排好的"干饭→摸鱼→委屈"打乱。
    names = list(scenes.keys())
    name = names[(max(1, _int_of(level, 1)) - 1) % len(names)]
    return name, str(scenes.get(name) or "")


def _cg_prompt(level: int, identity: str) -> Tuple[str, Dict[str, Any]]:
    """这一档 CG 的作图提示词

    2026-09-20：加了**身份专属提示词**（`options.<身份>.cg.prompt`）。大肥鱼那套是用户
    自己写的完整形象词（鲸鱼娘/女仆装/白米饭…），比通用模板 + "cat ears" 这种 hint
    还原度高得多；没写专属词的身份继续走通用模板。
    """
    stage = _cg_stage(level)
    over = (_identity_options().get(identity) or {}).get("cg") or {}
    over = over if isinstance(over, dict) else {}
    base = str(over.get("prompt") or PROMPTS.get("cg", "base_prompt", default="") or "")
    hints = PROMPTS.get("cg", "identity_hint", default={}) or {}
    hint = str(hints.get(identity or "", hints.get("", "")) or "")
    stage_txt = str(stage.get("prompt") or PROMPTS.get("cg", "stage_fallback", default="") or "")
    scene_name, scene_txt = _cg_scene(identity, level)
    # 2026-09-22 优化：`{stage}` / `{scene}` 允许**写进模板中间**。
    # 原因：身份专属提示词（大肥鱼那套）本身就 50+ 词，原来一律把剧情/场景**追加在尾巴上**，
    # 而文本编码器有长度窗口（CLIP 系 77 token，本会话实测排在后面的风格词直接被丢），
    # 于是"这一档的剧情"和"场景轮换"很可能压根没生效。现在模板里写占位符就插在中间，
    # 没写占位符的老模板照旧追加在后面（向后兼容）。
    try:
        prompt = base.format(identity_hint=hint, stage=stage_txt, scene=scene_txt,
                             level=level, name=identity or "")
    except (KeyError, IndexError, ValueError):
        prompt = f"{base} {hint}"
    if "{stage}" not in base and stage_txt:
        prompt = f"{prompt} {stage_txt}"
    if scene_txt and "{scene}" not in base:
        prompt = f"{prompt} {scene_txt}"
    prompt = " ".join(prompt.split())
    # 没写 {scene} 的身份（猫娘/示例助手）会把占位符留成空串 → 清掉「, ,」这种空洞
    prompt = re.sub(r",(\s*,)+", ",", prompt)
    # 2026-10-11：柚子社（yuzusoft）视觉小说 CG 风格层。
    # ⚠️ 为什么要有这个：写了 `options.<身份>.cg.prompt` 的身份（猫娘/示例助手/鱼娘）**整条
    #    提示词都被自己的专属词替换掉了**，`cg.base_prompt` 里那套柚子社画风词对它们
    #    **一个字都不生效** —— 于是"按柚子社 CG 重写"只作用在没写专属词的身份上。
    #    用户这轮的要求是「参考柚子社的 cg，全部重写场景提示词，**不要动人物提示词**」：
    #    不动 JSON 里的人物词，改在**组装层**把统一的画风前缀拼到最前面（编码器对靠前的
    #    词权重更高，画风词本来就该在最前），这样所有身份都能吃到同一套柚子社质感。
    #    幂等：已经带了（含 "yuzusoft" / "visual novel CG"）就不再拼。
    style_prefix = str(PROMPTS.get("cg", "style_prefix", default="") or "")
    if style_prefix and "yuzusoft" not in prompt.lower() and "visual novel cg" not in prompt.lower():
        # 人物提示词自己开头也是 "masterpiece, best quality, anime cel shading, ..."，
        # 直接拼会出现「masterpiece, best quality, ... masterpiece, best quality, anime cel shading」
        # 这种重复。所以拼之前把人物词开头那几个**质量/基础画风标签**剥掉（它们已经被前缀覆盖）。
        stripped = prompt
        for lead in ("masterpiece", "best quality", "anime cel shading", "clean line art",
                     "flat color", "subtle film grain"):
            stripped = re.sub(rf"^\s*{re.escape(lead)}\s*,?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r",(\s*,)+", ",", stripped).lstrip(", ").strip()
        prompt = f"{style_prefix}, {stripped}" if stripped else style_prefix
        prompt = re.sub(r",(\s*,)+", ",", prompt)
        prompt = " ".join(prompt.split())
    out = dict(stage or {})
    if scene_name:
        out["scene"] = scene_name
    return prompt, out


def _siliconflow_key() -> str:
    """硅基流动的 key 从麦麦的 model_config.toml 里读（CG 页没单独填就用这个）"""
    try:
        import tomllib
        p = os.path.join(ROOT, "config", "model_config.toml")
        with open(p, "rb") as f:
            cfg = tomllib.load(f)
        for prov in cfg.get("api_providers", []):
            if str(prov.get("name") or "") == "硅基流动":
                return str(prov.get("api_key") or "")
    except Exception:
        pass
    return ""


def _doubao_cg(level: int, identity: str, prompt: str, dest: str) -> Tuple[bool, str]:
    """CG 走豆包网页版（Seedream 4.5）生成（2026-10-12 接入，2026-10-13 全量化）。

    2026-10-13 用户定稿「全用豆包」：**所有档位/所有身份**都走豆包，硅基流动只当
    兜底。有参考图的身份（示例角色/鱼娘）垫图锁形象；没参考图的（猫娘）走纯文生图，
    指令改为「严格按英文提示词作画」。subprocess 跑 doubao_cg.py（headless，
    登录态在 data/doubao_profile）。
    """
    db = PROMPTS.get("cg", "doubao", default={}) or {}
    if not db.get("enabled"):
        return False, "doubao-disabled"
    if level < int(db.get("from_level") or 1):
        return False, "level-below"
    # 2026-10-13：豆包网页版用**同一个登录 profile**（data/doubao_profile），
    # 同时起两个 chromium 会互相抢锁 → 第二个必然失败（实测：一个人正在出图时，
    # 另一个人的请求就掉去走硅基流动兜底了，出的图不是豆包那套）。
    # 所以这里串行：拿不到锁就排队等，等太久才放弃（让上层回落兜底）。
    if not _DOUBAO_LOCK.acquire(timeout=180):
        return False, "doubao-busy"
    try:
        return _doubao_cg_locked(level, identity, prompt, dest, db)
    finally:
        _DOUBAO_LOCK.release()


def _doubao_cg_locked(level: int, identity: str, prompt: str, dest: str,
                      db: dict) -> Tuple[bool, str]:
    """真正跑豆包的部分（调用方已持锁）。"""
    script = str(db.get("script") or "")
    if not os.path.exists(script):
        return False, "no-script"
    ref = str((db.get("ref") or {}).get(identity) or "")
    if ref and not os.path.exists(ref):
        ref = ""                                           # 参考图丢了 → 退纯文生图
    timeout = int(db.get("timeout") or 300)
    if ref:
        # 豆包对中文理解好，指令 = 锁形象 + 组装好的场景词
        # 2026-10-13：截断 600 → 1800。风格前缀（yuzusoft 那串）就占 ~570 字符，
        # 600 截断把 {stage} 剧情词全切了 —— 豆包只能自由发挥场景（实测 lv11 出来
        # 是学校走廊）。豆包输入框吃几千字符没问题。
        instruction = ("保持参考图中人物的外貌完全不变。以她为主角生成一张日系恋爱游戏CG，"
                       "画面为 16:9 宽屏横版构图（横向画幅，人物完整呈现不被裁切），"
                       "⚠️ 画面里只能出现她一个人：绝对不要双胞胎/镜像复制/第二个女孩，"
                       "⚠️ 她手上不要拿法杖、魔杖、手杖或任何杖类道具，画面里也不要有法杖"
                       "（空手或自然手势即可），"
                       "高质量，动漫赛璐璐风格，safe for work。" + prompt[:1800])
    else:
        # 无垫图：严格按身份提示词作画（形象全靠文字描述）
        instruction = ("请严格按照下面这段英文提示词作画，以她为主角生成一张日系恋爱游戏CG，"
                       "画面为 16:9 宽屏横版构图（横向画幅，人物完整呈现不被裁切），"
                       "⚠️ 画面里只能出现她一个人：绝对不要双胞胎/镜像复制/第二个女孩，"
                       "⚠️ 她手上不要拿法杖、魔杖、手杖或任何杖类道具，画面里也不要有法杖"
                       "（空手或自然手势即可），"
                       "人物外貌、服装、发型必须严格符合提示词描述，"
                       "高质量，动漫赛璐璐风格，safe for work。" + prompt[:1800])
    py = sys.executable
    try:
        import subprocess as sp
        r = sp.run([py, script, "gen", ref, instruction, dest],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="ignore", timeout=timeout, cwd=os.path.dirname(script))
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 20000:
            from PIL import Image as _PILImage
            # 2026-10-19 双保险：豆包偶尔还没出图，就把上传的参考图当结果返回
            # （脚本侧已只认 rc_gen_image 路径；这里再按尺寸挡一层）。
            # 尺寸和参考图完全一样 = 参考图本身，判失败 → 上层回落到硅基流动，
            # 绝不把参考图裁成 16:9 发到群里（00:29 群里收到的就是这种图）。
            if ref and os.path.exists(ref):
                try:
                    _out_size = _PILImage.open(dest).size
                    _ref_size = _PILImage.open(ref).size
                    if _out_size == _ref_size:
                        logger.warning(f"[CG] 豆包返回的是参考图（{_out_size}），判失败")
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
                        return False, "doubao-ref-image"
                except Exception as e:                          # noqa: BLE001
                    logger.warning(f"[CG] 参考图比对失败（继续用下载结果）: {type(e).__name__}: {e}")
            # 只对 <720 的小图超分（Seedream 4.5 本来就出高清，不用放大）
            _w = _PILImage.open(dest).size[0] if os.path.exists(dest) else 0
            if _w < 720:
                try:
                    up_exe = os.path.join(os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.dirname(ROOT)))),
                        "tools", "realesrgan", "realesrgan-ncnn-vulkan.exe")
                    if os.path.exists(up_exe):
                        tmp_in = dest + ".in.png"
                        os.replace(dest, tmp_in)
                        sp.run([up_exe, "-i", tmp_in, "-o", dest,
                                "-n", "realesr-animevideov3", "-s", "4"],
                               capture_output=True, timeout=120,
                               cwd=os.path.dirname(up_exe))
                        os.remove(tmp_in)
                except Exception as e:                          # noqa: BLE001
                    logger.warning(f"[CG] 超分失败（用原图）: {e}")
            # 统一 16:9：不是 16:9 就裁剪（偏上保留人物头部）
            im = _PILImage.open(dest)
            w, h = im.size
            if abs(w / h - 16 / 9) > 0.02:
                if w / h > 16 / 9:                              # 太宽 → 裁左右
                    nw = int(h * 16 / 9)
                    x0 = (w - nw) // 2
                    im = im.crop((x0, 0, x0 + nw, h))
                else:                                           # 太高 → 裁上下
                    nh = int(w * 9 / 16)
                    y0 = max(0, int((h - nh) * 0.35))
                    im = im.crop((0, y0, w, y0 + nh))
                im.save(dest)
            return True, "doubao"
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        info = tail[-1][:120] if tail else f"rc={r.returncode}"
        return False, f"doubao-fail: {info}"
    except sp.TimeoutExpired:
        return False, "doubao-timeout"
    except Exception as exc:                                # noqa: BLE001
        return False, f"doubao-err: {type(exc).__name__}: {exc}"


def _fetch_cg_image(prompt: str, dest: str, size: str = "", negative: str = "") -> Tuple[bool, str]:
    """阻塞式出图（放线程里跑）：成功就把图写到 dest，返回 (ok, 说明)

    size/negative 留空就用 `cg` 全局的；身份专属的（比如大肥鱼的 16:9 + 那串反向词）
    由调用方传进来。
    """
    import urllib.parse
    import urllib.request
    cfg = PROMPTS.get("cg", default={}) or {}
    provider = str(cfg.get("provider") or "pollinations")
    width = int(cfg.get("width") or 1024)
    height = int(cfg.get("height") or 1024)
    if size and "x" in str(size).lower():
        w, _, h = str(size).lower().partition("x")
        if w.strip().isdigit() and h.strip().isdigit():
            width, height = int(w), int(h)
    model = str(cfg.get("model") or "flux")
    neg = str(negative or cfg.get("negative") or "")
    if provider == "pollinations" and neg:
        # pollinations 没有 negative 参数，只能塞进提示词
        prompt = f"{prompt}, avoid: {neg}"
    try:
        if provider == "siliconflow":
            prov = (cfg.get("providers", {}) or {}).get("siliconflow", {}) or {}
            url = str(prov.get("url") or "https://api.siliconflow.cn/v1/images/generations")
            key = str(cfg.get("api_key") or "") or _siliconflow_key()
            if not key:
                return False, "没有 API key"
            body = json.dumps({"model": str(cfg.get("sf_model") or prov.get("model")
                                           or "Kwai-Kolors/Kolors"),
                               "prompt": prompt,
                               "image_size": f"{width}x{height}",
                               "batch_size": 1,
                               "negative_prompt": neg[:400]}).encode()
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            imgs = data.get("images") or data.get("data") or []
            img_url = str((imgs[0] or {}).get("url") or "") if imgs else ""
            if not img_url:
                return False, f"没拿到图片地址: {json.dumps(data, ensure_ascii=False)[:120]}"
        else:
            prov = (cfg.get("providers", {}) or {}).get("pollinations", {}) or {}
            base = str(prov.get("url") or "https://image.pollinations.ai/prompt/{prompt}")
            extra = str(prov.get("extra") or "?width={w}&height={h}&nologo=true&model={model}&seed={seed}")
            import random as _random
            extra = (extra.replace("{w}", str(width)).replace("{h}", str(height))
                          .replace("{model}", model).replace("{seed}", str(_random.randint(1, 10 ** 9))))
            img_url = base.replace("{prompt}", urllib.parse.quote(prompt[:1500])) + extra
        req2 = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=180) as r:
            raw = r.read()
        if len(raw) < 1024:
            return False, f"图片太小（{len(raw)} 字节）"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        return True, f"{len(raw) // 1024} KB"
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode("utf-8", "replace")[:160]
            except Exception:
                body = ""
        return False, f"{type(e).__name__}: {body or e}"


def _cg_daily_count(uid: str) -> int:
    """今天给这个人出过几张（防刷爆），记在好感度记录里"""
    today = time.strftime("%Y-%m-%d")
    rec = FAVOR.rec(uid)
    if rec.get("cg_day") != today:
        rec["cg_day"] = today
        rec["cg_today"] = 0
        FAVOR.save()
    return int(rec.get("cg_today") or 0)


def _cg_bump_count(uid: str) -> None:
    rec = FAVOR.rec(uid)
    rec["cg_today"] = int(rec.get("cg_today") or 0) + 1
    FAVOR.save()


# ---- 真 @ 只能走 NapCat 的 HTTP API（2026-09-20 查证）----
# 麦麦自己的出站链路**没有 at 段**：`send_text` 里写 `@<昵称:QQ号>` 只是普通文字，
# 适配器的 ACCEPT_FORMAT 里没有 at（`MaiBot-Napcat-Adapter\src\send_handler\
# send_message_handler.py:28-76`），Seg(type="at") 会被静默丢掉。
# 所以"@ 目标人物"这件事直接打 NapCat 的 /send_group_msg，用正牌 at 段；
# 失败再退回麦麦自己的 send_text/send_image（那时 @ 只是文字）。

def _napcat_http() -> Tuple[str, str]:
    """OneBot 的 HTTP 地址与 token —— 从 qq-monitor 的配置读，那是唯一可信来源

    ⚠️ 2026-10-01：Windows 上监控实际读的是 `config.win.json`（见面板 `_monitor_data_dir`
    同样的顾虑），这里原来写死 `config.json`。两份 token 一旦不一致就会静默失败，
    所以按和监控一致的顺序找。
    """
    base, token = "http://127.0.0.1:3000", ""
    try:
        ws = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))))
        cfg_dir = os.path.join(ws, "qq-monitor", "config")
        for name in ("config.win.json", "config.json"):
            p = os.path.join(cfg_dir, name)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                nav = (json.load(f) or {}).get("napcat", {}) or {}
            if nav.get("http_url") and nav.get("token"):
                base = str(nav["http_url"]).rstrip("/")
                token = str(nav["token"])
                break
    except Exception as e:
        logger.debug(f"[CG] 读 OneBot 配置失败，用默认地址: {type(e).__name__}: {e}")
    return base, token


def read_group_members(group_id: str) -> List[Dict[str, Any]]:
    """读取完整成员列表；本机直连、有界超时，不截断 JSON。"""
    import urllib.request
    if not str(group_id).isdigit():
        raise ValueError("无效群号")
    base, token = _napcat_http()
    request = urllib.request.Request(base + "/get_group_member_list",
        data=json.dumps({"group_id": int(group_id)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=8) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("成员列表过大")
    body = json.loads(raw.decode("utf-8"))
    if body.get("retcode") != 0 or body.get("status") not in (None, "ok") or not isinstance(body.get("data"), list):
        raise ValueError("成员列表获取失败")
    return [item for item in body["data"] if isinstance(item, dict)]


def favor_leaderboard(users: Dict[str, Any], members: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    """只展示本群已有记录的人，姓名只来自本群名片，不创建记录。"""
    import math
    rows, seen = [], set()
    for member in members:
        uid = str(member.get("user_id") or "")
        rec = users.get(uid)
        if uid in seen or not isinstance(rec, dict):
            continue
        seen.add(uid)
        try:
            score = float(rec.get("score", 100) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        name = str(member.get("card") or member.get("nickname") or uid)
        name = re.sub(r"[\r\n\t]", " ", name).strip()[:24] or uid
        rows.append({"user_id": uid, "name": name, "score": score})
    rows.sort(key=lambda row: (-row["score"], row["user_id"]))
    last_score, rank = None, 0
    for index, row in enumerate(rows, 1):
        if row["score"] != last_score:
            rank = index
        row["rank"], last_score = rank, row["score"]
    return rows[:limit]


def _napcat_post_blocking(url: str, token: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    import urllib.request
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        flat = body.replace(" ", "")
        # ⚠️ 2026-10-01 修：原来这里截到 **200 字符**（NapCat 时代返回很短，够用）。
        # 换成 SnowLuma 之后它的响应更长，`message_id` 落在截断点之后 →
        # `_napcat_msg_id()` 永远解析不出来 → 发出去的表情包**再也记不上 id→hash**
        # （`data/sticker_sent.json` 从 2026-09-24 起一条没写），用户回复那张图说
        # 「删掉」时就认不出、静默放行 —— 用户报的「撤回和删掉功能没了」就是这个。
        # 留 4000 字符足够装下返回体，又不会把日志/内存撑爆。
        return ('"status":"ok"' in flat or '"retcode":0' in flat), body[:4000]
    except Exception as e:
        extra = ""
        if hasattr(e, "read"):
            try:
                extra = e.read().decode("utf-8", "replace")[:160]
            except Exception:
                extra = ""
        return False, f"{type(e).__name__}: {extra or e}"


async def napcat_group_msg(group_id: str, segments: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """直发群消息（支持正牌 at 段 + base64 图片）"""
    gid = str(group_id or "").strip()
    if not gid:
        return False, "没有群号"
    base, token = _napcat_http()
    payload = {"group_id": int(gid) if gid.isdigit() else gid, "message": segments}
    return await asyncio.to_thread(_napcat_post_blocking, base + "/send_group_msg", token, payload)


def at_seg(qq: str) -> Dict[str, Any]:
    return {"type": "at", "data": {"qq": str(qq)}}


def text_seg(text: str) -> Dict[str, Any]:
    return {"type": "text", "data": {"text": text}}


def image_seg_b64(b64: str) -> Dict[str, Any]:
    return {"type": "image", "data": {"file": "base64://" + b64}}


def _napcat_msg_id(info: str) -> str:
    """从 /send_group_msg 的返回里抠 message_id

    删表情包要靠它：用户在群里**回复**那张图，插件拿到的只有被回复消息的 id
    （适配器写进 additional_config 的 reply_message_id），所以发送时得把
    id ↔ 库里 hash 记下来（见 SentStickerStore）。
    """
    s = str(info or "")
    try:
        d = json.loads(s or "{}")
        mid = ((d or {}).get("data") or {}).get("message_id")
        if mid:
            return str(mid)
    except Exception:
        pass
    m = re.search(r'"message_id"\s*:\s*"?(-?\d+)"?', s)
    return m.group(1) if m else ""


async def napcat_delete_msg(message_id: Any) -> Tuple[bool, str]:
    """撤回一条群消息（NapCat /delete_msg）"""
    mid = str(message_id or "").strip()
    if not mid:
        return False, "没有 message_id"
    base, token = _napcat_http()
    payload = {"message_id": int(mid) if mid.isdigit() else mid}
    return await asyncio.to_thread(_napcat_post_blocking, base + "/delete_msg", token, payload)


def _fmt(tpl: str, **kw: Any) -> str:
    """模板取值：缺键不炸，原样返回（面板里写漏一个 {xxx} 不该让整条链路挂掉）"""
    try:
        return str(tpl or "").format(**kw)
    except (KeyError, IndexError, ValueError):
        out = str(tpl or "")
        for k, v in kw.items():
            out = out.replace("{" + k + "}", str(v))
        return out


def _cmd_sig(uid: str, text: str) -> str:
    """命令消息的签名：同一个人 + 同一句原文 = 同一条命令

    为什么不用"15 秒内"这种时间窗口：2026-09-20 实测，插件把「菜单」解释发出去（19:25:29）之后，
    麦麦的回复链路 19:26:22 才生成完回复 —— **隔了 53 秒**，时间窗口根本盖不住，于是同一条命令
    被答了两遍（用户看到的就是重复输出）。签名跟消息本身绑定，多久之后跑到都认得出来。
    """
    return f"{uid}|{clean(text)[:80]}"


# ---------------------------------------------------------------- 入站消息去重（2026-10-11）
# 🔴 用户报告的两个 bug 同源：「主人点一次生图出了 4 张」「一次发了 10 张表情包」。
# 日志实测：MaiSaka 会对**同一批积压消息**连跑好几个 planner 轮次（循环编号 8、9、10…），
# 于是 `chat.receive.after_process` 钩子对**同一条消息**被调了 2 次 —— 每次都会把
# `handle_admin_draw` / `handle_sticker` 完整跑一遍 → 出图 2 次、发表情包 2 次。
#
# 为什么不用 `_cmd_sig(uid, text)` 那套：那是"内容签名 + 计数拦"，是为**用户真的再发一次
# 同样的话**设计的（所以不能拦死）。但"同一条消息被处理两遍"是**平台层重复投递**，
# 跟用户无关 —— 用 QQ 的 `message_id` 做**硬去重**才对：同一条消息只允许记账/出图一次。
#
# 进程内环形表就够：重启后清空，只影响"刚重启那一小会儿可能重复一次"，可以接受。
_MSG_SEEN_TTL = 300.0        # 同一条 message_id 多久之内算"同一次投递"
_MSG_SEEN_MAX = 512          # 最多记这么多条，防内存无限涨
_MSG_SEEN: "OrderedDict[str, float]" = OrderedDict()


def is_duplicate_message(message_id: str) -> bool:
    """同一条入站消息是不是**已经处理过**了（平台层重复投递）。

    返回 True = 这次是重复投递，调用方应**整条跳过**（不记账、不出图、不发表情包）。
    第一次见到就登记并返回 False。

    Args:
        message_id: QQ 消息 ID（`MessageAdapter.message_id`）。空串视为"无法判断" → 不算重复。

    Returns:
        bool: 重复投递时 True。
    """
    mid = str(message_id or "").strip()
    if not mid:
        return False
    now = time.time()
    # 先清过期
    while _MSG_SEEN:
        k, ts = next(iter(_MSG_SEEN.items()))
        if now - ts > _MSG_SEEN_TTL:
            _MSG_SEEN.popitem(last=False)
        else:
            break
    # ⚠️ 只判"在不在"，**不刷新时间戳** —— 刷新的话反复重投递会把它续期成永生。
    if mid in _MSG_SEEN:
        return True
    _MSG_SEEN[mid] = now
    while len(_MSG_SEEN) > _MSG_SEEN_MAX:
        _MSG_SEEN.popitem(last=False)
    return False


def reset_message_seen() -> None:
    """清空消息去重表（测试与手动排障用）。"""
    _MSG_SEEN.clear()


def _int_of(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _options_lines() -> str:
    """把身份选项列成菜单（名字 + 一句解释），解释取自配置里的 desc

    2026-10-10：按**字母**排序输出 —— 配置里 options 的书写顺序是 猫娘/示例助手/鱼娘，
    直接照抄出来就是「A 猫娘 / C 示例助手 / B 鱼娘」，字母跳着来看着像坏了。
    """
    out = []

    def _label(item):
        return str((item[1] or {}).get("label") or "").strip()

    for name, cfg in sorted((_identity_options() or {}).items(), key=_label):
        cfg = cfg or {}
        label = str(cfg.get("label") or "?").strip()
        # 展示名用「称号」：鱼娘那套 title 是"大肥鱼"（用户认的是这个），
        # 但 key 还叫"鱼娘"（老记录不能失效），两边都要能认，菜单上优先显示 title。
        shown = str(cfg.get("title") or name or "").strip()
        desc = str(cfg.get("desc") or "").strip()
        # 2026-10-11 19:51 用户要求「菜单改回之前紧凑的样子」—— 回退成单行
        # `A 猫娘（一句解释）`，不再每项换行缩进（那种排版菜单太长、太散）。
        out.append(f"{label} {shown}" + (f"（{desc}）" if desc else ""))
    # 2026-10-11 用户要求：「D 选项不要做解释」—— 保持，别把扣分惩罚摆出来。
    out.append("D 都不选")
    return "\n".join(out)


def should_nudge_identity(uid: str, text: str, mentioned: bool,
                          rec: Dict[str, Any]) -> Tuple[bool, str]:
    """要不要**主动 @ 他**弹一次身份菜单（2026-10-11 用户要求）

    用户原话：「没选择身份的人在和 ai 聊天的时候应该适时蹦出来选择身份的选项并 @ 他」。
    难点全在"适时"两个字 —— 每句都弹就是刷屏，所以这里用五道闸把它压住：

      ① 已经选过身份 → 不弹（`rec["identity"]` 有值）；
      ② 好感度不到门槛（默认 500）→ 不弹：这会儿弹出来他多半选不了，反而尴尬；
      ③ 好感度低于翻脸线 → 不弹（人都翻脸了还推销菜单很怪）；
      ④ 消息太短 / 纯命令 / 在问好感度 → 不弹：这种话不适合插播菜单；
      ⑤ 冷却 + 终身次数双限：`nudge_cooldown_seconds`（默认 900 秒）之内只弹一次，
         总共最多弹 `nudge_max_times`（默认 2）次 —— 一个人问两遍还不选就算了，
         不用一直追着念。

    另外优先弹的场景：他 **@ 了机器人**（说明确实在跟它说话），或者消息里带了
    "我是谁 / 身份 / 什么样子"这类明确话题。

    Args:
        uid: 用户 ID。
        text: 已 clean 的文本。
        mentioned: 是否 @ 了机器人。
        rec: 该用户的好感度记录（`FAVOR.rec(uid)`）。

    Returns:
        Tuple[bool, str]: (要不要弹, 原因)；不弹时原因为空串。
    """
    cfg = PROMPTS.get("identity", default={}) or {}
    if not cfg.get("enabled", True):
        return False, ""
    if str((rec or {}).get("identity") or "").strip():
        return False, ""                                  # ① 已经有身份了

    cur = _int_of((rec or {}).get("cur", (rec or {}).get("favor")), DEFAULT_FAV)
    # rec 里没存当前值就现查（`FAVOR.rec` 是纯记录，当前值在 `FAVOR.get`）
    try:
        cur = FAVOR.get(uid)
    except Exception:  # noqa: BLE001
        pass
    try:
        need = int(cfg.get("min_favor") or 500)
    except (TypeError, ValueError):
        need = 500
    if cur < need:
        return False, ""                                  # ② 好感度不够，弹了也选不了
    if cur < LOW_FAV:
        return False, ""                                  # ③ 翻脸了，别推销

    t = clean(text)
    if not t or len(t) < 3:
        return False, ""                                  # ④ 太短
    if _looks_like_command(t):
        return False, ""
    if any(w in t for w in FAV_ASK) or any(w in t for w in REL_ASK):
        return False, ""                                  # 在问好感度/关系，别插播

    # ⑤ 冷却 + 次数
    try:
        cd = float(cfg.get("nudge_cooldown_seconds") or 900)
    except (TypeError, ValueError):
        cd = 900.0
    now = time.time()
    if now - float((rec or {}).get("id_nudge_ts") or 0) < cd:
        return False, ""
    max_times = _int_of(cfg.get("nudge_max_times"), 2)
    if _int_of((rec or {}).get("id_nudge_count"), 0) >= max_times:
        return False, ""

    # 触发条件：@ 了它（首选）；或者话题明显和"身份/我是谁/长什么样"有关
    topic_kws = [str(w) for w in (cfg.get("nudge_keywords") or []) if w] or [
        "我是谁", "身份", "什么样子", "长什么样", "你认识我", "选一个", "选个身份",
        "换装", "什么形象", "人设",
    ]
    hit_topic = any(w in t for w in topic_kws)
    if not mentioned and not hit_topic:
        return False, ""
    # @ 了它但只是一句"在吗/嗯"这种极短的，也别弹（上面已经按长度挡过一轮，这里再收一道）
    if mentioned and len(t) < 4 and not hit_topic:
        return False, ""
    return True, ("他 @ 了我" if mentioned else "聊到了身份相关")


def _help_text(uid: str, uname: str, is_admin: bool = False) -> str:
    """「菜单/帮助」的解释文案

    ⚠️ 门槛（500 / 500 / 每 150）是**现算**塞进模板的，不是写死在文案里 ——
    这样改配置以后菜单不会和实际行为对不上。

    Args:
        uid: 问菜单的人。
        uname: 他的昵称。
        is_admin: 是不是管理员（`behavior_score.admin_qq`）。决定 `{admin}` 那几行
            要不要出现 —— 2026-10-11 主人生图命令上线后加的：那是**主人专属**命令，
            非管理员说了会被静默放行（不当众说"你没权限"），所以菜单里也不能给他看，
            否则他只会以为命令坏了。不是管理员时**整行删掉**（不留空行）。
    """
    rec = FAVOR.rec(uid)
    id_cfg = PROMPTS.get("identity", default={}) or {}
    cg_cfg = PROMPTS.get("cg", default={}) or {}
    st_cfg = PROMPTS.get("sticker", default={}) or {}
    sticker_line = ""
    if st_cfg.get("enabled", True):
        sticker_line = _fmt(str(id_cfg.get("sticker_help") or ""),
                            min_favor=_int_of(st_cfg.get("min_favor"), 500))
    admin_line = ""
    if is_admin:
        ad_cfg = PROMPTS.get("cg", "admin_draw", default={}) or {}
        # 功能关掉就别在菜单里留一行用不了的
        if isinstance(ad_cfg, dict) and ad_cfg.get("enabled", True) is not False:
            admin_line = _fmt(str(id_cfg.get("admin_help") or ""),
                              min_favor=_int_of(id_cfg.get("min_favor"), 500),
                              cg_start=_int_of(cg_cfg.get("start_favor"), 500),
                              cg_step=_int_of(cg_cfg.get("step"), 150),
                              cur=FAVOR.get(uid),
                              identity=rec.get("identity") or "（还没选）",
                              nickname=rec.get("nickname") or "（还没设）")
    tpl = str(id_cfg.get("help") or "")
    if not admin_line:
        # 占位符没内容 → 连它占的那一行一起删掉，别在菜单中间留个空行
        tpl = tpl.replace("{admin}\n", "").replace("{admin}", "")
    # 2026-10-13 菜单优化：动态算「离下一张纪念图还差多少分」——
    # 静态文案只能告诉别人"每 150 分一张"，加上进度才有盼头。
    cur_score = FAVOR.get(uid)
    start = _int_of(cg_cfg.get("start_favor"), 500)
    step = _int_of(cg_cfg.get("step"), 150) or 150
    if cur_score < start:
        cg_next = f"，再过 {start - cur_score} 分就开张"
    else:
        nxt = start + ((cur_score - start) // step + 1) * step
        cg_next = f"，离下一张还差 {nxt - cur_score} 分"
    return _fmt(tpl,
                who=uname or uid or "你",
                cur=cur_score,
                min_favor=_int_of(id_cfg.get("min_favor"), 500),
                cg_start=start,
                cg_step=step,
                cg_next=cg_next,
                sticker=sticker_line,
                sticker_min=_int_of(st_cfg.get("min_favor"), 500),
                admin=admin_line,
                options=_options_lines(),
                identity=rec.get("identity") or "（还没选）",
                nickname=rec.get("nickname") or "（还没设）")


_VLM_NEG = ("没", "不", "无", "非", "未", "别", "否", "no", "not")


def _vlm_hit(ans: str, pass_words: List[str]) -> bool:
    """VLM 的回答算不算"通过"（纯函数，方便探针直接测）

    ⚠️ 2026-09-22 发现并修：原来是朴素的 `w in ans` 子串匹配，中文直接把自检废掉了 ——
    问「两条腿有没有正常露出来」（通过词 `有`），VLM 答**「没有」**，`"有" in "没有"` 为真 →
    判 **通过**；问「是不是只有她一个人」（通过词 `是`），答**「不是」**同理也过。
    日志形态就是 `[CG] 自检：通过 ← 没有`。等于除了"长在她身上 vs 另一只鲸鱼"那条，
    重试自检从来没拦下过任何一张图。
    修法：命中通过词时还要看**它前面一两个字是不是否定词**（没有/不是/无/未…）。
    """
    s = re.sub(r"[\s，。！？、,.!?~～*「」\"'（）()]", "", str(ans or "")).lower()
    for w in pass_words:
        w = str(w or "").strip().lower()
        if not w:
            continue
        idx = s.find(w)
        while idx != -1:
            prev = s[max(0, idx - 3):idx]
            if not any(prev.endswith(n) for n in _VLM_NEG):
                return True
            idx = s.find(w, idx + 1)
    return False


def _vlm_yes_no(path: str, question: str, pass_words: List[str]) -> bool:
    """让 VLM 审一眼生成的图，判断某个特征在不在 —— 用来做"出图自检重试"

    2026-09-20 实测：纯文字提示画「鲸鱼长在身上」只有一半概率（模型经常另画一只独立鲸鱼，
    或者干脆没尾巴）。与其反复改提示词，不如**出完图自己看一眼，不合格就重画**
    （里程碑 CG 每 150 好感才一张，多画一两张的成本可以接受）。
    自检本身失败（没 key / 超时）时**当作通过**，不能因为审核挂掉就不出图。
    """
    try:
        cfg = PROMPTS.get("cg", default={}) or {}
        key = str(cfg.get("api_key") or "") or _siliconflow_key()
        if not key:
            return True
        import urllib.request
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        model = str(cfg.get("check_model") or "Qwen/Qwen3-VL-30B-A3B-Instruct")
        url = str(cfg.get("vlm_url") or "https://api.siliconflow.cn/v1/chat/completions")
        body = json.dumps({"model": model, "max_tokens": 60, "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            ans = json.loads(r.read().decode())["choices"][0]["message"]["content"]
        hit = _vlm_hit(ans, pass_words)
        logger.info(f"[CG] 自检：{'通过' if hit else '不合格'} ← {ans.strip()[:50]}")
        return hit
    except Exception as e:
        # 2026-10-11：debug → warning。审核挂掉时"当作通过"是对的（不能不出图），
        # 但必须能被看见 —— 10-09 硅基流动 402 那天，自检全程静默跳过，
        # 两张"两个人"的翻车图就这么直接发进了群里，日志里连个 WARNING 都没有。
        logger.warning(f"[CG] 自检跳过（当作通过，图可能没审过）: {type(e).__name__}: {e}")
        return True


def _running_apps(limit: int = 8) -> List[str]:
    """本机正在运行、**且有可见窗口**的应用名（给「主人在干什么」用）

    只取有窗口的进程：后台服务（svchost / 各种 helper）列出来没意义，也会泄露一堆无关信息。
    名字先过 `pc_status.skip` 名单，再按 `pc_status.friendly` 映射成好读的名字（chrome → Chrome）。
    """
    cfg = PROMPTS.get("pc_status", default={}) or {}
    skip = {str(x).strip().lower() for x in (cfg.get("skip") or []) if str(x).strip()}
    friendly = cfg.get("friendly") if isinstance(cfg.get("friendly"), dict) else {}
    out: List[str] = []
    seen = set()
    try:
        import ctypes
        import psutil
        user32 = ctypes.windll.user32
        pids: List[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _lp):      # noqa: ANN001
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pids.append(int(pid.value))
            return True

        user32.EnumWindows(_cb, 0)
        for pid in pids:
            try:
                nm = (psutil.Process(pid).name() or "").rsplit(".", 1)[0]
            except Exception:
                continue
            if not nm or nm.lower() in skip:
                continue
            label = str(friendly.get(nm, nm) or "").strip()   # 映射成空串 = 不想显示
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            out.append(label)
            if len(out) >= limit:
                break
    except Exception as e:
        logger.debug(f"[主人在干什么] 读窗口失败: {type(e).__name__}: {e}")
    return out


async def handle_pc_status(handler: Any, message: Any, uid: str, uname: str,
                           text: str, mentioned: bool) -> bool:
    """「主人在干什么」：读本机正在运行的应用名，直接回给提问的人（2026-09-20 新增）

    ⚠️ 这是把主人的电脑状态发到群里 —— 默认**谁问都答**（用户要求"有人问"就回），
    想收紧就把 `pc_status.admin_only` 改成 true（只有管理员的 QQ 能问）。
    """
    cfg = PROMPTS.get("pc_status", default={}) or {}
    if not cfg.get("enabled", True) or not mentioned:
        return False
    if cfg.get("admin_only") and uid not in [str(x) for x in ADMIN_QQ]:
        return False
    t = clean(text)
    kws = [str(w) for w in (cfg.get("keywords") or []) if w]
    if not kws or not any(w in t for w in kws):
        return False
    sid = message.stream_id
    gid = str((getattr(message, "message_base_info", None) or {}).get("group_id") or "")
    rec = FAVOR.rec(uid)
    now = time.time()
    cd = float(cfg.get("cooldown_seconds") or 60)
    if now - float(rec.get("pc_ts") or 0) < cd:
        await _reply_text(handler, sid, gid, uid,
                          str(cfg.get("cooling") or "刚说过啦，等会儿再问～"))
        return True
    rec["pc_ts"] = now
    FAVOR.save()
    apps = _running_apps(_int_of(cfg.get("limit"), 8))
    if apps:
        # ⚠️ 别把机器人自己（python.exe）算进去 —— skip 名单里默认有 python/pythonw
        line = _fmt(str(cfg.get("answer") or "主人现在开着：{apps}"),
                    who=uname or uid, apps="、".join(apps), count=len(apps))
    else:
        line = _fmt(str(cfg.get("empty") or "主人这会儿好像没开什么程序"), who=uname or uid)
    await _reply_text(handler, sid, gid, uid, line)
    logger.info(f"[主人在干什么] {uname or uid} 问了 → {line[:60]}")
    return True


# ---------------------------------------------------------------- 表情包库（免费那条路）
_STICKER_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "仨": 3}


def _at_others(message: Any, bot_qq: str, bot_nick: str) -> bool:
    """这条消息 @ 的是不是**别人**

    2026-09-22 实测：卜月在群里发「@Tsukimura Temari 好感度」，插件把它当成"在问自己好感度"，
    20 秒里连答两遍「你在我这儿 216」。根因是 bare_ask 只看"短消息 + 关键词"，
    没管这条消息的 @ 是冲着谁去的。@ 了别人就别抢答。

    ⚠️ 2026-10-11 修：旧版只认 `@<昵称:QQ>` 和裸 `@QQ号`，但 1.2.5 的文本里
    @ 是**纯昵称** `@示例助手`（`message.py:process_at_component` 把 QQ 号丢了）——
    两种都匹配不上，于是这个函数**恒为 False**，2026-09-22 那个抢答 bug 一直没真修好。
    现在优先查**消息段**（拿得到 `target_user_id`），文本形态兜底。
    """
    bot_qq = str(bot_qq or "")
    bot_nick = str(bot_nick or "")

    # ---- 1) 消息段优先：有真 QQ 号，最可靠 ----
    segs = getattr(message, "message_segments", None)
    for data in _iter_at_segments(segs):
        qq = str(data.get("target_user_id") or data.get("user_id") or "").strip()
        if qq and qq != bot_qq:
            return True
        if not qq:
            # 段里没 QQ 号就按昵称认
            nm = str(data.get("target_user_cardname") or data.get("target_user_nickname") or "").strip()
            if nm and bot_nick and nm != bot_nick:
                return True

    text = str(getattr(message, "plain_text", "") or "")
    # ---- 2) 旧格式 @<昵称:QQ号> ----
    for m in re.finditer(r"@<([^:>]*):([0-9]*)>", text):
        qq = m.group(2)
        if qq and bot_qq and qq == bot_qq:
            continue
        return True
    # ---- 3) 裸 @QQ号 ----
    for m in re.finditer(r"@([0-9]{5,})", text):
        if not (bot_qq and m.group(1) == bot_qq):
            return True
    # ---- 4) 纯文本 @昵称（1.2.5 的常态）----
    for m in re.finditer(r"@([^\s@\[\]<>（）()]{1,32})", text):
        nick = m.group(1).strip()
        if not nick:
            continue
        if bot_nick and (nick == bot_nick or nick.startswith(bot_nick)):
            continue
        # QQ 号形态的已经在第 3 步处理过，这里只认非纯数字的昵称
        if nick.isdigit():
            continue
        return True
    return False


def _sticker_count(text: str, dflt: int, cap: int) -> int:
    """从话里猜要几张：「发两个表情包」= 2（没写就默认 1，最多 cap 张）"""
    t = clean(text)
    n = 0
    m = re.search(r"([0-9]+)\s*[张个条]?", t)
    if m:
        n = int(m.group(1))
    if not n:
        for k, v in _STICKER_CN_NUM.items():
            if k in t:
                n = v
                break
    n = n or dflt
    return max(1, min(max(1, cap), n))


# ---- 删除库里的表情包（2026-09-22 用户要求）----
# 用户原话：「我在聊天界面回复相应表情包发送，删掉，bot 就应该撤回然后在表情包库
# 里把相应的删了」。难点是**认图**：被回复的消息回到插件里只有一个 message_id
# （适配器 `additional_config["reply_message_id"]`），所以发送时就得把
# message_id ↔ 库里的 hash 记下来；图片字节 md5 是兜底（走麦麦出站那条路拿不到 id）。
STK_SENT_FILE = os.path.join(ROOT, "data", "sticker_sent.json")
STK_SENT_KEEP = 300            # 最多记多少条
STK_SENT_TTL = 3 * 86400       # 超过 3 天的记录没意义（QQ 也撤不回了）
DEFAULT_STK_DEL_KWS = ["删掉", "删除这张", "删了", "不要这张", "别发这张", "把这图删了"]


class SentStickerStore:
    """机器人发出去的库表情包：message_id → {h: 库里 hash, t: 时间, d: 描述}"""

    def __init__(self, path: str = STK_SENT_FILE):
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f) or {}
            if isinstance(raw, dict):
                self.data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
            self.prune()
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"[表情包] 读发送记录失败: {type(e).__name__}: {e}")

    def save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)          # 原子替换：写一半崩了不该毁掉旧记录
        except Exception as e:
            logger.warning(f"[表情包] 写发送记录失败: {type(e).__name__}: {e}")

    def prune(self) -> None:
        now = time.time()
        self.data = {k: v for k, v in self.data.items()
                     if now - float(v.get("t") or 0) <= STK_SENT_TTL}
        if len(self.data) > STK_SENT_KEEP:
            old = sorted(self.data, key=lambda k: float(self.data[k].get("t") or 0))
            for k in old[:len(self.data) - STK_SENT_KEEP]:
                self.data.pop(k, None)

    def note(self, msg_id: Any, emoji_hash: str, desc: str = "") -> None:
        mid = str(msg_id or "").strip()
        if not mid or not emoji_hash:
            return
        self.data[mid] = {"h": str(emoji_hash), "t": time.time(), "d": str(desc or "")[:40]}
        self.prune()
        self.save()

    def pop(self, msg_id: Any) -> Optional[Dict[str, Any]]:
        mid = str(msg_id or "").strip()
        if not mid:
            return None
        hit = self.data.pop(mid, None)
        if hit:
            self.save()
        return hit if isinstance(hit, dict) else None


STK_SENT = SentStickerStore()


def _lib_index() -> Dict[str, str]:
    """库里 hash → 本地文件路径（把一张图认回是库里的哪张）

    ⚠️ 2026-10-01 修：新版 emoji 系统搬了家、也改了字段名，原来那套写法**全对不上**：
      · 模块路径 `src.chat.emoji_system.emoji_manager` → 现在是 `src.emoji_system.emoji_manager`；
      · manager 的属性 `emoji_objects` → 现在是 `emojis`；
      · 每个表情的 hash 字段 `hash` → 现在是 `file_hash`（**sha256**，不再是 md5）；
      · `is_deleted` 这个字段没了。
    于是 `_lib_index()` 永远返回空 → 发出去的表情包既记不上 `message_id → hash`，
    用户回复它说「删掉」时也认不出是哪张（用户报的「撤回和删掉功能没了」就是这个）。
    这里把新旧写法都认下来，上游再改也不至于整条链路哑掉。
    """
    out: Dict[str, str] = {}
    mgr = None
    for mod_name in ("src.emoji_system.emoji_manager", "src.chat.emoji_system.emoji_manager"):
        try:
            # 新版导出的是模块级单例 `emoji_manager`（旧的 `get_emoji_manager()` 函数已经没了）
            mod = __import__(mod_name, fromlist=["emoji_manager", "get_emoji_manager"])
        except Exception:
            continue
        mgr = getattr(mod, "emoji_manager", None)
        if mgr is None:
            getter = getattr(mod, "get_emoji_manager", None)
            mgr = getter() if callable(getter) else None
        if mgr is not None:
            break
    if mgr is not None:
        items: List[Any] = []
        for attr in ("emojis", "emoji_objects"):
            v = getattr(mgr, attr, None)
            if isinstance(v, (list, tuple)) and v:
                items = list(v)
                break
        for e in items:
            if getattr(e, "is_deleted", False) or getattr(e, "no_file_flag", False):
                continue
            h = str(getattr(e, "file_hash", "") or getattr(e, "hash", "") or "")
            if h:
                out[h] = str(getattr(e, "full_path", "") or "")
    # ⚠️ 2026-10-02 再修：插件跑在 `plugin_runtime` 的**独立进程**里，
    # `import src.emoji_system.emoji_manager` 拿到的是模块的**新副本** ——
    # 那个 EmojiManager 实例的 `emojis` 永远是空 list
    # （麦麦主进程日志写着「成功加载 799 个已注册表情包」，插件这边 len()==0）。
    # 所以内存拿不到时**直接查数据库**：那本来就是插件在用的同一个库。
    if not out:
        out = _lib_index_from_db()
    if not out:
        logger.warning("[表情包] 表情包库索引为空（内存实例和数据库都没拿到，撤回/删除会认不出图）")
    return out


def _lib_index_from_db() -> Dict[str, str]:
    """从麦麦的 `images` 表直接建索引：hash → 本地绝对路径

    `images.image_hash` 存的是 **md5（32 位）**，而 `_lib_hash_of_b64()` 同时算 sha256 和
    md5，所以 md5 这一路能对上。只取「已注册 + 未封禁 + 文件真的在」的记录，
    口径跟 emoji_manager 自己的加载保持一致。
    """
    import sqlite3                       # 局部导入：不动文件头，避免插错位置
    out: Dict[str, str] = {}
    try:
        db = os.path.join(ROOT, "data", "MaiBot.db")
        if not os.path.exists(db):
            logger.warning(f"[表情包] 找不到麦麦数据库 {db}")
            return out
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute("""SELECT image_hash, full_path FROM images
                           WHERE image_type = 'EMOJI' AND is_registered = 1
                             AND is_banned = 0""")
            for h, p in cur.fetchall():
                h = str(h or "").strip()
                p = str(p or "").strip()
                if not h or not p:
                    continue
                full = p if os.path.isabs(p) else os.path.join(ROOT, p)
                if os.path.exists(full):
                    out[h] = full
        finally:
            con.close()
        logger.info(f"[表情包] 已从数据库建立表情包索引：{len(out)} 条")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[表情包] 从数据库读索引失败: {type(e).__name__}: {e}")
    return out


def _b64_digest(data: Any) -> Tuple[str, str]:
    """图片段的 base64 → (sha256, md5)

    库现在用 **sha256**（`MaiEmoji.file_hash`）；2026-09-24 之前写进
    `sticker_sent.json` 的老记录是 md5，两个都算出来、都能认。
    """
    s = str(data or "").strip()
    if len(s) < 32 or s.startswith("http"):
        return "", ""
    if s.startswith("base64://"):
        s = s[len("base64://"):]
    if s.startswith("data:") and "," in s[:80]:
        s = s.split(",", 1)[1]
    s = re.sub(r"\s+", "", s)
    try:
        raw = base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return "", ""
    if not raw:
        return "", ""
    return hashlib.sha256(raw).hexdigest(), hashlib.md5(raw).hexdigest()


def _b64_md5(data: Any) -> str:
    """老接口：只取 md5（保留给老调用点/老记录用）"""
    return _b64_digest(data)[1]


def _lib_hash_of_b64(data: Any, index: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """一张图的 base64 → (库里 hash, 本地路径)；不在库里返回 ("", "")"""
    sha, md5 = _b64_digest(data)
    if not sha and not md5:
        return "", ""
    idx = _lib_index() if index is None else index
    for h in (sha, md5):
        if h and h in idx:
            return h, idx[h]
    return "", ""


def _reply_image_b64s(segments: Any, depth: int = 0) -> List[Any]:
    """消息段里所有图片/表情包段的 data（引用回复时会把被回复那张图**内联**进来）"""
    if depth > 6 or not segments or isinstance(segments, (str, bytes)):
        return []
    if not isinstance(segments, (list, tuple)):
        segments = [segments]
    out: List[Any] = []
    for seg in segments:
        if isinstance(seg, (list, tuple)):
            out += _reply_image_b64s(seg, depth + 1)
            continue
        if str(getattr(seg, "type", "") or "") in ("image", "emoji"):
            d = getattr(seg, "data", None)
            if d:
                out.append(d)
    return out


async def napcat_get_msg(message_id: Any) -> Dict[str, Any]:
    """取回一条消息（OneBot `/get_msg`）—— 用来认「被回复的那张图」是哪张

    2026-10-01 加：发送时记的 `message_id → hash` 只覆盖**新发**的图（而且 3 天过期），
    用户回复一张旧的 / 当初没记上的表情包说「删掉」时，就靠这里把那条消息捞回来。
    """
    mid = str(message_id or "").strip()
    if not mid:
        return {}
    base, token = _napcat_http()
    payload = {"message_id": int(mid) if mid.lstrip("-").isdigit() else mid}
    ok, body = await asyncio.to_thread(_napcat_post_blocking, base + "/get_msg", token, payload)
    if not ok:
        return {}
    try:
        return (json.loads(body or "{}") or {}).get("data") or {}
    except Exception:
        return {}


def _seg_field(seg: Any, key: str) -> Any:
    """消息段取值：适配器给的是对象，别处（探针/原始 JSON）给的是 dict，两边都认"""
    if isinstance(seg, dict):
        return seg.get(key)
    return getattr(seg, key, None)


def _image_urls_of_segments(segments: Any, depth: int = 0) -> List[str]:
    """消息段里所有图片的 url（适配器只给 url、不给内联字节时用它）"""
    if depth > 6 or not segments or isinstance(segments, (str, bytes)):
        return []
    if not isinstance(segments, (list, tuple)):
        segments = [segments]
    out: List[str] = []
    for seg in segments:
        if isinstance(seg, (list, tuple)):
            out += _image_urls_of_segments(seg, depth + 1)
            continue
        if str(_seg_field(seg, "type") or "") not in ("image", "emoji", "face"):
            continue
        data = _seg_field(seg, "data")
        url = ""
        if isinstance(data, dict):
            url = str(data.get("url") or "").strip()
        elif isinstance(data, str):
            url = data.strip()
        if url.startswith("http"):
            out.append(url)
    return out


async def _hash_of_url(url: str, idx: Dict[str, str]) -> str:
    """下载一张图 → 字节 md5 → 在库里找（找不到返回空串）"""
    if not url or not idx:
        return ""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
    except Exception as e:
        logger.debug(f"[表情包] 取被回复的图失败: {type(e).__name__}: {e}")
        return ""
    if not raw:
        return ""
    for h in (hashlib.sha256(raw).hexdigest(), hashlib.md5(raw).hexdigest()):
        if h in idx:
            return h
    return ""


async def _replied_image_hash(rid: str) -> str:
    """被回复的那条消息里的图片 → 库里 hash（适配器没把图内联进来时的兜底）"""
    idx = _lib_index()
    if not idx or not rid:
        return ""
    data = await napcat_get_msg(rid)
    if not data:
        return ""
    segs = data.get("message") or []
    for b64 in _reply_image_b64s(segs):
        h, _ = _lib_hash_of_b64(b64, idx)
        if h:
            return h
    for url in _image_urls_of_segments(segs):
        h = await _hash_of_url(url, idx)
        if h:
            return h
    return ""


async def _lib_stickers(count: int) -> List[Any]:
    """从麦麦自己的表情包库随机拿几张（免费、秒回；失败返回空）

    库在 `data/emoji_registed`（500 张，麦麦"偷"来的群友表情包），由 emoji_manager 管。
    这里**不做 AI 生图** —— 用户 2026-09-22 的原话是"叫它发表情包结果去生图了"。

    ⚠️ 0.11 的 `src.plugin_system.apis.emoji_api` 在 1.2.5 里没了，改用 SDK 的 emoji 能力；
    能力要 `ctx`，所以由 `plugin.py` 在加载时把实现注入到 `emoji_provider`（见该文件）。
    没注入时**明确报一句**再返回空，不静默装作"库里没图"。
    """
    if emoji_provider is None:
        logger.warning("[表情包] 新版 emoji 能力尚未接上（emoji_provider 为空），跳过取库")
        return []
    try:
        return list(await emoji_provider.get_random(int(count)) or [])
    except Exception as e:
        logger.warning(f"[表情包] 取库失败: {type(e).__name__}: {e}")
        return []


async def send_lib_stickers(handler: Any, sid: str, gid: str, uid: str,
                            count: int, mention: bool = False) -> int:
    """把库里的表情包发出去，返回成功张数（优先直发 NapCat，失败退回麦麦出站）

    发出去的每一张都顺手记 `message_id → 库里 hash`（`STK_SENT`），
    这样用户回复那张图说「删掉」时才知道要删库里哪一张。
    """
    got = await _lib_stickers(count)
    if not got:
        return 0
    sent = 0
    idx = _lib_index()
    for item in got:
        b64 = item[0] if isinstance(item, (list, tuple)) and item else ""
        if not b64:
            continue
        desc = str(item[1]) if isinstance(item, (list, tuple)) and len(item) > 1 else ""
        if gid:
            segs: List[Dict[str, Any]] = []
            if mention and sent == 0:
                segs.append(at_seg(uid))
            segs.append(image_seg_b64(b64))
            ok, info = await napcat_group_msg(gid, segs)
            if ok:
                sent += 1
                h, _path = _lib_hash_of_b64(b64, idx)
                if h:
                    STK_SENT.note(_napcat_msg_id(info), h, desc)
                continue
            logger.warning(f"[表情包] 直发 NapCat 失败，退回麦麦出站: {str(info)[:80]}")
        if sid:
            try:
                await handler.send_image(sid, b64)
                sent += 1
            except Exception as e:
                logger.warning(f"[表情包] 麦麦出站也失败: {type(e).__name__}: {e}")
    return sent


async def maybe_auto_sticker(handler: Any, sid: str, gid: str, text: str = "") -> int:
    """机器人刚说完话 → 按概率顺手补一张库里的表情包（"表情包多用点"）

    为什么挂在 AFTER_SEND（机器人真的回了话）而不是每条消息上：后者等于群里每句话
    都甩图，纯刷屏。频率全在配置里（`sticker.auto_chance / auto_cooldown_seconds /
    auto_daily_limit`），冷却和当日计数记在 behavior_score.json 的 per-stream 记录里。
    """
    try:
        st = PROMPTS.get("sticker", default={}) or {}
        if not st.get("enabled", True):
            return 0
        chance = float(st.get("auto_chance") or 0)
        if chance <= 0 or random.random() > chance:
            return 0
        if text and any(w in str(text) for w in (st.get("draw_keywords") or [])):
            return 0                      # 刚画过图，别再叠一张
        rec = SCORE.stream(sid)
        now = time.time()
        cd = float(st.get("auto_cooldown_seconds") or 120)
        if now - float(rec.get("stk_auto_ts") or 0) < cd:
            return 0
        today = time.strftime("%Y-%m-%d")
        if rec.get("stk_auto_day") != today:
            rec["stk_auto_day"] = today
            rec["stk_auto_today"] = 0
        limit = _int_of(st.get("auto_daily_limit"), 60)
        if int(rec.get("stk_auto_today") or 0) >= limit:
            return 0
        rec["stk_auto_ts"] = now
        SCORE.save()
        got = await send_lib_stickers(handler, sid, gid, "", 1, False)
        if got > 0:
            rec["stk_auto_today"] = int(rec.get("stk_auto_today") or 0) + got
            SCORE.save()
            logger.info(f"[表情包] 说完话顺手补了一张（{gid or sid} "
                        f"今日 {rec['stk_auto_today']}/{limit}）")
        return got
    except Exception as e:
        logger.warning(f"[表情包] 自动补图失败: {type(e).__name__}: {e}")
        return 0


async def _reply_text(handler: Any, sid: str, gid: str, uid: str, line: str) -> None:
    """回一句纯文本，能真 @ 就真 @（走 NapCat 的 at 段），不行退回麦麦出站"""
    if not line:
        return
    if gid:
        ok, info = await napcat_group_msg(gid, [at_seg(uid), text_seg(" " + line)])
        if ok:
            return
        logger.debug(f"[图片] 直发 NapCat 失败，退回麦麦出站: {info[:80]}")
    if sid:
        await handler.send_text(sid, line)


async def send_image_msg(handler: Any, sid: str, gid: str, uid: str, uname: str,
                         path: str, caption: str, mention: bool = True) -> bool:
    """把一张本地图片发到群里（里程碑 CG 和梗图共用这一条路径）"""
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        logger.warning(f"[图片] 读图失败: {type(e).__name__}: {e}")
        return False
    if gid:
        segs: List[Dict[str, Any]] = []
        if mention:
            segs.append(at_seg(uid))
            segs.append(text_seg(" " + caption))
        else:
            segs.append(text_seg(caption))
        segs.append(image_seg_b64(b64))
        ok, info = await napcat_group_msg(gid, segs)
        if ok:
            return True
        logger.warning(f"[图片] 直发 NapCat 失败，退回麦麦出站: {info[:100]}")
    if sid:
        fb = f"@{uname or uid} {caption}" if mention else caption
        try:
            await handler.send_text(sid, fb)
            await handler.send_image(sid, b64)
            return True
        except Exception as e:
            logger.warning(f"[图片] 麦麦出站也失败: {type(e).__name__}: {e}")
    return False


def _replied_qq(text: str) -> str:
    """这条消息在回复谁 —— 适配器把被引用消息写成 `[回复<昵称:QQ>：……]，说：`

    （`message_handler.py:476`）只用来判断"是不是在回复机器人自己"，别的消息一律不认。
    """
    m = re.match(r"\s*\[回复<[^:>]*:([0-9]*)>", str(text or ""))
    return m.group(1) if m else ""


async def handle_sticker_delete(handler: Any, message: Any, uid: str, uname: str,
                                text: str) -> bool:
    """回复机器人发的那张表情包 + 说「删掉」→ 撤回消息 + 从库里删掉（2026-09-22）

    三个条件缺一不做（宁可不动，也不能误删图库）：
      ① 这条消息是**引用回复**（适配器的 `reply_message_id`）；
      ② 话里有删除词（`sticker.delete_keywords`）；
      ③ 认得出被回复的是哪张 —— 先查发送时记的 `message_id → hash`，
         再用被回复那张图的字节 md5 跟库里的 hash 对（麦麦出站那条路拿不到 id）。
    认不出就**放行**（返回 False），交给正常聊天 —— 群里随便一句「删掉」不该被它抢答；
    唯一的例外：回复的**就是机器人自己的消息**时回一句提示（`delete_unknown`），
    不然用户会以为这功能坏了（这个功能上线前发的老表情包就属于这类）。
    默认只有管理员能删（`sticker.delete_admin_only`）。
    """
    st = PROMPTS.get("sticker", default={}) or {}
    if not st.get("enabled", True):
        return False
    rid = str(((getattr(message, "additional_data", None) or {})
               .get("reply_message_id")) or "").strip()
    if not rid:
        return False
    kws = [str(w) for w in (st.get("delete_keywords") or DEFAULT_STK_DEL_KWS) if w]
    if not any(w in clean(text) for w in kws):
        return False
    if st.get("delete_admin_only", True) and not _is_admin_of(handler, uid):
        return False

    sid = message.stream_id
    gid = str((getattr(message, "message_base_info", None) or {}).get("group_id") or "")
    hit = STK_SENT.pop(rid)                       # ① 发送时记的 id → hash
    h = str((hit or {}).get("h") or "")
    if not h:                                     # ② 消息段里内联进来的字节 md5
        for data in _reply_image_b64s(getattr(message, "message_segments", None)):
            h, _path = _lib_hash_of_b64(data)
            if h:
                break
    if not h:                                     # ③ 用 /get_msg 把被回复那条捞回来再认
        h = await _replied_image_hash(rid)
    if not h:
        # 认不出是哪张：只有在**回复机器人自己的消息**时才回一句提示（这个功能落地之前的
        # 老表情包、或者走麦麦出站那条路没记上 id 的，就落在这里）。其余一律放行、不吭声。
        bot_qq, _nick = _bot_ids()
        if bot_qq and _replied_qq(text) == bot_qq:
            await _reply_text(handler, sid, gid, uid,
                              str(st.get("delete_unknown")
                                  or "这张我没找到对应的库记录…你再 @我说「表情包」发张新的，"
                                     "回复它说「删掉」就行～"))
            return True
        logger.info(f"[表情包] {uname or uid} 说要删，但没认出被回复的是哪张（id={rid}）")
        return False

    recalled = False
    if gid:
        recalled, info = await napcat_delete_msg(rid)
        if not recalled:
            logger.info(f"[表情包] 消息未能撤回: {str(info)[:120]}")

    gone, left = False, None
    path = _lib_index().get(h, "")            # 只为了日志能指出删了哪个文件（可追溯）
    try:
        if emoji_provider is None:
            raise RuntimeError("新版 emoji 能力尚未接上（emoji_provider 为空）")
        res = await emoji_provider.delete_emoji(h) or {}
        gone = bool(res.get("success"))
        reported_count = res.get("count_after")
        if type(reported_count) is int and reported_count >= 0:
            left = reported_count
    except Exception as e:
        logger.warning(f"[表情包] 从库里删除失败: {type(e).__name__}: {e}")

    if not gone and not recalled:
        tpl = str(st.get("delete_both_failed") or "消息没能撤回，表情包也没能从库里删掉。")
    elif not gone:
        tpl = str(st.get("delete_failed") or "消息已撤回，但没能从库里删掉这张表情包。")
    elif not recalled:
        tpl = str(st.get("delete_recall_failed") or "库里的删掉了（这条消息没能撤回）～")
    else:
        tpl = str(st.get("delete_done") or "删掉了，这张以后不发了～")
    if left is None:
        # 兼容旧模板里的 {left}：无计数证据时移除独立计数括号，不凭空填零。
        tpl = re.sub(r"[（(][^（）()\n]*\{left\}[^（）()\n]*[）)]", "", tpl)
    await _reply_text(handler, sid, gid, uid, _fmt(tpl, who=uname or uid, left=left if left is not None else "未知"))
    logger.info(f"[表情包] {uname or uid} 让删 {h[:8]}"
                f"（{os.path.basename(path) if path else '库里已无此图'}）："
                f"撤回={recalled} 出库={gone} 剩余={left}")
    return True


async def handle_sticker(handler: Any, message: Any, uid: str, uname: str,
                         text: str, mentioned: bool) -> bool:
    """表情包：库模式（默认）直接发它偷来的表情包；画模式用当前身份 AI 画 Q 版

    2026-09-22 用户口径（原话）：
      · 「我叫 bot 发表情包会触发生图」→ 要的是**库里那些群友表情包**，不是每次 AI 生图；
      · 「表情包使用的频率不够高」→ 库里免费，门槛就该低（不要好感度、20 秒冷却、每天 30 张）。
    所以两条路彻底分开：
      · 库模式（`sticker.lib_keywords`）：谁都能要，说「发两个表情包」就发两张；
      · 画模式（`sticker.draw_keywords`，如「梗图 / 画一张」）：仍要 `min_favor` 好感度，
        计数走 `stk_*`。
    """
    st = PROMPTS.get("sticker", default={}) or {}
    if not st.get("enabled", True) or not mentioned:
        return False
    t = clean(text)
    lib_kws = [str(w) for w in (st.get("lib_keywords") or ["表情包", "表情"]) if w]
    draw_kws = [str(w) for w in (st.get("draw_keywords") or st.get("keywords") or []) if w]
    # 「画一张」这种明确要图的优先按画模式走：两个词表都命中时别退化成发表情包
    draw = any(w in t for w in draw_kws)
    lib = (not draw) and any(w in t for w in lib_kws)
    if not (draw or lib):
        return False
    sid = message.stream_id
    gid = str((getattr(message, "message_base_info", None) or {}).get("group_id") or "")
    rec = FAVOR.rec(uid)
    cur = FAVOR.get(uid)
    now = time.time()

    # ---------------- ① 库模式：免费、门槛低、秒回 ----------------
    if lib:
        cd = float(st.get("lib_cooldown_seconds") or 20)
        left = cd - (now - float(rec.get("lib_ts") or 0))
        if left > 0:
            await _reply_text(handler, sid, gid, uid,
                              _fmt(str(st.get("lib_cooling") or "刚发过，{left} 秒后再要～"),
                                   who=uname or uid, left=int(left)))
            return True
        today = time.strftime("%Y-%m-%d")
        if rec.get("lib_day") != today:
            rec["lib_day"] = today
            rec["lib_today"] = 0
        limit = _int_of(st.get("lib_daily_limit"), 30)
        if int(rec.get("lib_today") or 0) >= limit:
            rec["lib_ts"] = now
            FAVOR.save()
            await _reply_text(handler, sid, gid, uid,
                              _fmt(str(st.get("lib_limit") or "今天给你发了 {limit} 张了，明天再要～"),
                                   who=uname or uid, limit=limit))
            return True
        cnt = _sticker_count(text,
                             _int_of(st.get("lib_count_default"), 1),
                             _int_of(st.get("lib_count_max"), 3))
        # 2026-10-11 用户反馈「没有提示词突然发出五个表情包」：
        # **没写数字**、只说了「表情包」这种短促请求时，最多给 `lib_short_msg_max` 张（默认 2）
        # —— 人只是随手要一张，一口气甩 5 张就是刷屏。
        # 「来 5 张表情包」这种**写明了数字**的不受这条限（他真要 5 张就给他 5 张，封顶走
        # `lib_count_max`）。
        ct = clean(text)
        has_num = bool(re.search(r"[0-9]", ct)) or any(k in ct for k in _STICKER_CN_NUM)
        if not has_num:
            cnt = min(cnt, _int_of(st.get("lib_short_msg_max"), 2))
        rec["lib_ts"] = now
        FAVOR.save()
        got = await send_lib_stickers(handler, sid, gid, uid, cnt,
                                      bool(st.get("lib_mention")))
        if got <= 0:
            logger.warning(f"[表情包] {uname or uid} 要 {cnt} 张，一张都没发出去")
            await _reply_text(handler, sid, gid, uid,
                              str(st.get("lib_empty") or "库里这会儿翻不出图，等下再要～"))
            return True
        rec["lib_today"] = int(rec.get("lib_today") or 0) + got
        FAVOR.save()
        logger.info(f"[表情包] 给 {uname or uid} 发了 {got} 张库里的"
                    f"（今日 {rec['lib_today']}/{limit}）")
        return True

    # ---------------- ② 画模式：AI 出一张 Q 版（要好感度）----------------
    need = _int_of(st.get("min_favor"), 500)

    if cur < need:
        await _reply_text(handler, sid, gid, uid,
                          _fmt(str(st.get("not_enough")
                                   or "表情包要 {min_favor} 好感度，你现在 {cur}，先攒着～"),
                               who=uname or uid, cur=cur, min_favor=need))
        logger.info(f"[梗图] {uname or uid} 好感度 {cur} < {need}，没给画")
        return True

    now = time.time()
    cd = float(st.get("cooldown_seconds") or 90)
    left = cd - (now - float(rec.get("stk_ts") or 0))
    if left > 0:
        await _reply_text(handler, sid, gid, uid, f"刚画过，等 {int(left)} 秒再要～")
        return True
    today = time.strftime("%Y-%m-%d")
    if rec.get("stk_day") != today:
        rec["stk_day"] = today
        rec["stk_today"] = 0
    limit = _int_of(st.get("daily_limit"), 5)
    if int(rec.get("stk_today") or 0) >= limit:
        rec["stk_ts"] = now
        FAVOR.save()
        await _reply_text(handler, sid, gid, uid, f"今天已经给你画了 {limit} 张，明天再来 🐟")
        return True

    identity = str(rec.get("identity") or "")
    ident = _identity_options().get(identity) or {}
    prompt = str(ident.get("chibi") or "").strip()
    neg = str(ident.get("chibi_negative") or "").strip()
    if not prompt:
        hints = (PROMPTS.get("cg", "identity_hint", default={}) or {})
        prompt = _fmt(str(st.get("fallback") or "chibi, Q版, 1girl, {identity_hint}"),
                      identity_hint=str(hints.get(identity or "", hints.get("", "")) or ""))
    dest = os.path.join(CG_IMG_DIR, f"stk_{uid}_{int(now)}.jpg")
    rec["stk_ts"] = now
    FAVOR.save()
    ok, info = await asyncio.to_thread(_fetch_cg_image, prompt, dest,
                                       str(st.get("size") or ""), neg)
    if not ok:
        logger.warning(f"[梗图] 出图失败: {info}")
        await _reply_text(handler, sid, gid, uid, "画崩了，等下再试（这张不算你的）")
        return True
    rec["stk_today"] = int(rec.get("stk_today") or 0) + 1
    FAVOR.save()
    caption = _fmt(str(st.get("caption") or "{who} 的 Q 版表情包"),
                   who=uname or uid, identity=identity or "没选身份")
    await send_image_msg(handler, sid, gid, uid, uname, dest, caption)
    logger.info(f"[梗图] 给 {uname or uid} 画好了（{info}）")
    return True


async def handle_identity_and_callname(handler: Any, message: Any, uid: str, uname: str,
                                       text: str, mentioned: bool) -> bool:
    """身份选择 + 自定义称呼（2026-09-20 新增）

    返回 True = 已经处理完，调用方直接 `continue_flag=False` 取消正常回复。
    只在"没被翻脸闸门拦下"的路径上调用，所以这里不再判低好感。

    三条命令都要求 **@ 了机器人**，否则群里随便一句"我选 A 座"都会被当成选身份。
    """
    t = clean(text)
    if not t:
        return False
    sid = message.stream_id
    gid = str((getattr(message, "message_base_info", None) or {}).get("group_id") or "")
    rec = FAVOR.rec(uid)
    cur = FAVOR.get(uid)
    id_cfg = PROMPTS.get("identity", default={}) or {}
    cn_cfg = PROMPTS.get("callname", default={}) or {}

    # 正在被翻脸（好感度 < 阈值）的人不给改设定
    if cur < LOW_FAV:
        return False

    # 「回答菜单」**不用再 @ 我**：2026-09-20 实测，让人回两次 @ 太反人类，
    # 而且手一懒没 @ → 答案被整个吞掉（日志里只有菜单、没有"选了"，身份永远切不过去）。
    answering = False
    expired = False
    ttl = 300.0
    if id_cfg.get("enabled", True):
        try:
            ttl = float(id_cfg.get("pending_seconds") or 300)
        except (TypeError, ValueError):
            ttl = 300.0
        pending_ts = float(rec.get("id_pending_ts") or 0)
        if pending_ts:
            age = time.time() - pending_ts
            answering = age <= ttl
            # 2026-10-11：菜单过期后，如果他还在回「A / 猫娘」这种答案，
            # 得告诉他"过期了、怎么重来"——不能装没看见（旧行为就是这样，用户会以为坏了）。
            # 这里只标记「过期 + 像在答题」，真正回什么话放到下面 ①b 分支里做。
            expired = (not answering) and age > ttl
    if not mentioned and not answering:
        # 过期但看起来在答题 → 走 ①b 给提示；其余（纯路过消息）照旧放行给模型
        if not (expired and looks_like_identity_answer(text)):
            return False

    async def reply(line: str) -> None:
        """能真 @ 就真 @（走 NapCat 的 at 段），不行再退回麦麦自己的出站"""
        if not line:
            return
        if gid:
            ok, info = await napcat_group_msg(gid, [at_seg(uid), text_seg(" " + line)])
            if ok:
                return
            logger.debug(f"[身份] 直发 NapCat 失败，退回麦麦出站: {info[:80]}")
        if sid:
            await handler.send_text(sid, line)

    # ---- ① 先看是不是在回答身份菜单（菜单过期就不认了）----
    if answering:
        # 2026-10-10：必须喂**原始**文本 —— `t` 已经是 `clean()` 过的（空白全没了），
        # `@示例助手 A` 会变成 `@示例助手A`，剥 @ 时正则一路吃到结尾，答案整个被吞掉。
        pick = _match_identity(text)
        if pick:
            rec.pop("id_pending_ts", None)
            if pick == "不选":
                before = cur
                try:
                    cost = int(id_cfg.get("penalty_no_choice") or 150)
                except (TypeError, ValueError):
                    cost = 150
                after = FAVOR.admin_add(uid, -cost, uname)
                FAVOR.save()
                await reply(_fmt(str(id_cfg.get("declined") or ""), who=uname or uid,
                                 before=before, after=after, cost=cost, cur=after))
                logger.info(f"[身份] {uname or uid} 选「不选」，扣 {cost}：{before} → {after}")
            else:
                rec["identity"] = pick
                FAVOR.save()
                await reply(_fmt(str(id_cfg.get("applied") or ""), title=pick,
                                 who=uname or uid, cur=cur))
                logger.info(f"[身份] {uname or uid} 选了「{pick}」")
            return True

    # ---- ①b 菜单过期了，但他还在回答案 → 提示「过期了 + 怎么重来」----
    # 2026-10-11 用户要求：「身份选择加一个时间限制，然后顺便提示错过了怎么办」。
    # 只在「确实有菜单 + 确实超时 + 这句像在答题」时才提示，别把普通聊天也拦下来。
    # 提示里**不扣分**（超时不是他的错，他可能只是没看见），也不清 `id_pending_ts`
    # —— 保持原样，这样他要是又超时再来一次，还能再收到一次提示，不会变成哑巴。
    if expired and looks_like_identity_answer(text):
        rec.pop("id_pending_ts", None)   # 清掉过期时间戳，避免以后每次答题都触发提示
        FAVOR.save()
        secs = int(ttl) if float(ttl).is_integer() else ttl
        await reply(_fmt(str(id_cfg.get("pending_expired") or ""), who=uname or uid,
                         seconds=secs, cur=cur,
                         min_favor=_int_of(id_cfg.get("min_favor"), 500)))
        logger.info(f"[身份] {uname or uid} 的菜单已过期（>{ttl:.0f}s），回了答案，已提示重新发起")
        return True

    # ---- ② 菜单/帮助：把"都能干啥"讲一遍 ----
    # 文案从配置里现生成，所以门槛（500 / 每 150）永远和代码实际行为一致，
    # 不会出现"菜单写着 300、代码要 350"这种对不上的事。
    help_kws = [str(w) for w in (id_cfg.get("help_keywords") or []) if w]
    if mentioned and help_kws and any(w.lower() in t.lower() for w in help_kws):
        # 2026-10-11：`is_admin` 决定菜单里那几行「主人专属命令」出不出来
        await reply(_help_text(uid, uname, is_admin=_is_admin_of(handler, uid)))
        logger.info(f"[身份] {uname or uid} 看了菜单解释")
        return True

    # ---- ③ 问身份 → 发菜单（好感度够才给）----
    if id_cfg.get("enabled", True):
        kws = [str(w) for w in (id_cfg.get("ask_keywords") or []) if w]
        if mentioned and any(w in t for w in kws):
            try:
                need = int(id_cfg.get("min_favor") or 500)
            except (TypeError, ValueError):
                need = 500
            if cur < need:
                await reply(_fmt(str(id_cfg.get("not_enough") or ""), who=uname or uid,
                                 cur=cur, min_favor=need))
                logger.info(f"[身份] {uname or uid} 好感度 {cur} < {need}，没给菜单")
            else:
                rec["id_pending_ts"] = time.time()
                FAVOR.save()
                # {after} 给"选 D 之后会变成多少"用，省得它自己算错
                try:
                    cost = int(id_cfg.get("penalty_no_choice") or 150)
                except (TypeError, ValueError):
                    cost = 150
                # 2026-10-10：`{options}` 现在真的传了 —— 原来菜单文案里手写着
                # "四个 A/B/C/D"，改了 `options`（增删身份 / 换字母）以后菜单不会跟着变，
                # 于是"菜单写着 D、实际没有 D"这种对不上。文案里写 {options} 就永远同步。
                menu_txt = _fmt(str(id_cfg.get("menu") or ""), who=uname or uid, cur=cur,
                                min_favor=need, after=max(0, cur - cost), cost=cost,
                                options=_options_lines())
                # 2026-10-11：菜单末尾追一句有效期提示（用户要求「加一个时间限制」）。
                # 提前把时限告诉他，省得他慢慢想、反应过来时菜单已经过期了。
                hint = str(id_cfg.get("menu_timeout_hint") or "")
                if hint:
                    secs = int(ttl) if float(ttl).is_integer() else ttl
                    menu_txt = f"{menu_txt}\n{_fmt(hint, seconds=secs)}"
                await reply(menu_txt)
                logger.info(f"[身份] {uname or uid} 好感度 {cur}，已发身份菜单（有效期 {ttl:.0f}s）")
            return True

    # ---- ④ 自定义称呼（要 @ 它，免得群里一句"以后叫我X"就改设定）----
    # 2026-10-24：只在**整句就是改名请求**时才接（_parse_callname 的纯度判定）。
    # 像「十分钟后叫我睡觉」这种挂着时间/动作的，放给模型回，不再误设称呼。
    if cn_cfg.get("enabled", True):
        nick = _parse_callname(t)
        if mentioned and nick:
            problem = _callname_problem(nick)
            if problem:
                await reply(_fmt(str(cn_cfg.get("bad") or ""), who=uname or uid,
                                 nick=nick, reason=problem))
            else:
                rec["nickname"] = nick
                FAVOR.save()
                await reply(_fmt(str(cn_cfg.get("ok") or ""), who=uname or uid, nick=nick))
                logger.info(f"[身份] {uname or uid} 的称呼设为「{nick}」")
            return True
    return False


async def handle_admin_draw(handler: Any, message: Any, uid: str, uname: str,
                            text: str, mentioned: bool) -> bool:
    """主人专属：**现在就要一张纪念图**（2026-10-11 新增）

    正常流程得等好感度跨档（500 起、每 +150 一张）才出图，主人想立刻看一眼新装扮/
    新提示词长什么样，就得有个口子。

    三道闸，缺一不可：
      ① 必须 **@ 了它**（群里随口一句"生图"不能烧钱）；
      ② 必须是**管理员**（`behavior_score.admin_qq`，默认 1000000008）；
      ③ 必须命中 `cg.admin_draw.keywords`。
    非管理员命中关键词时：**插件自己接管回一句**（`cg.admin_draw.denied`），
    不交给模型 —— 2026-10-11 实测，放给模型它会自由发挥出「你不是主人」这种话，
    既是凭空造设定、又在群里打了人脸（用户当场问"他发言有逻辑吗"）。
    语气按配置走：默认是**半开玩笑地推掉**，不当众说"你没权限"。

    可以指定档位：「@示例助手 生图 5」出第 5 档；不写就用他当前好感度对应的那一档。
    """
    cfg = PROMPTS.get("cg", "admin_draw", default={}) or {}
    if not isinstance(cfg, dict) or cfg.get("enabled", True) is False:
        return False
    t = clean(text)
    if not t or not mentioned:
        return False
    kws = [str(w) for w in (cfg.get("keywords") or []) if str(w).strip()]
    if not kws or not any(w in t for w in kws):
        return False

    sid = message.stream_id
    gid = str((getattr(message, "message_base_info", None) or {}).get("group_id") or "")
    cur = FAVOR.get(uid)

    if not _is_admin_of(handler, uid):
        # 非管理员：插件接管，别让模型自己编「你不是主人」那种台词。
        # 同一条消息只接一次（MaiSaka 会重复投递，见 `is_duplicate_message` 的注释）。
        line = _fmt(str(cfg.get("denied")
                        or "纪念图是主人的特权，你嘛…先好好聊天，好感度够了自然有～"),
                    who=uname or uid, cur=cur)
        await _reply_text(handler, sid, gid, uid, line)
        logger.info(f"[CG] {uname or uid} 不是管理员，想要生图 → 插件接管回绝")
        return True

    # 档位上限取 stages 里最大的 level（默认 8）：主人好感度高时 `_cg_level_for`
    # 能算出 12 这种数，虽然 `_cg_stage` 会兜住复用最后一张，但文案会显示"第 12 张"。
    stage_levels = [int(st.get("level", 0)) for st in
                    (PROMPTS.get("cg", "stages", default=[]) or [])
                    if isinstance(st, dict) and str(st.get("level", "")).lstrip("-").isdigit()]
    max_level = max(stage_levels) if stage_levels else 8
    # 指定档位：句子里出现的第一个 1~8（@<昵称:QQ> 已被 clean 剥掉，不会误取 QQ 号里的数字）
    level = 0
    m = re.search(r"[1-8]", t)
    if m:
        level = int(m.group(0))
    if not level:
        level = _cg_level_for(cur) or 1
    level = max(1, min(int(level), max_level))
    logger.info(f"[CG] 主人（{uname or uid}）点名要第 {level} 张，好感度 {cur}")
    # 2026-10-19：**不能 await** —— 豆包出一张要 60~90s，而 on_message Hook 的超时是 60s。
    # 实测 00:29:07 报「HookHandler 执行超时，已超过 60000ms」+ 熔断计数 1/3。
    # 和里程碑 CG 一样丢后台，收消息这一层立刻返回。
    asyncio.create_task(handler._send_cg(uid, uname, sid, gid, cur, level, force=True))
    return True


# ---------------------------------------------------------------- 共同小工具

def _seg_mentions(segments: Any, bot_qq: str, bot_nick: str, depth: int = 0) -> bool:
    """在消息段（含 seglist 嵌套）里找"@了机器人"

    为什么要递归：NapCat 适配器的段结构是嵌套的（`seglist` 里套 `at`/`text`，
    合并转发更深），原来只扫一层 list，里面的 at 段根本看不到（2026-09-19 修）。
    """
    if depth > 6 or not segments:
        return False
    if isinstance(segments, (str, bytes)):
        return False
    if not isinstance(segments, (list, tuple)):
        segments = [segments]
    for seg in segments:
        if isinstance(seg, (list, tuple)):
            if _seg_mentions(seg, bot_qq, bot_nick, depth + 1):
                return True
            continue
        stype = str(getattr(seg, "type", "") or "")
        sdata = getattr(seg, "data", None)
        if stype in ("at", "text"):
            s = str(sdata or "")
            if bot_qq and (f":{bot_qq}>" in s or f"@{bot_qq}" in s or s.strip() == bot_qq):
                return True
            if bot_nick and s.strip() in (f"@{bot_nick}", bot_nick):
                return True
            if isinstance(sdata, dict):
                qq = str(sdata.get("qq") or sdata.get("user_id") or "")
                if qq and bot_qq and qq == bot_qq:
                    return True
        if stype == "seglist" and _seg_mentions(sdata, bot_qq, bot_nick, depth + 1):
            return True
    return False


def _mentioned_bot(message: MaiMessages, bot_qq: str, bot_nick: str) -> Tuple[bool, bool]:
    """返回 (是否@了机器人, 是否引用了消息)

    `message_base_info` 里没有 is_at 字段，所以从四处取：
      · **NapCat 适配器把 @ 转成了文本段**，格式是 `@<昵称:QQ号>`
        （`message_handler.py:411/417`），所以要按这个格式找 QQ 号；
      · 裸 `@QQ号`；
      · 段结构里的 at 段（含嵌套 seglist）；
      · 适配器写进 additional_config 的 `reply_message_id`：有它 = 这条是**引用回复**，
        而机器人正好是上一个说话的人。
    """
    # ⚠️ 这里必须用**原始**文本，不能用 clean() 的结果。
    # clean() 为了"别让引用前缀里的词参与判定"会把 `@<昵称:QQ>` 整段抹掉，
    # 于是这里永远找不到 QQ 号 —— 2026-09-18 踩过：mentioned 恒为 False，
    # 「@示例助手 好感度」不再被直接回答，ReactionHandler 的好感度加减也一起失效。
    #
    # 2026-09-24（1.2.5）：新版 payload **顶层直接给了 `is_mentioned` / `is_at`**，
    # 有它就信它（比抠文本格式可靠）；没有才回落到下面那套文本/段判定。
    text = str(message.plain_text or "")
    mentioned = bool(getattr(message, "is_mentioned", False) or getattr(message, "is_at", False))
    if bot_qq and (f":{bot_qq}>" in text or f"@{bot_qq}" in text):
        mentioned = True
    # @昵称 不带 QQ 号的情况（手工发、别的适配器）：整条只有"@昵称 + 一句话"时也算 @
    if not mentioned and bot_nick and f"@{bot_nick}" in text:
        mentioned = True
    if not mentioned and (bot_qq or bot_nick) and _seg_mentions(message.message_segments, bot_qq, bot_nick):
        mentioned = True
    # 诊断（2026-09-19）：有人 @ 它但没被认出来时，把原文打出来——别再靠猜格式
    if not mentioned and bot_nick and bot_nick in text:
        logger.warning(f"[好感度] 疑似 @ 但没认出来：text={text[:80]!r} "
                       f"segments={str(message.message_segments)[:120]!r}")
    quoted = bool((message.additional_data or {}).get("reply_message_id"))
    return mentioned, quoted


def _bot_ids() -> Tuple[str, str]:
    try:
        from src.config.config import global_config
        return (str(getattr(global_config.bot, "qq_account", "") or ""),
                str(getattr(global_config.bot, "nickname", "") or ""))
    except Exception:
        return "", ""


# ---------------------------------------------------------------- 管理员命令

# ⚠️ 2026-10-11 修正：旧版只认 `@<昵称:QQ号>` 这个格式，但 1.2.5 的
# `processed_plain_text` 把 @ 渲染成**纯文本 @昵称**（`message.py:process_at_component`
# 返回 `@备注名`，QQ 号在渲染时就丢了）。实测库里真实的文本长这样：
#     '@示例助手  生图5'      '@尼古拉斯·翠花  去dq坐😋'     '@小骑士 咪咪'
# 于是 `@某人 好感度 50` 永远抠不到目标 QQ，`_parse_target` 一路回落到发送者 ——
# 主人以为是给别人加好感，其实改的是自己（这条命令等于完全失效，用户 10-11 报障）。
# 正确做法是**从消息段里取 `target_user_id`**（段结构里一直带着真 QQ 号）：
#     {"type":"at","data":{"target_user_id":"1000000009","target_user_nickname":"示例助手"}}
# `_CMD_AT` 保留给"文本兜底"用（别处还在用，比如 `_looks_like_command`）。
_CMD_AT = re.compile(r"@<[^>]*?:(\d+)>")
_CMD_NUM = re.compile(r"[-+]?\d+")

# 从纯文本里找 `@昵称` 的兜底形状（段结构拿不到时才用）
_CMD_AT_PLAIN = re.compile(r"@([^\s@\[\]]+)")


def _iter_at_segments(segments: Any, depth: int = 0):
    """递归产出消息段里的所有 at 段（`seglist` 会嵌套，合并转发更深）。

    Args:
        segments: 段数组 / 单个段 / 嵌套列表。
        depth: 递归深度（防环）。

    Yields:
        Any: 每个 at 段对象或字典。
    """
    if depth > 6 or not segments:
        return
    if isinstance(segments, (str, bytes)):
        return
    if isinstance(segments, dict):
        # 已经是单个段字典
        if str(segments.get("type") or "") == "at":
            yield segments
        return
    if not isinstance(segments, (list, tuple)):
        segments = [segments]
    for seg in segments:
        if seg is None or isinstance(seg, (str, bytes)):
            continue
        if isinstance(seg, (list, tuple)):
            yield from _iter_at_segments(seg, depth + 1)
            continue
        stype = str(getattr(seg, "type", "") or (seg.get("type") if isinstance(seg, dict) else "") or "")
        sdata = getattr(seg, "data", None) if not isinstance(seg, dict) else seg.get("data")
        if stype == "at":
            if isinstance(sdata, dict):
                yield sdata
        elif stype == "seglist":
            yield from _iter_at_segments(sdata, depth + 1)


def _at_target_from_segments(segments: Any, skip_uids: Any = None) -> Tuple[str, str]:
    """从消息段里取**第一个"不是机器人"的** @ 的目标 QQ 和昵称。

    ⚠️ 这是 2026-10-11 新增的正确解法：`processed_plain_text` 只有 `@昵称`，
    真 QQ 号只存在于段结构的 `target_user_id` 里。

    ⚠️ 为什么要 `skip_uids`：命令的常见写法是「@机器人 好感度 @目标 50」——
    两个 @ 都在段里，**第一个是喊机器人**、第二个才是目标。不跳过的话
    会把目标认成机器人自己（2026-10-11 实测踩到，返回了 bot 自己的 QQ）。

    Args:
        segments: 消息段数组（`plugin._Seg` 对象列表或原始字典列表）。
        skip_uids: 要跳过的 QQ 号集合（一般是机器人自己，外加操作者）。

    Returns:
        Tuple[str, str]: `(QQ号, 昵称)`；没找到返回 `("", "")`。
    """
    skip = {str(x).strip() for x in (skip_uids or []) if str(x).strip()}
    for data in _iter_at_segments(segments):
        sid = str(data.get("target_user_id") or data.get("user_id") or data.get("qq") or "").strip()
        if not sid or sid in skip:
            continue
        name = str(
            data.get("target_user_cardname")
            or data.get("target_user_nickname")
            or ""
        ).strip()
        return sid, name
    return "", ""


def _split_first_at(text: str) -> Tuple[str, str]:
    """把命令参数里**第一个** `@昵称` 抠掉，同时返回它的昵称和剩下的部分。

    用途：从 `@小骑士 50` 里分离出"昵称=小骑士"和"参数=50"，
    这样逐字比对昵称时不会被后面的数字干扰。

    Args:
        text: 已剥掉命令词的参数串。

    Returns:
        Tuple[str, str]: `(昵称, 剩余参数)`；没有 @ 时昵称为空、剩余为原文。
    """
    t = _CMD_AT.sub(" ", str(text or ""))          # 先干掉带 QQ 号的旧格式
    m = _CMD_AT_PLAIN.search(t)
    if not m:
        return "", t
    name = m.group(1).strip()
    rest = (t[:m.start()] + " " + t[m.end():]).strip()
    return name, rest


def _strip_first_at_nick(text: str) -> str:
    """把参数里的第一个 `@昵称` 抹掉，只留数值部分。

    为什么单独抽一个：`_CMD_NUM.findall` 会从 `@小骑士 50` 里正确取到 50，
    但如果昵称本身带数字（比如 `@233三`），就会把 233 当成人要设的数值。
    先把 @昵称 整段抹掉，再找数字才安全。

    Args:
        text: 命参数串。

    Returns:
        str: 抹掉第一个 @昵称 之后的串。
    """
    _name, rest = _split_first_at(text)
    return rest


def _has_at_mark(text: str) -> bool:
    """参数里是否**明确指定了某人**（带 QQ 号的旧格式，或纯文本 @昵称）。

    用来区分「好感度 重置」的两种含义：
      · 带 @ → 只重置那一个人；
      · 不带 @ → 重置所有人。

    Args:
        text: 参数串。

    Returns:
        bool: 指定了 @ 返回 True。
    """
    if not text:
        return False
    if _CMD_AT.search(text):
        return True
    return bool(_CMD_AT_PLAIN.search(text))


def _is_admin(uid: str, cfg) -> bool:
    """谁能用管理命令：插件配置 `behavior_score.admin_qq`（默认机器人主人）"""
    admins = cfg.get("admin_qq") if isinstance(cfg, dict) else None
    if not admins:
        admins = ADMIN_QQ
    if isinstance(admins, str):
        admins = [x.strip() for x in admins.replace("，", ",").split(",") if x.strip()]
    return str(uid) in [str(a) for a in admins]


def _is_admin_of(handler_obj: Any, uid: str) -> bool:
    """从处理器/命令对象身上取插件配置判管理员（两种入口共用一套 admin_qq）"""
    cfg = getattr(handler_obj, "plugin_config", None)
    inner = (cfg or {}).get("behavior_score", {}) if isinstance(cfg, dict) else {}
    return _is_admin(uid, inner if isinstance(inner, dict) else {})


def _looks_like_command(text: str) -> bool:
    """这条消息是不是在发管理命令（命令不该被算成"聊天"）"""
    t = clean(text)
    t = _CMD_AT.sub("", t)          # 去掉 @<昵称:QQ号>
    t = re.sub(r"^@\S*\s*", "", t)  # 去掉开头的 @机器人
    return t.lstrip("/")[:3] in ("好感度", "表现分")


def _parse_target(
    text: str,
    sender_uid: str,
    segments: Any = None,
) -> Tuple[str, str]:
    """从命令里抠出目标 QQ；没写目标就是操作者自己。

    ⚠️ 2026-10-11 重写。旧版只认 `@<昵称:QQ号>`，但 1.2.5 把 @ 渲染成 `@昵称`、
    真 QQ 号只留在**消息段**里 —— 于是「@某人 好感度 50」永远抠不到目标，
    一路回落到发送者，主人给自己加了分还以为在给别人加（用户报障的根因）。

    现在的解析顺序（从最可靠往下退）：
      1. **消息段里的 at 段**（`target_user_id`）—— 这才是真 QQ 号，首选；
      2. 文本里的 `@<昵称:QQ号>` —— 旧格式，某些适配器还会用；
      3. 文本里的 `@昵称` —— 拿昵称去 `person_info` 反查 QQ；
      4. 都没有 → 操作者自己。

    ⚠️ 第 3 步的反查**必须命中唯一一个人**才认，重名就放弃（宁可回落到自己，
    也别把好感度加到陌生人头上）。

    Args:
        text: 命令参数串（已去掉命令词）。
        sender_uid: 发送者 QQ，兜底用。
        segments: 消息段数组，用来取 `target_user_id`。

    Returns:
        Tuple[str, str]: `(目标QQ, 昵称)`；昵称可能为空。
    """
    raw = str(text or "")

    # ---- 1) 消息段优先：拿真 QQ 号 ----
    # ⚠️ 跳过机器人自己：命令通常写成「@机器人 好感度 @目标 50」，段里有**两个** at，
    #    第一个是喊机器人、第二个才是目标。另外文本里已经出现过的 @昵称（目标）
    #    也要在文本里再确认一次，避免把"喊机器人"那个当成目标。
    bot_qq, bot_nick = _bot_ids()
    skip = {bot_qq} if bot_qq else set()
    seg_uid, seg_name = _at_target_from_segments(segments, skip)
    if seg_uid:
        # 段里的 QQ 号是权威的，昵称顺带记一下（落库时写进 name 字段）
        return seg_uid, seg_name

    # ---- 2) 旧格式 @<昵称:QQ号> ----
    m = _CMD_AT.search(raw)
    if m:
        return m.group(1), ""

    # ---- 3) 纯文本 @昵称：反查 QQ ----
    text_nick, _rest = _split_first_at(raw)
    if text_nick and text_nick != bot_nick:
        uid = _lookup_uid_by_name(text_nick)
        if uid:
            return uid, text_nick

    return str(sender_uid), ""


def _lookup_uid_by_name(name: str) -> str:
    """按昵称/群名片反查 QQ 号（只认唯一命中，重名返回空）。

    数据源是麦麦的 `person_info` 表：`user_nickname` 是全局昵称，
    `group_cardname` 是群名片（JSON 数组），两个都比对一下。

    Args:
        name: 要查的昵称。

    Returns:
        str: 唯一命中的 QQ 号；查不到或有多个同名的返回空串。
    """
    name = str(name or "").strip()
    if not name:
        return ""
    try:
        db_path = os.path.join(ROOT, "data", "MaiBot.db")
        if not os.path.exists(db_path):
            return ""
        import sqlite3

        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        try:
            con.execute("PRAGMA busy_timeout=3000")
            rows = con.execute(
                "SELECT user_id, user_nickname, group_cardname FROM person_info "
                "WHERE user_nickname = ? OR group_cardname LIKE ?",
                (name, f"%{name}%"),
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[好感度] 按昵称反查 QQ 失败: {type(exc).__name__}: {exc}")
        return ""

    hits = set()
    for uid, nickname, cards in rows:
        uid = str(uid or "").strip()
        if not uid:
            continue
        if str(nickname or "").strip() == name:
            hits.add(uid)
            continue
        # 群名片是 JSON 数组：[{"group_id":…,"group_cardname":…}]
        try:
            import json

            for card in json.loads(cards or "[]") or []:
                if isinstance(card, dict) and str(card.get("group_cardname") or "").strip() == name:
                    hits.add(uid)
                    break
        except Exception:  # noqa: BLE001
            continue
    if len(hits) == 1:
        return hits.pop()
    if len(hits) > 1:
        logger.warning(f"[好感度] 昵称 {name!r} 命中多个 QQ，放弃反查：{sorted(hits)}")
    return ""




def render_feeding_card(food: str, delta: int, score: int, item: str = "", category: str = "") -> str:
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    font = lambda size: ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    item = item or ("吐司" if food == "吐司" else "小点心")
    canvas = Image.new("RGB", (900, 850), "#fff3e3")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((30,30,870,820),radius=30,fill="#fffdf8",outline="#dfc4a3",width=2)
    draw.text((76,65),"投食时间",font=font(46),fill="#705045")
    if item == "猫条":
        draw.rounded_rectangle((395,170,505,390),radius=12,fill="#b8cdbb",outline="#738f78",width=3)
        draw.rectangle((395,170,505,205),fill="#e6dcc8")
        draw.rectangle((395,350,505,390),fill="#e6dcc8")
        draw.text((410,240),"猫条",font=font(32),fill="#4b6650")
    elif item == "吐司":
        draw.rounded_rectangle((330,175,570,410),radius=60,fill="#bc7842",outline="#97592e",width=4)
        draw.rounded_rectangle((350,193,550,390),radius=48,fill="#ffe7b2")
        draw.ellipse((292,395,608,425),fill="#ead6bc")
    elif category == "饮品":
        draw.rounded_rectangle((370,185,530,400),radius=22,fill="#d2e4df",outline="#829c96",width=4)
        draw.rectangle((382,235,518,380),fill="#b8d3c3")
        draw.line((460,300,470,155,530,155),fill="#b98a64",width=9)
    elif category == "水果":
        draw.ellipse((345,215,555,405),fill="#eeb46b",outline="#c58d4c",width=3)
        draw.ellipse((440,175,520,220),fill="#9cb384")
    else:
        draw.ellipse((302,200,598,345),fill="#e9cfab",outline="#b89979",width=3)
        colors=("#d4a06a","#9caf7b","#e6bd77","#bb8b68")
        for i,(x,y) in enumerate(((365,250),(435,240),(515,265),(395,300),(470,305))):
            draw.ellipse((x-30,y-23,x+30,y+23),fill=colors[i%4])
        draw.chord((302,235,598,425),0,180,fill="#d0c5b3",outline="#9f9584",width=3)
    label_face=font(42)
    x=max(76,(900-label_face.getlength(item))/2)
    draw.text((x,445),item,font=label_face,fill="#76563e")
    draw.text((76,525),"（接住，嚼嚼）",font=font(36),fill="#735b4c")
    draw.text((76,590),f"好感度 +{delta}",font=font(54),fill="#b76d45")
    draw.text((80,675),f"当前好感度：{score}",font=font(29),fill="#806953")
    draw.text((80,755),"今日投食已领取 · 投食与吐司每天共一次",font=font(23),fill="#a38a73")
    output = BytesIO()
    canvas.save(output,format="PNG",optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")
