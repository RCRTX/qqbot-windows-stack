
"""QQ bot stack component."""


















from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import ssl
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIBOT_DIR = os.path.join(os.environ.get("MAIBOT_HOME") or os.path.join(REPO_ROOT, "bot", "MaiBotOneKey"), "modules", "MaiBot")
MAIBOT_DB = os.path.join(MAIBOT_DIR, "data", "MaiBot.db")


DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


FETCH_TIMEOUT = 12
CACHE_TTL = 300.0

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")



SOURCES = [
    {"id": "bili", "name": "B站热搜", "kind": "json_keys",
     "url": "https://api.bilibili.com/x/web-interface/search/square?limit=30",
     "keys": ("keyword",)},
    {"id": "yystv", "name": "游研社", "kind": "rss",
     "url": "https://www.yystv.cn/rss/feed"},
    {"id": "gcores", "name": "机核", "kind": "rss",
     "url": "https://www.gcores.com/rss"},
    {"id": "baidu", "name": "百度热搜", "kind": "json_keys",
     "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime",
     "keys": ("word", "query")},
    {"id": "douyin", "name": "抖音热榜", "kind": "json_keys",
     "url": "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
     "keys": ("word",)},
    {"id": "weibo", "name": "微博热搜", "kind": "json_keys",
     "url": "https://api.codelife.cc/api/top/list?lang=cn&id=KqndgxeLl9",
     "keys": ("title",)},
]


GAME_KW = (
    "游戏", "手游", "端游", "网游", "steam", "主机", "ps5", "switch", "xbox", "任天堂",
    "索尼", "米哈游", "原神", "崩坏", "星穹铁道", "绝区零", "鸣潮", "明日方舟", "碧蓝",
    "英雄联盟", "lol", "王者荣耀", "kpl", "lpl", "dota", "csgo", "cs2", "无畏契约",
    "瓦罗兰特", "永劫无间", "黑神话", "塞尔达", "宝可梦", "我的世界", "蛋仔",
    "电竞", "战队", "选手", "赛季", "版本", "开服", "公测", "联动", "皮肤", "卡池",
    "抽卡", "up池", "复刻", "测试服", "内测", "爆料", "dlc", "更新",
)
MATCH_KW = (
    "比赛", "决赛", "半决赛", "四强", "八强", "季后赛", "常规赛", "小组赛", "联赛",
    "杯赛", "夺冠", "冠军", "亚军", "晋级", "淘汰", "连胜", "连败", "对战", "对阵",
    "转会", "复出", "退役", "教练", "战队", "选手", "msi", "s赛", "全球总决赛",
)
ANIME_KW = (
    "动漫", "番剧", "新番", "动画", "漫画", "轻小说", "galgame", "声优", "手办",
    "同人", "cos", "漫展", "剧场版", "ova", "二次元", "国漫", "日漫", "b站",
    "哔哩哔哩", "鬼灭", "咒术", "间谍过家家", "进击的巨人", "fate", "高达", "eva",
    "初音", "vtuber", "虚拟主播", "hololive", "宫崎骏", "京阿尼", "骨头社",
)
MEME_KW = (
    "梗", "热梗", "笑死", "离谱", "整活", "发疯", "抽象", "破防", "绷不住",
    "塌房", "社死", "上分", "名场面", "爆火", "出圈", "玩梗", "复读",
)


BAD_KW = (
    "去世", "死亡", "遇难", "车祸", "事故", "杀人", "强奸", "自杀", "跳楼", "诈骗",
    "判刑", "落马", "被捕", "地震", "洪水", "疫情", "火灾", "战争", "导弹", "袭击",
    "离婚", "出轨", "性侵", "吸毒", "赌博", "贷款", "兼职", "招聘", "优惠券",
)


def _kw_hit(text, kws):
    low = text.lower()
    return sum(1 for k in kws if k in low)


def score_title(title):
    """QQ bot stack component."""
    t = str(title or "").strip()
    if not t:
        return -99
    s = _kw_hit(t, GAME_KW) * 3 + _kw_hit(t, MATCH_KW) * 3 + _kw_hit(t, ANIME_KW) * 3
    s += _kw_hit(t, MEME_KW) * 2
    s -= _kw_hit(t, BAD_KW) * 6
    if len(t) < 4 or len(t) > 40:
        s -= 2                      
    return s



