"""QQ bot stack component."""





import json
import os
import shutil
import gzip
import threading
import time
import requests
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque

from .logger import setup_logger

logger = setup_logger("storage")


class MessageStore:
    """QQ bot stack component."""

    
    
    
    
    
    IMAGE_MAX_ATTEMPTS = 3
    IMAGE_RETRY_BACKOFF = (0.4, 1.0)   
    IMAGE_TIMEOUT = 20                 

    def __init__(self, data_dir: str, log_dir: str,
                 max_storage_mb: int = 500,
                 archive_days: int = 30,
                 file_rotate_hours: int = 24,
                 save_images: bool = True,
                 max_image_size_mb: int = 5,
                 save_files: bool = True,
                 large_file_confirm_mb: int = 1024,
                 max_alert_records: int = 1000,
                 max_memory_index_per_group: int = 10000,
                 max_saved_ids: int = 200000,
                 max_finished_pending_records: int = 200,
                 auto_cleanup_enabled: bool = False):
        """QQ bot stack component."""









        self.data_dir = data_dir
        self.max_storage_mb = max_storage_mb
        self.archive_days = archive_days
        self.file_rotate_hours = file_rotate_hours
        self.save_images = save_images
        self.max_image_size_mb = max_image_size_mb
        self.save_files = save_files
        self.large_file_confirm_mb = large_file_confirm_mb
        self.max_alert_records = max_alert_records
        
        self.auto_cleanup_enabled = bool(auto_cleanup_enabled)
        self._large_file_threshold_bytes = max(1, large_file_confirm_mb) * 1024 * 1024
        
        
        
        self._last_image_error = ""

        
        self._group_dirs: Dict[int, str] = {}
        
        self._file_handles: Dict[str, Any] = {}
        self._file_lock = threading.Lock()
        self._storage_stats_lock = threading.Lock()
        self._storage_stats_sizes = None
        self._storage_stats_updated = 0.0
        self._storage_stats_refreshing = False
        self._current_date: Dict[int, str] = {}

        
        self._index: Dict[int, List[Dict]] = defaultdict(list)
        self._index_lock = threading.Lock()
        self._max_index_per_group = max_memory_index_per_group  
        
        self._trimmed_dates: set = set()

        
        self._saved_message_ids: set = set()
        self._saved_ids_order: deque = deque()
        self._max_saved_ids = max_saved_ids
        self._saved_ids_lock = threading.Lock()

        
        self._alerts: List[Dict] = []
        self._alerts_lock = threading.Lock()
        
        self._alerts_file_lock = threading.Lock()

        
        self._pending_files: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._large_file_callbacks: List[Any] = []
        self._max_finished_pending = max_finished_pending_records

        
        os.makedirs(data_dir, exist_ok=True)

        
        self._load_history()
        self._load_pending_files()

        logger.info(f"存储管理器初始化完成，数据目录: {data_dir}")

    def _load_history(self) -> None:
        """QQ bot stack component."""
        if not os.path.exists(self.data_dir):
            return

        loaded_messages = 0
        loaded_alerts = 0

        
        
        
        loaded_ids: Dict[Any, int] = {}
        duplicate_lines = 0
        for group_name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, group_name)
            if not os.path.isdir(group_path):
                continue

            try:
                group_id = int(group_name)
            except ValueError:
                
                continue

            
            all_files = []
            for filename in os.listdir(group_path):
                if filename.startswith("alerts"):
                    continue
                if filename.endswith(".jsonl") or filename.endswith(".jsonl.gz"):
                    all_files.append(filename)

            
            all_files.sort()

            for filename in all_files:

                file_path = os.path.join(group_path, filename)
                try:
                    
                    is_gz = filename.endswith(".gz")
                    
                    if is_gz:
                        import gzip
                        f = gzip.open(file_path, 'rt', encoding='utf-8')
                    else:
                        f = open(file_path, 'r', encoding='utf-8')
                    
                    with f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                                mid = msg.get("message_id", 0)
                                if mid:
                                    prev_idx = loaded_ids.get(mid)
                                    if prev_idx is not None:
                                        duplicate_lines += 1
                                        
                                        if self._message_richness(msg) > \
                                                self._message_richness(self._index[group_id][prev_idx]):
                                            self._index[group_id][prev_idx] = msg
                                        continue
                                    loaded_ids[mid] = len(self._index[group_id])
                                    
                                    self._remember_saved_id_locked(mid)
                                self._index[group_id].append(msg)
                                loaded_messages += 1
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    logger.error(f"加载历史文件失败: {file_path}, 错误: {e}")

            
            with self._index_lock:
                self._trim_index_locked(group_id)

        
        alerts_file = os.path.join(self.data_dir, "alerts.jsonl")
        if os.path.exists(alerts_file):
            try:
                with open(alerts_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            alert = json.loads(line)
                            if not alert.get("alert_id"):
                                alert["alert_id"] = uuid.uuid4().hex[:12]
                            self._alerts.append(alert)
                            loaded_alerts += 1
                        except json.JSONDecodeError:
                            continue
                
                if len(self._alerts) > self.max_alert_records:
                    self._alerts = self._alerts[-self.max_alert_records:]
            except Exception as e:
                logger.error(f"加载历史告警失败: {e}")

        if duplicate_lines:
            logger.warning(
                f"历史文件中发现并跳过了 {duplicate_lines} 条重复记录"
                f"（message_id 重复，已保留信息更全的那一份）"
            )
        logger.info(f"历史记录加载完成: {loaded_messages} 条消息, {loaded_alerts} 条告警")

    def _pending_file_path(self) -> str:
        """QQ bot stack component."""
        return os.path.join(self.data_dir, "pending_large_files.json")

    def _load_pending_files(self) -> None:
        """QQ bot stack component."""
        path = self._pending_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._pending_files = {str(item.get("file_id")): item for item in data if item.get("file_id")}
            elif isinstance(data, dict):
                self._pending_files = data
            self._prune_pending_files()
            logger.info(f"已加载 {len(self._pending_files)} 条待确认大文件记录")
        except Exception as e:
            logger.error(f"加载待确认大文件记录失败: {e}")

    def _prune_pending_files(self) -> int:
        """QQ bot stack component."""



        finished = [
            (fid, rec) for fid, rec in self._pending_files.items()
            if rec.get("status") != "waiting_confirm"
        ]
        if len(finished) <= self._max_finished_pending:
            return 0

        def sort_key(item):
            fid, rec = item
            return rec.get("created_at", "") or ""

        finished.sort(key=sort_key)
        removed = 0
        for fid, _rec in finished[:len(finished) - self._max_finished_pending]:
            self._pending_files.pop(fid, None)
            removed += 1
        return removed

    def _save_pending_files(self) -> None:
        """QQ bot stack component."""
        try:
            self._prune_pending_files()
            with open(self._pending_file_path(), "w", encoding="utf-8") as f:
                json.dump(list(self._pending_files.values()), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存待确认大文件记录失败: {e}")

    def _remember_saved_id_locked(self, msg_id) -> None:
        """QQ bot stack component."""




        if msg_id in self._saved_message_ids:
            return
        self._saved_message_ids.add(msg_id)
        self._saved_ids_order.append(msg_id)
        while len(self._saved_ids_order) > self._max_saved_ids:
            self._saved_message_ids.discard(self._saved_ids_order.popleft())

    @staticmethod
    def _seg_field(seg: Dict[str, Any], key: str) -> Any:
        """QQ bot stack component."""
        value = seg.get(key)
        if value:
            return value
        data = seg.get("data")
        if isinstance(data, dict):
            return data.get(key)
        return None

    @classmethod
    def _message_richness(cls, message: Dict[str, Any]) -> tuple:
        """QQ bot stack component."""





        score = 0
        content = message.get("content") or {}
        segments = content.get("segments") or []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            for key in ("url", "local_path", "file", "name", "text", "id", "qq", "msg_preview"):
                if cls._seg_field(seg, key):
                    score += 1
        if content.get("image_urls"):
            score += 1
        if message.get("raw_message"):
            score += 1
        try:
            return (score, len(json.dumps(message, ensure_ascii=False, sort_keys=True)))
        except (TypeError, ValueError):
            return (score, 0)

    def _trim_index_locked(self, group_id: int) -> None:
        """QQ bot stack component."""




        messages = self._index.get(group_id)
        if not messages or len(messages) <= self._max_index_per_group:
            return
        drop_count = len(messages) - self._max_index_per_group
        dropped = messages[:drop_count]
        self._index[group_id] = messages[drop_count:]
        for msg in dropped:
            dt = msg.get("datetime", "")
            if len(dt) >= 10:
                self._trimmed_dates.add((group_id, dt[:10]))

    def save_message(self, message: Dict[str, Any], download_media: bool = True) -> None:
        """QQ bot stack component."""



        msg_id = message.get("message_id", 0)
        if msg_id:
            with self._saved_ids_lock:
                if msg_id in self._saved_message_ids:
                    return  
                self._remember_saved_id_locked(msg_id)

        if message.get("type") == "message":
            group_id = message.get("group_id", 0)
            self._save_to_file(group_id, message, download_media=download_media)
            self._add_to_index(group_id, message)
        elif message.get("type") == "notice":
            group_id = message.get("group_id", 0)
            self._save_to_file(group_id, message, download_media=download_media)
            self._add_to_index(group_id, message)

    def save_alert(self, alert: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        
        if not alert.get("alert_id"):
            alert["alert_id"] = uuid.uuid4().hex[:12]
        with self._alerts_lock:
            self._alerts.append(alert)
            
            if len(self._alerts) > self.max_alert_records:
                self._alerts = self._alerts[-self.max_alert_records:]

        
        
        
        alert_file = os.path.join(self.data_dir, "alerts.jsonl")
        with self._alerts_file_lock:
            try:
                with open(alert_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(alert, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"写入告警文件失败: {e}")

    def feedback_alert(self, alert_id: str, feedback: str) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {"success": False, "error": ""}
        if feedback not in ("confirmed", "false_positive"):
            result["error"] = "反馈类型无效，只能是 confirmed 或 false_positive"
            return result

        with self._alerts_lock:
            for alert in self._alerts:
                if alert.get("alert_id") == alert_id:
                    alert["user_feedback"] = feedback
                    alert["user_feedback_time"] = datetime.now().isoformat()
                    result["success"] = True
                    break

        if not result["success"]:
            result["error"] = f"未找到告警 ID: {alert_id}"
            return result

        
        self._rewrite_alerts_file()
        return result

    def _rewrite_alerts_file(self) -> None:
        """QQ bot stack component."""







        alert_file = os.path.join(self.data_dir, "alerts.jsonl")
        temp_file = alert_file + ".tmp"
        try:
            with self._alerts_lock:
                updates = {a.get("alert_id"): a for a in self._alerts if a.get("alert_id")}

            with self._alerts_file_lock:
                written = set()
                with open(temp_file, 'w', encoding='utf-8') as out:
                    if os.path.exists(alert_file):
                        with open(alert_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                stripped = line.strip()
                                if not stripped:
                                    continue
                                try:
                                    existing = json.loads(stripped)
                                except json.JSONDecodeError:
                                    
                                    out.write(stripped + "\n")
                                    continue
                                aid = existing.get("alert_id") if isinstance(existing, dict) else None
                                if aid and aid in updates:
                                    written.add(aid)
                                    out.write(json.dumps(updates[aid], ensure_ascii=False) + "\n")
                                else:
                                    out.write(stripped + "\n")
                    
                    for aid, alert in updates.items():
                        if aid not in written:
                            out.write(json.dumps(alert, ensure_ascii=False) + "\n")
                os.replace(temp_file, alert_file)
        except Exception as e:
            logger.error(f"重写告警文件失败: {e}")
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass

    def on_large_file_pending(self, callback) -> None:
        """QQ bot stack component."""
        self._large_file_callbacks.append(callback)

    def get_pending_files(self) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        with self._pending_lock:
            items = list(self._pending_files.values())
        return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)

    def confirm_pending_file(self, file_id: str) -> Dict[str, Any]:
        """QQ bot stack component."""
        with self._pending_lock:
            record = self._pending_files.get(file_id)
        if not record:
            return {"success": False, "error": "待确认文件不存在"}
        if record.get("status") == "saved":
            return {"success": True, "message": "文件已经保存", "record": record}
        if record.get("status") == "rejected":
            return {"success": False, "error": "文件已被拒绝保存"}

        local_path = self._download_attachment_record(record, force=True)
        with self._pending_lock:
            if local_path:
                record["status"] = "saved"
                record["local_path"] = local_path
            else:
                record["status"] = "download_failed"
            self._pending_files[file_id] = record
            self._save_pending_files()
        return {"success": bool(local_path), "record": record, "error": "" if local_path else "文件下载失败"}

    def reject_pending_file(self, file_id: str) -> Dict[str, Any]:
        """QQ bot stack component."""
        with self._pending_lock:
            record = self._pending_files.get(file_id)
            if not record:
                return {"success": False, "error": "待确认文件不存在"}
            record["status"] = "rejected"
            self._pending_files[file_id] = record
            self._save_pending_files()
        return {"success": True, "record": record}

    def _save_to_file(self, group_id: int, message: Dict[str, Any],
                      download_media: bool = True) -> None:
        """QQ bot stack component."""









        today = self._message_date(message)
        group_dir = os.path.join(self.data_dir, str(group_id))
        os.makedirs(group_dir, exist_ok=True)

        file_path = os.path.join(group_dir, f"{today}.jsonl")

        
        
        save_data = {k: v for k, v in message.items() if k != "raw"}
        content = save_data.get("content")
        
        if isinstance(content, dict) and content.get("segments"):
            content = dict(content)  
            save_data["content"] = content
            simplified_segments = []
            image_index = 0
            attachment_index = 0
            for seg in content["segments"]:
                seg_type = seg.get("type", "")
                seg_data = seg.get("data", {}) or {}
                seg_entry = {
                    "type": seg_type,
                    "summary": seg_data.get("summary", seg_type)
                }
                
                if seg_type == "text":
                    seg_entry["text"] = seg_data.get("text", "")
                
                elif seg_type == "image":
                    image_index += 1
                    img_url = seg_data.get("url", "")
                    seg_entry["url"] = img_url
                    
                    
                    if seg_data.get("file"):
                        seg_entry["file"] = seg_data["file"]
                    
                    if download_media and self.save_images and img_url:
                        images_dir = os.path.join(group_dir, "附件", "图片", today)
                        os.makedirs(images_dir, exist_ok=True)
                        self._last_image_error = ""
                        local_path = self._download_image(
                            img_url, images_dir, message, image_index
                        )
                        if local_path:
                            seg_entry["local_path"] = local_path
                        else:
                            
                            seg_entry["img_error"] = self._last_image_error or "下载失败"
                elif seg_type in ("file", "video", "voice"):
                    attachment_index += 1
                    seg_entry.update({
                        "url": seg_data.get("url", ""),
                        "file": seg_data.get("file", ""),
                        "name": seg_data.get("name", seg_data.get("file", seg_type)),
                        "size": self._parse_size(seg_data.get("size", 0))
                    })
                    if download_media and self.save_files:
                        result = self._save_attachment(seg_type, seg_data, message, attachment_index)
                        if result.get("local_path"):
                            seg_entry["local_path"] = result["local_path"]
                        if result.get("pending_file_id"):
                            seg_entry["pending_file_id"] = result["pending_file_id"]
                            seg_entry["pending_status"] = "waiting_confirm"
                
                elif seg_type == "face":
                    seg_entry["id"] = seg_data.get("id", "")
                
                elif seg_type == "reply":
                    seg_entry["msg_preview"] = (seg_data.get("msg_preview") or "")[:100]
                
                elif seg_type == "at":
                    seg_entry["qq"] = seg_data.get("qq", "")
                    seg_entry["name"] = seg_data.get("name", "")
                simplified_segments.append(seg_entry)
            content["segments"] = simplified_segments

        
        with self._file_lock:
            try:
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(save_data, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"写入消息文件失败 (群{group_id}): {e}")

    def _download_image(self, url: str, save_dir: str,
                        message: Dict[str, Any], image_index: int = 1) -> Optional[str]:
        """QQ bot stack component."""







        self._last_image_error = "" if url else "没有图片地址"
        if not url:
            return None

        for attempt in range(1, self.IMAGE_MAX_ATTEMPTS + 1):
            path, err, retryable = self._download_image_once(url, save_dir, message, image_index)
            if path:
                self._last_image_error = ""
                return path
            if attempt >= self.IMAGE_MAX_ATTEMPTS or not retryable:
                self._last_image_error = err
                logger.warning(f"图片未落盘（第 {attempt} 次尝试后放弃）: {err} | {url[:130]}")
                return None
            wait = self.IMAGE_RETRY_BACKOFF[min(attempt - 1, len(self.IMAGE_RETRY_BACKOFF) - 1)]
            logger.info(f"图片下载失败，{wait} 秒后重试（第 {attempt}/{self.IMAGE_MAX_ATTEMPTS} 次）: {err}")
            time.sleep(wait)
        return None

    def _download_image_once(self, url: str, save_dir: str, message: Dict[str, Any],
                             image_index: int = 1) -> tuple:
        """QQ bot stack component."""




        temp_path = None
        try:
            group_dir = os.path.dirname(os.path.dirname(os.path.dirname(save_dir)))

            max_bytes = max(1, self.max_image_size_mb) * 1024 * 1024
            resp = requests.get(url, timeout=self.IMAGE_TIMEOUT, stream=True)
            if resp.status_code != 200:
                
                retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
                return None, f"HTTP {resp.status_code}", retryable

            
            
            ext = self._guess_image_ext(resp.headers.get("Content-Type", ""), url)

            content_length = self._parse_size(resp.headers.get("Content-Length", 0))
            if content_length and content_length > max_bytes:
                logger.info(f"图片超过大小限制，跳过保存: {content_length} bytes")
                return None, f"超过大小限制（{content_length} 字节）", False

            downloaded = 0
            hasher = hashlib.sha256()
            temp_name = f".tmp_{uuid.uuid4().hex}.download"
            temp_path = os.path.join(save_dir, temp_name)
            with open(temp_path, 'wb') as f:
                for chunk in resp.iter_content(8192):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        f.close()
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                        temp_path = None
                        logger.info(f"图片下载超过大小限制，已删除临时文件: {url}")
                        return None, f"超过大小限制（已下 {downloaded} 字节）", False
                    hasher.update(chunk)
                    f.write(chunk)

            if downloaded <= 0:
                return None, "下载到的内容是空的", True

            content_hash = hasher.hexdigest()
            existing_path = self._find_existing_image(group_dir, content_hash, downloaded)
            if existing_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                temp_path = None
                return (f"/api/images/{os.path.relpath(existing_path, self.data_dir).replace(os.sep, '/')}",
                        "", False)

            filename = self._build_image_filename(message, image_index, content_hash, downloaded, ext)
            local_path = os.path.join(save_dir, filename)
            os.replace(temp_path, local_path)
            temp_path = None
            rel = os.path.relpath(local_path, self.data_dir).replace(os.sep, '/')
            logger.debug(f"图片已保存: {local_path}")
            return f"/api/images/{rel}", "", False
        except requests.exceptions.RequestException as e:
            
            return None, f"{type(e).__name__}: {str(e)[:120]}", True
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:120]}", False
        finally:
            
            if temp_path:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def _guess_image_ext(content_type: str, url: str) -> str:
        """QQ bot stack component."""
        ct = (content_type or "").lower()
        for marker, ext in (("image/jpeg", ".jpg"), ("image/jpg", ".jpg"), ("image/png", ".png"),
                            ("image/gif", ".gif"), ("image/webp", ".webp"),
                            ("image/bmp", ".bmp"), ("image/avif", ".avif")):
            if marker in ct:
                return ext
        low = (url or "").lower()
        for marker, ext in ((".gif", ".gif"), ("gif", ".gif"), (".png", ".png"), ("png", ".png"),
                            (".webp", ".webp"), ("webp", ".webp"), (".bmp", ".bmp")):
            if marker in low:
                return ext
        return ".jpg"

    def _save_attachment(self, seg_type: str, seg_data: Dict[str, Any],
                         message: Dict[str, Any], index: int) -> Dict[str, Any]:
        """QQ bot stack component."""
        url = seg_data.get("url", "")
        name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
        known_size = self._parse_size(seg_data.get("size", 0))
        remote_size = known_size or self._get_remote_size(url)
        if remote_size and remote_size > self._large_file_threshold_bytes:
            record = self._add_pending_large_file(seg_type, seg_data, message, index, remote_size)
            return {"pending_file_id": record["file_id"], "record": record}

        pending_out: Dict[str, Any] = {}
        local_path = self._download_attachment(
            seg_type, seg_data, message, index, force=False, pending_out=pending_out
        )
        if local_path:
            return {"local_path": local_path}
        record = pending_out.get("record")
        if record:
            
            return {"pending_file_id": record["file_id"], "record": record}
        return {}

    def _download_attachment_record(self, record: Dict[str, Any], force: bool = False) -> Optional[str]:
        """QQ bot stack component."""
        return self._download_attachment(
            record.get("segment_type", "file"),
            {
                "url": record.get("url", ""),
                "name": record.get("name", ""),
                "file": record.get("name", ""),
                "size": record.get("size", 0)
            },
            record.get("message", {}),
            record.get("index", 1),
            force=force
        )

    def _is_complete_attachment(self, path: str, seg_data: Dict[str, Any]) -> bool:
        """QQ bot stack component."""




        try:
            actual = os.path.getsize(path)
        except OSError:
            return False
        if actual <= 0:
            return False
        expected = self._parse_size(seg_data.get("size", 0))
        if expected and actual < expected:
            return False
        return True

    def _download_attachment(self, seg_type: str, seg_data: Dict[str, Any],
                             message: Dict[str, Any], index: int,
                             force: bool = False,
                             pending_out: Dict[str, Any] = None) -> Optional[str]:
        """QQ bot stack component."""




        url = seg_data.get("url", "")
        if not url:
            return None
        try:
            date_str = self._message_date(message)
            group_id = message.get("group_id", 0)
            group_dir = os.path.join(self.data_dir, str(group_id))
            category = self._attachment_category(seg_type)
            save_dir = os.path.join(group_dir, "附件", category, date_str)
            os.makedirs(save_dir, exist_ok=True)

            original_name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
            ext = self._guess_extension(original_name, url, seg_type)
            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            existing_path = self._find_existing_attachment(group_dir, category, url_hash)
            if existing_path and self._is_complete_attachment(existing_path, seg_data):
                return f"/api/files/{os.path.relpath(existing_path, self.data_dir).replace(os.sep, '/')}"

            filename = self._build_attachment_filename(message, index, original_name, url_hash, ext)
            local_path = os.path.join(save_dir, filename)
            if os.path.exists(local_path) and self._is_complete_attachment(local_path, seg_data):
                return f"/api/files/{os.path.relpath(local_path, self.data_dir).replace(os.sep, '/')}"

            
            
            if existing_path or os.path.exists(local_path):
                logger.info(f"附件疑似残缺，尝试重新下载: {os.path.basename(existing_path or local_path)}")

            max_bytes = None if force else self._large_file_threshold_bytes
            resp = requests.get(url, timeout=15, stream=True)
            if resp.status_code != 200:
                logger.warning(f"附件下载失败: HTTP {resp.status_code}")
                return None
            content_length = self._parse_size(resp.headers.get("Content-Length", 0))
            if max_bytes and content_length and content_length > max_bytes:
                record = self._add_pending_large_file(seg_type, seg_data, message, index, content_length)
                if pending_out is not None:
                    pending_out["record"] = record
                return None

            
            part_path = local_path + ".part"
            downloaded = 0
            over_limit = False
            try:
                with open(part_path, "wb") as f:
                    for chunk in resp.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if max_bytes and downloaded > max_bytes:
                            over_limit = True
                            break
                        f.write(chunk)
            except Exception:
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except OSError:
                    pass
                raise

            if over_limit:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                record = self._add_pending_large_file(seg_type, seg_data, message, index, downloaded)
                if pending_out is not None:
                    pending_out["record"] = record
                return None

            os.replace(part_path, local_path)
            rel = os.path.relpath(local_path, self.data_dir).replace(os.sep, "/")
            return f"/api/files/{rel}"
        except Exception as e:
            logger.debug(f"附件下载异常: {e}")
            return None

    def _add_pending_large_file(self, seg_type: str, seg_data: Dict[str, Any],
                                message: Dict[str, Any], index: int,
                                size: int) -> Dict[str, Any]:
        """QQ bot stack component."""
        url = seg_data.get("url", "")
        name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
        stable_key = f"{message.get('message_id', 0)}:{index}:{url or name}"
        file_id = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:10]
        with self._pending_lock:
            if file_id in self._pending_files:
                return self._pending_files[file_id]
            record = {
                "file_id": file_id,
                "status": "waiting_confirm",
                "segment_type": seg_type,
                "name": name,
                "url": url,
                "size": size,
                "size_text": self._format_size(size),
                "index": index,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": {k: v for k, v in message.items() if k != "raw"}
            }
            self._pending_files[file_id] = record
            self._save_pending_files()
        for callback in self._large_file_callbacks:
            try:
                callback(record)
            except Exception as e:
                logger.error(f"大文件待确认回调失败: {e}")
        return record

    def _message_date(self, message: Dict[str, Any]) -> str:
        """QQ bot stack component."""
        dt = message.get("datetime", "")
        if len(dt) >= 10:
            return dt[:10]
        return datetime.now().strftime("%Y-%m-%d")

    def _safe_filename_part(self, value: Any, max_len: int = 24) -> str:
        """QQ bot stack component."""
        text = str(value or "").strip()
        text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
        text = re.sub(r"\s+", "_", text)
        text = text.strip("._ ")
        return (text[:max_len] or "未知")

    def _build_image_filename(self, message: Dict[str, Any], image_index: int,
                              content_hash: str, size_bytes: int, ext: str) -> str:
        """QQ bot stack component."""
        dt = message.get("datetime", "")
        date_part = self._message_date(message).replace("-", "")
        time_part = "000000"
        if len(dt) >= 19:
            time_part = dt[11:19].replace(":", "")
        user_id = self._safe_filename_part(message.get("user_id", 0), 20)
        short_hash = content_hash[:12]
        return f"{date_part}_{time_part}_QQ{user_id}_图{image_index}_{short_hash}_{int(size_bytes)}B{ext}"

    def _build_attachment_filename(self, message: Dict[str, Any], index: int,
                                   original_name: str, url_hash: str, ext: str) -> str:
        """QQ bot stack component."""
        dt = message.get("datetime", "")
        date_part = self._message_date(message).replace("-", "")
        time_part = dt[11:19].replace(":", "") if len(dt) >= 19 else "000000"
        user_id = self._safe_filename_part(message.get("user_id", 0), 20)
        nickname = self._safe_filename_part(message.get("card") or message.get("nickname", "未知"), 20)
        message_id = self._safe_filename_part(message.get("message_id", 0), 24)
        base = self._safe_filename_part(os.path.splitext(original_name or "文件")[0], 36)
        return f"{date_part}_{time_part}_QQ{user_id}_{nickname}_消息{message_id}_文件{index}_{base}_{url_hash}{ext}"

    def _find_existing_image(self, group_dir: str, content_hash: str, size_bytes: int) -> Optional[str]:
        """QQ bot stack component."""
        images_root = os.path.join(group_dir, "附件", "图片")
        if not os.path.isdir(images_root):
            return None
        marker = f"_{content_hash[:12]}_{int(size_bytes)}B."
        try:
            for dirpath, _, filenames in os.walk(images_root):
                for filename in filenames:
                    if marker in filename:
                        return os.path.join(dirpath, filename)
        except OSError:
            return None
        return None

    def _find_existing_attachment(self, group_dir: str, category: str, url_hash: str) -> Optional[str]:
        """QQ bot stack component."""
        root = os.path.join(group_dir, "附件", category)
        if not os.path.isdir(root):
            return None
        marker = f"_{url_hash}."
        try:
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if marker in filename:
                        return os.path.join(dirpath, filename)
        except OSError:
            return None
        return None

    def _attachment_category(self, seg_type: str) -> str:
        """QQ bot stack component."""
        return {
            "file": "文件",
            "video": "视频",
            "voice": "语音"
        }.get(seg_type, "文件")

    def _guess_extension(self, name: str, url: str, seg_type: str) -> str:
        """QQ bot stack component."""
        ext = os.path.splitext(name or "")[1]
        if ext and len(ext) <= 12:
            return ext
        url_ext = os.path.splitext(url.split("?")[0])[1]
        if url_ext and len(url_ext) <= 12:
            return url_ext
        return {"video": ".mp4", "voice": ".amr", "file": ".bin"}.get(seg_type, ".bin")

    def _parse_size(self, value: Any) -> int:
        """QQ bot stack component."""
        try:
            if value is None or value == "":
                return 0
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    def _format_size(self, size: int) -> str:
        """QQ bot stack component."""
        size = self._parse_size(size)
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024

    def _get_remote_size(self, url: str) -> int:
        """QQ bot stack component."""
        if not url:
            return 0
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                return self._parse_size(resp.headers.get("Content-Length", 0))
        except Exception:
            return 0
        return 0

    def get_recent_messages(self, group_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        if not limit or limit <= 0:
            return []
        with self._index_lock:
            messages = self._index.get(group_id, [])
            return list(messages[-limit:])

    def _add_to_index(self, group_id: int, message: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        with self._index_lock:
            self._index[group_id].append(message)
            self._trim_index_locked(group_id)

    @staticmethod
    def _enrich_from_memory(file_msg: Dict[str, Any], mem_msg: Dict[str, Any]) -> None:
        """QQ bot stack component."""






        if not mem_msg:
            return
        f_segs = (file_msg.get("content") or {}).get("segments") or []
        m_segs = (mem_msg.get("content") or {}).get("segments") or []
        if len(f_segs) != len(m_segs):
            return
        for f, m in zip(f_segs, m_segs):
            if f.get("type") != m.get("type"):
                return
            for field in ("local_path", "img_error"):
                if not f.get(field) and m.get(field):
                    f[field] = m[field]

    def iter_all_messages(self, group_id: int = None, enrich_from_index: bool = True):
        """QQ bot stack component."""












        if group_id:
            groups = [int(group_id)]
        else:
            groups = []
            if os.path.isdir(self.data_dir):
                for name in os.listdir(self.data_dir):
                    if name.isdigit() and os.path.isdir(os.path.join(self.data_dir, name)):
                        groups.append(int(name))

        mem: Dict[Any, Dict[str, Any]] = {}
        if enrich_from_index:
            with self._index_lock:
                for gid, msgs in self._index.items():
                    if group_id and gid != int(group_id):
                        continue
                    for m in msgs:
                        if m.get("message_id"):
                            mem[(gid, m["message_id"])] = m

        for gid in sorted(groups):
            gdir = os.path.join(self.data_dir, str(gid))
            if not os.path.isdir(gdir):
                continue
            try:
                names = sorted(n for n in os.listdir(gdir)
                               if n.endswith((".jsonl", ".jsonl.gz")))
            except OSError as e:
                logger.error(f"列出群 {gid} 的消息文件失败: {e}")
                continue
            for name in names:
                path = os.path.join(gdir, name)
                opener = gzip.open if name.endswith(".gz") else open
                try:
                    with opener(path, "rt", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if msg.get("type") == "message":
                                if mem:
                                    self._enrich_from_memory(
                                        msg, mem.get((gid, msg.get("message_id"))))
                                yield gid, msg
                except Exception as e:
                    logger.error(f"读消息文件失败 {path}: {e}")

    

    def query_messages(self, group_id: int = None,
                       user_id: int = None,
                       keyword: str = None,
                       start_time: str = None,
                       end_time: str = None,
                       page: int = 1,
                       page_size: int = 50,
                       include_alerts: bool = False,
                       only_violations: bool = False) -> Dict[str, Any]:
        """QQ bot stack component."""






















        results = []

        if group_id:
            groups_to_search = [group_id]
        else:
            groups_to_search = list(self._index.keys())
            
            if os.path.exists(self.data_dir):
                for name in os.listdir(self.data_dir):
                    group_path = os.path.join(self.data_dir, name)
                    if os.path.isdir(group_path):
                        try:
                            gid = int(name)
                            if gid not in groups_to_search:
                                groups_to_search.append(gid)
                        except ValueError:
                            continue

        for gid in groups_to_search:
            
            mem_messages = self._index.get(gid, [])
            
            
            all_dates = self.get_available_dates(gid)
            
            
            
            has_filter = bool(keyword or user_id or start_time or end_time)
            
            if has_filter:
                
                
                search_dates = all_dates[:]
                if start_time:
                    start_date = start_time[:10]
                    search_dates = [d for d in search_dates if d >= start_date]
                if end_time:
                    end_date = end_time[:10]
                    search_dates = [d for d in search_dates if d <= end_date]
                
                
                file_messages = []
                for date_str in search_dates:
                    msgs = self.query_from_file(gid, date_str, user_id=user_id, keyword=keyword)
                    
                    for msg in msgs:
                        msg_time = msg.get("datetime", "")
                        if start_time and msg_time < start_time:
                            continue
                        if end_time and msg_time > end_time:
                            continue
                        file_messages.append(msg)
                
                
                mem_filtered = []
                for msg in mem_messages:
                    if user_id and msg.get("user_id") != user_id:
                        continue
                    if keyword and not self._msg_matches_keyword(msg, keyword):
                        continue
                    if start_time:
                        msg_time = msg.get("datetime", "")
                        if msg_time < start_time:
                            continue
                    if end_time:
                        msg_time = msg.get("datetime", "")
                        if msg_time > end_time:
                            continue
                    mem_filtered.append(msg)
                
                
                seen_ids = set()
                combined = []
                for msg in file_messages + mem_filtered:
                    mid = msg.get("message_id")
                    if mid and mid in seen_ids:
                        continue
                    if mid:
                        seen_ids.add(mid)
                    combined.append(msg)
                
                results.extend(combined)
            else:
                
                mem_dates = set()
                for msg in mem_messages:
                    dt = msg.get("datetime", "")
                    if len(dt) >= 10:
                        mem_dates.add(dt[:10])

                
                
                file_dates = [
                    d for d in all_dates
                    if d not in mem_dates or (gid, d) in self._trimmed_dates
                ]

                file_messages = []
                for date_str in file_dates:
                    msgs = self.query_from_file(gid, date_str)
                    file_messages.extend(msgs)

                
                seen_ids = set()
                combined = []
                for msg in file_messages + mem_messages:
                    mid = msg.get("message_id")
                    if mid and mid in seen_ids:
                        continue
                    if mid:
                        seen_ids.add(mid)
                    combined.append(msg)
                results.extend(combined)

        
        if only_violations:
            with self._alerts_lock:
                violation_ids = {
                    a.get("message_id") for a in self._alerts if a.get("message_id")
                }
            results = [m for m in results if m.get("message_id") in violation_ids]

        
        results.sort(key=lambda x: x.get("time", 0), reverse=True)

        total = len(results)
        
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 50
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 1
        if page_size <= 0:
            page_size = 50
        if page < 1:
            page = 1
        start = (page - 1) * page_size
        end_idx = start + page_size
        paged = results[start:end_idx]

        response = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "messages": paged
        }

        if include_alerts:
            with self._alerts_lock:
                response["alerts"] = self._sort_alerts_desc(self._alerts)[0:50]
            self._attach_alerts_to_messages(response["messages"])

        return response

    def _attach_alerts_to_messages(self, messages: List[Dict[str, Any]]) -> None:
        """QQ bot stack component."""
        if not messages:
            return

        with self._alerts_lock:
            alerts = self._alerts.copy()

        by_msg_id = {}
        by_fallback = {}
        for alert in alerts:
            msg_id = alert.get("message_id")
            if msg_id:
                by_msg_id.setdefault(msg_id, []).append(alert)
            fallback_key = (
                alert.get("group_id"),
                alert.get("user_id"),
                alert.get("datetime")
            )
            by_fallback.setdefault(fallback_key, []).append(alert)

        for idx, msg in enumerate(messages):
            msg_alerts = []
            msg_id = msg.get("message_id")
            if msg_id and msg_id in by_msg_id:
                msg_alerts.extend(by_msg_id[msg_id])

            fallback_key = (
                msg.get("group_id"),
                msg.get("user_id"),
                msg.get("datetime")
            )
            for alert in by_fallback.get(fallback_key, []):
                if alert not in msg_alerts:
                    msg_alerts.append(alert)

            if msg_alerts:
                
                
                enriched = dict(msg)
                enriched["alerts"] = msg_alerts
                enriched["has_violation"] = True
                latest = self._sort_alerts_desc(msg_alerts)[0]
                enriched["violation_summary"] = {
                    "severity": latest.get("severity", "medium"),
                    "category": latest.get("category", "other"),
                    "category_label": latest.get("category_label", ""),
                    "violation_type": latest.get("violation_type", ""),
                    "secondary_status": latest.get("secondary_status", "not_reviewed"),
                    "secondary_status_label": latest.get("secondary_status_label", "未二次复核"),
                    "should_notify": latest.get("should_notify", True),
                    "notified": latest.get("notified", False)
                }
                messages[idx] = enriched

    def _msg_matches_keyword(self, msg: Dict, keyword: str) -> bool:
        """QQ bot stack component."""
        if not keyword:
            return True
        kw = keyword.lower()
        
        text = msg.get("content", {}).get("text", "")
        if kw in text.lower():
            return True
        
        nickname = msg.get("nickname", "") or ""
        card = msg.get("card", "") or ""
        if kw in nickname.lower() or kw in card.lower():
            return True
        
        user_id = str(msg.get("user_id", "") or "")
        if kw in user_id:
            return True
        return False

    def query_from_file(self, group_id: int, date: str,
                        user_id: int = None,
                        keyword: str = None) -> List[Dict]:
        """QQ bot stack component."""








        
        
        group_id = str(group_id or "").strip()
        date = str(date or "").strip()
        if not re.fullmatch(r"[0-9]{1,20}", group_id) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
            logger.warning(f"query_from_file 收到非法的 group_id/date，已拒绝：{group_id!r} / {date!r}")
            return []
        file_path = os.path.join(self.data_dir, group_id, f"{date}.jsonl")
        if not os.path.exists(file_path):
            
            gz_path = file_path + ".gz"
            if os.path.exists(gz_path):
                return self._read_gzip_file(gz_path, user_id, keyword)
            return []

        results = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if user_id and msg.get("user_id") != user_id:
                            continue
                        if keyword and not self._msg_matches_keyword(msg, keyword):
                            continue
                        results.append(msg)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"读取消息文件失败: {e}")

        return results

    def _read_gzip_file(self, gz_path: str,
                        user_id: int = None,
                        keyword: str = None) -> List[Dict]:
        """QQ bot stack component."""
        results = []
        try:
            with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if user_id and msg.get("user_id") != user_id:
                            continue
                        if keyword and not self._msg_matches_keyword(msg, keyword):
                            continue
                        results.append(msg)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"读取压缩文件失败: {e}")
        return results

    def get_alerts(self, limit: int = 50,
                   group_id: int = None,
                   severity: str = None,
                   category: str = None,
                   secondary_status: str = None,
                   user_id: int = None) -> List[Dict]:
        """QQ bot stack component."""
        with self._alerts_lock:
            alerts = self._alerts.copy()

        if group_id:
            alerts = [a for a in alerts if a.get("group_id") == group_id]
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        if category:
            alerts = [a for a in alerts if a.get("category") == category]
        if secondary_status:
            alerts = [a for a in alerts if a.get("secondary_status") == secondary_status]
        if user_id:
            alerts = [
                a for a in alerts
                if (a.get("user_id") or a.get("message", {}).get("user_id")) == user_id
            ]

        return self._sort_alerts_desc(alerts)[:limit]

    def get_alerted_message_records(self) -> List[tuple]:
        """QQ bot stack component."""









        records: List[tuple] = []
        with self._alerts_lock:
            alerts = self._alerts.copy()
        for alert in alerts:
            mid = alert.get("message_id")
            if not mid:
                continue

            notified = alert.get("notified")
            if notified is None:
                
                notified = alert.get("should_notify")
            if not notified:
                continue

            gid = alert.get("group_id")
            if gid is None:
                gid = (alert.get("message") or {}).get("group_id")
            records.append((
                gid,
                mid,
                alert.get("severity"),
                alert.get("secondary_status", "not_reviewed"),
            ))
        return records

    def get_alerted_message_ids(self) -> List[Any]:
        """QQ bot stack component."""
        return [(gid, mid) for gid, mid, _sev, _st in self.get_alerted_message_records()]

    def get_alert_users(self) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        users: Dict[int, Dict[str, Any]] = {}
        with self._alerts_lock:
            alerts = self._alerts.copy()
        for alert in alerts:
            msg = alert.get("message", {})
            uid = alert.get("user_id") or msg.get("user_id")
            if not uid:
                continue
            item = users.setdefault(uid, {
                "user_id": uid,
                "nickname": msg.get("card") or msg.get("nickname") or alert.get("nickname", "未知"),
                "count": 0,
                "latest_time": ""
            })
            item["count"] += 1
            latest = alert.get("review_time") or alert.get("datetime") or msg.get("datetime", "")
            if latest > item["latest_time"]:
                item["latest_time"] = latest
                item["nickname"] = msg.get("card") or msg.get("nickname") or item["nickname"]
        return sorted(users.values(), key=lambda x: (-x["count"], x["nickname"]))

    def _sort_alerts_desc(self, alerts: List[Dict]) -> List[Dict]:
        """QQ bot stack component."""
        def sort_key(alert: Dict[str, Any]) -> Any:
            return (
                alert.get("review_time")
                or alert.get("time")
                or alert.get("datetime")
                or alert.get("message", {}).get("datetime")
                or ""
            )
        return sorted(alerts, key=sort_key, reverse=True)

    def _cached_storage_statistics(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        def refresh():
            try:
                sizes = self._measure_storage()
                with self._storage_stats_lock:
                    self._storage_stats_sizes = sizes
            except Exception as exc:
                logger.warning(f"刷新存储占用失败: {exc}")
            finally:
                with self._storage_stats_lock:
                    self._storage_stats_updated = time.monotonic()
                    self._storage_stats_refreshing = False

        with self._storage_stats_lock:
            if (not self._storage_stats_refreshing
                    and (not self._storage_stats_updated
                         or time.monotonic() - self._storage_stats_updated >= 60)):
                self._storage_stats_refreshing = True
                try:
                    threading.Thread(target=refresh, daemon=True,
                                     name="Storage-Stats").start()
                except Exception:
                    self._storage_stats_refreshing = False
                    raise
            sizes = self._storage_stats_sizes
            return {
                "storage_used_mb": (round(sum(sizes.values()) / (1024 * 1024), 2)
                                    if sizes is not None else None),
                "storage_scanning": self._storage_stats_refreshing,
            }

    def get_statistics(self, fast: bool = False) -> Dict[str, Any]:
        """QQ bot stack component."""
        with self._alerts_lock:
            alert_count = len(self._alerts)
        with self._index_lock:
            index_snapshot = {gid: list(msgs) for gid, msgs in self._index.items()}

        stats = {
            "total_groups": 0,
            "total_messages": 0,
            "total_alerts": alert_count,
            "storage_used_mb": 0,
            "groups": {},
            "recent_activity": {}
        }

        
        for gid, messages in index_snapshot.items():
            latest = ""
            for msg in messages:
                dt = msg.get("datetime", "")
                if dt > latest:
                    latest = dt
            stats["groups"][str(gid)] = {
                "message_count": len(messages),
                "latest_message": latest
            }
            stats["total_messages"] += len(messages)

        stats["total_groups"] = len(index_snapshot)

        
        
        if fast:
            stats.update(self._cached_storage_statistics())
        else:
            sizes = self._measure_storage()
            stats["storage_used_mb"] = round(
                (sizes["message"] + sizes["attachment"] + sizes["alert"]) / (1024 * 1024), 2
            )

        return stats

    def get_available_dates(self, group_id: int) -> List[str]:
        """QQ bot stack component."""
        group_dir = os.path.join(self.data_dir, str(group_id))
        if not os.path.exists(group_dir):
            return []

        dates = []
        for filename in os.listdir(group_dir):
            if filename.endswith(".jsonl"):
                dates.append(filename.replace(".jsonl", ""))
            elif filename.endswith(".jsonl.gz"):
                dates.append(filename.replace(".jsonl.gz", ""))

        dates.sort(reverse=True)
        return dates

    def get_monitored_groups(self) -> List[Dict]:
        """QQ bot stack component."""
        groups = []
        for gid, messages in self._index.items():
            groups.append({
                "group_id": gid,
                "message_count": len(messages),
                "latest_message": messages[-1].get("datetime", "") if messages else "",
                "available_dates": self.get_available_dates(gid)
            })
        return groups

    

    
    
    
    

    @staticmethod
    def _parse_date_dir(name: str) -> Optional[datetime]:
        """QQ bot stack component."""
        try:
            return datetime.strptime(str(name), "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def _iter_attachment_dirs(self, group_id: int = None, categories: List[str] = None):
        """QQ bot stack component."""
        if not os.path.isdir(self.data_dir):
            return
        for name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, name)
            if not os.path.isdir(group_path):
                continue
            try:
                gid = int(name)
            except ValueError:
                continue
            if group_id and gid != group_id:
                continue

            attach_root = os.path.join(group_path, "附件")
            if os.path.isdir(attach_root):
                for cat in os.listdir(attach_root):
                    cat_path = os.path.join(attach_root, cat)
                    if not os.path.isdir(cat_path):
                        continue
                    if categories and cat not in categories:
                        continue
                    for date_name in os.listdir(cat_path):
                        date_path = os.path.join(cat_path, date_name)
                        if os.path.isdir(date_path):
                            yield gid, cat, date_name, date_path

            
            legacy_root = os.path.join(group_path, "images")
            if os.path.isdir(legacy_root) and (not categories or "图片" in categories):
                for date_name in os.listdir(legacy_root):
                    date_path = os.path.join(legacy_root, date_name)
                    if os.path.isdir(date_path):
                        yield gid, "图片(旧)", date_name, date_path

    @staticmethod
    def _dir_size_and_count(path: str):
        """QQ bot stack component."""
        total = 0
        count = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, filename))
                    count += 1
                except OSError:
                    continue
        return total, count

    def get_attachment_stats(self) -> Dict[str, Any]:
        """QQ bot stack component."""




        groups: Dict[int, Dict[str, Any]] = {}
        undated: List[Dict[str, Any]] = []
        total_bytes = 0
        total_files = 0

        for gid, cat, date_name, date_path in self._iter_attachment_dirs():
            size, count = self._dir_size_and_count(date_path)
            if count == 0:
                continue
            total_bytes += size
            total_files += count

            if self._parse_date_dir(date_name) is None:
                undated.append({
                    "group_id": gid, "category": cat, "name": date_name,
                    "files": count, "mb": round(size / (1024 * 1024), 2)
                })
                continue

            entry = groups.setdefault(gid, {
                "group_id": gid, "bytes": 0, "files": 0,
                "oldest_date": "", "newest_date": "", "categories": {}
            })
            entry["bytes"] += size
            entry["files"] += count
            cat_entry = entry["categories"].setdefault(cat, {"bytes": 0, "files": 0})
            cat_entry["bytes"] += size
            cat_entry["files"] += count
            if not entry["oldest_date"] or date_name < entry["oldest_date"]:
                entry["oldest_date"] = date_name
            if not entry["newest_date"] or date_name > entry["newest_date"]:
                entry["newest_date"] = date_name

        result = []
        for entry in groups.values():
            entry["mb"] = round(entry["bytes"] / (1024 * 1024), 2)
            for cat_entry in entry["categories"].values():
                cat_entry["mb"] = round(cat_entry["bytes"] / (1024 * 1024), 2)
            result.append(entry)
        result.sort(key=lambda x: -x["bytes"])

        return {
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "total_files": total_files,
            "max_storage_mb": self.max_storage_mb,
            "groups": result,
            "undated": sorted(undated, key=lambda x: -x["mb"]),
        }

    def cleanup_attachments(self, older_than_days: int = None,
                            group_id: int = None,
                            categories: List[str] = None,
                            dry_run: bool = True) -> Dict[str, Any]:
        """QQ bot stack component."""










        
        
        if not dry_run and not self.auto_cleanup_enabled:
            logger.info("自动清理已关闭（storage.auto_cleanup_enabled=false），拒绝执行附件删除")
            return {
                "dry_run": False,
                "skipped": True,
                "reason": "auto_cleanup_disabled",
                "message": "自动清理已关闭，未删除任何附件。如需清理请先把 "
                           "config.json 里的 storage.auto_cleanup_enabled 改为 true。",
                "older_than_days": older_than_days,
                "dirs": 0, "files": 0, "mb": 0.0, "by_group": {}, "errors": [],
            }

        cutoff = None
        if older_than_days is not None:
            try:
                older_than_days = max(0, int(older_than_days))
            except (TypeError, ValueError):
                older_than_days = 0
            
            
            cutoff = (datetime.now() - timedelta(days=older_than_days)).date()

        targets = []
        for gid, cat, date_name, date_path in self._iter_attachment_dirs(group_id, categories):
            date_value = self._parse_date_dir(date_name)
            if date_value is None:
                continue
            if cutoff is not None and date_value.date() >= cutoff:
                continue
            size, count = self._dir_size_and_count(date_path)
            if count == 0:
                continue
            targets.append((date_path, gid, cat, size, count))

        by_group: Dict[str, Dict[str, Any]] = {}
        total_bytes = 0
        total_files = 0
        errors = []
        deleted_dirs = 0

        for date_path, gid, cat, size, count in targets:
            total_bytes += size
            total_files += count
            bucket = by_group.setdefault(str(gid), {"dirs": 0, "files": 0, "bytes": 0})
            bucket["dirs"] += 1
            bucket["files"] += count
            bucket["bytes"] += size

        if not dry_run:
            for date_path, gid, cat, size, count in targets:
                try:
                    shutil.rmtree(date_path, ignore_errors=False)
                    deleted_dirs += 1
                except Exception as e:
                    errors.append(f"{date_path}: {e}")
                    logger.error(f"清理附件目录失败: {date_path}, {e}")
            if deleted_dirs:
                logger.warning(
                    f"已清理附件: {deleted_dirs} 个日期目录, {total_files} 个文件, "
                    f"{total_bytes / (1024 * 1024):.1f}MB"
                )

        for bucket in by_group.values():
            bucket["mb"] = round(bucket["bytes"] / (1024 * 1024), 2)

        return {
            "dry_run": dry_run,
            "older_than_days": older_than_days,
            "dirs": len(targets) if dry_run else deleted_dirs,
            "files": total_files,
            "mb": round(total_bytes / (1024 * 1024), 2),
            "by_group": by_group,
            "errors": errors,
        }

    def _measure_storage(self) -> Dict[str, int]:
        """QQ bot stack component."""




        base = os.path.abspath(self.data_dir)
        sizes = {"message": 0, "attachment": 0, "alert": 0}
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            rel = os.path.relpath(dirpath, base)
            parts = [] if rel == "." else rel.split(os.sep)
            if any(p.startswith(".") for p in parts):
                continue
            is_attachment = "附件" in parts or "images" in parts
            for filename in filenames:
                if filename.startswith("."):
                    continue
                file_path = os.path.join(dirpath, filename)
                try:
                    size = os.path.getsize(file_path)
                except OSError:
                    continue
                if not parts and filename.startswith("alerts.jsonl"):
                    sizes["alert"] += size
                elif is_attachment:
                    sizes["attachment"] += size
                else:
                    sizes["message"] += size
        return sizes

    def check_storage(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        sizes = self._measure_storage()
        used_mb = (sizes["message"] + sizes["attachment"] + sizes["alert"]) / (1024 * 1024)
        quota = float(self.max_storage_mb or 0)
        if quota > 0:
            usage_percent = round(used_mb / quota * 100, 2)
            needs_cleanup = used_mb > quota * 0.8
        else:
            usage_percent = 0.0
            needs_cleanup = False
        return {
            "used_mb": round(used_mb, 2),
            "max_mb": self.max_storage_mb,
            "usage_percent": usage_percent,
            "needs_cleanup": needs_cleanup,
            "message_mb": round(sizes["message"] / (1024 * 1024), 2),
            "attachment_mb": round(sizes["attachment"] / (1024 * 1024), 2),
            "alert_mb": round(sizes["alert"] / (1024 * 1024), 2),
        }

    def cleanup_old_files(self, force: bool = False) -> Dict[str, Any]:
        """QQ bot stack component."""





        if not self.auto_cleanup_enabled and not force:
            logger.info(
                "自动清理已关闭（storage.auto_cleanup_enabled=false），未删除或压缩任何记录。"
                "如需清理请把该配置改为 true。"
            )
            return {
                "skipped": True,
                "reason": "auto_cleanup_disabled",
                "message": "自动清理已关闭，未做任何删除或压缩",
                "compressed": 0,
                "deleted": 0,
                "alerts_compacted": 0,
                "quota_deleted": 0,
                "freed_mb": 0,
            }

        cleanup_result = {
            "skipped": False,
            "compressed": 0,
            "deleted": 0,
            "alerts_compacted": 0,
            "quota_deleted": 0,
            "freed_mb": 0
        }

        threshold_date = datetime.now() - timedelta(days=self.archive_days)
        delete_date = datetime.now() - timedelta(days=self.archive_days * 2)

        for group_name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, group_name)
            if not os.path.isdir(group_path):
                continue

            for filename in os.listdir(group_path):
                if not filename.endswith(".jsonl"):
                    continue

                file_path = os.path.join(group_path, filename)
                
                date_str = filename.replace(".jsonl", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue

                file_size = os.path.getsize(file_path)

                if file_date < delete_date:
                    
                    os.remove(file_path)
                    cleanup_result["deleted"] += 1
                    cleanup_result["freed_mb"] += file_size / (1024 * 1024)
                    logger.info(f"已删除旧文件: {file_path}")

                elif file_date < threshold_date:
                    
                    gz_path = file_path + ".gz"
                    if not os.path.exists(gz_path):
                        try:
                            with open(file_path, 'rb') as f_in:
                                with gzip.open(gz_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            os.remove(file_path)
                            gz_size = os.path.getsize(gz_path)
                            cleanup_result["compressed"] += 1
                            cleanup_result["freed_mb"] += (file_size - gz_size) / (1024 * 1024)
                            logger.info(f"已压缩归档文件: {file_path}")
                        except Exception as e:
                            logger.error(f"压缩文件失败: {file_path}, 错误: {e}")

            
            for filename in os.listdir(group_path):
                if not filename.endswith(".jsonl.gz"):
                    continue
                file_path = os.path.join(group_path, filename)
                date_str = filename.replace(".jsonl.gz", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if file_date < delete_date:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    cleanup_result["deleted"] += 1
                    cleanup_result["freed_mb"] += file_size / (1024 * 1024)
                    logger.info(f"已删除旧压缩文件: {file_path}")

        cleanup_result["alerts_compacted"] = self._compact_alerts_file()

        
        self._cleanup_by_quota(cleanup_result)

        cleanup_result["freed_mb"] = round(cleanup_result["freed_mb"], 2)
        logger.info(f"清理完成: 压缩{cleanup_result['compressed']}个文件, "
                    f"删除{cleanup_result['deleted']}个文件, "
                    f"释放{cleanup_result['freed_mb']}MB空间")

        return cleanup_result

    def _cleanup_by_quota(self, cleanup_result: Dict[str, Any]) -> None:
        """QQ bot stack component."""




        quota = float(self.max_storage_mb or 0)
        if quota <= 0:
            return

        archives = []
        for group_name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, group_name)
            if not os.path.isdir(group_path):
                continue
            for filename in os.listdir(group_path):
                if not filename.endswith(".jsonl.gz"):
                    continue
                file_path = os.path.join(group_path, filename)
                try:
                    archives.append((file_path, os.path.getmtime(file_path)))
                except OSError:
                    continue
        if not archives:
            return

        archives.sort(key=lambda x: x[1])
        used_mb = self._calculate_storage_size()

        while archives and used_mb > quota * 0.7:
            file_path, _mtime = archives.pop(0)
            try:
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                os.remove(file_path)
                used_mb -= size_mb
                cleanup_result["deleted"] += 1
                cleanup_result["quota_deleted"] += 1
                cleanup_result["freed_mb"] += size_mb
                logger.warning(f"存储超配额，已删除最早归档: {file_path}")
            except OSError as e:
                logger.error(f"配额清理失败: {file_path}, {e}")

        if used_mb > quota * 0.8:
            sizes = self._measure_storage()
            logger.warning(
                f"存储仍占用 {used_mb:.1f}MB（配额 {quota:.0f}MB），"
                f"其中附件 {sizes['attachment'] / (1024 * 1024):.1f}MB 不会被自动清理，"
                f"需要释放空间请手动处理 data 目录下的 附件/ 与 images/ 文件夹"
            )

    def _compact_alerts_file(self) -> int:
        """QQ bot stack component."""




        alert_file = os.path.join(self.data_dir, "alerts.jsonl")
        if not os.path.exists(alert_file):
            return 0

        try:
            with self._alerts_file_lock:
                
                file_count = 0
                try:
                    with open(alert_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                file_count += 1
                except OSError:
                    file_count = 0

                with self._alerts_lock:
                    alerts = self._sort_alerts_desc(self._alerts)[:self.max_alert_records]
                    
                    alerts_to_write = list(reversed(alerts))
                    self._alerts = alerts_to_write[-self.max_alert_records:]

                temp_file = alert_file + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    for alert in alerts_to_write:
                        f.write(json.dumps(alert, ensure_ascii=False) + "\n")
                os.replace(temp_file, alert_file)
                return max(0, file_count - len(alerts_to_write))
        except Exception as e:
            logger.error(f"压缩告警文件失败: {e}")
            try:
                temp_file = alert_file + ".tmp"
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass
            return 0

    def _calculate_path_size(self, path: str) -> int:
        """QQ bot stack component."""
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except OSError:
                return 0
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(file_path)
                except (OSError, FileNotFoundError):
                    continue
        return total

    def _calculate_storage_size(self) -> float:
        """QQ bot stack component."""
        return self._calculate_path_size(self.data_dir) / (1024 * 1024)

    def flush(self) -> None:
        """QQ bot stack component."""
        with self._file_lock:
            self._file_handles.clear()
        logger.info("存储缓冲区已刷新")
