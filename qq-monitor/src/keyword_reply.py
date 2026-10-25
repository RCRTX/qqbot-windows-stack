
"""QQ bot stack component."""
























from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from src.logger import setup_logger
from src.quirky_pool import DEFAULT_MAX_CHARS, DEFAULT_POOL_FILE, QuirkyPool, blocked_reason, pool_path

logger = setup_logger("keyword_reply")


CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "keyword_reply.json")




DEFAULT_FOOD_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "foods.json")


DEFAULT_FOOD_TEMPLATE = "建议吃{food}！"



SING_TOGGLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "sing_groups.json")


SING_ADMIN_ONLY = False


DEFAULT_COOLDOWN = 60





QUIRKY_KEYWORDS = [
    "怪话", "文案", "随机文案", "随机怪话", "来句怪话", "说句怪话", "来段怪话", "整段怪话", "随机一句", "来点怪的", "来段文案", "整点怪话",
    "随机来一句", "来一句", "来一段", "整段活", "说个怪话", "讲个怪话", "来个怪话", "来点怪话", "来句", "说怪话", "讲怪话", "怪话呢", "整个活",
    "整点活", "来活", "来活儿", "发癫", "来点乐子", "随便说点", "说点什么",
]


def default_config():
    return {"enabled": False, "groups": [], "rules": [], "mention": False, "cooldown_seconds": 60, "quirky_file": "", "max_chars": 0}


def message_text(message: Dict[str, Any]) -> str:
    """QQ bot stack component."""










    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, dict) and content.get("text"):
        return str(content["text"])
    if message.get("text"):
        return str(message["text"])
    return str(message.get("raw_message") or "")


def at_targets(message: Dict[str, Any]) -> List[str]:
    """QQ bot stack component."""




    if not isinstance(message, dict):
        return []
    out: List[str] = []
    content = message.get("content")
    if isinstance(content, dict):
        for seg in (content.get("segments") or []):
            if isinstance(seg, dict) and seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq") or "").strip()
                if qq:
                    out.append(qq)
    raw = str(message.get("raw_message") or "").replace(" ", "")
    for chunk in raw.split("[CQ:at,qq=")[1:]:
        qq = chunk.split("]")[0].strip()
        if qq:
            out.append(qq)
    return out


def mentioned_bot(message: Dict[str, Any], bot_qq: Any) -> bool:
    """QQ bot stack component."""
    bot = str(bot_qq or "").strip()
    if not bot:
        return False
    return bot in at_targets(message)


def rule_type(rule: Dict[str, Any]) -> str:
    """QQ bot stack component."""











    t = str((rule or {}).get("type") or "text").strip().lower()
    return t if t in ("quirky", "food", "favor", "learn", "mylearn",
                      "sing", "groupon", "study", "reflect") else "text"









KNOWN_RULE_TYPES = ("quirky", "food", "favor", "learn", "mylearn", "sing", "groupon", "study", "reflect", "text")


def rule_type_known(rule: Dict[str, Any]) -> bool:
    """QQ bot stack component."""
    t = str((rule or {}).get("type") or "text").strip().lower()
    return t in KNOWN_RULE_TYPES


PENDING_PIC_SEC = 120        











def sing_groups_read() -> Dict[str, bool]:
    """QQ bot stack component."""
    try:
        with open(SING_TOGGLE_PATH, encoding="utf-8") as f:
            d = json.load(f) or {}
        return {str(k): bool(v) for k, v in d.items()}
    except Exception:
        return {}


def sing_groups_write(mapping: Dict[str, bool]) -> bool:
    """QQ bot stack component."""
    try:
        clean = {str(k): False for k, v in mapping.items() if not v}
        os.makedirs(os.path.dirname(SING_TOGGLE_PATH), exist_ok=True)
        tmp = SING_TOGGLE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SING_TOGGLE_PATH)
        return True
    except Exception as e:                                  
        logger.error(f"[唱歌] 写开关表失败: {type(e).__name__}: {e}")
        return False


def sing_disabled_groups() -> set:
    """QQ bot stack component."""
    return {g for g, on in sing_groups_read().items() if not on}


def sing_enabled(gid: Any) -> bool:
    """QQ bot stack component."""
    return str(gid) not in sing_disabled_groups()


def sing_toggle(gid: Any, on: bool) -> bool:
    """QQ bot stack component."""


    m = sing_groups_read()
    if on:
        m.pop(str(gid), None)
    else:
        m[str(gid)] = False
    return sing_groups_write(m)