def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout,
                                  context=ssl.create_default_context())


def _get(url, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://www.bilibili.com/",
    })
    with _open(req, timeout) as r:
        return r.read().decode("utf-8", "replace")


def _collect(obj, keys, out, depth=0):
    """QQ bot stack component."""
    if depth > 8 or len(out) > 400:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and 2 <= len(v.strip()) <= 60:
                out.append(v.strip())
            else:
                _collect(v, keys, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, keys, out, depth + 1)


_TAG_RE = re.compile(r"<[^>]+>")


def _rss_titles(text):
    out = []
    for m in re.finditer(r"<item\b.*?</item>", text, re.S | re.I):
        t = re.search(r"<title>(.*?)</title>", m.group(0), re.S | re.I)
        if not t:
            continue
        title = t.group(1)
        title = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", title.strip())
        title = _TAG_RE.sub("", title).strip()
        if title:
            out.append(title)
    return out


def fetch_source(src, timeout=FETCH_TIMEOUT):
    """QQ bot stack component."""
    try:
        body = _get(src["url"], timeout)
        if src.get("kind") == "rss":
            titles = _rss_titles(body)
        else:
            titles = []
            _collect(json.loads(body), tuple(src.get("keys") or ()), titles)
    except Exception:
        return []
    name = src["name"]
    seen, out = set(), []
    for t in titles:
        key = t.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, name))
    return out


_CACHE = {"ts": 0.0, "items": [], "lock": threading.Lock()}


def hot_topics(force=False, timeout=FETCH_TIMEOUT):
    """QQ bot stack component."""




    now = time.time()
    with _CACHE["lock"]:
        if not force and _CACHE["items"] and now - _CACHE["ts"] < CACHE_TTL:
            return list(_CACHE["items"])
    rows = []
    try:
        with ThreadPoolExecutor(max_workers=min(6, len(SOURCES))) as ex:
            for part in ex.map(lambda s: fetch_source(s, timeout), SOURCES):
                rows.extend(part)
    except Exception:
        pass
    items, seen = [], set()
    for title, source in rows:
        if title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "source": source, "score": score_title(title)})
    items.sort(key=lambda i: -i["score"])
    with _CACHE["lock"]:
        if items:
            _CACHE["items"] = items
            _CACHE["ts"] = now
        elif _CACHE["items"]:
            return list(_CACHE["items"])
    return items


