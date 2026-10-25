
"""QQ bot stack component."""
















from __future__ import annotations

import os
import random
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

DEFAULT_TEXTS = ["戳我干嘛", "别戳了别戳了", "再戳要收费了啊", "有事说事",
                 "痒", "手别抖", "戳坏了你赔"]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class PokeManager:
    """QQ bot stack component."""

    def __init__(self, config: Any, client: Any, logger: Any):
        self.config = config
        self.client = client
        self.logger = logger
        
        
        cfg = (getattr(config, "_config", None) or {}).get("poke") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        self.cfg = cfg
        self._lock = threading.Lock()
        
        
        
        
        
        self._last_event: Dict[str, float] = {}
        
        self._daily: Dict[str, tuple] = {}
        self._last_active = 0.0

    
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled"))

    def _bot_qq(self) -> str:
        return str(self.cfg.get("bot_qq") or getattr(self.client, "bot_qq", "") or "")

    def _db(self) -> str:
        p = str(self.cfg.get("maibot_db") or "").strip()
        return p or os.path.join(os.environ.get("MAIBOT_HOME") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bot", "MaiBotOneKey"), "modules", "MaiBot", "data", "MaiBot.db")

    
    def on_notice(self, notice: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        if not self.enabled or not isinstance(notice, dict):
            return
        nt = str(notice.get("notice_type") or "")
        st = str(notice.get("sub_type") or "")
        if not (nt == "poke" or (nt == "notify" and st == "poke")):
            return
        target = str(notice.get("target_id") or "")
        if target != self._bot_qq():
            return                      
        uid = str(notice.get("user_id") or "")
        gid = notice.get("group_id") or 0
        if not uid or uid == self._bot_qq():
            return                      

        rep = self.cfg.get("reply") or {}
        if not rep.get("enabled", True):
            return
        
        
        dedupe = float(rep.get("dedupe_seconds", 2) or 0)
        now = time.time()
        dkey = f"{gid or 0}:{uid}"
        if dedupe > 0:
            with self._lock:
                if now - self._last_event.get(dkey, 0) < dedupe:
                    self.logger.info(f"[戳] 忽略重复投递（{dedupe:g}s 内同一次点击）："
                                     f"{uid} @ 群 {gid}")
                    return
                self._last_event[dkey] = now

        back = bool(rep.get("poke_back", True))
        try:
            if back:
                self.client.send_poke(int(gid) if gid else 0, int(uid))
            sent_text = False
            chance = float(rep.get("text_chance") or 0)
            if chance > 0 and random.random() < chance:
                texts = rep.get("texts") or DEFAULT_TEXTS
                line = random.choice(list(texts))
                if gid:
                    self.client.send_group_message(int(gid), line)
                else:
                    self.client.send_private_message(int(uid), line)
                sent_text = True
            self.logger.info(f"[戳] 被 {uid} 戳了 → {'戳回去' if back else ''}"
                             f"{' + 配文' if sent_text else ''}（群 {gid}）")
        except Exception as e:  
            self.logger.error(f"[戳] 回应失败: {type(e).__name__}: {e}")

    
    def active_poke_once(self) -> Optional[str]:
        """QQ bot stack component."""
        if not self.enabled:
            return None
        act = self.cfg.get("active") or {}
        if not act.get("enabled", True):
            return None

        now = time.time()
        gap = float(act.get("min_gap_minutes") or 30) * 60
        if now - self._last_active < gap:
            return None

        groups = self._candidate_groups(act)
        if not groups:
            return None
        random.shuffle(groups)
        for gid in groups:
            today, used = self._daily.get(str(gid), (_today(), 0))
            if today != _today():
                used = 0
            limit = int(act.get("daily_limit_per_group") or 4)
            if used >= limit:
                continue
            target = self._pick_target(gid, act)
            if not target:
                continue
            try:
                self.client.send_poke(int(gid), int(target))
            except Exception as e:  
                self.logger.error(f"[戳] 主动戳失败（群 {gid} 用户 {target}）："
                                  f"{type(e).__name__}: {e}")
                continue
            with self._lock:
                self._daily[str(gid)] = (_today(), used + 1)
                self._last_active = now
            self.logger.info(f"[戳] 主动戳了群 {gid} 的 {target}（该群今天第 {used + 1}/{limit} 次）")
            return f"{gid}:{target}"
        return None

    def _candidate_groups(self, act: Dict[str, Any]) -> List[str]:
        """QQ bot stack component."""
        want = [str(x) for x in (act.get("groups") or []) if str(x).strip()]
        if want:
            return want
        nap = (getattr(self.config, "_config", None) or {}).get("napcat") or {}
        return [str(x) for x in (nap.get("monitor_groups") or [])]

    def _pick_target(self, group_id: str, act: Dict[str, Any]) -> Optional[str]:
        """QQ bot stack component."""




        if not os.path.exists(self._db()):
            self.logger.warning(f"[戳] 找不到麦麦数据库 {self._db()}，主动戳跳过")
            return None
        minutes = int(act.get("recent_minutes") or 30)
        min_msgs = int(act.get("min_messages") or 3)
        skip = {str(x) for x in (act.get("skip_users") or [])}
        skip.add(self._bot_qq())
        try:
            con = sqlite3.connect(f"file:{self._db()}?mode=ro", uri=True)
            try:
                cur = con.cursor()
                cur.execute("""SELECT user_id, COUNT(*) AS n FROM mai_messages
                               WHERE group_id = ?
                                 AND timestamp > strftime('%Y-%m-%d %H:%M:%S','now','localtime',?)
                               GROUP BY user_id HAVING n >= ?
                               ORDER BY n DESC LIMIT 8""",
                            (group_id, f"-{minutes} minutes", min_msgs))
                cands = [str(r[0]) for r in cur.fetchall()
                         if r[0] and str(r[0]) not in skip]
            finally:
                con.close()
        except Exception as e:  
            self.logger.warning(f"[戳] 查活跃用户失败（群 {group_id}）：{type(e).__name__}: {e}")
            return None
        return random.choice(cands) if cands else None
