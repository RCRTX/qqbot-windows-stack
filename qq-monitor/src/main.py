"""QQ bot stack component."""




import os
import sys
import time
import signal
import threading
import traceback
import schedule
from datetime import datetime
from typing import Any, Dict, List, Optional












_LOCAL_NO_PROXY = "127.0.0.1,localhost,::1,"
for _k in ("no_proxy", "NO_PROXY"):
    _cur = os.environ.get(_k, "").strip()
    os.environ[_k] = f"{_cur},{_LOCAL_NO_PROXY}" if _cur else _LOCAL_NO_PROXY


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_loader import Config
from src.logger import setup_logger
from src.onebot_client import OneBotClient
from src.message_store import MessageStore
from src.compliance import ComplianceManager, ChatCompanion, Repeater
from src.alert_manager import AlertManager
from src.web_panel import WebPanel
from src.history_fetcher import HistoryFetcher
from src.keyword_reply import KeywordReplier
from src.human_readable_exporter import HumanReadableExporter
from src.word_exporter import WordExporter
from src.marked_users import MarkedUserStore

logger = setup_logger("main")


class QQMonitor:
    """QQ bot stack component."""

    def __init__(self, config_path: str):
        self.config_path = config_path

        
        self.config = Config(config_path)

        
        self._init_modules()

        
        self._running = False
        self._scheduler_thread = None
        
        self._topup_lock = threading.Lock()
        self._topup_state: Dict[str, Any] = {"runs": 0, "last_run": "", "last_added": 0,
                                             "last_self_added": 0, "checked": 0}

    def _init_modules(self) -> None:
        """QQ bot stack component."""
        logger.info("正在初始化模块...")

        
        self.store = MessageStore(
            data_dir=self.config.storage['data_dir'],
            log_dir=self.config.storage['log_dir'],
            max_storage_mb=self.config.storage['max_storage_mb'],
            archive_days=self.config.storage['archive_days'],
            file_rotate_hours=self.config.storage['file_rotate_hours'],
            save_images=self.config.storage.get('save_images', True),
            max_image_size_mb=self.config.storage.get('max_image_size_mb', 5),
            save_files=self.config.storage.get('save_files', True),
            large_file_confirm_mb=self.config.storage.get('large_file_confirm_mb', 1024),
            max_alert_records=self.config.storage.get('max_alert_records', 1000),
            max_memory_index_per_group=self.config.storage.get('max_memory_index_per_group', 10000),
            max_saved_ids=self.config.storage.get('max_saved_ids', 200000),
            max_finished_pending_records=self.config.storage.get('max_finished_pending_records', 200),
            auto_cleanup_enabled=self.config.storage.get('auto_cleanup_enabled', False)
        )

        
        self.onebot = OneBotClient(
            ws_url=self.config.napcat['ws_url'],
            token=self.config.napcat.get('token', ''),
            monitor_groups=self.config.napcat['monitor_groups'],
            http_url=self.config.napcat.get('http_url', '')
        )

        
        self.compliance = ComplianceManager(self.config._config, config_path=self.config_path)

        
        try:
            from .poke import PokeManager
        except ImportError:  
            from poke import PokeManager
        self.poke = PokeManager(self.config, self.onebot, logger)

        
        
        try:
            self.compliance.seed_alerted_messages(self.store.get_alerted_message_records())
        except Exception as e:
            logger.warning(f"载入历史告警去重集合失败（不影响运行）: {e}")

        
        chat_cfg = self.config._config.get("chat_companion", {})
        secondary_cfg = self.config._config.get("secondary_ai_review", {})
        self.companion = None
        if chat_cfg.get("enabled", False):
            self.companion = ChatCompanion(
                api_base=chat_cfg.get("api_base") or secondary_cfg.get("api_base", "http://localhost:11434/v1"),
                api_key=chat_cfg.get("api_key") or secondary_cfg.get("api_key", "ollama"),
                model=chat_cfg.get("model") or secondary_cfg.get("model", "qwen2.5"),
                system_prompt=chat_cfg.get("system_prompt", ""),
                bot_name=chat_cfg.get("bot_name", "小助手"),
                cooldown_seconds=chat_cfg.get("cooldown_seconds", 10)
            )

        
        self.alert = AlertManager(self.config._config)

        
        
        
        repeat_cfg = self.config._config.get("repeater", {}) or {}
        if repeat_cfg.get("enabled", False):
            self.repeater = Repeater(
                cooldown_seconds=int(repeat_cfg.get("cooldown_seconds", 1800)))
            logger.info(f"复读功能已启用（冷却 {self.repeater.cooldown_seconds} 秒）")
        else:
            self.repeater = None
            logger.info("复读功能未启用（repeater.enabled=false）——群里的发言只来自麦麦")

        
        
        
        
        
        mark_cfg = self.config._config.get("marked_users", {}) or {}
        self.marked_users = MarkedUserStore(
            data_dir=self.config.storage['data_dir'],
            enabled=mark_cfg.get("enabled", True),
            client=self.onebot,
        )
        if self.marked_users.enabled:
            logger.info(f"标记用户已启用（正文出现 ** 且 @ 了人 → 标记被 @ 的人，"
                        f"追加到 {self.marked_users.path}）")
        else:
            logger.info("标记用户未启用（marked_users.enabled=false）")

        
        web_cfg = self.config._config.get("web_panel", {}) or {}
        self.web_panel = WebPanel(
            store=self.store,
            host=web_cfg.get("host", "0.0.0.0"),
            port=int(web_cfg.get("port", 8080)),
            access_token=web_cfg.get("access_token", "")
        )
        self.web_panel.set_components(
            onebot_client=self.onebot,
            compliance_manager=self.compliance,
            alert_manager=self.alert,
            companion=self.companion
        )

        
        
        self.keyword_replier = KeywordReplier(self.onebot, store=self.store)
        self.onebot.on_any_group_message(self.keyword_replier.handle)

        
        
        
        from src.memory_keeper import MemoryKeeper
        self.memory_keeper = MemoryKeeper(self.onebot)
        self.onebot.on_any_group_message(self.memory_keeper.handle)
        self.memory_keeper.start()

        
        
        from src.diary_keeper import DiaryKeeper
        self.diary_keeper = DiaryKeeper(self.store, self.memory_keeper)

        self.web_panel.set_components(
            onebot_client=self.onebot,
            compliance_manager=self.compliance,
            alert_manager=self.alert,
            companion=self.companion,
            memory_keeper=self.memory_keeper,
            diary_keeper=self.diary_keeper
        )

        
        
        
        
        
        self.onebot.on_any_group_message(self._on_any_group_message)

        
        self.onebot.on_message(self._on_message_received)
        self.onebot.on_private_message(self._on_private_message_received)
        if getattr(self, "poke", None) is not None:
            self.onebot.on_notice(self.poke.on_notice)

        
        self.store.on_large_file_pending(self.alert.send_large_file_confirm_alert)

        
        self.compliance.on_violation(self._on_violation_detected)

        
        self.history_fetcher = None
        http_url = self.config.napcat.get('http_url', '')
        if http_url:
            self.history_fetcher = HistoryFetcher(
                http_url=http_url,
                token=self.config.napcat.get('token', ''),
                monitor_groups=self.config.napcat['monitor_groups']
            )
            logger.info("历史消息拉取器初始化成功")

        
        self.exporter = HumanReadableExporter(
            export_dir=self.config.storage.get('export_dir'),
            max_storage_mb=self.config.storage.get('max_storage_mb', 500),
            data_dir=self.config.storage.get('data_dir')
        )
        
        
        self.word_exporter = WordExporter(
            export_dir=self.config.storage.get('export_dir'),
            data_dir=self.config.storage.get('data_dir')
        )
        self.web_panel.set_components(exporter=self.exporter, word_exporter=self.word_exporter,
                                      monitor=self)
        
        
        
        
        
        if str(self.config.storage.get("export_on_start", "")).lower() in ("1", "true", "yes"):
            logger.info("正在导出历史记录为人类可读格式（export_on_start=true）...")
            self.exporter.export_history_from_store(self.store)

        
        
        
        
        
        try:
            self._export_rebuild_days = int(self.config.storage.get("export_rebuild_days", 3) or 3)
        except (TypeError, ValueError):
            self._export_rebuild_days = 3
        if self._export_rebuild_days > 0:
            try:
                self.exporter.export_recent_from_store(self.store, days=self._export_rebuild_days)
            except Exception as exc:  
                logger.warning("重建最近几天导出失败: %s", exc)

        logger.info("所有模块初始化完成")

    def _on_any_group_message(self, message: dict) -> None:
        """QQ bot stack component."""








        try:
            for hit in self.marked_users.maybe_record(message, self.onebot.bot_qq):
                logger.info(f"标记用户：群{hit['group_id']} 被标记 {hit['qq']}"
                            f"({hit['nickname'] or '?'}/{hit['role'] or '?'})，"
                            f"标记人 {hit['by_qq']}({hit['by_nickname'] or '?'})"
                            f" → {hit['text'][:40]}")
        except Exception as e:
            logger.error(f"标记用户处理失败: {e}")

    def _on_message_received(self, message: dict) -> None:
        """QQ bot stack component."""
        
        self.store.save_message(message)

        
        self.exporter.export_message(message)

        
        violation = self.compliance.add_message(message)
        if violation:
            logger.warning(
                f"检测到违规内容! 群:{message.get('group_id')} "
                f"用户:{message.get('nickname')} "
                f"类型:{violation.get('type')} "
                f"级别:{violation.get('severity')}"
            )

        
        if self.repeater:
            try:
                repeat_group = self.repeater.check_and_repeat(message)
                if repeat_group:
                    text = self.repeater._extract_text(message)
                    if text:
                        self.onebot.send_group_message(repeat_group, text)
            except Exception as e:
                logger.error(f"复读处理失败: {e}")

        
        

        
        if self.companion:
            try:
                bot_qq = self.onebot.bot_qq
                if not bot_qq:
                    
                    logger.debug("陪聊跳过：机器人QQ号尚未获取到（等待WebSocket消息）")
                else:
                    if self.companion.is_mentioned(message, bot_qq):
                        group_id = message.get("group_id", 0)
                        logger.info(f"陪聊触发：群{group_id}，用户{message.get('nickname')}@了机器人")
                        
                        recent = self.store.get_recent_messages(group_id, limit=6)
                        reply = self.companion.generate_reply(message, recent)
                        if reply:
                            logger.info(f"陪聊回复：{reply[:50]}")
                            self.onebot.send_group_message(group_id, reply)
                        else:
                            logger.debug("陪聊：AI未生成回复")
            except Exception as e:
                logger.error(f"陪聊处理失败: {e}")
        else:
            
            if not hasattr(self, '_companion_warned'):
                self._companion_warned = True
                logger.info("陪聊功能未启用（chat_companion.enabled=false或配置缺失）")

    def _on_violation_detected(self, violation: dict) -> None:
        """QQ bot stack component."""
        message = violation.get("message", {})

        
        alert_record = {
            "type": violation.get("type", "unknown"),
            "severity": violation.get("severity", "medium"),
            "category": violation.get("category", "other"),
            "category_label": violation.get("category_label", ""),
            "violation_type": violation.get("violation_type", violation.get("type", "")),
            "reason": violation.get("reason", ""),
            "secondary_status": violation.get("secondary_status", "not_reviewed"),
            "secondary_status_label": violation.get("secondary_status_label", "未二次复核"),
            "secondary_reason": violation.get("secondary_reason", ""),
            "report_basis": violation.get("report_basis", "primary_review"),
            "report_basis_label": violation.get("report_basis_label", "按首次结果上报"),
            "should_notify": violation.get("should_notify", True),
            "is_escalation": violation.get("is_escalation", False),
            "previous_level": violation.get("previous_level"),
            "matched_word": violation.get("matched_word", ""),
            "content_preview": violation.get("content_preview", ""),
            "message_id": message.get("message_id", 0),
            "group_id": message.get("group_id", 0),
            "user_id": message.get("user_id", 0),
            "nickname": message.get("nickname", ""),
            "card": message.get("card", ""),
            "datetime": message.get("datetime", ""),
            "time": message.get("time", 0),
            "review_time": datetime.now().isoformat(),
            "notified": False
        }

        
        if alert_record["should_notify"]:
            try:
                
                
                
                self.alert.send_violation_alert_async(violation)
                alert_record["notified"] = True
            except Exception as e:
                alert_record["notify_error"] = str(e)
                logger.error(f"告警通知发送失败，告警记录仍会保存: {e}")
        else:
            logger.info("二次复核认为可能误报，已记录但不发送通知")

        
        self.store.save_alert(alert_record)

    def _on_private_message_received(self, message: dict) -> None:
        """QQ bot stack component."""
        text = (message.get("text") or "").strip()
        user_id = int(message.get("user_id", 0) or 0)
        allowed = []
        qq_notifier = getattr(self.alert, "qq_private_notifier", None)
        if qq_notifier:
            allowed = [int(x) for x in getattr(qq_notifier, "recipient_user_ids", [])]
        if allowed and user_id not in allowed:
            logger.info(f"忽略非通知接收人的私聊管理命令: {user_id}")
            return

        parts = text.split()
        if len(parts) < 2:
            return
        action = parts[0].lower()
        file_id = parts[1].strip()
        if action in ("保存", "save", "确认", "yes", "y"):
            result = self.store.confirm_pending_file(file_id)
            reply = "大文件已确认保存" if result.get("success") else f"大文件保存失败：{result.get('error')}"
            self.onebot.send_private_message(user_id, f"{reply}\n文件ID：{file_id}")
        elif action in ("拒绝", "reject", "no", "n", "取消"):
            result = self.store.reject_pending_file(file_id)
            reply = "已拒绝保存该大文件" if result.get("success") else f"拒绝失败：{result.get('error')}"
            self.onebot.send_private_message(user_id, f"{reply}\n文件ID：{file_id}")

    def _run_ai_review_once(self, source: str = "手动") -> list:
        """QQ bot stack component."""
        try:
            pending_count = self.compliance.get_pending_count()
            logger.info(f"{source}触发AI审查，待审查消息: {pending_count} 条")
            violations = self.compliance.do_ai_review()
            if violations:
                logger.info(f"{source}AI审查发现 {len(violations)} 条违规")
            else:
                logger.info(f"{source}AI审查完成，未发现违规")
            return violations
        except Exception as e:
            logger.error(f"{source}AI审查任务异常: {e}")
            return []

    def _run_scheduler(self) -> None:
        """QQ bot stack component."""
        logger.info("定时任务调度器已启动")

        
        try:
            _pc = (getattr(self.config, "_config", None) or {}).get("poke") or {}
            _pa = (_pc.get("active") or {}) if isinstance(_pc, dict) else {}
            if _pc.get("enabled") and _pa.get("enabled", True):
                _pmin = int(_pa.get("check_interval_minutes") or 45)
                _pchance = float(_pa.get("chance") or 0.5)

                def do_active_poke():
                    if not self._running:
                        return
                    import random as _rnd
                    if _rnd.random() > _pchance:
                        logger.debug("[戳] 这轮摇到不戳")
                        return
                    try:
                        got = self.poke.active_poke_once()
                        if not got:
                            logger.debug("[戳] 这轮没找到合适的目标")
                    except Exception as e:  
                        logger.error(f"[戳] 主动戳任务异常: {type(e).__name__}: {e}")

                schedule.every(_pmin).minutes.do(do_active_poke)
                logger.info(f"主动戳已启用：每 {_pmin} 分钟看一次，{int(_pchance * 100)}% 概率出手")
        except Exception as e:  
            logger.error(f"主动戳初始化失败（不影响其他功能）: {type(e).__name__}: {e}")

        
        review_interval = self.config.ai_review.get('review_interval_minutes', 5)

        def do_review():
            if not self._running:
                return
            self._run_ai_review_once("定时")

        schedule.every(review_interval).minutes.do(do_review)

        
        history_review_enabled = self.config.ai_review.get('history_review_enabled', True)
        history_review_interval = self.config.ai_review.get('history_review_interval_hours', 2)
        history_review_hours_back = self.config.ai_review.get('history_review_hours_back', 4)
        history_review_max = self.config.ai_review.get('history_review_max_messages', 150)

        if history_review_enabled:
            logger.info(f"历史消息定时审查已启用：每{history_review_interval}小时审查过去{history_review_hours_back}小时内的{history_review_max}条消息")

            def do_history_review():
                if not self._running:
                    return
                try:
                    logger.info(f"===== 定时历史消息审查开始 =====")
                    violations = self.compliance.review_history_messages(
                        message_store=self.store,
                        hours_back=history_review_hours_back,
                        max_messages=history_review_max
                    )
                    if violations:
                        logger.info(f"历史消息审查发现 {len(violations)} 条违规，已发送通知")
                    else:
                        logger.info(f"历史消息审查完成，未发现违规")
                    logger.info(f"===== 定时历史消息审查结束 =====")
                except Exception as e:
                    logger.error(f"历史消息审查任务异常: {e}")

            
            
            
            
            
            schedule.every(history_review_interval).hours.do(do_history_review)

            _first_history = {"pending": True}

            def first_history_review():
                if not _first_history["pending"]:
                    return
                _first_history["pending"] = False
                logger.info("启动后的首次历史消息补审（每%s小时一次的常规补审仍照常）"
                            % history_review_interval)
                do_history_review()

            schedule.every(5).minutes.do(first_history_review)

        
        def check_storage():
            if not self._running:
                return
            try:
                storage_info = self.store.check_storage()
                if not storage_info.get("needs_cleanup"):
                    return
                
                if not self.store.auto_cleanup_enabled:
                    logger.warning(
                        f"存储已用到 {storage_info.get('used_mb')}MB"
                        f"（配额 {storage_info.get('max_mb')}MB，"
                        f"{storage_info.get('usage_percent')}%），"
                        f"但自动清理已关闭，不会删除任何记录。"
                        f"如需释放空间：附件可在网页面板「系统配置 → 附件占用与清理」里按日期手动清理；"
                        f"确需自动清理请把 config.json 的 storage.auto_cleanup_enabled 改为 true。"
                    )
                    return
                logger.info("存储空间不足，开始清理...")
                result = self.store.cleanup_old_files()
                logger.info(f"清理完成: {result}")
            except Exception as e:
                logger.error(f"存储检查任务异常: {e}")

        schedule.every().hour.do(check_storage)

        
        def flush_storage():
            if not self._running:
                return
            try:
                self.store.flush()
            except Exception as e:
                logger.error(f"存储刷新异常: {e}")

        schedule.every(10).minutes.do(flush_storage)

        
        while self._running:
            schedule.run_pending()
            time.sleep(1)

    def start(self) -> None:
        """QQ bot stack component."""
        logger.info("=" * 50)
        logger.info("QQ群聊监控系统启动中...")
        logger.info("=" * 50)

        self._running = True

        
        self.web_panel.start_in_thread()

        
        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler,
            daemon=True,
            name="Scheduler"
        )
        self._scheduler_thread.start()

        
        self.onebot.start()

        logger.info("=" * 50)
        logger.info("系统启动完成!")
        logger.info(f"Web面板: http://localhost:{self.web_panel.port}")
        logger.info(f"监控群组: {self.config.napcat['monitor_groups']}")
        logger.info(f"AI审查间隔: {self.config.ai_review.get('review_interval_minutes', 5)}分钟")
        logger.info("=" * 50)

        
        if self.history_fetcher:
            self._fetch_history_on_startup()
            self._start_history_topup()

        else:
            self.diary_keeper.start()

        
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止...")
            self.stop()

    def _ensure_bot_qq(self) -> str:
        """QQ bot stack component."""






        qq = str(getattr(self.onebot, "_bot_qq", "") or "")
        if not qq:
            try:
                qq = str(self.onebot.bot_qq or "")
            except Exception as e:
                logger.debug(f"取机器人 QQ 失败（后面靠 WS 事件补）：{e}")
                qq = ""
        if qq:
            for exp in (getattr(self, "exporter", None), getattr(self, "word_exporter", None)):
                if exp is not None and not getattr(exp, "bot_qq", ""):
                    exp.bot_qq = qq
        return qq

    def _ingest_raw_message(self, raw_msg: Dict[str, Any], source: str = "历史") -> bool:
        """QQ bot stack component."""










        parsed = self.onebot._parse_message(raw_msg)
        if self.onebot.is_bot_message(parsed):
            parsed["is_bot"] = True
        msg_id = parsed.get("message_id", 0)
        with self.store._saved_ids_lock:
            is_new = not msg_id or msg_id not in self.store._saved_message_ids
        
        
        self.store.save_message(parsed, download_media=not self._too_old_for_media(parsed))
        self.exporter.export_message(parsed)
        if is_new and not self._too_old_for_review(parsed):
            self.compliance.add_message(parsed)
            
            
            
            try:
                if getattr(self, "keyword_replier", None):
                    self.keyword_replier.handle(parsed)
            except Exception as e:
                logger.error(f"补齐消息规则处理失败: {e}")
        return is_new

    def _too_old_for_media(self, message: Dict[str, Any]) -> bool:
        """QQ bot stack component."""





        try:
            limit_d = float(self.config.storage.get('backfill_media_max_age_days', 3) or 0)
        except (TypeError, ValueError):
            limit_d = 3.0
        if limit_d <= 0:
            return False
        t = message.get('time') or 0
        if not t:
            return False
        return (time.time() - float(t)) > limit_d * 86400

    def _too_old_for_review(self, message: Dict[str, Any]) -> bool:
        """QQ bot stack component."""








        try:
            limit_h = float(self.config.ai_review.get('history_backfill_max_age_hours', 24) or 0)
        except (TypeError, ValueError):
            limit_h = 24.0
        if limit_h <= 0:
            return False
        t = message.get('time') or 0
        if not t:
            return False
        return (time.time() - float(t)) > limit_h * 3600

    def _topup_once(self, page_size: int = 200, max_pages: int = 0) -> Dict[str, Any]:
        """QQ bot stack component."""











        result = {"checked": 0, "added": 0, "self_added": 0, "errors": 0, "pages": 0}
        if not self.history_fetcher:
            return result
        self._ensure_bot_qq()   
        try:
            cap = int(max_pages or self.config.storage.get('history_topup_max_pages', 10) or 10)
        except (TypeError, ValueError):
            cap = 10
        for group_id in self.config.napcat['monitor_groups']:
            cursor = 0
            for _page_no in range(1, max(1, cap) + 1):
                try:
                    messages = self.history_fetcher.fetch_group_history(
                        group_id=group_id, count=page_size, message_seq=cursor,
                        reverse_order=True if cursor else None)
                except Exception as e:
                    logger.error(f"补齐群 {group_id} 历史失败: {e}")
                    result["errors"] += 1
                    break
                if not messages:
                    break
                result["pages"] += 1
                result["checked"] += len(messages)
                new_here = 0
                for raw in messages:
                    try:
                        if self._ingest_raw_message(raw, source="定时补齐"):
                            new_here += 1
                            result["added"] += 1
                            if self.onebot.is_bot_message(self.onebot._parse_message(raw)):
                                result["self_added"] += 1
                    except Exception as e:
                        logger.debug(f"补齐消息解析跳过: {e}")
                        result["errors"] += 1
                if not new_here:
                    break        
                cursor = self.history_fetcher._oldest_cursor(messages)
                if not cursor:
                    break
                time.sleep(0.2)
        with self._topup_lock:
            self._topup_state.update({
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_added": result["added"],
                "last_self_added": result["self_added"],
                "runs": self._topup_state.get("runs", 0) + 1,
                "checked": result["checked"],
                "pages": result["pages"],
            })
        if result["added"]:
            logger.info(f"历史补齐：翻 {result['pages']} 页、检查 {result['checked']} 条，"
                        f"新增 {result['added']} 条（其中自发言 {result['self_added']} 条）")
        return result

    def _start_history_topup(self) -> None:
        """QQ bot stack component."""
        interval = int(self.config.storage.get('history_topup_interval', 180) or 0)
        if interval <= 0:
            logger.info("历史补齐已关闭（storage.history_topup_interval = 0）")
            return

        def loop():
            time.sleep(30)     
            while self._running:
                try:
                    self._topup_once()
                except Exception as e:
                    logger.error(f"历史补齐出错: {e}\n{traceback.format_exc()}")
                for _ in range(interval):
                    if not self._running:
                        return
                    time.sleep(1)

        threading.Thread(target=loop, daemon=True, name="HistoryTopUp").start()
        logger.info(f"历史补齐已启动：每 {interval} 秒把各群最近的消息拉回来对一遍"
                    f"（含机器人自己的发言）")

    def _fetch_history_on_startup(self) -> None:
        """QQ bot stack component."""





        max_count = int(self.config.storage.get('history_fetch_max', 4000) or 0)

        def fetch_task():
            
            time.sleep(3)
            
            qq = self._ensure_bot_qq()
            logger.info(f"开始拉取历史消息（每群最多 {max_count} 条，含自发言）"
                        f"{'，机器人 QQ=' + qq if qq else '，机器人 QQ 未知（靠 WS 事件补）'}...")

            def on_message(raw_msg):
                """QQ bot stack component."""
                try:
                    self._ingest_raw_message(raw_msg, source="启动回捞")
                except Exception as e:
                    logger.debug(f"历史消息解析跳过: {e}")

            added_total = 0
            for group_id in self.config.napcat['monitor_groups']:
                try:
                    count = self.history_fetcher.fetch_all_history(
                        group_id=group_id,
                        max_count=max_count,
                        callback=on_message
                    )
                    added_total += count
                    logger.info(f"群 {group_id} 历史消息拉取完成: {count} 条")
                except Exception as e:
                    logger.error(f"群 {group_id} 历史消息拉取失败: {e}")

            logger.info(f"所有群历史消息拉取完成（本轮扫过 {added_total} 条）")
            if self._running:
                
                
                try:
                    days = getattr(self, "_export_rebuild_days", 3)
                    if days and days > 0:
                        self.exporter.export_recent_from_store(self.store, days=days)
                except Exception as exc:  
                    logger.warning(f"历史补齐后重排导出失败: {exc}")
                
                self.diary_keeper.start()
            if self.compliance.get_pending_count() > 0:
                self._run_ai_review_once("启动历史消息")

        def fetch_then_start_diary():
            try:
                fetch_task()
            finally:
                
                if self._running:
                    self.diary_keeper.start()

        thread = threading.Thread(target=fetch_then_start_diary, daemon=True, name="HistoryFetcher")
        thread.start()

    def stop(self) -> None:
        """QQ bot stack component."""
        self._running = False
        logger.info("正在停止监控系统...")

        if getattr(self, "diary_keeper", None) is not None:
            self.diary_keeper.stop()

        self.onebot.stop()
        self.store.flush()

        logger.info("监控系统已停止")