def pick_candidates(items, n=12, used=(), rng=None, per_source=None):
    """QQ bot stack component."""







    rng = rng or random
    skip = {str(x) for x in (used or [])}
    pool = [i for i in items if i["title"] not in skip and i["score"] > -6]
    if not pool:
        pool = [i for i in items if i["score"] > -6]
    if not pool:
        pool = list(items)
    pool = sorted(pool, key=lambda i: -i["score"])       
    want = max(n * 2, n)
    cap = int(per_source or max(2, n // 3))
    head, count = [], {}
    for it in pool:
        src = str(it.get("source") or "")
        if count.get(src, 0) >= cap:
            continue
        count[src] = count.get(src, 0) + 1
        head.append(it)
        if len(head) >= want:
            break
    if len(head) < n:                                    
        head = pool[:want]
    head = head[:n]
    
    
    
    rng.shuffle(head)
    return head



def llm_ready(llm):
    return bool(str((llm or {}).get("api_base") or "").strip()
                and str((llm or {}).get("api_key") or "").strip())





LAST_ERROR = {"msg": "", "at": 0.0}


def chat(llm, system, user, max_tokens=160, temperature=1.05, timeout=45):
    """QQ bot stack component."""



    base = str((llm or {}).get("api_base") or "").strip().rstrip("/")
    key = str((llm or {}).get("api_key") or "").strip()
    model = str((llm or {}).get("model") or "").strip() or DEFAULT_MODEL
    if not base or not key:
        LAST_ERROR.update(msg="没有配置 api_base/api_key", at=time.time())
        return ""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with _open(req, timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        content = str((d.get("choices") or [{}])[0].get("message", {}).get("content") or "")
        if not content.strip():
            LAST_ERROR.update(msg=f"模型返回空内容（finish_reason="
                                  f"{(d.get('choices') or [{}])[0].get('finish_reason')}）",
                              at=time.time())
        return content
    except Exception as e:  
        LAST_ERROR.update(msg=f"{type(e).__name__}: {e}"[:200], at=time.time())
        return ""


_QUOTE_CHARS = "\"'“”‘’「」【】 \t\r\n"




_JUNK_CHARS_RE = re.compile(r"[\"'‘’“”`*_#|/\\·]")



_TAIL_PUNCT_RE = re.compile(r"[。.\s、,，;；:：!！?？\-—~～]+$")





_CODE_JUNK_RE = re.compile(r"[a-z][A-Z]|[a-z]_[a-z]|[;{}()<>]")


_BROKEN_PUNCT_RE = re.compile(r"([，,、])\s*[.。]")


def clean_line(text, limit=70):
    """QQ bot stack component."""
    t = str(text or "").strip()
    if not t:
        return ""
    t = re.split(r"\n+", t)[0].strip()          
    t = t.strip(_QUOTE_CHARS)
    t = re.sub(r"^(回复|回答|开场白|话题)[:：]\s*", "", t)
    t = _JUNK_CHARS_RE.sub("", t)               
    t = t.replace("**", "").replace("`", "")
    t = re.sub(r"\s{2,}", " ", t)
    t = _BROKEN_PUNCT_RE.sub(r"\1", t)          
    t = _TAIL_PUNCT_RE.sub("", t)
    return t[:limit].strip()


_PERSONA = "你在 QQ 群「{group}」中自然交流，依据当前话题简洁发言，不编造事实。"




MACHINE_WORDS = (
    "热搜", "资讯", "据报道", "据悉", "消息称", "网友", "引发热议", "值得一提",
    "首先", "其次", "总而言之", "不得不说", "堪称", "可以说是", "让人不禁",
    "这操作绝了", "真是绝了", "终于开窍", "属实离谱", "真的离谱", "直接裂开",
    "防到玩家头上", "令人", "引发关注", "登上热搜",
    
    
    "赶紧下载", "快来下载", "值得一试", "不容错过", "千万别错过", "快去",
    "推荐大家", "点击下方", "抓紧时间", "限时",
)


SERVICE_WORDS = ("感谢", "很高兴", "很荣幸", "有什么可以帮", "希望对你有帮助",
                 "综上所述", "总的来说", "作为一个", "身为AI", "我是AI", "我是人工智能")


def trim_smart(text, limit=32):
    """QQ bot stack component."""







    t = str(text or "").strip()
    if limit <= 0 or len(t) <= limit:
        return t
    head = t[:limit]
    cut = max(head.rfind("，"), head.rfind(","), head.rfind("、"))
    if cut >= 8:
        return head[:cut].strip(" ，,、")
    return head.rstrip(" ，,、")




ASK_RE = re.compile(r"[?？]|吗[，。！~～\s]?$|怎么|为啥|为什么|咋|多少|几个|哪个|哪部|哪款|"
                    r"推荐|值不值|好不好|该不该|要不要|能不能|是不是|有没有|求")


def is_asking(lines):
    """QQ bot stack component."""
    return any(ASK_RE.search(str(x)) for x in (lines or [])[-3:])


def looks_human(text, limit=32, extra_bad=()):
    """QQ bot stack component."""






    t = str(text or "").strip()
    if len(t) < 8:
        return False
    
    if _JUNK_CHARS_RE.search(t):
        return False
    
    if _CODE_JUNK_RE.search(t):
        return False
    if limit and limit > 0 and len(t) > limit:
        return False
    if "。" in t or "；" in t:
        return False
    if t.count("，") + t.count(",") + t.count("、") >= 4:
        return False
    if t.endswith("？") or t.endswith("?"):
        return False
    for w in tuple(MACHINE_WORDS) + tuple(SERVICE_WORDS) + tuple(extra_bad):
        if w and w in t:
            return False
    return True


def bad_reason(text, limit=32):
    """QQ bot stack component."""




    t = str(text or "").strip()
    out = []
    if _JUNK_CHARS_RE.search(t):
        out.append("混进了引号/斜杠/管道这类格式残片，重说一遍干净的")
    if _CODE_JUNK_RE.search(t):
        out.append("混进了代码一样的东西（handleSubmit 那种），群里没人这么打字")
    if limit and limit > 0 and len(t) > limit:
        out.append(f"太长了（{len(t)} 字，群里人一条才十来个字，要 {limit} 字以内）")
    if "。" in t or "；" in t:
        out.append("用了句号/分号，群里打字不打句号")
    if t.count("，") + t.count(",") + t.count("、") >= 4:
        out.append("逗号堆太多了，读着像写文章")
    if t.endswith("？") or t.endswith("?"):
        out.append("拿问号结尾了")
    for w in tuple(MACHINE_WORDS) + tuple(SERVICE_WORDS):
        if w in t:
            out.append(f"用了「{w}」这种资讯号/客服的词")
            break
    return "；".join(out) if out else "不像群里随口说的话"


def _style_block(examples):
    """QQ bot stack component."""

    if not examples:
        return ""
    lines = "\n".join(f"  {t}" for t in examples)
    return ("\n【你平时在群里是这么说话的 —— 照着这个手感，别照抄内容】\n"
            f"{lines}\n")


_OPEN_SYS = _PERSONA + """{style}
现在群里冷场了，你想主动扔个话头。会给你一批刚在网上刷到的实时热点，
挑一条你最想聊的，写成一句**你在群里随口说的话**。

【必须做到】
- **15~28 字**（群里人一条才十来个字，写长了很显眼），最多两句
- **一个句号都不要**，用逗号断，或者干脆不断
- 带上你自己的东西：你的经历（"我以前拼过类似的"）、你的口味（"我就吃这种"）、
  你的吐槽（"属于是…"）—— 光把热点复述一遍不算
- 语气词**一条最多带一个**：笑死 / 是吧 / 那确实 / 行吧 / 好家伙。别每条都加，
  更别把这些当成必须撒的调料（尤其别句句都以「喵」结尾）

【千万别】
- 别像游戏资讯号或评测号。反面例子：
  「索尼这操作绝了，中签PS5 Pro还得先玩满60小时，防黄牛防到玩家头上，我直接裂开」
  —— 这是自媒体句式，群里没人这么说话
- 别复述热点信息（谁干了什么、多少钱、什么时候）
- 别说「大家」「有人吗」「你们知道吗」，别 @ 人，别自我介绍，别说自己在上网看
- 别用问号结尾，别用「首先/其次/总之/值得一提/引发热议/据悉」

【反例 → 正例】
反例：火线迈阿密8块4是真的离谱，死到红温还停不下手，这游戏配乐一响我就知道又要重来了
正例：8块4的火线迈阿密我昨晚又死了两百次，纯纯有毒，删是不可能删的
反例：高达模型现在不用额外工具就能顺畅拼了，万代终于开窍了啊
正例：拼高达终于不用翻工具箱了，我那盒吃灰半年的可以拿出来了
反例：英雄联盟全球总决赛赛制说明公布，今年取消了瑞士轮
正例：今年s赛没瑞士轮了？那入围赛加小组赛得打到什么时候去，选手怕是要熬秃

输出格式（必须严格遵守，就一行）：
序号|开场白
其中「序号」是你选的那条热点在上面列表里的编号。比如：3|这版本抽卡概率是不是又暗改了
除了这一行什么都不要输出。"""

_OPEN_RETRY = """

⚠️ 你刚才写的那句不合格：{bad}
原句是：「{old}」
重写一句：{limit} 字以内、不要句号、别复述热点、像群里随口说的。还是「序号|开场白」一行。"""

_REPLY_SYS = _PERSONA + """{style}
你刚才在群里扔了个话头，现在有人接话了。回他一句。

【必须做到】
- **先接住他刚说的那句**（可以顺一下他的词、他的外号），再给你自己的东西
- **15~35 字**（群里人一条才十来个字），最多两句，**一个句号都不要**
- 要给具体内容：作品名 / 角色 / 哪场比赛 / 什么梗 / 你自己的判断或经历
- 你懂的东西直接说，别说自己在查资料、上网搜、问别人
- 语气词**一条最多带一个**：笑死 / 是吧 / 那确实 / 行吧 / 好家伙。别每条都加

【千万别】
- 别说「挺有意思的」「还不错」「长知识了」这种空话
- 别说「感谢」「很高兴」「有什么可以帮你的」这种客服腔
- 别列一二三点，别用问号结尾，别说自己是 AI
- 别人发一大段，只挑最有意思的那一个点回，别逐条点评、别复述他说的

【反例 → 正例】
反例：感谢分享，这个游戏确实很有意思，我也很喜欢这种需要反复尝试的玩法
正例：这游戏我也死到麻了，不过配乐一响就又坐回去了，属于是被PUA了

直接输出回复内容本身：不要引号、不要解释。"""


def _candidate_block(items):
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it.get('source', '网络')}] {it.get('title', '')}")
    return "\n".join(lines)


def make_opening(llm, items, group_name="", used=(), rng=None, timeout=45,
                 examples=None):
    """QQ bot stack component."""







    rng = rng or random
    cands = pick_candidates(items, 12, used, rng)
    if not cands:
        return "", ""
    if examples is None:
        examples = style_examples(rng=rng)
    sys_prompt = _OPEN_SYS.format(group=group_name or '群',
                                  style=_style_block(examples))
    user = (f"群名：{group_name or '（未知）'}\n\n实时热点：\n{_candidate_block(cands)}\n\n"
            "挑一条写开场白。")
    best, best_title, fb = "", "", ""
    for attempt in range(2):
        raw = chat(llm, sys_prompt, user + fb, max_tokens=180, timeout=timeout)
        if not raw:
            continue
        idx, body = 0, raw
        m = re.match(r"^\s*(\d{1,2})\s*[|｜:：,，]\s*(.+)$",
                     raw.strip().split("\n")[0].strip())
        if m:
            idx, body = int(m.group(1)), m.group(2)
        text = clean_line(body, 200)          
        if text and looks_human(text, 32):
            title = cands[idx - 1]["title"] if 1 <= idx <= len(cands) else ""
            return text, title
        if text and not best:
            best = text                                    
            best_title = cands[idx - 1]["title"] if 1 <= idx <= len(cands) else ""
        fb = _OPEN_RETRY.format(bad=bad_reason(text, 32), old=str(text)[:60], limit=26)
    return trim_smart(best, 32), best_title


def make_reply(llm, topic_text, topic_title, lines, group_name="", timeout=45,
               examples=None, rng=None):
    """QQ bot stack component."""





    if not lines:
        return ""
    asking = is_asking(lines)
    limit = 0 if asking else 42
    if examples is None:
        examples = style_examples(rng=rng)
    sys_prompt = _REPLY_SYS.format(group=group_name or '群',
                                   style=_style_block(examples))
    if asking:
        sys_prompt += ("\n\n⚠️ 对方是在**问你问题**：这次**不看字数**，把问题答全、答清楚为止 ——"
                       "该列式子列式子、该比较一样样比、该说清楚就说完，宁可写长也不能答不全或者糊弄。")
    ctx = "\n".join(f"- {str(x)[:120]}" for x in lines[-6:])
    base_user = (f"群名：{group_name or '（未知）'}\n"
                 f"你扔的话头：{str(topic_text)[:120]}\n"
                 f"（背景热点：{str(topic_title)[:80] or '无'}）\n\n"
                 f"群友刚才说的话（最后一条是你要接的）：\n{ctx}\n\n写你的回复。")
    best, fb = "", ""
    for _ in range(2):
        text = clean_line(chat(llm, sys_prompt, base_user + fb,
                               max_tokens=400 if asking else 200, timeout=timeout), 200)
        if text and looks_human(text, limit, extra_bad=("挺有意思", "还不错", "长知识")):
            return text
        if text and not best:
            best = text
        tail = "不要句号，别客套。" if asking else "重写一句，15~35 字，不要句号，别客套。"
        fb = f"\n\n⚠️ 刚才那句不合格：{bad_reason(text, limit)}。原句是「{str(text)[:60]}」。{tail}"
    return trim_smart(best, limit)



def _db():
    if not os.path.isfile(MAIBOT_DB):
        return None
    try:
        return sqlite3.connect(f"file:{MAIBOT_DB}?mode=ro".replace("\\", "/"),
                               uri=True, timeout=3)
    except Exception:
        return None


def bot_qq(default=""):
    """QQ bot stack component."""
    con = _db()
    if con is None:
        return default
    try:
        row = con.execute("SELECT account_id FROM bot_platform_accounts "
                          "WHERE platform='qq' AND (disabled=0 OR disabled IS NULL) "
                          "ORDER BY last_seen_at DESC LIMIT 1").fetchone()
        return str(row[0]) if row and row[0] else default
    except Exception:
        return default
    finally:
        con.close()



_QUOTE_PREFIX = re.compile(
    r"^\s*(?:\[(?:回复了[^\]]*?|回复消息[^\]]*?|回复[^\]]*?)\]|【合并转发消息[:：]?[^】]*】)\s*")


def _own_text(raw):
    """QQ bot stack component."""








    t = str(raw or "").strip()
    if "]" in t:
        t = t[t.rfind("]") + 1:].strip()
    elif " " in t:
        t = t[t.rfind(" ") + 1:].strip()
    return _QUOTE_PREFIX.sub("", t).strip()


def style_examples(n=12, rng=None, lo=10, hi=55, bot=None):
    """QQ bot stack component."""




    rng = rng or random
    bot = str(bot or bot_qq())
    con = _db()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT processed_plain_text FROM mai_messages WHERE user_id=? "
            "AND group_id IS NOT NULL AND processed_plain_text IS NOT NULL "
            "ORDER BY id DESC LIMIT 400", (bot,)).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    out, seen = [], set()
    for (raw,) in rows:
        t = _own_text(raw)
        if not t or t[0] in "[【":
            continue
        if re.match(r"^@\S*\s*$", t) or "Error occurred" in t:
            continue
        
        if re.search(r"[\[\]【】]|https?://|www\.", t):
            continue
        
        
        if " " in t or "\u3000" in t:
            continue
        if re.search(r"\[图片|\[表情|\[语音|\[视频|\[文件", t):
            continue
        if not (lo <= len(t) <= hi):
            continue
        key = t[:10]
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    rng.shuffle(out)
    return out[:int(n)]