def reply_message_id(message: Dict[str, Any]) -> str:
    """QQ bot stack component."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        for seg in (content.get("segments") or []):
            if isinstance(seg, dict) and seg.get("type") == "reply":
                mid = str((seg.get("data") or {}).get("id") or "").strip()
                if mid:
                    return mid
    m = re.search(r"\[CQ:reply,[^\]]*id=([^,\]]+)", str((message or {}).get("raw_message") or ""))
    return m.group(1) if m else ""


def segments_image_urls(segs: Any) -> List[str]:
    """QQ bot stack component."""
    if isinstance(segs, str):
        return [u.replace("&amp;", "&")
                for u in re.findall(r"\[CQ:image,[^\]]*url=([^,\]]+)", segs) if u]
    out: List[str] = []
    for seg in (segs or []):
        if not isinstance(seg, dict) or seg.get("type") != "image":
            continue
        u = str((seg.get("data") or {}).get("url") or "").strip()
        if u:
            out.append(u)
    return out


def image_urls_of(message: Dict[str, Any]) -> List[str]:
    """QQ bot stack component."""
    out: List[str] = []
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        for seg in (content.get("segments") or []):
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue
            u = str((seg.get("data") or {}).get("url") or "").strip()
            if u:
                out.append(u)
    return out


def fetch_image(url: str, max_mb: float = 5.0) -> Tuple[bytes, str]:
    """QQ bot stack component."""
    req = urllib.request.Request(url, headers={"User-Agent": "qq-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = r.read(int(max_mb * 1024 * 1024) + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"图太大（超过 {max_mb:g}MB）")
    ext = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
           "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp"}.get(ctype)
    if not ext:
        tail = url.split("?")[0].rsplit(".", 1)
        if len(tail) == 2 and tail[1].lower() in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
            ext = "." + ("jpg" if tail[1].lower() == "jpeg" else tail[1].lower())
        else:
            raise ValueError(f"不认识的图片类型 {ctype!r}")
    return data, ext


def emoji_dir(cfg: Dict[str, Any]) -> str:
    """QQ bot stack component."""
    p = str(cfg.get("emoji_dir") or "").strip()
    if p:
        return os.path.abspath(os.path.expanduser(p))
    return os.path.join(os.path.dirname(pool_path(cfg.get("quirky_file"))), "emoji")


def learned_log(cfg: Dict[str, Any]) -> str:
    """QQ bot stack component."""
    return os.path.join(os.path.dirname(emoji_dir(cfg)), "emoji_learned.json")


def learn_payload(message: Dict[str, Any], words: List[str]) -> str:
    """QQ bot stack component."""




    text = message_text(message) or ""
    for w in sorted({str(x).strip() for x in (words or []) if str(x).strip()},
                    key=len, reverse=True):
        i = text.find(w)
        if i >= 0:
            return text[i + len(w):].strip().lstrip("：:，,。.、!！?？~～ 	")
    return ""


DEFAULT_FAVOR_FILE = os.path.join(os.path.dirname(DEFAULT_POOL_FILE), "favorability.json")


def favor_file(configured: Any = "") -> str:
    """QQ bot stack component."""
    p = str(configured or "").strip()
    return os.path.abspath(os.path.expanduser(p)) if p else DEFAULT_FAVOR_FILE


def favor_label(score: float) -> str:
    """QQ bot stack component."""
    if score >= 500:
        return "死心塌地"
    if score >= 200:
        return "很喜欢"
    if score >= 80:
        return "挺熟"
    if score >= 30:
        return "一般"
    return "快翻脸了"



SING_FAVOR_MIN = 300.0


def rule_requires_at(rule: Dict[str, Any]) -> bool:
    """QQ bot stack component."""
    r = rule or {}
    if "require_at_bot" in r:
        return r.get("require_at_bot") is not False
    return rule_type(r) in ("quirky", "favor", "learn", "mylearn", "sing", "groupon", "study", "reflect")





EXACT_MATCH_TYPES = ("favor",)

_EXACT_STRIP = " \t\r\n？?。.!！~～、,，；;：:…·"
_AT_PREFIX = re.compile(r"^(?:@[^\s@]+|\[CQ:at,[^\]]*\])+")


def _exact_key(value: Any) -> str:
    """QQ bot stack component."""

    s = str(value or "").strip()
    s = _AT_PREFIX.sub("", s).strip()
    return s.strip(_EXACT_STRIP)


def match_rule(text: str, rules: List[Any]) -> Tuple[int, str]:
    """QQ bot stack component."""









    t = str(text or "")
    if not t:
        return -1, ""
    for i, rule in enumerate(rules or []):
        if not isinstance(rule, dict) or rule.get("enabled", True) is False:
            continue
        exact = rule_type(rule) in EXACT_MATCH_TYPES
        for w in (rule.get("keywords") or []):
            w = str(w or "").strip()
            if not w:
                continue
            if exact:
                if _exact_key(t) == _exact_key(w):
                    return i, w
            elif w in t:
                return i, w
    return -1, ""



_SING_TRIGGERS = ("唱首歌", "唱一个", "唱一首", "唱一下", "来一首", "来一个", "唱唱",
                  "唱歌", "唱", "点歌", "来首")


def extract_song_query(text: str, hit_word: str = "") -> str:
    """QQ bot stack component."""






    t = str(text or "")
    
    t = re.sub(r"\[CQ:at,[^\]]*\]", " ", t)
    t = re.sub(r"@\S+", " ", t)
    t = t.strip()
    if not t:
        return ""

    
    for pat in (r"[《【]([^》】]{1,40})[》】]", r"[\"“]([^\"”]{1,40})[\"”]",
                r"『([^』]{1,40})』"):
        m = re.search(pat, t)
        if m:
            return m.group(1).strip()

    
    
    
    for trig in sorted(_SING_TRIGGERS, key=len, reverse=True):
        i = t.find(trig)
        if i >= 0:
            rest = t[i + len(trig):].strip(" ：:，,。.!！?？的 \t")
            rest = re.sub(r"^(首|个|一下|一段|点|歌)\s*", "", rest).strip()
            return rest[:40] if rest else ""
    
    if hit_word:
        i = t.find(str(hit_word))
        if i >= 0:
            rest = t[i + len(str(hit_word)):].strip(" ：:，,。.!！?？的 \t")
            if rest:
                return rest[:40]
    return ""


def cooldown_ok(state: Dict[str, Any], gid: Any, idx: int, cd: float,
                now: Optional[float] = None, mark: bool = True) -> bool:
    """QQ bot stack component."""






    if cd <= 0:
        return True
    now = time.time() if now is None else now
    key = f"{gid}|{idx}"
    last = float(state.get(key) or 0)
    if now - last < cd:
        return False
    if mark:
        state[key] = now
    return True


def cooldown_mark(state: Dict[str, Any], gid: Any, idx: int,
                  now: Optional[float] = None) -> None:
    """QQ bot stack component."""
    now = time.time() if now is None else now
    state[f"{gid}|{idx}"] = now


class KeywordReplier:
    """QQ bot stack component."""

    def __init__(self, client: Any, path: str = CONFIG_PATH, store: Any = None) -> None:
        self.client = client
        self.path = path
        self._store = store                   
        self._jail_timers: Dict[str, Any] = {}  
        self._lock = threading.Lock()
        self._cfg: Dict[str, Any] = {}
        self._mtime = 0.0
        self._state: Dict[str, Any] = {}      
        self._hits = 0
        self._sent = 0
        self._skipped = 0                     
        
        self._pending_pic: Dict[str, float] = {}
        self._pool: Optional[QuirkyPool] = None
        self._pool_key: Tuple[str, int] = ("", 0)
        self._food_pool: Optional[QuirkyPool] = None
        self._food_key: str = ""
        self._sing_mod: Any = None            
        self._study_mod: Any = None           
        self._say_mod: Any = None             
        self._say_cd: Dict[int, float] = {}   
        self._unknown_types: set = set()      
        
        self._pending_version: Dict[int, dict] = {}
        self.reload(force=True)
        
        logger.info(f"[关键词] 本进程支持的规则类型：{'/'.join(KNOWN_RULE_TYPES)}"
                    f"（规则 JSON 热重载、**代码不热重载**；JSON 里出现清单外的 type 会静默失效）")

    
    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            cfg = default_config()
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)          
                logger.info(f"已生成默认关键词规则: {self.path}")
            except OSError as e:
                logger.warning(f"写默认关键词规则失败（用内存里的默认值继续）: {e}")
            return cfg
        with open(self.path, encoding="utf-8") as f:
            cfg = json.load(f) or {}
        return cfg if isinstance(cfg, dict) else {}

    def reload(self, force: bool = False) -> bool:
        """QQ bot stack component."""
        try:
            mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else 0.0
        except OSError:
            mtime = 0.0
        if not force and mtime and mtime == self._mtime:
            return False
        try:
            cfg = self._read()
        except Exception as e:
            logger.error(f"关键词规则读取失败（沿用上一次的规则）: {type(e).__name__}: {e}")
            return False
        with self._lock:
            self._cfg = cfg
            self._mtime = mtime
        rules = [r for r in (cfg.get("rules") or []) if isinstance(r, dict)]
        logger.info(f"关键词规则已载入：{len(rules)} 条（怪话 "
                    f"{sum(1 for r in rules if rule_type(r) == 'quirky')} 条），"
                    f"{'启用' if cfg.get('enabled', True) else '停用'}")
        return True

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            cfg = self._cfg
            rules = [r for r in (cfg.get("rules") or []) if isinstance(r, dict)]
            pool = self._pool
        out = {"enabled": bool(cfg.get("enabled", True)), "rules": len(rules),
               "quirky_rules": sum(1 for r in rules if rule_type(r) == "quirky"),
               "hits": self._hits, "sent": self._sent, "skipped_no_at": self._skipped,
               "path": self.path}
        if pool is not None:
            out["pool"] = pool.stats()
        return out

    
    def _pool_for(self, cfg: Dict[str, Any]) -> QuirkyPool:
        """QQ bot stack component."""
        path = pool_path(cfg.get("quirky_file"))
        try:
            max_chars = int(cfg.get("max_chars") or DEFAULT_MAX_CHARS)
        except (TypeError, ValueError):
            max_chars = DEFAULT_MAX_CHARS
        key = (path, max_chars)
        with self._lock:
            if self._pool is None or self._pool_key != key:
                self._pool = QuirkyPool(path, max_chars)
                self._pool_key = key
                logger.info(f"怪话池已就绪：{path}"
                            + (f"（只发 ≤{max_chars} 字）" if max_chars > 0 else "（不限字数）"))
            return self._pool

    def _food_pool_for(self, cfg: Dict[str, Any]) -> QuirkyPool:
        """QQ bot stack component."""





        path = str(cfg.get("food_file") or "").strip()
        path = os.path.abspath(os.path.expanduser(path)) if path else DEFAULT_FOOD_FILE
        with self._lock:
            if self._food_pool is None or self._food_key != path:
                self._food_pool = QuirkyPool(path, 0, label="食物库")   
                self._food_key = path
                logger.info(f"食物库已就绪：{path}")
            return self._food_pool

    def _bot_qq(self) -> str:
        """QQ bot stack component."""
        try:
            return str(getattr(self.client, "bot_qq", "") or "").strip()
        except Exception:                       
            return ""

    def _compose(self, rule: Dict[str, Any], cfg: Dict[str, Any],
                 message: Optional[Dict[str, Any]] = None, word: str = "") -> str:
        """QQ bot stack component."""
        prefix = str(rule.get("prefix") or "")
        if rule_type(rule) == "quirky":
            item = self._pool_for(cfg).pick()
            if not item:
                logger.warning("怪话库没有可发的内容（空了 / 全被停用 / 都超过 max_chars）")
                return ""
            return prefix + self._pool_for(cfg).takeover(item)
        if rule_type(rule) == "food":
            pool = self._food_pool_for(cfg)
            item = pool.pick()
            if not item:
                logger.warning("食物库没有可发的内容（空了 / 全被停用）")
                return ""
            dish = pool.takeover(item).strip()
            if not dish:
                return ""
            
            tpl = str(cfg.get("food_template") or DEFAULT_FOOD_TEMPLATE)
            return prefix + tpl.replace("{food}", dish)
        if rule_type(rule) == "learn":
            return self._learn_line(cfg, message or {}, rule, word)
        if rule_type(rule) == "mylearn":
            return self._mylearn_line(cfg, message or {})
        if rule_type(rule) == "favor":
            
            return self._favor_line(cfg, message or {})
        return prefix + str(rule.get("reply") or "").strip()

    
    def _sing_service(self):
        """QQ bot stack component."""




        if self._sing_mod is not None:
            return self._sing_mod or None
        try:
            import sys
            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "panel", "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import rvc_singer                                 
            self._sing_mod = rvc_singer
            return rvc_singer
        except Exception as e:                                
            logger.error(f"[唱歌] 载入 rvc_singer 失败: {type(e).__name__}: {e}")
            self._sing_mod = False
            return None

    
    
    
    
    
    STUDY_OFF_WORDS = ("出关", "闭关结束", "结束学习", "停止学习", "别学了", "学完了", "学习结束")
    STUDY_ON_WORDS = ("闭关", "开始学习", "学习模式", "去学习", "学习一下", "闭关学习")

    def _study_service(self):
        """QQ bot stack component."""




        if self._study_mod is not None:
            return self._study_mod or None
        try:
            import importlib.util
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            path = os.path.join(root, "bot", "MaiBotOneKey", "modules", "MaiBot",
                                "src", "learners", "study_mode.py")
            spec = importlib.util.spec_from_file_location("_maibot_study_mode", path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"加载不了 {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._study_mod = mod
            logger.info(f"[闭关] 已加载学习状态模块: {path}")
            return mod
        except Exception as e:                                
            logger.error(f"[闭关] 载入 study_mode 失败: {type(e).__name__}: {e}")
            self._study_mod = False
            return None

    def _study_send(self, gid: Any, idx: int, line: str, what: str) -> Optional[str]:
        """QQ bot stack component."""
        try:
            sent = bool(self.client.send_group_message(int(gid), line))
        except Exception as e:                                
            logger.error(f"[闭关] 回执发送失败: {type(e).__name__}: {e}")
            return None
        if not sent:
            return None
        self._sent += 1
        with self._lock:
            cooldown_mark(self._state, gid, idx)
        logger.info(f"[闭关] 群 {gid} {what}")
        return line

    def _handle_study(self, message: Dict[str, Any], gid: Any, idx: int) -> Optional[str]:
        """QQ bot stack component."""
        mod = self._study_service()
        if mod is None:
            return None
        raw = message_text(message) or ""

        
        if any(w in raw for w in self.STUDY_OFF_WORDS):
            left = mod.remaining_seconds()
            if left <= 0:
                return self._study_send(gid, idx, "我没在闭关呀，一直在听着的～", "喊出关但其实没在闭关")
            mod.deactivate(source="keyword_reply")
            mins = max(1, int(round(left / 60.0)))
            return self._study_send(gid, idx, f"学完了，我回来啦～（提前 {mins} 分钟出关）", "出关")

        
        sender = str(message.get("user_id") or "").strip()
        admins = {str(a).strip() for a in ((self._cfg or {}).get("admins") or []) if str(a).strip()}
        if not admins or sender not in admins:
            logger.debug(f"[闭关] 群 {gid} 的 {sender} 想让我闭关但不是管理员，忽略")
            return None

        was_active = mod.remaining_seconds() > 0
        state = mod.activate(mod.parse_duration_minutes(raw), requester=sender,
                             group_id=str(gid or ""), source="keyword_reply")
        dur = int(state.get("duration_minutes") or 0)
        until = mod.until_text() or "一会儿"
        if was_active:
            line = f"好，续上 —— 再学 {dur} 分钟（{until} 出关）。"
        else:
            line = (f"好，我闭关学习 {dur} 分钟（{until} 出关）—— 这段时间先不回消息，"
                    f"让我把大家说的话好好消化一下。想让我出来就喊「出关」。")
        return self._study_send(gid, idx, line, f"闭关 {dur} 分钟（到 {until}）")

    
    
    
    REFLECT_ON_WORDS = ("禁闭", "面壁")
    REFLECT_OFF_WORDS = ("禁闭结束", "解除禁闭", "放出来", "别罚了", "反思完了")

    def _llm_reflect(self, gid: Any) -> str:
        """QQ bot stack component."""
        try:
            import requests
            cfg: Dict[str, Any] = {}
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "config", "memory_keeper.json")
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception as e:                            
                logger.warning(f"[禁闭] memory_keeper.json 读取失败，用默认 luna 配置: {e}")
            api_base = (cfg.get("api_base") or "http://127.0.0.1:9879/v1").rstrip("/")
            model = cfg.get("model") or "gpt-6-luna-medium"
            lines: List[str] = []
            try:
                msgs = self._store.get_recent_messages(int(gid), 60) if self._store else []
            except Exception as e:                            
                logger.warning(f"[禁闭] 取最近发言失败: {e}")
                msgs = []
            for m in msgs[-45:]:
                who = "鱼(我自己)" if m.get("is_bot") else (
                    m.get("card") or m.get("nickname") or str(m.get("user_id") or "群友"))
                t = ((m.get("content") or {}).get("text") or "").strip()
                if t:
                    lines.append(f"{who}: {t[:150]}")
            if not lines:
                return "刚才……我好像没说什么话，但反省的态度是端正的！"
            recent = "\n".join(lines)
            system = (
                "你是鱼，叫示例角色。你没有主人，也不属于任何人。有人请你暂停发言，先读最近的群聊。"
                "用第一人称写一段简短反思，100字以内，具体说说自己刚才哪里没做好；"
                "如果没有做错，也不必装作认错。语气真诚自然，可以带一点委屈或可爱，"
                "但不要讨好别人，也不要称任何人为主人。直接输出要说的话，不加前后缀。"
            )
            payload: Dict[str, Any] = {"model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"以下是这个群最近的聊天记录（鱼=我自己）：\n{recent}"},
            ]}
            headers = {"Content-Type": "application/json"}
            key = cfg.get("api_key", "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            resp = requests.post(api_base + "/chat/completions", json=payload, headers=headers,
                                 timeout=int(cfg.get("llm_timeout") or 90))
            resp.raise_for_status()
            text = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            return text[:400] or "（我反省了，但一时词穷，态度是真的端正）"
        except Exception as e:                                
            logger.error(f"[禁闭] 反思生成失败: {type(e).__name__}: {e}")
            return "（禁闭期间我认真面壁了，具体错在哪我心里有数，下次改！）"

    def _reflect_release(self, gid: Any) -> None:
        """QQ bot stack component."""
        try:
            mod = self._study_service()
            if mod is not None and mod.remaining_seconds() > 0:
                mod.deactivate(source="jail_reflect")
            text = self._llm_reflect(gid)
            try:
                self.client.send_group_message(int(gid), f"（禁闭结束，面壁完毕）我反省好了：{text}")
                logger.info(f"[禁闭] 群 {gid} 禁闭结束，悔过书已发")
            except Exception as e:                            
                logger.error(f"[禁闭] 悔过书发送失败: {e}")
        finally:
            with self._lock:
                self._jail_timers.pop(str(gid), None)

    def _handle_reflect(self, message: Dict[str, Any], gid: Any, idx: int) -> Optional[str]:
        """QQ bot stack component."""
        mod = self._study_service()
        if mod is None:
            return None
        raw = message_text(message) or ""

        
        if any(w in raw for w in self.REFLECT_OFF_WORDS):
            left = mod.remaining_seconds()
            if left <= 0:
                return self._study_send(gid, idx, "我没在禁闭呀，一直乖乖的～", "喊解除禁闭但其实没在禁闭")
            t = self._jail_timers.pop(str(gid), None)
            if t:
                t.cancel()
            mod.deactivate(source="jail_reflect")
            return self._study_send(gid, idx, "（提前放出来了……悔过态度永远端正！）", "提前解除禁闭")

        
        sender = str(message.get("user_id") or "").strip()
        admins = {str(a).strip() for a in ((self._cfg or {}).get("admins") or []) if str(a).strip()}
        if not admins or sender not in admins:
            logger.debug(f"[禁闭] 群 {gid} 的 {sender} 想罚我禁闭但不是管理员，忽略")
            return None
        if mod.remaining_seconds() > 0:
            return self._study_send(gid, idx, "（已经在禁闭中了……跪得更端正了一点）", "重复禁闭")
        minutes = mod.parse_duration_minutes(raw) or 10
        minutes = max(1, min(int(minutes), 60))
        mod.activate(minutes, requester=sender, group_id=str(gid or ""), source="jail_reflect")
        t = threading.Timer(minutes * 60 + 3, self._reflect_release, args=(gid,))
        t.daemon = True
        with self._lock:
            old = self._jail_timers.pop(str(gid), None)
            if old:
                old.cancel()
            self._jail_timers[str(gid)] = t
        t.start()
        return self._study_send(
            gid, idx,
            f"（乖乖面壁去了……禁闭 {minutes} 分钟，这段时间不说话，好好反省刚才都干了什么）",
            f"禁闭 {minutes} 分钟（反思模式）")

    def _handle_groupon(self, message: Dict[str, Any], rule: Dict[str, Any],
                        gid: Any, idx: int) -> Optional[str]:
        """QQ bot stack component."""
        raw = message_text(message) or ""
        
        OFF_WORDS = ("关闭", "关掉", "别唱", "闭嘴", "禁用", "关", "不要唱", "别唱了")
        ON_WORDS = ("打开", "开启", "开一下", "可以唱", "允许", "来唱", "开")
        if any(w in raw for w in OFF_WORDS):
            on = False
        elif any(w in raw for w in ON_WORDS):
            on = True
        else:
            
            on = True
        was_on = sing_enabled(gid)
        ok = sing_toggle(gid, on)
        if not ok:
            line = "开关没写进去…等会儿再试试。"
        elif on:
            line = ("本鱼本来就能唱～想听什么就说「唱《歌名》」🎤" if was_on
                    else "好耶，本群又能唱啦~ 想听什么就说「唱《歌名》」🎤")
        else:
            line = "行吧，本群不唱了。想恢复就说「打开唱歌」。"
        try:
            sent = bool(self.client.send_group_message(int(gid), line))
        except Exception as e:                                
            logger.error(f"[唱歌] 开关回复失败: {type(e).__name__}: {e}")
            return None
        if sent:
            self._sent += 1
            with self._lock:
                cooldown_mark(self._state, gid, idx)
            logger.info(f"[唱歌] 群 {gid} 唱歌开关 -> {'开' if on else '关'}")
            return line
        return None

    def _handle_sing(self, message: Dict[str, Any], rule: Dict[str, Any],
                     gid: Any, idx: int, word: str) -> Optional[str]:
        """QQ bot stack component."""




        if not sing_enabled(gid):
            try:
                self.client.send_group_message(
                    int(gid), "这个群的唱歌开关被关掉了…让管理员说「打开唱歌」就能恢复。")
            except Exception as e:                            
                logger.error(f"[唱歌] 未开提示失败: {type(e).__name__}: {e}")
            return None

        
        if not self._sing_favor_ok(gid, str(message.get("user_id") or "")):
            return None

        mod = self._sing_service()
        if mod is None:
            try:
                self.client.send_group_message(int(gid), "本鱼现在开不了嗓…（唱歌服务没起来）")
            except Exception:                                 
                pass
            return None

        query = extract_song_query(message_text(message) or "", word)
        if not query:
            
            
            
            
            try:
                self.client.send_group_message(
                    int(gid), "想听什么呀？说「唱《歌名》」本鱼就唱~")
            except Exception:                                 
                pass
            return None

        uid = str(message.get("user_id") or "")
        
        force = False
        if any(w in (message_text(message) or "")
               for w in ("重唱", "重新唱", "重录", "再唱一遍", "再唱一次")):
            admins = {str(a).strip() for a in ((self._cfg or {}).get("admins") or [])
                      if str(a).strip()}
            force = bool(admins) and uid in admins
            if not force:
                logger.debug(f"[唱歌] 群 {gid} 有人想重唱但不在管理员名单里，按普通点歌处理")

        
        
        
        if not force and hasattr(mod, "search_versions"):
            try:
                has_pref = bool(mod.get_version_pref(query))
                has_cache = bool(mod.find_cached_song(query))
            except Exception:                             
                has_pref = has_cache = False
            if not has_pref and not has_cache:
                try:
                    vers = mod.search_versions(query)
                except Exception as exc:                  
                    logger.debug(f"[唱歌] 版本搜索失败: {exc}")
                    vers = []
                good = [v for v in vers if v.get("score", -100) > -50]
                if len(good) >= 2:
                    top = good[:4]
                    self._pending_version[int(gid)] = {
                        "query": query, "cands": top, "exp": time.time() + 90}
                    lines = [f"《{query}》找到 {len(top)} 个版本，"
                             f"回复「选 1/2/3…」告诉本鱼唱哪个（90 秒内有效）："]
                    for i, v in enumerate(top, 1):
                        mm, ss = divmod(int(v.get("dur") or 0), 60)
                        lines.append(f"{i}. {v.get('title', '')} - "
                                     f"{v.get('artist', '')} [{mm}:{ss:02d}]")
                    try:
                        self.client.send_group_message(int(gid), "\n".join(lines))
                        self._sent += 1
                        logger.info(f"[唱歌] 群 {gid} 列出版本清单（{len(top)} 个，"
                                    f"来自 {uid}）")
                    except Exception as e:                
                        logger.error(f"[唱歌] 版本清单发送失败: {e}")
                    return None

        try:
            ok, immediate = mod.request_song(int(gid), query, uid, force=force)
        except Exception as e:                                
            logger.error(f"[唱歌] 点歌异常: {type(e).__name__}: {e}")
            return None
        if not ok:
            try:
                self.client.send_group_message(int(gid), immediate)
            except Exception:                                 
                pass
            return None
        if immediate:
            try:
                self.client.send_group_message(int(gid), immediate)
            except Exception:                                 
                pass
        self._sent += 1
        with self._lock:
            cooldown_mark(self._state, gid, idx)
        logger.info(f"[唱歌] 群 {gid} 点歌「{query}」（来自 {uid}）")
        return immediate or f"唱《{query}》"

    
    _PICK_RE = re.compile(r"^\s*(?:选|第)?\s*([1-9])\s*(?:个|号|首)?\s*$")

    
    def _favor_score(self, uid: str) -> float:
        """QQ bot stack component."""
        try:
            path = favor_file((self._cfg or {}).get("favor_file"))
            with open(path, encoding="utf-8") as f:
                users = (json.load(f) or {}).get("users") or {}
            u = users.get(str(uid))
            if isinstance(u, dict):
                return float(u.get("score", 0) or 0)
            return 0.0
        except Exception as e:                              
            logger.warning(f"[关键词] 好感度文件读不了（唱歌门槛）: "
                           f"{type(e).__name__}: {e}")
            return -1.0

    def _sing_favor_ok(self, gid: Any, uid: str) -> bool:
        """QQ bot stack component."""
        uid = str(uid or "")
        admins = {str(a).strip() for a in ((self._cfg or {}).get("admins") or [])
                  if str(a).strip()}
        if uid in admins:
            return True
        score = self._favor_score(uid)
        if score >= SING_FAVOR_MIN:
            return True
        tip = (f"好感度到 {SING_FAVOR_MIN:.0f} 才能让本鱼开嗓哦～"
               f"（你现在是 {score:.0f}，多陪本鱼聊聊就涨啦）"
               if score >= 0 else "好感度这会儿查不出来，等会儿再试吧～")
        try:
            self.client.send_group_message(int(gid), tip)
        except Exception as e:                              
            logger.error(f"[唱歌] 门槛提示失败: {type(e).__name__}: {e}")
        return False

    
    
    
    
    _SAY_RE = re.compile(r"^说[:：\s]*(.+)$", re.S)

    def _match_say(self, message: Dict[str, Any]) -> Optional[str]:
        """QQ bot stack component."""
        gid = message.get("group_id")
        if gid is None:
            return None
        text = (message_text(message) or "").strip()
        if not text:
            return None
        text = re.sub(r"^@\S+\s*", "", text)          
        m = self._SAY_RE.match(text)
        if not m:
            return None
        if not mentioned_bot(message, self._bot_qq()):
            return None
        body = m.group(1).strip()
        
        if not body or body.startswith(("唱", "歌")):
            return None
        return body

    def _say_service(self):
        """QQ bot stack component."""
        if getattr(self, "_say_mod", None) is not None:
            return self._say_mod or None
        try:
            import sys
            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "panel", "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import tts_speaker                                  
            self._say_mod = tts_speaker
            return tts_speaker
        except Exception as e:                                  
            logger.error(f"[说话] 加载 tts_speaker 失败: {type(e).__name__}: {e}")
            self._say_mod = False
            return None

    def _handle_say(self, message: Dict[str, Any], gid: Any, text: str) -> Optional[str]:
        """QQ bot stack component."""
        text = (text or "").strip()[:300]
        uid = str(message.get("user_id") or "")
        if not text:
            try:
                self.client.send_group_message(int(gid), "要说什么呀？说完整嘛~")
            except Exception:                                   
                pass
            return None
        now = time.time()
        last = float(self._say_cd.get(int(gid), 0) or 0)
        if now - last < 10:
            logger.debug(f"[说话] 群 {gid} 冷却中，忽略")
            return None
        self._say_cd[int(gid)] = now

        mod = self._say_service()
        if mod is None:
            try:
                self.client.send_group_message(int(gid), "本鱼现在发不出声…（TTS 服务没起来）")
            except Exception:                                   
                pass
            return None

        def _fail(g: int, reason: str) -> None:
            logger.error(f"[说话] 群 {g} 合成失败: {reason}")
            try:
                self.client.send_group_message(g, "呜…这句说不出来，换个短点的试试？")
            except Exception:                                   
                pass

        try:
            mod.say_async(int(gid), text, on_fail=_fail)
            logger.info(f"[说话] 群 {gid} {uid} 让本鱼说（{len(text)} 字）: {text[:50]}")
        except Exception as e:                                  
            logger.error(f"[说话] 启动合成失败: {type(e).__name__}: {e}")
        return None

    
    
    
    _TRIM_RE = re.compile(r"^调歌\s+(.+?)\s+(降|升)(\d+|一点|两点)$")

    def _match_pitch_trim(self, message: Dict[str, Any]) -> Optional[Tuple[str, int]]:
        gid = message.get("group_id")
        if gid is None:
            return None
        text = (message_text(message) or "").strip()
        if not text:
            return None
        text = re.sub(r"^@\S+\s*", "", text)
        if not text.startswith("调歌"):
            return None
        if not mentioned_bot(message, self._bot_qq()):
            return None
        if re.match(r"^调歌\s+.+\s+归零$", text):
            return text[3:].split("归零")[0].strip(), 0
        m = self._TRIM_RE.match(text)
        if not m:
            return None
        query, direction, amount = m.group(1).strip(), m.group(2), m.group(3)
        n = {"一点": 1, "两点": 2}.get(amount)
        if n is None:
            n = int(amount)
        return query, (-n if direction == "降" else n)

    def _handle_pitch_trim(self, message: Dict[str, Any], gid: Any,
                           query: str, delta: int) -> Optional[str]:
        uid = str(message.get("user_id") or "")
        admins = {str(a).strip() for a in ((self._cfg or {}).get("admins") or [])
                  if str(a).strip()}
        if not admins or uid not in admins:
            return None                                  
        mod = self._sing_service()
        if mod is None or not hasattr(mod, "set_pitch_trim"):
            try:
                self.client.send_group_message(int(gid), "调音功能没就绪…重启一下监控就好。")
            except Exception:                               
                pass
            return None
        try:
            mod.set_pitch_trim(query, delta)
        except Exception as e:                              
            logger.error(f"[调歌] 写微调失败: {type(e).__name__}: {e}")
            return None
        total = int(os.environ.get("SING_PITCH_OFFSET", "-1")) + delta
        tip = (f"好，以后《{query}》都按{'低' if total < 0 else '高'}"
               f"{abs(total)} 个半音唱（全局 -1 {f'{delta:+d}' if delta else ''}）。"
               f"再点一次这首歌就能听到新版~") if delta else \
              f"好，《{query}》的音高微调已归零（回到全局 -1）。"
        try:
            self.client.send_group_message(int(gid), tip)
            self._sent += 1
        except Exception as e:                              
            logger.error(f"[调歌] 回执失败: {e}")
        logger.info(f"[调歌] 群 {gid} 《{query}》微调 {delta:+d}（总 {total:+d}）")
        return tip

    
    def _match_model_query(self, message: Dict[str, Any]) -> bool:
        """QQ bot stack component."""

        gid = message.get("group_id")
        if gid is None:
            return False
        text = (message_text(message) or "").strip()
        if not text:
            return False
        if "模型" not in text:
            return False
        return mentioned_bot(message, self._bot_qq())

    @staticmethod
    def _model_query_config_lines(cfg: Dict[str, Any]) -> List[str]:
        """QQ bot stack component."""
        models = {m.get("name"): m for m in cfg.get("models", [])}
        tasks = cfg.get("model_task_config") or {}

        def preferred(task: str) -> str:
            settings = tasks.get(task) or {}
            choices = settings.get("model_list") or []
            if not choices:
                return "未配置"
            name = str(choices[0])
            model = models.get(name) or {}
            
            display = str(model.get("name") or model.get("model_identifier") or name)
            display = re.sub(r"^Codex(?: 问答)?\s*·\s*", "", display)
            try:
                pin, pout = float(model.get("price_in") or 0), float(model.get("price_out") or 0)
                valid = "price_in" in model and "price_out" in model and pin >= 0 and pout >= 0 and (pin > 0 or pout > 0)
                price = f"（输入 {pin:g} / 输出 {pout:g} 元/百万 token）" if valid else "（单价未完整配置）"
            except (ValueError, TypeError):
                price = "（单价未完整配置）"
            if settings.get("selection_strategy", "sequential") != "sequential" and len(choices) > 1:
                return f"{display}{price} 等 {len(choices)} 个候选（动态选择）"
            return display + price

        lines = ["【模型菜单】"]
        for task, label in [("replyer", "发言回复"), ("planner", "思考决策"), ("qa", "独立问答")]:
            lines.append(f"{label}：{preferred(task)}")
        groups = {}
        for task, label in [("utils", "摘要"), ("learner", "学习"), ("expression_use", "表达"),
                            ("memory", "记忆"), ("mid_memory", "回想"), ("vlm", "看图"),
                            ("emoji", "表情"), ("embedding", "向量检索"), ("voice", "语音转写")]:
            groups.setdefault(preferred(task), []).append(label)
        lines += ["", "【辅助模型】"]
        for name, labels in groups.items():
            lines.append(f"· {'/'.join(labels)}：{name}")
        if any("Codex" in str(m.get("api_provider", "")) or str(m.get("model_identifier", "")).startswith("gpt-") for m in models.values()):
            lines += ["", "GPT 单价为官方 API 参考价，按固定 1 美元=7 元折算，不代表账号实际扣费。"]
        return lines

    def _handle_model_query(self, gid: Any) -> Optional[str]:
        """QQ bot stack component."""
        started_at = time.monotonic()
        config_elapsed = usage_elapsed = 0.0
        try:
            import tomllib
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
                "bot", "MaiBotOneKey", "modules", "MaiBot")
            cfg_p = os.path.join(base, "config", "model_config.toml")
            with open(cfg_p, "rb") as cfg_file:
                cfg = tomllib.load(cfg_file)
            
            config_elapsed = time.monotonic() - started_at
            usage_started = time.monotonic()
            usage_lines, total_cost, total_tok = [], 0.0, 0

            def format_tokens(value: int) -> str:
                return f"{value / 10000:.1f}万" if value >= 10000 else f"{value:,}"

            try:
                import sqlite3
                db = os.path.join(base, "data", "MaiBot.db")
                from pathlib import Path
                from contextlib import closing
                con = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
                with closing(con):
                    deadline = time.monotonic() + 0.5
                    con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                    cur = con.cursor()
                    columns = {row[1] for row in cur.execute("PRAGMA table_info(llm_usage)")}
                    has_cost = "cost" in columns
                    cost_expr = "SUM(cost)" if has_cost else "NULL"
                    missing_cost_expr = "COUNT(*) - COUNT(cost)" if has_cost else "COUNT(*)"
                    order_expr = "SUM(cost)" if has_cost else "SUM(total_tokens)"
                    today = time.strftime("%Y-%m-%d")
                    detailed_schema = {"model_name", "prompt_tokens", "completion_tokens"}.issubset(columns)
                    if not detailed_schema:
                        rows = cur.execute(
                            f"SELECT task_name, SUM(total_tokens), {cost_expr}, {missing_cost_expr} FROM llm_usage "
                            f"WHERE timestamp >= ? GROUP BY task_name ORDER BY {order_expr} DESC",
                            (today,)).fetchall()
                    
                    if detailed_schema:
                        prices = {}
                        family_prices = {}
                        def gpt_family(name):
                            normalized = re.sub(r"^Codex(?: 问答)?\s*·\s*", "", str(name), flags=re.I)
                            normalized = re.sub(r"\s*·\s*视觉$", "", normalized)
                            normalized = re.sub(r"\s+", "-", normalized.strip().lower())
                            matched = re.fullmatch(r"gpt-6-(astra|sol|luna)(?:-(?:low|medium|high|xhigh|max|ultra))?", normalized)
                            return matched.group(1) if matched else None
                        for model in cfg.get("models", []):
                            try:
                                pin, pout = float(model.get("price_in") or 0), float(model.get("price_out") or 0)
                            except (TypeError, ValueError):
                                continue
                            if "price_in" in model and "price_out" in model and pin >= 0 and pout >= 0 and (pin > 0 or pout > 0):
                                for key in (model.get("name"), model.get("model_identifier")):
                                    if key:
                                        prices[str(key)] = (pin, pout)
                                family = gpt_family(model.get("model_identifier", ""))
                                if family:
                                    family_prices[family] = (pin, pout)
                        detailed = cur.execute(
                            f"SELECT task_name, model_name, SUM(total_tokens), SUM(prompt_tokens), "
                            f"SUM(completion_tokens), {cost_expr}, {missing_cost_expr}, "
                            "COUNT(*) - COUNT(prompt_tokens), COUNT(*) - COUNT(completion_tokens) "
                            "FROM llm_usage WHERE timestamp >= ? GROUP BY task_name, model_name",
                            (today,)).fetchall()
                        grouped = {}
                        for task, model_name, tok, prompt, completion, old_cost, missing, missing_prompt, missing_completion in detailed:
                            row = grouped.setdefault(task, [0, 0.0, 0])
                            row[0] += int(tok or 0)
                            price = prices.get(str(model_name))
                            if price is None:
                                family = gpt_family(model_name)
                                if family:
                                    price = family_prices.get(family)
                            if price is not None and not missing_prompt and not missing_completion:
                                pin, pout = price
                                row[1] += (float(prompt or 0) * pin + float(completion or 0) * pout) / 1000000
                            else:
                                row[1] += float(old_cost or 0)
                                
                                is_gpt = bool(re.match(r"^(?:Codex(?: 问答)?\s*·\s*)?gpt-", str(model_name), re.I))
                                row[2] += int(missing or 0) + int(old_cost is None or (is_gpt and not old_cost))
                        rows = [(task, *values) for task, values in grouped.items()]
                TASK_CN = {"replyer": "发言回复", "planner": "思考决策", "qa": "独立问答", "utils": "摘要/工具",
                           "memory": "记忆", "mid_memory": "回想", "vlm": "视觉/表情",
                           "embedding": "向量", "asr": "语音转写", "emoji": "表情",
                           "voice": "语音转写", "learner": "行为学习", "expression_use": "表达"}
                items = []
                complete_cost = has_cost or {"model_name", "prompt_tokens", "completion_tokens"}.issubset(columns)
                for task, tok, cost, missing_cost in rows:
                    tok = int(tok or 0)
                    if cost is None or missing_cost:
                        complete_cost = False
                    recorded_cost = None if missing_cost else cost
                    cost = float(cost or 0)
                    total_cost += cost
                    total_tok += tok
                    items.append((TASK_CN.get(str(task), str(task)), tok, recorded_cost))
                items.sort(key=lambda x: -(float(x[2] or 0) if complete_cost else x[1]))
                if rows:
                    estimate = f"｜配置估算 ¥{total_cost:.2f}" if complete_cost else "｜费用记录不完整"
                    usage_lines.append(f"合计：{format_tokens(total_tok)} token{estimate}")
                for cn, tok, cost in items[:4]:          
                    price = f"｜¥{float(cost):.2f}" if cost is not None else ""
                    usage_lines.append(f"· {cn}：{format_tokens(tok)} token{price}")
                if len(items) > 4:
                    usage_lines.append(f"· 另有 {len(items) - 4} 类任务，已计入合计")
            except Exception as e:                          
                logger.debug(f"[模型查询] 用量统计失败: {e}")
                usage_lines.append("· 用量这会儿读不出来")
            usage_elapsed = time.monotonic() - usage_started

            lines = self._model_query_config_lines(cfg)
            lines += ["", f"【今日用量 · {time.strftime('%m-%d %H:%M')}】"]
            lines += usage_lines or ["· 今天还没有用量记录"]
            lines += ["", "以上为首选配置，非最近实际调用；异常时可能切换备用。",
                      "费用按当前配置单价估算，未扣缓存折扣，不代表实际账单。"]
            line = "\n".join(lines)
        except Exception as e:                              
            logger.error(f"[模型查询] 读取配置失败: {type(e).__name__}: {e}")
            line = "模型配置这会儿读不出来…稍后再试。"
        try:
            self.client.send_group_message(int(gid), line)
            self._sent += 1
        except Exception as e:                              
            logger.error(f"[模型查询] 发送失败: {e}")
        elapsed = time.monotonic() - started_at
        if elapsed > 1:
            logger.warning(f"[模型查询] 总耗时 {elapsed:.2f}s，配置 {config_elapsed:.2f}s，用量 {usage_elapsed:.2f}s，发送及格式化 {max(0, elapsed-config_elapsed-usage_elapsed):.2f}s")
        return line

    def _match_version_pick(self, message: Dict[str, Any]) -> Optional[Tuple[int, int, str]]:
        """QQ bot stack component."""



        gid = message.get("group_id")
        if gid is None:
            return None
        pend = self._pending_version.get(int(gid))
        if not pend:
            return None
        if time.time() > float(pend.get("exp") or 0):
            self._pending_version.pop(int(gid), None)
            logger.debug(f"[唱歌] 群 {gid} 的版本清单已过期")
            return None
        text = (message_text(message) or "").strip()
        m = self._PICK_RE.match(text)
        if not m:
            return None
        return int(gid), int(m.group(1)), str(message.get("user_id") or "")

    def _handle_version_pick(self, gid: int, n: int, uid: str = "") -> Optional[str]:
        """QQ bot stack component."""
        
        if not self._sing_favor_ok(gid, uid):
            return None
        pend = self._pending_version.pop(int(gid), None)
        if not pend:
            return None
        cands = pend.get("cands") or []
        if n < 1 or n > len(cands):
            try:
                self.client.send_group_message(
                    int(gid), f"没有第 {n} 个版本哦…说「唱《{pend.get('query', '')}》」重新来~")
            except Exception as e:                          
                logger.error(f"[唱歌] 版本序号无效提示失败: {e}")
            return None
        cand = cands[n - 1]
        mod = self._sing_service()
        if mod is None:
            try:
                self.client.send_group_message(int(gid), "本鱼现在开不了嗓…（唱歌服务没起来）")
            except Exception:                               
                pass
            return None
        if not hasattr(mod, "request_song_rid"):
            logger.warning("[唱歌] 唱歌服务模块太旧（没有 request_song_rid），重启监控可解")
            return None
        try:
            ok, msg = mod.request_song_rid(int(gid), pend.get("query", ""), cand)
        except Exception as e:                              
            logger.error(f"[唱歌] 版本选择点歌异常: {type(e).__name__}: {e}")
            return None
        if ok and msg:
            try:
                self.client.send_group_message(int(gid), msg)
                self._sent += 1
            except Exception as e:                          
                logger.error(f"[唱歌] 版本选择回执发送失败: {e}")
            logger.info(f"[唱歌] 群 {gid} 用户选了第 {n} 版："
                        f"{cand.get('title')} - {cand.get('artist')}")
        return msg

    def _onebot_get_msg(self, message_id: str) -> Dict[str, Any]:
        """QQ bot stack component."""
        base = str(getattr(self.client, "http_url", "") or "").rstrip("/")
        if not base:
            raise RuntimeError("没配 OneBot 的 http_url，回查不了消息")
        import requests
        headers: Dict[str, str] = {}
        params: Dict[str, Any] = {"message_id": message_id}
        tok = str(getattr(self.client, "token", "") or "")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
            params["access_token"] = tok          
        r = requests.get(f"{base}/get_msg", params=params, headers=headers, timeout=10)
        r.raise_for_status()
        d = r.json()
        if str(d.get("status")) != "ok":
            raise RuntimeError(f"get_msg 失败：{d.get('status')} "
                               f"{d.get('wording') or d.get('message') or ''}")
        return d.get("data") or {}

    def _deliver(self, message: Dict[str, Any], line: str, at_qq: str = "") -> bool:
        """QQ bot stack component."""
        gid = message.get("group_id")
        try:
            return bool(self.client.send_group_message(int(gid), line, at_qq=at_qq))
        except Exception as e:  
            logger.error(f"[关键词] 发送失败: {type(e).__name__}: {e}")
            return False

    def _pending_pic_check(self, message: Dict[str, Any]) -> str:
        """QQ bot stack component."""



        key = f"{message.get('group_id')}:{str(message.get('user_id') or '').strip()}"
        exp = self._pending_pic.get(key, 0)
        if not exp:
            return ""
        if time.time() > exp:
            self._pending_pic.pop(key, None)
            return ""
        if not image_urls_of(message):
            return ""
        self._pending_pic.pop(key, None)
        with self._lock:
            cfg = dict(self._cfg)
        return self._learn_pic(cfg, message, str(message.get("user_id") or "").strip())

    def _learn_pic(self, cfg: Dict[str, Any], message: Dict[str, Any], sender: str) -> str:
        """QQ bot stack component."""







        urls = image_urls_of(message)
        if not urls:
            
            mid = reply_message_id(message)
            if mid:
                try:
                    got = self._onebot_get_msg(mid)
                    urls = segments_image_urls(got.get("message"))
                except Exception as e:  
                    logger.warning(f"[关键词] 学表情包：回查被回复的消息失败（id={mid}）："
                                   f"{type(e).__name__}: {e}")
        if not urls:
            
            
            
            self._pending_pic[f"{message.get('group_id')}:{sender}"] = \
                time.time() + PENDING_PIC_SEC
            return ("两种都行：① 长按那张图 → 引用 → 打「学表情包」；"
                    "② 就这样等着，2 分钟内把图发过来也认")
        emo = emoji_dir(cfg)
        try:
            os.makedirs(emo, exist_ok=True)
        except OSError as e:
            logger.error(f"[关键词] 学表情包：建目录失败 {emo}：{e}")
            return "表情包库这会儿写不进去…回头再试"
        try:
            max_mb = float(cfg.get("learn_pic_max_mb") or 5.0)
        except (TypeError, ValueError):
            max_mb = 5.0
        saved: List[str] = []
        dup = 0
        fail = 0
        for u in urls[:3]:                      
            try:
                data, ext = fetch_image(u, max_mb)
            except Exception as e:  
                logger.warning(f"[关键词] 学表情包：图下不下来（{u[:70]}）：{type(e).__name__}: {e}")
                fail += 1
                continue
            h = hashlib.sha256(data).hexdigest()
            dst = os.path.join(emo, h + ext)
            if os.path.exists(dst):
                dup += 1
                continue
            try:
                tmp = dst + ".tmp-learn"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dst)
            except OSError as e:
                logger.error(f"[关键词] 学表情包：写文件失败 {dst}：{e}")
                fail += 1
                continue
            saved.append(h)
        if not saved and not dup:
            return "图我没拿到…再发一次试试？"
        added = 0
        if saved:
            rec = learned_log(cfg)
            try:
                with open(rec, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:  
                d = {"items": []}
            items = d.setdefault("items", [])
            known = {str(i.get("hash")) for i in items if isinstance(i, dict)}
            for h in saved:
                if h in known:
                    continue
                items.append({"hash": h, "by": sender, "ts": time.time(),
                              "group_id": message.get("group_id")})
                added += 1
            try:
                with open(rec + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                os.replace(rec + ".tmp", rec)
            except OSError as e:
                logger.error(f"[关键词] 学表情包：记录写不进去 {rec}：{e}")
        logger.info(f"[关键词] 学表情包：群 {message.get('group_id')} 的 {sender} 教了 "
                    f"{added} 张（重复 {dup}，失败 {fail}）")
        if not added:
            return "这张我已经会了～换一张教我"
        tip = f"学会了 {added} 张表情包！"
        if dup:
            tip += f"（{dup} 张本来就有）"
        return tip + "麦麦两分钟内会把它们收编，之后要「表情包」就可能抽到"

    def _mylearn_line(self, cfg: Dict[str, Any], message: Dict[str, Any]) -> str:
        """QQ bot stack component."""
        sender = str(message.get("user_id") or "").strip()
        mine: List[str] = []
        try:
            with open(pool_path(cfg.get("quirky_file")), encoding="utf-8") as f:
                for it in (json.load(f).get("items") or []):
                    if isinstance(it, dict) and str(it.get("by") or "") == sender:
                        t = str(it.get("text") or "").strip()
                        if t:
                            mine.append(t)
        except Exception:  
            pass
        pics = 0
        try:
            with open(learned_log(cfg), encoding="utf-8") as f:
                pics = sum(1 for i in (json.load(f).get("items") or [])
                           if isinstance(i, dict) and str(i.get("by") or "") == sender)
        except Exception:  
            pass
        if not mine and not pics:
            return ("你还没教过我东西～发「学怪话 正文」教一句，"
                    "或者发张图说「学表情包」")
        lines = [f"你教过我 {len(mine)} 条怪话、{pics} 张表情包"]
        for t in mine[-5:]:
            lines.append("· " + (t if len(t) <= 40 else t[:40] + "…"))
        if len(mine) > 5:
            lines.append(f"（只列最近 5 条，一共 {len(mine)} 条）")
        return "\n".join(lines)

    def _learn_line(self, cfg: Dict[str, Any], message: Dict[str, Any],
                    rule: Dict[str, Any], word: str = "") -> str:
        """QQ bot stack component."""








        sender = str(message.get("user_id") or "").strip()
        admins = {str(a).strip() for a in (cfg.get("admins") or []) if str(a).strip()}
        if cfg.get("learn_admins_only") and sender not in admins:
            logger.debug("[关键词] 有人想教怪话但不是管理员（learn_admins_only），忽略")
            return ""
        words = list(rule.get("keywords") or []) + ["学怪话"]
        body = learn_payload(message, words)
        pics = image_urls_of(message)
        
        if ("表情" in word) or (not body and pics):
            return self._learn_pic(cfg, message, sender)
        if not body:
            return ("用法：@我说「学怪话」+ 正文，比如「学怪话 今天风好大，"
                    "吹得我头发都站起来了」")
        try:
            limit = int(cfg.get("learn_max_chars") or 500)
        except (TypeError, ValueError):
            limit = 500
        if limit > 0 and len(body) > limit:
            return f"这条太长了（{len(body)} 字，我最多记 {limit} 字），短的我才学得会～"
        
        
        bad = blocked_reason(body)
        if bad:
            logger.info(f"[关键词] 学怪话被护栏拦下（{bad}）：群 {message.get('group_id')} 的 {sender}")
            return "这条带攻击/烂梗/连锁信，我不学这个，换一条吧～"
        path = pool_path(cfg.get("quirky_file"))
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            items = d.get("items")
            if not isinstance(items, list):
                raise ValueError("库里没有 items 数组")
        except Exception as e:  
            logger.warning(f"[关键词] 学怪话：怪话库读不了（{path}）：{type(e).__name__}: {e}")
            return "怪话库这会儿读不了，等会儿再教我～"
        if any(str(i.get("text") or "").strip() == body for i in items if isinstance(i, dict)):
            return "这条我已经会了～换一条教我"
        
        items.append({"id": os.urandom(4).hex(), "text": body, "kind": "群友学的",
                      "enabled": True, "used": 0, "last_used": 0.0,
                      "by": sender, "by_ts": time.time()})
        d["items"] = items
        d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            tmp = path + ".tmp-learn"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:  
            logger.error(f"[关键词] 学怪话写库失败：{type(e).__name__}: {e}")
            return "记是记住了，但写不进库…回头再试"
        logger.info(f"[关键词] 学怪话：群 {message.get('group_id')} 的 {sender} 教了一条"
                    f"（{len(body)} 字，库里现在 {len(items)} 条）")
        head = body if len(body) <= 30 else body[:30] + "…"
        return f"学会了！「{head}」—— 库里现在 {len(items)} 条"

    def _favor_line(self, cfg: Dict[str, Any], message: Dict[str, Any]) -> str:
        """QQ bot stack component."""





        sender = str(message.get("user_id") or "").strip()
        admins = {str(a).strip() for a in (cfg.get("admins") or []) if str(a).strip()}
        if not admins or sender not in admins:
            logger.debug("[关键词] 有人想查好感度但不是管理员，忽略")
            return ""
        bot = str(self._bot_qq() or "")
        targets = [t for t in at_targets(message) if str(t).strip() and str(t) != bot]
        uid = str(targets[0]) if targets else sender      
        path = favor_file(cfg.get("favor_file"))
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            users = d.get("users") or {}
        except Exception as e:  
            logger.warning(f"[关键词] 好感度文件读不了（{path}）：{type(e).__name__}: {e}")
            return "好感度记录这会儿读不出来，回头再试～"
        u = users.get(uid)
        if not isinstance(u, dict):
            return f"没查到 QQ {uid} 的好感度记录（这个人可能还没跟麦麦说过话）"
        try:
            score = float(u.get("score", 100) or 0)
        except (TypeError, ValueError):
            score = 100.0
        try:
            hits = int(u.get("hits", 0) or 0)
        except (TypeError, ValueError):
            hits = 0
        name = str(u.get("name") or "").strip() or f"QQ {uid}"
        reason = str(u.get("last_reason") or "").strip()
        rank_txt = ""
        try:
            ranked = sorted(users.items(),
                            key=lambda kv: float((kv[1] or {}).get("score", 100) or 0),
                            reverse=True)
            for i, (k, _v) in enumerate(ranked):
                if str(k) == uid:
                    rank_txt = f" · 排第 {i + 1}/{len(ranked)}"
                    break
        except Exception:  
            rank_txt = ""
        tail = f" · 最近：{reason}" if reason else ""
        return (f"「{name}」对示例角色的好感度：{score:.0f}（{favor_label(score)}）"
                f" · 互动 {hits} 次{rank_txt}{tail}")

    
    def handle(self, message: Dict[str, Any]) -> Optional[str]:
        """QQ bot stack component."""



        self.reload()                      
        with self._lock:
            cfg = dict(self._cfg)
            rules = [r for r in (cfg.get("rules") or []) if isinstance(r, dict)]

        if not cfg.get("enabled", True) or not rules:
            return None
        if message.get("is_bot"):
            return None                    
        gid = message.get("group_id")
        if not gid:
            return None
        scope = [str(g).strip() for g in (cfg.get("groups") or []) if str(g).strip()]
        if scope and str(gid) not in scope:
            return None

        
        pend = self._pending_pic_check(message)
        if pend:
            if self._deliver(message, pend):
                self._sent += 1
                logger.info(f"[关键词] 群 {gid} 的「先说后发」表情包学完（共 {len(pend)} 字）")
                return pend
            return None

        
        pick = self._match_version_pick(message)
        if pick is not None:
            return self._handle_version_pick(*pick)

        
        say_text = self._match_say(message)
        if say_text is not None:
            return self._handle_say(message, gid, say_text)

        
        trim = self._match_pitch_trim(message)
        if trim is not None:
            return self._handle_pitch_trim(message, gid, *trim)

        
        if self._match_model_query(message):
            return self._handle_model_query(gid)

        idx, word = match_rule(message_text(message), rules)
        if idx < 0:
            return None
        rule = rules[idx]

        
        if rule_requires_at(rule) and not mentioned_bot(message, self._bot_qq()):
            self._skipped += 1
            logger.debug(f"[关键词] 群 {gid} 命中第 {idx + 1} 条但没 @ 机器人，跳过")
            return None

        self._hits += 1
        cd = float(cfg.get("cooldown_seconds") or 0)
        with self._lock:
            
            if not cooldown_ok(self._state, gid, idx, cd, mark=False):
                logger.debug(f"[关键词] 群 {gid} 第 {idx + 1} 条规则还在冷却（{cd:g}s），跳过")
                return None

        
        
        
        if not rule_type_known(rule):
            raw_t = str(rule.get("type") or "")
            with self._lock:
                first = raw_t not in self._unknown_types
                self._unknown_types.add(raw_t)
            if first:
                logger.warning(
                    f"[关键词] 群 {gid} 命中第 {idx + 1} 条，但规则类型 {raw_t!r} 本进程不认识"
                    f"（认识的：{'/'.join(KNOWN_RULE_TYPES)}）—— 规则 JSON 是热重载的、代码不是，"
                    f"这条规则会一直静默失效，**重启监控进程**即可")

        
        _rt = rule_type(rule)
        if _rt == "groupon":
            return self._handle_groupon(message, rule, gid, idx)
        if _rt == "sing":
            return self._handle_sing(message, rule, gid, idx, word)
        if _rt == "study":
            return self._handle_study(message, gid, idx)
        if _rt == "reflect":
            return self._handle_reflect(message, gid, idx)

        line = self._compose(rule, cfg, message, word)
        if not line:
            return None
        uid = message.get("user_id") or ""
        
        
        want_mention = rule.get("mention") if "mention" in rule else cfg.get("mention")
        at_qq = str(uid) if (want_mention and uid) else ""
        try:
            ok = bool(self.client.send_group_message(int(gid), line, at_qq=at_qq))
        except Exception as e:
            logger.error(f"[关键词] 发送失败: {type(e).__name__}: {e}")
            return None
        if ok:
            self._sent += 1
            with self._lock:
                
                cooldown_mark(self._state, gid, idx)
            _rt = rule_type(rule)
            kind = {"quirky": "随机怪话", "favor": "好感度查询", "learn": "学习",
                    "mylearn": "我教过的"}.get(_rt, "第 %d 条规则" % (idx + 1))
            logger.info(f"[关键词] 群 {gid} 有人提到「{word}」→ 已发{kind}"
                        f"（共 {len(line)} 字）")
            return line
        return None
