"""QQ bot stack component."""




import time
import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests

from .logger import setup_logger
from .net_utils import normalize_localhost

logger = setup_logger("history")


class HistoryFetcher:
    """QQ bot stack component."""

    def __init__(self, http_url: str, token: str = "",
                 monitor_groups: List[int] = None):
        self.http_url = (normalize_localhost(http_url) or "").rstrip("/")
        self.token = token
        self.monitor_groups = list(monitor_groups or [])

        self._session = requests.Session()
        
        
        
        
        
        
        self.timeout = 30

        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"

        self._fetched_seqs: Dict[int, int] = {}  
        self._lock = threading.Lock()

    def fetch_group_history(self, group_id: int,
                            count: int = 20,
                            message_seq: int = 0,
                            reverse_order: bool = None) -> List[Dict[str, Any]]:
        """QQ bot stack component."""



















        try:
            url = f"{self.http_url}/get_group_msg_history"
            payload = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": count
            }
            if reverse_order is not None:
                payload["reverseOrder"] = bool(reverse_order)

            resp = self._session.post(url, json=payload, timeout=self.timeout)
            result = resp.json()

            if result.get("status") == "ok" and result.get("data"):
                messages = result["data"].get("messages", [])
                logger.info(f"拉取群 {group_id} 历史消息: {len(messages)} 条")
                return messages
            else:
                logger.warning(f"拉取群 {group_id} 历史消息失败: {result.get('message', '未知错误')}")
                return []

        except Exception as e:
            logger.error(f"拉取历史消息异常: {e}")
            return []

    @staticmethod
    def _oldest_cursor(messages: List[Dict[str, Any]]) -> int:
        """QQ bot stack component."""
        best = None
        for m in messages:
            cur = m.get("message_id") or m.get("message_seq") or 0
            if not cur:
                continue
            t = m.get("time", 0)
            if best is None or t < best[0]:
                best = (t, cur)
        return int(best[1]) if best else 0

    def iter_history(self, group_id: int, page_size: int = 200,
                     max_pages: int = 0, stop_time: float = 0,
                     on_page=None):
        """QQ bot stack component."""












        cursor = 0
        page = 0
        seen = set()
        while True:
            messages = self.fetch_group_history(
                group_id=group_id, count=page_size,
                message_seq=cursor, reverse_order=True if cursor else None)
            page += 1
            if not messages:
                logger.info(f"群 {group_id}: 第{page}页为空，历史翻到头")
                break

            fresh = []
            for m in messages:
                mid = m.get("message_id")
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                fresh.append(m)
            if on_page:
                try:
                    on_page(fresh, page)
                except Exception as e:
                    logger.error(f"历史分页回调异常: {e}")
            for m in fresh:
                yield m

            if max_pages and page >= max_pages:
                logger.info(f"群 {group_id}: 到达页数上限 {max_pages}")
                break
            oldest = self._oldest_cursor(messages)
            if not oldest or oldest == cursor:
                logger.info(f"群 {group_id}: 游标不再前进（{cursor}），历史翻到头")
                break
            cursor = oldest
            if stop_time:
                oldest_t = min((m.get("time", 0) for m in messages), default=0)
                if oldest_t and oldest_t < stop_time:
                    logger.info(f"群 {group_id}: 已翻到时间下限，停止")
                    break
            time.sleep(0.3)   

    def fetch_all_history(self, group_id: int,
                          max_count: int = 1000,
                          callback=None) -> int:
        """QQ bot stack component."""










        total = 0
        
        
        for msg in self.iter_history(group_id=group_id, page_size=200,
                                     max_pages=max(1, max_count // 200 + 1)):
            total += 1
            if callback:
                try:
                    callback(msg)
                except Exception as e:
                    logger.error(f"历史消息回调异常: {e}")
            if total >= max_count:
                break

        logger.info(f"群 {group_id}: 历史消息拉取完成，共 {total} 条")
        return total

    def fetch_all_groups_history(self, max_count: int = 1000,
                                 callback=None) -> Dict[int, int]:
        """QQ bot stack component."""





        results = {}
        for group_id in self.monitor_groups:
            count = self.fetch_all_history(
                group_id=group_id,
                max_count=max_count,
                callback=callback
            )
            results[group_id] = count
        return results
