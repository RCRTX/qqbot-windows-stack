"""QQ bot stack component."""
















import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .logger import setup_logger

logger = setup_logger("marked_users")

MARK = "**"


_AT_RE = re.compile(r"\[CQ:at,[^\]]*?qq=([^,\]]+)[^\]]*\]")
_CQ_RE = re.compile(r"\[CQ:[^\]]+\]")


def at_targets(segments: List[Dict[str, Any]], bot_qq: Any = None) -> List[str]:
    """QQ bot stack component."""



    out: List[str] = []
    seen = set()
    for seg in segments or []:
        if not isinstance(seg, dict) or seg.get("type") != "at":
            continue
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        qq = str(data.get("qq") or seg.get("qq") or "").strip()
        if not qq or qq in ("all", "0"):
            continue
        if bot_qq not in (None, "") and qq == str(bot_qq):
            continue
        if qq in seen:
            continue
        seen.add(qq)
        out.append(qq)
    return out


def at_targets_raw(raw_message: str, bot_qq: Any = None) -> List[str]:
    """QQ bot stack component."""
    out: List[str] = []
    seen = set()
    for m in _AT_RE.finditer(str(raw_message or "")):
        qq = m.group(1).strip()
        if not qq or qq in ("all", "0"):
            continue
        if bot_qq not in (None, "") and qq == str(bot_qq):
            continue
        if qq in seen:
            continue
        seen.add(qq)
        out.append(qq)
    return out


def message_plain_text(message: Dict[str, Any]) -> str:
    """QQ bot stack component."""




    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    text = ""
    if isinstance(content, dict):
        text = str(content.get("text") or "")
    if not text:
        text = str(message.get("raw_message") or "")
    return _CQ_RE.sub("", text).strip()


def is_mark_request(message: Dict[str, Any], bot_qq: Any = None) -> Tuple[List[str], str]:
    """QQ bot stack component."""



    if not isinstance(message, dict):
        return [], ""
    content = message.get("content")
    segments = content.get("segments") if isinstance(content, dict) else None
    targets = at_targets(segments or [], bot_qq)
    if not targets:
        targets = at_targets_raw(message.get("raw_message") or "", bot_qq)
    text = message_plain_text(message)
    if not targets or MARK not in text:
        return [], text
    return targets, text


class MarkedUserStore:
    """QQ bot stack component."""

    FILE_NAME = "marked_users.jsonl"
    MAX_TEXT = 200          
    GROUP_NAME_TTL = 600    
    MEMBER_TTL = 3600       

    def __init__(self, data_dir: str, enabled: bool = True, client: Any = None,
                 max_text: int = MAX_TEXT):
        self.data_dir = data_dir
        self.enabled = bool(enabled)
        self.client = client
        self.max_text = int(max_text)
        self._gname: Dict[str, str] = {}
        self._gname_at = 0.0
        self._member: Dict[str, Dict[str, Any]] = {}   
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return os.path.join(self.data_dir, self.FILE_NAME)

    def group_name(self, group_id: Any) -> str:
        """QQ bot stack component."""
        now = time.time()
        if self.client is not None and now - self._gname_at > self.GROUP_NAME_TTL:
            self._gname_at = now
            try:
                for g in self.client.get_group_list() or []:
                    gid = g.get("group_id")
                    if gid is not None:
                        self._gname[str(gid)] = str(g.get("group_name") or "")
            except Exception as e:
                logger.warning(f"取群名失败（不影响标记记录）: {e}")
        return self._gname.get(str(group_id), "")

    def member_info(self, group_id: Any, qq: Any) -> Dict[str, Any]:
        """QQ bot stack component."""




        key = f"{group_id}:{qq}"
        cached = self._member.get(key)
        now = time.time()
        if cached and now - cached.get("_at", 0) < self.MEMBER_TTL:
            return cached
        info: Dict[str, Any] = {"nickname": "", "card": "", "role": ""}
        if self.client is not None:
            try:
                d = self.client.get_group_member_info(int(group_id), int(qq)) or {}
                info = {
                    "nickname": str(d.get("nickname") or ""),
                    "card": str(d.get("card") or ""),
                    "role": str(d.get("role") or ""),
                }
            except Exception as e:
                logger.debug(f"取群成员信息失败（不影响标记）: {e}")
        info["_at"] = now
        self._member[key] = info
        return info

    def build_records(self, message: Dict[str, Any],
                      bot_qq: Any = None) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        if not self.enabled or not isinstance(message, dict):
            return []
        if str(message.get("message_type") or "group") != "group":
            return []
        targets, text = is_mark_request(message, bot_qq)
        if not targets:
            return []

        gid = message.get("group_id")
        gname = self.group_name(gid)
        ts = str(message.get("datetime") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        by_qq = str(message.get("user_id") or "")
        by_nick = str(message.get("card") or message.get("nickname") or "")
        snippet = text[: self.max_text]

        recs = []
        for qq in targets:
            info = self.member_info(gid, qq)
            recs.append({
                "ts": ts,
                "qq": qq,                                   
                "nickname": info.get("nickname", ""),
                "card": info.get("card", ""),
                "role": info.get("role", ""),               
                "by_qq": by_qq,                             
                "by_nickname": by_nick,
                "group_id": str(gid if gid is not None else ""),
                "group_name": gname,
                "text": snippet,
            })
        return recs

    def maybe_record(self, message: Dict[str, Any],
                     bot_qq: Any = None) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        try:
            recs = self.build_records(message, bot_qq)
            if not recs:
                return []
            out = []
            for rec in recs:
                if self.append(rec):
                    out.append(rec)
            return out
        except Exception as e:
            logger.error(f"标记用户处理异常（已忽略）: {e}")
            return []

    def append(self, rec: Dict[str, Any]) -> bool:
        with self._lock:
            try:
                os.makedirs(self.data_dir, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return True
            except Exception as e:
                logger.error(f"写标记流水失败: {e}")
                return False

    @staticmethod
    def read_records(path: str) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        recs: List[Dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        recs.append(obj)
        except FileNotFoundError:
            return []
        return recs
