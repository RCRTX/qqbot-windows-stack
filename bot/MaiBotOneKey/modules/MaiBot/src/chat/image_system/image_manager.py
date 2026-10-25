import asyncio
import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from rich.traceback import install
from sqlmodel import select

from src.common.data_models.image_data_model import MaiImage
from src.common.data_models.llm_service_data_models import LLMGenerationOptions
from src.common.database.database import get_db_session
from src.common.database.database_model import Images, ImageType
from src.common.logger import get_logger
from src.common.i18n import get_locale
from src.common.utils.image_path import resolve_stored_image_path, serialize_stored_image_path
from src.common.utils.utils_image import ImageUtils
from src.chat.image_system.character_reference import append_image_correction, image_corrections_fingerprint, load_character_reference
from src.config.config import config_manager
from src.llm_models.llm_priority import with_llm_low_priority
from src.llm_models.payload_content.context_item import ContextItemBuilder
from src.llm_models.utils_model import pending_model_cancellations_count
from src.prompt.prompt_manager import prompt_manager
from src.services.llm_service import LLMServiceClient

install(extra_lines=3)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.absolute().resolve()
DATA_DIR = PROJECT_ROOT / "data"
IMAGE_DIR = DATA_DIR / "images"
DESCRIPTION_VERSION_DIR = DATA_DIR / "image_description_versions"
SEMANTIC_ASSOCIATION_TIMEOUT = 6.0
SEMANTIC_ASSOCIATION_TOTAL_TIMEOUT = 20.0
SEMANTIC_ASSOCIATION_SIGNAL = re.compile(
    r"反差|矛盾|冲突|双关|讽刺|荒诞|反常|夸张|违背|不可能|隐喻|耸动|错愕|调侃|暗示|话外|指代|暧昧|玩笑|梗|"
    r"absurd|surreal|satir|ironi|contrast|contradict|incongruous|double.meaning|\bpun\b|\bmeme\b|anomal|paradox|teas|innuendo|allusion|"
    r"皮肉|風刺|不条理|ダブルミーニング|ありえない|比喩|含み|からかい|ほのめか", re.IGNORECASE
)
SEMANTIC_ASSOCIATION_TEXT_SIGNAL = re.compile(
    r"[“「『\"][^”」』\"\n]{2,}[”」』\"]|文字|台词|写着|文案|标语|字幕|"
    r"\btext\b|\bcaption\b|\breads\b|\bwritten\b|\bdialogue\b|セリフ|書かれ|書いて", re.IGNORECASE
)
SEMANTIC_ASSOCIATION_NO_TEXT = re.compile(
    r"(?:没有|无|不含|未见)(?:任何|可见|明显的?)?(?:文字|台词|文案|字幕)|"
    r"\b(?:no|without)(?:\s+(?:any|visible|readable))?\s+(?:text|caption|writing)\b|"
    r"文字(?:は|が)(?:見当たらない|ない|ありません)", re.IGNORECASE
)

logger = get_logger("image")


def _ensure_image_dir_exists() -> None:
    """确保图片缓存目录存在。"""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def _is_vlm_task_configured() -> bool:
    """判断是否配置了可用于图片识别的视觉模型任务。"""

    try:
        vlm_models = config_manager.get_model_config().model_task_config.vlm.model_list
        return any(str(model_name).strip() for model_name in vlm_models)
    except Exception as exc:
        logger.warning(f"读取 VLM 模型配置失败，跳过图片识别: {exc}")
        return False


vlm = LLMServiceClient(task_name="vlm", request_type="image")
image_semantics = LLMServiceClient(task_name="utils", request_type="image.semantic_association")