def group_name_of(gid, default=""):
    """QQ bot stack component."""
    con = _db()
    if con is None:
        return default
    try:
        row = con.execute("SELECT group_name FROM mai_messages WHERE group_id=? "
                          "AND group_name IS NOT NULL AND group_name<>'' "
                          "ORDER BY id DESC LIMIT 1", (str(gid),)).fetchone()
        return str(row[0]) if row and row[0] else default
    except Exception:
        return default
    finally:
        con.close()


def _ts_of(text):
    t = str(text or "").strip()
    if len(t) < 19:
        return 0.0
    try:
        return time.mktime(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0.0


def messages_since(gid, since_ts, exclude_user=None, limit=20):
    """QQ bot stack component."""



    con = _db()
    if con is None:
        return []
    bound = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(max(0.0, since_ts - 1)))
    
    
    
    
    if not exclude_user:
        try:
            exclude_user = bot_qq()
        except Exception:                               
            exclude_user = None
    try:
        rows = con.execute(
            "SELECT timestamp, user_id, user_nickname, processed_plain_text "
            "FROM mai_messages WHERE group_id=? AND datetime(timestamp) > datetime(?) "
            "ORDER BY id DESC LIMIT ?", (str(gid), bound, int(limit))).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    rows = list(reversed(rows))                          
    out = []
    for ts, uid, nick, text in rows:
        uid = str(uid or "")
        if exclude_user and uid == str(exclude_user):
            continue
        body = str(text or "").strip()
        if not body or body.startswith("[图片"):
            continue
        out.append({"ts": _ts_of(ts), "text": body, "user": uid, "nick": str(nick or "")})
    return out


