"""QQ bot stack component."""




import os
import time
import threading
import requests
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from .logger import setup_logger

logger = setup_logger("exporter")


class HumanReadableExporter:
    """QQ bot stack component."""

    def __init__(self, export_dir: str, max_storage_mb: int = 500,
                 data_dir: str = None, bot_qq: str = ""):
        self.export_dir = export_dir
        self.max_storage_mb = max_storage_mb
        
        self.bot_qq = str(bot_qq or "")
        
        
        
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )

        
        self._file_handles: Dict[str, Any] = {}
        self._file_lock = threading.Lock()

        
        self._exported_ids: set = set()
        self._exported_lock = threading.Lock()

        
        self._img_counters: Dict[str, int] = {}

        
        
        self._image_index: Dict[int, Dict[str, str]] = {}
        self._image_index_lock = threading.Lock()

        
        self._ensured_dirs: set = set()
        self._dir_lock = threading.Lock()

        
        
        
        
        
        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as e:
            fallback = os.path.join(self.data_dir, "导出")
            logger.warning(
                f"导出目录建不出来（{export_dir}）：{type(e).__name__}: {e} —— "
                f"多半是没插 U 盘 / 盘符变了，本次降级到 {fallback}")
            export_dir = fallback
            try:
                os.makedirs(export_dir, exist_ok=True)
            except OSError as e2:
                logger.error(f"降级目录也建不出来（{export_dir}）：{e2} —— "
                             f"本次导出功能不可用，但监控继续跑")
                export_dir = self.data_dir
        self.export_dir = export_dir
        logger.info(f"人类可读导出器初始化完成，导出目录: {export_dir}")

    def update_export_dir(self, export_dir: str) -> bool:
        """QQ bot stack component."""




        if not export_dir:
            return False
        export_dir = os.path.abspath(export_dir)
        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"切换导出目录失败（{export_dir}）：{type(e).__name__}: {e} —— "
                           f"继续用原来的 {self.export_dir}")
            return False
        with self._file_lock:
            self.export_dir = export_dir
            self._img_counters.clear()
        with self._image_index_lock:
            self._image_index.clear()
        with self._dir_lock:
            self._ensured_dirs.clear()
        logger.info(f"聊天记录TXT导出目录已更新: {export_dir}")

    def export_message(self, message: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        if message.get("type") != "message":
            return

        msg_key = self._get_message_key(message)
        if not msg_key:
            return

        
        with self._exported_lock:
            if msg_key in self._exported_ids:
                return
            self._exported_ids.add(msg_key)

        group_id = message.get("group_id", 0)
        dt_str = message.get("datetime", "")
        date_part = dt_str[:10] if len(dt_str) >= 10 else datetime.now().strftime("%Y-%m-%d")

        
        file_key = f"{group_id}_{date_part}"
        file_path = self._get_file_path(group_id, date_part)

        
        line = self._format_message_line(message, group_id, date_part)

        
        with self._file_lock:
            try:
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(line + "\n")
            except Exception as e:
                logger.error(f"写入导出文件失败: {e}")

    def _get_message_key(self, message: Dict[str, Any]) -> Optional[Tuple]:
        """QQ bot stack component."""
        msg_id = message.get("message_id", 0)
        group_id = message.get("group_id", 0)
        if msg_id:
            return ("id", group_id, msg_id)

        content_text = message.get("content", {}).get("text", "")
        return (
            "fallback",
            group_id,
            message.get("user_id", 0),
            message.get("time", 0),
            content_text
        )

    def _ensure_dir(self, path: str) -> None:
        """QQ bot stack component."""
        with self._dir_lock:
            if path in self._ensured_dirs:
                return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            logger.debug(f"创建目录失败: {path}, {e}")
            return
        with self._dir_lock:
            self._ensured_dirs.add(path)

    def _get_file_path(self, group_id: int, date_str: str) -> str:
        """QQ bot stack component."""
        group_dir = os.path.join(self.export_dir, f"群{group_id}")
        self._ensure_dir(group_dir)
        return os.path.join(group_dir, f"{date_str}.txt")

    def _format_message_line(self, message: Dict[str, Any],
                             group_id: int, date_str: str,
                             allow_download: bool = True) -> str:
        """QQ bot stack component."""




        dt = message.get("datetime", "")
        nickname = message.get("card") or message.get("nickname", "未知")
        user_id = message.get("user_id", 0)
        
        
        
        
        if message.get("is_bot") or (self.bot_qq and str(user_id) == str(self.bot_qq)):
            nickname = f"{nickname}[AI]"
        content = message.get("content", {})
        segments = content.get("segments", [])
        
        content_text = content.get("text", "").strip()

        parts = []

        image_index = 0
        for seg in segments:
            seg_type = seg.get("type", "")
            
            seg_data = seg.get("data", seg)  

            if seg_type == "text":
                text = seg.get("text", "") or seg_data.get("text", "")
                if text:
                    parts.append(text)
                elif content_text:
                    
                    parts.append(content_text)
                    content_text = ""  

            elif seg_type == "image":
                image_index += 1
                
                local_path = seg.get("local_path", "")
                img_url = seg.get("url", "") or seg_data.get("url", "")
                dest_rel = None
                if local_path:
                    
                    dest_rel = self._copy_or_download_image(
                        local_path, img_url, message, date_str, image_index,
                        allow_download=allow_download
                    )
                elif img_url and allow_download:
                    dest_rel = self._download_image(
                        img_url, message, date_str, image_index
                    )
                parts.append(f"[图片] -> {dest_rel}" if dest_rel else "[图片]")

            elif seg_type == "face":
                face_id = seg.get("id", "") or seg_data.get("id", "")
                parts.append(f"[表情:{face_id}]")

            elif seg_type == "at":
                qq = seg.get("qq", "") or seg_data.get("qq", "")
                name = seg.get("name", "") or seg_data.get("name", "")
                if name or qq:
                    parts.append(f"[@{name or qq}]")

            elif seg_type == "reply":
                msg_preview = seg.get("msg_preview", "") or seg_data.get("msg_preview", "")[:50]
                parts.append(f"[回复: {msg_preview}]")

            elif seg_type == "voice":
                parts.append("[语音消息]")

            elif seg_type == "video":
                parts.append("[视频]")

            elif seg_type == "forward":
                parts.append("[合并转发消息]")

            elif seg_type == "json":
                parts.append("[JSON消息]")

            elif seg_type == "xml":
                parts.append("[XML消息]")

            elif seg_type == "markdown":
                parts.append("[Markdown消息]")

            elif seg_type == "poke":
                parts.append("[戳一戳]")

            elif seg_type == "dice":
                parts.append("[骰子]")

            elif seg_type == "rps":
                parts.append("[猜拳]")

            else:
                summary = seg.get("summary", "") or seg_data.get("summary", "")
                if summary and summary != seg_type:
                    parts.append(f"[{summary}]")
                

        
        if not parts:
            raw = message.get("raw_message", "").strip()
            if raw:
                
                import re
                clean = re.sub(r'\[CQ:[^\]]+\]', '[消息]', raw)
                parts.append(clean)

        content_str = " ".join(parts) if parts else "[无法识别的内容]"
        return f"[{dt}] {nickname}(QQ:{user_id}): {content_str}"

    def _copy_or_download_image(self, local_path: str, img_url: str,
                                message: Dict[str, Any], date_str: str,
                                image_index: int = 1,
                                allow_download: bool = True) -> Optional[str]:
        """QQ bot stack component."""
        group_id = message.get("group_id", 0)
        img_dir = os.path.join(self.export_dir, f"群{group_id}", "附件", "图片", date_str)
        self._ensure_dir(img_dir)

        
        ext = ".jpg"
        if local_path:
            low = local_path.lower()
            if ".gif" in low:
                ext = ".gif"
            elif ".png" in low:
                ext = ".png"
        elif img_url:
            low = img_url.lower()
            if "gif" in low:
                ext = ".gif"
            elif "png" in low:
                ext = ".png"

        
        if local_path:
            src_path = self._resolve_local_image_path(local_path)
            if src_path and os.path.exists(src_path):
                meta = self._parse_source_image_meta(src_path)
                if meta:
                    
                    content_hash, size_bytes = meta
                else:
                    content_hash, size_bytes = self._hash_file(src_path)
                existing_path = self._find_existing_image(group_id, content_hash, size_bytes)
                if existing_path:
                    rel = os.path.relpath(existing_path, os.path.join(self.export_dir, f"群{group_id}"))
                    return rel.replace(os.sep, "/")
                filename = self._build_image_filename(message, date_str, image_index, content_hash, size_bytes, ext)
                dest_path = os.path.join(img_dir, filename)
                if not os.path.exists(dest_path):
                    import shutil
                    shutil.copy2(src_path, dest_path)
                self._register_exported_image(group_id, content_hash, size_bytes, dest_path)
                rel = os.path.relpath(dest_path, os.path.join(self.export_dir, f"群{group_id}"))
                return rel.replace(os.sep, "/")

        
        if img_url and allow_download:
            return self._download_image(img_url, message, date_str, image_index)

        return None

    def _resolve_local_image_path(self, local_path: str) -> Optional[str]:
        """QQ bot stack component."""
        if not local_path:
            return None
        rel = str(local_path).strip()
        for prefix in ("/api/images/", "api/images/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        rel = rel.replace("/", os.sep)

        if os.path.isabs(rel):
            candidate = os.path.abspath(rel)
        else:
            candidate = os.path.abspath(os.path.join(self.data_dir, rel))

        
        base = os.path.abspath(self.data_dir)
        if candidate != base and not candidate.startswith(base + os.sep):
            return None
        return candidate

    def _download_image(self, url: str, message: Dict[str, Any],
                        date_str: str, image_index: int = 1) -> Optional[str]:
        """QQ bot stack component."""
        if not url:
            return None

        temp_path = None
        try:
            group_id = message.get("group_id", 0)
            img_dir = os.path.join(self.export_dir, f"群{group_id}", "附件", "图片", date_str)
            self._ensure_dir(img_dir)

            ext = ".jpg"
            if "gif" in url.lower():
                ext = ".gif"
            elif "png" in url.lower():
                ext = ".png"

            resp = requests.get(url, timeout=10, stream=True)
            if resp.status_code == 200:
                hasher = hashlib.sha256()
                downloaded = 0
                temp_path = os.path.join(img_dir, f".tmp_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}.download")
                with open(temp_path, 'wb') as f:
                    for chunk in resp.iter_content(8192):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        hasher.update(chunk)
                        f.write(chunk)
                content_hash = hasher.hexdigest()
                existing_path = self._find_existing_image(group_id, content_hash, downloaded)
                if existing_path:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                    temp_path = None
                    rel = os.path.relpath(existing_path, os.path.join(self.export_dir, f"群{group_id}"))
                    return rel.replace(os.sep, "/")
                filename = self._build_image_filename(message, date_str, image_index, content_hash, downloaded, ext)
                local_path = os.path.join(img_dir, filename)
                os.replace(temp_path, local_path)
                temp_path = None
                self._register_exported_image(group_id, content_hash, downloaded, local_path)
                rel = os.path.relpath(local_path, os.path.join(self.export_dir, f"群{group_id}"))
                logger.debug(f"图片已导出: {local_path}")
                return rel.replace(os.sep, "/")
            else:
                return None

        except Exception as e:
            logger.debug(f"图片导出失败: {e}")
            return None
        finally:
            if temp_path:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    pass

    def _safe_filename_part(self, value: Any, max_len: int = 24) -> str:
        """QQ bot stack component."""
        text = str(value or "").strip()
        text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
        text = re.sub(r"\s+", "_", text)
        text = text.strip("._ ")
        return (text[:max_len] or "未知")

    def _build_image_filename(self, message: Dict[str, Any], date_str: str,
                              image_index: int, content_hash: str,
                              size_bytes: int, ext: str) -> str:
        """QQ bot stack component."""
        dt = message.get("datetime", "")
        date_part = date_str.replace("-", "")
        time_part = "000000"
        if len(dt) >= 19:
            time_part = dt[11:19].replace(":", "")
        user_id = self._safe_filename_part(message.get("user_id", 0), 20)
        return f"{date_part}_{time_part}_QQ{user_id}_图{image_index}_{content_hash[:12]}_{int(size_bytes)}B{ext}"

    def _find_existing_image(self, group_id: int, content_hash: str, size_bytes: int) -> Optional[str]:
        """QQ bot stack component."""
        marker = self._image_marker(content_hash, size_bytes)
        return self._get_image_index(group_id).get(marker)

    @staticmethod
    def _image_marker(content_hash: str, size_bytes: int) -> str:
        """QQ bot stack component."""
        return f"_{str(content_hash or '')[:12].lower()}_{int(size_bytes)}B."

    def _get_image_index(self, group_id: int) -> Dict[str, str]:
        """QQ bot stack component."""
        with self._image_index_lock:
            cached = self._image_index.get(group_id)
            if cached is not None:
                return cached

        index: Dict[str, str] = {}
        images_root = os.path.join(self.export_dir, f"群{group_id}", "附件", "图片")
        if os.path.isdir(images_root):
            try:
                for dirpath, _, filenames in os.walk(images_root):
                    for filename in filenames:
                        m = re.search(r"_([0-9a-fA-F]{12})_(\d+)B\.", filename)
                        if m:
                            marker = f"_{m.group(1).lower()}_{m.group(2)}B."
                            index.setdefault(marker, os.path.join(dirpath, filename))
            except OSError:
                pass

        with self._image_index_lock:
            self._image_index[group_id] = index
        return index

    def _register_exported_image(self, group_id: int, content_hash: str,
                                 size_bytes: int, path: str) -> None:
        """QQ bot stack component."""
        with self._image_index_lock:
            index = self._image_index.get(group_id)
            if index is not None:
                index.setdefault(self._image_marker(content_hash, size_bytes), path)

    @staticmethod
    def _parse_source_image_meta(src_path: str) -> Optional[Tuple[str, int]]:
        """QQ bot stack component."""





        name = os.path.basename(src_path or "")
        m = re.search(r"_([0-9a-fA-F]{12})_(\d+)B\.[A-Za-z0-9]+$", name)
        if not m:
            return None
        try:
            return m.group(1).lower(), int(m.group(2))
        except (TypeError, ValueError):
            return None

    def _hash_file(self, file_path: str) -> Tuple[str, int]:
        """QQ bot stack component."""
        hasher = hashlib.sha256()
        size = 0
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                size += len(chunk)
                hasher.update(chunk)
        return hasher.hexdigest(), size

    def export_history_from_store(self, store, allow_download: bool = False) -> int:
        """QQ bot stack component."""









        exported = 0
        grouped_lines: Dict[str, List[str]] = {}
        seen_keys = set()

        
        
        by_day: Dict[Any, List[Dict[str, Any]]] = {}
        for group_id, msg in store.iter_all_messages():
            try:
                if msg.get("type") != "message":
                    continue
                msg_key = self._get_message_key(msg)
                if not msg_key or msg_key in seen_keys:
                    continue
                seen_keys.add(msg_key)
                dt_str = msg.get("datetime", "")
                date_part = dt_str[:10] if len(dt_str) >= 10 else datetime.now().strftime("%Y-%m-%d")
                by_day.setdefault((group_id, date_part), []).append(msg)
            except Exception as e:
                logger.debug(f"导出历史消息跳过: {e}")

        for (group_id, date_part), messages in by_day.items():
            file_path = self._get_file_path(group_id, date_part)
            lines = grouped_lines.setdefault(file_path, [])
            for msg in sorted(messages, key=lambda x: (x.get("time", 0), x.get("message_id", 0))):
                try:
                    lines.append(self._format_message_line(msg, group_id, date_part,
                                                           allow_download=allow_download))
                    exported += 1
                except Exception as e:
                    logger.debug(f"导出历史消息跳过: {e}")

        with self._file_lock:
            for file_path, lines in grouped_lines.items():
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write("\n".join(lines))
                        if lines:
                            f.write("\n")
                except Exception as e:
                    logger.error(f"重建导出文件失败: {file_path}, 错误: {e}")

        with self._exported_lock:
            self._exported_ids = seen_keys

        logger.info(f"历史记录导出完成，共导出 {exported} 条")
        return exported

    def export_recent_from_store(self, store, days: int = 3, allow_download: bool = False,
                                 dates: Optional[List[str]] = None) -> int:
        """QQ bot stack component."""












        from datetime import timedelta

        try:
            span = max(1, int(days))
        except (TypeError, ValueError):
            span = 3
        today = datetime.now().date()
        
        day_list = [str(d) for d in (dates or []) if str(d).strip()]
        if not day_list:
            day_list = [(today - timedelta(days=i)).isoformat() for i in range(span)]

        groups: List[int] = []
        try:
            for item in store.get_monitored_groups():
                gid = item.get("group_id")
                if isinstance(gid, int) or (isinstance(gid, str) and gid.isdigit()):
                    groups.append(int(gid))
        except Exception as exc:  
            logger.debug("取监控群失败，改用数据目录扫描: %s", type(exc).__name__)
        if not groups:
            try:
                base = getattr(store, "data_dir", "")
                for name in os.listdir(base):
                    if name.isdigit() and os.path.isdir(os.path.join(base, name)):
                        groups.append(int(name))
            except Exception:  
                groups = []

        exported = 0
        for group_id in groups:
            for date_part in day_list:
                try:
                    messages = store.query_from_file(group_id, date_part)
                except Exception as exc:  
                    logger.debug("读取 %s/%s 失败: %s", group_id, date_part, type(exc).__name__)
                    continue
                if not messages:
                    continue

                seen = set()
                picked: List[Tuple[float, str, Dict[str, Any]]] = []
                for msg in messages:
                    if msg.get("type") != "message":
                        continue
                    key = self._get_message_key(msg)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    picked.append((msg.get("time", 0) or 0, str(msg.get("message_id", "")), msg))
                if not picked:
                    continue
                picked.sort(key=lambda item: (item[0], item[1]))

                lines: List[str] = []
                for _, _, msg in picked:
                    try:
                        lines.append(
                            self._format_message_line(msg, group_id, date_part, allow_download=allow_download)
                        )
                    except Exception as exc:  
                        logger.debug("格式化消息失败，跳过: %s", type(exc).__name__)

                file_path = self._get_file_path(group_id, date_part)
                with self._file_lock:
                    try:
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write("\n".join(lines))
                            if lines:
                                f.write("\n")
                    except Exception as exc:  
                        logger.error("重建导出文件失败: %s, 错误: %s", file_path, exc)
                        continue
                with self._exported_lock:
                    self._exported_ids |= seen
                exported += len(lines)

        if exported:
            scope = f"{len(day_list)} 个指定日期" if dates else f"最近 {span} 天"
            logger.info("重建导出完成（%s），共 %s 行", scope, exported)
        return exported

    def check_and_cleanup(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(self.export_dir):
            for f in filenames:
                try:
                    total_size += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    continue

        used_mb = total_size / (1024 * 1024)
        result = {
            "used_mb": round(used_mb, 2),
            "max_mb": self.max_storage_mb,
            "needs_cleanup": used_mb > self.max_storage_mb * 0.8
        }

        if result["needs_cleanup"]:
            self._cleanup_old_files()

        return result

    def _cleanup_old_files(self) -> None:
        """QQ bot stack component."""
        from datetime import timedelta

        
        txt_files = []
        for group_dir_name in os.listdir(self.export_dir):
            group_path = os.path.join(self.export_dir, group_dir_name)
            if not os.path.isdir(group_path):
                continue
            for fname in os.listdir(group_path):
                if fname.endswith(".txt"):
                    fpath = os.path.join(group_path, fname)
                    txt_files.append((fpath, os.path.getmtime(fpath)))

        txt_files.sort(key=lambda x: x[1])  

        
        while txt_files:
            used_mb = self._calc_total_size() / (1024 * 1024)
            if used_mb < self.max_storage_mb * 0.7:
                break

            fpath, _ = txt_files.pop(0)
            try:
                os.remove(fpath)
                logger.info(f"清理旧文件: {fpath}")
                
                
                date_str = os.path.basename(fpath).replace(".txt", "")
                group_dir = os.path.dirname(fpath)
                import shutil
                for img_dir in (
                    os.path.join(group_dir, "附件", "图片", date_str),
                    os.path.join(group_dir, "附件", "文件", date_str),
                    os.path.join(group_dir, "附件", "视频", date_str),
                    os.path.join(group_dir, "附件", "语音", date_str),
                    os.path.join(group_dir, "images", date_str),
                ):
                    if os.path.exists(img_dir):
                        shutil.rmtree(img_dir, ignore_errors=True)
                        logger.info(f"清理附件目录: {img_dir}")
            except Exception as e:
                logger.error(f"清理文件失败: {fpath}, {e}")

        
        with self._image_index_lock:
            self._image_index.clear()

    def _calc_total_size(self) -> float:
        total = 0
        for dirpath, _, filenames in os.walk(self.export_dir):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    continue
        return total
