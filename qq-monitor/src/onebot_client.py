"""QQ bot stack component."""













import json
import logging
import time
import threading
import traceback
from typing import Callable, Optional, Dict, Any, List
from datetime import datetime

import websocket

from .logger import setup_logger
from .net_utils import normalize_localhost

logger = setup_logger("napcat")


class OneBotClient:
    """QQ bot stack component."""

    def __init__(self, ws_url: str, token: str = "",
                 monitor_groups: List[int] = None,
                 http_url: str = ""):
        """QQ bot stack component."""








        self.ws_url = normalize_localhost(ws_url)
        self.token = token
        self.monitor_groups = set(monitor_groups or [])
        self.http_url = (normalize_localhost(http_url) or "").rstrip("/")

        self._ws: Optional[websocket.WebSocketApp] = None
        self._running = False
        self._connected = False
        self._reconnect_interval = 5
        self._max_reconnect_interval = 60
        self._current_reconnect_interval = self._reconnect_interval
        
        self._last_event_ts = 0.0
        self._watchdog_started = False
        self._message_callbacks: List[Callable] = []
        self._notice_callbacks: List[Callable] = []
        self._private_message_callbacks: List[Callable] = []
        
        self._keyword_callbacks: List[Callable] = []
        self._connection_callbacks: List[Callable] = []
        self._bot_qq = ""
        self._disconnection_callbacks: List[Callable] = []

        
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()

        
        self._stats = {
            "total_messages": 0,
            "filtered_messages": 0,
            "last_message_time": None,
            "connection_count": 0,
            "errors": 0
        }

    def on_notice(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._notice_callbacks.append(callback)

    def _emit_notice(self, parsed: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        with self._buffer_lock:
            self._message_buffer.append(parsed)
        for callback in self._notice_callbacks:
            try:
                callback(parsed)
            except Exception as e:  
                logger.error(f"通知回调执行失败: {e}")

    def send_poke(self, group_id: int, user_id: int) -> bool:
        """QQ bot stack component."""



        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法戳一戳")
            return False
        try:
            import requests
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            
            
            
            
            
            if group_id:
                path, payload = "/group_poke", {"group_id": group_id, "user_id": user_id}
            else:
                path, payload = "/friend_poke", {"user_id": user_id}
            resp = requests.post(f"{self.http_url}{path}", json=payload,
                                 headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                return True
            logger.warning(f"戳一戳失败: {resp.status_code} {resp.text[:120]}")
            return False
        except Exception as e:  
            logger.error(f"戳一戳异常: {e}")
            return False

    def on_message(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._message_callbacks.append(callback)

    def on_any_group_message(self, callback: Callable) -> None:
        """QQ bot stack component."""




        self._keyword_callbacks.append(callback)

    def on_private_message(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._private_message_callbacks.append(callback)

    def on_connect(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._connection_callbacks.append(callback)

    def on_disconnect(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._disconnection_callbacks.append(callback)

    def start(self) -> None:
        """QQ bot stack component."""
        if not self._running:
            
            
            
            self._current_reconnect_interval = self._reconnect_interval
        self._running = True

        
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        self._ws = websocket.WebSocketApp(
            self.ws_url,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_ws_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        
        
        
        
        
        
        
        
        ws_thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={"ping_interval": 60, "ping_timeout": 45},
            
            
            daemon=True,
            name="NapCat-WS"
        )
        ws_thread.start()
        logger.info(f"OneBot(SnowLuma) WebSocket 客户端已启动，连接地址: {self.ws_url}")
        self._start_watchdog()

    def _start_watchdog(self) -> None:
        """QQ bot stack component."""













        if self._watchdog_started:
            return
        self._watchdog_started = True

        def loop():
            while self._running:
                time.sleep(30)
                try:
                    last = self._last_event_ts
                    if last and (time.time() - last) > 100:
                        idle = int(time.time() - last)
                        logger.warning(f"WebSocket 已 {idle} 秒没有任何事件（含心跳），判定连接失效，主动重连")
                        self._last_event_ts = time.time()   
                        try:
                            if self._ws:
                                self._ws.close()            
                        except Exception as e:
                            logger.error(f"关闭失效连接失败: {e}")
                except Exception as e:
                    logger.error(f"WS看门狗出错: {e}")

        threading.Thread(target=loop, daemon=True, name="NapCat-WS-Watchdog").start()

    def stop(self) -> None:
        """QQ bot stack component."""
        self._running = False
        self._connected = False
        if self._ws:
            self._ws.close()
        logger.info("NapCat WebSocket客户端已停止")

    def get_buffered_messages(self) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        with self._buffer_lock:
            messages = self._message_buffer.copy()
            self._message_buffer.clear()
        return messages

    def get_stats(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        stats = self._stats.copy()
        stats["is_connected"] = self._connected
        return stats

    def _on_open(self, ws) -> None:
        """QQ bot stack component."""
        self._current_reconnect_interval = self._reconnect_interval
        self._connected = True
        self._stats["connection_count"] += 1
        logger.info("已连接到 OneBot(SnowLuma) WebSocket 服务")

        self._last_event_ts = time.time()   

        
        for callback in self._connection_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"连接回调执行失败: {e}")

    def _on_ws_message(self, ws, message: str) -> None:
        """QQ bot stack component."""
        self._last_event_ts = time.time()   
        
        
        if logger.isEnabledFor(logging.DEBUG):
            try:
                quick = json.loads(message)
                if quick.get("post_type", "?") != "meta_event":  
                    logger.debug(f"WS原始消息: {message[:300]}")
            except Exception:
                logger.debug(f"WS非JSON消息: {message[:200]}")

        try:
            data = json.loads(message)
            post_type = data.get("post_type", "")

            
            self_id = data.get("self_id", "")
            if self_id and not self._bot_qq:
                self._bot_qq = str(self_id)
                logger.info(f"从WebSocket消息中获取到机器人QQ号: {self._bot_qq}")

            if post_type == "message":
                msg_type = data.get("message_type", "")
                group_id = data.get("group_id", "?")
                sender = data.get("sender", {}).get("nickname", "") or data.get("sender", {}).get("card", "")
                logger.debug(f"WS收到消息: type={msg_type}, group={group_id}, sender={sender}")
                self._handle_message(data)
            elif post_type == "message_sent":
                
                
                
                
                logger.debug(f"WS收到自发言: group={data.get('group_id')}")
                self._handle_message(data, is_self=True)
            elif post_type == "meta_event":
                
                pass
            elif post_type == "notice":
                self._handle_notice(data)

        except json.JSONDecodeError:
            logger.warning(f"收到非JSON消息: {message[:200]}")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}\n{traceback.format_exc()}")
            self._stats["errors"] += 1

    def _handle_message(self, data: Dict[str, Any], is_self: bool = False) -> None:
        """QQ bot stack component."""




        message_type = data.get("message_type", "")
        group_id = data.get("group_id", 0)

        
        if message_type == "private":
            text = self._extract_plain_text(data.get("message", []), data.get("raw_message", ""))
            parsed_private = {
                "type": "private_message",
                "user_id": data.get("user_id", 0),
                "time": data.get("time", 0),
                "datetime": datetime.fromtimestamp(data.get("time", time.time())).strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "is_bot": is_self,
                "raw": data
            }
            for callback in self._private_message_callbacks:
                try:
                    callback(parsed_private)
                except Exception as e:
                    logger.error(f"私聊消息回调执行失败: {e}")
            return

        
        if message_type != "group":
            return

        
        
        
        
        monitored = (not self.monitor_groups) or (group_id in self.monitor_groups)
        parsed = None
        if not is_self and self._keyword_callbacks and not monitored:
            try:
                parsed = self._parse_message(data)
                for callback in self._keyword_callbacks:
                    callback(parsed)
            except Exception as e:
                logger.error(f"关键词回调执行失败: {e}")

        if not monitored:
            self._stats["filtered_messages"] += 1
            return

        self._stats["total_messages"] += 1
        self._stats["last_message_time"] = datetime.now().isoformat()

        
        if parsed is None:
            parsed = self._parse_message(data)
        if is_self or self.is_bot_message(parsed):
            parsed["is_bot"] = True
        if is_self:
            self._stats["self_messages"] = self._stats.get("self_messages", 0) + 1

        
        with self._buffer_lock:
            self._message_buffer.append(parsed)

        
        if not is_self and self._keyword_callbacks:
            for callback in self._keyword_callbacks:
                try:
                    callback(parsed)
                except Exception as e:
                    logger.error(f"关键词回调执行失败: {e}")

        
        for callback in self._message_callbacks:
            try:
                callback(parsed)
            except Exception as e:
                logger.error(f"消息回调执行失败: {e}")

    def _handle_notice(self, data: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        notice_type = data.get("notice_type", "")
        group_id = data.get("group_id", 0)

        
        
        
        
        
        if notice_type == "poke" or (notice_type == "notify"
                                     and str(data.get("sub_type") or "") == "poke"):
            self._emit_notice({
                "type": "notice", "notice_type": "poke",
                "sub_type": data.get("sub_type", ""), "group_id": group_id,
                "user_id": data.get("user_id", 0),
                "target_id": data.get("target_id", 0),
                "time": data.get("time", 0), "raw": data,
            })
            return

        if self.monitor_groups and group_id not in self.monitor_groups:
            return

        if notice_type in ("group_increase", "group_decrease", "group_ban"):
            parsed = {
                "type": "notice",
                "notice_type": notice_type,
                "group_id": group_id,
                "user_id": data.get("user_id", 0),
                "operator_id": data.get("operator_id", 0),
                "sub_type": data.get("sub_type", ""),
                "time": data.get("time", 0),
                "raw": data
            }
            with self._buffer_lock:
                self._message_buffer.append(parsed)

            for callback in self._message_callbacks:
                try:
                    callback(parsed)
                except Exception as e:
                    logger.error(f"通知回调执行失败: {e}")

    def is_bot_message(self, message: Dict[str, Any]) -> bool:
        """QQ bot stack component."""





        try:
            uid = str(message.get("user_id") or "")
            if not uid:
                return False
            for cand in (message.get("self_id"), getattr(self, "_bot_qq", "")):
                if cand and str(cand) == uid:
                    return True
            return False
        except Exception:
            return False

    def _parse_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """QQ bot stack component."""





























        message_segments = data.get("message", [])
        raw_message = data.get("raw_message", "")
        time_ts = data.get("time", 0)
        group_id = data.get("group_id", 0)

        
        segments = []
        text_parts = []
        has_image = False
        has_face = False
        image_urls = []
        file_count = 0

        for seg in message_segments:
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})

            if seg_type == "text":
                text = seg_data.get("text", "").strip()
                if text:
                    text_parts.append(text)
                    segments.append({"type": "text", "data": {"text": text}})

            elif seg_type == "image":
                has_image = True
                url = seg_data.get("url", "")
                file = seg_data.get("file", "")
                image_urls.append(url)
                segments.append({
                    "type": "image",
                    "data": {
                        "url": url,
                        "file": file,
                        "summary": "[图片]"
                    }
                })

            elif seg_type == "face":
                has_face = True
                face_id = seg_data.get("id", "")
                segments.append({
                    "type": "face",
                    "data": {
                        "id": face_id,
                        "summary": f"[表情:{face_id}]"
                    }
                })

            elif seg_type == "at":
                qq = seg_data.get("qq", "all")
                name = seg_data.get("name", "")
                segments.append({
                    "type": "at",
                    "data": {"qq": qq, "name": name}
                })

            elif seg_type == "reply":
                msg_id = seg_data.get("id", "")
                msg_text = seg_data.get("msg", "")[:100]
                segments.append({
                    "type": "reply",
                    "data": {"id": msg_id, "msg_preview": msg_text}
                })

            elif seg_type == "record":
                url = seg_data.get("url", "")
                segments.append({
                    "type": "voice",
                    "data": {"url": url, "summary": "[语音消息]"}
                })

            elif seg_type == "video":
                url = seg_data.get("url", "")
                segments.append({
                    "type": "video",
                    "data": {
                        "url": url,
                        "file": seg_data.get("file", ""),
                        "name": seg_data.get("name", seg_data.get("file", "")),
                        "size": seg_data.get("size", 0),
                        "summary": "[视频]"
                    }
                })

            elif seg_type == "file":
                file_count += 1
                name = seg_data.get("name", "") or seg_data.get("file", "") or "文件"
                segments.append({
                    "type": "file",
                    "data": {
                        "url": seg_data.get("url", ""),
                        "file": seg_data.get("file", ""),
                        "name": name,
                        "size": seg_data.get("size", 0),
                        "file_id": seg_data.get("file_id", ""),
                        "summary": f"[文件:{name}]"
                    }
                })

            elif seg_type == "forward":
                segments.append({
                    "type": "forward",
                    "data": {"summary": "[合并转发消息]"}
                })

            elif seg_type == "json":
                data_str = seg_data.get("data", "")
                segments.append({
                    "type": "json",
                    "data": {"raw": data_str, "summary": "[JSON消息]"}
                })

            elif seg_type == "xml":
                data_str = seg_data.get("data", "")
                segments.append({
                    "type": "xml",
                    "data": {"raw": data_str, "summary": "[XML消息]"}
                })

            else:
                segments.append({
                    "type": seg_type,
                    "data": seg_data,
                    "summary": f"[{seg_type}]"
                })

        
        content_summary = " ".join(text_parts)
        if has_image:
            content_summary += f" [包含{len(image_urls)}张图片]"
        if has_face:
            content_summary += " [包含表情]"
        if file_count:
            content_summary += f" [包含{file_count}个文件]"

        
        try:
            dt = datetime.fromtimestamp(time_ts)
            datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        
        sender = data.get("sender", {})
        nickname = sender.get("nickname", "")
        card = sender.get("card", "") or nickname
        role = sender.get("role", "member")

        return {
            "type": "message",
            "message_id": data.get("message_id", 0),
            "group_id": group_id,
            "user_id": data.get("user_id", 0),
            "nickname": nickname,
            "card": card,
            "role": role,
            "time": time_ts,
            "datetime": datetime_str,
            "message_type": "group",
            "sub_type": data.get("sub_type", "normal"),
            "raw_message": raw_message,
            "content": {
                "text": content_summary.strip(),
                "segments": segments,
                "has_image": has_image,
                "has_face": has_face,
                "image_urls": image_urls
            },
            "raw": data
        }

    def _extract_plain_text(self, message_segments: List[Dict[str, Any]], raw_message: str = "") -> str:
        """QQ bot stack component."""
        parts = []
        for seg in message_segments or []:
            if seg.get("type") == "text":
                text = seg.get("data", {}).get("text", "").strip()
                if text:
                    parts.append(text)
        return " ".join(parts).strip() or raw_message.strip()

    def _on_error(self, ws, error) -> None:
        """QQ bot stack component."""
        self._stats["errors"] += 1
        logger.error(f"WebSocket错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        """QQ bot stack component."""
        self._connected = False
        logger.warning(f"WebSocket连接已关闭 (code={close_status_code}, msg={close_msg})")

        for callback in self._disconnection_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"断开回调执行失败: {e}")

        
        if self._running:
            logger.info(f"{self._current_reconnect_interval}秒后尝试重连...")
            time.sleep(self._current_reconnect_interval)
            self._current_reconnect_interval = min(
                self._current_reconnect_interval * 2,
                self._max_reconnect_interval
            )
            self.start()

    def send_group_message(self, group_id: int, message: str, at_qq: str = "") -> bool:
        """QQ bot stack component."""



        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法发送消息")
            return False

        try:
            import requests
            url = f"{self.http_url}/send_group_msg"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            segments: List[Dict[str, Any]] = []
            if str(at_qq or "").strip():
                segments.append({"type": "at", "data": {"qq": str(at_qq).strip()}})
                segments.append({"type": "text", "data": {"text": " " + message}})
            else:
                segments.append({"type": "text", "data": {"text": message}})

            payload = {
                "group_id": group_id,
                "message": segments
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    logger.info(f"已向群 {group_id} 发送消息")
                    return True
                else:
                    logger.error(f"发送消息失败: {data}")
                    return False
            else:
                logger.error(f"发送消息HTTP错误: {resp.status_code}")
                return False

        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False

    def send_private_message(self, user_id: int, message: str) -> bool:
        """QQ bot stack component."""
        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法发送私聊消息")
            return False

        try:
            import requests
            url = f"{self.http_url}/send_private_msg"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            payload = {
                "user_id": user_id,
                "message": [{"type": "text", "data": {"text": message}}]
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    logger.info(f"已向用户 {user_id} 发送私聊消息")
                    return True
                else:
                    logger.error(f"发送私聊消息失败: {data}")
                    return False
            else:
                logger.error(f"发送私聊消息HTTP错误: {resp.status_code}")
                return False

        except Exception as e:
            logger.error(f"发送私聊消息异常: {e}")
            return False

    def get_login_info(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        if not self.http_url:
            return {}
        try:
            import requests
            url = f"{self.http_url}/get_login_info"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
        return {}

    def get_group_member_info(self, group_id: int, user_id: int,
                              timeout: float = 2.0) -> Dict[str, Any]:
        """QQ bot stack component."""




        if not self.http_url:
            return {}
        try:
            import requests
            url = f"{self.http_url}/get_group_member_info"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            resp = requests.get(url, headers=headers,
                                params={"group_id": group_id, "user_id": user_id},
                                timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and isinstance(data.get("data"), dict):
                    return data["data"]
                logger.debug(f"取群成员信息失败: {data}")
            else:
                logger.debug(f"取群成员信息HTTP错误: {resp.status_code}")
        except Exception as e:
            logger.debug(f"取群成员信息异常（不影响标记）: {e}")
        return {}

    def get_group_list(self) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法获取群列表")
            return []
        try:
            import requests
            url = f"{self.http_url}/get_group_list"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    groups = data.get("data", [])
                    logger.info(f"获取到 {len(groups)} 个群")
                    return groups
                else:
                    logger.error(f"获取群列表失败: {data}")
            else:
                logger.error(f"获取群列表HTTP错误: {resp.status_code}")
        except Exception as e:
            logger.error(f"获取群列表异常: {e}")
        return []

    def get_group_info(self, group_id: int) -> Dict[str, Any]:
        """QQ bot stack component."""
        if not self.http_url:
            return {}
        try:
            import requests
            url = f"{self.http_url}/get_group_info"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            params = {"group_id": group_id, "no_cache": True}
            resp = requests.get(url, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"获取群信息失败: {e}")
        return {}

    @property
    def bot_qq(self) -> str:
        """QQ bot stack component."""
        if not hasattr(self, '_bot_qq'):
            self._bot_qq = ""
        if not self._bot_qq:
            
            
            info = self.get_login_info()
            qq = str(info.get("user_id", ""))
            if qq:
                self._bot_qq = qq
                logger.info(f"通过HTTP API获取到机器人QQ号: {self._bot_qq}")
            
        return self._bot_qq