def bot_spoke_since(gid, since_ts, bot=None):
    """QQ bot stack component."""
    con = _db()
    if con is None:
        return False
    bound = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(max(0.0, since_ts - 1)))
    try:
        row = con.execute(
            "SELECT 1 FROM mai_messages WHERE group_id=? AND user_id=? "
            "AND datetime(timestamp) > datetime(?) LIMIT 1",
            (str(gid), str(bot or bot_qq()), bound)).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        con.close()



def in_quiet_hours(now, start=0, end=8):
    """QQ bot stack component."""
    try:
        s, e = int(start), int(end)
    except Exception:
        return False
    if s == e:
        return False
    h = time.localtime(now).tm_hour
    if s < e:
        return s <= h < e
    return h >= s or h < e


def roll_gap(gap_min=120, gap_max=240, rng=None):
    """QQ bot stack component."""
    rng = rng or random
    lo, hi = int(gap_min or 120), int(gap_max or 240)
    if hi < lo:
        lo, hi = hi, lo
    return rng.randint(lo, hi) * 60


def should_use_topic(prob=0.8, rng=None):
    """QQ bot stack component."""
    rng = rng or random
    try:
        p = float(prob)
    except Exception:
        p = 0.8
    return rng.random() < max(0.0, min(1.0, p))