class ImageManager:
    """图片描述管理器。"""

    def __init__(self) -> None:
        """初始化图片管理器。"""
        _ensure_image_dir_exists()
        self._pending_description_tasks: Dict[str, asyncio.Task[None]] = {}
        self._description_build_tasks: Dict[str, asyncio.Task[MaiImage]] = {}
        self._description_slots = asyncio.Semaphore(2)
        self._description_version_lock = Lock()
        self._unsaved_description_versions: Dict[str, str] = {}
        self._description_retry_after: Dict[str, float] = {}
        self._semantic_tasks: set[asyncio.Task] = set()
        self._semantic_tail_tasks: set[asyncio.Task] = set()
        self._semantic_by_hash: Dict[str, tuple[str, asyncio.Task]] = {}
        self._description_generations: Dict[str, int] = {}
        self.cleanup_legacy_image_registration_records()

        logger.info("图片管理器初始化完成")

    def _description_fingerprint(self) -> str:
        """实际语言、模板及视觉模型设置共同决定识图版本，不把元数据混进描述。"""
        task = config_manager.get_model_config().model_task_config.vlm
        models = {model.name: model for model in config_manager.get_model_config().models}
        reference = load_character_reference()
        payload = {
            "image_corrections": image_corrections_fingerprint(),
            "character_reference": reference.sha256 if reference else None,
            "locale": get_locale(),
            "template": prompt_manager.get_prompt("image_description").template,
            "max_tokens": task.max_tokens,
            "models": [(name, models[name].model_identifier) for name in task.model_list if name in models],
            "semantic_version": "image-mechanism-association-v4",
            "semantic_signals": SEMANTIC_ASSOCIATION_SIGNAL.pattern,
            "semantic_text_signals": SEMANTIC_ASSOCIATION_TEXT_SIGNAL.pattern,
            "semantic_no_text": SEMANTIC_ASSOCIATION_NO_TEXT.pattern,
            "semantic_template": prompt_manager.get_prompt("image_semantic_association").template,
            "semantic_models": [
                (name, models[name].model_identifier)
                for name in config_manager.get_model_config().model_task_config.utils.model_list if name in models
            ],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _description_version_path(self, image_hash: str) -> Path:
        # 对调用方传入的 hash 再摘要，避免将任意字符串解释成路径。
        key = hashlib.sha256(image_hash.encode("utf-8")).hexdigest()
        return DESCRIPTION_VERSION_DIR / f"{key}.sha256"

    def _description_is_current(self, image_hash: str, fingerprint: str | None = None) -> bool:
        try:
            current = fingerprint or self._description_fingerprint()
            with self._description_version_lock:
                if self._unsaved_description_versions.get(image_hash) == current:
                    return True
                return self._description_version_path(image_hash).read_text(encoding="ascii").strip() == current
        except (OSError, ValueError, UnicodeError):
            return False

    def _mark_description_version(self, image_hash: str, fingerprint: str) -> None:
        try:
            with self._description_version_lock:
                path = self._description_version_path(image_hash)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                with temporary.open("w", encoding="ascii") as stream:
                    stream.write(fingerprint + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                self._unsaved_description_versions.pop(image_hash, None)
        except OSError as exc:
            # 版本索引失败不能使已经保存成功的有效描述失效。
            with self._description_version_lock:
                self._unsaved_description_versions[image_hash] = fingerprint
            logger.warning(f"图片描述已保存，但版本标记写入失败: {image_hash}: {exc}")

    def _get_image_record(self, image_hash: str) -> Optional[Images]:
        """根据哈希获取图片记录。"""
        with get_db_session() as session:
            statement = select(Images).filter_by(image_hash=image_hash, image_type=ImageType.IMAGE).limit(1)
            record = session.exec(statement).first()
            if record is not None:
                # 返回会话外使用的只读记录，避免在会话关闭后触发属性刷新。
                session.expunge(record)
            return record

    def _normalize_image_registration_fields(self, record: Images) -> bool:
        """Normalize accidental emoji registration fields on image records."""
        if record.image_type != ImageType.IMAGE:
            return False
        if not record.is_registered and record.register_time is None:
            return False

        record.is_registered = False
        record.register_time = None
        return True

    async def get_image_description(
        self,
        *,
        image_hash: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        wait_for_build: bool = True,
    ) -> str:
        """
        获取图片描述的封装方法

        如果图片已存在于数据库中，则直接返回描述

        如果不存在，则**保存图片**并**生成描述**后返回

        Args:
            image_hash (Optional[str]): 图片的哈希值，如果提供则优先使用该
            image_bytes (Optional[bytes]): 图片的字节数据，如果提供则在数据库中找不到哈希值时使用该数据生成描述
            wait_for_build (bool): 未命中缓存时是否同步等待描述构建完成
        Returns:
            return (str): 图片描述，如果发生错误或无法生成描述则返回空字符串
        Raises:
            ValueError: 如果未提供有效的图片哈希值或图片字节数据
            Exception: 在查询数据库、保存图片或生成描述过程中发生的其他异常
        """
        if image_hash:
            hash_str = image_hash
        elif not image_bytes:
            raise ValueError("必须提供图片哈希值或图片字节数据")
        else:
            hash_str = hashlib.sha256(image_bytes).hexdigest()

        try:
            if record := self._get_image_record(hash_str):
                if record.vlm_processed and record.description:
                    try:
                        if not self._description_is_current(hash_str):
                            cached_bytes = image_bytes
                            if not cached_bytes and not record.no_file_flag:
                                path = resolve_stored_image_path(record.full_path)
                                if path.is_file():
                                    cached_bytes = path.read_bytes()
                            if cached_bytes:
                                self._schedule_description_build(
                                    hash_str, cached_bytes, saved_image=MaiImage.from_db_instance(record)
                                )
                    except Exception as exc:
                        logger.warning(f"旧图片描述继续可用，后台刷新调度失败: {hash_str}: {exc}")
                    return append_image_correction(hash_str, record.description)
        except Exception as e:
            logger.error(f"查询图片描述时发生错误: {e}")

        if not image_bytes:
            logger.warning("图片哈希值未找到，且未提供图片字节数据，返回无描述")
            return ""
        try:
            saved_image = await self.ensure_image_saved(image_bytes)
        except Exception as e:
            logger.error(f"保存图片文件时发生错误: {e}")
            return ""
        if not _is_vlm_task_configured():
            logger.info("未配置 VLM 模型，跳过图片识别")
            return ""
        if not wait_for_build:
            self._schedule_description_build(hash_str, image_bytes, saved_image=saved_image)
            return ""
        logger.info(f"图片描述未找到，哈希值: {hash_str}，准备生成新描述")
        try:
            image = await self.build_image_description(image_bytes, saved_image=saved_image)
            return append_image_correction(hash_str, image.description)
        except Exception as e:
            logger.error(f"生成图片描述时发生错误: {e}")
            return ""

    def _schedule_description_build(
        self,
        image_hash: str,
        image_bytes: bytes,
        *,
        saved_image: Optional[MaiImage] = None,
    ) -> None:
        """调度图片描述后台构建任务。

        Args:
            image_hash: 图片哈希值。
            image_bytes: 图片字节数据。
            saved_image: 已保存的图片对象，避免后台任务重复执行保存流程。
        """
        if not _is_vlm_task_configured():
            logger.info("未配置 VLM 模型，跳过图片后台识别任务")
            return

        if image_hash in self._pending_description_tasks:
            return
        if image_hash in self._description_build_tasks:
            return
        if time.monotonic() < self._description_retry_after.get(image_hash, 0.0):
            return
        # 只刷新被访问的图片；队列满时保留旧描述，后续访问仍可重试。
        if len(self._pending_description_tasks) >= 8:
            return

        task = asyncio.create_task(
            self._build_description_in_background(image_hash, image_bytes, saved_image=saved_image)
        )
        self._pending_description_tasks[image_hash] = task
        task.add_done_callback(lambda finished_task: self._finalize_description_build(image_hash, finished_task))

    @with_llm_low_priority
    async def _build_description_in_background(
        self,
        image_hash: str,
        image_bytes: bytes,
        *,
        saved_image: Optional[MaiImage] = None,
    ) -> None:
        """在后台构建并缓存图片描述。

        Args:
            image_hash: 图片哈希值。
            image_bytes: 图片字节数据。
            saved_image: 已保存的图片对象，避免重复查询和更新访问计数。
        """
        try:
            logger.debug(f"图片描述后台构建已开始，哈希值: {image_hash}")
            await self.build_image_description(image_bytes, saved_image=saved_image)
            logger.debug(f"图片描述后台构建完成，哈希值: {image_hash}")
        except Exception as exc:
            self._description_retry_after[image_hash] = time.monotonic() + 30.0
            logger.warning(f"图片描述后台构建失败，哈希值: {image_hash}，错误: {exc}")

    def _finalize_description_build(self, image_hash: str, task: asyncio.Task[None]) -> None:
        """回收图片描述后台构建任务。

        Args:
            image_hash: 图片哈希值。
            task: 已完成的后台任务。
        """
        self._pending_description_tasks.pop(image_hash, None)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            logger.debug(f"图片描述后台任务结束时捕获异常，哈希值: {image_hash}，错误: {exc}")
            return

        try:
            from src.maisaka.visual.chat_history_refresher import log_tracked_image_recognition_completed

            log_tracked_image_recognition_completed(image_hash)
        except Exception as exc:
            logger.debug(f"通知 MaiSaka 图片识别完成状态失败，image_hash={image_hash}: {exc}")

    def get_image_from_db(self, image_hash: str) -> Optional[MaiImage]:
        """
        从数据库中根据图片哈希值获取图片记录

        """
        with get_db_session() as session:
            statement = select(Images).filter_by(image_hash=image_hash, image_type=ImageType.IMAGE).limit(1)
            if record := session.exec(statement).first():
                if record.no_file_flag:
                    logger.warning(f"数据库记录标记为文件不存在，哈希值: {image_hash}")
                    return None
                image = MaiImage.from_db_instance(record)
                image.description = append_image_correction(image_hash, image.description)
                return image
            logger.info(f"未找到哈希值为 {image_hash} 的图片记录")
            return None

    def register_image_to_db(self, image: MaiImage) -> bool:
        """
        将图片对象注册到数据库中
        Args:
            image (MaiImage): 包含图片信息的 MaiImage 对象，必须包含有效的 full_path 和 image_format
        Returns:
            return (bool): 注册成功返回 True，失败返回 False
        """
        # sourcery skip: extract-method
        if not image or not isinstance(image, MaiImage):
            logger.error("无效的图片对象，无法注册到数据库")
            return False
        if not image.full_path.exists():
            logger.error(f"图片文件不存在，无法注册到数据库: {image.full_path}")
            return False

        try:
            with get_db_session() as session:
                record = image.to_db_instance()
                record.is_registered = False
                record.register_time = None
                record.last_used_time = datetime.now()
                session.add(record)
                session.flush()  # 确保记录被写入数据库以获取ID
                record_id = record.id
                logger.debug(f"保存图片: ID: {record_id}，路径: {record.full_path}")
        except Exception as e:
            logger.error(f"保存图片记录到数据库时发生错误: {e}")
            return False
        return True

    def update_image_description(self, image: MaiImage) -> bool:
        """
        更新图片描述

        Args:
            image (MaiImage): 包含新描述的图片对象，必须包含有效的 file_hash 和 full_path
        Returns:
            return (bool): 更新成功返回 True，失败返回 False
        """
        try:
            with get_db_session() as session:
                statement = select(Images).filter_by(image_hash=image.file_hash, image_type=ImageType.IMAGE).limit(1)
                record = session.exec(statement).first()
                if not record:
                    logger.error(f"未找到哈希值为 {image.file_hash} 的图片记录，无法更新描述")
                    return False
                self._normalize_image_registration_fields(record)
                record.description = image.description
                record.last_used_time = datetime.now()
                record.vlm_processed = image.vlm_processed
                session.add(record)
                logger.info(f"理解图片: {image.description}")
        except Exception as e:
            logger.error(f"更新图片描述时发生错误: {e}")
            return False
        return True

    def delete_image(self, image: MaiImage) -> bool:
        """
        删除图片记录和对应的文件

        Args:
            image (MaiImage): 包含要删除图片信息的对象，必须包含有效的 file_hash 和 full_path
        Returns:
            return (bool): 删除成功返回 True，失败返回 False
        """
        try:
            with get_db_session() as session:
                statement = select(Images).filter_by(image_hash=image.file_hash, image_type=ImageType.IMAGE).limit(1)
                record = session.exec(statement).first()
                if not record:
                    logger.error(f"未找到哈希值为 {image.file_hash} 的图片记录，无法删除")
                    return False
                session.delete(record)
                logger.info(f"成功删除图片记录: {image.file_hash}")

            if image.full_path.exists():
                image.full_path.unlink()
                logger.info(f"成功删除图片文件: {image.full_path}")
            else:
                logger.warning(f"图片文件不存在，无法删除: {image.full_path}")
        except Exception as e:
            logger.error(f"删除图片时发生错误: {e}")
            if image.full_path.exists():
                logger.warning(f"图片文件未被删除: {image.full_path}")
            return False
        return True

    async def ensure_image_saved(self, image_bytes: bytes) -> MaiImage:
        """先保存图片记录，确保后续可以按哈希回填图片内容。"""
        hash_str = hashlib.sha256(image_bytes).hexdigest()

        try:
            with get_db_session() as session:
                statement = select(Images).filter_by(image_hash=hash_str, image_type=ImageType.IMAGE).limit(1)
                if record := session.exec(statement).first():
                    self._normalize_image_registration_fields(record)
                    record_path = resolve_stored_image_path(record.full_path)
                    if not record.no_file_flag and record_path.is_file():
                        logger.info(f"图片已存在于数据库中，哈希值: {hash_str}")
                        record.last_used_time = datetime.now()
                        record.query_count += 1
                        session.add(record)
                        session.flush()
                        return MaiImage.from_db_instance(record)
                    logger.info(f"图片记录存在但文件缺失，准备重新保存图片文件，哈希值: {hash_str}")
        except Exception as e:
            logger.error(f"查询图片记录时发生错误: {e}")
            raise e

        logger.debug(f"图片不存在或文件缺失，准备保存图片文件，哈希值: {hash_str}")
        tmp_file_path = IMAGE_DIR / f"{hash_str}.tmp"
        with tmp_file_path.open("wb") as f:
            f.write(image_bytes)
        mai_image = MaiImage(full_path=tmp_file_path, image_bytes=image_bytes)
        await mai_image.calculate_hash_format()
        if not self._upsert_saved_image_record(mai_image):
            raise RuntimeError(f"保存图片记录到数据库失败: {hash_str}")
        return mai_image

    def _upsert_saved_image_record(self, image: MaiImage) -> bool:
        """保存图片记录，或在文件被清理后恢复同 hash 记录的文件状态。"""
        try:
            with get_db_session() as session:
                statement = select(Images).filter_by(image_hash=image.file_hash, image_type=ImageType.IMAGE).limit(1)
                record = session.exec(statement).first()
                if record is None:
                    record = image.to_db_instance()
                    record.is_registered = False
                    record.register_time = None
                    record.query_count = 0
                else:
                    self._normalize_image_registration_fields(record)
                    image.description = record.description
                    image.vlm_processed = record.vlm_processed
                    record.full_path = serialize_stored_image_path(image.full_path)

                record.no_file_flag = False
                record.last_used_time = datetime.now()
                session.add(record)
                session.flush()
                logger.info(f"保存图片: ID: {record.id}，路径: {record.full_path}")
        except Exception as e:
            logger.error(f"保存图片记录到数据库时发生错误: {e}")
            return False
        return True

    async def build_image_description(
        self,
        image_bytes: bytes,
        *,
        saved_image: Optional[MaiImage] = None,
        force_refresh: bool = False,
    ) -> MaiImage:
        """在图片已保存的前提下生成或补齐图片描述。"""
        mai_image = saved_image or await self.ensure_image_saved(image_bytes)
        if not mai_image.image_format:
            await mai_image.calculate_hash_format()
        fingerprint = self._description_fingerprint()
        semantic_pending = self._semantic_by_hash.get(mai_image.file_hash)
        if semantic_pending and semantic_pending[0] == fingerprint and not semantic_pending[1].done():
            mai_image.description = append_image_correction(mai_image.file_hash, mai_image.description)
            return mai_image
        if not force_refresh and mai_image.vlm_processed and mai_image.description and self._description_is_current(mai_image.file_hash, fingerprint):
            mai_image.description = append_image_correction(mai_image.file_hash, mai_image.description)
            return mai_image
        if not _is_vlm_task_configured():
            logger.info(f"未配置 VLM 模型，跳过图片识别: {mai_image.file_hash}")
            return mai_image

        image_hash = mai_image.file_hash
        task = self._description_build_tasks.get(image_hash)
        if task is None:
            task = asyncio.create_task(self._build_versioned_description(image_bytes, mai_image, fingerprint))
            self._description_build_tasks[image_hash] = task
            task.add_done_callback(lambda finished: self._finalize_shared_description_build(image_hash, finished))
        # 单个等待者取消不取消同 hash 其他调用者和后台刷新共享的工作。
        result = await asyncio.shield(task)
        result.description = append_image_correction(result.file_hash, result.description)
        return result

    def _finalize_shared_description_build(self, image_hash: str, task: asyncio.Task[MaiImage]) -> None:
        if self._description_build_tasks.get(image_hash) is task:
            self._description_build_tasks.pop(image_hash, None)
        if not task.cancelled():
            task.exception()

    async def _build_versioned_description(self, image_bytes: bytes, image: MaiImage, fingerprint: str) -> MaiImage:
        async with self._description_slots:
            generation = self._description_generations.get(image.file_hash, 0) + 1
            self._description_generations[image.file_hash] = generation
            desc = (await self._generate_image_description(image_bytes, image.image_format)).strip()
            if not desc:
                raise RuntimeError(f"识图返回空描述，保留已有缓存: {image.file_hash}")
            old_description, old_processed = image.description, image.vlm_processed
            image.description, image.vlm_processed = desc, True
            if not self.update_image_description(image):
                image.description, image.vlm_processed = old_description, old_processed
                raise RuntimeError(f"更新图片描述失败: {image.file_hash}")
            # 基础描述先落库可读；可选关联最多额外等六秒，失败不损失图中原始信息。
            enriched = await self._supplement_image_semantics(
                desc, context=(image.file_hash, fingerprint, generation)
            )
            if enriched != desc:
                image.description = enriched
                if not self.update_image_description(image):
                    image.description = desc
            self._mark_description_version(image.file_hash, fingerprint)
            self._description_retry_after.pop(image.file_hash, None)
            return image

    def _consume_semantic_task(self, task: asyncio.Task, image_hash: str = "") -> None:
        self._semantic_tasks.discard(task)
        pending = self._semantic_by_hash.get(image_hash)
        if pending and pending[1] is task:
            self._semantic_by_hash.pop(image_hash, None)
        if not task.cancelled():
            task.exception()

    @with_llm_low_priority
    async def _request_semantic_association(self, description: str):
        template = prompt_manager.get_prompt("image_semantic_association")
        prompt = await prompt_manager.render_prompt(template)
        prompt += "\n<image-description-data>\n" + json.dumps(
            {"image_description": description}, ensure_ascii=False
        ) + "\n</image-description-data>"
        return await image_semantics.generate_response(
            prompt, options=LLMGenerationOptions(max_tokens=320, raise_when_empty=False)
        )

    def _parse_semantic_association(self, description: str, result) -> str:
        payload = json.loads((result.response or "").strip())
        if not isinstance(payload, dict) or payload.get("confidence") != "high":
            logger.debug("图片语义补充未采用: 非高置信度结果")
            return description
        kind, relation = payload.get("kind"), payload.get("salient_relation")
        if kind not in ("cultural_reference", "wordplay") or not isinstance(relation, str) or not relation.strip():
            logger.debug("图片语义补充未采用: 缺少有效类型或关键关系")
            return description
        relation_type = payload.get("relation_type")
        if relation_type not in ("rule", "image_text") or (relation_type == "rule" and kind == "wordplay"):
            logger.debug("图片语义补充未采用: 关系类型缺失或规则被当成双关")
            return description
        association, mechanism = payload.get("association"), payload.get("shared_mechanism")
        if not isinstance(association, str) or not isinstance(mechanism, str):
            return description
        association, mechanism = association.strip(), mechanism.strip()
        if not association or not mechanism or len(association) > 160 or len(mechanism) > 240 or len(relation) > 240:
            logger.debug("图片语义补充未采用: 关联/共同点为空或超长")
            return description
        label = {"en-US": "Possible association (inference, not visible text)",
                 "ja-JP": "可能な連想（推測であり画像内の原文ではない）"}.get(
                     get_locale(), "可能联想（推测，并非图中原文）")
        return description + f"\n【{label}】{association}；{relation.strip()}；{mechanism}"

    def _consume_semantic_tail(self, task: asyncio.Task) -> None:
        self._semantic_tail_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _finish_semantic_in_background(
        self, task: asyncio.Task, description: str, context: tuple[str, str, int] | None, deadline: float
    ) -> None:
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0.0, deadline - time.monotonic()))
            if task not in done:
                task.cancel()
                logger.debug("图片语义补充超总预算20秒，保留基础描述并取消原请求")
                return
            enriched = self._parse_semantic_association(description, task.result())
            if enriched == description or context is None:
                return
            image_hash, fingerprint, generation = context
            if (
                self._description_generations.get(image_hash) != generation
                or self._description_fingerprint() != fingerprint
                or not self._description_is_current(image_hash, fingerprint)
            ):
                logger.debug(f"图片语义尾段版本已过期，拒绝回写: {image_hash}")
                return
            record = self._get_image_record(image_hash)
            if record is None or not record.vlm_processed or record.description != description:
                logger.debug(f"图片语义尾段基础描述已变化，拒绝回写: {image_hash}")
                return
            image = MaiImage.from_db_instance(record)
            image.description = enriched
            if self.update_image_description(image):
                self._mark_description_version(image_hash, fingerprint)
                logger.debug(f"图片语义后台尾段已更新同版本缓存: {image_hash}")
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            raise
        except Exception as exc:
            logger.debug(f"图片语义后台未采用，保留基础描述: {type(exc).__name__}")

    async def _supplement_image_semantics(
        self, description: str, *, context: tuple[str, str, int] | None = None
    ) -> str:
        if not (
            SEMANTIC_ASSOCIATION_SIGNAL.search(description)
            or SEMANTIC_ASSOCIATION_TEXT_SIGNAL.search(SEMANTIC_ASSOCIATION_NO_TEXT.sub("", description))
        ):
            return description
        if len(self._semantic_tasks) + pending_model_cancellations_count() >= 2:
            logger.debug("图片语义补充让路: 在途/未退出取消请求已达2个")
            return description
        task = None
        try:
            deadline = time.monotonic() + SEMANTIC_ASSOCIATION_TOTAL_TIMEOUT
            # 从登记到添加任务之间不 await，避免并发渲染模板时绕过在途上限。
            task = asyncio.create_task(self._request_semantic_association(description))
            self._semantic_tasks.add(task)
            image_hash = context[0] if context else ""
            if context:
                self._semantic_by_hash[image_hash] = (context[1], task)
            task.add_done_callback(lambda finished: self._consume_semantic_task(finished, image_hash))
            done, _ = await asyncio.wait({task}, timeout=SEMANTIC_ASSOCIATION_TIMEOUT)
            if task not in done:
                # 前台六秒结束等待；同一个请求继续到总二十秒，不重新请求模型。
                logger.debug("图片语义补充超过前台6秒，基础描述先用，原请求交后台尾段")
                tail = asyncio.create_task(self._finish_semantic_in_background(task, description, context, deadline))
                self._semantic_tail_tasks.add(tail)
                tail.add_done_callback(self._consume_semantic_tail)
                return description
            return self._parse_semantic_association(description, task.result())
        except asyncio.CancelledError:
            if task is not None and not task.done():
                task.cancel()
            raise
        except Exception as exc:
            logger.debug(f"图片语义关联未采用，保留基础描述: {type(exc).__name__}")
            return description

    async def save_image_and_process(self, image_bytes: bytes) -> MaiImage:
        """
        保存图片并生成描述

        Args:
            image_bytes (bytes): 图片的字节数据
        Returns:
            return (MaiImage): 包含图片信息的 MaiImage 对象
        Raises:
            Exception: 如果在保存或处理过程中发生错误
        """
        return await self.build_image_description(image_bytes)

    def cleanup_invalid_descriptions_in_db(self):
        """
        清理数据库中无效的图片记录

        无效的判定：`description` 为空或仅包含空白字符，或者文件路径不存在
        """
        invalid_values = {"", None}
        invalid_counter: int = 0
        null_path_counter: int = 0
        logger.info("开始清理数据库中无效的图片记录...")

        try:
            with get_db_session() as session:
                for record in session.exec(select(Images)).yield_per(100):
                    if record.description in invalid_values:
                        if record.full_path and resolve_stored_image_path(record.full_path).exists():
                            try:
                                resolve_stored_image_path(record.full_path).unlink()
                                logger.info(f"已删除无效描述的图片文件: {record.full_path}")
                            except Exception as e:
                                logger.error(f"删除无效描述的图片文件时发生错误: {e}")
                        session.delete(record)
                        invalid_counter += 1
                    elif record.full_path and not resolve_stored_image_path(record.full_path).exists():
                        session.delete(record)
                        null_path_counter += 1
        except Exception as e:
            logger.error(f"清理数据库中无效图片记录时发生错误: {e}")

        logger.info(f"清理完成: {invalid_counter} 条无效描述记录，{null_path_counter} 条文件路径不存在记录")

    def cleanup_legacy_image_registration_records(self) -> None:
        """Clean up legacy image records with mistaken registration fields."""
        fixed_counter = 0
        try:
            with get_db_session() as session:
                statement = select(Images).filter_by(image_type=ImageType.IMAGE)
                for record in session.exec(statement).yield_per(100):
                    if not self._normalize_image_registration_fields(record):
                        continue
                    session.add(record)
                    fixed_counter += 1
        except Exception as e:
            logger.error(f"Failed to clean image registration state: {e}")
            return

        if fixed_counter:
            logger.info(f"Cleaned mistaken registration state on {fixed_counter} image records")

    async def _generate_image_description(self, image_bytes: bytes, image_format: str) -> str:
        prompt_template = prompt_manager.get_prompt("image_description")
        prompt = await prompt_manager.render_prompt(prompt_template)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        reference = load_character_reference()
        if reference is None:
            generation_result = await vlm.generate_response_for_image(prompt, image_base64, image_format)
        else:
            # 两张图在同一次请求中明确分工，参考自身不能成为当前图片的事实。
            target_base64, target_format, _ = ImageUtils.normalize_image_base64_for_model(image_base64, image_format)
            reference_base64 = base64.b64encode(reference.image_bytes).decode("utf-8")

            def context_factory(client):
                builder = ContextItemBuilder().add_text_content(prompt + "\nIMAGE 1: TARGET / 待描述原图")
                builder.add_image_content(target_format, target_base64, client.get_support_image_formats())
                builder.add_text_content(
                    "IMAGE 2: REFERENCE ONLY / 用户明确指定的机器人自身角色参考，不是当前场景。"
                    "Compare identity only; never copy its clothing, pose or scenery into IMAGE 1."
                )
                builder.add_image_content(reference.image_format, reference_base64, client.get_support_image_formats())
                return [builder.build()]

            generation_result = await vlm.generate_response_with_context(context_factory)
        description = generation_result.response
        if not description:
            logger.warning("VLM未能生成图片描述")
        return description or ""


image_manager = ImageManager()