def main():
    """QQ bot stack component."""
    import argparse

    parser = argparse.ArgumentParser(description="QQ群聊监控系统")
    parser.add_argument(
        "-c", "--config",
        default="config/config.json",
        help="配置文件路径 (默认: config/config.json)"
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8080,
        help="Web面板端口 (默认: 8080)"
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="发送测试告警"
    )

    args = parser.parse_args()

    
    config_path = args.config
    if not os.path.isabs(config_path):
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, config_path)

    if not os.path.exists(config_path):
        print(f"错误: 配置文件不存在: {config_path}")
        print(f"请复制 config/config.example.json 为 config/config.json 并修改配置")
        sys.exit(1)

    
    monitor = QQMonitor(config_path)

    if args.web_port != 8080:
        monitor.web_panel.port = args.web_port

    if args.test_alert:
        monitor.alert.send_test_alert()
        print("测试告警已发送")
        sys.exit(0)

    
    def signal_handler(sig, frame):
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    
    
    
    
    def _dialog_watch_loop():
        import ctypes
        import ctypes.wintypes as _wt
        import subprocess as _sp
        u = ctypes.windll.user32
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, _wt.HWND, _wt.LPARAM)
        log_p = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "dialog_watcher.log")
        with open(log_p, "a", encoding="utf-8") as f:
            f.write(f"=== dialog_watcher 线程启动 {time.strftime('%m-%d %H:%M:%S')} ===\n")
        seen = {}
        pmap = {}

        def _pids():
            out = _sp.run(["tasklist", "/FO", "CSV"], capture_output=True,
                          text=True, encoding="gbk", errors="ignore",
                          creationflags=_sp.CREATE_NO_WINDOW, timeout=5).stdout or ""
            m = {}
            for line in out.splitlines()[1:]:
                parts = [x.strip('"') for x in line.split('","')]
                if len(parts) >= 2:
                    try:
                        m[int(parts[1])] = parts[0]
                    except ValueError:
                        pass
            return m

        def _scan():
            found = {}

            def cb(hwnd, lp):
                cls = ctypes.create_unicode_buffer(256)
                u.GetClassNameW(hwnd, cls, 256)
                if cls.value == "#32770":
                    pid = _wt.DWORD()
                    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    found[int(pid.value)] = hwnd
                return True

            u.EnumWindows(CB(cb), 0)
            return found

        while True:
            try:
                cur = _scan()
                gone = set(seen) - set(cur)
                if gone:
                    with open(log_p, "a", encoding="utf-8") as f:
                        for pid in gone:
                            f.write(f"{time.strftime('%m-%d %H:%M:%S')} 消失 "
                                    f"pid={pid} 进程={pmap.get(pid, '?')}\n")
                    seen = {k: v for k, v in seen.items() if k in cur}
                new = {k: v for k, v in cur.items() if k not in seen}
                if new:
                    pmap = _pids()
                    with open(log_p, "a", encoding="utf-8") as f:
                        for pid, hwnd in new.items():
                            title = ctypes.create_unicode_buffer(512)
                            u.GetWindowTextW(hwnd, title, 512)
                            f.write(f"{time.strftime('%m-%d %H:%M:%S')} ★新对话框 "
                                    f"pid={pid} 进程={pmap.get(pid, '?')} "
                                    f"可见={bool(u.IsWindowVisible(hwnd))} "
                                    f"标题={title.value[:80]!r}\n")
                    seen.update(new)
            except Exception:                         
                pass
            time.sleep(0.5)

    
    if os.environ.get("QQBOT_DIALOG_WATCHER", "0") == "1":
        threading.Thread(target=_dialog_watch_loop, daemon=True,
                         name="DialogWatcher").start()

    
    
    
    def _audio_watch_loop():
        log_p = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "audio_watcher.log")
        try:
            from pycaw.pycaw import AudioUtilities
        except Exception as e:                             
            with open(log_p, "a", encoding="utf-8") as f:
                f.write(f"=== audio_watcher 无法导入 pycaw: {e} ===\n")
            return
        from pycaw.pycaw import IAudioMeterInformation
        last_logged = {}        
        THRESH = 0.02           
        with open(log_p, "a", encoding="utf-8") as f:
            f.write(f"=== audio_watcher 线程启动（峰值监听） "
                    f"{time.strftime('%m-%d %H:%M:%S')} ===\n")
        while True:
            try:
                for sess in AudioUtilities.GetAllSessions():
                    if sess.Process is None:
                        continue
                    try:
                        meter = sess._ctl.QueryInterface(IAudioMeterInformation)
                        peak = float(meter.GetPeakValue())
                    except Exception:                       
                        continue
                    if peak <= THRESH:
                        continue
                    name = sess.Process.name()
                    now = time.time()
                    if now - last_logged.get(name, 0) < 2.0:
                        continue                             
                    last_logged[name] = now
                    with open(log_p, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%m-%d %H:%M:%S')} 🔊出声 "
                                f"{name} pid={sess.Process.pid} peak={peak:.3f}\n")
            except Exception:                               
                pass
            time.sleep(0.15)

    if os.environ.get("QQBOT_AUDIO_WATCHER", "0") == "1":
        threading.Thread(target=_audio_watch_loop, daemon=True,
                         name="AudioWatcher").start()

    
    
    
    
    
    
    
    def _snowluma_hook_watch_loop():
        import socket
        import subprocess

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.abspath(os.path.join(
            base_dir, "..", "panel", "tools", "snowluma_autohook.ps1"))
        check_every = 60          
        retry_every = 120         
        boot_grace = 180          

        time.sleep(boot_grace)
        while True:
            try:
                if not os.path.exists(script):
                    logger.warning("[SnowLuma看守] 找不到 %s，看守不启用", script)
                    return
                s = socket.socket()
                s.settimeout(1.5)
                listening = (s.connect_ex(("127.0.0.1", 3001)) == 0)
                s.close()
                if listening:
                    time.sleep(check_every)
                    continue
                
                logger.info("[SnowLuma看守] OneBot(3001) 没在监听，尝试自动重新注入")
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-WindowStyle", "Hidden", "-File", script, "-Quiet"],
                    capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="ignore",
                )
                tail = (proc.stdout or "").strip().splitlines()
                if proc.returncode == 0:
                    logger.info("[SnowLuma看守] 重新注入成功：%s",
                                tail[-1] if tail else "(无输出)")
                    time.sleep(check_every)
                else:
                    logger.warning("[SnowLuma看守] 这次没成功（退出码 %s）：%s",
                                   proc.returncode,
                                   tail[-1] if tail else "(无输出)")
                    time.sleep(retry_every)
            except Exception as exc:                   
                logger.warning("[SnowLuma看守] 本轮异常：%s", type(exc).__name__)
                time.sleep(retry_every)

    if os.environ.get("QQBOT_SNOWLUMA_WATCHDOG", "0") == "1":
        threading.Thread(target=_snowluma_hook_watch_loop, daemon=True,
                         name="SnowLumaHookWatchdog").start()
        logger.info("[SnowLuma看守] 已启动（每 60 秒看一次 OneBot:3001）")
    monitor.start()



if __name__ == "__main__":
    main()
